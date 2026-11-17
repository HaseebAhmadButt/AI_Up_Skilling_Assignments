"""Scheduler: one pass over approval_workflows. Recorded decisions are routed by the Agent; the scheduler
only hands over the workflow, applies the verified answer, and handles reminders and escalation."""
import copy
import logging
import time

from mock_data import send_notification
from .routing import apply_routing, default_next_step_fn
from .store import get_workflow, list_active_workflows, lock, update_workflow
from .workflow_tools import add_history, current_step, has_unrouted_decision

log = logging.getLogger("approval.scheduler")
STALE_AFTER_SECONDS = 24 * 3600  # an approver is considered unresponsive after 24 hours
MAX_REMINDERS = 2  # reminders sent before the request is escalated


def process_workflows(now=None, stale_after=STALE_AFTER_SECONDS, max_reminders=MAX_REMINDERS, next_step_fn=None):
    """Route recorded decisions through the Agent, remind stale approvers, then escalate. Returns a summary dict."""
    next_step_fn = next_step_fn or default_next_step_fn
    # Step 1: set up the clock (injectable for tests) and the summary of what this pass does.
    now = time.time() if now is None else now
    summary = {"processed": [], "reminded": [], "escalated": []}

    # Step 2 (locked): split the pending workflows into those with a decision waiting for the Agent and the rest.
    # Decisions get a snapshot so the Agent can be called without holding the lock (the menus stay responsive).
    jobs = []
    with lock:
        active = list_active_workflows()
        log.debug("Scheduler cycle: %d active workflow(s)", len(active))
        for workflow in active:
            if has_unrouted_decision(workflow):
                jobs.append((workflow["request_id"], copy.deepcopy(workflow)))
            else:
                _remind_or_escalate(workflow, now, stale_after, max_reminders, summary)

    # Step 3 (unlocked): pass the complete request, approvers list and tools to the Agent; it decides the next step.
    for request_id, snapshot in jobs:
        try:
            output, error = next_step_fn(snapshot), None
        except Exception as exc:
            log.exception("[%s] agent routing call failed", request_id)
            output, error = None, f"Agent call failed: {exc}"

        # Step 4 (locked): verify the Agent's answer and apply it (assign next approver, complete, or block).
        with lock:
            action = apply_routing(get_workflow(request_id), output, error)
        if action == "escalated":
            summary["escalated"].append(request_id)
        elif action:
            summary["processed"].append(request_id)

    # Step 5: log the pass only if it did something, then return the summary.
    if any(summary.values()):
        log.info("Scheduler cycle summary: %s", summary)
    return summary


def _remind_or_escalate(workflow, now, stale_after, max_reminders, summary):
    """Reminder / escalation for an approver who has not responded. Runs under the lock."""
    # Skip if there is nothing to wait on: no current approver, approver not yet notified, or a decision recorded.
    step = current_step(workflow)
    if step is None or step["notified_at"] is None or step["decision"] is not None:
        return
    # Skip if the approver has not been waiting longer than the stale threshold.
    if now - step["notified_at"] < stale_after:
        return

    request_id = workflow["request_id"]
    if step["reminders"] >= max_reminders:
        # Reminders exhausted, so escalate the workflow and record it in history.
        update_workflow(request_id, status="escalated")
        add_history(workflow, "escalated", "scheduler",
                    f"No response from {step['name']} after {step['reminders']} reminders.")
        summary["escalated"].append(request_id)
    else:
        # Send another reminder, restart the stale timer, and record it in history.
        step["reminders"] += 1
        step["notified_at"] = now
        send_notification(step["employee_id"], f"Reminder: approval pending for {request_id}.")
        add_history(workflow, "reminder", "scheduler", f"Reminder {step['reminders']} sent to {step['name']}.")
        summary["reminded"].append(request_id)
