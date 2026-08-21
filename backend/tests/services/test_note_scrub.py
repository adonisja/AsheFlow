"""PII scrub for operational-note free text (ADR-220). Public service."""
from app.services.note_scrub import scrub_note


def test_none_and_empty_pass_through():
    assert scrub_note(None) == (None, [])
    assert scrub_note("") == ("", [])


def test_clean_note_unchanged_no_flags():
    txt = "Elevator to the 4th floor; buzzer on the left."
    out, flags = scrub_note(txt)
    assert out == txt and flags == []


def test_phone_redacted():
    out, flags = scrub_note("Call 212-555-1234 for access")
    assert "[redacted]" in out and "212-555-1234" not in out
    assert any("phone" in f for f in flags)


def test_email_redacted():
    out, flags = scrub_note("Email super@building.com to be let in")
    assert "super@building.com" not in out
    assert any("email" in f for f in flags)


def test_person_reference_redacted_verb_kept():
    out, flags = scrub_note("Leave with Maria in the mailroom")
    assert out.startswith("Leave with [redacted]")   # trigger kept, name gone
    assert "Maria" not in out
    assert any("person: Maria" == f for f in flags)


def test_multiple_pii_in_one_note():
    out, flags = scrub_note("Ask for John, call 917.555.0000, or bob@x.co")
    assert "John" not in out and "917.555.0000" not in out and "bob@x.co" not in out
    kinds = {f.split(":")[0] for f in flags}
    assert kinds == {"person", "phone", "email"}


def test_conservative_two_word_name():
    out, flags = scrub_note("give to Mary Jane at the desk")
    assert "Mary Jane" not in out
    assert any("person: Mary Jane" == f for f in flags)
