"""Business logic for member notifications (Phase 3, step 3)."""

import uuid
from datetime import datetime, timezone

from db.mdb import get_connector
from audit.repository import AuditRepository
from members.repository import MemberRepository
from .repository import NotificationRepository


class NotificationService:
    """Composes and persists member-facing notifications about authorization
    outcomes. Reads the decision (the prior-auth trace in the Audit Log) and the
    member's name, then writes a plain-language notification."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = NotificationRepository(connector)
        self.audit_repo = AuditRepository(connector)
        self.member_repo = MemberRepository(connector)

    def notify_member(self, member_id: str) -> dict:
        """Phase 3, step 3 / 3a: notify the member about their latest decision.

        Reads the member's most recent prior-auth trace (status + review) and name,
        composes a plain-language message, and inserts a notification (the change
        stream a frontend watches).

        A case routed to a human is NOT final, so the member is told it is under
        review — not approved/denied — until the physician closes it (Phase 3a).
        Raises ValueError if the member has no trace yet.
        """
        traces = self.audit_repo.find_by_member(member_id)
        if not traces:
            raise ValueError(f"No authorization to notify for member {member_id}")
        trace = max(traces, key=lambda t: t.get("createdAt", ""))

        member = self.member_repo.get_by_key(member_id) or {}
        name = member.get("firstName") or "Member"
        service = trace.get("requested_service", "the requested treatment")
        status = trace.get("status", "pending")
        review = trace.get("review") or {}
        # "Under review" only while routed AND not yet closed by a human. Once the
        # medical director closes it, routedToHuman stays true but closedBy is set —
        # that is a final decision, not a pending review.
        pending_human = bool(review.get("routedToHuman")) and not review.get("closedBy")
        human_closed = bool(review.get("closedBy"))

        if pending_human:
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
        elif status == "denied" and human_closed:
            message = (
                f"{name}, after review by a medical director, {service} could not be "
                "approved at this time. Please contact member services to discuss "
                "next steps, including your right to appeal."
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
            "memberId": member_id,
            "traceId": trace["traceId"],
            "status": status,
            "message": message,
            "createdAt": now,
            "read": False,
        }
        self.repository.upsert(notification)
        return notification

    def get_member_notifications(self, member_id: str) -> list:
        return self.repository.find_by_member(member_id)
