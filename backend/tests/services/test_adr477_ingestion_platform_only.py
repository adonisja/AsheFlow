"""Ingestion mode is a platform decision (ADR-477).

`ingestion_mode` decides whether a tenant's manifests arrive by file upload or
by API integration, which depends on whether that integration has been built and
credentialed for the station. A company admin switching to "API Integration"
does not make an integration exist -- it makes manifests stop arriving.

It was editable at PATCH /companies/my-config, gated to company admin. HIDING
THE DROPDOWN WOULD HAVE LEFT THE API WRITABLE, which is why this is a backend
fix with a UI consequence rather than the reverse.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPANY_FORM = ROOT / "frontend/src/pages/CompanySettings.tsx"
SUPER_ADMIN = ROOT / "frontend/src/pages/superadmin/CompanyDetail.tsx"


def test_ingestion_mode_is_super_admin_only():
    from app.routers.companies import _SUPER_ADMIN_ONLY_FIELDS

    assert "ingestion_mode" in _SUPER_ADMIN_ONLY_FIELDS


def test_it_uses_the_existing_mechanism_not_a_new_one():
    """The set is the established expression of 'not the tenant's to set'. A
    second guard beside it is a second place to forget."""
    from app.routers.companies import _SUPER_ADMIN_ONLY_FIELDS

    assert "invite_expiry_days" in _SUPER_ADMIN_ONLY_FIELDS, (
        "the precedent field is gone; this test's premise has changed"
    )


def test_the_company_form_does_not_offer_the_field():
    src = COMPANY_FORM.read_text()
    assert "Manifest Ingestion" not in src.replace(
        "/* ADR-477. Manifest Ingestion is gone from here.", ""
    ) or "const INGESTION" not in src


def test_the_company_form_does_not_SEND_the_field():
    """THE bug this surfaced. `ingestion_mode` was in STRING_FIELDS, which
    controls what the form sends, and the read path still populated it -- so
    every save would have PATCHed it and taken a 403, blocking the whole form
    over a field the operator cannot see.

    Removing the input was not the fix. Removing it from what the form SENDS
    was."""
    src = COMPANY_FORM.read_text()
    m = re.search(r"const CONFIG_KEYS: string\[\] = \[(.*?)\n\];", src, re.S)
    assert m, "CONFIG_KEYS not found"
    keys = re.findall(r"'([a-z0-9_]+)'", m.group(1))
    assert "ingestion_mode" not in keys, "the form still sends a 403 field"


def test_config_keys_carries_no_field_the_model_dropped():
    """Ten scorecard_*_target keys outlived ADR-473's columns here. Harmless on
    read, and sitting in the exact list that just proved it is not harmless on
    write."""
    from app.models.company import CompanyConfig

    src = COMPANY_FORM.read_text()
    m = re.search(r"const CONFIG_KEYS: string\[\] = \[(.*?)\n\];", src, re.S)
    keys = set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))
    columns = {c.name for c in CompanyConfig.__table__.columns}
    stale = sorted(keys - columns)
    assert not stale, f"CONFIG_KEYS lists columns that no longer exist: {stale}"


def test_the_super_admin_page_can_set_it():
    """Removing it from the company form alone would leave NOBODY able to set
    it -- ADR-381 inverted: not an endpoint with no caller, but a field with no
    editor."""
    src = SUPER_ADMIN.read_text()
    assert "ingestion_mode" in src
    assert "Manifest Ingestion" in src


def test_neither_config_form_uses_a_raw_select():
    """ui/SelectMenu exists because a native select opens with the OS palette --
    a white panel on our dark theme. It was already used for the timezone picker
    on the same page, but not for the generic renderer every other select goes
    through."""
    for path in (COMPANY_FORM, SUPER_ADMIN):
        markup = re.sub(r"\{?/\*.*?\*/\}?", "", path.read_text(), flags=re.S)
        assert "<select" not in markup, f"{path.name} renders a raw select"


def test_the_generic_renderer_uses_the_house_dropdown():
    src = COMPANY_FORM.read_text()
    block = src.split("field.type === 'select'", 1)[1][:400]
    assert "SelectMenu" in block
