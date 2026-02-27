"""Password sync queue model for Keycloak integration."""
import enum
from sqlalchemy import Column, Integer, String, Boolean, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.sql import func
from app.database import Base


class SyncOperation(str, enum.Enum):
    """Type of sync operation to perform on Keycloak."""
    CREATE_USER = "create_user"
    UPDATE_PASSWORD = "update_password"
    DELETE_USER = "delete_user"


class PasswordSyncQueue(Base):
    """
    Queue for syncing user credentials to Keycloak when it becomes available.

    Entries are created when:
    - A user confirms participation (CREATE_USER)
    - A password is reset (UPDATE_PASSWORD)
    - A participant is removed (DELETE_USER)

    A background job processes unsynced entries periodically.
    """

    __tablename__ = "password_sync_queue"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    username = Column(String(255), nullable=False)
    encrypted_password = Column(Text, nullable=True)  # Fernet encrypted; NULL for DELETE_USER
    operation = Column(String(50), nullable=False, default=SyncOperation.CREATE_USER.value)

    # Sync tracking
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    synced = Column(Boolean, default=False, nullable=False)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Retry logic
    retry_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_password_sync_queue_synced', 'synced'),
        Index('idx_password_sync_queue_user_id', 'user_id'),
    )

    def __repr__(self):
        return (
            f"<PasswordSyncQueue(id={self.id}, user_id={self.user_id}, "
            f"username={self.username}, operation={self.operation}, synced={self.synced})>"
        )
