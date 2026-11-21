"""Submission service: call the agent synchronously, validate in code, then initialize the workflow."""
import logging
import re

from decimal import Decimal, InvalidOperation

from mock_data import POLICY_VERSION, find_employee_id_by_name, get_employee, get_policy_rule
from tools._shared import normalize
from tools.approval_policy import COST_PATTERN
from .store import create_workflow, find_duplicate_request, lock, next_request_id
from .validation import requester_id_from, validate_agent_result
from .workflow_tools import add_history, notify_approver

from common import invoke_agent
from policy.retrieval import PolicyRetrievalError, retrieve_approval_policy
from tools import create_budget_release_request, lookup_requester_manager, lookup_role_holder

TOOLS = [lookup_requester_manager, lookup_role_holder, create_budget_release_request]
TOOL_MAP = {t.name: t for t in TOOLS}
log = logging.getLogger("approval.submission")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _business_error(message):
    return {"success": False, "request_id": None, "error_type": "business_rule", "error": message}


def _test_policy_context(request_cost):
    """Keep injected route functions usable in isolated tests without Chroma or a network."""
    cost = Decimal(str(request_cost).replace("$", "").replace(",", "").strip())
    roles, rule = get_policy_rule(cost)
    return {
        "record_id": "injected-test-policy",
        "policy_text": rule,
        "document_id": "software-request-approval",
        "document_title": "Software Request Approval Routing",
        "version": POLICY_VERSION,
        "section_id": "2",
        "section_title": "Approval thresholds",
        "citation": f"Software Request Approval Routing, {POLICY_VERSION}, §2 — Approval thresholds",
        "approval_status": "test-injected",
        "required_roles": roles,
    }


def _duplicate_error(request):
    existing = find_duplicate_request(request["requester_email"], request.get("policy_context", ""))
    if existing:
        return (f"Duplicate request: {request['requester_email']} already has request {existing} "
                f"for {request.get('policy_context')}.")
    return None


def default_route_fn(request):
    """Call the real v2.0.0 agent. Imported lazily so the workflow can be used without an API key."""
    from common import build_user_message

    conversation = [{"role": "user", "content": build_user_message(request)}]
    return get_approval_routing(conversation, verbose=False)


def parse_agent_output(text):
    """Convert the agent's text answer into the agent-result dict."""
    designations = re.findall(r"Job Designation:\s*(.+)", text)
    names = [n.strip() for n in re.findall(r"Approver's name:\s*(.+)", text)]
    reason = re.search(r"Reason:\s*(.+)", text)
    version = re.search(r"Policy version:\s*(v\d+\.\d+\.\d+)", text)

    if not names or len(names) != len(designations):
        return {"approvers": [], "reason": None, "policy_version": None, "error": text.strip()}

    approvers = [
        {"employee_id": find_employee_id_by_name(normalize(name), normalize),
         "name": name, "job_designation": designation.strip()}
        for name, designation in zip(names, designations)
    ]
    return {
        "approvers": approvers,
        "reason": reason.group(1).strip() if reason else None,
        "policy_version": version.group(1) if version else None,
        "error": None,
    }
    
def get_approval_routing(conversation, max_steps=6, verbose=True):
    """Call the model, run any tools it requests, feed results back, repeat until it answers."""
    return invoke_agent(conversation, tools=TOOLS, tool_map=TOOL_MAP, max_steps=max_steps, verbose=verbose)


def submit_request(request: dict, route_fn=None, request_id=None, policy_retriever=None) -> dict:
    """Returns {"success": bool, "request_id": str|None, "error": str|None}."""
    log.info("Step 1: submitting request: %s", request)
    email = str(request.get("requester_email", "")).strip()
    if not EMAIL_PATTERN.match(email):
        return _business_error("Invalid request: a valid Requester email is required.")
    request = {**request, "requester_email": email.lower()}
    request.setdefault("cost_currency", "USD")  # the manual form is explicitly denominated in USD
    if str(request["cost_currency"]).strip().upper() != "USD":
        return _business_error("Unsupported request currency. This prototype approval policy accepts USD only.")
    request["cost_currency"] = "USD"
    # The email must belong to the stated identity. A mismatch is never guessed around; the request is refused.
    record = get_employee(requester_id_from(request))
    if record and record["email"].lower() != request["requester_email"]:
        log.warning("Step 1: identity mismatch: %s is %s (%s), not %s", requester_id_from(request),
                    record["name"], record["email"], request["requester_email"])
        return _business_error(f"Identity mismatch: {request['requester_email']} is not the email on record for "
                               f"{record['name']} ({requester_id_from(request)}).")
    with lock:
        duplicate = _duplicate_error(request)
    if duplicate:
        log.warning("Step 1: %s", duplicate)
        return _business_error(duplicate)
    raw_cost = str(request.get("request_cost", "")).strip()
    if not COST_PATTERN.match(raw_cost):
        return _business_error("Invalid request: Request cost must be a single positive amount, for example $1,800.")
    try:
        cost = Decimal(raw_cost.replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return _business_error("Invalid request: Request cost must be a single positive amount, for example $1,800.")
    if cost <= 0:
        return _business_error("Invalid request: Request cost must be a single positive amount, for example $1,800.")

    try:
        if policy_retriever is not None:
            retrieved_policy = policy_retriever(raw_cost)
        elif route_fn is not None:
            # Explicit route_fn injection is the existing offline test seam. Production paths always retrieve Chroma.
            retrieved_policy = _test_policy_context(raw_cost)
        else:
            retrieved_policy = retrieve_approval_policy(raw_cost)
    except PolicyRetrievalError as error:
        log.exception("Request %s stopped because Chroma policy retrieval failed", request_id or "(unassigned)")
        return {"success": False, "request_id": None, "error_type": "policy_retrieval", "error": str(error)}
    except Exception as error:
        log.exception("Unexpected policy retrieval failure")
        return {"success": False, "request_id": None, "error_type": "policy_retrieval",
                "error": f"Approval policy retrieval failed: {error}"}

    request = {**request, "retrieved_policy": retrieved_policy}
    try:
        output = (route_fn or default_route_fn)(request)
    except Exception as error:
        log.exception("Step 2: technical failure while calling the agent; no workflow created")
        return {"success": False, "request_id": None, "error_type": "technical",
                "error": f"Agent call failed: {error}"}

    log.info("Step 2: agent returned output: %r", output)
    result = parse_agent_output(output)
    log.info("Step 3: parsed agent output: %s", result)
    if not validate_agent_result(result, request):
        log.warning("Step 4: validation FAILED; no workflow created. Reason: %s", result["error"] or "agent result failed validation")
        return {"success": False, "request_id": None, "error_type": "business_rule",
                "error": result["error"] or "Agent result failed validation."}
    log.info("Step 4: validation passed")

    with lock:
        duplicate = _duplicate_error(request)  # re-check: another request may have been created during the agent call
        if duplicate:
            log.warning("Step 4: %s", duplicate)
            return _business_error(duplicate)
        request_id = request_id or next_request_id()
        workflow = create_workflow(request_id, request, result["approvers"])
        log.info("Step 5: workflow %s created with approval chain: %s", request_id,
                 [(a["employee_id"], a["name"], a["job_designation"]) for a in result["approvers"]])
        add_history(workflow, "policy_retrieved", "ChromaDB",
                    f"{retrieved_policy['citation']} (record {retrieved_policy['record_id']}).")
        add_history(workflow, "submitted", request.get("requester_identity", "requester"),
                    result["reason"] or "")
        notify_approver(workflow)
    return {"success": True, "request_id": request_id, "error_type": None, "error": None}
