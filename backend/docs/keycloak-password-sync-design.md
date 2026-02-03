# Keycloak Password Synchronization Design

## Problem Statement

The CyberX event management system needs to synchronize user credentials between two separate authentication systems:

1. **Web Portal** - PostgreSQL database (stores `password_hash` for bcrypt/argon2)
2. **Training Environment (Keycloak)** - Manages training event credentials

### Constraints

- **Security**: Cannot store plaintext passwords in the database
- **Availability**: Keycloak will NOT be available at the same time as the website
- **Separation**: Authentication sources must remain independent
- **User Experience**: Users should only remember one password

## Current Database Schema

```python
# app/models/user.py
class User(Base):
    # Web portal authentication
    password_hash = Column(String(255), nullable=True)  # Hashed for web login

    # Training environment credentials
    pandas_username = Column(String(255), unique=True, nullable=True)
    pandas_password = Column(String(255), nullable=True)  # Currently plaintext - SECURITY ISSUE
```

## Recommended Solution: Encrypted Queue with Retry

### Architecture Overview

```
User Password Change
       ↓
Store hashed (web) + encrypted (Keycloak sync queue)
       ↓
Background Job (every 5 min)
       ↓
Check if Keycloak available
       ↓
Decrypt → Sync → Mark as synced
```

### Security Model

- **Web Portal**: Passwords hashed with bcrypt/argon2 (one-way)
- **Sync Queue**: Passwords encrypted with Fernet (symmetric, reversible)
- **Keycloak**: Manages its own password hashing
- **Encryption Key**: Stored in environment variables, rotatable

### Implementation Components

#### 1. Password Sync Queue Table

```python
# backend/app/models/password_sync_queue.py
class PasswordSyncQueue(Base):
    """Queue for syncing passwords to Keycloak when it becomes available."""

    __tablename__ = "password_sync_queue"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    username = Column(String(255), nullable=False)
    encrypted_password = Column(Text, nullable=False)  # Fernet encrypted

    # Sync tracking
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    synced = Column(Boolean, default=False)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Retry logic
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_password_sync_queue_synced', 'synced'),
        Index('idx_password_sync_queue_user_id', 'user_id'),
    )
```

#### 2. Password Sync Service

```python
# backend/app/services/password_sync_service.py
from cryptography.fernet import Fernet

class PasswordSyncService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.cipher = Fernet(settings.PASSWORD_ENCRYPTION_KEY.encode())

    def encrypt_password(self, password: str) -> str:
        """Encrypt password for temporary storage."""
        return self.cipher.encrypt(password.encode()).decode()

    def decrypt_password(self, encrypted: str) -> str:
        """Decrypt password for Keycloak sync."""
        return self.cipher.decrypt(encrypted.encode()).decode()

    async def queue_password_sync(self, user_id: int, username: str, password: str):
        """Queue password for later sync to Keycloak."""
        encrypted = self.encrypt_password(password)

        # Upsert logic: update if exists, create if not
        existing = await self.session.execute(
            select(PasswordSyncQueue).where(
                PasswordSyncQueue.user_id == user_id,
                PasswordSyncQueue.synced == False
            )
        )
        existing = existing.scalar_one_or_none()

        if existing:
            existing.encrypted_password = encrypted
            existing.retry_count = 0
            existing.last_error = None
        else:
            queue_entry = PasswordSyncQueue(
                user_id=user_id,
                username=username,
                encrypted_password=encrypted
            )
            self.session.add(queue_entry)

        await self.session.commit()

    async def process_sync_queue(self, max_retries: int = 5):
        """Process all pending password syncs when Keycloak is available."""
        result = await self.session.execute(
            select(PasswordSyncQueue).where(
                PasswordSyncQueue.synced == False,
                PasswordSyncQueue.retry_count < max_retries
            )
        )
        pending = result.scalars().all()

        synced_count = 0
        failed_count = 0

        for entry in pending:
            try:
                password = self.decrypt_password(entry.encrypted_password)
                success = await self.sync_to_keycloak(entry.username, password)

                if success:
                    entry.synced = True
                    entry.synced_at = datetime.now(timezone.utc)
                    synced_count += 1
                else:
                    entry.retry_count += 1
                    entry.last_error = "Keycloak sync failed"
                    failed_count += 1

            except Exception as e:
                entry.retry_count += 1
                entry.last_error = str(e)
                failed_count += 1

        await self.session.commit()
        return {"synced": synced_count, "failed": failed_count}

    async def sync_to_keycloak(self, username: str, password: str) -> bool:
        """Attempt to sync password to Keycloak via Admin API."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Health check
                health = await client.get(f"{settings.KEYCLOAK_URL}/health")
                if health.status_code != 200:
                    return False

                # Get admin token
                admin_token = await self._get_admin_token(client)

                # Find user
                user_id = await self._find_keycloak_user(client, admin_token, username)

                # Update password
                response = await client.put(
                    f"{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}/users/{user_id}/reset-password",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "type": "password",
                        "value": password,
                        "temporary": False
                    }
                )
                return response.status_code == 204

        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def _get_admin_token(self, client: httpx.AsyncClient) -> str:
        """Get Keycloak admin access token."""
        response = await client.post(
            f"{settings.KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET
            }
        )
        data = response.json()
        return data["access_token"]

    async def _find_keycloak_user(self, client: httpx.AsyncClient, token: str, username: str) -> str:
        """Find Keycloak user ID by username."""
        response = await client.get(
            f"{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}/users",
            headers={"Authorization": f"Bearer {token}"},
            params={"username": username, "exact": True}
        )
        users = response.json()
        if not users:
            raise ValueError(f"User {username} not found in Keycloak")
        return users[0]["id"]
```

#### 3. Background Sync Job

```python
# backend/app/jobs/password_sync_job.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.password_sync_service import PasswordSyncService

async def sync_passwords_job():
    """Periodic job to sync queued passwords when Keycloak becomes available."""
    async with get_db_session() as session:
        sync_service = PasswordSyncService(session)
        result = await sync_service.process_sync_queue()

        if result['synced'] > 0:
            logger.info(f"Synced {result['synced']} passwords to Keycloak")
        if result['failed'] > 0:
            logger.warning(f"{result['failed']} password syncs failed, will retry")

# Setup scheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(sync_passwords_job, 'interval', minutes=5)
scheduler.start()
```

#### 4. Integration with Participant Service

```python
# backend/app/services/participant_service.py
async def update_participant(self, participant_id: int, **kwargs) -> Optional[User]:
    """Update a participant and queue password sync if password changed."""
    participant = await self.get_participant(participant_id)

    # Check if password is being updated
    new_password = kwargs.get('pandas_password')

    # Update fields
    for key, value in kwargs.items():
        if hasattr(participant, key):
            setattr(participant, key, value)

    # Also update web portal password hash
    if new_password:
        participant.password_hash = hash_password(new_password)

        # Queue for Keycloak sync
        sync_service = PasswordSyncService(self.session)
        await sync_service.queue_password_sync(
            user_id=participant.id,
            username=participant.pandas_username,
            password=new_password
        )

    await self.session.commit()
    return participant
```

#### 5. Admin Dashboard for Sync Monitoring

```python
# backend/app/api/routes/admin.py
@router.get("/password-sync/status")
async def get_password_sync_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get password sync queue status."""
    result = await db.execute(
        select(
            func.count(PasswordSyncQueue.id).label('total'),
            func.sum(case((PasswordSyncQueue.synced == True, 1), else_=0)).label('synced'),
            func.sum(case((PasswordSyncQueue.synced == False, 1), else_=0)).label('pending')
        )
    )
    stats = result.first()

    # Get failed syncs (retry_count >= max_retries)
    failed_result = await db.execute(
        select(PasswordSyncQueue).where(
            PasswordSyncQueue.synced == False,
            PasswordSyncQueue.retry_count >= 5
        )
    )
    failed = failed_result.scalars().all()

    return {
        "total": stats.total or 0,
        "synced": stats.synced or 0,
        "pending": stats.pending or 0,
        "failed": len(failed),
        "failed_items": [
            {
                "user_id": f.user_id,
                "username": f.username,
                "retry_count": f.retry_count,
                "last_error": f.last_error,
                "created_at": f.created_at
            }
            for f in failed
        ]
    }

@router.post("/password-sync/retry/{queue_id}")
async def retry_password_sync(
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Manually retry a failed password sync."""
    result = await db.execute(
        select(PasswordSyncQueue).where(PasswordSyncQueue.id == queue_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Sync entry not found")

    # Reset retry count to allow processing
    entry.retry_count = 0
    entry.last_error = None
    await db.commit()

    return {"status": "ok", "message": "Retry scheduled"}

@router.post("/password-sync/process-now")
async def process_sync_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Manually trigger password sync processing."""
    sync_service = PasswordSyncService(db)
    result = await sync_service.process_sync_queue()

    return {
        "status": "ok",
        "synced": result["synced"],
        "failed": result["failed"]
    }
```

## Configuration

### Environment Variables (.env)

```bash
# Keycloak Configuration
KEYCLOAK_URL=https://auth.cyberxredteam.org
KEYCLOAK_REALM=cyberx
KEYCLOAK_ADMIN_CLIENT_ID=admin-cli
KEYCLOAK_ADMIN_CLIENT_SECRET=your-secret-here

# Password Encryption Key (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
PASSWORD_ENCRYPTION_KEY=your-fernet-key-here

# Sync Job Configuration
PASSWORD_SYNC_ENABLED=true
PASSWORD_SYNC_INTERVAL_MINUTES=5
PASSWORD_SYNC_MAX_RETRIES=5
```

### Settings Schema

```python
# backend/app/config.py
class Settings(BaseSettings):
    # Existing settings...

    # Keycloak
    KEYCLOAK_URL: str = Field(default="https://auth.cyberxredteam.org")
    KEYCLOAK_REALM: str = Field(default="cyberx")
    KEYCLOAK_ADMIN_CLIENT_ID: str = Field(default="admin-cli")
    KEYCLOAK_ADMIN_CLIENT_SECRET: str

    # Password Sync
    PASSWORD_ENCRYPTION_KEY: str
    PASSWORD_SYNC_ENABLED: bool = Field(default=True)
    PASSWORD_SYNC_INTERVAL_MINUTES: int = Field(default=5)
    PASSWORD_SYNC_MAX_RETRIES: int = Field(default=5)
```

## Database Migration

```python
# backend/migrations/versions/xxx_add_password_sync_queue.py
def upgrade() -> None:
    op.create_table(
        'password_sync_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('synced', sa.Boolean(), nullable=False, default=False),
        sa.Column('synced_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_password_sync_queue_synced', 'password_sync_queue', ['synced'])
    op.create_index('idx_password_sync_queue_user_id', 'password_sync_queue', ['user_id'])

def downgrade() -> None:
    op.drop_index('idx_password_sync_queue_user_id', 'password_sync_queue')
    op.drop_index('idx_password_sync_queue_synced', 'password_sync_queue')
    op.drop_table('password_sync_queue')
```

## Implementation Checklist

- [ ] **Database & Models**
  - [ ] Create `PasswordSyncQueue` model
  - [ ] Create Alembic migration
  - [ ] Run migration on dev database

- [ ] **Core Service**
  - [ ] Implement `PasswordSyncService` with encryption
  - [ ] Add Keycloak Admin API client methods
  - [ ] Add error handling and logging

- [ ] **Background Job**
  - [ ] Create `password_sync_job.py`
  - [ ] Integrate with APScheduler
  - [ ] Add job to application startup

- [ ] **Service Integration**
  - [ ] Update `participant_service.update_participant()`
  - [ ] Update `participant_service.create_participant()`
  - [ ] Update password reset endpoints

- [ ] **Admin API**
  - [ ] Add `/api/admin/password-sync/status` endpoint
  - [ ] Add `/api/admin/password-sync/retry/{queue_id}` endpoint
  - [ ] Add `/api/admin/password-sync/process-now` endpoint

- [ ] **Admin UI** (Optional)
  - [ ] Create password sync dashboard page
  - [ ] Add status cards (pending, synced, failed)
  - [ ] Add failed syncs table with retry button
  - [ ] Add manual trigger button

- [ ] **Configuration**
  - [ ] Add Keycloak settings to `.env`
  - [ ] Generate and add `PASSWORD_ENCRYPTION_KEY`
  - [ ] Update `Settings` class

- [ ] **Security**
  - [ ] Remove plaintext `pandas_password` storage (replace with encrypted queue)
  - [ ] Implement key rotation procedure
  - [ ] Add audit logging for sync operations

- [ ] **Testing**
  - [ ] Unit tests for encryption/decryption
  - [ ] Integration tests for Keycloak API
  - [ ] Test retry logic with Keycloak offline
  - [ ] Test background job execution

## Security Considerations

1. **Encryption Key Management**
   - Store encryption key in environment variables only
   - Never commit to git
   - Rotate keys periodically (requires re-encrypting queue)
   - Use different keys for dev/staging/prod

2. **Password Lifecycle**
   - Passwords exist encrypted in queue only until synced
   - Successfully synced entries can be purged after N days
   - Failed syncs (max retries) should alert admins

3. **Audit Trail**
   - Log all password sync attempts (success/failure)
   - Track who initiated password changes
   - Monitor sync queue size (large queue = Keycloak down)

4. **Access Control**
   - Only admin users can view sync status
   - Only admin users can manually retry syncs
   - Background job runs with service account

## Monitoring & Alerting

**Metrics to Track:**
- Queue size (pending syncs)
- Sync success rate
- Average sync latency
- Failed sync count (retry_count >= max)

**Alerts:**
- Queue size > 100 (Keycloak likely down)
- Failed syncs > 10 (investigate)
- No successful syncs in 24 hours (Keycloak down)

## Alternative Approaches (Rejected)

### 1. Plaintext Storage
**Why rejected:** Security risk. Passwords should never be stored in plaintext.

### 2. One-Way Sync Only (No Retry)
**Why rejected:** With Keycloak unavailable when website runs, syncs would fail permanently.

### 3. User-Initiated Password Reset
**Why rejected:** Poor UX. Users shouldn't need to reset passwords in Keycloak separately.

### 4. Shared Database
**Why rejected:** Violates separation of concerns. Systems should remain independent.

## Future Enhancements

1. **Bulk User Provisioning**
   - Mass create Keycloak accounts from CSV import
   - Batch password sync API

2. **Bi-directional Sync**
   - Listen to Keycloak password change events
   - Update web portal when users change password in Keycloak

3. **Multi-Realm Support**
   - Support syncing to different Keycloak realms
   - Environment-based realm selection (dev/staging/prod)

4. **Advanced Retry Logic**
   - Exponential backoff
   - Circuit breaker pattern
   - Priority queue (admins first)

## References

- [Keycloak Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/)
- [Cryptography Fernet](https://cryptography.io/en/latest/fernet/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
