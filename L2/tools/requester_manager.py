from langchain.tools import tool

from mock_data import employee_name_exists, get_employee, manager_stage_approver_id
from ._shared import SELF_APPROVAL_MESSAGE, normalize, person


@tool
def lookup_requester_manager(requester_identity: str, provided_manager_name: str = "") -> dict:
    """Look up the requester in the employee directory and return the approver for the Manager stage from the system of record.
    Pass the Requester identity exactly as the user wrote it.
    If the user supplied a Manager name, pass it exactly as written in provided_manager_name; otherwise leave it empty.
    The approver on record is always the one returned (for a self-managed requester this is the configured authorized substitute, never the requester). A provided name is only checked against it.
    Returns found, the requester and the manager (employee_id, name, job_designation, department).
    If found is false, the error field holds the exact message to output."""
    requester_id = str(requester_identity).split(",")[0].strip().upper()
    requester = get_employee(requester_id)
    if not requester:
        return {"found": False, "error": "Invalid request: Requester was not found in the employee directory."}

    # The approver always comes from the system of record. A self-managed requester is routed to the configured substitute.
    record_manager_id = requester["manager_id"]
    manager_id = manager_stage_approver_id(requester_id)
    if record_manager_id == requester_id and not manager_id:
        return {"found": False, "error": SELF_APPROVAL_MESSAGE}
    manager = get_employee(manager_id) if manager_id else None
    if not manager:
        return {"found": False, "error": "Routing cannot be completed: no manager is on record for this requester. Manual escalation required."}

    # A manager name is optional. If given, it is only checked against the approver on record (or the manager of record).
    provided = normalize(str(provided_manager_name).split(",")[0])
    if provided and provided != "not provided":
        if not employee_name_exists(provided, normalize):
            return {"found": False, "error": "Invalid request: Manager was not found in the employee directory."}
        accepted = {normalize(manager["name"]), normalize(get_employee(record_manager_id)["name"])}
        if provided not in accepted:
            return {"found": False, "error": "Invalid request: The manager name provided does not match the manager on record for this requester."}

    return {
        "found": True,
        "requester": person(requester_id),
        "manager": person(manager_id),
    }
