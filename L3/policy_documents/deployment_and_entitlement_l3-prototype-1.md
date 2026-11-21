---
document_id: deployment-and-entitlement-controls
document_title: Prototype License, Deployment, and Verification Controls
version: l3-prototype-1
effective_date: unspecified
approval_status: unverified
authority: L3 prototype configuration, not company policy
source_path: L3/installation/memory.py; L3/installation/tools.py; L3/fixtures/license_entitlements.json
---

# Prototype License, Deployment, and Verification Controls

## §1 — Named-user entitlement

The prototype allows an existing-entitlement exception only when the requester employee ID is explicitly listed as assigned to the named-user license. Otherwise it allocates one available seat. Missing license configuration or exhausted seats hold the request for a licensing administrator; the system does not infer entitlement.

## §2 — Device and package prerequisites

Deployment requires all human approvals, a verified entitlement when the software requires one, the employee's registered device and matching account, an online and ready device, and an approved available package version compatible with the device operating system. Installation runs in user scope and must not require administrator rights.

## §3 — Retry and completion

The prototype permits at most `ASSETDESK_INSTALL_MAX_ATTEMPTS` installation attempts (default three); an offline device does not consume an attempt. Exhausted attempts remain open for IT support. A deployment result must match the job, request, device, employee, account, package, and user scope. Only a matching installed version and passing required checks may close the request. Duplicate and late results cannot close it again.
