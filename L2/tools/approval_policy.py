import re
from decimal import Decimal, InvalidOperation

from langchain.tools import tool

from mock_data import POLICY_VERSION, get_policy_rule
from ._shared import INVALID_COST_MESSAGE

COST_PATTERN = re.compile(r"^\$?\s*(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$")


@tool
def get_approval_policy(request_cost: str) -> dict:
    """Validate the request cost and return the ordered approver roles required by the approval policy.
    Pass the Request cost exactly as the user wrote it, character for character, without cleaning or changing it.
    Returns valid, the required_roles in approval order, the rule_applied and the policy_version.
    If valid is false, the error field holds the exact message to output."""
    text = str(request_cost).strip()
    invalid = {"valid": False, "error": INVALID_COST_MESSAGE, "policy_version": POLICY_VERSION}
    if not COST_PATTERN.match(text):
        return invalid

    try:
        cost = Decimal(text.replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return invalid
    if cost <= 0:
        return invalid

    roles, rule = get_policy_rule(cost)
    return {
        "valid": True,
        "cost_used": str(cost),
        "required_roles": roles,
        "rule_applied": rule,
        "policy_version": POLICY_VERSION,
    }
