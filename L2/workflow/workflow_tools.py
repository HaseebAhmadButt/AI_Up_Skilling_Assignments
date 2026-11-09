"""Workflow tools: authorization, state transitions, idempotency, notifications and audit history."""
import time
from datetime import datetime

from mock_data import send_notification
from .store import get_workflow, update_workflow


def add_history(workflow, event, actor, details=""):
    """The single place history is appended."""
    workflow["history"].append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "actor": actor,
        "details": details,
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


def record_decision(request_id, approver_id, decision):
    """Apply an approve/reject decision. Returns a dict: {success, status, message, duplicate}."""
    def result(success, message, duplicate=False):
        return {"success": success, "status": workflow["status"] if workflow else None,
                "message": message, "duplicate": duplicate}

    workflow = get_workflow(request_id)
    if workflow is None:
        return result(False, "Unknown request_id.")
    if decision not in ("approve", "reject"):
        return result(False, "Decision must be 'approve' or 'reject'.")

    # Idempotency: the same approver repeating the same decision is a no-op.
    for step in workflow["approval_chain"]:
        if step["employee_id"] == approver_id and step["decision"] is not None:
            if step["decision"] == decision:
                return result(True, "Decision already recorded.", duplicate=True)
            return result(False, "A different decision was already recorded by this approver.")

    if workflow["status"] != "pending":
        return result(False, f"Workflow is {workflow['status']}; no further decisions accepted.")

    step = current_step(workflow)
    if step is None or step["employee_id"] != approver_id:
        return result(False, "Not authorized: this approver is not the current approver.")

    step["decision"] = decision
    add_history(workflow, decision, approver_id, f"{step['name']} recorded '{decision}'.")

    if decision == "reject":
        update_workflow(request_id, status="rejected")
        add_history(workflow, "rejected", "system", "Workflow rejected; chain stopped.")
        send_notification(workflow["request"].get("requester_identity", "requester"),
                          f"{request_id} was rejected.")
        return result(True, "Workflow rejected.")

    update_workflow(request_id, current_approver_index=workflow["current_approver_index"] + 1)
    if workflow["current_approver_index"] >= len(workflow["approval_chain"]):
        update_workflow(request_id, status="approved")
        add_history(workflow, "approved", "system", "All approvers approved.")
        send_notification(workflow["request"].get("requester_identity", "requester"),
                          f"{request_id} was fully approved.")
        return result(True, "Workflow approved.")

    notify_approver(workflow)
    return result(True, "Approval recorded; moved to next approver.")
