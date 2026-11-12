"""Mock employee directory and role holders. Replace the accessors with real system calls later."""

EMPLOYEES = {
    "E1001": {"name": "Sara Khan", "email": "sara.khan@example.com", "title": "Marketing Analyst", "department": "Marketing", "manager_id": "E2001"},
    "E1002": {"name": "Haseeb Ahmad", "email": "haseeb.ahmad@example.com", "title": "Marketing Executive", "department": "Marketing", "manager_id": "E2001"},
    # Self-managed on purpose, so the self-approval block stays testable.
    "E2001": {"name": "Ali Raza", "email": "ali.raza@example.com", "title": "Manager Marketing Department", "department": "Marketing", "manager_id": "E2001"},
    "E3001": {"name": "Omar Sheikh", "email": "omar.sheikh@example.com", "title": "IT Lead", "department": "IT", "manager_id": None},
    "E4001": {"name": "Nadia Malik", "email": "nadia.malik@example.com", "title": "Finance Director", "department": "Finance", "manager_id": None},
    # Authorized substitute approver for self-managed requesters (see SUBSTITUTE_APPROVERS).
    "E5001": {"name": "Zain Abbas", "email": "zain.abbas@example.com", "title": "Marketing Director", "department": "Marketing", "manager_id": None},
}

ROLE_HOLDERS = {"it lead": "E3001", "finance director": "E4001"}

# When a requester is their own manager, the Manager stage is held for this configured substitute instead.
SUBSTITUTE_APPROVERS = {"E2001": "E5001"}


def get_substitute_id(requester_id):
    """Return the authorized substitute approver for a self-managed requester, or None."""
    return SUBSTITUTE_APPROVERS.get(requester_id)


def manager_stage_approver_id(requester_id):
    """Return the employee ID who must decide the Manager stage: the manager on record, or the configured
    substitute when the requester is their own manager. None when no valid approver exists."""
    requester = EMPLOYEES.get(requester_id)
    manager_id = requester["manager_id"] if requester else None
    if not manager_id:
        return None
    if manager_id == requester_id:
        manager_id = get_substitute_id(requester_id)
        if manager_id == requester_id:
            return None
    return manager_id


def get_employee(employee_id):
    """Return the employee record for an ID, or None."""
    return EMPLOYEES.get(employee_id)


def find_employee_id_by_name(normalized_name, normalize):
    """Return the employee ID whose normalized name matches, or None."""
    for employee_id, rec in EMPLOYEES.items():
        if normalize(rec["name"]) == normalized_name:
            return employee_id
    return None


def employee_name_exists(normalized_name, normalize):
    """True if any employee's normalized name matches."""
    return any(normalize(rec["name"]) == normalized_name for rec in EMPLOYEES.values())


def get_role_holder_id(normalized_role):
    """Return the employee ID holding a role (lower-case, whitespace-normalized), or None."""
    return ROLE_HOLDERS.get(normalized_role)
