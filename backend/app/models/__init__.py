"""SQLAlchemy models."""
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.models.session import Session
from app.models.audit_log import AuditLog, EmailEvent, VPNRequest
from app.models.event import Event, EventParticipation, ParticipationStatus
from app.models.email_template import EmailTemplate
from app.models.email_queue import EmailQueue, EmailBatchLog, EmailQueueStatus
from app.models.email_workflow import EmailWorkflow, WorkflowTriggerEvent
from app.models.app_setting import AppSetting
from app.models.cloud_init_template import CloudInitTemplate
from app.models.instance import Instance
from app.models.license import LicenseProduct, LicenseToken, LicenseSlot

__all__ = [
    "User",
    "UserRole",
    "VPNCredential",
    "Session",
    "AuditLog",
    "EmailEvent",
    "VPNRequest",
    "Event",
    "EventParticipation",
    "ParticipationStatus",
    "EmailTemplate",
    "EmailQueue",
    "EmailBatchLog",
    "EmailQueueStatus",
    "EmailWorkflow",
    "WorkflowTriggerEvent",
    "AppSetting",
    "CloudInitTemplate",
    "Instance",
    "LicenseProduct",
    "LicenseToken",
    "LicenseSlot",
]
