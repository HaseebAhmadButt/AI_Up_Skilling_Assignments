"""Submission service: call the agent synchronously, validate in code, then initialize the workflow."""
import logging
import re

from mock_data import find_employee_id_by_name
from tools._shared import normalize
from .store import create_workflow, find_duplicate_request, lock, next_request_id
from .validation import validate_agent_result
from .workflow_tools import add_history, notify_approver

from common import invoke_agent
from tools import get_approval_policy, lookup_requester_manager, lookup_role_holder

TOOLS = [get_approval_policy, lookup_requester_manager, lookup_role_holder]
TOOL_MAP = {t.name: t for t in TOOLS}
log = logging.getLogger("approval.submission")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _business_error(message):
    return {"success": False, "request_id": None, "error_type": "business_rule", "error": message}


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


def submit_request(request: dict, route_fn=None) -> dict:
    """Returns {"success": bool, "request_id": str|None, "error": str|None}."""
    route_fn = route_fn or default_route_fn
    log.info("Step 1: submitting request: %s", request)
    email = str(request.get("requester_email", "")).strip()
    if not EMAIL_PATTERN.match(email):
        return _business_error("Invalid request: a valid Requester email is required.")
    request = {**request, "requester_email": email.lower()}
    with lock:
        duplicate = _duplicate_error(request)
    if duplicate:
        log.warning("Step 1: %s", duplicate)
        return _business_error(duplicate)
    try:
        output = route_fn(request)
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
        request_id = next_request_id()
        workflow = create_workflow(request_id, request, result["approvers"])
        log.info("Step 5: workflow %s created with approval chain: %s", request_id,
                 [(a["employee_id"], a["name"], a["job_designation"]) for a in result["approvers"]])
        add_history(workflow, "submitted", request.get("requester_identity", "requester"),
                    result["reason"] or "")
        notify_approver(workflow)
    return {"success": True, "request_id": request_id, "error_type": None, "error": None}
