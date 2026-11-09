"""Simulated approver decisions, passed as plain dicts."""
from .store import get_workflow
from .workflow_tools import current_step, record_decision


def simulate_decision(request_id, decision, approver_id=None):
    """Decide as the current approver (or as approver_id, to test authorization)."""
    workflow = get_workflow(request_id)
    if approver_id is None:
        step = current_step(workflow) if workflow else None
        approver_id = step["employee_id"] if step else None
    decision_dict = {"request_id": request_id, "approver_id": approver_id, "decision": decision}
    return record_decision(**decision_dict)
