# Installation Agent Prototype

The installation workflow is separate from `workflow/store.py`. `memory.py` owns the device registry, approved package catalog, install requests, IT pending items, jobs, per-user simulated installs, and completion outbox. The second scheduler only discovers fully approved L3 requests and invokes `agent.py`; the Agent chooses which installation tool to call next.

Run the L3 app from this directory with `python main.py`. After all approvers complete a request, the installation scheduler invokes the Agent automatically (requires the configured OpenAI API key). Option 7 displays installation and IT pending state. It may take up to one scheduler interval for new approved work to appear.

The ten synthetic device profiles are in `fixtures/employee_devices.json`. Sample approved software and versions are in `fixtures/approved_software.json`; `release_rank` identifies ordering within this prototype catalog. Named-user seat limits and existing assignments are in `fixtures/license_entitlements.json`. Existing entitlement reuse is granted only when the employee ID is explicitly assigned; otherwise an available seat is reserved once per request. Editing fixtures is picked up on the next installation scheduler cycle. To simulate an IT package becoming available, approve it in the IT packaging menu; the Agent revisits matching pending requests on its next cycle.

Installation retries use `ASSETDESK_INSTALL_MAX_ATTEMPTS` (default `3`). Offline retries do not consume an installation attempt. Exhausted retries remain open with IT support as owner. A delivery adapter may call `memory.record_external_result(job_id, event_id, payload)`; duplicate event IDs are idempotent, mismatched targets are ignored, and even accepted success results must pass verification before closure.

All install jobs and results exist only in Python memory. The simulator never runs an installer, writes to a real user profile, changes the host device, or requests administrator rights. Every simulated package is user-scope and marked as not requiring admin rights. The fixture versions and outcomes are examples, not current vendor package data.
