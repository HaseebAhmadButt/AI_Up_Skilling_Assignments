"""Agent-driven routing. After an approver raises APPROVED or REJECTED, the Agent receives the complete request,
the approvers list and the tools, and decides the next step. Deterministic code only verifies and applies it."""
import logging
import re

from common import ROUTING_SYSTEM_MESSAGES, invoke_agent
from mock_data import send_notification
from tools._shared import normalize
from .store import update_workflow
from .submission import TOOLS, TOOL_MAP
from .workflow_tools import REJECTED, add_history, current_step, has_unrouted_decision, notify_approver

log = logging.getLogger("approval.routing")
MAX_ROUTING_ATTEMPTS = 3  # failed or invalid agent answers tolerated before the request is escalated


def build_routing_message(workflow):
    """Complete request details, the full approvers list with decisions, and the latest decision."""
    request = workflow["request"]
    chain = workflow["approval_chain"]
    index = workflow["current_approver_index"]
    lines = [
        f"Request ID: {workflow['request_id']}",
        f"Request cost: ${float(request['request_cost']):,.2f}",
        f"Requester identity: {request['requester_identity']}",
        f"Manager name: {request.get('manager_name', 'Not provided')}",
        f"Software name: {request.get('policy_context', 'Not provided')}",
        f"Business justification: {request.get('business_justification', 'Not provided')}",
        "Approvers list (in approval order):",
    ]
    for i, step in enumerate(chain, 1):
        line = f"{i}. {step['job_designation']} - {step['name']} ({step['employee_id']}): {step['decision'] or 'PENDING'}"
        if step.get("decided_at"):
            line += f" at {step['decided_at']}"
        if step.get("reason"):
            line += f" | Rejection reason: {step['reason']}"
        lines.append(line)
    step = chain[index]
    lines.append(f"Latest decision: {step['decision']} by {step['name']} ({step['job_designation']}), "
                 f"position {index + 1} of {len(chain)}")
    return "\n".join(lines)


def default_next_step_fn(workflow):
    """Ask the real agent for the next step. Receives a snapshot of the workflow."""
    message = build_routing_message(workflow)
    return invoke_agent([{"role": "user", "content": message}], tools=TOOLS, tool_map=TOOL_MAP,
                        verbose=False, system_messages=ROUTING_SYSTEM_MESSAGES)


def parse_routing_output(text):
    action = re.search(r"ACTION:\s*(ASSIGN_NEXT|COMPLETE|REJECT|BLOCK)\b", text or "")
    approver = re.search(r"NEXT_APPROVER:\s*(.+)", text or "")
    reason = re.search(r"REASON:\s*(.+)", text or "")
    return {"action": action.group(1) if action else None,
            "next_approver": approver.group(1).strip() if approver else None,
            "reason": reason.group(1).strip() if reason else ""}


def routing_error(workflow, result):
    """Deterministic check of the agent's choice. Returns an error text, or None if it can be applied.
    The Agent chooses the action; this only rejects answers that contradict the recorded decision."""
    action = result["action"]
    if action is None:
        return "Agent output had no valid ACTION."
    chain = workflow["approval_chain"]
    index = workflow["current_approver_index"]
    if chain[index]["decision"] == REJECTED:
        return None if action == "REJECT" else f"Agent answered {action} for a rejected request; it must reject."
    if action == "REJECT":
        return "Agent answered REJECT but the latest decision was not a rejection."
    if action == "BLOCK":
        return None
    if index + 1 >= len(chain):
        return None if action == "COMPLETE" else f"Agent answered {action} after the last approver; it must complete."
    if action != "ASSIGN_NEXT":
        return f"Agent answered {action} but another approver is still required."
    if normalize(result["next_approver"] or "") != normalize(chain[index + 1]["name"]):
        return f"Agent chose {result['next_approver']!r}, but the next approver in the list is {chain[index + 1]['name']!r}."
    return None


def apply_routing(workflow, output, error=None):
    """Apply the agent's routing decision once. Returns the action taken, 'escalated', or None to retry later."""
    if workflow is None or not has_unrouted_decision(workflow):
        return None
    request_id = workflow["request_id"]
    index = workflow["current_approver_index"]
    step = workflow["approval_chain"][index]
    requester = workflow["request"].get("requester_identity", "requester")

    result = None
    if error is None:
        result = parse_routing_output(output)
        error = routing_error(workflow, result)
    if error:
        step["routing_attempts"] = step.get("routing_attempts", 0) + 1
        log.warning("[%s] routing attempt %d/%d failed: %s", request_id, step["routing_attempts"],
                    MAX_ROUTING_ATTEMPTS, error)
        if step["routing_attempts"] < MAX_ROUTING_ATTEMPTS:
            return None  # the decision stays unrouted; the scheduler asks the Agent again next pass
        step["processed"] = True
        update_workflow(request_id, status="escalated")
        add_history(workflow, "escalated", "scheduler", f"Agent could not route the request: {error}")
        return "escalated"

    step["processed"] = True
    action, reason = result["action"], result["reason"]
    log.info("[%s] agent decided %s (%s)", request_id, action, reason)
    if action == "ASSIGN_NEXT":
        update_workflow(request_id, current_approver_index=index + 1)
        step["resulting_state"] = f"pending: advanced to {workflow['approval_chain'][index + 1]['name']}"
        add_history(workflow, "routed", "agent",
                    f"Assigned next approver {workflow['approval_chain'][index + 1]['name']}. {reason}")
        notify_approver(workflow)
    elif action == "COMPLETE":
        update_workflow(request_id, status="approved")
        step["resulting_state"] = "approved (budget approval complete)"
        add_history(workflow, "approved", "agent", f"All approvers approved. {reason}")
        send_notification(requester, f"{request_id} was fully approved.")
        log.info("[%s] HANDOFF: budget approval complete; ready for the next workflow stage. "
                 "Software installation is NOT completed by this workflow.", request_id)
    elif action == "REJECT":
        update_workflow(request_id, status="rejected", rejection_reason=step.get("reason"))
        step["resulting_state"] = "rejected"
        add_history(workflow, "rejected", "agent",
                    f"Request rejected after decision by {step['name']}. Reason: {step.get('reason')}. {reason}")
        send_notification(requester, f"{request_id} was rejected.")
    else:
        update_workflow(request_id, status="blocked", block_reason=reason)
        step["resulting_state"] = "blocked"
        add_history(workflow, "blocked", "agent", f"Flow blocked by the Agent. {reason}")
        send_notification(requester, f"{request_id} was blocked: {reason}")
    return action
