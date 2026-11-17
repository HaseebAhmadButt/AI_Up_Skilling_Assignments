"""Helpers and messages shared by the tools."""
from mock_data import get_employee

INVALID_COST_MESSAGE = "Invalid request: Request cost must be a single positive amount, for example $1,800."
SELF_APPROVAL_MESSAGE = "Routing cannot be completed: self-approval is not allowed. The requester cannot be their own approver. Manual escalation required."


def normalize(text):
    return " ".join(str(text).split()).lower()


def person(employee_id):
    record = get_employee(employee_id)
    return {
        "employee_id": employee_id,
        "name": record["name"],
        "job_designation": record["title"],
        "department": record["department"],
    }
