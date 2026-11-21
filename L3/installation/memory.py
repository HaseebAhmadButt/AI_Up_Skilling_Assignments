"""Separate in-memory store for installation, device, catalog, and IT queue state."""

from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
memory_lock = threading.RLock()
device_registry = {}
approved_software_catalog = {}
license_entitlements = {}
installation_requests = {}
it_pending_software = {}
deployment_jobs = {}
installed_user_software = {}
completion_messages = []
_completion_keys = set()
_it_approved_package_overrides = {}
_license_allocations = {}
_license_policy_overrides = {}
_external_result_events = {}
try:
    MAX_INSTALL_ATTEMPTS = max(1, int(os.getenv("ASSETDESK_INSTALL_MAX_ATTEMPTS", "3")))
except ValueError:
    MAX_INSTALL_ATTEMPTS = 3


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def refresh_fixtures():
    """Load or refresh the prototype's device and approved package records from JSON."""
    device_records = json.loads((FIXTURE_DIR / "employee_devices.json").read_text(encoding="utf-8"))
    catalog_records = json.loads((FIXTURE_DIR / "approved_software.json").read_text(encoding="utf-8"))
    entitlement_records = json.loads((FIXTURE_DIR / "license_entitlements.json").read_text(encoding="utf-8"))
    with memory_lock:
        device_registry.clear()
        device_registry.update({record["device_id"]: record for record in device_records})
        approved_software_catalog.clear()
        approved_software_catalog.update({record["software_name"].casefold(): record for record in catalog_records})
        license_entitlements.clear()
        license_entitlements.update({record["software_name"].casefold(): record for record in entitlement_records})
        for software_key, override in _license_policy_overrides.items():
            current = license_entitlements.get(software_key)
            if current is None:
                license_entitlements[software_key] = copy.deepcopy(override)
            else:
                current["seat_limit"] = override["seat_limit"]
                current["entitlement_type"] = override["entitlement_type"]
                for employee_id in override.get("assigned_users", []):
                    if employee_id not in current["assigned_users"]:
                        current["assigned_users"].append(employee_id)
        for allocation in _license_allocations.values():
            entitlement = license_entitlements.get(allocation["software_name"].casefold())
            if entitlement and allocation["employee_id"] not in entitlement["assigned_users"]:
                entitlement["assigned_users"].append(allocation["employee_id"])
        for software_key, override in _it_approved_package_overrides.items():
            catalog_record = approved_software_catalog.get(software_key)
            if catalog_record is None:
                catalog_record = copy.deepcopy(override)
                approved_software_catalog[software_key] = catalog_record
                continue
            catalog_record["package_id"] = override["package_id"]
            catalog_record["license_required"] = override.get("license_required")
            catalog_record["user_scope_installable"] = True
            catalog_record["requires_admin"] = False
            for version in override["versions"]:
                existing = next((entry for entry in catalog_record["versions"]
                                 if entry["version"] == version["version"]), None)
                if existing:
                    existing.update(copy.deepcopy(version))
                else:
                    catalog_record["versions"].append(copy.deepcopy(version))


def _event(record, event, actor, details):
    record.setdefault("history", []).append({"timestamp": _now(), "event": event,
                                             "actor": actor, "details": details})


def register_approved_request(workflow):
    """Copy a completed approval into install memory once; keep L2 approval state separate."""
    request_id = workflow["request_id"]
    with memory_lock:
        if request_id in installation_requests:
            return copy.deepcopy(installation_requests[request_id])
        request = workflow["request"]
        employee_id = str(request.get("requester_identity", "")).split(",", 1)[0].strip().upper()
        record = {
            "request_id": request_id,
            "employee_id": employee_id,
            "requester_email": request.get("requester_email", ""),
            "software_name": request.get("policy_context", "").strip(),
            "request_cost": request.get("request_cost"),
            "cost_currency": request.get("cost_currency", "USD"),
            "requested_version": request.get("requested_version"),
            "requested_device_id": request.get("device_id"),
            "license_details": request.get("license_details"),
            "approval_chain": copy.deepcopy(workflow["approval_chain"]),
            "approved_at": _now(),
            "status": "approved_waiting_for_agent",
            "owner": "Installation Agent",
            "next_action": "Agent to inspect the device and approved software catalog",
            "device_id": None,
            "license_status": "not_checked",
            "license_entitlement_id": None,
            "package_id": None,
            "version": None,
            "job_id": None,
            "history": [],
        }
        _event(record, "approval_handoff", "approval_scheduler", "All L2 approvers approved; installation workflow is ready for the Agent.")
        installation_requests[request_id] = record
        return copy.deepcopy(record)


def get_installation_request(request_id):
    with memory_lock:
        record = installation_requests.get(request_id)
        return copy.deepcopy(record) if record else None


def list_installation_requests():
    with memory_lock:
        return copy.deepcopy(list(installation_requests.values()))


def list_agent_work():
    active = {"approved_waiting_for_agent", "waiting_for_device", "waiting_for_package", "waiting_for_license",
              "job_accepted", "installation_reported", "install_failed", "verification_failed"}
    with memory_lock:
        return [copy.deepcopy(record) for record in installation_requests.values()
                if record["status"] in active]


def find_device_for_employee(employee_id):
    with memory_lock:
        for device in device_registry.values():
            if device["employee_id"] == employee_id:
                return copy.deepcopy(device)
    return None


def list_approved_versions(software_name, device_id):
    with memory_lock:
        device = device_registry.get(device_id)
        software = approved_software_catalog.get(software_name.strip().casefold())
        if device is None:
            return {"found": False, "error": "No registered user device found."}
        if software is None:
            return {"found": True, "software_name": software_name, "versions": []}
        versions = [copy.deepcopy(version) for version in software["versions"]
                    if version.get("approved") and version.get("available")
                    and device["os"] in version.get("supported_os", [])]
        versions.sort(key=lambda version: version.get("release_rank", 0), reverse=True)
        for index, version in enumerate(versions):
            version["latest"] = index == 0
        return {
            "found": True,
            "software_name": software["software_name"],
            "package_id": software["package_id"],
            "user_scope_installable": software.get("user_scope_installable", False),
            "requires_admin": software.get("requires_admin", True),
            "license_required": software.get("license_required"),
            "versions": versions,
        }


def ensure_license_entitlement(request_id):
    """Grant a fixture entitlement only after approvals; honor a verified existing named-user seat first."""
    with memory_lock:
        request = installation_requests.get(request_id)
        if request is None:
            return {"success": False, "status": "unknown_request", "error": "Unknown installation request."}
        if not request["approval_chain"] or any(step.get("decision") != "APPROVED"
                                                 for step in request["approval_chain"]):
            return {"success": False, "status": "blocked", "error": "License check requires all human approvals."}
        software = approved_software_catalog.get(request["software_name"].casefold())
        if software is None or software.get("license_required") is None:
            request.update(status="waiting_for_license", owner="Licensing administrator",
                           next_action=f"Configure license policy for {request['software_name']}")
            if request.get("license_status") != "policy_missing":
                _event(request, "license_policy_missing", "installation_agent",
                       f"No explicit license requirement is configured for {request['software_name']}.")
            request["license_status"] = "policy_missing"
            return {"success": False, "status": "policy_missing", "error": "License policy is not configured."}
        if not software["license_required"]:
            request.update(license_status="not_required", license_entitlement_id="not-required")
            return {"success": True, "status": "not_required", "entitlement_id": "not-required"}
        entitlement = license_entitlements.get(request["software_name"].casefold())
        if entitlement is None:
            request.update(status="waiting_for_license", owner="Licensing administrator",
                           next_action=f"Add named-user entitlement details for {request['software_name']}",
                           license_status="unavailable")
            return {"success": False, "status": "unavailable", "error": "No entitlement record is configured."}

        employee_id = request["employee_id"]
        if employee_id in entitlement["assigned_users"]:
            source = "existing_entitlement_exception"
        elif len(entitlement["assigned_users"]) < int(entitlement["seat_limit"]):
            entitlement["assigned_users"].append(employee_id)
            _license_allocations[request_id] = {"software_name": request["software_name"],
                                                "employee_id": employee_id}
            source = "new_seat_allocated"
        else:
            request.update(status="waiting_for_license", owner="Licensing administrator",
                           next_action=f"Provide a named-user {request['software_name']} entitlement",
                           license_status="unavailable")
            if request.get("license_status") != "unavailable":
                _event(request, "license_unavailable", "installation_agent",
                       f"No free {entitlement['entitlement_type']} seats are available.")
            return {"success": False, "status": "unavailable", "error": "No license entitlement is available."}

        entitlement_id = f"LIC-{request['software_name'].upper().replace(' ', '-')}-{employee_id}"
        request.update(license_status="entitled", license_entitlement_id=entitlement_id,
                       license_source=source, status="approved_waiting_for_agent",
                       owner="Installation Agent", next_action="License confirmed; Agent may continue package and device checks")
        if request.get("license_granted_event") != entitlement_id:
            _event(request, "license_entitled", "license_service",
                   f"Verified {source} for {employee_id}; entitlement {entitlement_id}.")
            request["license_granted_event"] = entitlement_id
        return {"success": True, "status": "entitled", "entitlement_id": entitlement_id, "source": source}


def update_installation_request(request_id, *, status=None, owner=None, next_action=None, **fields):
    with memory_lock:
        record = installation_requests[request_id]
        for key, value in {"status": status, "owner": owner, "next_action": next_action, **fields}.items():
            if value is not None:
                record[key] = value
        return copy.deepcopy(record)


def append_install_history(request_id, event, actor, details):
    with memory_lock:
        record = installation_requests[request_id]
        _event(record, event, actor, details)


def add_it_pending_item(request_id, device_id, reason):
    with memory_lock:
        request = installation_requests[request_id]
        existing = it_pending_software.get(request_id)
        if existing:
            return copy.deepcopy(existing)
        item = {
            "pending_id": f"ITP-{len(it_pending_software) + 1:04d}",
            "request_id": request_id,
            "employee_id": request["employee_id"],
            "requester_email": request["requester_email"],
            "software_name": request["software_name"],
            "device_id": device_id,
            "requested_version": "latest approved user-scoped version when available",
            "status": "pending",
            "reason": reason,
            "created_at": _now(),
        }
        it_pending_software[request_id] = item
        request.update(status="waiting_for_package", owner="IT packaging", device_id=device_id,
                       next_action=f"Approve and publish a user-scoped version of {request['software_name']}")
        _event(request, "added_to_it_pending", "installation_agent", reason)
        return copy.deepcopy(item)


def list_it_pending_items():
    with memory_lock:
        return copy.deepcopy(list(it_pending_software.values()))


def decide_it_pending_item(request_id, decision, *, package_id=None, version=None,
                           license_required=None, seat_limit=None):
    """Record an IT packaging decision; approval publishes a simulated user-scope package version."""
    decision = str(decision).strip().lower()
    if decision not in {"approve", "reject"}:
        return {"success": False, "error": "Decision must be approve or reject."}
    with memory_lock:
        item = it_pending_software.get(request_id)
        request = installation_requests.get(request_id)
        if item is None or request is None:
            return {"success": False, "error": "No IT packaging request was found."}
        if item["status"] != "pending":
            return {"success": False, "error": f"This IT request is already {item['status']}."}

        if decision == "approve":
            package_id = str(package_id or "").strip()
            version = str(version or "").strip()
            if not package_id or not version:
                return {"success": False, "error": "Package ID and version are required to approve packaging."}
            configured_license = license_entitlements.get(item["software_name"].casefold())
            if license_required is True and configured_license is None and (
                    seat_limit is None or int(seat_limit) < 1):
                return {"success": False, "error": "A positive license seat limit is required for licensed software."}
            device = device_registry.get(item["device_id"])
            if device is None:
                return {"success": False, "error": "The requester's registered device is unavailable."}
            catalog_record = approved_software_catalog.get(item["software_name"].casefold())
            if catalog_record is None:
                catalog_record = {
                    "software_name": item["software_name"],
                    "package_id": package_id,
                    "license_required": license_required,
                    "user_scope_installable": True,
                    "requires_admin": False,
                    "versions": [],
                }
                approved_software_catalog[item["software_name"].casefold()] = catalog_record
            catalog_record["package_id"] = package_id
            if license_required is not None:
                catalog_record["license_required"] = license_required
            catalog_record["user_scope_installable"] = True
            catalog_record["requires_admin"] = False
            prior = next((entry for entry in catalog_record["versions"] if entry["version"] == version), None)
            if prior:
                prior.update(approved=True, available=True)
                prior.setdefault("release_rank", max((v.get("release_rank", 0) for v in catalog_record["versions"]), default=0))
                prior.setdefault("supported_os", [device["os"]])
                prior.setdefault("required_checks", ["user_profile_install", "application_launch"])
            else:
                rank = max((entry.get("release_rank", 0) for entry in catalog_record["versions"]), default=0) + 1
                catalog_record["versions"].append({
                    "version": version,
                    "release_rank": rank,
                    "approved": True,
                    "available": True,
                    "supported_os": [device["os"]],
                    "required_checks": ["user_profile_install", "application_launch"],
                })
            override = _it_approved_package_overrides.setdefault(item["software_name"].casefold(), {
                "software_name": item["software_name"], "package_id": package_id,
                "license_required": catalog_record.get("license_required"),
                "user_scope_installable": True, "requires_admin": False, "versions": [],
            })
            override["package_id"] = package_id
            override["license_required"] = catalog_record.get("license_required")
            approved_version = next((entry for entry in catalog_record["versions"]
                                     if entry["version"] == version), None)
            if approved_version is not None:
                override["versions"] = [entry for entry in override["versions"]
                                         if entry["version"] != version]
                override["versions"].append(copy.deepcopy(approved_version))
            if catalog_record.get("license_required") is True and seat_limit is not None:
                if configured_license is None:
                    license_entitlements[item["software_name"].casefold()] = {
                        "software_name": item["software_name"], "entitlement_type": "named_user",
                        "seat_limit": int(seat_limit), "assigned_users": [],
                    }
                    _license_policy_overrides[item["software_name"].casefold()] = copy.deepcopy(
                        license_entitlements[item["software_name"].casefold()])
                else:
                    configured_license["seat_limit"] = int(seat_limit)
                    _license_policy_overrides[item["software_name"].casefold()] = copy.deepcopy(configured_license)
            item.update(status="approved", decision="APPROVED", package_id=package_id,
                        version=version, decided_at=_now())
            request.update(status="waiting_for_package", owner="Installation Agent",
                           package_id=package_id, version=version,
                           next_action="Approved package is ready; installation Agent will retry automatically")
            _event(request, "it_package_approved", "IT packaging", f"Approved {package_id} {version}; package published to the prototype catalog.")
            return {"success": True, "status": item["status"], "request_id": request_id,
                    "package_id": package_id, "version": version}

        item.update(status="rejected", decision="REJECTED", decided_at=_now())
        request.update(status="package_rejected", owner="IT packaging",
                       next_action="Review the packaging rejection and submit a revised package")
        _event(request, "it_package_rejected", "IT packaging", "IT rejected the proposed software packaging request.")
        return {"success": True, "status": item["status"], "request_id": request_id}


def create_or_get_job(request_id, device_id, package_id, version):
    with memory_lock:
        request = installation_requests[request_id]
        request_job_id = request.get("job_id")
        if request_job_id:
            request_job = deployment_jobs.get(request_job_id)
            if request_job:
                if (request_job["device_id"], request_job["package_id"], request_job["version"]) == (
                        device_id, package_id, version):
                    return copy.deepcopy(request_job), False
                raise ValueError(f"Request {request_id} already has deployment job {request_job_id}.")
        existing = next((job for job in deployment_jobs.values()
                         if job["request_id"] == request_id and job["device_id"] == device_id
                         and job["package_id"] == package_id and job["version"] == version), None)
        if existing:
            return copy.deepcopy(existing), False
        software = approved_software_catalog.get(request["software_name"].casefold(), {})
        package_version = next((item for item in software.get("versions", [])
                                if item.get("version") == version), {})
        job_id = f"JOB-{len(deployment_jobs) + 1:04d}"
        job = {
            "job_id": job_id,
            "request_id": request_id,
            "employee_id": request["employee_id"],
            "user_account": request["requester_email"],
            "device_id": device_id,
            "package_id": package_id,
            "version": version,
            "install_scope": "user",
            "requires_admin": False,
            "required_checks": copy.deepcopy(package_version.get("required_checks", [])),
            "status": "accepted",
            "attempts": 0,
            "max_attempts": MAX_INSTALL_ATTEMPTS,
            "accepted_at": _now(),
            "installation_result": None,
            "verification": None,
        }
        deployment_jobs[job_id] = job
        request.update(status="job_accepted", owner="Installation simulator",
                       next_action=f"Simulate user-scope installation of {package_id} {version}",
                       device_id=device_id, package_id=package_id, version=version, job_id=job_id)
        _event(request, "deployment_job_accepted", "installation_agent",
               f"{job_id} accepted for {device_id}, user scope, package {package_id} version {version}.")
        pending = it_pending_software.get(request_id)
        if pending:
            pending["status"] = "installing"
        return copy.deepcopy(job), True


def get_job(job_id):
    with memory_lock:
        job = deployment_jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def simulate_job(job_id):
    """Write a simulated per-user install result; never invokes an OS installer."""
    with memory_lock:
        job = deployment_jobs.get(job_id)
        if job is None:
            return {"success": False, "error": "Unknown deployment job."}
        if job["installation_result"] is not None:
            return copy.deepcopy(job["installation_result"])
        device = device_registry[job["device_id"]]
        request = installation_requests[job["request_id"]]
        if not device.get("online"):
            job["status"] = "waiting_for_device"
            request.update(status="waiting_for_device", owner="Requester/device support",
                           next_action="Bring the assigned device online; scheduler will ask the Agent to retry")
            if not job.get("offline_event_recorded"):
                _event(request, "device_offline", "installation_simulator",
                       f"{device['device_id']} is offline; no install was reported.")
                job["offline_event_recorded"] = True
            return {"success": False, "status": "waiting_for_device", "job_id": job_id,
                    "message": "Device is offline; installation was not performed."}
        if job["attempts"] >= job["max_attempts"]:
            job["status"] = "install_exhausted"
            request.update(status="install_exhausted", owner="IT support",
                           next_action=f"Installation exhausted {job['max_attempts']} attempts; administrator review required")
            if not job.get("exhausted_event_recorded"):
                _event(request, "installation_retries_exhausted", "installation_simulator",
                       f"No attempts remain for {job_id}; administrator review is required.")
                job["exhausted_event_recorded"] = True
            return {"success": False, "status": "install_exhausted", "job_id": job_id}
        job["attempts"] += 1
        outcome = device.get("simulated_install_outcome", "success")
        if outcome != "success":
            result = {"success": False, "status": "failed", "job_id": job_id,
                      "device_id": device["device_id"], "version": job["version"],
                      "user_account": job["user_account"], "install_scope": "user", "requires_admin": False}
            job.update(status="install_failed", installation_result=result)
            request.update(status="install_failed", owner="IT support",
                           next_action="Review the simulated installer failure before retrying")
            _event(request, "installation_failed", "installation_simulator", f"Simulated installation failed for {job_id}.")
            return copy.deepcopy(result)

        key = (device["device_id"], job["user_account"], job["package_id"])
        check_values = device.get("simulated_checks", {})
        checks = {check: bool(check_values.get(check, True)) for check in job["required_checks"]}
        installed = {"device_id": device["device_id"], "employee_id": job["employee_id"],
                     "user_account": job["user_account"], "package_id": job["package_id"],
                     "version": job["version"], "install_scope": "user", "requires_admin": False,
                     "checks": checks,
                     "installed_at": _now()}
        installed_user_software[key] = installed
        result = {"success": True, "status": "installation_reported", "job_id": job_id,
                  **copy.deepcopy(installed)}
        job.update(status="installation_reported", installation_result=result)
        request.update(status="installation_reported", owner="Installation verifier",
                       next_action="Agent to verify the reported device, user, version, scope, and checks")
        _event(request, "installation_reported", "installation_simulator",
               f"{job_id} reports {job['package_id']} {job['version']} in the user's profile on {device['device_id']}.")
        return copy.deepcopy(result)


def retry_failed_installation(job_id):
    """Schedule a bounded retry of the existing deployment job."""
    with memory_lock:
        job = deployment_jobs.get(job_id)
        if job is None:
            return {"success": False, "error": "Unknown deployment job."}
        if job["status"] not in {"install_failed", "verification_failed"}:
            return {"success": False, "error": f"Job status {job['status']} is not retryable."}
        request = installation_requests[job["request_id"]]
        if job["attempts"] >= job["max_attempts"]:
            job["status"] = "install_exhausted"
            request.update(status="install_exhausted", owner="IT support",
                           next_action=f"Installation exhausted {job['max_attempts']} attempts; administrator review required")
            if not job.get("exhausted_event_recorded"):
                _event(request, "installation_retries_exhausted", "installation_agent",
                       f"No attempts remain for {job_id}; administrator review is required.")
                job["exhausted_event_recorded"] = True
            return {"success": False, "status": "install_exhausted", "error": request["next_action"]}
        job["installation_result"] = None
        job["verification"] = None
        job["status"] = "accepted"
        request.update(status="job_accepted", owner="Installation simulator",
                       next_action=f"Retry user-scope installation (attempt {job['attempts'] + 1} of {job['max_attempts']})")
        _event(request, "installation_retry_scheduled", "installation_agent",
               f"Retry scheduled for {job_id}, attempt {job['attempts'] + 1} of {job['max_attempts']}.")
        return {"success": True, "job_id": job_id, "attempt": job["attempts"] + 1,
                "max_attempts": job["max_attempts"]}


def record_external_result(job_id, event_id, payload):
    """Accept one matching delivery callback; ignore duplicate, late, or cross-request results safely."""
    event_id = str(event_id or "").strip()
    event_key = (str(job_id), event_id)
    with memory_lock:
        if not event_id:
            return {"success": False, "error": "An external result event ID is required."}
        if event_key in _external_result_events:
            return copy.deepcopy(_external_result_events[event_key])
        job = deployment_jobs.get(job_id)
        if job is None:
            result = {"success": False, "status": "ignored", "error": "Unknown deployment job."}
            _external_result_events[event_key] = result
            return copy.deepcopy(result)
        request = installation_requests[job["request_id"]]
        if job["status"] in {"verified", "verification_failed", "install_exhausted"} or request["status"] == "completed":
            result = {"success": False, "status": "ignored", "error": "Late result for a closed or exhausted job."}
        elif job["attempts"] >= job["max_attempts"]:
            result = {"success": False, "status": "ignored", "error": "Configured installation attempts are exhausted."}
        elif job.get("installation_result") is not None:
            result = {"success": False, "status": "ignored", "error": "A result is already recorded for this attempt."}
        else:
            payload = payload if isinstance(payload, dict) else {}
            expected = {"request_id": job["request_id"], "device_id": job["device_id"],
                        "employee_id": job["employee_id"], "user_account": job["user_account"],
                        "package_id": job["package_id"], "install_scope": "user", "requires_admin": False,
                        "attempt": job["attempts"] + 1}
            mismatches = [field for field, value in expected.items() if payload.get(field) != value]
            checks = payload.get("checks")
            if not isinstance(payload.get("success"), bool) or not isinstance(checks, dict):
                mismatches.append("result_schema")
            elif any(not isinstance(value, bool) for value in checks.values()):
                mismatches.append("check_values")
            if mismatches:
                result = {"success": False, "status": "ignored",
                          "error": "Mismatched external result fields: " + ", ".join(mismatches)}
                _event(request, "external_result_rejected", "deployment_callback",
                       f"Event {event_id} ignored due to mismatched result fields: {', '.join(mismatches)}.")
            else:
                job["attempts"] += 1
                result_record = {"success": payload["success"],
                                 "status": "installation_reported" if payload["success"] else "failed",
                                 "job_id": job_id, "request_id": job["request_id"],
                                 "device_id": payload["device_id"], "employee_id": payload["employee_id"],
                                 "user_account": payload["user_account"], "package_id": payload["package_id"],
                                 "version": str(payload.get("version", "")),
                                 "install_scope": payload["install_scope"],
                                 "requires_admin": payload["requires_admin"], "checks": copy.deepcopy(checks),
                                 "attempt": expected["attempt"], "event_id": event_id, "reported_at": _now()}
                job["installation_result"] = result_record
                if payload["success"]:
                    installed_user_software[(job["device_id"], job["user_account"], job["package_id"])] = {
                        "device_id": job["device_id"], "employee_id": job["employee_id"],
                        "user_account": job["user_account"], "package_id": job["package_id"],
                        "version": result_record["version"], "install_scope": "user", "requires_admin": False,
                        "checks": copy.deepcopy(checks), "installed_at": _now(),
                    }
                    job["status"] = "installation_reported"
                    request.update(status="installation_reported", owner="Installation verifier",
                                   next_action="Verify the external result against the target device and package")
                    _event(request, "external_installation_result", "deployment_callback",
                           f"Accepted result event {event_id} for job {job_id}; verification is still required.")
                    result = {"success": True, "status": "installation_reported", "job_id": job_id}
                else:
                    job["status"] = "install_failed"
                    request.update(status="install_failed", owner="IT support",
                                   next_action="Review failure result and retry within the configured limit")
                    _event(request, "external_installation_failed", "deployment_callback",
                           f"Accepted failure event {event_id} for job {job_id}.")
                    result = {"success": True, "status": "install_failed", "job_id": job_id}
        _external_result_events[event_key] = copy.deepcopy(result)
        return copy.deepcopy(result)


def verify_job(job_id):
    with memory_lock:
        job = deployment_jobs.get(job_id)
        if job is None:
            return {"success": False, "error": "Unknown deployment job."}
        if job["verification"] is not None:
            return copy.deepcopy(job["verification"])
        result = job.get("installation_result")
        request = installation_requests[job["request_id"]]
        device = device_registry[job["device_id"]]
        if not result or not result.get("success"):
            return {"success": False, "status": "open", "error": "No successful installation result is available to verify."}
        key = (job["device_id"], job["user_account"], job["package_id"])
        installed = installed_user_software.get(key)
        checks = {
            "device_matches": result.get("device_id") == job["device_id"] == device["device_id"],
            "employee_matches": result.get("employee_id") == job["employee_id"] == device["employee_id"],
            "user_account_matches": result.get("user_account") == job["user_account"] == device["user_account"],
            "package_matches": result.get("package_id") == job["package_id"],
            "version_matches": result.get("version") == job["version"],
            "user_scope_only": result.get("install_scope") == "user" and job["install_scope"] == "user",
            "no_admin_required": result.get("requires_admin") is False and job["requires_admin"] is False,
            "reported_checks_pass": all(result.get("checks", {}).get(check) is True
                                         for check in job["required_checks"]),
            "stored_user_install_matches": installed is not None and installed.get("version") == job["version"],
        }
        success = all(checks.values())
        verification = {"success": success, "status": "verified" if success else "verification_failed",
                        "job_id": job_id, "checks": checks, "verified_at": _now()}
        job.update(status="verified" if success else "verification_failed", verification=verification)
        if success:
            request.update(status="completed", owner="None", next_action="Installation verified; request closed")
            _event(request, "installation_verified", "installation_agent", f"Verified {job['package_id']} {job['version']} on the assigned user device.")
            pending = it_pending_software.get(job["request_id"])
            if pending:
                pending["status"] = "completed"
            if job["request_id"] not in _completion_keys:
                _completion_keys.add(job["request_id"])
                completion_messages.append({"request_id": job["request_id"], "to": job["user_account"],
                                            "message": f"{job['package_id']} {job['version']} is installed and verified.",
                                            "sent_at": _now()})
                _event(request, "completion_message_sent", "simulated_email", "One completion email recorded in memory.")
        else:
            request.update(status="verification_failed", owner="IT support",
                           next_action="Review failed verification checks; request remains open")
            _event(request, "verification_failed", "installation_agent", "At least one installation verification check failed.")
        return copy.deepcopy(verification)


refresh_fixtures()
