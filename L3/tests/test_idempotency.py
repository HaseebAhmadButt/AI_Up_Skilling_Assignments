"""Repeat-action safeguards for the simulated email and installation workflows."""
import unittest

from intake import EmailIntakeService
from installation import memory
from mock_data.notifications import (clear_notifications, mark_notification_delivered,
                                     send_notification, sent_notifications)


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        memory.refresh_fixtures()
        memory.installation_requests.clear()
        memory.it_pending_software.clear()
        memory.deployment_jobs.clear()
        memory.installed_user_software.clear()
        memory.completion_messages.clear()
        memory._completion_keys.clear()
        memory._it_approved_package_overrides.clear()
        memory._license_policy_overrides.clear()
        memory._license_allocations.clear()

    def tearDown(self):
        memory.installation_requests.clear()
        memory.it_pending_software.clear()
        memory.deployment_jobs.clear()
        memory.installed_user_software.clear()
        memory.completion_messages.clear()
        memory._completion_keys.clear()
        memory._it_approved_package_overrides.clear()
        memory._license_policy_overrides.clear()
        memory._license_allocations.clear()
        memory.refresh_fixtures()

    def test_duplicate_inbound_email_does_not_repeat_ack_or_create_request(self):
        service = EmailIntakeService()
        message = {"message_id": "idempotency-test-1", "from": "sara.khan@example.com",
                   "subject": "Install request", "body": "Software name: Figma"}
        first = service.process_message(message)
        second = service.process_message(message)
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(len(service.requests), 1)
        acknowledgements = [item for item in service.email.outbox if item["idempotency_key"] == "ack:idempotency-test-1"]
        self.assertEqual(len(acknowledgements), 1)

    def test_notification_queue_is_distinct_from_confirmed_delivery(self):
        clear_notifications()
        first = send_notification("E1001", "Approval needed", idempotency_key="notify-once")
        duplicate = send_notification("E1001", "Approval needed", idempotency_key="notify-once")
        self.assertEqual(first["notification_id"], duplicate["notification_id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(len(sent_notifications), 1)
        delivered = mark_notification_delivered(first["notification_id"])
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(sent_notifications[0]["status"], "delivered")
        clear_notifications()

    def test_repeated_offline_retry_adds_one_history_event(self):
        memory.device_registry["IDEMPOTENCY-DEVICE"] = {
            "device_id": "IDEMPOTENCY-DEVICE", "employee_id": "E1001", "online": False,
        }
        memory.installation_requests["REQ-IDEMPOTENCY"] = {
            "request_id": "REQ-IDEMPOTENCY", "device_id": "IDEMPOTENCY-DEVICE",
            "employee_id": "E1001", "requester_email": "sara.khan@example.com", "history": [],
        }
        memory.deployment_jobs["JOB-IDEMPOTENCY"] = {
            "job_id": "JOB-IDEMPOTENCY", "request_id": "REQ-IDEMPOTENCY",
            "device_id": "IDEMPOTENCY-DEVICE", "installation_result": None,
        }
        memory.simulate_job("JOB-IDEMPOTENCY")
        memory.simulate_job("JOB-IDEMPOTENCY")
        events = [event for event in memory.installation_requests["REQ-IDEMPOTENCY"]["history"]
                  if event["event"] == "device_offline"]
        self.assertEqual(len(events), 1)

    def test_deployment_job_is_reused_and_request_cannot_get_second_job(self):
        memory.installation_requests["REQ-JOB"] = {
            "request_id": "REQ-JOB", "software_name": "Figma", "employee_id": "E1001",
            "requester_email": "sara.khan@example.com", "history": [],
        }
        first, created = memory.create_or_get_job("REQ-JOB", "DEV-E1001-01", "figma-desktop", "1.1.0")
        second, created_again = memory.create_or_get_job("REQ-JOB", "DEV-E1001-01", "figma-desktop", "1.1.0")
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["job_id"], second["job_id"])
        with self.assertRaises(ValueError):
            memory.create_or_get_job("REQ-JOB", "DEV-E1001-01", "figma-desktop", "1.0.0")
        accepted = [event for event in memory.installation_requests["REQ-JOB"]["history"]
                    if event["event"] == "deployment_job_accepted"]
        self.assertEqual(len(accepted), 1)

    def test_repeated_verification_sends_one_completion_message(self):
        memory.installation_requests["REQ-RESULT"] = {
            "request_id": "REQ-RESULT", "software_name": "Figma", "employee_id": "E1001",
            "requester_email": "sara.khan@example.com", "approval_chain": [], "history": [],
        }
        memory.device_registry["DEV-E1001-01"].update(online=True, ready=True)
        job, _ = memory.create_or_get_job("REQ-RESULT", "DEV-E1001-01", "figma-desktop", "1.1.0")
        memory.simulate_job(job["job_id"])
        first = memory.verify_job(job["job_id"])
        second = memory.verify_job(job["job_id"])
        self.assertTrue(first["success"])
        self.assertEqual(first, second)
        self.assertEqual(len(memory.completion_messages), 1)
        sent = [event for event in memory.installation_requests["REQ-RESULT"]["history"]
                if event["event"] == "completion_message_sent"]
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
