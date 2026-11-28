"""
Personal-data export (access requests): one ZIP with everything the platform
holds about a person, driven by app.services.personal_data_registry so export
and deletion cover the same tables.

Contents: README.txt, data.json (one key per source), summary.html (the same as
readable tables, no external assets) and certificates/*.pdf.

Never included: secrets (each source has an explicit column allowlist), and
anything about another person beyond a name that's part of the relationship
(referrer, guardian). Rows that belong to someone else are filtered out (e.g. a
guardian's copies of a minor's emails), other people's IP/browser on audit
entries are dropped, and other people's emails/names inside audit details are
replaced with "another user".
"""
from __future__ import annotations

import html
import io
import json
import logging
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.event import Event
from app.models.role import Role
from app.models.user import User
from app.services.personal_data_registry import REGISTRY, PersonalDataSource

logger = logging.getLogger(__name__)

ANOTHER_USER = "another user"

SECTION_TITLES = {
    "users": "Your account and contact details",
    "event_participations": "Invitations and registrations",
    "sessions": "Active portal sign-in sessions",
    "audit_logs": "Security log entries about you",
    "email_events": "Email delivery records",
    "email_queue": "Emails we sent you",
    "vpn_requests": "Network access requests",
    "vpn_credentials": "Network access assigned to you",
    "instances": "Exercise systems assigned to you",
    "tls_certificates": "TLS certificates",
    "participant_actions": "Actions assigned to you",
    "cpe_certificates": "CPE certificates",
    "guardian_consents": "Parent or guardian consent",
    "redirectors": "Redirectors you own",
}


def _plain(value: Any) -> Any:
    """JSON-safe value with ISO 8601 timestamps."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


# Audit `details` keys that hold a person's name (not e.g. template_name / event_name)
PERSON_NAME_KEYS = {
    "name", "user_name", "full_name", "first_name", "last_name", "invitee_name", "sponsor_name",
    "admin_name", "guardian_name", "minor_name", "target_name", "deleted_user_name",
    "created_by_name", "issued_by_name", "revoked_by_name",
}


def _redact_others(value: Any, own_identity: set[str]) -> Any:
    """Replace other people's emails / names in an audit `details` blob."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, str) and k in PERSON_NAME_KEYS and v.strip().lower() not in own_identity:
                out[k] = ANOTHER_USER
            else:
                out[k] = _redact_others(v, own_identity)
        return out
    if isinstance(value, list):
        return [_redact_others(v, own_identity) for v in value]
    if isinstance(value, str) and "@" in value and value.strip().lower() not in own_identity:
        return ANOTHER_USER
    return value


class DataExportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    # ------------------------------------------------------------- collect

    async def _rows(self, src: PersonalDataSource, user: User) -> list[dict]:
        table = src.model.__table__
        conds = [table.c[c] == user.id for c in src.subject_columns]
        if src.model is AuditLog:
            conds.append(and_(table.c.resource_type == "USER", table.c.resource_id == user.id))
        cols = [table.c[c] for c in src.export_columns]
        extra = [table.c[c] for c in src.subject_columns if c not in src.export_columns]
        query = select(*cols, *extra).where(or_(*conds))
        if "created_at" in table.c:
            query = query.order_by(table.c.created_at)
        result = await self.session.execute(query)
        return [dict(r._mapping) for r in result.all()]

    async def collect(self, user: User) -> dict:
        own = {v.strip().lower() for v in (user.email, user.email_normalized,
                                           f"{user.first_name} {user.last_name}") if v}
        event_names = {e.id: e.name for e in (await self.session.execute(select(Event))).scalars().all()}
        data: dict[str, Any] = {}
        for src in REGISTRY:
            if not src.subject_columns or not src.export_columns:
                continue
            rows = await self._rows(src, user)
            out = []
            for row in rows:
                if src.key == "users":
                    if row.get("id", user.id) != user.id:
                        continue
                elif src.key in ("email_queue", "email_events"):
                    addr = row.get("recipient_email") or row.get("email_to") or ""
                    if addr.strip().lower() not in own:
                        continue  # e.g. a guardian's copy of a minor's email
                elif src.key == "audit_logs":
                    if row.get("user_id") != user.id:
                        # Someone else acted on your account: their IP/browser aren't yours
                        row["ip_address"] = None
                        row["user_agent"] = None
                        row["performed_by"] = ANOTHER_USER if row.get("user_id") else "system"
                    else:
                        row["performed_by"] = "you"
                    row["details"] = _redact_others(row.get("details"), own)
                elif src.key == "guardian_consents":
                    if row.get("guardian_user_id") != user.id:
                        row["ip_address"] = None  # the guardian's signature details
                        row["user_agent"] = None
                    row["your_role"] = "guardian" if row.get("guardian_user_id") == user.id else "participant"
                if "event_id" in row:
                    row["event_name"] = event_names.get(row["event_id"])
                for c in src.subject_columns:
                    if c not in src.export_columns:
                        row.pop(c, None)
                out.append({k: _plain(v) for k, v in row.items()})
            data[src.key] = out

        # Relationship names only (never the other person's contact details)
        profile = data["users"][0] if data.get("users") else {}
        if user.role_id:
            role = await self.session.get(Role, user.role_id)
            profile["role"] = role.name if role else None
        if user.sponsor_id:
            sponsor = await self.session.get(User, user.sponsor_id)
            profile["referred_by"] = f"{sponsor.first_name} {sponsor.last_name}" if sponsor else None
        if user.guardian_user_id:
            guardian = await self.session.get(User, user.guardian_user_id)
            profile["parent_or_guardian"] = f"{guardian.first_name} {guardian.last_name}" if guardian else None
        return data

    # --------------------------------------------------------------- build

    async def _certificate_pdfs(self, data: dict) -> dict[str, bytes]:
        keys = await self.session.execute(
            select(self._cpe_table().c.certificate_number, self._cpe_table().c.pdf_storage_key).where(
                self._cpe_table().c.certificate_number.in_(
                    [c["certificate_number"] for c in data.get("cpe_certificates", [])]
                ),
                self._cpe_table().c.pdf_storage_key.isnot(None),
            )
        )
        pdfs: dict[str, bytes] = {}
        rows = keys.all()
        if not rows:
            return pdfs
        import asyncio
        from app.utils.r2_client import R2Client
        client = R2Client.from_settings()
        for number, key in rows:
            content = await asyncio.to_thread(client.get_object, key)
            if content:
                pdfs[f"certificates/{number}.pdf"] = content
            else:
                logger.warning("Export: certificate PDF unavailable for %s", number)
        return pdfs

    @staticmethod
    def _cpe_table():
        from app.models.cpe_certificate import CPECertificate
        return CPECertificate.__table__

    async def export_user(self, user_id: int, link_expiry_days: Optional[int] = None) -> tuple[str, bytes]:
        """Build the ZIP. Returns (filename, bytes). Raises LookupError if no such user."""
        user = await self.session.get(User, user_id)
        if user is None:
            raise LookupError("user not found")
        now = datetime.now(timezone.utc)
        data = await self.collect(user)
        from app.services.invite_suppression_service import InviteSuppressionService
        suppressed = await InviteSuppressionService(self.session).is_suppressed(user.email)
        pdfs = await self._certificate_pdfs(data)

        payload = {"generated_at": now.isoformat(), "data": data}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", self._readme(now, suppressed, link_expiry_days, len(pdfs)))
            z.writestr("data.json", json.dumps(payload, indent=2, ensure_ascii=False))
            z.writestr("summary.html", self._summary_html(now, data))
            for name, content in pdfs.items():
                z.writestr(name, content)
        return f"cyberx-red-team-data-{now.date().isoformat()}.zip", buf.getvalue()

    def _readme(self, now: datetime, suppressed: bool, link_days: Optional[int], pdf_count: int) -> str:
        contact = self.settings.PRIVACY_CONTACT_EMAIL
        lines = [
            "CyberX Red Team: a copy of the information we hold about you",
            f"Generated {now.strftime('%B %d, %Y at %H:%M UTC').replace(' 0', ' ')}",
            "",
            "Files",
            "  data.json      everything below, machine-readable (one section per source,",
            "                 timestamps in ISO 8601, UTC)",
            "  summary.html   the same information as tables you can open in a browser",
        ]
        if pdf_count:
            lines.append("  certificates/  your CPE certificate PDFs")
        lines += [
            "",
            "What's included",
            "  Your account and contact details, invitations and registrations (including",
            "  any reason you gave for declining), privacy choices, sign-in sessions,",
            "  security log entries about you, email delivery records, network access and",
            "  exercise systems assigned to you, TLS and CPE certificates, actions assigned",
            "  to you, and parent/guardian consent records where they apply.",
            "",
            "What's left out, and why",
            "  - Secrets: passwords (we only store a one-way hash), your event-service",
            "    password, keys, tokens and confirmation codes. They're security",
            "    credentials, not information about you.",
            "  - Other people's information: we include the name of your referrer and of",
            "    a parent or guardian, but not their contact details. Where someone else",
            "    acted on your account, their IP address and browser aren't included, and",
            "    other people's names or emails in log entries read \"another user\".",
            "  - Internal sync queues for your event-service account (they hold encrypted",
            "    credentials).",
            "  - Notes staff wrote for running the event, and the names of staff who",
            "    issued or revoked certificates.",
        ]
        if suppressed:
            lines += [
                "",
                "Do-not-invite list",
                "  You asked not to be invited again. We keep only a scrambled (hashed) form",
                "  of your email address to block future invitations; it can't be turned back",
                "  into your address. Ask us if you'd like it removed.",
            ]
        if link_days:
            lines += ["", f"This download link stops working {link_days} days after it was sent."]
        lines += [
            "",
            f"Questions, corrections or requests: {contact}",
            f"Privacy Policy: {self.settings.PRIVACY_POLICY_URL}",
            "",
        ]
        return "\n".join(lines)

    def _summary_html(self, now: datetime, data: dict) -> str:
        esc = html.escape
        parts = [
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">",
            "<title>Your CyberX Red Team data</title>",
            "<style>body{font-family:-apple-system,Segoe UI,sans-serif;margin:24px;color:#1e293b}"
            "h1{font-size:22px}h2{font-size:17px;margin-top:28px}table{border-collapse:collapse;"
            "width:100%;font-size:13px}th,td{border:1px solid #e5e7eb;padding:4px 6px;text-align:left;"
            "vertical-align:top}th{background:#f8fafc}p.none{color:#64748b}</style></head><body>",
            "<h1>The information CyberX Red Team holds about you</h1>",
            f"<p>Generated {esc(now.strftime('%B %d, %Y %H:%M UTC'))}. See README.txt for what's included and left out.</p>",
        ]
        for key, rows in data.items():
            parts.append(f"<h2>{esc(SECTION_TITLES.get(key, key))}</h2>")
            if not rows:
                parts.append("<p class=\"none\">Nothing recorded.</p>")
                continue
            if key == "users":
                parts.append("<table>")
                for k, v in rows[0].items():
                    parts.append(f"<tr><th>{esc(k)}</th><td>{esc('' if v is None else str(v))}</td></tr>")
                parts.append("</table>")
                continue
            cols = list(rows[0].keys())
            parts.append("<table><tr>" + "".join(f"<th>{esc(c)}</th>" for c in cols) + "</tr>")
            for row in rows:
                cells = []
                for c in cols:
                    v = row.get(c)
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v, ensure_ascii=False)
                    cells.append(f"<td>{esc('' if v is None else str(v))}</td>")
                parts.append("<tr>" + "".join(cells) + "</tr>")
            parts.append("</table>")
        parts.append("</body></html>")
        return "".join(parts)


# ------------------------------------------------------------------ delivery

def email_delivery_available() -> bool:
    """Emailed links store the ZIP in R2. Not on staging (its bucket is production's)."""
    from app.utils.external_stubs import externals_stubbed
    st = get_settings()
    configured = all([st.R2_ACCOUNT_ID, st.R2_ACCESS_KEY_ID, st.R2_SECRET_ACCESS_KEY, st.R2_BUCKET])
    return configured and not externals_stubbed()


async def email_export_link(session: AsyncSession, user: User, filename: str, blob: bytes) -> None:
    """Store the ZIP in R2 and email a time-limited link to the address on file only."""
    import asyncio
    from app.services.download_service import DownloadService
    from app.services.email_queue_service import EmailQueueService
    from app.utils.r2_client import R2Client
    st = get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{st.DATA_EXPORT_R2_PREFIX.rstrip('/')}/{user.id}/{stamp}-{filename}"
    if not await asyncio.to_thread(R2Client.from_settings().put_object, key, blob, "application/zip"):
        raise RuntimeError("could not store the export")
    days = st.DATA_EXPORT_LINK_EXPIRY_DAYS
    url = DownloadService().generate_link(key, expires_in=days * 86400)
    await EmailQueueService(session).enqueue_email(
        user_id=user.id, template_name="data_export_ready", priority=2, force=True,
        allow_duplicates=True,
        custom_vars={
            "first_name": user.first_name, "download_url": url, "expiry_days": str(days),
            "contact_email": st.PRIVACY_CONTACT_EMAIL, "privacy_policy_url": st.PRIVACY_POLICY_URL,
        },
    )


async def recent_export_exists(session: AsyncSession, user_id: int, hours: int) -> bool:
    """Was an export made for this person in the last `hours` (rate limit)?"""
    from datetime import timedelta
    from sqlalchemy import func
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    n = (await session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "DATA_EXPORT_CREATED",
            AuditLog.resource_type == "USER",
            AuditLog.resource_id == user_id,
            AuditLog.created_at >= since,
        )
    )).scalar()
    return bool(n)


def zip_response(filename: str, blob: bytes):
    from fastapi.responses import Response
    return Response(
        content=blob, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
