"""Deterministic validation of the agent's result. The LLM output is never trusted on its own."""
from decimal import Decimal, InvalidOperation

from mock_data import POLICY_VERSION, get_employee, get_policy_rule, get_role_holder_id, manager_stage_approver_id
from tools._shared import normalize


def requester_id_from(request):
    return str(request.get("requester_identity", "")).split(",")[0].strip().upper()


def validate_agent_result(result: dict, request: dict) -> bool:
    if not isinstance(result, dict) or not isinstance(request, dict):
        return False
    if result.get("error"):
        return False
    if result.get("policy_version") != POLICY_VERSION:
        return False

    approvers = result.get("approvers")
    if not isinstance(approvers, list) or not approvers:
        return False

    ids = []
    for approver in approvers:
        if not isinstance(approver, dict):
            return False
        if not all(approver.get(k) for k in ("employee_id", "name", "job_designation")):
            return False
        record = get_employee(approver["employee_id"])
        if record is None or record["name"] != approver["name"]:
            return False
        ids.append(approver["employee_id"])
    if len(set(ids)) != len(ids):
        return False

    requester_id = requester_id_from(request)
    requester = get_employee(requester_id)
    if requester is None or requester_id in ids:
        return False
    # Manager stage: the manager on record, or the configured substitute when the requester manages themselves.
    manager_id = manager_stage_approver_id(requester_id)
    if not manager_id or manager_id == requester_id or get_employee(manager_id) is None:
        return False

    try:
        cost = Decimal(str(request.get("request_cost")).replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return False
    if cost <= 0:
        return False

    roles, _ = get_policy_rule(cost)
    # A typed Manager name is only a check against the record, never a source of the approver.
    typed = normalize(str(request.get("manager_name") or ""))
    if typed and typed != "not provided":
        on_record = {normalize(get_employee(manager_id)["name"])}
        record_manager = get_employee(requester["manager_id"])
        if record_manager:
            on_record.add(normalize(record_manager["name"]))
        if typed not in on_record:
            return False
    expected = [manager_id] + [get_role_holder_id(normalize(role)) for role in roles[1:]]
    return ids == expected
