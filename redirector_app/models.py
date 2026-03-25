"""Re-export shim — canonical model definitions live in backend/app/models/redirector.py.

Both this module and backend/app/models/redirector.py previously defined Redirector and
StreamConfig, causing a SQLAlchemy registry collision (both imported the same Base via
backend/app/database.py → redirector_app/database.py). This shim eliminates the duplicate.
"""
from app.models.redirector import (  # noqa: F401
    Redirector,
    StreamConfig,
    RedirectorStatus,
    StreamProtocol,
)
