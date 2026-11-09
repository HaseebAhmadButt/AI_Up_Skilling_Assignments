"""In-memory workflow store. Only validated, initialized workflows are ever added here."""

approval_workflows = {}
_counter = 0


def next_request_id():
    global _counter
    _counter += 1
    return f"REQ-{_counter:04d}"


def create_workflow(request_id, request, approval_chain):
    """Add a new workflow. Each chain entry is {employee_id, name, job_designation}."""
    if request_id in approval_workflows:
        raise ValueError(f"Workflow {request_id} already exists.")
    approval_workflows[request_id] = {
        "request_id": request_id,
        "request": dict(request),
        "approval_chain": [
            {**approver, "decision": None, "notified_at": None, "reminders": 0}
            for approver in approval_chain
        ],
        "current_approver_index": 0,
        "status": "pending",  # pending | approved | rejected | escalated
        "history": [],
    }
    return approval_workflows[request_id]


def get_workflow(request_id):
    return approval_workflows.get(request_id)


def update_workflow(request_id, **fields):
    workflow = approval_workflows[request_id]
    workflow.update(fields)
    return workflow


def list_active_workflows():
    return [w for w in approval_workflows.values() if w["status"] == "pending"]


def clear_workflows():
    approval_workflows.clear()
