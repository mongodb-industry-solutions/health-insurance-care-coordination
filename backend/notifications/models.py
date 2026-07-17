"""Pydantic models for the notifications domain."""

from pydantic import BaseModel, Field
from typing import Optional, List


class Notification(BaseModel):
    notification_id: str = Field(alias="_id")
    member_id: str
    authorization_id: Optional[str] = None
    status: str
    message: str
    created_at: str
    read: bool = False

    class Config:
        populate_by_name = True


class NotificationsListResponse(BaseModel):
    member_id: str
    count: int
    notifications: List[Notification]
