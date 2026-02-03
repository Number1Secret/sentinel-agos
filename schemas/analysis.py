"""
Pydantic models for users, webhooks, and other entities.
"""
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class User(BaseModel):
    """User profile."""
    id: UUID
    email: str
    fullName: Optional[str] = None
    companyName: Optional[str] = None
    plan: Literal["free", "starter", "pro"] = "free"
    auditsRemaining: int = 5
    createdAt: datetime

    class Config:
        from_attributes = True


class WebhookCreate(BaseModel):
    """Request body for creating a webhook."""
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    events: list[Literal["audit.completed", "audit.failed"]] = Field(
        ...,
        min_length=1,
        description="Events to trigger webhook"
    )
    secret: Optional[str] = Field(
        default=None,
        description="HMAC secret for signature verification"
    )


class WebhookResponse(BaseModel):
    """Webhook response."""
    id: UUID
    url: str
    events: list[str]
    active: bool = True
    createdAt: datetime

    class Config:
        from_attributes = True


class WebhookPayload(BaseModel):
    """Payload sent to webhook endpoints."""
    event: str
    timestamp: datetime
    data: dict


class AuditListResponse(BaseModel):
    """Response for list audits endpoint."""
    audits: list
    total: int
    hasMore: bool


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    details: Optional[dict] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    version: str = "0.1.0"


class MagicLinkRequest(BaseModel):
    """Request for magic link login."""
    email: str = Field(..., description="User email address")


class MagicLinkResponse(BaseModel):
    """Response for magic link request."""
    message: str = "Check your email for login link"
