"""A company's pass/fail target for one scorecard metric (ADR-473).

REPLACES ten hardcoded `CompanyConfig.scorecard_*_target` columns. Those asserted
a direction and a unit at schema level -- `# %, higher better` in a comment, and
a `le=100.0` bound in the request schema -- and five of the ten asserted them
WRONG when checked against Amazon's own metric guides: two defect rates modelled
as percentages where higher passes, one completion rate that measures something
else entirely, one metric that is not scored at all, and one that is a component
of another.

Nothing compared against them yet (`meets_target` had no callers), so the fix
landed before the wiring rather than after an incident.

SHAPED LIKE `ScorecardMetric` ON PURPOSE. The ingestion side was already
key/value with a `unit`, which is why it absorbed Amazon's changes while the
column side silently diverged. A metric Amazon adds is now a row; one it renames
is a data migration; one it retires becomes inert instead of a column that must
be explained forever.

DIRECTION AND UNIT ARE STORED, NEVER INFERRED. That is the whole correction: a
column comment is not enforcement, and the old `le=100.0` actively prevented a
correct DPMO value from being saved.
"""
import uuid

from sqlalchemy import (
    CheckConstraint, Column, DateTime, Float, ForeignKey, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

# How a value is compared against its target.
VALID_DIRECTIONS = ("higher", "lower")

# What the number means. Drives validation, not just display: a percent is
# bounded 0-100 and a DPMO is not, which is exactly the distinction the old
# request schema got wrong.
VALID_UNITS = ("percent", "dpmo", "rate_per_100", "score")


class CompanyMetricTarget(Base):
    """One company's target for one metric key.

    `metric_key` matches the key used by `ScorecardMetric`, so a stored target
    and an ingested value meet on the same string rather than through a
    hand-maintained map between column names and metric names.
    """

    __tablename__ = "company_metric_targets"
    __table_args__ = (
        UniqueConstraint("company_id", "metric_key",
                         name="uq_company_metric_targets_company_key"),
        CheckConstraint(
            "direction IN {}".format(VALID_DIRECTIONS),
            name="ck_company_metric_targets_direction",
        ),
        CheckConstraint(
            "unit IN {}".format(VALID_UNITS),
            name="ck_company_metric_targets_unit",
        ),
        # A percent that cannot be a percent is the ADR-472 defect in miniature.
        # Enforced in the DB as well as the schema because the schema was where
        # the original bound was wrong.
        CheckConstraint(
            "unit <> 'percent' OR (target_value >= 0 AND target_value <= 100)",
            name="ck_company_metric_targets_percent_range",
        ),
        CheckConstraint(
            "target_value >= 0",
            name="ck_company_metric_targets_non_negative",
        ),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    metric_key   = Column(String(50), nullable=False, index=True)
    target_value = Column(Float, nullable=False)
    # NOT defaulted. A target whose direction nobody stated is a comparison
    # waiting to be made backwards, which is the whole reason this table exists.
    direction    = Column(String(10), nullable=False)
    unit         = Column(String(20), nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
