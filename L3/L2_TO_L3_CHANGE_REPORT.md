# L2 to L3 Change Report

## Purpose and scope

L3 extends the reviewed L2 approval workflow into a local, repeatable prototype of an end-to-end software request service. It covers simulated email intake, clarification, approvals, budget release, software eligibility and entitlement, device readiness, package handling, installation simulation, verification, closure, and policy Q&A. L2 remains intact; L3 contains the additions and integration seams.

The central design is **agentic flow, rather than a hard-coded business process that prescribes every next step**. Agents receive the current request context and available tools, then choose the next approval or installation action. Deterministic code still provides safety boundaries: it authenticates actors, checks authorization and prerequisites, rejects invalid transitions, prevents replayed side effects, and decides whether evidence is sufficient to close. This distinction matters: agents make operational choices, while code enforces invariants that must never be bypassed.

## What L2 provides and L3 retains

L2 provides interactive request submission, requester identity checks, ordered human approvals, approval and rejection handling, reminders and escalation, workflow status, and history. Its approval-routing agent uses policy and employee/role-holder tools to propose an approver sequence. The workflow validates that sequence and each decision before recording transitions. L2 stores workflow state in process memory and ends at approval; it does not handle inbound email, device/license/package checks, software delivery, verified installation, or policy Q&A.

L3 reuses the L2 workflow, approval list, role and employee fixtures, tools, and tests. It adds request-time policy retrieval through ChromaDB: the relevant versioned approval tier and citation are retrieved and given to the routing agent. If live retrieval fails or does not produce a unique tier, request routing stops; it does not silently fall back to a local threshold rule. L2's approval behavior and folder are not changed.

## L3 additions

| Area | L3 approach |
| --- | --- |
| Email intake | `intake.py` simulates inbox and outbox events from fixtures. A new message creates a tracked request and acknowledgement; missing details are requested, and an authorized reply is attached to the original request. Message IDs and requester identity are checked to prevent duplicate or unauthorized actions. |
| Workflow visibility | Request state and history expose status, owner, next action, and events. The prototype uses in-memory state rather than durable production storage. |
| Policy-controlled approval | Versioned policy sections and structured cost-tier records are ingested into ChromaDB. Retrieved tier context is supplied to the approval agent, which proposes an ordered chain using directory tools. Silence triggers reminders/escalation; it is never approval. |
| Budget | Once human approvals are complete, the agent can invoke `create_budget_release_request`. The tool validates the approval state and records an automatically approved simulated budget release. This is not a finance-system integration. |
| Prerequisites | Fixtures and tools model eligibility, named-user license entitlement, device ownership/readiness, OS compatibility, package approval, and user-scope/no-admin constraints. Missing or failed prerequisites hold the request open with an owner/next action. |
| Installation | A separate installation memory and secondary scheduler discover fully approved work and invoke the installation agent. The agent chooses whether to wait, queue a compatible package, simulate installation, verify, or leave the request pending with IT. |
| IT packaging | If no approved compatible package is available, the agent records an IT pending item. An IT reviewer can approve or reject packaging; a newly approved catalog version is picked up on a later scheduler cycle and the agent revisits the request. |
| Verification and closure | Job acceptance is distinct from installation success. Results must match the request, employee, registered device, account, package, desired catalog version, and user-scope checks. Only verified success closes the request and creates one simulated completion notification. Failures and unverified results remain open. |
| Policy assistant | `policy/` implements Chroma-backed RAG, not standard tool calling. Retrieved policy sections are passed as evidence to the LLM; answers must cite document and section or the assistant refuses. Unsupported questions and unavailable evidence fail closed. |

## Agentic workflow in practice

There are two agent roles. The approval agent receives the retrieved approval tier and request facts, then uses employee and role-holder tools to determine and propose the authorized approval sequence. The installation agent is invoked by the secondary scheduler with request, approval, device, catalog, entitlement, and available-tool context. The scheduler finds work; it does not prescribe the installation transition. The agent selects the next tool action, while each tool checks required authorization and state before applying it.

This is not a claim that all rules have disappeared. Business routing and next-step selection are agent-led and grounded in retrieved policy/context. Fixed checks remain for identity, decision authority, approval order, entitlement, target-device matching, no-admin installation, retry bounds, event idempotency, and verified closure. These guardrails protect the prototype from unsafe or unsupported agent decisions.

## ChromaDB RAG and policy evaluation

`policy/ingest_chroma.py` loads sectioned, versioned Markdown from `policy_documents/` into the `assetdesk_policy` collection. The client targets the configured Chroma tenant/database (defaults described in the project plan). Records retain document, version, section, approval-status, and source metadata. `policy/retrieval.py` retrieves policy sections; `policy/assistant.py` provides grounded answers with validated citations or refusal. Approval routing also retrieves the relevant cost-tier record before the approval agent runs.

The frozen evaluation set has 16 cases, including at least three unsupported questions, two wording-variation pairs, and a question requiring two documents. `policy/evaluate.py` compares top-1 baseline retrieval with top-6 retrieval as the documented improvement, reporting source recall, answer correctness, citation validity, and refusal accuracy. The harness and cases exist, but live baseline and revised scores are **pending**: the recorded environment lacked the Chroma client/server connection and `OPENAI_API_KEY`. Unit tests with injected evidence do not count as a completed live RAG evaluation. The current prototype policy files are marked unverified and must be replaced by approved current company sources before operational use.

## Data, replay protection, and audit

Synthetic fixtures provide ten employee-device assignments, approved software versions, and license entitlements. The catalog selects the latest approved compatible version; a user-requested version is recorded but does not override that rule. Stable message, decision, job, result, verification, and notification keys prevent duplicate events from repeating business actions during a process run. Mismatched, stale, or duplicate deployment results cannot close the wrong request. Timeline/history records actions and outcomes. Because stores are in memory, replay protection and audit history do not survive restart.

## Participant guide requirements and implementation status

The table maps the participant guide's required outcomes to the prototype. “Implemented” means represented in code/fixtures and covered by tests; it does not mean connected to a production service.

| Guide requirement | L3 implementation and evidence | Status / boundary |
| --- | --- | --- |
| One request and acknowledgement per email; deduplicate and attach authorized replies | `intake.py`, inbound email fixtures, intake acceptance and idempotency tests | Implemented as a repeatable inbox simulation. Sender identity is checked against sample employees; there is no live mailbox. |
| Capture requester, software/version, laptop, reason, cost/currency, and license details; ask for missing information | Intake captures supplied fields and requests missing details, including currency when needed; the reply updates the same request | Implemented in simulation. Unknown identity or device is not guessed; company-specific field rules still need policy-owner review. |
| Show status, owner, next action, and event history | Workflow state/history and installation memory expose request progress and operational events | Implemented for the process lifetime; no durable database or restart recovery. |
| Check eligibility, existing-entitlement exception, license, device, OS, package, and budget | Approval and installation tools inspect policy tier, sample entitlement assignments, registered device, compatibility, approved catalog, and simulated budget release | Implemented with synthetic data. License authority, budget authority, eligibility policy, and real device status are not integrated. |
| Ordered authorized approvals, no self-approval, actor/reason/time, rejection blocks deployment | L2 approval chain and authorization checks are retained and regression tested; the agent routes from retrieved tier context | Implemented. CLI fixture identities are not authenticated enterprise accounts. |
| Reminders and escalation; silence never approves | Existing L2 reminder/escalation behavior retained and exercised with controlled time; notification state distinguishes queued from delivered | Implemented in simulation; delivery timing/provider must be configured for production. |
| Automatically dispatch approved package to eligible device; wait for offline devices or missing packages | Secondary scheduler invokes the installation agent; agent selects retry/IT-pending or job actions through tools; catalog updates allow pending work to resume | Implemented as a deployment simulation. No endpoint management or installer is invoked. |
| Separate accepted job from install; verify matching version and checks; close and notify once only on verified success | Install records are separately verified against request/device/user/package/version/scope/checks; failure or mismatch stays open; completion notification is idempotent | Implemented in simulation and covered by acceptance/idempotency tests. Notification is queued in an outbox, not delivered by email. |
| Bound retries; handle duplicate, late, and mismatched results; no false success | Configurable `ASSETDESK_INSTALL_MAX_ATTEMPTS` (default 3); offline waits do not consume an attempt; external-result checks and duplicate keys guard state | Implemented in memory. No production rollback; no supported delivery adapter is configured. |
| Policy answers from current sources with citations, refuse unsupported questions, handle paraphrases and multi-document answers | Chroma RAG retrieves policy sections and sends them to the LLM as context (not standard tool calling); citation validation and refusal paths are tested | Mechanism implemented. Current corpus is marked unverified, so current-company-policy compliance is not established. |
| Evaluate at least 12 cases, including 3 refusals, 2 wording variations, 1 cross-document case; baseline, improvement, revised results | `policy/evaluation_cases.json` has 16 cases with those categories; evaluator compares top-1 against top-6 retrieval and reports separate metrics | Cases and comparison harness implemented; measured live baseline/revised results and failure diagnosis remain outstanding because Chroma/API access was unavailable in the recorded run. |
| Handover, review/ownership records, walkthrough evidence, and rollout recommendation | Operating notes, acceptance coverage, plans, this report, and known limits describe setup and architecture | Partial delivery package. A completed Delegate/Review/Own log, named owner decisions, actual run artifacts/screenshots, upload cover sheet, and reviewer sign-off are not yet recorded here. |

## Requirement clarification and ownership decisions

The prototype uses fixture-backed email events as the agreed demonstration channel; it does not connect to an employee mailbox. A message ID identifies a delivery for deduplication, while the sender must resolve to a fixture employee before a reply can change the request. Requests without required details wait for clarification. This is a demonstration choice, not a decision about the eventual production channel.

The codebase has synthetic employee, role-holder, device, entitlement, package, and policy records, but the participant guide requires real ownership and authority to be agreed. The following questions therefore remain open for the reviewer/company owners: which mailbox and identity provider are authoritative; who owns current policy and its effective dates; which approval roles and timing/escalation schedule apply; who owns catalog/package approval; which license service grants entitlement; how budget release is authorized; which device-readiness and verification signals are trusted; and who owns deployment operations and exception handling. These are handover dependencies, not values inferred by the prototype.

The guide's responsibility model is reflected in the work, but a signed responsibility log still needs to be completed by the participant/reviewer:

- **Delegate:** AI-assisted drafting and bounded code/document generation, including this comparison report. Verification should be recorded against tests, source documents, and a manual review.
- **Review:** Agent prompts/tool behavior, policy extraction and citations, acceptance scenarios, and claims about coverage. The current policy corpus and test evidence require human review before operational reliance.
- **Own:** Company policy interpretation, data permission, identity and approver authority, acceptance criteria, risk acceptance, final handover, and any rollout decision remain with named people, not the model.

## Submission readiness against the guide

The repository contains the working prototype, fixture configuration, dependency manifest, setup/evaluation instructions, acceptance coverage, policy cases, and this L2-to-L3 report. The recorded automated suite is useful repeatable evidence, and the tests distinguish a queued job from verified completion. The guide's formal package is not fully complete until the participant prepares the assignment cover, records agreed decisions/owners and Delegate/Review/Own evidence, runs and saves the end-to-end walkthrough outputs, completes live policy evaluation with baseline and revised metrics plus failure diagnosis, obtains review/sign-off, and uploads the labeled files to the assigned shared folder. The upload folder, due date, full name/team, and reviewer are intentionally not assumed here because the guide leaves them to agreement.

## Validation and operating commands

L3 retains the L2 unit suites and adds acceptance, idempotency, deployment, and policy-assistant tests. The recorded complete suite result is 107 tests passing:

```bash
cd L3
../.venv/bin/python -m unittest discover -s tests -q
```

To start the prototype, run `python main.py` from `L3/`. From the same directory, `python -m policy.ingest_chroma` ingests policy documents, and `python -m policy.evaluate` runs the live RAG evaluation. The latter two require the configured ChromaDB server; evaluation also requires `OPENAI_API_KEY`. Install project dependencies from the repository root with `python -m pip install -r requirements.txt`.

## Limitations and handover

This is a simulation, not a production deployment service. It has no live mailbox, authenticated approver login, durable request database, finance or license provider, endpoint-management integration, installer execution, or rollback. Notifications and device installs are simulated. Offline retry and installation retry limits are modeled; retry attempts are bounded by `ASSETDESK_INSTALL_MAX_ATTEMPTS` (default 3), and offline retries do not consume an installation attempt. Package, device, and entitlement fixtures are examples, not company inventory. Policies have unverified status and unspecified effective dates.

Before rollout, owners must supply and approve current policy documents; employee identity and approver sources; mailbox and reply authorization; budget process; license inventory; registered device/readiness data; approved package/version sources; deployment and verification services; durable audit/idempotency storage; notification delivery; security/operations ownership; and a monitored live policy evaluation. The recommended next step is a controlled integration pilot using those approved sources and real service adapters, with this prototype’s simulated behavior kept clearly separated from operational outcomes.
