"""Mock employee directory and role holders. Replace the accessors with real system calls later."""
import logging

log = logging.getLogger("approval.employees")

EMPLOYEES = {
    "E1001": {"name": "Sara Khan", "email": "sara.khan@example.com", "title": "Marketing Analyst", "department": "Marketing", "manager_id": "E2001"},
    "E1002": {"name": "Haseeb Ahmad", "email": "haseeb.ahmad@example.com", "title": "Marketing Executive", "department": "Marketing", "manager_id": "E2001"},
    # Self-managed on purpose, so the self-approval block stays testable.
    "E2001": {"name": "Ali Raza", "email": "ali.raza@example.com", "title": "Manager Marketing Department", "department": "Marketing", "manager_id": "E2001"},
    "E3001": {"name": "Omar Sheikh", "email": "omar.sheikh@example.com", "title": "IT Lead", "department": "IT", "manager_id": None},
    "E4001": {"name": "Nadia Malik", "email": "nadia.malik@example.com", "title": "Finance Director", "department": "Finance", "manager_id": None},
    # Authorized substitute approver for self-managed requesters (see SUBSTITUTE_APPROVERS).
    "E5001": {"name": "Zain Abbas", "email": "zain.abbas@example.com", "title": "Marketing Director", "department": "Marketing", "manager_id": None},
    # Extra normal requesters under the same manager (E2001)
    "E1003": {"name": "Bilal Ahmed", "email": "bilal.ahmed@example.com", "title": "Content Specialist", "department": "Marketing", "manager_id": "E2001"},

    # Manager is ALSO the Finance Director: same person could appear twice in a 3-person chain
    "E1004": {"name": "Ayesha Noor", "email": "ayesha.noor@example.com", "title": "Finance Analyst", "department": "Finance", "manager_id": "E4001"},

    # Manager is ALSO the IT Lead: same person could appear twice in a chain
    "E1005": {"name": "Hamza Tariq", "email": "hamza.tariq@example.com", "title": "IT Support Engineer", "department": "IT", "manager_id": "E3001"},

    # Different department with its own manager
    "E1006": {"name": "Maria Iqbal", "email": "maria.iqbal@example.com", "title": "Sales Executive", "department": "Sales", "manager_id": "E2002"},
    # Self-managed with NO substitute configured: must give an unresolved route, not a guess
    "E2002": {"name": "Kamran Yousaf", "email": "kamran.yousaf@example.com", "title": "Manager Sales Department", "department": "Sales", "manager_id": "E2002"},

    # No manager at all: record an unresolved question, never guess
    "E1007": {"name": "Daniyal Shah", "email": "daniyal.shah@example.com", "title": "Operations Associate", "department": "Operations", "manager_id": None},

    # Dangling manager reference (manager ID does not exist)
    "E1008": {"name": "Rina Fatima", "email": "rina.fatima@example.com", "title": "Operations Analyst", "department": "Operations", "manager_id": "E9999"},

    # Same display name as E2001 but a different person: name lookup must be ambiguous
    "E2003": {"name": "Ali Raza", "email": "ali.raza.eng@example.com", "title": "Manager Engineering", "department": "Engineering", "manager_id": "E2003"},

    # Second substitute, for testing "substitute unavailable / substitute is requester"
    "E5002": {"name": "Hira Siddiqui", "email": "hira.siddiqui@example.com", "title": "Operations Director", "department": "Operations", "manager_id": None},
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
        substitute_id = get_substitute_id(requester_id)
        log.warning("Self-managed requester: %s (%s) is the manager of themselves; Manager stage goes to "
                    "substitute %s", requester_id, requester["name"], substitute_id or "NONE CONFIGURED")
        manager_id = substitute_id
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
