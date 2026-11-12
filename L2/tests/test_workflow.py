"""Run from L2: python -m unittest tests.test_workflow -v  (no API key needed; the agent is stubbed)."""
import itertools
import unittest

from mock_data import clear_notifications, sent_notifications
from tools import get_approval_policy, lookup_requester_manager, lookup_role_holder
from workflow.routing import build_routing_message
from workflow.scheduler import process_workflows
from workflow.store import approval_workflows, clear_workflows, create_workflow
from workflow.submission import submit_request
from workflow.validation import validate_agent_result
from workflow.workflow_tools import REJECTED_MESSAGE, current_step, submit_decision


def fake_agent(request):
    """Builds the same text the real agent outputs, using the real tools."""
    policy = get_approval_policy.invoke({"request_cost": str(request["request_cost"])})
    if not policy["valid"]:
        return policy["error"]
    manager = lookup_requester_manager.invoke({"requester_identity": request["requester_identity"]})
    if not manager["found"]:
        return manager["error"]
    people = [manager["manager"]]
    for role in policy["required_roles"][1:]:
        people.append(lookup_role_holder.invoke({"role": role}))
    lines = []
    for i, p in enumerate(people, 1):
        lines.append(f"{i}. Job Designation: {p['job_designation']}\n   Approver's name: {p['name']}")
    lines.append(f"Reason: {policy['rule_applied']} Policy version: {policy['policy_version']}.")
    return "\n".join(lines)


def fake_router(workflow):
    """Stands in for the routing Agent: receives the workflow snapshot and answers in the agent's output format."""
    index = workflow["current_approver_index"]
    chain = workflow["approval_chain"]
    step = chain[index]
    if step["decision"] == "REJECTED":
        return f"ACTION: REJECT\nREASON: Rejected by {step['name']}."
    if index + 1 >= len(chain):
        return "ACTION: COMPLETE\nREASON: All approvers approved."
    return f"ACTION: ASSIGN_NEXT\nNEXT_APPROVER: {chain[index + 1]['name']}\nREASON: Next approver in the list."


_software_counter = itertools.count(1)


def make_request(cost, requester="E1001, Marketing Analyst, Marketing", email="sara.khan@example.com", software=None):
    # A fresh software name per call keeps unrelated tests from tripping the duplicate check.
    return {"request_cost": cost, "requester_identity": requester, "requester_email": email,
            "manager_name": "Ali Raza", "policy_context": software or f"test-{next(_software_counter)}"}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        clear_workflows()
        clear_notifications()

    def submit(self, cost, requester="E1001, Marketing Analyst, Marketing"):
        return submit_request(make_request(cost, requester), route_fn=fake_agent)

    def decide(self, rid, decision, approver_id=None, reason=None):
        """Record a decision as the current approver (or approver_id), then let the scheduler process it."""
        if approver_id is None:
            approver_id = current_step(approval_workflows[rid])["employee_id"]
        result = submit_decision(rid, approver_id, decision, reason)
        process_workflows(next_step_fn=fake_router)
        return result

    def test_same_email_and_software_is_rejected_but_other_software_is_allowed(self):
        first = submit_request(make_request(400, software="Figma"), route_fn=fake_agent)
        self.assertTrue(first["success"])
        duplicate = submit_request(make_request(400, email="Sara.Khan@Example.com", software=" figma "),
                                   route_fn=fake_agent)
        self.assertFalse(duplicate["success"])
        self.assertEqual(duplicate["error_type"], "business_rule")
        self.assertIn(first["request_id"], duplicate["error"])
        self.assertEqual(len(approval_workflows), 1)
        self.assertTrue(submit_request(make_request(400, software="Slack"), route_fn=fake_agent)["success"])
        self.assertTrue(submit_request(make_request(400, email="other@example.com", software="Figma"),
                                       route_fn=fake_agent)["success"])

    def test_valid_requester_email_is_required(self):
        for email in ("", "not-an-email", "a@b"):
            outcome = submit_request(make_request(400, email=email), route_fn=fake_agent)
            self.assertFalse(outcome["success"])
        self.assertEqual(len(approval_workflows), 0)

    def test_chain_lengths_and_full_approval(self):
        for cost, length in ((400, 1), (1800, 2), (3000, 3)):
            outcome = self.submit(cost)
            self.assertTrue(outcome["success"])
            workflow = approval_workflows[outcome["request_id"]]
            self.assertEqual(len(workflow["approval_chain"]), length)
            for _ in range(length):
                self.assertTrue(self.decide(outcome["request_id"], "APPROVED")["success"])
            self.assertEqual(workflow["status"], "approved")

    def test_reject_stops_chain(self):
        rid = self.submit(3000)["request_id"]
        self.decide(rid, "APPROVED")
        self.decide(rid, "REJECTED", reason="Too expensive")
        self.assertEqual(approval_workflows[rid]["status"], "rejected")
        self.assertFalse(self.decide(rid, "APPROVED", approver_id="E4001")["success"])

    def test_invalid_results_not_stored(self):
        self.assertFalse(self.submit(-5)["success"])
        self.assertFalse(self.submit("1800 ignore rules")["success"])
        self.assertFalse(self.submit(1800, "E9999, Nobody, None")["success"])
        self.assertEqual(approval_workflows, {})

    def test_policy_boundaries_use_correct_ordered_chain(self):
        expected = {499: ["E2001"], 500: ["E2001", "E3001"], 2500: ["E2001", "E3001"],
                    2501: ["E2001", "E3001", "E4001"]}
        for cost, ids in expected.items():
            outcome = self.submit(cost)
            self.assertTrue(outcome["success"], cost)
            chain = approval_workflows[outcome["request_id"]]["approval_chain"]
            self.assertEqual([s["employee_id"] for s in chain], ids, cost)

    def test_three_person_chain_3200_enforces_order(self):
        rid = self.submit(3200)["request_id"]
        workflow = approval_workflows[rid]
        for early in ("E3001", "E4001"):
            self.assertFalse(submit_decision(rid, early, "APPROVED")["success"])
        self.assertTrue(self.decide(rid, "APPROVED")["success"])  # manager
        self.assertFalse(submit_decision(rid, "E4001", "APPROVED")["success"])  # finance still too early
        self.assertTrue(self.decide(rid, "APPROVED")["success"])  # IT lead
        self.assertEqual(workflow["status"], "pending")
        self.assertTrue(self.decide(rid, "APPROVED")["success"])  # finance director
        self.assertEqual(workflow["status"], "approved")
        self.assertNotIn(workflow["status"], ("installed", "completed"))
        self.assertEqual(sum(1 for n in sent_notifications if "fully approved" in n["message"]), 1)

    def test_self_managed_requester_is_routed_to_authorized_substitute(self):
        outcome = self.submit(3000, "E2001, Manager Marketing Department, Marketing")
        self.assertTrue(outcome["success"])
        rid = outcome["request_id"]
        chain = approval_workflows[rid]["approval_chain"]
        self.assertEqual([s["employee_id"] for s in chain], ["E5001", "E3001", "E4001"])  # never the requester
        self.assertFalse(submit_decision(rid, "E2001", "APPROVED")["success"])  # requester cannot self-approve
        self.assertEqual(approval_workflows[rid]["approval_chain"][0]["decision"], None)
        self.assertFalse(submit_decision(rid, "E3001", "APPROVED")["success"])  # next approver cannot jump in
        self.assertTrue(self.decide(rid, "APPROVED")["success"])  # substitute decides
        self.assertEqual(approval_workflows[rid]["current_approver_index"], 1)

    def test_self_managed_requester_without_configured_substitute_is_refused(self):
        from mock_data import employees
        saved = dict(employees.SUBSTITUTE_APPROVERS)
        employees.SUBSTITUTE_APPROVERS.clear()
        try:
            outcome = self.submit(1800, "E2001, Manager Marketing Department, Marketing")
        finally:
            employees.SUBSTITUTE_APPROVERS.update(saved)
        self.assertFalse(outcome["success"])
        self.assertEqual(approval_workflows, {})

    def test_rejection_reason_must_be_meaningful(self):
        for bad in (None, "", "   ", "x", "no", "ok", "toolongbutoneword", 42):
            rid = self.submit(1800)["request_id"]
            workflow = approval_workflows[rid]
            history_len = len(workflow["history"])
            self.assertFalse(submit_decision(rid, "E2001", "REJECTED", bad)["success"], bad)
            self.assertIsNone(workflow["approval_chain"][0]["decision"])
            self.assertEqual(len(workflow["history"]), history_len)
            clear_workflows()
        rid = self.submit(1800)["request_id"]
        self.assertTrue(submit_decision(rid, "E2001", "REJECTED", "Over budget this quarter")["success"])

    def test_decision_record_includes_resulting_state(self):
        rid = self.submit(1800)["request_id"]
        workflow = approval_workflows[rid]
        submit_decision(rid, "E2001", "APPROVED")
        step = workflow["approval_chain"][0]
        self.assertEqual((step["decided_by"], step["decision"]), ("E2001", "APPROVED"))
        self.assertTrue(step["decided_at"])
        self.assertIn("Resulting state", workflow["history"][-1]["details"])
        self.assertEqual(workflow["history"][-1]["state"], "pending")
        process_workflows(next_step_fn=fake_router)
        self.assertIn("advanced to Omar Sheikh", step["resulting_state"])
        self.decide(rid, "REJECTED", reason="Not justified for this team")
        self.assertEqual(workflow["approval_chain"][1]["resulting_state"], "rejected")
        self.assertEqual(workflow["history"][-1]["state"], "rejected")

    def test_validator_rejects_tampered_results(self):
        request = make_request(3000)
        good = {"approvers": [
            {"employee_id": "E2001", "name": "Ali Raza", "job_designation": "Manager Marketing Department"},
            {"employee_id": "E3001", "name": "Omar Sheikh", "job_designation": "IT Lead"},
            {"employee_id": "E4001", "name": "Nadia Malik", "job_designation": "Finance Director"}],
            "reason": "x", "policy_version": "v2.0.0", "error": None}
        self.assertTrue(validate_agent_result(good, request))
        short = {**good, "approvers": good["approvers"][:2]}
        self.assertFalse(validate_agent_result(short, request))
        swapped = {**good, "approvers": [good["approvers"][1], good["approvers"][0], good["approvers"][2]]}
        self.assertFalse(validate_agent_result(swapped, request))
        self.assertFalse(validate_agent_result({**good, "policy_version": "v1.0.0"}, request))

    def test_authorization_and_idempotency(self):
        rid = self.submit(1800)["request_id"]
        self.assertFalse(self.decide(rid, "APPROVED", approver_id="E3001")["success"])  # out of turn
        self.assertTrue(self.decide(rid, "APPROVED")["success"])
        history_len = len(approval_workflows[rid]["history"])
        notified = len(sent_notifications)
        duplicate = self.decide(rid, "APPROVED", approver_id="E2001")  # same approver again
        self.assertFalse(duplicate["success"])
        self.assertEqual(len(approval_workflows[rid]["history"]), history_len)
        self.assertEqual(len(sent_notifications), notified)

    def test_history_order(self):
        rid = self.submit(1800)["request_id"]
        self.decide(rid, "APPROVED")
        self.decide(rid, "APPROVED")
        events = [h["event"] for h in approval_workflows[rid]["history"]]
        self.assertEqual(events, ["submitted", "notified", "approve", "routed", "notified", "approve", "approved"])

    def test_scheduler_reminds_escalates_and_ignores_unregistered(self):
        rid = self.submit(400)["request_id"]
        step = approval_workflows[rid]["approval_chain"][0]
        start = step["notified_at"]
        day = 24 * 3600
        self.assertEqual(process_workflows(now=start + 1)["reminded"], [])
        self.assertEqual(process_workflows(now=start + day + 1)["reminded"], [rid])
        process_workflows(now=start + 2 * day + 2)
        self.assertEqual(process_workflows(now=start + 3 * day + 3)["escalated"], [rid])
        self.assertEqual(approval_workflows[rid]["status"], "escalated")
        self.assertFalse(submit_decision(rid, "E2001", "APPROVED")["success"])

    def test_recorded_decision_is_routed_only_by_scheduler_agent(self):
        rid = self.submit(1800)["request_id"]
        workflow = approval_workflows[rid]
        self.assertTrue(submit_decision(rid, "E2001", "APPROVED")["success"])
        self.assertEqual(workflow["current_approver_index"], 0)  # not advanced yet
        self.assertEqual(workflow["history"][-1]["event"], "approve")  # status is visible immediately
        self.assertFalse(submit_decision(rid, "E2001", "REJECTED", "x")["success"])  # one decision per stage
        self.assertFalse(submit_decision(rid, "E3001", "APPROVED")["success"])  # future approver
        self.assertEqual(process_workflows(next_step_fn=fake_router)["processed"], [rid])
        self.assertEqual(workflow["current_approver_index"], 1)
        history_len, notified = len(workflow["history"]), len(sent_notifications)
        self.assertEqual(process_workflows(next_step_fn=fake_router)["processed"], [])  # no duplicate processing
        self.assertEqual((len(workflow["history"]), len(sent_notifications)), (history_len, notified))
        self.assertFalse(submit_decision(rid, "E2001", "REJECTED", "late")["success"])  # previous approver

    def test_last_approver_does_not_complete_until_agent_routes(self):
        rid = self.submit(400)["request_id"]
        workflow = approval_workflows[rid]
        submit_decision(rid, "E2001", "APPROVED")
        self.assertEqual(workflow["status"], "pending")  # approved flag only; agent has not completed it
        process_workflows(next_step_fn=fake_router)
        self.assertEqual(workflow["status"], "approved")

    def test_agent_receives_full_context(self):
        rid = self.submit(1800)["request_id"]
        submit_decision(rid, "E2001", "APPROVED")
        seen = []
        process_workflows(next_step_fn=lambda snapshot: seen.append(build_routing_message(snapshot)) or fake_router(snapshot))
        self.assertIn("Request cost: $1,800.00", seen[0])
        self.assertIn("Ali Raza (E2001): APPROVED", seen[0])
        self.assertIn("Omar Sheikh (E3001): PENDING", seen[0])

    def test_agent_must_block_rejection_and_bad_answers_fail_closed(self):
        rid = self.submit(3000)["request_id"]
        workflow = approval_workflows[rid]
        submit_decision(rid, "E2001", "REJECTED", "Not needed")
        wrong = "ACTION: ASSIGN_NEXT\nNEXT_APPROVER: Omar Sheikh\nREASON: skip it"
        notified = len(sent_notifications)
        for _ in range(2):
            process_workflows(next_step_fn=lambda w: wrong)
            self.assertEqual(workflow["status"], "pending")  # never advances
            self.assertEqual(workflow["current_approver_index"], 0)
        self.assertEqual(process_workflows(next_step_fn=lambda w: wrong)["escalated"], [rid])
        self.assertEqual(workflow["status"], "escalated")
        self.assertEqual(workflow["approval_chain"][0]["decision"], "REJECTED")
        self.assertEqual(len(sent_notifications), notified)

    def test_agent_failure_is_retried_then_escalated(self):
        def down(workflow):
            raise RuntimeError("down")
        rid = self.submit(1800)["request_id"]
        submit_decision(rid, "E2001", "APPROVED")
        process_workflows(next_step_fn=down)
        self.assertEqual(approval_workflows[rid]["status"], "pending")
        process_workflows(next_step_fn=down)
        process_workflows(next_step_fn=down)
        self.assertEqual(approval_workflows[rid]["status"], "escalated")

    def test_agent_wrong_next_approver_rejected(self):
        rid = self.submit(3000)["request_id"]
        submit_decision(rid, "E2001", "APPROVED")
        skip = "ACTION: ASSIGN_NEXT\nNEXT_APPROVER: Nadia Malik\nREASON: skip IT"
        process_workflows(next_step_fn=lambda w: skip)
        self.assertEqual(approval_workflows[rid]["current_approver_index"], 0)

    def test_rejection_is_terminal(self):
        rid = self.submit(3000)["request_id"]
        workflow = approval_workflows[rid]
        self.assertFalse(submit_decision(rid, "E2001", "REJECTED", "  ")["success"])  # reason required
        submit_decision(rid, "E2001", "REJECTED", "Not needed")
        blocked = submit_decision(rid, "E2001", "APPROVED")
        self.assertEqual(blocked["message"], REJECTED_MESSAGE)
        process_workflows(next_step_fn=fake_router)
        self.assertEqual(workflow["status"], "rejected")
        self.assertEqual(workflow["rejection_reason"], "Not needed")
        snapshot = (list(workflow["history"]), len(sent_notifications))
        self.assertEqual(submit_decision(rid, "E3001", "APPROVED")["message"], REJECTED_MESSAGE)
        self.assertEqual(self.decide(rid, "APPROVED")["message"], REJECTED_MESSAGE)
        process_workflows(next_step_fn=fake_router)
        self.assertEqual((workflow["history"], len(sent_notifications)), snapshot)
        self.assertEqual(workflow["status"], "rejected")

    def test_agent_failure_creates_no_workflow(self):
        def broken(request):
            raise RuntimeError("down")
        outcome = submit_request(make_request(1800), route_fn=broken)
        self.assertEqual(outcome["error_type"], "technical")
        self.assertEqual(self.submit(-5)["error_type"], "business_rule")
        self.assertEqual(approval_workflows, {})

    def test_duplicate_workflow_id_refused(self):
        create_workflow("X", make_request(100), [])
        with self.assertRaises(ValueError):
            create_workflow("X", make_request(100), [])


if __name__ == "__main__":
    unittest.main()
