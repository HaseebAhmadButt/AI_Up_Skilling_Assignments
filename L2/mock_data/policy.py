"""Mock approval policy data. Replace get_policy_rule with a policy store or vector DB query later."""
from decimal import Decimal

POLICY_VERSION = "v2.0.0"


def get_policy_rule(cost: Decimal):
    """Return (required_roles, rule_applied) for a validated positive cost."""
    if cost < 500:
        return ["Manager"], "Cost is below $500: Manager approval only."
    if cost <= 2500:
        return ["Manager", "IT Lead"], "Cost is from $500 to $2,500 inclusive: Manager, then IT Lead."
    return ["Manager", "IT Lead", "Finance Director"], "Cost is above $2,500: Manager, then IT Lead, then Finance Director."
