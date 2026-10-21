from sqlalchemy import Column, DateTime, String, func

from app.models.base import Base


class PlatformSessionStamp(Base):
    """When a platform account's sessions were last ended (ADR-549 D3).

    The platform twin of `Employee.tokens_valid_after` (ADR-541 D2). Platform
    accounts (super_admin, platform_support, surveyor) have no Employee row by
    design (ADR-394), so before this there was nowhere to record "every session
    signed in before now is over" -- a password change revoked their refresh
    tokens at Cognito but left access tokens working here for up to an hour.

    Keyed by the Cognito sub: it is the one identifier a platform account has
    that never changes. Durable (not Redis) because revocation that a cache
    flush can undo is not revocation.
    """
    __tablename__ = "platform_session_stamps"

    cognito_sub        = Column(String(64), primary_key=True)
    tokens_valid_after = Column(DateTime(timezone=True), nullable=False)
    updated_at         = Column(DateTime(timezone=True), nullable=False,
                                server_default=func.now(), onupdate=func.now())
