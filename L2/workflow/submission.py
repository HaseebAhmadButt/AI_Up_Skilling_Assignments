"""Submission service: call the agent synchronously, validate in code, then initialize the workflow."""
import re

from mock_data import find_employee_id_by_name
from tools._shared import normalize
from .store import create_workflow, next_request_id
from .validation import validate_agent_result
from .workflow_tools import add_history, notify_approver


def default_route_fn(request):
    """Call the real v2.0.0 agent. Imported lazily so the workflow can be used without an API key."""
    from agent_v2_0_0 import get_approval_routing, messages
    from common import build_user_message

    conversation = messages + [{"role": "user", "content": build_user_message(request)}]
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


def submit_request(request: dict, route_fn=None) -> dict:
    """Returns {"success": bool, "request_id": str|None, "error": str|None}."""
    route_fn = route_fn or default_route_fn
    try:
        output = route_fn(request)
    except Exception as error:
        return {"success": False, "request_id": None, "error": f"Agent call failed: {error}"}

    result = parse_agent_output(output)
    if not validate_agent_result(result, request):
        return {"success": False, "request_id": None,
                "error": result["error"] or "Agent result failed validation."}

    request_id = next_request_id()
    workflow = create_workflow(request_id, request, result["approvers"])
    add_history(workflow, "submitted", request.get("requester_identity", "requester"),
                result["reason"] or "")
    notify_approver(workflow)
    return {"success": True, "request_id": request_id, "error": None}
