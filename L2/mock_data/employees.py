"""Mock employee directory and role holders. Replace the accessors with real system calls later."""

EMPLOYEES = {
    "E1001": {"name": "Sara Khan", "title": "Marketing Analyst", "department": "Marketing", "manager_id": "E2001"},
    "E1002": {"name": "Haseeb Ahmad", "title": "Marketing Executive", "department": "Marketing", "manager_id": "E2001"},
    # Self-managed on purpose, so the self-approval block stays testable.
    "E2001": {"name": "Ali Raza", "title": "Manager Marketing Department", "department": "Marketing", "manager_id": "E2001"},
    "E3001": {"name": "Omar Sheikh", "title": "IT Lead", "department": "IT", "manager_id": None},
    "E4001": {"name": "Nadia Malik", "title": "Finance Director", "department": "Finance", "manager_id": None},
}

ROLE_HOLDERS = {"it lead": "E3001", "finance director": "E4001"}


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
