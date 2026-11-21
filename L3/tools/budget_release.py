"""Agent tool for a simulated budget release request and approval."""
from langchain.tools import tool

from workflow.store import get_workflow, lock
from workflow.workflow_tools import APPROVED, add_history


@tool
def create_budget_release_request(request_id: str) -> dict:
    """Create and automatically approve a simulated budget release after every approver has approved."""
    with lock:
        workflow = get_workflow(request_id)
        if workflow is None:
            return {"success": False, "error": "Request was not found."}
        chain = workflow.get("approval_chain", [])
        if not chain or any(step.get("decision") != APPROVED for step in chain):
            return {"success": False, "error": "Budget release is unavailable until every approver has approved."}
        existing = workflow.get("budget_release")
        if existing:
            return {"success": True, **existing, "duplicate": True}
        release = {
            "release_id": f"BUD-{request_id}",
            "request_id": request_id,
            "amount": workflow["request"]["request_cost"],
            "status": "approved",
            "approval_mode": "automatic_prototype",
        }
        workflow["budget_release"] = release
        add_history(workflow, "budget_release_requested", "agent",
                    f"Created budget release request {release['release_id']} for {release['amount']}.")
        add_history(workflow, "budget_release_approved", "budget_release_tool",
                    f"Simulated budget release {release['release_id']} was automatically approved.")
        return {"success": True, **release, "duplicate": False}
