from langchain.tools import tool

from mock_data import get_role_holder_id
from ._shared import normalize, person


@tool
def lookup_role_holder(role: str) -> dict:
    """Return the current holder of an approver role. Valid roles are 'IT Lead' and 'Finance Director'.
    Do not use this for the Manager role; use lookup_requester_manager for that.
    If found is false, the error field holds the exact message to output."""
    employee_id = get_role_holder_id(normalize(role))
    if not employee_id:
        return {"found": False, "error": "Routing cannot be completed: unknown approver role. Manual escalation required."}
    return {"found": True, "role": role, **person(employee_id)}
