"""PII scrub for operational-note free text (ADR-220).

Operational notes are walker-submitted free text ("leave with Maria in 4B",
"call John 555-1234"). Before a note enters the permanently-retained
BuildingProfileLibrary (AsheFlow's first-party asset), scrub personal data:
phone numbers, emails, and "leave with / ask for <Name>" person references.

Conservative by design — over-redact rather than let PII into a retained asset.
Returns (scrubbed_text, flags) so a super admin sees what was removed and
confirms (ADR-220 forced-review gate). Never auto-writes without that review.
"""
import re

_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# "leave with / ask for / give to / see <Name>" — capture a following capitalized
# token (or two) as a likely person name. Deliberately broad.
# Trigger verbs are case-insensitive (sentence-start "Leave with"); the name
# capture still requires an initial capital so it targets proper names, not the
# next ordinary word. (?i:...) scopes the flag to the trigger group only.
_PERSON = re.compile(
    r"\b(?i:leave with|leave it with|ask for|give to|give it to|see|call|contact|hand to)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)

_REDACTION = "[redacted]"


def scrub_note(note: str | None) -> tuple[str | None, list[str]]:
    """Return (scrubbed_note, flags). flags lists what was redacted (for review).
    None/empty passes through with no flags."""
    if not note:
        return note, []

    flags: list[str] = []
    out = note

    for m in _PHONE.finditer(note):
        flags.append(f"phone: {m.group(0)}")
    out = _PHONE.sub(_REDACTION, out)

    for m in _EMAIL.finditer(note):
        flags.append(f"email: {m.group(0)}")
    out = _EMAIL.sub(_REDACTION, out)

    # For person refs, keep the trigger verb, redact the name. The trigger is a
    # non-capturing (?i:) group now, so the whole match minus the name = the verb.
    def _person_sub(m: re.Match) -> str:
        name = m.group(1)
        flags.append(f"person: {name}")
        verb = m.group(0)[: m.start(1) - m.start(0)].rstrip()
        return f"{verb} {_REDACTION}"

    out = _PERSON.sub(_person_sub, out)

    return out, flags
