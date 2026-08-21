"""Dimension 9: no `Any` at the trust boundary (CLAUDE.md).

A request body is attacker-controlled input. `Any` / `Dict[str, Any]` / bare
`dict` on a request field means it is accepted unvalidated and — when the field
backs a JSONB column — persisted verbatim and echoed back into a UI.

Not SQL injection; SQLAlchemy parameterises. The risk is unbounded writes,
silent persistence of malformed data, and a mistyped key becoming data
corruption instead of a 422.

**Scoped to REQUEST models only**, resolved from the OpenAPI schema rather than
from naming conventions: whether a model is attacker-reachable is decided by
having an endpoint accept it as a body, not by whether someone remembered to
call it `...In`. `Any` on a RESPONSE field is a typing weakness with no
injection surface and is deliberately not failed here.

ALLOWLIST is the escape hatch, and each entry states why. Adding to it is a
decision that should be visible in review — an unexplained entry is how a
guard decays into theatre.
"""
import pytest

# (model, field): why this is acceptable unvalidated.
ALLOWLIST: dict[tuple[str, str], str] = {}


def _request_models() -> dict[str, dict]:
    """Every schema reachable as (or inside) an endpoint request body.

    Walks $refs transitively — a typed wrapper around a `Dict[str, Any]` child
    is exactly the shape that hides from a top-level-only check.
    """
    import app.main as m

    spec = m.app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})

    roots: set[str] = set()
    for ops in spec.get("paths", {}).values():
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            body = op.get("requestBody")
            if not body:
                continue
            for content in body.get("content", {}).values():
                sch = content.get("schema", {})
                ref = sch.get("$ref") or sch.get("items", {}).get("$ref")
                if ref:
                    roots.add(ref.split("/")[-1])

    seen: dict[str, dict] = {}

    def visit(name: str) -> None:
        if name in seen or name not in schemas:
            return
        node = schemas[name]
        seen[name] = node
        for ref in _refs_in(node):
            visit(ref)

    for r in roots:
        visit(r)
    return seen


def _refs_in(node) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out.append(v.split("/")[-1])
            else:
                out.extend(_refs_in(v))
    elif isinstance(node, list):
        for item in node:
            out.extend(_refs_in(item))
    return out


def _is_untyped(prop: dict) -> bool:
    """Does this property accept arbitrary JSON?

    Pydantic renders `Any` as an EMPTY schema ({}), and `Dict[str, Any]` as
    `{"type": "object"}` with no properties and no additionalProperties
    constraint. Both are the trust-boundary hole; a model reference or a typed
    scalar is not.
    """
    if not isinstance(prop, dict):
        return False

    # Optional[...] / unions: untyped only if every non-null branch is untyped.
    for key in ("anyOf", "oneOf", "allOf"):
        if key in prop:
            branches = [b for b in prop[key] if b.get("type") != "null"]
            return bool(branches) and all(_is_untyped(b) for b in branches)

    if "$ref" in prop or "enum" in prop:
        return False

    t = prop.get("type")
    if t is None:
        # {} — a bare `Any`. A description-only annotation still accepts anything.
        return not any(k in prop for k in ("$ref", "enum", "const"))
    if t == "object":
        ap = prop.get("additionalProperties")
        # object with no declared properties and unconstrained values
        return not prop.get("properties") and ap in (True, None, {})
    if t == "array":
        return _is_untyped(prop.get("items", {}))
    return False


def test_no_untyped_fields_on_request_models():
    findings = []
    for name, schema in sorted(_request_models().items()):
        for field, prop in (schema.get("properties") or {}).items():
            if (name, field) in ALLOWLIST:
                continue
            if _is_untyped(prop):
                findings.append(f"{name}.{field}")

    assert not findings, (
        "Dimension 9 — request fields that accept arbitrary JSON:\n\n  "
        + "\n  ".join(findings)
        + "\n\nA request body is attacker-controlled. Give the field a concrete "
          "type (a nested BaseModel, not Dict[str, Any]), set "
          'model_config = ConfigDict(extra="forbid") on nested models, and bound '
          "strings/lists with max_length and numbers with ge=/le=.\n"
          "If the field backs a JSONB column, the write site must call "
          ".model_dump() — every write site.\n"
          "If it is genuinely unavoidable, add it to ALLOWLIST in this file "
          "WITH the reason."
    )


def test_allowlist_has_no_stale_entries():
    """An allowlist that outlives its fields stops describing reality."""
    live = {
        (n, f)
        for n, s in _request_models().items()
        for f in (s.get("properties") or {})
    }
    stale = sorted(ALLOWLIST.keys() - live)
    assert not stale, (
        "ALLOWLIST names request fields that no longer exist:\n  "
        + "\n  ".join(f"{n}.{f}" for n, f in stale)
    )


# ── the detector must actually detect ────────────────────────────────────────
#
# This test gates a merge on an EMPTY result, and an empty result from a broken
# checker is indistinguishable from a clean codebase. Each shape it claims to
# catch is asserted directly.

@pytest.mark.parametrize("prop,expected,label", [
    ({}, True, "bare Any"),
    ({"type": "object"}, True, "Dict[str, Any] / bare dict"),
    ({"type": "object", "additionalProperties": True}, True, "explicitly open object"),
    ({"type": "array", "items": {}}, True, "List[Any]"),
    ({"anyOf": [{"type": "object"}, {"type": "null"}]}, True, "Optional[Dict[str, Any]]"),
    ({"$ref": "#/components/schemas/AppealEvidence"}, False, "typed model"),
    ({"type": "string", "maxLength": 50}, False, "bounded string"),
    ({"type": "integer", "minimum": 0}, False, "bounded int"),
    ({"anyOf": [{"$ref": "#/x/Y"}, {"type": "null"}]}, False, "Optional[Model]"),
    ({"type": "array", "items": {"$ref": "#/x/Y"}}, False, "List[Model]"),
    ({"type": "object", "properties": {"a": {"type": "string"}}}, False, "declared object"),
])
def test_detector_classifies(prop, expected, label):
    assert _is_untyped(prop) is expected, label


def test_the_scan_actually_reaches_request_models():
    """Guards against the whole check silently passing on an empty set."""
    models = _request_models()
    assert len(models) > 50, (
        f"only {len(models)} request models discovered — the OpenAPI walk is "
        f"probably broken, and a passing Dimension 9 test would mean nothing"
    )


def test_nested_models_are_reached_not_just_top_level():
    """A typed wrapper around an untyped child is the shape that hides from a
    top-level-only scan, so the transitive walk is pinned explicitly."""
    models = _request_models()
    assert "AppealItemIn" in models, "nested request models are not being walked"
