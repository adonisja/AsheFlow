"""ADR-281 — Phase 0, the ORE day.

Three things these guard, in order of how badly they fail:

  * a forged Content-Type getting an arbitrary file into the bucket
  * the attestation dying with the file, so a trainee's March completion
    evaporates on the third day
  * left_early leaking into anything that reads like a performance signal
"""
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.main import app
from app.models.training import TrainingRecord
from app.routers import training as tr
from app.services import ore_certificates as oc


def _code_only(obj) -> str:
    """Source with comments stripped.

    Well-documented code names the thing it avoids. A scanner asserting a name
    is ABSENT will otherwise read its own explanation as the offence — this bit
    ADR-280's seed guard and ADR-277's bulk path before it.
    """
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    # Docstrings too. A function that explains WHY it avoids something names
    # that thing in prose, and an absence assertion reads the explanation as
    # the offence — the same trap, one layer up from `#` comments.
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


class TestRoutes:
    def test_endpoints_registered(self):
        paths = app.openapi()["paths"]
        assert "/api/v1/training/record/{record_id}/ore-certificate" in paths
        assert "/api/v1/training/record/{record_id}/left-early" in paths

    def test_viewing_is_narrower_than_uploading(self):
        """Many people submit evidence; few should read someone else's
        training document."""
        upload = set(tr._allow_ore_upload.allowed_roles)
        view = set(tr._allow_ore_view.allowed_roles)
        assert "trainee" in upload and "trainer" in upload
        assert view == {"management", "admin"}
        assert "trainee" not in view and "trainer" not in view


class TestContentSniffing:
    def test_real_types_are_recognised(self):
        assert oc.sniff_content_type(b"%PDF-1.7") == "application/pdf"
        assert oc.sniff_content_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
        assert oc.sniff_content_type(b"\x89PNG\r\n\x1a\n") == "image/png"

    def test_a_forged_header_cannot_smuggle_a_file_in(self):
        """THE security case. A client sets Content-Type: image/png on an HTML
        page or a script; only the bytes tell the truth."""
        for payload in (b"<!DOCTYPE html>", b"#!/bin/sh\n", b"PK\x03\x04", b"MZ\x90\x00"):
            assert oc.sniff_content_type(payload) is None

    def test_the_endpoint_sniffs_rather_than_trusting_the_header(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "sniff_content_type" in src
        assert "file.content_type" not in src, (
            "the client's Content-Type header must not decide what is stored"
        )


class TestKeyLayout:
    def test_key_carries_no_pii(self):
        """Not the trainee's name, not their email — UUIDs and an extension."""
        key = oc.build_key(uuid4(), uuid4(), "pdf")
        assert key.startswith("ore-certificates/")
        assert key.count("/") == 2
        assert key.endswith(".pdf")

    def test_key_is_company_prefixed(self):
        """So a bucket policy CAN be scoped per tenant later without migrating
        existing objects."""
        cid = uuid4()
        assert oc.build_key(cid, uuid4(), "png").startswith(f"ore-certificates/{cid}/")


class TestAttestationOutlivesTheFile:
    def test_model_separates_attestation_from_pointer(self):
        cols = TrainingRecord.__table__.columns
        for name in (
            "ore_completed_at",
            "ore_certificate_uploaded_by",
            "ore_certificate_key",
            "ore_certificate_expires_at",
            "left_early",
            "left_early_at",
        ):
            assert cols.get(name) is not None, f"ADR-281: {name} missing"

    def test_purge_nulls_the_pointer_but_not_the_attestation(self):
        """The whole point of D2. If the sweep cleared ore_completed_at, a
        trainee who finished ORE in March would lose that fact on day three."""
        from app.tasks.cleanup import purge_expired_ore_certificates

        src = inspect.getsource(purge_expired_ore_certificates)
        assert "record.ore_certificate_key = None" in src
        assert "ore_completed_at = None" not in src, (
            "the attestation must survive the file"
        )

    def test_purge_only_nulls_after_a_confirmed_delete(self):
        """Nulling after a failed delete orphans the object: nothing points at
        it, so nothing retries, and it outlives its retention window."""
        from app.tasks.cleanup import purge_expired_ore_certificates

        src = _code_only(purge_expired_ore_certificates)
        assert "if ore_certificates.delete(" in src
        i = src.index("if ore_certificates.delete(")
        # The null must be INSIDE the success branch. With comments stripped it
        # is the next statement; with them it was 400+ chars away.
        assert "record.ore_certificate_key = None" in src[i : i + 200]

    def test_reupload_does_not_restart_the_completion_clock(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "if record.ore_completed_at is None:" in src

    def test_expired_is_a_distinct_answer_from_never_uploaded(self):
        """404 and 410 mean different things to a manager."""
        src = inspect.getsource(tr.get_ore_certificate)
        assert "HTTP_404_NOT_FOUND" in src
        assert "HTTP_410_GONE" in src
        i = src.index("HTTP_410_GONE")
        assert "ore_completed_at" in src[i : i + 400], (
            "the 410 should still tell the manager when ORE was completed"
        )


class TestLeftEarlyIsNotAMark:
    def test_it_is_scoped_to_phase_zero(self):
        src = inspect.getsource(tr._load_phase_zero_record)
        assert "_PHASE_ZERO" in src
        assert tr._PHASE_ZERO == 0

    def test_it_never_touches_the_scorecard(self):
        """ADR-281 D5: a permitted choice must not become a performance signal."""
        # _code_only already strips the docstring, which explains D5 by NAMING
        # the scorecard — no second pass needed.
        src = _code_only(tr.mark_left_early)
        for forbidden in ("Scorecard", "scorecard", "appeal", "penalty", "infraction"):
            assert forbidden not in src

    def test_no_programme_wide_counter_exists(self):
        """A tally is a judgement waiting for a threshold. Each phase-0 day
        carries its own pay implication; they do not accumulate."""
        cols = set(TrainingRecord.__table__.columns.keys())
        for banned in ("left_early_count", "early_departures", "left_early_total"):
            assert banned not in cols

    def test_it_is_a_one_way_stamp(self):
        """A second call must not fire a second notification."""
        src = inspect.getsource(tr.mark_left_early)
        assert "if record.left_early:" in src
        assert "HTTP_409_CONFLICT" in src

    def test_dispatch_learns_twice(self):
        """D6: the notification is the alert, the field is the truth. A
        notification that fired while nobody was looking must not be the only
        record that someone left."""
        src = inspect.getsource(tr.mark_left_early)
        assert "trainee_left_early" in src
        assert "record.left_early = True" in src


class TestErrorExposure:
    def test_aws_detail_never_reaches_the_client(self):
        """An S3 error names the bucket and the key; an HTTP body is the wrong
        place for either (ADR-115 dim 6)."""
        src = inspect.getsource(oc)
        assert "raise OreCertificateError" in src
        assert "str(exc)" not in src
        assert "detail=str(" not in inspect.getsource(tr.upload_ore_certificate)

    def test_unconfigured_storage_degrades_rather_than_crashing(self):
        """A deploy without the bucket should 503 with a clear message, not
        throw a boto3 error at a trainee mid-upload."""
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "is_enabled()" in src
        assert "HTTP_503_SERVICE_UNAVAILABLE" in src


class TestTenancy:
    def test_record_lookup_is_company_scoped(self):
        src = inspect.getsource(tr._load_phase_zero_record)
        assert "company_id == caller.company_id" in src

    def test_a_trainee_can_only_upload_their_own(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert 'caller.role == "trainee"' in src
        assert "record.trainee_id != caller.id" in src

    def test_dispatch_notification_is_company_scoped(self):
        src = inspect.getsource(tr.mark_left_early)
        assert "Employee.company_id == caller.company_id" in src


class TestInjector:
    def test_a_trainees_first_day_is_phase_zero(self):
        """The one line ADR-281 D1 changes. Everything downstream then works
        untouched — the existing phase_closed branch advances 0 -> 1 exactly as
        it advances 1 -> 2."""
        from app.services import training_injection

        # Assert on the BRANCH, not a byte window — the explanatory comment
        # between the condition and the assignment is exactly the kind of thing
        # that grows, and a fixed offset silently stops covering the statement.
        src = _code_only(training_injection)
        i = src.index("if not prev_records:")
        branch = src[i : src.index("else:", i)]
        # Conditional by design: phase 0 only when its curriculum is seeded.
        # Without that, the record would carry no mandatory tasks and auto-close
        # as complete — an ORE day that trained nothing. Adopting ADR-281 is
        # therefore seeding the curriculum, not deploying this code.
        assert "current_phase = 0 if curriculum_by_phase.get(0) else 1" in branch, (
            "a trainee's first record must be phase 0 when phase-0 curriculum exists"
        )

    def test_phase_four_does_not_mirror_phase_zero(self):
        """'Installed the app' is not a Phase 4 demonstration task. The
        allowlist at training_injection.py already excludes 0 — this pins it."""
        from app.services import training_injection

        src = inspect.getsource(training_injection)
        assert "day_number in (1, 2, 3)" in src


class TestPhaseZeroCurriculum:
    """The three topics a TRAINER covers on the ORE day.

    Deliberately short: ORE itself is Amazon's course on AtoZ, which AsheFlow
    neither hosts nor tracks. The certificate upload evidences the course; these
    rows cover the only things the trainer does alongside it.
    """

    def _rows(self):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "scripts"
               / "seed_training_curriculum.py").read_text()
        return re.findall(r'^\s{4}\(0, "([^"]+)"', src, re.M)

    def test_the_three_topics_are_seeded(self):
        titles = self._rows()
        assert len(titles) == 3, f"expected 3 phase-0 topics, found {titles}"
        assert any("login" in t.lower() for t in titles)
        assert any("website" in t.lower() for t in titles)
        assert any("procedure" in t.lower() for t in titles)

    def test_phase_zero_is_walker_only(self):
        """ORE is the WALKER onboarding course. A driver_trainee has no phase 0
        and starts at phase 1.

        Marking these ["walker", "driver"] would give every new driver an ORE
        day they can never complete — no certificate exists for them to upload,
        so the phase would never close and they would be stuck before phase 1.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "scripts"
               / "seed_training_curriculum.py").read_text()
        # Scope to the phase-0 TUPLES themselves. A byte window past them runs
        # into phase-1 rows, which legitimately DO include the driver track —
        # the first version of this test failed on exactly that.
        import re

        rows = re.findall(r"^\s{4}\(0,.*?\),\s*$", src, re.M | re.S)
        assert len(rows) == 3, f"expected 3 phase-0 rows, found {len(rows)}"
        for row in rows:
            code = "\n".join(
                ln for ln in row.splitlines() if not ln.lstrip().startswith("#")
            )
            assert '["walker"]' in code, f"not walker-scoped: {code[:60]}"
            assert '"driver"' not in code, (
                "phase 0 must not reach the driver track — a driver_trainee has "
                "no ORE certificate to upload, so the phase would never close"
            )

    def test_curriculum_must_exist_before_phase_zero_activates(self):
        """Without seeded rows the record would carry no mandatory tasks and
        auto-close as complete — an ORE day that trained nothing. Adopting
        ADR-281 is therefore seeding the curriculum, not deploying the code."""
        from app.services import training_injection

        src = _code_only(training_injection)
        assert "current_phase = 0 if curriculum_by_phase.get(0) else 1" in src


class TestStayingStartsPhaseOne:
    """ORE is not a full day's work (operator, 2026-08-21).

    A trainee who stays goes on to phase 1 THAT AFTERNOON rather than waiting
    for the next dispatch day — so two records share the date on purpose.
    """

    def test_endpoint_registered(self):
        assert "/api/v1/training/record/{record_id}/ore-stayed" in app.openapi()["paths"]

    def test_it_does_not_route_through_the_injector(self):
        """training_injection DELETES any existing record for the date and
        rebuilds it. Here that would destroy the phase-0 record and the ORE
        attestation on it."""
        src = _code_only(tr.stay_after_ore)
        assert "inject" not in src.lower()
        assert "db.delete(" not in src

    def test_it_requires_the_certificate_first(self):
        """Phase 1 starting without ORE recorded would mean the day advanced
        on nothing."""
        src = _code_only(tr.stay_after_ore)
        assert "ore_completed_at is None" in src

    def test_it_refuses_when_they_already_left(self):
        src = _code_only(tr.stay_after_ore)
        assert "record.left_early" in src

    def test_it_is_idempotent(self):
        """A second tap must not create a second phase-1 record for the day."""
        src = _code_only(tr.stay_after_ore)
        assert "TrainingRecord.current_day_number == 1" in src
        assert '"created": False' in src

    def test_the_new_record_gets_phase_one_tasks(self):
        """Without tasks the record carries no mandatory work and closes
        trivially — the silent-empty-phase failure training_injection warns
        about."""
        src = _code_only(tr.stay_after_ore)
        assert "TrainingCurriculum" in src
        assert "day_number == 1" in src
        assert "TrainingTask(" in src

    def test_it_seeds_the_walker_track(self):
        """Phase 0 is walker-only, so phase 1 started FROM it is too.

        A per-trainee track lookup here would be dead code implying a
        driver_trainee could have an ORE day to stay after. This mirrors
        training_injection, which filters the same way (ADR-263: `trainer` is a
        WALKER trainer and never supervises a driver).
        """
        src = _code_only(tr.stay_after_ore)
        assert 'track = "walker"' in src
        assert "driver_trainee" not in src, (
            "phase 0 is walker-only — a driver branch here is unreachable"
        )
        assert "item.roles" in src

    def test_every_query_is_company_scoped(self):
        src = _code_only(tr.stay_after_ore)
        assert src.count("db.query(") == src.count("company_id == caller.company_id")

    def test_every_reader_of_a_phase_zero_record_sets_the_flag(self):
        """phase_one_started defaults False, so any endpoint that serializes a
        phase-0 record WITHOUT setting it keeps offering "stay or leave" after
        the choice was made.

        /training/trainer/today builds its own response instead of reusing the
        list serializer, and shipped with exactly that gap — the trainer screen
        reads this endpoint, not the list one.
        """
        # DISCOVERED, not listed. Naming the endpoints by hand is how the gap
        # arose in the first place — a new serializer would simply not be in
        # the list, and the test would keep passing.
        import inspect

        # Scoped to the endpoints the ORE CARD reads. A write response
        # (add_trainer_comment, submit_trainee_review) returns the record it
        # just mutated and the card is not rendered from it, so requiring the
        # flag there would be noise that trains people to widen the allowlist.
        CARD_READERS = {"get_trainer_today", "get_trainee_history"}

        offenders = []
        for name, fn in vars(tr).items():
            if name not in CARD_READERS:
                continue
            src = _code_only(fn)
            assert "TrainingRecordResponse.model_validate" in src, (
                f"{name} no longer serializes a record — update CARD_READERS"
            )
            if "phase_one_started" not in src:
                offenders.append(name)
        assert not offenders, (
            "these feed the ORE card but never set phase_one_started, so it "
            f"keeps offering stay-or-leave after the choice: {offenders}"
        )

    def test_the_flag_hides_the_choice_once_taken(self):
        """phase_one_started drives whether the ORE card still offers
        stay-or-leave; without it the buttons never disappear."""
        from app.schemas.training import TrainingRecordResponse

        assert "phase_one_started" in TrainingRecordResponse.model_fields


class TestDriverTrackHasNoPhaseZero:
    """ORE is the walker onboarding course (operator, 2026-08-21).

    The failure this prevents is a stuck trainee, not a crash: give a driver an
    ORE day and there is no certificate for them to upload, so the phase never
    closes and they never reach phase 1.
    """

    def test_the_injector_filters_before_deciding_the_phase(self):
        """curriculum_by_phase is built from the ROLE-FILTERED list, so a
        driver's get(0) is empty and they fall through to phase 1. If the
        filter moved after the phase decision this would silently break."""
        from app.services import training_injection

        src = _code_only(training_injection)
        filter_at = src.index("TRAINEE_CURRICULUM_ROLE in (item.roles")
        build_at = src.index("curriculum_by_phase.setdefault")
        decide_at = src.index("current_phase = 0 if curriculum_by_phase.get(0)")
        assert filter_at < build_at < decide_at, (
            "the role filter must run before the phase decision"
        )

    def test_seeded_data_gives_each_track_the_right_first_phase(self):
        """Against the seed file itself: walkers have phase-0 rows, drivers
        have none."""
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "scripts"
               / "seed_training_curriculum.py").read_text()
        rows = re.findall(r"^\s{4}\(0,.*?\),\s*$", src, re.M | re.S)
        driver_rows = [r for r in rows if '"driver"' in
                       "\n".join(ln for ln in r.splitlines()
                                 if not ln.lstrip().startswith("#"))]
        assert rows, "no phase-0 rows seeded"
        assert not driver_rows, (
            f"{len(driver_rows)} phase-0 row(s) reach the driver track"
        )
