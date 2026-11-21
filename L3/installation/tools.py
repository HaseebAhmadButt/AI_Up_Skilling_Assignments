"""Tools the installation Agent uses to inspect and advance simulated installs."""

from langchain.tools import tool

from . import memory


@tool
def get_installation_context(request_id: str) -> dict:
    """Return an approved request, ordered approval list, current install state, job, and IT ticket."""
    request = memory.get_installation_request(request_id)
    if request is None:
        return {"found": False, "error": "No installation request with that ID."}
    job = memory.get_job(request.get("job_id")) if request.get("job_id") else None
    pending = next((item for item in memory.list_it_pending_items()
                    if item["request_id"] == request_id), None)
    return {"found": True, "request": request, "job": job, "it_pending": pending}


@tool
def find_user_device(employee_id: str) -> dict:
    """Find the registered fixture device assigned to this employee and show readiness/user scope."""
    device = memory.find_device_for_employee(employee_id)
    return {"found": device is not None, "device": device,
            "error": None if device else "No fixture device is registered for this employee."}


@tool
def list_approved_software_versions(software_name: str, device_id: str) -> dict:
    """List approved, available versions compatible with a device; latest is marked in the result."""
    return memory.list_approved_versions(software_name, device_id)


@tool
def check_license_entitlement(request_id: str) -> dict:
    """Verify an existing named-user entitlement or allocate one available seat after approval."""
    return memory.ensure_license_entitlement(request_id)


@tool
def wait_for_device(request_id: str, reason: str) -> dict:
    """Keep an approved install open until its assigned user device is online and ready."""
    request = memory.get_installation_request(request_id)
    if request is None:
        return {"success": False, "error": "Unknown installation request."}
    next_action = reason or "Make the assigned device available and ready; the scheduler will ask the Agent to retry"
    already_waiting = request["status"] == "waiting_for_device" and request["next_action"] == next_action
    memory.update_installation_request(
        request_id, status="waiting_for_device", owner="Endpoint support",
        next_action=next_action,
    )
    if not already_waiting:
        memory.append_install_history(request_id, "waiting_for_device", "installation_agent", next_action)
    return {"success": True, "status": "waiting_for_device", "request_id": request_id}


@tool
def add_to_it_pending_software(request_id: str, device_id: str, reason: str) -> dict:
    """Create an IT packaging ticket when requested software has no approved compatible version."""
    request = memory.get_installation_request(request_id)
    if request is None:
        return {"success": False, "error": "Unknown installation request."}
    if not request["approval_chain"] or any(step.get("decision") != "APPROVED" for step in request["approval_chain"]):
        return {"success": False, "error": "IT pending packaging may start only after every approver approved."}
    device = memory.find_device_for_employee(request["employee_id"])
    if device is None or device["device_id"] != device_id:
        return {"success": False, "error": "IT pending ticket must target the requester's assigned device."}
    item = memory.add_it_pending_item(request_id, device_id, reason)
    return {"success": True, "ticket": item,
            "message": "The request is waiting for IT to publish an approved user-scope package version."}


@tool
def queue_user_scope_install(request_id: str, device_id: str, package_id: str, version: str) -> dict:
    """Queue the latest approved compatible package for the requester's account without admin rights."""
    request = memory.get_installation_request(request_id)
    if request is None:
        return {"success": False, "error": "Unknown installation request."}
    if not request["approval_chain"] or any(step.get("decision") != "APPROVED" for step in request["approval_chain"]):
        return {"success": False, "error": "Installation is blocked until all human approvals are recorded."}
    if request.get("license_status") not in {"entitled", "not_required"}:
        return {"success": False, "error": "A verified license entitlement is required before deployment."}

    device = memory.find_device_for_employee(request["employee_id"])
    if device is None or device["device_id"] != device_id:
        return {"success": False, "error": "Target device is not registered to this requester."}
    if request.get("requested_device_id") and request["requested_device_id"] != device_id:
        return {"success": False, "error": "Target device does not match the employee's explicit laptop identity."}
    if device.get("user_account", "").casefold() != request["requester_email"].casefold():
        return {"success": False, "error": "Device user account does not match the requester."}
    if not device.get("online") or not device.get("ready"):
        return {"success": False, "error": "Device is offline or not ready; wait for the device before queuing."}
    if not device.get("user_scope_supported") or device.get("requires_admin_for_user_install"):
        return {"success": False, "error": "This device cannot meet the user-scope, no-admin installation requirement."}

    catalog = memory.list_approved_versions(request["software_name"], device_id)
    versions = catalog.get("versions", [])
    if not catalog.get("found") or not versions:
        return {"success": False, "error": "No approved and available version is compatible with this device."}
    if not catalog.get("user_scope_installable") or catalog.get("requires_admin"):
        return {"success": False, "error": "Catalog package is not approved for user-scope installation without admin rights."}
    latest = versions[0]
    if package_id != catalog["package_id"] or version != latest["version"]:
        return {"success": False, "error": f"Choose the latest compatible approved version: {latest['version']}."}

    if request.get("job_id"):
        existing_job = memory.get_job(request["job_id"])
        if existing_job and (existing_job["device_id"], existing_job["package_id"], existing_job["version"]) != (
                device_id, package_id, version):
            return {"success": False,
                    "error": f"Request already has deployment job {existing_job['job_id']} for "
                             f"{existing_job['package_id']} {existing_job['version']}; a second job is refused."}

    job, created = memory.create_or_get_job(request_id, device_id, package_id, version)
    return {"success": True, "created": created, "job": job,
            "message": "One user-scope job was accepted; installation is not yet verified."}


@tool
def simulate_user_scope_installation(job_id: str) -> dict:
    """Run the fixture installer in memory for one user's profile; it never runs an OS installer."""
    job = memory.get_job(job_id)
    if job is None:
        return {"success": False, "error": "Unknown deployment job."}
    return memory.simulate_job(job_id)


@tool
def verify_user_scope_installation(job_id: str) -> dict:
    """Verify the reported device, employee, user account, package, version, user scope, and checks."""
    return memory.verify_job(job_id)


@tool
def retry_failed_user_scope_installation(job_id: str) -> dict:
    """Schedule another attempt of the existing deployment job within its configured retry limit."""
    return memory.retry_failed_installation(job_id)


INSTALLATION_TOOLS = [
    get_installation_context,
    find_user_device,
    list_approved_software_versions,
    check_license_entitlement,
    wait_for_device,
    add_to_it_pending_software,
    queue_user_scope_install,
    simulate_user_scope_installation,
    verify_user_scope_installation,
    retry_failed_user_scope_installation,
]
INSTALLATION_TOOL_MAP = {tool.name: tool for tool in INSTALLATION_TOOLS}
