---
document_id: approval-lifecycle-controls
document_title: Approval Lifecycle, Rejection, and Escalation Controls
version: l3-prototype-1
effective_date: unspecified
approval_status: unverified
authority: L2 prototype safeguards, reconstructed from source code and decisions
source_path: L3/workflow/scheduler.py; L3/workflow/routing.py; L3/workflow/workflow_tools.py; L3/workflow/submission.py; L3/DECISIONS.md
---

# Approval Lifecycle, Rejection, and Escalation Controls

## §1 — Explicit decisions and completion

Silence, a timeout, a reminder, or an agent response cannot count as an approval. A human approver must explicitly record `APPROVED` or `REJECTED`. The workflow may become approved only after every required approver has approved in order. A rejected request cannot be changed or advanced.

## §2 — Rejection reason

A rejection requires a reason of at least 10 characters and at least two words after trimming whitespace. Stored reasons collapse repeated whitespace and line breaks to single spaces.

## §3 — Reminders and escalation

The prototype waits 24 hours after notifying an approver before sending a reminder. It sends at most two reminders; if the approver remains silent after those reminders, it escalates for manual action. Escalation does not record a decision or approve the request. Invalid or unavailable agent routing is retried up to three times before escalation.

## §4 — Duplicate requests and resubmission

The prototype treats a request as a duplicate when the same normalized requester email submits the same software while an earlier request is pending, approved, blocked, or escalated. A rejected request is terminal and does not prevent a new request for that software. The earlier request remains unchanged.

## §5 — Audit and repeat decisions

Decisions are recorded once, by the authorized approver, with actor and timestamp in workflow history. Duplicate decisions and changes to terminal requests are refused. Approval is a workflow handoff only; deployment and installation are outside this L2-derived rule.
