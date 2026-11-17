# L3 Prototype Implementation Plan

## Goal and boundary

Extend the reviewed L2 approval workflow into a repeatable, auditable **local prototype**. Demonstrate an email-to-verified-install lifecycle and a cited policy assistant using fixtures and faithful deployment simulation. Do not connect to real mailboxes, employee directories, license systems, endpoint management, or production deployment services. An accepted deployment job must remain distinct from verified installation; only simulated verification success closes a request.

## What L2 already provides

Retain L2's requester identity checks, ordered human approvals, rejection handling, reminder/escalation behavior, audit history, duplicate-request guard, and decision authorization. The current app accepts interactive requests, stores workflows in a process-local dictionary, and ends at `approved`; it does not provide email intake, entitlement/device/package checks, deployment, installation verification, or policy Q&A. L2 tests use `unittest` and stub agent calls, making them a useful regression base.

## Prototype structure

Keep the L2 implementation intact and place L3 additions under this directory:

- `intake.py`: parse fixture email events, validate sender identity, collect missing fields through simulated replies, and associate authorized replies with the original request.
- `service.py`: orchestrate eligibility, entitlement, device readiness, budget, existing approval, deployment, verification, and closure transitions.
- `adapters/`: deterministic in-memory or JSON-backed simulators for email, employee/device/license/package data, deployment job acceptance, and installation results. Give events stable IDs and deduplicate before side effects.
- `policy/`: ingest only supplied, versioned policy documents into ChromaDB; retrieve relevant sections with RAG; generate answers grounded in those passages with document and section citations, or refuse when evidence is insufficient.
- `tests/` and `fixtures/`: repeatable scenario tests and synthetic emails, policies, devices, packages, and deployment outcomes.
- `evidence/`: workflow run records, policy evaluation cases/results, operating notes, limitations, ownership checklist, and rollout recommendation.

Use a small persistent local store (SQLite is sufficient) for request state, idempotency keys, and append-only event history so a restart does not lose the prototype's audit trail. Use the user's ChromaDB server for policy passages, not SQLite. Keep integration boundaries behind adapter interfaces. Adapt L2 through a narrow service seam rather than copying its approval rules; ensure L2 modules can be imported consistently from tests and the L3 entry point.

## Policy assistant: ChromaDB-backed RAG

Connect with ChromaDB's Python HTTP client using `host="localhost"`, `port=8000`, `tenant="default_tenant"`, and `database="default_database"`. Put connection settings in configuration (environment variables with these local defaults), and fail clearly if the server or collection is unavailable. Add the `chromadb` Python dependency in the L3 dependency manifest; it is not currently installed in the repository's `.venv` and no dependency manifest exists yet. Verify the installed client/server compatibility when setting up the prototype.

Use a dedicated collection such as `assetdesk_policy`. Each stored record should be a coherent policy section or subsection with a stable ID, text, and scalar metadata for `document_id`, `document_title`, `version`, `section_id`, `section_title`, `effective_date`, `status`, and `source_path`. Ingest only explicitly supplied documents marked current/approved. Preserve historical versions for audit, but filter retrieval to the approved current version set; never treat an older passage as current just because it scores highly. Re-ingestion should be deterministic and idempotent by record ID and version. Keep source files and their ownership outside Chroma; persist enough metadata to show exactly where each passage came from.

The request path is classic RAG: normalize the user's question, retrieve a small set of relevant passages from Chroma (using the same configured embedding function/model for ingestion and query), apply current-document metadata filters, then pass only those passages and citation metadata to a text-generation model. The model is a generator over retrieved context, not an agent selecting or invoking tools. Require it to answer from that context only and cite every factual policy claim as `Document title, version, §section_id — Section title`. Validate citation identifiers against the retrieved records before returning the answer. If Chroma is unavailable, no current passage is retrieved, retrieval confidence is below a measured threshold, or the passages do not support the question, return a clear refusal and do not fall back to model memory. Log query, retrieved record IDs, model/config version, citations, and refusal reason without storing unnecessary personal data.

Choose and configure the embedding and generation providers before implementation. Prefer a reproducible local embedding setup for the prototype if available; otherwise document required network access and credentials. Keep model names and thresholds configurable, never commit credentials, and ensure the same embedding configuration is used at index and query time. The user's supplied current policy corpus and section structure are still required; until provided, use labeled synthetic documents strictly for demonstration.

## Implementation sequence

1. **Freeze the L2 baseline.** Run `cd L2 && python -m unittest discover -s tests -v`; record current behavior and define a versioned request/event schema. Preserve L2 tests and its `approved` meaning.
2. **Add durable request intake.** Simulate inbound email and acknowledgement. Create one request per new message, deduplicate by provider message ID, validate sender against employee records, request missing details, and attach only authenticated/authorized replies to the same request. Expose request ID, status, owner, next action, and history in a simple CLI/report.
3. **Add prerequisite gates.** Check software eligibility, license availability, registered device ownership/readiness, package approval/version, and budget before deployment. Route policy-defined human decisions through L2's ordered chain. Missing/failed checks block with a named owner and next action; silence only reminds/escalates.
4. **Add simulated delivery and verification.** After all gates pass, create one deployment job for the approved package/version and eligible device. Simulate offline-device retry and unavailable-package hold. Record job acceptance separately from installation result. Close only when device identity, installed version, and required checks match; failures/unverified results stay open. Send one completion message after verified success.
5. **Harden replay behavior and audit.** Make intake, replies, decisions, jobs, results, reminders, and completion messages idempotent. Authorize every state-changing event, retain actor/source/time/result, and test duplicate and out-of-order delivery.
6. **Build and evaluate policy Q&A.** Connect and health-check the configured ChromaDB tenant/database; create or open the policy collection; ingest approved current documents as versioned sections; and test retrieval filters against historical versions. Run the retrieve-then-generate RAG path without tool calling, validate exact citations, and refuse unsupported or ambiguous questions. Create at least 12 cases: 3 explicit refusals, 2 wording variants of equivalent questions, and 1 requiring two documents. Record a baseline, make one documented improvement (for example, section-aware chunking, hybrid retrieval, or a tuned cutoff based on validation cases), rerun unchanged cases, and report both result sets.
7. **Package the handover.** Document local setup, demo commands, fixture reset/replay, workflow evidence, policy evaluation, known limits, accountable owners, required real-company configuration, and a recommendation for or against a later rollout.

## Acceptance evidence

The prototype is ready for review when a clean fixture run demonstrates: a new email creates one tracked request and acknowledgement; missing details and a reply update that same request; authorization and prerequisites control ordered approval; silence cannot approve; duplicate events do not repeat business actions; accepted deployment alone does not close; offline, unavailable-package, failed, and unverified cases remain open; only a matching verified installation closes and sends one completion email. A report should show status, owner, next action, and timestamped history for each scenario. Policy evidence must show successful Chroma connection with the configured tenant/database, that only current approved records were retrieved, all required case categories, citation validation/refusals, and baseline versus improved results.

## Assumptions and handover dependencies

Until current company materials and named owners are supplied, use clearly labeled synthetic policies and fixtures; do not invent policy answers. The handover must identify the real sources and owners needed for employee identities, authorized email senders, software eligibility, budget thresholds, license inventory, device registration/readiness, approved packages/versions, deployment and verification services, and policy document maintenance. No production rollout should be inferred from a successful simulation.
