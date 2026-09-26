"""The roster and the escalation list are different artifacts (ADR-458).

The roster answers "who works here". Reaching an owner or a manager is a
different job with its own audited surface. These tests pin the split, in both
directions: office contact details must not ride the roster, and the escalation
list must still exist and be reachable by the roles that need it at 4am.
"""
import ast
import inspect
import uuid

from app.routers import employees as E
from app.schemas.employee import (
    EmployeeEscalationResponse,
    EmployeeOfficeResponse,
    EmployeeResponse,
)


class _Row:
    """Minimal stand-in: model_validate(from_attributes) reads attributes."""
    def __init__(self, **kw):
        self.id = kw.pop("id", uuid.uuid4())
        self.name = kw.pop("name", "Nicoy Hunt")
        self.role = kw.pop("role", "admin")
        self.is_active = kw.pop("is_active", True)
        self.account_status = kw.pop("account_status", "active")
        self.email = kw.pop("email", "owner@example.com")
        self.phone_number = kw.pop("phone_number", "+15551234821")
        self.discord_id = kw.pop("discord_id", "123456789012345678")
        self.username = kw.pop("username", "nicoy.hunt")
        self.invited_at = None
        self.email_bounced_at = None
        self.email_bounce_type = None
        self.injury_status = None
        self.injury_status_since = None
        for k, v in kw.items():
            setattr(self, k, v)


# ── D1: the roster shape ────────────────────────────────────────────────────

def test_office_response_drops_every_contact_channel():
    """Not just the phone: email and discord are contact channels too."""
    out = EmployeeOfficeResponse.model_validate(_Row(), from_attributes=True)
    dumped = out.model_dump()
    for leaked in ("phone_number", "email", "discord_id", "username"):
        assert leaked not in dumped, f"{leaked} survives the office redaction"
    # Still useful as a roster row.
    assert dumped["name"] == "Nicoy Hunt"
    assert dumped["role"] == "admin"
    assert dumped["is_active"] is True


def test_the_full_response_still_carries_contacts():
    """Guards the redaction being applied to everyone by accident."""
    dumped = EmployeeResponse.model_validate(_Row(role="driver"), from_attributes=True).model_dump()
    assert dumped["phone_number"] == "+15551234821"
    assert dumped["email"] == "owner@example.com"


def test_roster_redacts_protected_rows_for_non_admin_callers():
    src = inspect.getsource(E.get_all_employees)
    assert "EmployeeOfficeResponse" in src, (
        "the roster no longer redacts office rows (ADR-458 D1)"
    )
    assert "PROTECTED_ROLES" in src


def test_management_is_no_longer_blind_to_office_rows():
    """The filter that hid admin rows from managers entirely is gone.

    That was the "too closed" half: the role most likely to need to escalate
    could not see anyone to escalate to.
    """
    src = inspect.getsource(E.get_all_employees)
    assert "role.notin_(PROTECTED_ROLES)" not in src.replace(" ", ""), (
        "managers are filtered away from office rows again"
    )


# ── D2: the escalation list ─────────────────────────────────────────────────

def test_escalation_entry_is_narrow():
    """Enough to call someone. Not a second roster."""
    dumped = EmployeeEscalationResponse.model_validate(_Row(), from_attributes=True).model_dump()
    assert set(dumped) == {"id", "name", "role", "phone_number"}
    assert dumped["phone_number"] == "+15551234821"


def test_escalation_covers_admin_and_management():
    assert set(E.ESCALATION_ROLES) == {"admin", "management"}


def test_field_supervisor_is_not_on_the_list():
    """In OVERSIGHT_ROLES, but it oversees the road rather than the company."""
    assert "field_supervisor" not in E.ESCALATION_ROLES


def test_dispatch_can_open_the_escalation_list():
    """The 4am case: excluding dispatch makes the list useless when needed."""
    src = inspect.getsource(E.get_escalation_contacts)
    for role in ("dispatch", "management", "admin"):
        assert f'"{role}"' in src, f"{role} cannot open the escalation list"


def test_field_roles_cannot_open_the_escalation_list():
    src = inspect.getsource(E.get_escalation_contacts)
    gate = src.split("RoleChecker(")[1].split(")")[0]
    for role in ("driver", "walker", "trainer", "trainee"):
        assert f'"{role}"' not in gate, f"{role} is on the escalation gate"


# ── D3: the audit row ───────────────────────────────────────────────────────

def test_opening_the_list_is_audited():
    src = inspect.getsource(E.get_escalation_contacts)
    assert "write_audit(" in src, "an unaudited gate cannot answer 'who looked'"
    assert "employee.escalation_viewed" in src


def test_the_audit_row_does_not_log_the_numbers():
    """Logging them copies the PII being protected into a second store (D7)."""
    src = inspect.getsource(E.get_escalation_contacts)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "write_audit":
            detail = next((k.value for k in node.keywords if k.arg == "detail"), None)
            assert detail is not None, "write_audit call has no detail"
            dumped = ast.dump(detail)
            assert "phone" not in dumped.lower(), "the audit row carries phone numbers"
            return
    raise AssertionError("no write_audit call found")


def test_the_list_is_rate_limited():
    """An audited endpoint callable in a loop produces noise, not accountability."""
    src = inspect.getsource(E)
    idx = src.index("def get_escalation_contacts")
    assert "@limiter.limit" in src[max(0, idx - 400):idx]


# ── The surface exists (ADR-381) ────────────────────────────────────────────

def test_the_endpoint_has_a_client_caller():
    """An endpoint no client calls is a feature that does not exist.

    ADR-381: three features shipped "done" with no caller. The trigger was
    written and silently dropped once during THIS change -- openEscalation was
    defined and never called, so the panel was unreachable and the build was
    clean.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    src = (root / "frontend/src/pages/Assets.tsx").read_text()
    assert "'/employees/escalation'" in src, "no client fetches the escalation list"
    assert "onClick={openEscalation}" in src, (
        "the escalation list has no trigger: it is unreachable from the UI"
    )
