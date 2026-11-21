"""Fixture-based email intake layered over the existing L3 approval workflow."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from mock_data import get_employee
from mock_data.employees import EMPLOYEES
from installation import memory as installation_memory
from workflow.store import get_workflow, next_request_id
from workflow.submission import submit_request
from workflow.workflow_tools import current_step


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "inbound_emails.json"
FIELD_LABELS = {
    "request cost": "request_cost",
    "requester identity": "requester_identity",
    "manager name": "manager_name",
    "software name": "software_name",
    "business justification": "business_justification",
    "software version": "requested_version",
    "requested version": "requested_version",
    "laptop identity": "device_id",
    "device id": "device_id",
    "request currency": "cost_currency",
    "currency": "cost_currency",
    "licensing details": "license_details",
}
REQUIRED_FIELDS = ("request_cost", "cost_currency", "requester_identity", "manager_name",
                   "software_name", "business_justification")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_request_fields(body: str) -> dict[str, str]:
    """Parse fixture email lines such as ``Software name: Figma``."""
    values = {}
    for line in body.splitlines():
        label, separator, value = line.partition(":")
        field_name = FIELD_LABELS.get(" ".join(label.strip().lower().split()))
        if separator and field_name and value.strip():
            values[field_name] = value.strip()
            if field_name == "request_cost" and value.strip().startswith("$"):
                values.setdefault("cost_currency", "USD")
    return values


class SimulatedEmailAdapter:
    """Local inbox/outbox fixture adapter; no network mail is sent or received."""

    def __init__(self):
        self.outbox = []
        self._sent_keys = set()

    def send_once(self, *, to: str, subject: str, body: str, idempotency_key: str) -> bool:
        if idempotency_key in self._sent_keys:
            return False
        self._sent_keys.add(idempotency_key)
        self.outbox.append({"to": to, "subject": subject, "body": body,
                            "idempotency_key": idempotency_key, "sent_at": _now()})
        return True


class EmailIntakeService:
    """Track fixture emails and carry one request ID through intake and L3 approvals."""

    def __init__(self, email_adapter=None, route_fn=None):
        self.email = email_adapter or SimulatedEmailAdapter()
        self.route_fn = route_fn
        self.requests = {}
        self.message_to_request = {}
        self.processed_message_ids = set()
        self._lock = threading.RLock()

    @staticmethod
    def _requester_id_for_email(address: str):
        address = address.strip().lower()
        return next((employee_id for employee_id, employee in EMPLOYEES.items()
                     if employee["email"].lower() == address), None)

    @staticmethod
    def _missing_fields(fields):
        return [field for field in REQUIRED_FIELDS if not str(fields.get(field, "")).strip()]

    def _history(self, record, event, actor, details):
        record["history"].append({"timestamp": _now(), "event": event,
                                  "actor": actor, "details": details})

    def _send(self, record, subject, body, key, event_name):
        if self.email.send_once(to=record["requester_email"], subject=subject, body=body,
                                idempotency_key=key):
            self._history(record, event_name, "simulated_email", subject)

    def process_message(self, message: dict) -> dict:
        """Process one simulated inbound email or authorized reply idempotently."""
        with self._lock:
            return self._process_message_locked(message)

    def _process_message_locked(self, message: dict) -> dict:
        message_id = str(message.get("message_id", "")).strip()
        sender = str(message.get("from", "")).strip().lower()
        if not message_id or not sender:
            raise ValueError("Fixture email requires message_id and from fields")
        if message_id in self.processed_message_ids:
            request_id = self.message_to_request.get(message_id)
            return self.get_request(request_id) if request_id else {"status": "ignored"}

        parent_id = str(message.get("in_reply_to", "")).strip()
        request_id = self.message_to_request.get(parent_id) if parent_id else None
        if request_id:
            return self._process_reply(message, message_id, sender, request_id)
        return self._process_new_request(message, message_id, sender)

    def _process_new_request(self, message, message_id, sender):
        requester_id = self._requester_id_for_email(sender)
        fields = parse_request_fields(str(message.get("body", "")))
        if requester_id:
            fields.setdefault("requester_identity", requester_id)

        request_id = next_request_id()
        record = {
            "request_id": request_id,
            "source_message_id": message_id,
            "requester_email": sender,
            "requester_id": requester_id,
            "fields": fields,
            "status": "intake",
            "owner": "Intake",
            "next_action": "Validate sender and request details",
            "history": [],
        }
        self.requests[request_id] = record
        self.message_to_request[message_id] = request_id
        self.processed_message_ids.add(message_id)
        self._history(record, "email_received", sender, str(message.get("subject", "New software request")))
        self._send(record, f"Request received: {request_id}",
                   f"We received your software request. Tracking ID: {request_id}.",
                   f"ack:{message_id}", "acknowledgement_sent")

        if requester_id is None:
            record.update(status="blocked", owner="Intake review",
                          next_action="Verify sender against the employee directory")
            self._history(record, "identity_unverified", "intake", "Sender email is not in the fixture employee directory.")
            return self.get_request(request_id)

        self._continue_intake(record)
        return self.get_request(request_id)

    def _process_reply(self, message, message_id, sender, request_id):
        record = self.requests[request_id]
        self.processed_message_ids.add(message_id)
        self.message_to_request[message_id] = request_id
        if sender != record["requester_email"]:
            self._history(record, "unauthorized_reply_ignored", sender,
                          f"Reply {message_id} did not come from the requester's recorded address.")
            return self.get_request(request_id)

        record["fields"].update(parse_request_fields(str(message.get("body", ""))))
        self._history(record, "details_received", sender, f"Authorized reply {message_id} attached to this request.")
        self._continue_intake(record)
        if record["status"] == "awaiting_details":
            self._ask_for_details(record)
        else:
            self._send(record, f"Request updated: {request_id}",
                       f"Your reply was added to request {request_id}. Current status: {record['status']}.",
                       f"update:{message_id}", "update_acknowledged")
        return self.get_request(request_id)

    def _ask_for_details(self, record):
        missing = self._missing_fields(record["fields"])
        labels = [next(label for label, field in FIELD_LABELS.items() if field == name) for name in missing]
        prompt = "Please reply to this message and provide: " + ", ".join(labels) + "."
        self._send(record, f"More information needed: {record['request_id']}", prompt,
                   f"details:{record['request_id']}:{','.join(missing)}", "details_requested")

    def _continue_intake(self, record):
        if get_workflow(record["request_id"]):
            return
        missing = self._missing_fields(record["fields"])
        if missing:
            record.update(status="awaiting_details", owner=record["requester_email"],
                          next_action="Reply with: " + ", ".join(missing))
            self._ask_for_details(record)
            return

        fields = record["fields"]
        employee_id = str(fields["requester_identity"]).split(",", 1)[0].strip().upper()
        assigned_device = installation_memory.find_device_for_employee(employee_id)
        requested_device = str(fields.get("device_id", "")).strip()
        if requested_device and (assigned_device is None or requested_device != assigned_device["device_id"]):
            record.update(status="blocked", owner="Intake review",
                          next_action="Confirm the laptop identity against the registered employee device")
            self._history(record, "device_identity_unverified", "intake",
                          f"Submitted device {requested_device} does not match the registered device.")
            return
        if assigned_device:
            fields["device_id"] = assigned_device["device_id"]
        request = {
            "request_cost": fields["request_cost"],
            "requester_identity": fields["requester_identity"],
            "requester_email": record["requester_email"],
            "manager_name": fields["manager_name"],
            "policy_context": fields["software_name"],
            "business_justification": fields["business_justification"],
            "cost_currency": fields["cost_currency"].upper(),
            "device_id": fields.get("device_id"),
            "requested_version": fields.get("requested_version"),
            "license_details": fields.get("license_details"),
        }
        outcome = submit_request(request, route_fn=self.route_fn, request_id=record["request_id"])
        if not outcome["success"]:
            record.update(status="blocked", owner="Intake review", next_action=outcome["error"])
            self._history(record, "request_not_submitted", "intake", outcome["error"])
            return

        workflow = get_workflow(record["request_id"])
        record["status"] = workflow["status"]
        record["owner"] = current_step(workflow)["name"]
        record["next_action"] = f"Await {current_step(workflow)['job_designation']} approval"
        self._history(record, "approval_workflow_started", "intake", "Request submitted to the existing L3 approval workflow.")

    def get_request(self, request_id):
        if request_id is None or request_id not in self.requests:
            return {"status": "not_found"}
        record = self.requests[request_id]
        result = {**record, "fields": dict(record["fields"]), "history": list(record["history"])}
        workflow = get_workflow(request_id)
        if workflow:
            result["status"] = workflow["status"]
            result["history"] = result["history"] + list(workflow["history"])
            step = current_step(workflow) if workflow["status"] == "pending" else None
            if step:
                result["owner"] = step["name"]
                result["next_action"] = (f"Approval recorded; awaiting routing for {step['job_designation']}"
                                          if step["decision"] is not None
                                          else f"Await {step['job_designation']} approval")
            else:
                result["owner"] = "L3 service"
                result["next_action"] = "Continue to prerequisite checks after approval" if workflow["status"] == "approved" else workflow["status"]
        return result

    def list_requests(self):
        return [self.get_request(request_id) for request_id in self.requests]


def load_fixture_messages(path: Path = FIXTURE_PATH) -> list[dict]:
    """Load the repeatable inbox sequence used by the L3 menu demo."""
    return json.loads(path.read_text(encoding="utf-8"))


def print_request(record):
    print(f"\nRequest {record['request_id']}: {record['status']}")
    print(f"  Owner: {record['owner']}")
    print(f"  Next action: {record['next_action']}")
    print("  History:")
    for event in record["history"]:
        print(f"    {event['timestamp']} {event['event']} — {event['actor']}: {event['details']}")


def run_fixture_demo(service: EmailIntakeService):
    for message in load_fixture_messages():
        print_request(service.process_message(message))
    print(f"\nSimulated email outbox: {len(service.email.outbox)} message(s); no real email was sent.")
