"""
Registry of where a person's data lives.

One list, used by both personal-data deletion (the snapshot scrubber) and
personal-data export, so a table can't be covered by one and forgotten in
the other. tests/unit/test_personal_data_registry.py fails if a model gains a
person-identifying column that isn't declared here.

Column roles, per source:
  subject_columns    value == users.id means the row is about this person
  email_columns      copies of this person's email ("snapshot survives deletion")
  name_columns       copies of this person's name
  json_columns       JSON blobs that may embed this person's email/name
  extra_scrub        other per-person values cleared on deletion (column -> value)
  other_person_columns  columns holding a *different* person's identity on this
                     row (referrer, creator, issuer). Never exported; when that
                     other person is deleted, FK columns go NULL via ondelete and
                     email copies listed in other_person_email_columns are cleared.

on_delete:
  "delete"  rows are removed with the person
  "scrub"   rows are kept (counts, security history) but this person's copies
            are removed
  "keep"    rows are kept as-is; only the FK goes NULL (no identifying copies)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.audit_log import AuditLog, EmailEvent, VPNRequest
from app.models.cpe_certificate import CPECertificate
from app.models.email_queue import EmailQueue
from app.models.email_template import EmailTemplate
from app.models.email_workflow import EmailWorkflow
from app.models.event import EventParticipation
from app.models.guardian_consent import GuardianConsent
from app.models.instance import Instance
from app.models.instance_template import InstanceTemplate
from app.models.agent_task import AgentTask
from app.models.participant_action import ParticipantAction
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.redirector import Redirector
from app.models.session import Session
from app.models.tls_certificate import CAChain, TLSCertificate
from app.models.user import User
from app.models.vpn import VPNCredential
from app.models.vpn_delete_job import VPNDeleteJob
from app.models.vpn_import_job import VPNImportJob

# Replacement for NOT NULL text columns that held the person's email.
DELETED_PLACEHOLDER = "[deleted]"


@dataclass(frozen=True)
class PersonalDataSource:
    key: str
    model: Any
    on_delete: str  # "delete" | "scrub" | "keep"
    subject_columns: tuple[str, ...] = ()
    email_columns: tuple[str, ...] = ()
    name_columns: tuple[str, ...] = ()
    json_columns: tuple[str, ...] = ()
    extra_scrub: dict[str, Any] = field(default_factory=dict)
    other_person_columns: tuple[str, ...] = ()
    other_person_email_columns: tuple[str, ...] = ()
    # Columns that look identifying but aren't about a person (documented, so the
    # completeness test knows they were considered).
    not_personal_columns: tuple[str, ...] = ()
    # Export (access requests): an explicit allowlist. Anything not listed is never
    # exported (secrets, other people's data, internal fields). An empty tuple with
    # export_note means the source is deliberately left out; the note says why.
    export_columns: tuple[str, ...] = ()
    export_note: str = ""
    notes: str = ""

    @property
    def table(self) -> str:
        return self.model.__tablename__

    def declared_columns(self) -> set[str]:
        return set(
            self.subject_columns + self.email_columns + self.name_columns
            + self.json_columns + tuple(self.extra_scrub) + self.other_person_columns
            + self.other_person_email_columns + self.not_personal_columns
        )

    def scrub_values(self) -> dict[str, Any]:
        """Column -> replacement applied to this person's kept rows on deletion."""
        values: dict[str, Any] = {}
        for col in self.email_columns + self.name_columns:
            nullable = self.model.__table__.c[col].nullable
            values[col] = None if nullable else DELETED_PLACEHOLDER
        values.update(self.extra_scrub)
        return values


REGISTRY: tuple[PersonalDataSource, ...] = (
    PersonalDataSource(
        key="users",
        model=User,
        on_delete="delete",
        export_columns=('email', 'first_name', 'last_name', 'country', 'confirmed', 'confirmed_at', 'decline_reason', 'email_status', 'terms_accepted', 'terms_accepted_at', 'terms_version', 'pandas_username', 'discord_username', 'snowflake_id', 'confirmed_in_person', 'is_active', 'future_contact_consent', 'future_contact_consent_at', 'age_attestation', 'age_attested_at', 'birth_year_month', 'adult_on', 'guardian_link_status', 'invite_sent', 'last_invite_sent', 'reminder_1_sent_at', 'reminder_2_sent_at', 'reminder_3_sent_at', 'password_email_sent', 'survey_email_sent', 'last_login_at', 'retention_hold_until', 'deletion_warning_sent_at', 'theme_preference', 'created_at', 'updated_at'),
        subject_columns=("id",),
        other_person_columns=("sponsor_id", "guardian_user_id", "guardian_link_status"),
        # Legacy copy of the referrer's email, and the guardian email a minor typed.
        other_person_email_columns=("sponsor_email", "guardian_email_pending"),
        notes=(
            "The account itself. sponsor_* identify the referrer and guardian_* the "
            "parent/guardian, not this person."
        ),
    ),
    PersonalDataSource(
        key="event_participations",
        model=EventParticipation,
        on_delete="delete",
        export_columns=('event_id', 'status', 'invited_at', 'responded_at', 'terms_accepted_at', 'terms_version_accepted', 'confirmed_at', 'declined_at', 'declined_reason', 'discord_invite_generated_at', 'discord_invite_used_at', 'discord_verified_at', 'activated_at', 'suspended_at', 'created_at'),
        subject_columns=("user_id",),
        other_person_columns=("invited_by_user_id",),
        notes="Invitation/registration per event, including any decline reason.",
    ),
    PersonalDataSource(
        key="sessions",
        model=Session,
        on_delete="delete",
        export_columns=('created_at', 'expires_at', 'ip_address', 'user_agent', 'is_active'),
        subject_columns=("user_id",),
    ),
    PersonalDataSource(
        key="password_sync_queue",
        model=PasswordSyncQueue,
        on_delete="delete",
        export_note="Internal queue for syncing your event-service account; it holds encrypted credentials, so it isn't included.",
        subject_columns=("user_id",),
        notes=(
            "Event-service account sync. Synced/pending rows for the person are removed; "
            "delete_participant() then queues one DELETE_USER entry (username only) so the "
            "event-service account is removed too. Synced rows are purged after the log period."
        ),
    ),
    PersonalDataSource(
        key="audit_logs",
        model=AuditLog,
        on_delete="scrub",
        export_columns=('created_at', 'action', 'resource_type', 'details', 'ip_address', 'user_agent'),
        subject_columns=("user_id",),
        email_columns=("user_email",),
        name_columns=("user_name",),
        json_columns=("details",),
        notes=(
            "Security log. Rows the person performed (user_id) or that target their "
            "account (resource_type USER + resource_id) are kept for security until the "
            "log period ends, with the person's email/name removed."
        ),
    ),
    PersonalDataSource(
        key="email_events",
        model=EmailEvent,
        on_delete="scrub",
        export_columns=('created_at', 'event_type', 'template_name', 'email_to'),
        subject_columns=("user_id",),
        email_columns=("email_to",),
        extra_scrub={"payload": None},
        notes="Delivery records; the raw provider payload (contains the address) is dropped.",
    ),
    PersonalDataSource(
        key="email_queue",
        model=EmailQueue,
        on_delete="scrub",
        export_columns=('created_at', 'template_name', 'status', 'sent_at', 'recipient_email'),
        subject_columns=("user_id",),
        email_columns=("recipient_email",),
        name_columns=("recipient_name",),
        extra_scrub={"custom_vars": None},
    ),
    PersonalDataSource(
        key="vpn_requests",
        model=VPNRequest,
        on_delete="scrub",
        export_columns=('requested_at', 'processed_at', 'status', 'key_type', 'request_source'),
        subject_columns=("user_id",),
        email_columns=("user_email",),
        name_columns=("user_name",),
    ),
    PersonalDataSource(
        key="vpn_credentials",
        model=VPNCredential,
        on_delete="scrub",
        export_columns=('interface_ip', 'ipv4_address', 'ipv6_local', 'ipv6_global', 'endpoint', 'key_type', 'assignment_type', 'assigned_at', 'is_active', 'created_at'),
        subject_columns=("assigned_to_user_id",),
        email_columns=("assigned_to_email",),
        name_columns=("assigned_to_name",),
        extra_scrub={"assigned_to_username": None},
        not_personal_columns=("assigned_to_instance_id",),
        notes="Network access. Kept (never recycled) until event close-out deletes it.",
    ),
    PersonalDataSource(
        key="instances",
        model=Instance,
        on_delete="scrub",
        export_columns=('name', 'provider', 'provider_region', 'provider_size_slug', 'status', 'ip_address', 'vpn_ip', 'visibility', 'event_id', 'created_at', 'deleted_at'),
        subject_columns=("assigned_to_user_id",),
        email_columns=("assigned_to_email",),
        name_columns=("assigned_to_name",),
        other_person_columns=("created_by_user_id",),
    ),
    PersonalDataSource(
        key="tls_certificates",
        model=TLSCertificate,
        on_delete="scrub",
        export_columns=('event_id', 'common_name', 'sans', 'is_wildcard', 'serial_number', 'fingerprint', 'status', 'issued_at', 'expires_at', 'revoked_at', 'revocation_reason'),
        subject_columns=("user_id",),
        email_columns=("user_email",),
        name_columns=("user_name",),
        not_personal_columns=("common_name",),  # a domain name, not a person
    ),
    PersonalDataSource(
        key="participant_actions",
        model=ParticipantAction,
        on_delete="scrub",
        export_columns=('event_id', 'action_type', 'title', 'description', 'status', 'deadline', 'responded_at', 'response_note', 'created_at'),
        subject_columns=("user_id",),
        email_columns=("user_email",),
        name_columns=("user_name",),
        extra_scrub={"response_note": None},
        other_person_columns=("created_by_id",),
    ),
    PersonalDataSource(
        key="cpe_certificates",
        model=CPECertificate,
        on_delete="scrub",
        export_columns=('event_id', 'certificate_number', 'user_name', 'cpe_hours', 'status', 'has_nextcloud_login', 'has_powerdns_login', 'has_vpn_assigned', 'pdf_generated_at', 'created_at', 'revoked_at', 'revocation_reason'),
        subject_columns=("user_id",),
        # Only the email goes: the printed name stays so the certificate can still
        # be verified (Privacy Policy keeps CPE records for the life of the portal).
        email_columns=("user_email",),
        not_personal_columns=("user_name",),
        other_person_columns=(
            "issued_by_user_id", "issued_by_name", "revoked_by_user_id", "revoked_by_name",
        ),
        notes="user_name is deliberately kept for certificate verification.",
    ),
    PersonalDataSource(
        key="guardian_consents",
        model=GuardianConsent,
        on_delete="scrub",
        export_columns=('event_id', 'relationship', 'guardian_name_typed', 'consent_text_version', 'terms_version', 'optional_email_consent', 'consented_at', 'withdrawn_at', 'ip_address', 'user_agent'),
        # About both people: the minor (subject of the consent) and the guardian
        # (who signed it). Rows go with the minor's account (FK cascade); if the
        # guardian is deleted the consent is void and their signature details go.
        subject_columns=("minor_user_id", "guardian_user_id"),
        name_columns=("guardian_name_typed",),
        extra_scrub={"ip_address": None, "user_agent": None},
        notes="Per-event written consent for a participant under 18.",
    ),
    PersonalDataSource(
        key="redirectors",
        model=Redirector,
        on_delete="keep",
        export_columns=('name', 'current_ip', 'status', 'visibility', 'created_at', 'last_deployed_at'),
        subject_columns=("owner_id",),
        notes="Infrastructure the person owned; no identity copies on the row.",
    ),
    # Staff-only references: the user here acted as creator/operator. Nothing about
    # them is exported as their personal data; FKs go NULL when they're deleted.
    PersonalDataSource(
        key="agent_tasks", model=AgentTask, on_delete="keep",
        other_person_columns=("created_by_user_id",),
    ),
    PersonalDataSource(
        key="ca_chains", model=CAChain, on_delete="keep",
        other_person_columns=("created_by_user_id",),
    ),
    PersonalDataSource(
        key="instance_templates", model=InstanceTemplate, on_delete="keep",
        other_person_columns=("created_by_user_id",),
    ),
    PersonalDataSource(
        key="email_templates", model=EmailTemplate, on_delete="keep",
        other_person_columns=("created_by_id",),
    ),
    PersonalDataSource(
        key="email_workflows", model=EmailWorkflow, on_delete="keep",
        other_person_columns=("created_by_id",),
    ),
    PersonalDataSource(
        key="vpn_import_jobs", model=VPNImportJob, on_delete="keep",
        other_person_columns=("created_by_user_id",),
    ),
    PersonalDataSource(
        key="vpn_delete_jobs", model=VPNDeleteJob, on_delete="keep",
        other_person_columns=("created_by_user_id",),
    ),
)


def get_source(key: str) -> Optional[PersonalDataSource]:
    return next((s for s in REGISTRY if s.key == key), None)
