"""VPN Delete Job model for asynchronous bulk credential deletion."""
import enum

from sqlalchemy import Column, ForeignKey, Index, Integer, String, TIMESTAMP, Text
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func

from app.database import Base
from app.models.vpn_import_job import JsonType


class VPNDeleteJobStatus(str, enum.Enum):
    """Lifecycle state of a VPN bulk delete job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VPNDeleteJobMode(str, enum.Enum):
    """Whether the job deletes a specific id list or every credential."""
    BY_IDS = "by_ids"  # uses target_ids
    ALL = "all"  # ignores target_ids; resolves at processing time


class VPNDeleteJob(Base):
    """
    Tracks a background bulk-delete of VPN credentials.

    The HTTP handler creates a row with ``status=pending`` and either a list
    of target ids (``mode=by_ids``) or a marker (``mode=all``) telling the
    worker to delete every credential. A scheduled task picks up pending
    rows and runs the deletion cooperatively, updating progress columns as
    it goes.
    """

    __tablename__ = "vpn_delete_jobs"

    id = Column(Integer, primary_key=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    mode = Column(String(20), nullable=False, default=VPNDeleteJobMode.BY_IDS.value)
    # JSON list of integers; only meaningful when mode=by_ids. For mode=all,
    # the worker resolves the list at processing time.
    target_ids = Column(JsonType, nullable=True)

    # Status / progress
    status = Column(
        String(20),
        nullable=False,
        default=VPNDeleteJobStatus.PENDING.value,
        index=True,
    )
    total_credentials = Column(Integer, nullable=True)
    processed_credentials = Column(Integer, nullable=False, default=0)
    deleted_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    # Capped list of error messages, stored under {"items": [...]}
    errors = Column(JsonType, nullable=True)

    # Timestamps
    created_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_vpn_delete_jobs_status", "status"),
        Index("idx_vpn_delete_jobs_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<VPNDeleteJob(id={self.id}, mode={self.mode}, status={self.status}, "
            f"deleted={self.deleted_count}/{self.total_credentials})>"
        )
