"""Run the frozen policy-assistant evaluation set against baseline and revised RAG retrieval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .assistant import answer_policy_question, retrieve_policy_evidence


HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "evaluation_cases.json"
RESULTS_PATH = HERE / "evaluation_results.json"


def _source_key(item):
    return f"{item['document_id']}:{item['section_id']}"


def evaluate_case(case, *, limit):
    evidence = retrieve_policy_evidence(case["question"], limit=limit)
    answer_result = answer_policy_question(case["question"],
                                           evidence_retriever=lambda _question: evidence)
    expected_sources = set(case["expected_sources"])
    retrieved_sources = {_source_key(item) for item in evidence}
    source_recall = (len(expected_sources & retrieved_sources) / len(expected_sources)) if expected_sources else None
    actual = answer_result["answer"].casefold()
    facts = case["expected_facts"]
    answer_correct = (all(term.casefold() in actual for term in facts) if case["answerable"]
                       else answer_result["refused"])
    valid_citations = all(citation in {item["citation"] for item in evidence}
                          for citation in answer_result["citations"])
    return {
        "id": case["id"], "question": case["question"],
        "expected_sources": sorted(expected_sources), "retrieved_sources": sorted(retrieved_sources),
        "retrieval_source_recall": source_recall,
        "answer_correct": answer_correct,
        "citation_valid": valid_citations and (answer_result["refused"] or bool(answer_result["citations"])),
        "refusal_correct": answer_result["refused"] == (not case["answerable"]),
        "actual_answer": answer_result["answer"], "citations": answer_result["citations"],
        "pass": answer_correct and valid_citations and answer_result["refused"] == (not case["answerable"]),
    }


def _summary(results):
    def mean(values):
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), 4) if values else None
    return {
        "cases": len(results),
        "retrieval_quality_source_recall": mean([item["retrieval_source_recall"] for item in results]),
        "answer_correctness_rate": mean([float(item["answer_correct"]) for item in results]),
        "citation_validity_rate": mean([float(item["citation_valid"]) for item in results]),
        "refusal_behavior_accuracy": mean([float(item["refusal_correct"]) for item in results]),
        "passed": sum(item["pass"] for item in results),
    }


def run_evaluation():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    baseline = [evaluate_case(case, limit=1) for case in cases]
    revised = [evaluate_case(case, limit=6) for case in cases]
    report = {
        "evaluation_set": "frozen policy evaluation cases",
        "improvement": "Increase Chroma section retrieval from top-1 to top-6 to support paraphrases and cross-document questions.",
        "baseline": {"configuration": "top_k=1", "summary": _summary(baseline), "cases": baseline},
        "revised": {"configuration": "top_k=6", "summary": _summary(revised), "cases": revised},
        "manual_citation_review": "Reviewer should compare each cited section with its source Markdown before operational use.",
    }
    RESULTS_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": report["baseline"]["summary"],
                      "revised": report["revised"]["summary"],
                      "results_path": str(RESULTS_PATH)}, indent=2))
    return report


if __name__ == "__main__":
    try:
        run_evaluation()
    except Exception as exc:
        print(f"Evaluation could not run: {exc}", file=sys.stderr)
        print("Start the configured Chroma server and set OPENAI_API_KEY, then rerun python -m policy.evaluate.",
              file=sys.stderr)
        raise SystemExit(1)
