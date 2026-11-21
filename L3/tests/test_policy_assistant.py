"""Offline unit tests for policy RAG behavior and the frozen evaluation design."""
import json
import tempfile
import unittest
from pathlib import Path

from policy.assistant import REFUSAL, answer_policy_question
from policy.retrieval import PolicyRetrievalError
from policy.ingest_chroma import load_policy_sections


ROOT = Path(__file__).resolve().parents[1]


class PolicyAssistantTests(unittest.TestCase):
    def setUp(self):
        self.first = {"citation": "Lifecycle, prototype-1, §1 — Explicit decisions",
                      "text": "Silence never counts as approval.", "document_id": "approval-lifecycle-controls",
                      "section_id": "1", "approval_status": "unverified"}
        self.second = {"citation": "Identity, prototype-1, §4 — Authorized decision maker",
                       "text": "Only the current approver may decide.",
                       "document_id": "identity-and-approver-authorization", "section_id": "4",
                       "approval_status": "unverified"}

    def test_cited_answers_can_combine_two_documents(self):
        evidence = [self.first, self.second]
        answer = ("Silence is not approval [" + self.first["citation"] + "]; only the current approver "
                  "may decide [" + self.second["citation"] + "].")
        result = answer_policy_question("Can silence approve, and who can decide?",
                                        evidence_retriever=lambda _q: evidence,
                                        answer_model=lambda _q, _e: answer)
        self.assertTrue(result["answered"])
        self.assertEqual(result["citations"], [self.first["citation"], self.second["citation"]])
        self.assertIn("not verified as current company policy", result["answer"])

    def test_unsupported_question_is_refused(self):
        result = answer_policy_question("How many licenses are free?",
                                        evidence_retriever=lambda _q: [self.first],
                                        answer_model=lambda _q, _e: "INSUFFICIENT_EVIDENCE")
        self.assertTrue(result["refused"])
        self.assertEqual(result["answer"], REFUSAL)

    def test_missing_or_fabricated_citation_fails_closed(self):
        for answer in ("Only the manager approves.", "Only the manager approves [fabricated §99]."):
            with self.subTest(answer=answer):
                result = answer_policy_question("Who approves?",
                                                evidence_retriever=lambda _q: [self.first],
                                                answer_model=lambda _q, _e: answer)
                self.assertTrue(result["refused"])
                self.assertEqual(result["answer"], REFUSAL)

    def test_retrieval_failure_refuses_without_local_policy_fallback(self):
        def unavailable(_question):
            raise PolicyRetrievalError("offline")
        result = answer_policy_question("Who approves?", evidence_retriever=unavailable)
        self.assertTrue(result["refused"])
        self.assertEqual(result["reason"], "retrieval_unavailable")

    def test_frozen_evaluation_meets_required_case_mix(self):
        cases = json.loads((ROOT / "policy" / "evaluation_cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 12)
        self.assertGreaterEqual(sum(not case["answerable"] for case in cases), 3)
        self.assertGreaterEqual(sum("wording_variant_of" in case for case in cases), 2)
        self.assertTrue(any(len(case["expected_sources"]) > 1 for case in cases if case["answerable"]))

    def test_ingestion_marks_only_the_latest_supplied_version_current(self):
        front = ("---\ndocument_id: sample\ndocument_title: Sample\neffective_date: unspecified\n"
                 "approval_status: unverified\nauthority: fixture\nsource_path: fixture.md\n")
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory)
            (docs / "old.md").write_text(front + "version: v1.0.0\n---\n## §1 — Rule\nOld rule.\n", encoding="utf-8")
            (docs / "new.md").write_text(front + "version: v2.0.0\n---\n## §1 — Rule\nNew rule.\n", encoding="utf-8")
            sections = load_policy_sections(docs)
        current_by_text = {section.text: section.metadata["is_current"] for section in sections}
        self.assertEqual(current_by_text, {"Old rule.": False, "New rule.": True})


if __name__ == "__main__":
    unittest.main()
