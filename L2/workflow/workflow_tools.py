"""Workflow tools: authorization, state transitions, idempotency, notifications and audit history."""
import logging
import time
from datetime import datetime

from mock_data import send_notification
from .store import get_workflow

log = logging.getLogger("approval.workflow")


def add_history(workflow, event, actor, details=""):
    """The single place history is appended."""
    log.info("[%s] history: %s by %s - %s", workflow["request_id"], event, actor, details)
    workflow["history"].append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "actor": actor,
        "details": details,
        "state": workflow["status"],  # workflow status right after this event
    })


def current_step(workflow):
    index = workflow["current_approver_index"]
    chain = workflow["approval_chain"]
    return chain[index] if index < len(chain) else None


def notify_approver(workflow, now=None):
    """Notify the current approver once per step. Returns False if already notified."""
    step = current_step(workflow)
    if step is None or step["notified_at"] is not None:
        return False
    step["notified_at"] = time.time() if now is None else now
    send_notification(step["employee_id"], f"Approval needed for {workflow['request_id']}.")
    add_history(workflow, "notified", "system", f"Notified {step['name']} ({step['employee_id']}).")
    return True


REJECTED_MESSAGE = "This request has already been rejected and cannot be modified."
APPROVED, REJECTED = "APPROVED", "REJECTED"
MIN_REASON_CHARS = 10
MIN_REASON_WORDS = 2
REASON_TOO_SHORT_MESSAGE = (f"A rejection reason is required: at least {MIN_REASON_WORDS} words and "
                            f"{MIN_REASON_CHARS} characters explaining why.")


def is_meaningful_reason(reason):
    text = reason.strip() if isinstance(reason, str) else ""
    return len(text) >= MIN_REASON_CHARS and len(text.split()) >= MIN_REASON_WORDS


def is_rejected(workflow):
    """A request is permanently terminal once rejected, or once a rejection is recorded and awaiting the scheduler."""
    return workflow["status"] == "rejected" or any(
        step["decision"] == REJECTED for step in workflow["approval_chain"])


def _result(workflow, success, message):
    log.log(logging.INFO if success else logging.WARNING, "[%s] decision result: success=%s message=%s",
            workflow["request_id"] if workflow else None, success, message)
    return {"success": success, "status": workflow["status"] if workflow else None,
            "message": message}


def submit_decision(request_id, approver_id, decision, reason=None):
    """Record-only: store an APPROVED/REJECTED decision on the current step. The scheduler processes it."""
    log.info("[%s] decision attempt: approver=%s decision=%s reason=%r", request_id, approver_id, decision, reason)
    workflow = get_workflow(request_id)
    if workflow is None:
        return _result(None, False, "Unknown request_id.")
    if decision not in (APPROVED, REJECTED):
        return _result(workflow, False, "Decision must be APPROVED or REJECTED.")
    if is_rejected(workflow):
        return _result(workflow, False, REJECTED_MESSAGE)
    if workflow["status"] != "pending":
        return _result(workflow, False, f"Workflow is {workflow['status']}; no further decisions accepted.")

    for step in workflow["approval_chain"]:
        if step["employee_id"] == approver_id and step["decision"] is not None:
            return _result(workflow, False, "A decision has already been recorded by this approver.")

    step = current_step(workflow)
    if step is None or step["employee_id"] != approver_id:
        return _result(workflow, False, "Not authorized: this approver is not the current approver.")
    if decision == REJECTED and not is_meaningful_reason(reason):
        return _result(workflow, False, REASON_TOO_SHORT_MESSAGE)

    step["decision"] = decision
    step["decided_by"] = approver_id
    step["decided_at"] = datetime.now().isoformat(timespec="seconds")
    step["reason"] = reason.strip() if decision == REJECTED else None
    step["processed"] = False
    step["resulting_state"] = "pending: decision recorded, awaiting Agent routing"
    # The approver only raises a flag. Routing (next approver, completion or blocking) is decided by the Agent
    # on the next scheduler pass, so the current stage stays where it is and shows the recorded decision.
    if decision == APPROVED:
        add_history(workflow, "approve", approver_id,
                    f"{step['name']} approved the request. Resulting state: {step['resulting_state']}.")
    else:
        add_history(workflow, "reject", approver_id,
                    f"{step['name']} rejected the request. Reason: {step['reason']}. "
                    f"Resulting state: {step['resulting_state']}.")
    return _result(workflow, True, "Decision recorded; awaiting Agent routing on the next scheduler pass.")


def has_unrouted_decision(workflow):
    """True when the current step has a recorded decision that the Agent has not routed yet."""
    if workflow["status"] != "pending":
        return False
    step = current_step(workflow)
    return step is not None and step["decision"] in (APPROVED, REJECTED) and not step.get("processed", True)
