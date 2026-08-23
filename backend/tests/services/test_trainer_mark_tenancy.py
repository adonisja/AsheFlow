"""ADR-115 dim 1 — trainer-mark attribution must not cross tenants.

Found while checking whether the driver track needed its own TrainerMark
handling (it does not — nothing is recorded about a supervising driver). The
walker path had eight queries in this service and six were unscoped.

THE ONE THAT MATTERED
---------------------
The underperforming-trainer threshold counted distinct trainees filtered by
`trainer_id` ALONE. A trainer present in two tenants had their marks pooled
across both, so one company's training records could fire a management alert in
another company — and the alert names the trainer.

`record_exemplary_note` resolved trainer AND trainee NAMES unscoped, straight
into a management notification: a cross-tenant name disclosure, not merely a
wrong count.
"""
import inspect

from app.services import record_trainer_mark as mod


def _queries(fn):
    src = inspect.getsource(fn)
    lines = src.splitlines()
    return [
        (ln.strip(), "\n".join(lines[i : i + 9]))
        for i, ln in enumerate(lines)
        if "db.query(" in ln
    ]


class TestEverySecondaryLookupIsScoped:
    def test_record_trainer_mark(self):
        unscoped = [
            q for q, w in _queries(mod.record_trainer_mark)
            if "company_id" not in w and "TrainingRecord.id ==" not in w
        ]
        assert not unscoped, f"unscoped secondary lookups: {unscoped}"

    def test_record_exemplary_note(self):
        unscoped = [
            q for q, w in _queries(mod.record_exemplary_note)
            if "company_id" not in w and "TrainingRecord.id ==" not in w
        ]
        assert not unscoped, f"unscoped secondary lookups: {unscoped}"


class TestTheThresholdCount:
    def test_it_is_company_scoped(self):
        """THE bug. Without this filter, marks pool across tenants and one
        company's records trip another company's alert."""
        src = inspect.getsource(mod.record_trainer_mark)
        i = src.index("db.query(TrainerMark.trainee_id)")
        window = src[i : i + 320]
        assert "TrainerMark.trainer_id == record.trainer_id" in window
        assert "TrainerMark.company_id == company_id" in window

    def test_the_mark_row_carries_its_company(self):
        """A mark written without company_id cannot be scoped when read back."""
        src = inspect.getsource(mod.record_trainer_mark)
        i = src.index("mark = TrainerMark(")
        assert "company_id=company_id," in src[i : i + 260]


class TestNamesInNotificationsAreScoped:
    def test_exemplary_note_resolves_both_names_within_the_tenant(self):
        """These names go into a management notification. An unscoped read is a
        PII disclosure across tenants (ADR-115 dim 7)."""
        src = inspect.getsource(mod.record_exemplary_note)
        assert src.count("Employee.company_id == record.company_id") == 2
