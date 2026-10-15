"""ADR-507 — every notification can be seen before anyone receives it.

Two halves: the catalogue (copy for every type, recovered or sourced) and Send
(a REAL notification, through the real pipeline, to a non-live tenant only).
"""
from __future__ import annotations

import inspect
import pathlib
import re
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.company import Company
from app.models.notification import Notification
from app.routers import notification_gallery as G
from app.services import notification_gallery as S
from app.services.notification_spec import SPEC
from tests.conftest import SEED_COMPANY_ID, make_employee

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

#: Pinned as a LITERAL. The first version asserted `startswith(S.SAMPLE_PREFIX)`,
#: which compares the code with itself: the probe that emptied the constant
#: passed, because every string starts with "".
MARK = "Sample · "


class TestEveryTypeHasCopy:
    """Walks SPEC (the world), not SAMPLES (a list that can go stale)."""

    def test_every_type_has_a_template_or_a_sample(self):
        templates = S.extract_templates()
        missing = [t for t in SPEC if t not in templates and t not in S.SAMPLES]
        assert not missing, (
            f"{missing}: no message template found at a raise site and no sample. "
            f"The gallery cannot show these. Add a sample to SAMPLES with the "
            f"text copied from the code that builds the message."
        )

    def test_no_sample_shadows_real_copy(self):
        """A sample is a stand-in. Once the real template is readable, the
        sample would show stale text instead of what users receive."""
        templates = S.extract_templates()
        stale = [t for t in S.SAMPLES if t in templates]
        assert not stale, f"{stale}: real templates exist now; delete these samples"

    def test_every_sample_names_a_declared_type(self):
        assert not [t for t in S.SAMPLES if t not in SPEC]

    def test_unraised_really_means_raised_by_nothing(self):
        """Re-derived every run: if anything starts raising one of these, the
        'unraised' label is a lie the gallery would show the owner."""
        allowed = {"services/notification_spec.py", "services/notification_gallery.py"}
        for t, (kind, _) in S.SAMPLES.items():
            if kind != "unraised":
                continue
            hits = [p.relative_to(APP).as_posix() for p in APP.rglob("*.py")
                    if t in p.read_text(errors="ignore")
                    and p.relative_to(APP).as_posix() not in allowed]
            assert not hits, f"{t} is labelled unraised but appears in {hits}"


class TestTheSampleMessage:
    @pytest.mark.parametrize("t", sorted(SPEC))
    def test_it_is_marked_and_fully_filled(self, t):
        msg = S.sample_message(t)
        assert msg.startswith(MARK), "a sample must be recognisable everywhere it lands"
        assert "‹" not in msg and "›" not in msg, f"unfilled placeholder in {msg!r}"

    def test_templates_carry_a_real_location(self):
        tpl = S.extract_templates()["dispatch_finalized"][0]
        path, line = tpl.location.rsplit(":", 1)
        src = (APP.parent / path).read_text().splitlines()
        assert "dispatch_finalized" in "\n".join(src[int(line) - 1:int(line) + 6])

    def test_the_catalog_covers_spec_with_the_wire_fields(self):
        cat = {x["type"]: x for x in S.catalog()}
        assert set(cat) == set(SPEC)
        for k in ("label", "severity", "tone", "icon", "channels", "actions",
                  "copy_source", "preview_message"):
            assert k in cat["timecard_mismatch"], k


class TestAccess:
    def _dep(self, fn, name):
        return inspect.signature(fn).parameters[name].default.dependency.__name__

    def test_reading_is_platform_staff(self):
        assert self._dep(G.get_gallery, "_staff") == "get_platform_staff"

    def test_writing_is_super_admin_only(self):
        """ADR-343 D1: platform support reads; only a super admin writes into a tenant."""
        assert self._dep(G.send_sample, "_super") == "get_super_admin"
        assert self._dep(G.get_targets, "_super") == "get_super_admin"


class TestSend:
    SUPER = {"sub": "super-1", "email": "owner@example.com", "cognito:groups": ["super_admin"]}

    def _company(self, db, data_class):
        c = db.get(Company, SEED_COMPANY_ID)
        c.data_class = data_class
        db.commit()
        return c

    def _send(self, db, emp, t="dispatch_finalized"):
        with patch("app.services.notify._enqueue") as enq, \
             patch.object(G, "write_audit") as audit:
            out = G.send_sample(t, G.SendSampleIn(employee_id=emp.id), db=db, _super=self.SUPER)
        return out, enq, audit

    def test_a_live_company_is_refused(self, db):
        self._company(db, "live")
        emp = make_employee(db)
        with pytest.raises(HTTPException) as e:
            self._send(db, emp)
        assert e.value.status_code == 403
        assert db.query(Notification).count() == 0, "a refused send must write nothing"

    def test_an_unknown_type_is_a_404(self, db):
        self._company(db, "seed")
        with pytest.raises(HTTPException) as e:
            self._send(db, make_employee(db), t="not_a_type")
        assert e.value.status_code == 404

    def test_a_seed_company_gets_a_real_marked_expiring_notification(self, db):
        self._company(db, "seed")
        emp = make_employee(db)
        out, enq, audit = self._send(db, emp)
        n = db.query(Notification).one()
        assert n.type == "dispatch_finalized" and n.employee_id == emp.id
        assert n.message.startswith(MARK)
        assert n.expires_at is not None
        assert audit.call_count == 1
        assert audit.call_args.kwargs["action_type"] == "notification.sample_sent"
        assert audit.call_args.kwargs["actor_id"] is None, "a super admin has no Employee row"

    def test_it_enters_the_real_delivery_pipeline(self, db):
        """Not a bare insert: write_notification records the delivery intent and
        the commit hands it to _enqueue, which is where push and Discord start."""
        self._company(db, "seed")
        emp = make_employee(db)
        _, enq, _ = self._send(db, emp, t="dispatch_finalized")
        assert SPEC["dispatch_finalized"].channels and enq.call_count >= 1, (
            "dispatch_finalized declares PUSH/DISCORD; nothing reached _enqueue"
        )


def test_a_truck_name_is_a_truck_not_a_person():
    """Specific before generic in `_fill`. Found in the browser: AP Arrival
    previewed as 'Alex Rivera — Alex Rivera arrived at…'."""
    assert S._fill("truck_name") == "Truck 12"
    assert S._fill("caller.name") == "Alex Rivera"
    # No leading ✅ any more: the registry icon is the only icon (ADR-508).
    assert S.sample_message("anchor_point_arrived").startswith(MARK + "Truck 12 — Alex Rivera")


def test_wrapper_raises_are_read_from_source_not_sampled():
    """`_notify(db, ids, "anchor_point_submitted", message, ...)` passes the type
    positionally. The first extractor missed it, the type fell to a hand-written
    sample, and that sample was invented. Both branches of the message (set a
    preliminary AP / relocating) must appear."""
    tpl = S.extract_templates()
    texts = [t.text for t in tpl["anchor_point_submitted"]]
    assert any("set preliminary AP" in x for x in texts)
    assert any("relocating to AP" in x for x in texts)
    for t in ("anchor_point_arrived", "exemplary_trainer", "underperforming_trainer"):
        assert t in tpl and t not in S.SAMPLES
