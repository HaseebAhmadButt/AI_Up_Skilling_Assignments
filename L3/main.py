"""L3 prototype app with employee and approver portals plus simulated email intake.
Approval transitions remain in the existing workflow scheduler; intake and workflow state are in memory."""
import logging
import threading

from app_logging import setup_logging
from intake import EmailIntakeService, run_fixture_demo
from installation import memory as installation_memory
from installation.scheduler import start_installation_scheduler
from mock_data import get_employee
from workflow.scheduler import process_workflows
from workflow.store import approval_workflows, lock
from workflow.submission import EMAIL_PATTERN, submit_request
from workflow.validation import requester_id_from
from workflow.workflow_tools import (REASON_TOO_SHORT_MESSAGE, REJECTED_MESSAGE, current_step, is_meaningful_reason,
                                     is_rejected, submit_decision)

SCHEDULER_INTERVAL_SECONDS = 5
log = logging.getLogger("approval.main")

MENU = (
    "\n===== Software Request Approval System =====\n"
    "1. Create a New Software Request.\n"
    "2. Employee Portal - Show Employee Request Details.\n"
    "3. Manager Portal - View and Process Assigned Requests.\n"
    "4. IT Lead Portal - View and Process Assigned Requests.\n"
    "5. Finance Director Portal - View and Process Assigned Requests.\n"
    "6. Run Simulated Email Intake Demo.\n"
    "7. Installation and IT Pending Status.\n"
    "8. Review IT Packaging Requests.\n"
    "9. Policy Assistant (Chroma RAG).\n"
    "10. Exit Application.\n"
)

email_intake_demo = EmailIntakeService()


def installation_status_board():
    """Display the separate installation memory and IT packaging queue."""
    print(f"\nRegistered fixture devices: {len(installation_memory.device_registry)}")
    print(f"Approved fixture software: {len(installation_memory.approved_software_catalog)}")
    requests = installation_memory.list_installation_requests()
    print("\n===== Installation Memory =====")
    if not requests:
        print("No fully approved requests have been handed to the installation Agent yet.")
    for request in requests:
        print(f"\n{request['request_id']} | {request['software_name']} | {request['status']}")
        print(f"  Employee: {request['employee_id']} ({request['requester_email']})")
        print(f"  Device: {request.get('device_id') or 'Awaiting Agent selection'}")
        print(f"  Owner: {request['owner']}")
        print(f"  Next action: {request['next_action']}")
        for event in request["history"]:
            print(f"  {event['timestamp']} {event['event']} — {event['actor']}: {event['details']}")

    pending = installation_memory.list_it_pending_items()
    print("\n===== IT Pending Software =====")
    if not pending:
        print("No software is waiting for packaging approval.")
    for item in pending:
        print(f"{item['pending_id']} | {item['software_name']} | {item['status']} | "
              f"request {item['request_id']} | {item['requested_version']}")


def review_it_packaging_requests():
    """Let IT review pending packaging and publish an approved simulated package version."""
    pending = [item for item in installation_memory.list_it_pending_items() if item["status"] == "pending"]
    if not pending:
        print("\nNo IT packaging requests are awaiting a decision.")
        return
    print("\n===== IT Packaging Requests Awaiting Decision =====")
    for index, item in enumerate(pending, 1):
        request = installation_memory.get_installation_request(item["request_id"])
        device = installation_memory.device_registry.get(item["device_id"], {})
        print(f"\n[{index}] {item['pending_id']} | {item['software_name']} | {item['requested_version']}")
        print(f"  Request: {item['request_id']} | Employee: {item['employee_id']} ({item['requester_email']})")
        print(f"  Device: {item['device_id']} ({device.get('os', 'unknown OS')})")
        print(f"  Reason: {item['reason']}")
        print(f"  Request status: {request['status']} | Next action: {request['next_action']}")

    selection = input("Select a request number, or B to go back: ").strip().lower()
    if selection == "b":
        return
    if not selection.isdigit() or not 1 <= int(selection) <= len(pending):
        print("Invalid selection.")
        return
    item = pending[int(selection) - 1]
    decision = input("Decision (A)pprove or (R)eject: ").strip().lower()
    if decision in {"a", "approve"}:
        package_id = read_required("Approved package ID: ")
        version = read_required("Approved package version: ")
        license_required = input("Does this package require a named-user license? (Y/N): ").strip().lower()
        if license_required not in {"y", "yes", "n", "no"}:
            print("Enter Y or N; no change was made.")
            return
        license_required = license_required in {"y", "yes"}
        seat_limit = read_positive_integer("Total named-user license seats: ") if license_required else None
        result = installation_memory.decide_it_pending_item(
            item["request_id"], "approve", package_id=package_id, version=version,
            license_required=license_required, seat_limit=seat_limit)
    elif decision in {"r", "reject"}:
        result = installation_memory.decide_it_pending_item(item["request_id"], "reject")
    else:
        print("Invalid decision; no change was made.")
        return
    if result["success"]:
        if result["status"] == "approved":
            print(f"Approved {result['package_id']} {result['version']}; the Agent will retry this request automatically.")
        else:
            print("Packaging request rejected. The software request remains open for IT review.")
    else:
        print(f"Could not record the decision: {result['error']}")


def policy_assistant_portal():
    """Answer policy questions from retrieved Chroma sections with citations or refuse."""
    from policy.assistant import answer_policy_question

    while True:
        question = input("Policy question (B to go back): ").strip()
        if question.lower() == "b":
            return
        result = answer_policy_question(question)
        print(f"\n{result['answer']}")
        if result["citations"]:
            print("Sources:")
            for citation in result["citations"]:
                print(f"  - {citation}")

DECISION_LABELS = {"approve": "APPROVED", "reject": "REJECTED", "APPROVED": "APPROVED", "REJECTED": "REJECTED"}


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
def read_required(prompt_text):
    """Keep asking until the user enters a non-empty value."""
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        print("This field is required. Please try again.")


def read_optional(prompt_text):
    return input(prompt_text).strip() or None


def read_positive_integer(prompt_text):
    while True:
        raw = input(prompt_text).strip()
        try:
            value = int(raw)
        except ValueError:
            print("Enter a whole number greater than zero.")
            continue
        if value > 0:
            return value
        print("Enter a whole number greater than zero.")


def read_cost():
    """Keep asking until the user enters a valid positive number."""
    while True:
        raw = input("Request cost (USD): ").strip()
        cleaned = raw.replace("$", "").replace(",", "")
        try:
            cost = float(cleaned)
        except ValueError:
            print("Please enter a numeric amount, for example 1800 or $1,800.")
            continue
        if cost <= 0:
            print("Cost must be greater than zero.")
            continue
        return cost


def read_email():
    """Keep asking until the user enters something that looks like an email address."""
    while True:
        value = input("Requester email: ").strip()
        if EMAIL_PATTERN.match(value):
            return value
        print("Please enter a valid email address, for example name@company.com.")


def read_user_request():
    """Collect the request fields. The agent only uses the four original fields."""
    print("\nPlease enter the software request details.\n")
    request_cost = read_cost()
    requester_identity = read_required("Requester identity (eid): ")
    requester_email = read_email()
    manager_name = read_required("Manager name: ")
    software_name = read_required("Software name: ")
    business_justification = read_required("Business justification: ")
    requested_version = read_optional("Requested version (blank means latest approved): ")
    device_id = read_optional("Laptop/device ID (blank means registered employee device): ")
    license_details = read_optional("License details, if known (optional): ")

    return {
        "request_cost": request_cost,
        "cost_currency": "USD",
        "requester_identity": requester_identity,
        "requester_email": requester_email,
        "manager_name": manager_name,
        "policy_context": software_name,
        "business_justification": business_justification,
        "requested_version": requested_version,
        "device_id": device_id,
        "license_details": license_details,
    }


# ---------------------------------------------------------------------------
# Display helpers (read-only)
# ---------------------------------------------------------------------------
def role_of(workflow, index):
    """Stage 0 is always the requester's Manager; later stages use the approver's designation."""
    return "Manager" if index == 0 else workflow["approval_chain"][index]["job_designation"]


def employee_of(workflow):
    employee_id = requester_id_from(workflow["request"])
    record = get_employee(employee_id)
    return (record["name"] if record else "Unknown"), employee_id


def stage_text(workflow):
    index = workflow["current_approver_index"]
    total = len(workflow["approval_chain"])
    if workflow["status"] == "pending" and index < total:
        step = workflow["approval_chain"][index]
        if step["decision"] is not None:
            verdict = DECISION_LABELS[step["decision"]].lower()
            return (f"Stage {index + 1} of {total}: {step['name']} ({role_of(workflow, index)}) has {verdict} "
                    f"the request; awaiting Agent routing")
        return f"Stage {index + 1} of {total}: {role_of(workflow, index)}"
    return {"approved": "Completed (all approval stages done)",
            "rejected": "Stopped (request rejected)",
            "blocked": "Stopped (blocked by Agent)",
            "escalated": "Stopped (escalated, manual action required)"}.get(workflow["status"], "Completed")


def assigned_text(workflow):
    step = current_step(workflow) if workflow["status"] == "pending" else None
    if step and step["decision"] is not None:
        return "None (decision recorded; awaiting Agent routing)"
    return f"{step['name']} ({role_of(workflow, workflow['current_approver_index'])})" if step else "None"


def print_summary(workflow, indent=""):
    name, employee_id = employee_of(workflow)
    request = workflow["request"]
    print(f"{indent}Request ID:           {workflow['request_id']}")
    print(f"{indent}Employee:             {name} ({employee_id})")
    print(f"{indent}Requester email:      {request.get('requester_email', 'Not provided')}")
    print(f"{indent}Software:             {request.get('policy_context', 'Not provided')}")
    print(f"{indent}Request cost:         ${float(request['request_cost']):,.2f}")
    print(f"{indent}Cost currency:        {request.get('cost_currency', 'USD')}")
    print(f"{indent}Request status:       {workflow['status'].upper()}")
    print(f"{indent}Approval stage:       {stage_text(workflow)}")
    print(f"{indent}Assigned approver:    {assigned_text(workflow)}")


def print_progress(workflow, indent=""):
    print(f"{indent}Approval progress:")
    for i, step in enumerate(workflow["approval_chain"]):
        decision = DECISION_LABELS.get(step["decision"], "PENDING")
        line = f"{indent}  {i + 1}. {role_of(workflow, i)} - {step['name']}: {decision}"
        if step.get("decided_at"):
            line += f" at {step['decided_at']}"
        if decision != "PENDING" and workflow["status"] == "pending" and step.get("processed") is False:
            line += " (awaiting Agent routing)"
        print(line)
        if step.get("reason"):
            print(f"{indent}       Rejection reason: {step['reason']}")


def print_details(workflow, indent="  "):
    print_summary(workflow, indent)
    print(f"{indent}Business justification: {workflow['request'].get('business_justification', 'Not provided')}")
    print_progress(workflow, indent)
    status = workflow["status"]
    if status == "rejected":
        print(f"{indent}Rejection reason: {workflow.get('rejection_reason') or 'Not provided'}")
    release = workflow.get("budget_release")
    budget = ("APPROVED" if release and release.get("status") == "approved" else
              {"rejected": "REJECTED", "blocked": "BLOCKED", "escalated": "ESCALATED"}.get(status, "PENDING"))
    print(f"{indent}Budget approval:      {budget}")
    if release:
        print(f"{indent}Budget release:       {release['release_id']} ({release['approval_mode']})")
    if status == "approved":
        print(f"{indent}Next-stage handoff:   Budget approved. Software installation is NOT completed by this workflow.")
    else:
        print(f"{indent}Next-stage handoff:   Not started")
    print(f"{indent}Workflow history:")
    for entry in workflow["history"]:
        print(f"{indent}  {entry['timestamp']} {entry['event']:<10} {entry['actor']}: {entry['details']} [{entry.get('state', '')}]")


# ---------------------------------------------------------------------------
# 1. Create request
# ---------------------------------------------------------------------------
def create_request():
    outcome = submit_request(read_user_request())
    if not outcome["success"]:
        if outcome["error_type"] == "policy_retrieval":
            label = "Approval policy could not be retrieved from ChromaDB; no workflow was created"
        elif outcome["error_type"] == "technical":
            label = "Technical failure (agent unavailable); no request was created"
        else:
            label = "Request rejected by business rules; no request was created"
        print(f"\n{label}:\n  {outcome['error']}")
        return
    with lock:
        workflow = approval_workflows[outcome["request_id"]]
        print("\nRequest created successfully.")
        print_summary(workflow, "  ")


# ---------------------------------------------------------------------------
# 2. Employee portal (read-only)
# ---------------------------------------------------------------------------
def employee_portal():
    with lock:
        if not approval_workflows:
            print("\nNo employee request information is available.")
            return
        by_employee = {}
        for workflow in approval_workflows.values():
            by_employee.setdefault(employee_of(workflow), []).append(workflow)
        for (name, employee_id), workflows in by_employee.items():
            print(f"\n=== Employee: {name} ({employee_id}) ===")
            for workflow in workflows:
                print(f"\n  --- {workflow['request_id']} ---")
                print_details(workflow)


# ---------------------------------------------------------------------------
# 3-5. Approver portals (record decisions only)
# ---------------------------------------------------------------------------
def assigned_requests(role):
    """Pending requests whose current approver is this role and who have not yet decided."""
    found = []
    for workflow in approval_workflows.values():
        if workflow["status"] != "pending" or is_rejected(workflow):
            continue
        step = current_step(workflow)
        if step is None or step["decision"] is not None:
            continue
        if role_of(workflow, workflow["current_approver_index"]) == role:
            found.append(workflow)
    return found


def processed_requests(role):
    """Requests where this role's stage already has a decision (including terminal ones)."""
    found = []
    for workflow in approval_workflows.values():
        for i, step in enumerate(workflow["approval_chain"]):
            if role_of(workflow, i) == role and step["decision"] is not None:
                found.append(workflow)
                break
    return found


def actionable_error(workflow, role):
    """Interface-level checks; the workflow decision method re-validates independently."""
    if is_rejected(workflow):
        return REJECTED_MESSAGE
    if workflow["status"] != "pending":
        return f"This request is {workflow['status']} and cannot be modified."
    step = current_step(workflow)
    if step is None or role_of(workflow, workflow["current_approver_index"]) != role:
        return "This request is no longer assigned to you."
    if step["decision"] is not None:
        return "You have already recorded a decision for this request."
    return None


def decide(workflow, role):
    """Show the decision menu and record the decision. Does not advance the workflow."""
    request_id = workflow["request_id"]
    while True:
        with lock:
            error = actionable_error(workflow, role)
            if error:
                print(f"\n{error}")
                return
            print("\n--- Request details ---")
            print_details(workflow)
        print("\n1. Approve\n2. Disapprove\n3. Return to Previous Menu")
        choice = input("Select an option: ").strip()
        log.info("[%s] %s decision menu selection: %r", request_id, role, choice)
        if choice == "3":
            return
        if choice not in ("1", "2"):
            print("Invalid selection. Please choose 1, 2 or 3.")
            continue
        reason = None
        if choice == "2":
            reason = read_required("Rejection reason: ")
            while not is_meaningful_reason(reason):
                print(REASON_TOO_SHORT_MESSAGE)
                reason = read_required("Rejection reason: ")
        with lock:
            error = actionable_error(workflow, role)
            if error:
                print(f"\n{error}")
                return
            approver_id = current_step(workflow)["employee_id"]
            result = submit_decision(request_id, approver_id, "APPROVED" if choice == "1" else "REJECTED", reason)
        print(f"\n{'Decision recorded' if result['success'] else 'Decision not recorded'}: {result['message']}")
        return


def approver_portal(role):
    while True:
        with lock:
            assigned = assigned_requests(role)
            print(f"\n===== {role} Portal =====")
            if not assigned:
                print("No requests are currently assigned to you.")
            for i, workflow in enumerate(assigned, 1):
                print(f"\n[{i}]")
                print_summary(workflow, "  ")
                done = [f"{role_of(workflow, j)} {DECISION_LABELS[s['decision']]}"
                        for j, s in enumerate(workflow["approval_chain"]) if s["decision"] is not None]
                print(f"  Previous decisions:   {', '.join(done) if done else 'None'}")
        choice = input("Enter a request number, H for history, or B to go back: ").strip().lower()
        log.info("%s portal selection: %r", role, choice)
        if choice == "b":
            return
        if choice == "h":
            with lock:
                history = processed_requests(role)
                print(f"\n----- {role} request history -----")
                if not history:
                    print("No previously processed requests.")
                for workflow in history:
                    print(f"\n  --- {workflow['request_id']} ---")
                    print_details(workflow)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(assigned):
            decide(assigned[int(choice) - 1], role)
            continue
        print("Invalid selection.")


# ---------------------------------------------------------------------------
# Scheduler (the only component that executes workflow transitions)
# ---------------------------------------------------------------------------
def start_scheduler(stop_event):
    def run():
        log.info("Scheduler started (interval %ss)", SCHEDULER_INTERVAL_SECONDS)
        while not stop_event.wait(SCHEDULER_INTERVAL_SECONDS):
            process_workflows()
        log.info("Scheduler stopped")

    thread = threading.Thread(target=run, name="scheduler", daemon=True)
    thread.start()
    return thread


def main():
    setup_logging()
    log.info("Application started")
    stop_event = threading.Event()
    start_scheduler(stop_event)
    start_installation_scheduler(stop_event)
    portals = {"3": "Manager", "4": "IT Lead", "5": "Finance Director"}
    try:
        while True:
            print(MENU)
            choice = input("Select an option (1-10): ").strip()
            log.info("Menu selection: %r", choice)
            if choice == "1":
                create_request()
            elif choice == "2":
                employee_portal()
            elif choice in portals:
                approver_portal(portals[choice])
            elif choice == "6":
                run_fixture_demo(email_intake_demo)
            elif choice == "7":
                installation_status_board()
            elif choice == "8":
                review_it_packaging_requests()
            elif choice == "9":
                policy_assistant_portal()
            elif choice == "10":
                print("Exiting application.")
                break
            else:
                print("Invalid selection. Please enter a number from 1 to 10.")
    except (KeyboardInterrupt, EOFError):
        print("\nExiting application.")
    finally:
        stop_event.set()
        log.info("Application stopped")


if __name__ == "__main__":
    main()
