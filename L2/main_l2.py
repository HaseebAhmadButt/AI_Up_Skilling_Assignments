"""L2 demo: submit requests through the real agent, then simulate approver decisions."""
from workflow.scheduler import process_workflows
from workflow.simulation import simulate_decision
from workflow.store import approval_workflows
from workflow.submission import submit_request


def show(request_id):
    workflow = approval_workflows[request_id]
    print(f"{request_id}: {workflow['status']}")
    for entry in workflow["history"]:
        print(f"  {entry['timestamp']} {entry['event']:<10} {entry['actor']}: {entry['details']}")


if __name__ == "__main__":
    request = {
        "request_cost": 3000,
        "requester_identity": "E1001, Marketing Analyst, Marketing",
        "manager_name": "Ali Raza",
        "policy_context": "IDE licence",
    }
    outcome = submit_request(request)
    print(outcome)
    if outcome["success"]:
        rid = outcome["request_id"]
        while approval_workflows[rid]["status"] == "pending":
            print(simulate_decision(rid, "approve"))
        process_workflows()
        show(rid)
