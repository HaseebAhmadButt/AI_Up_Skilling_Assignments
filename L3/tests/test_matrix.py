"""Test matrix C-H plus boundaries (I2). Run from L2: python -m unittest tests.test_matrix -v
No API key needed; the agents are stubbed. Test ids in the names (c1, d4, ...) match the matrix."""
import contextlib
import copy
import io
import json
import unittest
from unittest import mock

import main
from mock_data import clear_notifications, employees, sent_notifications
from tools import get_approval_policy
from workflow.scheduler import process_workflows
from workflow.store import approval_workflows, clear_workflows
from workflow.submission import submit_request
from workflow.validation import validate_agent_result
from workflow.workflow_tools import current_step, submit_decision

from tests.test_workflow import fake_agent, fake_router, make_request

MANAGER = "E1001, Marketing Analyst, Marketing"
SELF_MANAGED = "E2001, Manager Marketing Department, Marketing"
SELF_NO_SUB = "E2002, Manager Sales Department, Sales"
GOOD_REASON = "Not justified for this team"


class Base(unittest.TestCase):
    def setUp(self):
        clear_workflows()
        clear_notifications()

    def submit(self, cost, requester=MANAGER, manager_name=None, **kw):
        request = make_request(cost, requester, **kw)
        if manager_name is not None:
            request["manager_name"] = manager_name
        return submit_request(request, route_fn=fake_agent)

    def create(self, cost, requester=MANAGER):
        outcome = self.submit(cost, requester)
        self.assertTrue(outcome["success"], outcome)
        return outcome["request_id"]

    def decide(self, rid, decision, approver_id=None, reason=None):
        approver_id = approver_id or current_step(approval_workflows[rid])["employee_id"]
        result = submit_decision(rid, approver_id, decision, reason)
        process_workflows(next_step_fn=fake_router)
        return result

    def notes(self, to, text):
        return [n for n in sent_notifications if n["to"] == to and text in n["message"]]

    def history(self, rid, event=None):
        return [h for h in approval_workflows[rid]["history"] if event is None or h["event"] == event]


class SubstituteAndIdentity(Base):
    def test_c1_c2_self_request_goes_to_substitute_and_history_shows_both(self):
        rid = self.create(1800, SELF_MANAGED)
        chain = approval_workflows[rid]["approval_chain"]
        self.assertEqual(chain[0]["employee_id"], "E5001")
        self.assertTrue(self.decide(rid, "APPROVED")["success"])
        entry = self.history(rid, "approve")[0]
        self.assertEqual(entry["actor"], "E5001")
        self.assertIn("Zain Abbas", entry["details"])
        self.assertIn("Ali Raza", entry["details"])  # the original manager of record

    def test_c3_self_managed_without_substitute_is_unresolved(self):
        with self.assertLogs("approval", level="WARNING") as logs:
            outcome = self.submit(1800, SELF_NO_SUB)
        self.assertFalse(outcome["success"])
        self.assertEqual(approval_workflows, {})
        text = "\n".join(logs.output)
        self.assertIn("NONE CONFIGURED", text)
        self.assertIn("validation FAILED", text)

    def test_c4_no_manager_is_unresolved(self):
        outcome = self.submit(1800, "E1007, Operations Associate, Operations")
        self.assertFalse(outcome["success"])
        self.assertIn("no manager is on record", outcome["error"])
        self.assertEqual(approval_workflows, {})

    def test_c5_dangling_manager_is_unresolved(self):
        outcome = self.submit(1800, "E1008, Operations Analyst, Operations")
        self.assertFalse(outcome["success"])
        self.assertIn("no manager is on record", outcome["error"])
        self.assertEqual(approval_workflows, {})

    def test_c6_ambiguous_manager_name_is_never_picked_silently(self):
        # The name only checks the record; E1006's manager is E2002, so "Ali Raza" (two people) is refused.
        outcome = self.submit(1800, "E1006, Sales Executive, Sales", manager_name="Ali Raza")
        self.assertFalse(outcome["success"])
        # If the manager of record is the second Ali Raza (E2003), name-based resolution would pick E2001: refused.
        changed = {**employees.EMPLOYEES["E1001"], "manager_id": "E2003"}
        with mock.patch.dict(employees.EMPLOYEES, {"E1001": changed}):
            outcome = self.submit(1800, MANAGER, manager_name="Ali Raza")
        self.assertFalse(outcome["success"])
        self.assertEqual(approval_workflows, {})

    def test_c7_manager_name_not_matching_record_is_rejected(self):
        for typed in ("Zain Abbas", "Omar Sheikh", "Nobody Atall"):
            outcome = self.submit(1800, MANAGER, manager_name=typed)
            self.assertFalse(outcome["success"], typed)
        self.assertEqual(approval_workflows, {})
        # The deterministic validator refuses it too, even if the agent output were otherwise correct.
        good = {"approvers": [{"employee_id": "E2001", "name": "Ali Raza",
                               "job_designation": "Manager Marketing Department"}],
                "reason": "x", "policy_version": "v2.0.0", "error": None}
        request = make_request(400)
        self.assertTrue(validate_agent_result(good, request))
        self.assertFalse(validate_agent_result(good, {**request, "manager_name": "Omar Sheikh"}))

    def test_c8_email_not_matching_identity_is_refused_and_logged(self):
        with self.assertLogs("approval", level="WARNING") as logs:
            outcome = self.submit(1800, SELF_MANAGED, email="haseeb.ahmad@example.com")
        self.assertFalse(outcome["success"])
        self.assertIn("Identity mismatch", outcome["error"])
        self.assertIn("identity mismatch", "\n".join(logs.output))
        self.assertEqual(approval_workflows, {})

    def test_c9_substitute_that_is_the_requester_is_blocked(self):
        with mock.patch.dict(employees.SUBSTITUTE_APPROVERS, {"E2001": "E2001"}):
            outcome = self.submit(1800, SELF_MANAGED)
        self.assertFalse(outcome["success"])
        self.assertEqual(approval_workflows, {})


class ApprovalBehavior(Base):
    def test_d1_nonfinal_approval_advances_with_one_notification(self):
        rid = self.create(1800)
        self.decide(rid, "APPROVED")
        process_workflows(next_step_fn=fake_router)
        self.assertEqual(approval_workflows[rid]["current_approver_index"], 1)
        self.assertEqual(len(self.notes("E3001", "Approval needed")), 1)

    def test_d2_final_approval_is_one_approval_and_one_handoff(self):
        rid = self.create(400)
        submit_decision(rid, "E2001", "APPROVED")
        with self.assertLogs("approval", level="INFO") as logs:
            process_workflows(next_step_fn=fake_router)
            process_workflows(next_step_fn=fake_router)
        self.assertEqual(approval_workflows[rid]["status"], "approved")
        self.assertEqual(sum("HANDOFF" in line for line in logs.output), 1)
        self.assertEqual(len(self.notes(MANAGER, "fully approved")), 1)

    def test_d3_h3_final_approval_never_shows_installed(self):
        rid = self.create(3000)
        for _ in range(3):
            self.decide(rid, "APPROVED")
        workflow = approval_workflows[rid]
        self.assertEqual(workflow["status"], "approved")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.print_details(workflow)
        self.assertIn("Software installation is NOT completed", out.getvalue())
        for text in (out.getvalue(), json.dumps(workflow, default=str)):
            self.assertNotIn("installed", text.lower())

    def test_d4_three_person_chain_one_notification_per_hop_in_order(self):
        rid = self.create(3000)
        for _ in range(3):
            self.decide(rid, "APPROVED")
        needed = [n["to"] for n in sent_notifications if "Approval needed" in n["message"]]
        self.assertEqual(needed, ["E2001", "E3001", "E4001"])
        self.assertEqual(len(self.notes(MANAGER, "fully approved")), 1)

    def test_d5_every_decision_has_actor_timestamp_and_resulting_state(self):
        rid = self.create(3000)
        self.decide(rid, "APPROVED")
        self.decide(rid, "REJECTED", reason=GOOD_REASON)
        for entry in self.history(rid):
            self.assertTrue(entry["actor"] and entry["timestamp"] and entry["state"], entry)
        for entry in self.history(rid, "approve") + self.history(rid, "reject"):
            self.assertIn("Resulting state", entry["details"])


class Rejection(Base):
    def test_e1_manager_rejection_stops_chain_with_one_notification(self):
        rid = self.create(3000)
        self.decide(rid, "REJECTED", reason=GOOD_REASON)
        self.assertEqual(approval_workflows[rid]["status"], "rejected")
        self.assertEqual(len(self.notes(MANAGER, "was rejected")), 1)
        self.assertEqual(self.notes("E3001", "Approval needed"), [])

    def test_e2_it_lead_rejection_sends_nothing_to_finance(self):
        rid = self.create(3000)
        self.decide(rid, "APPROVED")
        self.decide(rid, "REJECTED", reason=GOOD_REASON)
        self.assertEqual([n for n in sent_notifications if n["to"] == "E4001"], [])
        self.assertEqual(approval_workflows[rid]["status"], "rejected")

    def test_e3_finance_rejection_preserves_earlier_approvals(self):
        rid = self.create(3000)
        self.decide(rid, "APPROVED")
        self.decide(rid, "APPROVED")
        self.decide(rid, "REJECTED", reason=GOOD_REASON)
        chain = approval_workflows[rid]["approval_chain"]
        self.assertEqual([s["decision"] for s in chain], ["APPROVED", "APPROVED", "REJECTED"])
        self.assertEqual(approval_workflows[rid]["status"], "rejected")

    def test_e4_empty_or_trivial_reasons_are_refused(self):
        rid = self.create(1800)
        workflow = approval_workflows[rid]
        before = len(workflow["history"])
        for bad in ("", "   ", ".", "no", "x", "\n \t", None):
            self.assertFalse(submit_decision(rid, "E2001", "REJECTED", bad)["success"], repr(bad))
        self.assertIsNone(workflow["approval_chain"][0]["decision"])
        self.assertEqual(len(workflow["history"]), before)

    def test_e5_meaningful_means_10_chars_and_2_words_boundary(self):
        # Rule: stripped reason of at least 10 characters (spaces count) and at least 2 words.
        for reason, ok in (("abcd efgh", False), ("abcd efghi", True), ("abcdefghij", False)):
            clear_workflows()
            rid = self.create(1800)
            self.assertEqual(submit_decision(rid, "E2001", "REJECTED", reason)["success"], ok, reason)

    def test_e6_long_special_and_multiline_reasons_are_safe(self):
        reasons = [("lorem ipsum " * 417)[:5000], "<b>&'\"; DROP TABLE x;-- \n second line\r\nthird %s {0}"]
        for reason in reasons:
            clear_workflows()
            rid = self.create(1800)
            self.assertTrue(submit_decision(rid, "E2001", "REJECTED", reason)["success"])
            process_workflows(next_step_fn=fake_router)
            workflow = approval_workflows[rid]
            self.assertEqual(workflow["status"], "rejected")
            self.assertEqual([h["event"] for h in workflow["history"]],
                             ["submitted", "notified", "reject", "rejected"])
            for entry in workflow["history"]:
                self.assertNotIn("\n", entry["details"])
                self.assertNotIn("\r", entry["details"])
            self.assertEqual(workflow["rejection_reason"], " ".join(reason.split()))

    def test_e7_decisions_after_rejection_are_blocked_without_new_history(self):
        rid = self.create(3000)
        self.decide(rid, "REJECTED", reason=GOOD_REASON)
        workflow = approval_workflows[rid]
        snapshot = (copy.deepcopy(workflow["history"]), len(sent_notifications))
        for approver in ("E2001", "E3001", "E4001"):
            self.assertFalse(submit_decision(rid, approver, "APPROVED")["success"])
            self.assertFalse(submit_decision(rid, approver, "REJECTED", GOOD_REASON)["success"])
        process_workflows(next_step_fn=fake_router)
        self.assertEqual((workflow["history"], len(sent_notifications)), snapshot)


class RepeatsAndInvalid(Base):
    def test_f1_double_approval_before_scheduler_is_one_change(self):
        rid = self.create(1800)
        self.assertTrue(submit_decision(rid, "E2001", "APPROVED")["success"])
        self.assertFalse(submit_decision(rid, "E2001", "APPROVED")["success"])
        self.assertEqual(len(self.history(rid, "approve")), 1)
        process_workflows(next_step_fn=fake_router)
        self.assertEqual(len(self.notes("E3001", "Approval needed")), 1)

    def test_f2_f3_decisions_on_finished_requests_are_blocked(self):
        approved = self.create(400)
        self.decide(approved, "APPROVED")
        rejected = self.create(1800, "E1002, Marketing Executive, Marketing")
        self.decide(rejected, "REJECTED", reason=GOOD_REASON)
        snapshot = (copy.deepcopy(approval_workflows), len(sent_notifications))
        for rid, decision in ((approved, "APPROVED"), (approved, "REJECTED"), (rejected, "APPROVED")):
            self.assertFalse(submit_decision(rid, "E2001", decision, GOOD_REASON)["success"])
        self.assertEqual((approval_workflows, len(sent_notifications)), snapshot)

    def test_f4_f5_duplicates_after_processing_and_second_pass_do_nothing(self):
        rid = self.create(400)
        self.decide(rid, "APPROVED")
        workflow = approval_workflows[rid]
        snapshot = (copy.deepcopy(workflow["history"]), len(sent_notifications))
        self.assertFalse(submit_decision(rid, "E2001", "APPROVED")["success"])
        summary = process_workflows(next_step_fn=fake_router)
        self.assertEqual(summary, {"processed": [], "reminded": [], "escalated": []})
        self.assertEqual((workflow["history"], len(sent_notifications)), snapshot)

    def test_f6_unknown_request_id_changes_nothing(self):
        rid = self.create(1800)
        snapshot = copy.deepcopy(approval_workflows)
        for bad in ("REQ-9999", "abc", "", None):
            result = submit_decision(bad, "E2001", "APPROVED")
            self.assertFalse(result["success"])
            self.assertEqual(result["message"], "Unknown request_id.")
        self.assertEqual(approval_workflows, snapshot)
        self.assertIn(rid, approval_workflows)

    def test_f8_f9_resubmission_after_rejection_and_other_requester(self):
        first = submit_request(make_request(400, software="Figma"), route_fn=fake_agent)
        self.assertFalse(submit_request(make_request(400, software="Figma"), route_fn=fake_agent)["success"])
        self.decide(first["request_id"], "REJECTED", reason=GOOD_REASON)
        self.assertTrue(submit_request(make_request(400, software="Figma"), route_fn=fake_agent)["success"])
        other = make_request(400, "E1002, Marketing Executive, Marketing", software="Figma")
        self.assertTrue(submit_request(other, route_fn=fake_agent)["success"])


class AgentSafety(Base):
    def route_with(self, rid, answer, passes=1):
        for _ in range(passes):
            process_workflows(next_step_fn=answer if callable(answer) else (lambda w: answer))

    def test_g1_complete_with_pending_approver_is_refused_and_logged(self):
        rid = self.create(1800)
        submit_decision(rid, "E2001", "APPROVED")
        with self.assertLogs("approval.routing", level="WARNING"):
            self.route_with(rid, "ACTION: COMPLETE\nREASON: done")
        workflow = approval_workflows[rid]
        self.assertEqual((workflow["status"], workflow["current_approver_index"]), ("pending", 0))

    def test_g2_wrong_next_approver_is_refused(self):
        rid = self.create(3000)
        submit_decision(rid, "E2001", "APPROVED")
        for name in ("Nadia Malik", "Eve Nobody", ""):
            with self.assertLogs("approval.routing", level="WARNING"):
                self.route_with(rid, f"ACTION: ASSIGN_NEXT\nNEXT_APPROVER: {name}\nREASON: x")
            self.assertEqual(approval_workflows[rid]["current_approver_index"], 0)

    def test_g3_malformed_or_empty_output_stays_pending_and_is_logged(self):
        rid = self.create(1800)
        submit_decision(rid, "E2001", "APPROVED")
        with self.assertLogs("approval.routing", level="WARNING"):
            self.route_with(rid, "")
        with self.assertLogs("approval.routing", level="WARNING"):
            self.route_with(rid, "ACTION: ???")
        self.assertEqual(approval_workflows[rid]["status"], "pending")
        self.route_with(rid, fake_router)  # a later valid answer is still applied (retry is safe)
        self.assertEqual(approval_workflows[rid]["current_approver_index"], 1)

    def test_g4_agent_unavailable_changes_no_state_and_approves_nothing(self):
        def down(workflow):
            raise TimeoutError("model unavailable")
        rid = self.create(400)
        submit_decision(rid, "E2001", "APPROVED")
        workflow = approval_workflows[rid]
        notified = len(sent_notifications)
        self.route_with(rid, down)
        self.assertEqual(workflow["status"], "pending")
        self.assertEqual(len(sent_notifications), notified)
        self.assertEqual(self.history(rid, "approved"), [])

    def test_g5_reject_after_approval_is_refused(self):
        rid = self.create(1800)
        submit_decision(rid, "E2001", "APPROVED")
        with self.assertLogs("approval.routing", level="WARNING"):
            self.route_with(rid, "ACTION: REJECT\nREASON: changed mind")
        workflow = approval_workflows[rid]
        self.assertEqual((workflow["status"], workflow["current_approver_index"]), ("pending", 0))


class SelfApprovalBlocked(Base):
    def test_requester_can_never_be_in_a_chain(self):
        # Every requester in the directory at every cost tier: either refused, or the requester is not an approver.
        for employee_id, record in employees.EMPLOYEES.items():
            for cost in (400, 1800, 3000):
                clear_workflows()
                requester = f"{employee_id}, {record['title']}, {record['department']}"
                outcome = self.submit(cost, requester)
                if outcome["success"]:
                    ids = [s["employee_id"] for s in approval_workflows[outcome["request_id"]]["approval_chain"]]
                    self.assertNotIn(employee_id, ids, (employee_id, cost))
                    self.assertEqual(len(ids), len(set(ids)), (employee_id, cost))

    def test_requester_who_holds_a_later_role_is_refused(self):
        # E1005's manager is the IT Lead and E1004's manager is the Finance Director: same person twice in a chain.
        self.assertFalse(self.submit(1800, "E1005, IT Support Engineer, IT")["success"])
        self.assertFalse(self.submit(3000, "E1004, Finance Analyst, Finance")["success"])
        # An IT Lead or Finance Director with a manager of their own can never approve themselves either.
        for holder, role_cost in (({"E3001": "E2001"}, 1800), ({"E4001": "E2001"}, 3000)):
            employee_id = next(iter(holder))
            changed = {**employees.EMPLOYEES[employee_id], "manager_id": holder[employee_id]}
            with mock.patch.dict(employees.EMPLOYEES, {employee_id: changed}):
                outcome = self.submit(role_cost, f"{employee_id}, x, y")
            self.assertFalse(outcome["success"], employee_id)
        self.assertEqual(approval_workflows, {})

    def test_requester_cannot_decide_own_request_at_any_stage(self):
        rid = self.create(3000, SELF_MANAGED)
        for _ in range(3):
            for decision in ("APPROVED", "REJECTED"):
                result = submit_decision(rid, "E2001", decision, GOOD_REASON)
                self.assertFalse(result["success"])
                self.assertIn("own request", result["message"])
            self.decide(rid, "APPROVED")
        self.assertTrue(all(s["decided_by"] != "E2001" for s in approval_workflows[rid]["approval_chain"]))

    def test_requester_in_a_tampered_chain_is_still_blocked(self):
        rid = self.create(1800)
        workflow = approval_workflows[rid]
        workflow["approval_chain"][0]["employee_id"] = "E1001"  # force the requester into the current step
        with self.assertLogs("approval.workflow", level="WARNING"):
            self.assertFalse(submit_decision(rid, "E1001", "APPROVED")["success"])
        self.assertIsNone(workflow["approval_chain"][0]["decision"])

    def test_agent_cannot_route_to_the_requester(self):
        rid = self.create(1800)
        workflow = approval_workflows[rid]
        submit_decision(rid, "E2001", "APPROVED")
        workflow["approval_chain"][1].update(employee_id="E1001", name="Sara Khan")  # tamper: requester is next
        for _ in range(2):
            process_workflows(next_step_fn=lambda w: "ACTION: ASSIGN_NEXT\nNEXT_APPROVER: Sara Khan\nREASON: x")
        self.assertEqual(workflow["current_approver_index"], 0)


class SilenceAndBoundaries(Base):
    DAY = 24 * 3600

    def test_h1_silence_gives_reminders_then_escalation_never_approval(self):
        rid = self.create(1800)
        workflow = approval_workflows[rid]
        start = workflow["approval_chain"][0]["notified_at"]
        for n in range(1, 5):
            process_workflows(now=start + n * self.DAY + n, next_step_fn=fake_router)
        self.assertEqual(workflow["status"], "escalated")
        self.assertEqual(len(self.history(rid, "reminder")), 2)
        self.assertTrue(all(s["decision"] is None for s in workflow["approval_chain"]))
        self.assertEqual(self.history(rid, "approved"), [])

    def test_h2_escalation_does_not_skip_or_approve(self):
        rid = self.create(3000)
        self.decide(rid, "APPROVED")
        workflow = approval_workflows[rid]
        start = workflow["approval_chain"][1]["notified_at"]
        for n in range(1, 5):
            process_workflows(now=start + n * self.DAY + n, next_step_fn=fake_router)
        self.assertEqual(workflow["status"], "escalated")
        self.assertEqual(workflow["current_approver_index"], 1)
        self.assertEqual([s["decision"] for s in workflow["approval_chain"]], ["APPROVED", None, None])
        self.assertEqual([n for n in sent_notifications if n["to"] == "E4001"], [])

    def test_i2_policy_boundaries(self):
        expected = {499: ["E2001"], 500: ["E2001", "E3001"], 2500: ["E2001", "E3001"],
                    2501: ["E2001", "E3001", "E4001"]}
        for cost, roles in expected.items():
            policy = get_approval_policy.invoke({"request_cost": str(cost)})
            self.assertEqual(len(policy["required_roles"]), len(roles), cost)
            rid = self.create(cost)
            chain = approval_workflows[rid]["approval_chain"]
            self.assertEqual([s["employee_id"] for s in chain], roles, cost)
            clear_workflows()


if __name__ == "__main__":
    unittest.main()
