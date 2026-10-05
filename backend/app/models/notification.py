import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


# ADR-487 D2. False while the 83 call sites migrate; True once they are done.
# The guard itself is tested in both states — see test_adr487_notify.py.
_GUARD_ARMED = False


class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type        = Column(String(50), nullable=False)
    message     = Column(Text, nullable=False)
    is_read     = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    # Populated only for type='dispatch_assignment' — tells the frontend
    # which date to POST /dispatch/{date}/confirmations against.
    dispatch_date = Column(Date, nullable=True)
    # dispatch_assignment: expires at confirmation deadline; dispatch_assignment_info: expires at midnight of dispatch_date; others: NULL
    expires_at    = Column(DateTime(timezone=True), nullable=True)

    def __init__(self, *args, **kwargs):
        """Refuse direct construction (ADR-487 D2).

        Migrating the 83 original call sites was not enough: `db.add(
        Notification(...))` still works afterwards and reads exactly like the
        surrounding code, so the 84th site would use it and skip the registry
        lookup — no severity, no push, no ticker.

        A CI grep cannot close that. `grep "db.add(Notification("` passes on
        `db.add_all([Notification(...) for ...])`, which is literally the shape
        of walker_routes.py:1040 — the one site that had no `type=` at all and
        whose rows were silently discarded. The LEARNING_GUIDE records the
        general case: "grepping for a function name misses its wrappers."

        SAFE FOR READS, verified rather than assumed: SQLAlchemy does not call
        __init__ when materialising a loaded row, so this constrains writes only.

            class T(Base):
                def __init__(self, **kw):
                    calls.append("init"); super().__init__(**kw)

            s.add(T(name="x")); s.commit()   # -> 1 call
            s.query(T).first()               # -> still 1 call

        Tests that genuinely exercise the model pass `_via_helper=True`; tests
        that exercise behaviour should go through `services.notify` instead.
        """
        # MIGRATION IN PROGRESS (ADR-487 D2). The guard is written and verified
        # but not yet armed: 83 call sites across 38 files still construct
        # directly, and arming it before they migrate means a red suite across
        # a dozen commits — in which a genuine regression hides among the
        # expected failures.
        #
        # Flip _GUARD_ARMED to True in the final migration commit, when nothing
        # violates it. `test_adr487_notify.py` asserts the guard WORKS whether
        # or not it is armed, so this cannot be forgotten silently: the test
        # that pins the armed behaviour is skipped with a reason, and
        # `test_the_guard_is_armed_once_migration_completes` fails as soon as
        # the last site is migrated.
        if _GUARD_ARMED and not kwargs.pop("_via_helper", False):
            raise RuntimeError(
                "Construct notifications with services.notify.write_notification() "
                "or fan_out() (ADR-487 D2) — they resolve notification_spec.SPEC "
                "and record the channel fan-out. A direct Notification(...) skips "
                "severity, push, Discord and the ticker."
            )
        kwargs.pop("_via_helper", None)
        super().__init__(*args, **kwargs)
