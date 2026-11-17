---
document_id: software-request-approval
document_title: Software Request Approval Routing
version: v2.0.0
effective_date: unspecified
approval_status: unverified
authority: L2 prototype rule, reconstructed from source code
source_path: L3/mock_data/policy.py
---

# Software Request Approval Routing

## §1 — Purpose and limits

This prototype rule maps a positive software request cost to an ordered human approval chain. It does not establish software eligibility, license entitlement, device readiness, deployment authorization, or a budget cap. Completing this chain means budget approval is complete in the prototype; it does not mean software has been installed.

## §2 — Approval thresholds

- A request costing less than $500 requires Manager approval only.
- A request costing $500 through $2,500 inclusive requires Manager approval, followed by IT Lead approval.
- A request costing more than $2,500 requires Manager approval, followed by IT Lead approval, followed by Finance Director approval.

The order is mandatory. The implementation labels this rule `v2.0.0`.

## §3 — Cost input

The request cost must be one valid positive monetary amount. Zero, negative values, malformed amounts, and text containing additional instructions are invalid. The implementation accepts a leading dollar sign, commas in correctly grouped thousands, and up to two decimal places.
