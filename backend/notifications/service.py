"""Business logic for member notifications (Phase 3, step 3)."""

import uuid
from datetime import datetime, timezone

from db.mdb import get_connector
from authorizations.repository import AuthorizationRepository
from members.repository import MemberRepository
from audit.repository import AuditRepository
from .repository import NotificationRepository


class NotificationService:
    """Composes and persists member-facing notifications about authorization
    outcomes. Reads the decision (authorizations) and demographics (members),
    writes a plain-language notification, and audits it."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = NotificationRepository(connector)
        self.auth_repo = AuthorizationRepository(connector)
        self.member_repo = MemberRepository(connector)
        self.audit = AuditRepository(connector)

    def notify_member(self, member_id: str) -> dict:
        """Phase 3, step 3/3a/3b: notify the member about their latest decision.

        Reads the member's most recent authorization (status + reasoning) and
        demographics, composes a plain-language message, inserts a notification
        (the change stream a frontend watches), and logs `member notified`.

        A case routed to a human is NOT final, so the member is told it is under
        review — not approved/denied — until the physician closes it (Phase 3a).
        Raises ValueError if the member has no authorization yet.
        """
        auths = self.auth_repo.find_by_member(member_id)
        if not auths:
            raise ValueError(f"No authorization to notify for member {member_id}")
        auth = max(auths, key=lambda a: a.get("created_at", ""))

        member = self.member_repo.get_by_id(member_id) or {}
        name = member.get("demographics", {}).get("name", "Member")
        service = auth.get("requested_service", "the requested treatment")
        status = auth.get("status", "pending")
        routed = bool((auth.get("review") or {}).get("routed_to_human"))

        if routed:
            message = (
                f"{name}, your request for {service} is being reviewed by a medical "
                "director. We'll let you know as soon as a decision is made."
            )
        elif status == "approved":
            message = (
                f"Good news, {name} — your authorization for {service} has been "
                "approved. Your pharmacy has been notified and your prescription "
                "should be ready shortly."
            )
        elif status == "denied":
            message = (
                f"{name}, {service} could not be approved under your current "
                "coverage. Please contact member services to discuss your options."
            )
        else:
            message = f"{name}, we have an update on your request for {service}."

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        notification = {
            "_id": f"NOTIF-{uuid.uuid4().hex[:10]}",
            "member_id": member_id,
            "authorization_id": auth["_id"],
            "status": status,
            "message": message,
            "created_at": now,
            "read": False,
        }
        self.repository.upsert(notification)

        self.audit.record(
            member_id=member_id,
            agent="notification_service",
            action="member notified",
            fields_accessed=[
                "demographics",
                "authorizations.status",
                "authorizations.decision_trace.reasoning",
            ],
            related_authorization=auth["_id"],
        )
        return notification

    def get_member_notifications(self, member_id: str) -> list:
        return self.repository.find_by_member(member_id)
