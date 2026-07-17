"""Pydantic models for audit domain."""

from pydantic import BaseModel, Field
from typing import Optional, List


class AuditLogEntry(BaseModel):
    log_id: str = Field(alias="_id")
    member_id: str
    agent: str
    action: str
    timestamp: str
    fields_accessed: List[str]
    related_authorization: Optional[str] = None
    related_note: Optional[str] = None
    related_medication: Optional[str] = None
    related_guideline: Optional[str] = None

    class Config:
        populate_by_name = True


class LogActionResponse(BaseModel):
    status: str
    member_id: str
    action: str


class MemberAuditTrailResponse(BaseModel):
    member_id: str
    entry_count: int
    entries: List[AuditLogEntry]
