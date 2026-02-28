"""Audit logging service for tracking user and admin actions."""
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog


class AuditService:
    """Service for logging audit events."""

    def __init__(self, session: AsyncSession):
        """Initialize audit service."""
        self.session = session

    async def log(
        self,
        action: str,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """
        Log an audit event.

        Args:
            action: Action performed (e.g., LOGIN, LOGOUT, USER_CREATE, USER_UPDATE, ROLE_CHANGE)
            user_id: ID of user who performed the action
            resource_type: Type of resource affected (e.g., USER, VPN, EMAIL)
            resource_id: ID of the affected resource
            details: Additional details as JSON
            ip_address: IP address of the request
            user_agent: User agent string

        Returns:
            Created AuditLog entry
        """
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

        self.session.add(audit_log)
        await self.session.commit()
        await self.session.refresh(audit_log)

        return audit_log

    async def log_login(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        details: Optional[dict] = None
    ) -> AuditLog:
        """Log a login attempt."""
        return await self.log(
            action="LOGIN_SUCCESS" if success else "LOGIN_FAILED",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details
        )

    async def log_logout(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log a logout event."""
        return await self.log(
            action="LOGOUT",
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_user_create(
        self,
        user_id: int,
        created_user_id: int,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log user creation."""
        return await self.log(
            action="USER_CREATE",
            user_id=user_id,
            resource_type="USER",
            resource_id=created_user_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_user_update(
        self,
        user_id: int,
        updated_user_id: int,
        changes: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log user update with field changes."""
        return await self.log(
            action="USER_UPDATE",
            user_id=user_id,
            resource_type="USER",
            resource_id=updated_user_id,
            details={"changes": changes},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_user_delete(
        self,
        user_id: int,
        deleted_user_id: int,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log user deletion."""
        return await self.log(
            action="USER_DELETE",
            user_id=user_id,
            resource_type="USER",
            resource_id=deleted_user_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_role_change(
        self,
        user_id: int,
        target_user_id: int,
        old_role: str,
        new_role: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log role change."""
        return await self.log(
            action="ROLE_CHANGE",
            user_id=user_id,
            resource_type="USER",
            resource_id=target_user_id,
            details={"old_role": old_role, "new_role": new_role},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_password_reset(
        self,
        user_id: int,
        target_user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log password reset by admin."""
        return await self.log(
            action="PASSWORD_RESET",
            user_id=user_id,
            resource_type="USER",
            resource_id=target_user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_password_change(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log self-service password change."""
        return await self.log(
            action="PASSWORD_CHANGE",
            user_id=user_id,
            resource_type="USER",
            resource_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_password_reset_request(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log password reset request."""
        return await self.log(
            action="PASSWORD_RESET_REQUEST",
            user_id=user_id,
            resource_type="USER",
            resource_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_password_reset_complete(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log successful password reset completion."""
        return await self.log(
            action="PASSWORD_RESET_COMPLETE",
            user_id=user_id,
            resource_type="USER",
            resource_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_bulk_action(
        self,
        user_id: int,
        action: str,
        affected_user_ids: list,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log bulk operations."""
        return await self.log(
            action=f"BULK_{action.upper()}",
            user_id=user_id,
            resource_type="USER",
            details={"affected_users": affected_user_ids, "count": len(affected_user_ids)},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_vpn_assignment(
        self,
        user_id: int,
        target_user_id: int,
        vpn_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log VPN credential assignment."""
        return await self.log(
            action="VPN_ASSIGN",
            user_id=user_id,
            resource_type="VPN",
            resource_id=vpn_id,
            details={"assigned_to_user_id": target_user_id},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_vpn_unassignment(
        self,
        user_id: int,
        vpn_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log VPN credential unassignment."""
        return await self.log(
            action="VPN_UNASSIGN",
            user_id=user_id,
            resource_type="VPN",
            resource_id=vpn_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_email_send(
        self,
        user_id: int,
        recipient_ids: list,
        template_name: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log email sending."""
        return await self.log(
            action="EMAIL_SEND",
            user_id=user_id,
            resource_type="EMAIL",
            details={
                "template": template_name,
                "recipients": recipient_ids,
                "count": len(recipient_ids)
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_participation_confirm(
        self,
        user_id: int,
        event_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log participation confirmation."""
        return await self.log(
            action="PARTICIPATION_CONFIRM",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_terms_acceptance(
        self,
        user_id: int,
        event_id: int,
        terms_version: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log terms of agreement acceptance."""
        return await self.log(
            action="TERMS_ACCEPT",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            details={"terms_version": terms_version},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_workflow_create(
        self,
        user_id: int,
        workflow_id: int,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log workflow creation."""
        return await self.log(
            action="WORKFLOW_CREATE",
            user_id=user_id,
            resource_type="WORKFLOW",
            resource_id=workflow_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_workflow_update(
        self,
        user_id: int,
        workflow_id: int,
        changes: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log workflow update with field changes."""
        return await self.log(
            action="WORKFLOW_UPDATE",
            user_id=user_id,
            resource_type="WORKFLOW",
            resource_id=workflow_id,
            details={"changes": changes},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_workflow_delete(
        self,
        user_id: int,
        workflow_id: int,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log workflow deletion."""
        return await self.log(
            action="WORKFLOW_DELETE",
            user_id=user_id,
            resource_type="WORKFLOW",
            resource_id=workflow_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_workflow_trigger(
        self,
        user_id: int,
        workflow_id: int,
        trigger_event: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log workflow trigger."""
        return await self.log(
            action="WORKFLOW_TRIGGER",
            user_id=user_id,
            resource_type="WORKFLOW",
            resource_id=workflow_id,
            details={
                "trigger_event": trigger_event,
                **(details or {})
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_event_create(
        self,
        user_id: int,
        event_id: int,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log event creation."""
        return await self.log(
            action="EVENT_CREATE",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_event_update(
        self,
        user_id: int,
        event_id: int,
        changes: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log event update with field changes."""
        return await self.log(
            action="EVENT_UPDATE",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            details={"changes": changes},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_event_activate(
        self,
        user_id: int,
        event_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log event activation."""
        return await self.log(
            action="EVENT_ACTIVATE",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            details={"action": "activate"},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_event_archive(
        self,
        user_id: int,
        event_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log event archival."""
        return await self.log(
            action="EVENT_ARCHIVE",
            user_id=user_id,
            resource_type="EVENT",
            resource_id=event_id,
            details={"action": "archive"},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_invitation_blocked(
        self,
        user_id: int,
        target_user_id: int,
        reason: str,
        event_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log when an invitation is blocked (e.g., by test mode)."""
        return await self.log(
            action="INVITATION_BLOCKED",
            user_id=user_id,
            resource_type="USER",
            resource_id=target_user_id,
            details={
                "reason": reason,
                "event_id": event_id
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_certificate_issue(
        self,
        user_id: int,
        target_user_id: int,
        certificate_id: int,
        event_id: int,
        certificate_number: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log CPE certificate issuance."""
        return await self.log(
            action="CERTIFICATE_ISSUE",
            user_id=user_id,
            resource_type="CERTIFICATE",
            resource_id=certificate_id,
            details={
                "target_user_id": target_user_id,
                "event_id": event_id,
                "certificate_number": certificate_number,
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_certificate_revoke(
        self,
        user_id: int,
        certificate_id: int,
        certificate_number: str,
        reason: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log CPE certificate revocation."""
        return await self.log(
            action="CERTIFICATE_REVOKE",
            user_id=user_id,
            resource_type="CERTIFICATE",
            resource_id=certificate_id,
            details={
                "certificate_number": certificate_number,
                "reason": reason,
            },
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_certificate_download(
        self,
        user_id: int,
        certificate_id: int,
        certificate_number: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log CPE certificate PDF download."""
        return await self.log(
            action="CERTIFICATE_DOWNLOAD",
            user_id=user_id,
            resource_type="CERTIFICATE",
            resource_id=certificate_id,
            details={"certificate_number": certificate_number},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_bulk_certificate_issue(
        self,
        user_id: int,
        event_id: int,
        count: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log bulk CPE certificate issuance."""
        return await self.log(
            action="BULK_CERTIFICATE_ISSUE",
            user_id=user_id,
            resource_type="CERTIFICATE",
            details={"event_id": event_id, "count": count},
            ip_address=ip_address,
            user_agent=user_agent
        )

    async def log_reminder_sent(
        self,
        user_id: int,
        target_user_id: int,
        stage: int,
        event_id: int,
        event_name: str,
        template_name: str,
        days_until_event: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Log when an invitation reminder is sent."""
        return await self.log(
            action=f"REMINDER_{stage}_SENT",
            user_id=target_user_id,  # The user receiving the reminder
            resource_type="EMAIL",
            resource_id=target_user_id,
            details={
                "event_id": event_id,
                "event_name": event_name,
                "template": template_name,
                "days_until_event": days_until_event,
                "stage": stage
            },
            ip_address=ip_address,
            user_agent=user_agent
        )
