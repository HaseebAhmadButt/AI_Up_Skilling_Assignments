"""Scheduler: one pass over approval_workflows. Uses workflow tools for every change."""
import time

from mock_data import send_notification
from .store import list_active_workflows, update_workflow
from .workflow_tools import add_history, current_step

STALE_AFTER_SECONDS = 24 * 3600
MAX_REMINDERS = 2


def process_workflows(now=None, stale_after=STALE_AFTER_SECONDS, max_reminders=MAX_REMINDERS):
    """Remind stale approvers, then escalate. Returns a summary dict."""
    now = time.time() if now is None else now
    summary = {"reminded": [], "escalated": []}

    for workflow in list_active_workflows():
        step = current_step(workflow)
        if step is None or step["notified_at"] is None:
            continue
        if now - step["notified_at"] < stale_after:
            continue

        request_id = workflow["request_id"]
        if step["reminders"] >= max_reminders:
            update_workflow(request_id, status="escalated")
            add_history(workflow, "escalated", "scheduler",
                        f"No response from {step['name']} after {step['reminders']} reminders.")
            summary["escalated"].append(request_id)
        else:
            step["reminders"] += 1
            step["notified_at"] = now
            send_notification(step["employee_id"], f"Reminder: approval pending for {request_id}.")
            add_history(workflow, "reminder", "scheduler", f"Reminder {step['reminders']} sent to {step['name']}.")
            summary["reminded"].append(request_id)
    return summary
