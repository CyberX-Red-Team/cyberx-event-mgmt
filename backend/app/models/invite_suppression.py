"""Do-not-invite list (stores only a keyed hash of the email address)."""
from sqlalchemy import Column, String, TIMESTAMP
from sqlalchemy.sql import func

from app.database import Base


class InviteSuppression(Base):
    """
    One row per person who asked not to be invited again.

    email_hmac is HMAC-SHA256 of the normalized email under a server-side key,
    so the table can't be turned back into email addresses.
    """

    __tablename__ = "invite_suppressions"

    email_hmac = Column(String(64), primary_key=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<InviteSuppression(created_at={self.created_at})>"
