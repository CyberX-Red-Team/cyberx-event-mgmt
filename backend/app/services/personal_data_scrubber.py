"""
Remove a person's identifying copies from every table before their user row
is deleted. Driven entirely by app.services.personal_data_registry.

Must run while the user row still exists: SET NULL foreign keys lose the link
on delete, after which only email matching can find the copies.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import String, and_, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.personal_data_registry import (
    DELETED_PLACEHOLDER,
    REGISTRY,
    PersonalDataSource,
)

logger = logging.getLogger(__name__)

DELETED_USER_TEXT = "[deleted user]"


def _replace_identity(value: Any, needles: list[str], names: set[str]) -> tuple[Any, bool]:
    """Recursively replace strings containing the person's email, or equal to their name."""
    if isinstance(value, dict):
        changed = False
        out = {}
        for k, v in value.items():
            out[k], c = _replace_identity(v, needles, names)
            changed |= c
        return out, changed
    if isinstance(value, list):
        changed = False
        out_list = []
        for v in value:
            nv, c = _replace_identity(v, needles, names)
            out_list.append(nv)
            changed |= c
        return out_list, changed
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in names or any(n in lowered for n in needles):
            return DELETED_USER_TEXT, True
    return value, False


class PersonalDataScrubber:
    """Scrub (or delete) everything the registry ties to one person."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _identity(user: User) -> tuple[list[str], set[str]]:
        needles = {e.strip().lower() for e in (user.email, user.email_normalized) if e}
        names = set()
        full = f"{user.first_name or ''} {user.last_name or ''}".strip().lower()
        if full and " " in full:  # never match a lone first name
            names.add(full)
        return sorted(needles), names

    def _row_filter(self, src: PersonalDataSource, user: User, needles: list[str]):
        model = src.model
        conds = [getattr(model, c) == user.id for c in src.subject_columns]
        for col in src.email_columns:
            conds.append(func.lower(getattr(model, col)).in_(needles))
        if model is AuditLog:
            conds.append(and_(AuditLog.resource_type == "USER", AuditLog.resource_id == user.id))
        return or_(*conds) if conds else None

    async def scrub_user(self, user: User) -> dict[str, int]:
        """Scrub/delete the person's rows. Doesn't delete the user row or commit."""
        needles, names = self._identity(user)
        counts: dict[str, int] = {}

        for src in REGISTRY:
            model = src.model
            if src.key == "users":
                # Copies of this person's email on other people's rows (referrer email).
                for col in src.other_person_email_columns:
                    res = await self.session.execute(
                        update(User)
                        .where(func.lower(getattr(User, col)).in_(needles), User.id != user.id)
                        .values({col: None})
                        .execution_options(synchronize_session=False)
                    )
                    counts[f"users.{col}"] = res.rowcount or 0
                continue

            if src.on_delete == "keep":
                continue

            row_filter = self._row_filter(src, user, needles)
            if row_filter is None:
                continue

            if src.on_delete == "delete":
                res = await self.session.execute(
                    delete(model).where(row_filter).execution_options(synchronize_session=False)
                )
                counts[src.key] = res.rowcount or 0
                continue

            # scrub
            values = src.scrub_values()
            if values:
                res = await self.session.execute(
                    update(model).where(row_filter).values(values)
                    .execution_options(synchronize_session=False)
                )
                counts[src.key] = res.rowcount or 0

            for col in src.json_columns:
                counts[f"{src.key}.{col}"] = await self._scrub_json(
                    src, col, row_filter, needles, names
                )

        logger.info("Scrubbed personal data for user %s: %s", user.id, counts)
        return counts

    async def _scrub_json(self, src, col, row_filter, needles, names) -> int:
        """Rewrite JSON values that embed the person's email or name."""
        model = src.model
        column = getattr(model, col)
        text = cast(column, String)
        candidates = or_(
            row_filter,
            *[text.ilike(f"%{n}%") for n in needles],
        )
        result = await self.session.execute(
            select(model.id, column).where(column.isnot(None), candidates)
        )
        changed = 0
        for row_id, value in result.all():
            new_value, did_change = _replace_identity(value, needles, names)
            if did_change:
                await self.session.execute(
                    update(model).where(model.id == row_id).values({col: new_value})
                    .execution_options(synchronize_session=False)
                )
                changed += 1
        return changed


__all__ = ["PersonalDataScrubber", "DELETED_USER_TEXT", "DELETED_PLACEHOLDER"]
