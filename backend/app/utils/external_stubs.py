"""Stub flag for external client calls.

When STAGING_STUB_EXTERNALS is set, destructive external calls (R2 object
deletes, Render service deletes, cloud-provider VM deletes) are skipped
and logged instead. Used during staging iterations where the DB was
restored from a prod dump and points at resources that live in a
different account — invoking the real APIs would either fail noisily
or, worse, affect prod.

DB mutations still run as normal; only external side-effects are
isolated. Production deployments must never set this flag.
"""
import os


def externals_stubbed() -> bool:
    return os.getenv("STAGING_STUB_EXTERNALS", "").lower() in ("1", "true", "yes")
