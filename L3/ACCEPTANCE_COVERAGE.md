# L3 Acceptance Coverage

Run from `L3/` with `../.venv/bin/python -m unittest discover -s tests -v`.

## Implemented and regression-tested

| Requirement | Evidence |
| --- | --- |
| Intake clarification, duplicate mail/acknowledgement, same-request authorized reply, identity and device mismatch, version/currency/license-note capture | `tests.test_acceptance_coverage.IntakeAcceptanceTests`; `tests.test_idempotency.IdempotencyTests` |
| Ordered human approval, self/order/duplicate checks, rejection handoff block, reminders and silence behavior | `tests.test_acceptance_coverage.ApprovalAcceptanceTests`; approval, authorization, reminder and silence cases in `test_matrix` and `test_workflow` |
| Existing named-user license exception, one-seat allocation, exhausted entitlement hold | `tests.test_acceptance_coverage.DeploymentAcceptanceTests.test_existing_license_exception_and_available_seat_are_explicitly_verified`; `...test_missing_license_entitlement_holds_request_open` |
| Approved catalog, OS/device/account/readiness/user-scope gates, offline retry, IT packaging approval/rejection and automatic resumption | `tests.test_acceptance_coverage.DeploymentAcceptanceTests` |
| Bounded installation retry, exhaustion owner, matching external result, duplicate/late/mismatched results | `tests.test_acceptance_coverage.DeploymentAcceptanceTests.test_installation_retries_are_bounded_and_exhaustion_is_visible`; `...test_external_results_are_idempotent_and_mismatches_cannot_close_request` |
| Job accepted without closure, wrong installed version, failed install, duplicate result/verification/completion, one notification | `tests.test_acceptance_coverage.DeploymentAcceptanceTests`; `tests.test_idempotency.IdempotencyTests` |
| Policy RAG refusal and citation validation, cross-document citation, current-version ingestion selection, evaluation case mix | `tests.test_policy_assistant.PolicyAssistantTests` |

## Policy evaluation set and execution

`policy/evaluation_cases.json` freezes 16 cases: three unsupported questions, two paraphrase pairs, and a question requiring two documents. `python -m policy.evaluate` runs the same cases with top-1 baseline retrieval and top-6 revised retrieval, reporting source recall, answer correctness, citation validity, and refusal accuracy separately. The improvement is wider Chroma section retrieval. A manual check confirmed that evaluation case P04's silence rule is stated in `approval_lifecycle_controls_l3-prototype-1.md`, §1.

The evaluation harness is implemented but **measured baseline and revised results are pending**: this environment has no `chromadb` package, Chroma at `localhost:8000` is unreachable, and `OPENAI_API_KEY` is unset. The assistant's unit tests use injected evidence/model responses; they are not a substitute for the 16 live RAG cases.

## Remaining prototype and rollout limits

- Policy documents are marked `unverified` with unspecified effective dates. Answers disclose this; they must not be treated as current company policy until approved company sources replace them.
- The request and idempotency stores are in memory, so deduplication and audit history do not survive restart. Notifications have queued/delivered states, but no real delivery provider or authenticated approver login is connected.
- Retry, license, device, and package fixtures model behavior only. User-supplied version is recorded; deployment selects the latest approved compatible version. Rollback is not implemented because no delivery capability exists in this prototype.
