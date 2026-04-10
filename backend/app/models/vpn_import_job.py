"""VPN Import Job model for asynchronous VPN credential imports."""
import enum

from sqlalchemy import BigInteger, Column, ForeignKey, Index, Integer, JSON, String, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func

from app.database import Base


# Portable JSON type: use JSONB on Postgres for indexable JSON, fall back to
# generic JSON on other dialects (SQLite in tests). Wrapped with MutableDict
# so in-place mutations on the column value are tracked by the SQLAlchemy
# session — needed because the import job appends to ``errors`` over time.
JsonType = MutableDict.as_mutable(JSON().with_variant(JSONB(), "postgresql"))


class VPNImportJobStatus(str, enum.Enum):
    """Lifecycle state of a VPN import job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VPNImportJob(Base):
    """
    Tracks a background VPN credential import from a ZIP archive.

    The HTTP handler stages the uploaded ZIP in R2 and creates a row with
    ``status=pending``. A scheduled task picks up pending rows and runs the
    import cooperatively, updating the progress counters as it goes. The
    admin UI polls the status endpoint to show a progress bar.
    """

    __tablename__ = "vpn_import_jobs"

    id = Column(Integer, primary_key=True)

    # Who and what
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename = Column(String(255), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=False)
    assignment_type = Column(String(50), nullable=False)
    endpoint_override = Column(String(255), nullable=True)

    # R2 key where the staged ZIP lives until processing completes. Cleared
    # when the job completes so the staged upload is not retained forever.
    r2_key = Column(String(255), nullable=True)

    # Status / progress
    status = Column(
        String(20),
        nullable=False,
        default=VPNImportJobStatus.PENDING.value,
        index=True,
    )
    total_files = Column(Integer, nullable=True)
    processed_files = Column(Integer, nullable=False, default=0)
    imported_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    # Capped list of error messages (stored under the "items" key)
    errors = Column(JsonType, nullable=True)

    # Timestamps
    created_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_vpn_import_jobs_status", "status"),
        Index("idx_vpn_import_jobs_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<VPNImportJob(id={self.id}, status={self.status}, "
            f"processed={self.processed_files}/{self.total_files})>"
        )
