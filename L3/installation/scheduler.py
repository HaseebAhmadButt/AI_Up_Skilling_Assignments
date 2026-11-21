"""Second scheduler: discover fully approved requests and ask the Agent to manage installation."""

import logging
import time

from workflow.store import approval_workflows, lock

from . import memory
from .agent import run_installation_agent


log = logging.getLogger("installation.scheduler")
INSTALLATION_SCHEDULER_INTERVAL_SECONDS = 30


def process_installation_workflows(agent_fn=None):
    """Register new approval handoffs, then let the Agent choose each install's next action."""
    memory.refresh_fixtures()
    with lock:
        approved = [workflow.copy() for workflow in approval_workflows.values()
                    if workflow.get("status") == "approved"
                    and workflow.get("approval_chain")
                    and all(step.get("decision") == "APPROVED" for step in workflow["approval_chain"])]

    registered = []
    for workflow in approved:
        was_new = memory.get_installation_request(workflow["request_id"]) is None
        memory.register_approved_request(workflow)
        if was_new:
            registered.append(workflow["request_id"])

    invoke_agent_fn = agent_fn or run_installation_agent
    invoked, failures = [], []
    for request in memory.list_agent_work():
        request_id = request["request_id"]
        try:
            response = invoke_agent_fn(request_id)
            invoked.append(request_id)
            log.info("[%s] installation Agent response: %s", request_id, response)
        except Exception:
            failures.append(request_id)
            log.exception("[%s] installation Agent invocation failed; request remains open", request_id)

    summary = {"registered": registered, "invoked": invoked, "agent_failures": failures}
    if any(summary.values()):
        log.info("Installation scheduler cycle: %s", summary)
    return summary


def start_installation_scheduler(stop_event, interval=INSTALLATION_SCHEDULER_INTERVAL_SECONDS):
    """Run the installation scheduler until the application's stop event is set."""
    import threading

    def run():
        log.info("Installation scheduler started (interval %ss)", interval)
        while not stop_event.is_set():
            process_installation_workflows()
            if stop_event.wait(interval):
                break
        log.info("Installation scheduler stopped")

    thread = threading.Thread(target=run, name="installation-scheduler", daemon=True)
    thread.start()
    return thread
