"""
Webhook management routes.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
import structlog

from api.dependencies import CurrentUser
from schemas.analysis import WebhookCreate, WebhookResponse, ErrorResponse
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register webhook for audit completion",
)
async def create_webhook(
    request: WebhookCreate,
    user: CurrentUser,
):
    """
    Register a webhook endpoint to receive notifications.

    Supported events:
    - `audit.completed`: Fired when an audit completes successfully
    - `audit.failed`: Fired when an audit fails

    Webhooks receive a POST request with JSON payload containing event data.
    If a secret is provided, the payload will be signed with HMAC-SHA256.
    """
    db = SupabaseService(use_admin=True)

    webhook = await db.create_webhook(
        user_id=user["id"],
        url=str(request.url),
        events=request.events,
        secret=request.secret,
    )

    logger.info(
        "Webhook created",
        webhook_id=webhook["id"],
        url=str(request.url),
        events=request.events,
    )

    return WebhookResponse(
        id=UUID(webhook["id"]),
        url=webhook["url"],
        events=webhook["events"],
        active=webhook["active"],
        createdAt=datetime.fromisoformat(webhook["created_at"].replace("Z", "+00:00")),
    )


@router.get(
    "",
    response_model=list[WebhookResponse],
    summary="List user's webhooks",
)
async def list_webhooks(user: CurrentUser):
    """List all webhooks registered by the authenticated user."""
    db = SupabaseService(use_admin=True)

    webhooks = await db.list_webhooks(user_id=user["id"])

    return [
        WebhookResponse(
            id=UUID(wh["id"]),
            url=wh["url"],
            events=wh["events"],
            active=wh["active"],
            createdAt=datetime.fromisoformat(wh["created_at"].replace("Z", "+00:00")),
        )
        for wh in webhooks
    ]


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Webhook not found"},
    },
    summary="Delete a webhook",
)
async def delete_webhook(
    webhook_id: UUID,
    user: CurrentUser,
):
    """Delete a webhook."""
    db = SupabaseService(use_admin=True)

    success = await db.delete_webhook(webhook_id, user_id=user["id"])

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )

    logger.info("Webhook deleted", webhook_id=str(webhook_id))

    return None
