---
document_id: identity-and-approver-authorization
document_title: Requester Identity and Approver Authorization Controls
version: l3-prototype-1
effective_date: unspecified
approval_status: unverified
authority: L2 prototype safeguards, reconstructed from source code and decisions
source_path: L3/workflow/submission.py; L3/workflow/validation.py; L3/mock_data/employees.py; L3/DECISIONS.md
---

# Requester Identity and Approver Authorization Controls

## §1 — Requester identity

When the requester ID exists in the employee directory, the submitted email must match the email recorded for that employee. A mismatch is refused; the system must not guess or silently substitute another identity.

## §2 — Manager of record

The manager approver comes from the employee directory, not from a manager name typed into the request. A supplied manager name is only checked against the manager of record and cannot choose or replace the approver. Ambiguous names are not resolved by guessing.

## §3 — Self-approval and substitutes

A requester may never approve or reject their own request. If the requester is also their own manager, the configured substitute approver is used for the Manager stage. If no valid substitute is configured, or the substitute is the requester, routing fails closed and requires manual handling.

## §4 — Authorized decision maker

Only the currently assigned approver may submit a decision for the active stage. A decision from a later approver, a requester, or an approver who already decided is refused. Each stage must be handled in order.
