# L3 Device Installation Simulation Plan

## Purpose and boundary

Demonstrate that an approved request reaches the correct employee device and closes only after the simulated installation is verified. This is a prototype: do not run installers, change the host laptop, require administrator rights, or connect to endpoint management. Model the user's laptop as a registered fixture device and record simulated state in the L3 prototype store.

## Simulation model

Keep the simulation behind Agent tools so a real deployment service could replace the simulator later. A secondary scheduler may discover fully approved requests and invoke the Agent, but it must not choose the install transition. The Agent inspects tool results and chooses to wait, create an IT packaging ticket, queue the latest version, simulate an install, or verify it. Tools enforce authorization and user-scope safeguards.

- **Device fixture:** Register a fake device ID, assigned employee ID, operating system/version, online state, disk space, and readiness checks. A request may target only the employee's registered, eligible device.
- **Package catalog:** List approved software package IDs, exact versions, supported operating systems, availability, and required post-install checks. A missing or unapproved package is held for packaging review; never substitute a different package or version.
- **Deployment job:** After identity, eligibility, license, budget, device-readiness, and human approval gates pass, create one job with a stable idempotency key derived from request, device, package, and version. Record `accepted` separately from installation.
- **Simulated installer:** An Agent tool consumes an accepted job and returns a fixture result. Store the expected package/version and device ID in separate installation memory. Represent installed state by the employee account, device, package, and version in that memory, not in the laptop's real filesystem or operating system.
- **Verifier:** Independently compare the job target with the simulated device's reported package ID and version, and evaluate every required check. Mark the request `completed` only when all checks pass. A job acceptance, missing result, mismatched device/version, or failed check leaves it open.

## Request lifecycle

1. Intake and approval stay in the existing L3 request flow. A secondary scheduler copies only requests with all approvers approved into the separate installation memory and invokes the Agent with the request, approval list, prompt, and tools. The Agent chooses the next step; each tool enforces its specific safety checks.
2. If the device is offline, set `waiting_for_device`, record the retry time/count, and retry on a controlled schedule. Repeated delivery of the same job must not create another installation action. Escalate after a configured retry limit without treating silence as success.
3. If no approved, compatible version is available, the Agent adds the software to the IT pending list and sets `waiting_for_package`. IT publishes an approved version in the catalog fixture. The scheduler reloads that catalog and invokes the Agent, which selects the latest compatible approved version and resumes the same request.
4. When gates pass, queue the job and record the queue event. The adapter then returns an explicit simulated installation result; it must not mark the request complete merely because the job was accepted.
5. Verify the result against the request's employee, registered device, package, version, and post-install checks. On failure or missing evidence, keep the request open with an actionable owner/next step. On verified success, append one completion event and send one simulated completion email.

## Repeatable demonstration cases

- **Success:** eligible online device, available approved package, matching version and passing checks; one job, one verified result, one completion message.
- **Offline device:** request waits, one or more controlled retries occur, then installation proceeds once the fixture changes to online.
- **Unavailable package:** request is held for packaging; no job is accepted until the exact package/version is marked ready.
- **Failed install:** simulated installer returns failure; request remains open and records the failure owner/action.
- **Wrong device or version:** verifier rejects the result and leaves the request open.
- **No verification result:** job acceptance is visible, but request remains open and no completion message is sent.
- **Duplicate events:** replaying a deployment job, install result, or verifier event does not repeat state changes or notifications.

The sample fixture set assigns ten devices to L2 employees and includes five synthetic catalog entries with multiple approved versions. Catalog versions use a release rank so the Agent can see which compatible version is latest. One device is offline, one is not ready, and one has a simulated failure profile for repeatable edge cases. Every catalog record is marked user-scope installable and does not require administrator rights.

## Evidence and handover

For each case, retain a request timeline showing the approval, prerequisite results, target device, package/version, job ID and acceptance time, simulated installer result, verifier checks, owner, next action, and completion state. The success evidence should make the distinction between `job accepted`, `installation reported`, and `installation verified` visible. Document that device profiles, package catalog entries, and installer outcomes are synthetic fixtures. A later real rollout would require named owners and approved sources for device identity/readiness, license entitlement, package signing/versioning, deployment credentials, result reporting, and verification checks.
