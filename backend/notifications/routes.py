"""API routes for member notifications."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import NotificationService
from .models import Notification, NotificationsListResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def get_notification_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> NotificationService:
    return NotificationService(connector)


@router.post("/notify", response_model=Notification)
async def notify_member(
    member_id: str,
    service: NotificationService = Depends(get_notification_service),
):
    """Phase 3, step 3: notify the member about their latest authorization decision.

    Inserts a plain-language notification (what the change stream surfaces) and
    logs `member notified`.
    """
    try:
        return service.notify_member(member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/member/{member_id}", response_model=NotificationsListResponse)
async def get_member_notifications(
    member_id: str,
    service: NotificationService = Depends(get_notification_service),
):
    """List a member's notifications (chronological)."""
    notifications = service.get_member_notifications(member_id)
    return {
        "member_id": member_id,
        "count": len(notifications),
        "notifications": notifications,
    }
