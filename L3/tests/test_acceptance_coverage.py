"""Acceptance scenarios for the L3 intake, approval, and simulated deployment paths."""
import unittest

from installation import memory
from installation.scheduler import process_installation_workflows
from installation.tools import queue_user_scope_install
from intake import EmailIntakeService
from mock_data import clear_notifications
from workflow.scheduler import process_workflows
from workflow.store import approval_workflows, clear_workflows
from workflow.submission import submit_request
from workflow.workflow_tools import submit_decision

from tests.test_workflow import fake_agent, fake_router, make_request


class IntakeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        clear_workflows()
        clear_notifications()

    def test_incomplete_email_duplicate_and_authorized_clarification_share_one_request(self):
        service = EmailIntakeService(route_fn=fake_agent)
        original = {"message_id": "acceptance-mail-1", "from": "sara.khan@example.com",
                    "subject": "Software request", "body": "Software name: Figma"}
        first = service.process_message(original)
        duplicate = service.process_message(original)
        self.assertEqual(first["status"], "awaiting_details")
        self.assertEqual(first["request_id"], duplicate["request_id"])
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(sum(item["idempotency_key"] == "ack:acceptance-mail-1"
                             for item in service.email.outbox), 1)

        reply = {"message_id": "acceptance-mail-2", "in_reply_to": "acceptance-mail-1",
                 "from": "sara.khan@example.com", "body": "Request cost: $400\n"
                 "Manager name: Ali Raza\nBusiness justification: Required for design work"}
        updated = service.process_message(reply)
        self.assertEqual(updated["request_id"], first["request_id"])
        self.assertIn("approval_workflow_started", [event["event"] for event in updated["history"]])
        self.assertEqual(len(approval_workflows), 1)

    def test_unauthorized_email_reply_is_ignored_and_audited(self):
        service = EmailIntakeService()
        original = {"message_id": "acceptance-mail-3", "from": "sara.khan@example.com",
                    "body": "Software name: Figma"}
        record = service.process_message(original)
        reply = {"message_id": "acceptance-mail-4", "in_reply_to": "acceptance-mail-3",
                 "from": "haseeb.ahmad@example.com", "body": "Request cost: 400"}
        updated = service.process_message(reply)
        self.assertEqual(updated["fields"].get("request_cost"), None)
        self.assertIn("unauthorized_reply_ignored", [event["event"] for event in updated["history"]])
        self.assertEqual(updated["request_id"], record["request_id"])

    def test_email_captures_version_device_currency_and_license_notes(self):
        service = EmailIntakeService(route_fn=fake_agent)
        message = {"message_id": "acceptance-mail-details", "from": "sara.khan@example.com",
                   "body": "Software name: Figma\nRequest cost: $400\nManager name: Ali Raza\n"
                           "Business justification: Design work\nSoftware version: latest\n"
                           "Laptop identity: DEV-E1001-01\nLicensing details: Named user"}
        result = service.process_message(message)
        request = approval_workflows[result["request_id"]]["request"]
        self.assertEqual(request["cost_currency"], "USD")
        self.assertEqual(request["requested_version"], "latest")
        self.assertEqual(request["device_id"], "DEV-E1001-01")
        self.assertEqual(request["license_details"], "Named user")

    def test_email_cost_without_currency_requests_clarification(self):
        service = EmailIntakeService()
        result = service.process_message({"message_id": "acceptance-mail-currency",
                                         "from": "sara.khan@example.com",
                                         "body": "Software name: Figma\nRequest cost: 400"})
        self.assertEqual(result["status"], "awaiting_details")
        self.assertIn("cost_currency", result["next_action"])

    def test_explicit_wrong_laptop_identity_is_not_guessed_around(self):
        service = EmailIntakeService(route_fn=fake_agent)
        result = service.process_message({"message_id": "acceptance-mail-device",
                                          "from": "sara.khan@example.com",
                                          "body": "Software name: Figma\nRequest cost: $400\n"
                                                  "Manager name: Ali Raza\nBusiness justification: Design work\n"
                                                  "Laptop identity: DEV-E1002-01"})
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn(result["request_id"], approval_workflows)
        self.assertIn("device_identity_unverified", [event["event"] for event in result["history"]])


class ApprovalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        clear_workflows()
        clear_notifications()

    def test_paid_request_routes_in_order_and_records_authorized_decisions(self):
        outcome = submit_request(make_request(3000), route_fn=fake_agent)
        workflow = approval_workflows[outcome["request_id"]]
        self.assertEqual([entry["employee_id"] for entry in workflow["approval_chain"]],
                         ["E2001", "E3001", "E4001"])
        for expected in ("E2001", "E3001", "E4001"):
            result = submit_decision(outcome["request_id"], expected, "APPROVED")
            self.assertTrue(result["success"])
            process_workflows(next_step_fn=fake_router)
        self.assertEqual(workflow["status"], "approved")
        self.assertEqual([event["actor"] for event in workflow["history"] if event["event"] == "approve"],
                         ["E2001", "E3001", "E4001"])

    def test_rejection_stops_route_and_install_handoff(self):
        outcome = submit_request(make_request(3000), route_fn=fake_agent)
        rid = outcome["request_id"]
        result = submit_decision(rid, "E2001", "REJECTED", "Not needed this quarter")
        self.assertTrue(result["success"])
        process_workflows(next_step_fn=fake_router)
        self.assertEqual(approval_workflows[rid]["status"], "rejected")
        self.assertEqual(approval_workflows[rid]["current_approver_index"], 0)
        self.assertNotIn(rid, memory.installation_requests)


class DeploymentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        approval_workflows.clear()
        memory.refresh_fixtures()
        memory.installation_requests.clear()
        memory.it_pending_software.clear()
        memory.deployment_jobs.clear()
        memory.installed_user_software.clear()
        memory.completion_messages.clear()
        memory._completion_keys.clear()
        memory._it_approved_package_overrides.clear()
        memory._license_allocations.clear()
        memory._license_policy_overrides.clear()
        memory._external_result_events.clear()
        memory.refresh_fixtures()

    def tearDown(self):
        approval_workflows.clear()
        memory.installation_requests.clear()
        memory.it_pending_software.clear()
        memory.deployment_jobs.clear()
        memory.installed_user_software.clear()
        memory.completion_messages.clear()
        memory._completion_keys.clear()
        memory._it_approved_package_overrides.clear()
        memory._license_allocations.clear()
        memory._license_policy_overrides.clear()
        memory._external_result_events.clear()
        memory.refresh_fixtures()

    def register(self, request_id="REQ-ACCEPT", employee_id="E1001", software="Figma"):
        from mock_data import get_employee
        employee = get_employee(employee_id)
        chain = [{"employee_id": "E2001", "decision": "APPROVED"}]
        workflow = {"request_id": request_id, "status": "approved", "approval_chain": chain,
                    "request": {"requester_identity": employee_id, "requester_email": employee["email"],
                                "policy_context": software, "request_cost": 400}}
        return memory.register_approved_request(workflow)

    def test_accepted_job_does_not_close_until_matching_version_is_verified_once(self):
        request = self.register()
        job, _ = memory.create_or_get_job(request["request_id"], "DEV-E1001-01", "figma-desktop", "1.1.0")
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "job_accepted")
        self.assertEqual(memory.completion_messages, [])
        memory.simulate_job(job["job_id"])
        result = memory.verify_job(job["job_id"])
        again = memory.verify_job(job["job_id"])
        self.assertTrue(result["success"])
        self.assertEqual(result, again)
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "completed")
        self.assertEqual(len(memory.completion_messages), 1)

    def test_scheduler_handoff_runs_agent_work_to_verified_closure(self):
        request_id = "REQ-SCHEDULED"
        workflow = {"request_id": request_id, "status": "approved",
                    "approval_chain": [{"employee_id": "E2001", "decision": "APPROVED"}],
                    "request": {"requester_identity": "E1001, Marketing Analyst, Marketing",
                                "requester_email": "sara.khan@example.com", "policy_context": "Figma",
                                "request_cost": 400}}
        approval_workflows[request_id] = workflow

        def simulated_agent(request_id):
            context = memory.get_installation_request(request_id)
            device = memory.find_device_for_employee(context["employee_id"])
            choices = memory.list_approved_versions(context["software_name"], device["device_id"])
            license_result = memory.ensure_license_entitlement(request_id)
            if not license_result["success"]:
                return
            version = choices["versions"][0]["version"]
            queued = queue_user_scope_install.invoke({"request_id": request_id,
                                                       "device_id": device["device_id"],
                                                       "package_id": choices["package_id"],
                                                       "version": version})
            memory.simulate_job(queued["job"]["job_id"])
            memory.verify_job(queued["job"]["job_id"])

        summary = process_installation_workflows(agent_fn=simulated_agent)
        self.assertIn(request_id, summary["registered"])
        self.assertIn(request_id, summary["invoked"])
        self.assertEqual(memory.get_installation_request(request_id)["status"], "completed")
        self.assertEqual(len(memory.completion_messages), 1)

    def test_wrong_installed_version_fails_verification_and_stays_open(self):
        request = self.register()
        job, _ = memory.create_or_get_job(request["request_id"], "DEV-E1001-01", "figma-desktop", "1.1.0")
        memory.simulate_job(job["job_id"])
        stored_job = memory.deployment_jobs[job["job_id"]]
        stored_job["installation_result"]["version"] = "9.9.9"
        result = memory.verify_job(job["job_id"])
        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["version_matches"])
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "verification_failed")
        self.assertEqual(memory.completion_messages, [])

    def test_offline_job_retries_when_device_returns_online(self):
        request = self.register("REQ-OFFLINE", "E1002")
        device_id = "DEV-E1002-01"
        job, _ = memory.create_or_get_job(request["request_id"], device_id, "figma-desktop", "1.1.0")
        memory.device_registry[device_id]["online"] = False
        first = memory.simulate_job(job["job_id"])
        second = memory.simulate_job(job["job_id"])
        self.assertEqual(first["status"], "waiting_for_device")
        self.assertEqual(second["status"], "waiting_for_device")
        events = [event for event in memory.installation_requests[request["request_id"]]["history"]
                  if event["event"] == "device_offline"]
        self.assertEqual(len(events), 1)
        memory.device_registry[device_id]["online"] = True
        result = memory.simulate_job(job["job_id"])
        self.assertTrue(result["success"])
        self.assertTrue(memory.verify_job(job["job_id"])["success"])

    def test_missing_package_waits_then_it_approval_publishes_and_requeues(self):
        request = self.register("REQ-PACKAGE", software="New Prototype App")
        device_id = "DEV-E1001-01"
        item = memory.add_it_pending_item(request["request_id"], device_id, "No approved package is available")
        self.assertEqual(item["status"], "pending")
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "waiting_for_package")
        decision = memory.decide_it_pending_item(request["request_id"], "approve",
                                                 package_id="prototype-app-user", version="2.0.0",
                                                 license_required=True, seat_limit=2)
        self.assertTrue(decision["success"])
        memory.refresh_fixtures()
        versions = memory.list_approved_versions("New Prototype App", device_id)["versions"]
        self.assertEqual(versions[0]["version"], "2.0.0")
        self.assertIn(request["request_id"], [item["request_id"] for item in memory.list_agent_work()])
        self.assertTrue(memory.ensure_license_entitlement(request["request_id"])["success"])
        queued = queue_user_scope_install.invoke({"request_id": request["request_id"],
                                                  "device_id": device_id,
                                                  "package_id": "prototype-app-user", "version": "2.0.0"})
        self.assertTrue(queued["success"])
        memory.simulate_job(queued["job"]["job_id"])
        self.assertTrue(memory.verify_job(queued["job"]["job_id"])["success"])
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "completed")

    def test_unapproved_request_cannot_queue_deployment(self):
        request = self.register("REQ-UNAPPROVED")
        memory.installation_requests[request["request_id"]]["approval_chain"][0]["decision"] = "PENDING"
        result = queue_user_scope_install.invoke({"request_id": request["request_id"],
                                                  "device_id": "DEV-E1001-01",
                                                  "package_id": "figma-desktop", "version": "1.1.0"})
        self.assertFalse(result["success"])
        self.assertEqual(memory.deployment_jobs, {})

    def test_unsupported_os_has_no_eligible_approved_versions(self):
        memory.device_registry["DEV-E1001-01"]["os"] = "UnsupportedOS"
        result = memory.list_approved_versions("Figma", "DEV-E1001-01")
        self.assertEqual(result["versions"], [])

    def test_it_rejection_is_recorded_and_does_not_make_package_available(self):
        request = self.register("REQ-PACKAGE-REJECT", software="Unpackaged Tool")
        item = memory.add_it_pending_item(request["request_id"], "DEV-E1001-01", "Package review needed")
        result = memory.decide_it_pending_item(request["request_id"], "reject")
        self.assertTrue(result["success"])
        self.assertEqual(memory.it_pending_software[request["request_id"]]["status"], "rejected")
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "package_rejected")
        self.assertEqual(memory.list_approved_versions("Unpackaged Tool", item["device_id"])["versions"], [])

    def test_user_scope_and_no_admin_are_enforced_and_verified(self):
        request = self.register("REQ-USER-SCOPE")
        self.assertTrue(memory.ensure_license_entitlement(request["request_id"])["success"])
        device_id = "DEV-E1001-01"
        memory.device_registry[device_id]["requires_admin_for_user_install"] = True
        blocked = queue_user_scope_install.invoke({"request_id": request["request_id"],
                                                   "device_id": device_id,
                                                   "package_id": "figma-desktop", "version": "1.1.0"})
        self.assertFalse(blocked["success"])
        self.assertEqual(memory.deployment_jobs, {})
        memory.device_registry[device_id]["requires_admin_for_user_install"] = False
        job, _ = memory.create_or_get_job(request["request_id"], device_id, "figma-desktop", "1.1.0")
        self.assertEqual((job["install_scope"], job["requires_admin"]), ("user", False))
        memory.simulate_job(job["job_id"])
        result = memory.verify_job(job["job_id"])
        self.assertTrue(result["checks"]["user_scope_only"])
        self.assertTrue(result["checks"]["no_admin_required"])

    def test_existing_license_exception_and_available_seat_are_explicitly_verified(self):
        existing = self.register("REQ-LICENSE-EXISTING", "E1001")
        same = memory.ensure_license_entitlement(existing["request_id"])
        self.assertTrue(same["success"])
        self.assertEqual(same["source"], "existing_entitlement_exception")
        self.assertEqual(memory.ensure_license_entitlement(existing["request_id"]), same)

        new_user = self.register("REQ-LICENSE-NEW", "E1004")
        allocated = memory.ensure_license_entitlement(new_user["request_id"])
        self.assertTrue(allocated["success"])
        self.assertEqual(allocated["source"], "new_seat_allocated")
        self.assertIn("E1004", memory.license_entitlements["figma"]["assigned_users"])

    def test_missing_license_entitlement_holds_request_open(self):
        request = self.register("REQ-LICENSE-EMPTY", "E1001", software="Slack")
        result = memory.ensure_license_entitlement(request["request_id"])
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "waiting_for_license")

    def test_installation_retries_are_bounded_and_exhaustion_is_visible(self):
        request = self.register("REQ-RETRY", "E1006")
        job, _ = memory.create_or_get_job(request["request_id"], "DEV-E1006-01", "figma-desktop", "1.1.0")
        for attempt in range(1, memory.MAX_INSTALL_ATTEMPTS + 1):
            failed = memory.simulate_job(job["job_id"])
            self.assertFalse(failed["success"])
            if attempt < memory.MAX_INSTALL_ATTEMPTS:
                self.assertTrue(memory.retry_failed_installation(job["job_id"])["success"])
        exhausted = memory.retry_failed_installation(job["job_id"])
        self.assertFalse(exhausted["success"])
        self.assertEqual(exhausted["status"], "install_exhausted")
        state = memory.get_installation_request(request["request_id"])
        self.assertEqual(state["owner"], "IT support")
        self.assertEqual(len([event for event in state["history"]
                              if event["event"] == "installation_retries_exhausted"]), 1)

    def test_external_results_are_idempotent_and_mismatches_cannot_close_request(self):
        request = self.register("REQ-EXTERNAL")
        job, _ = memory.create_or_get_job(request["request_id"], "DEV-E1001-01", "figma-desktop", "1.1.0")
        payload = {"request_id": request["request_id"], "device_id": "DEV-E1001-01",
                   "employee_id": "E1001", "user_account": "sara.khan@example.com",
                   "package_id": "figma-desktop", "version": "9.9.9", "success": True,
                   "attempt": 1,
                   "install_scope": "user", "requires_admin": False,
                   "checks": {"user_profile_install": True, "application_launch": True}}
        bad = {**payload, "device_id": "DEV-E1002-01"}
        rejected = memory.record_external_result(job["job_id"], "event-bad", bad)
        self.assertFalse(rejected["success"])
        self.assertIsNone(memory.get_job(job["job_id"])["installation_result"])
        accepted = memory.record_external_result(job["job_id"], "event-good", payload)
        duplicate = memory.record_external_result(job["job_id"], "event-good", payload)
        self.assertTrue(accepted["success"])
        self.assertEqual(accepted, duplicate)
        verification = memory.verify_job(job["job_id"])
        self.assertFalse(verification["success"])
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "verification_failed")
        late = memory.record_external_result(job["job_id"], "event-late", payload)
        self.assertFalse(late["success"])
        self.assertEqual(memory.completion_messages, [])

    def test_failed_installation_result_is_cached_and_never_closes(self):
        request = self.register("REQ-FAILED", "E1006")
        job, _ = memory.create_or_get_job(request["request_id"], "DEV-E1006-01", "figma-desktop", "1.1.0")
        first = memory.simulate_job(job["job_id"])
        second = memory.simulate_job(job["job_id"])
        self.assertFalse(first["success"])
        self.assertEqual(first, second)
        self.assertEqual(memory.get_installation_request(request["request_id"])["status"], "install_failed")
        self.assertEqual(memory.completion_messages, [])


if __name__ == "__main__":
    unittest.main()
