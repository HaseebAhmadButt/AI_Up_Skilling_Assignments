from langchain.tools import tool

from mock_data import employee_name_exists, get_employee
from ._shared import SELF_APPROVAL_MESSAGE, normalize, person


@tool
def lookup_requester_manager(requester_identity: str, provided_manager_name: str = "") -> dict:
    """Look up the requester in the employee directory and return their manager from the system of record.
    Pass the Requester identity exactly as the user wrote it.
    If the user supplied a Manager name, pass it exactly as written in provided_manager_name; otherwise leave it empty.
    The manager on record is always the one returned. A provided name is only checked against it.
    Returns found, the requester and the manager (employee_id, name, job_designation, department).
    If found is false, the error field holds the exact message to output."""
    requester_id = str(requester_identity).split(",")[0].strip().upper()
    requester = get_employee(requester_id)
    if not requester:
        return {"found": False, "error": "Invalid request: Requester was not found in the employee directory."}

    # The manager always comes from the requester's record (system of record).
    manager_id = requester["manager_id"]
    if manager_id == requester_id:
        return {"found": False, "error": SELF_APPROVAL_MESSAGE}
    manager = get_employee(manager_id) if manager_id else None
    if not manager:
        return {"found": False, "error": "Routing cannot be completed: no manager is on record for this requester. Manual escalation required."}

    # A manager name is optional. If given, it is only checked against the manager on record.
    provided = normalize(str(provided_manager_name).split(",")[0])
    if provided and provided != "not provided":
        if not employee_name_exists(provided, normalize):
            return {"found": False, "error": "Invalid request: Manager was not found in the employee directory."}
        if provided != normalize(manager["name"]):
            return {"found": False, "error": "Invalid request: The manager name provided does not match the manager on record for this requester."}

    return {
        "found": True,
        "requester": person(requester_id),
        "manager": person(manager_id),
    }
