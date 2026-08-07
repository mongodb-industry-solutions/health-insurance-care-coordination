"""Pydantic models for the notifications domain."""

from pydantic import BaseModel, Field
from typing import Optional, List


class Notification(BaseModel):
    notification_id: str = Field(alias="_id")
    # Stored camelCase (uniform with the five business objects); snake_case here
    # because these are Python attributes.
    member_id: str = Field(alias="memberId")
    trace_id: Optional[str] = Field(default=None, alias="traceId")
    status: str
    message: str
    created_at: str = Field(alias="createdAt")
    read: bool = False

    class Config:
        populate_by_name = True


class NotificationsListResponse(BaseModel):
    member_id: str
    count: int
    notifications: List[Notification]
