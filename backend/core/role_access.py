"""Shared role identities for the public, passwordless workspace picker."""
from django.db import transaction
from .models import BusinessUnit, Role, User

ROLE_CHOICES = (
    ("super_admin", "Super Admin", None),
    ("resort_inventory_manager", "Resort Inventory Manager", "RESORT"),
    ("healthcare_inventory_manager", "Pharmacy Inventory Manager", "HEALTH"),
    ("hr_manager", "HR Manager", "HR"),
    ("accountant", "Finance Manager", "FINANCE"),
    ("employee", "Staff", "RESORT"),
)


@transaction.atomic
def shared_role_user(code):
    # Provision only dedicated shared identities; never adopt a person's account.
    units = {}
    for unit_code, name in (("RESORT", "Resort Operations"), ("HEALTH", "Healthcare Operations"),
                            ("HR", "Human Resources"), ("FINANCE", "Finance and Accounting")):
        units[unit_code], _ = BusinessUnit.objects.get_or_create(code=unit_code, defaults={"name": name})
    _, name, unit_code = next(choice for choice in ROLE_CHOICES if choice[0] == code)
    unit = units.get(unit_code)
    role, _ = Role.objects.get_or_create(code=code, defaults={"name": name, "business_unit": unit})
    user, created = User.objects.get_or_create(
        email=f"workspace-{code}@roles.invalid",
        defaults={"username": f"workspace-{code}", "first_name": name,
                  "role": role, "business_unit": unit, "is_active": True, "is_approved": True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user
