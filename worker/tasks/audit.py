"""
Audit processing task for the background worker.
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional
from uuid import UUID

import httpx
import structlog

from agents.scout import ScoutAgent
from services.supabase import SupabaseService
from config import settings

logger = structlog.get_logger()


async def process_audit_job(job_data: dict) -> dict:
    """
    Process a website audit job.

    Args:
        job_data: Job data from Redis queue containing:
            - audit_id: UUID of the audit record
            - url: URL to analyze
            - user_id: User who requested the audit
            - competitors: Optional list of competitor URLs
            - options: Audit options

    Returns:
        Audit results dict
    """
    audit_id = job_data["audit_id"]
    url = job_data["url"]
    user_id = job_data["user_id"]
    competitors = job_data.get("competitors", [])
    options = job_data.get("options", {})

    logger.info(
        "Processing audit job",
        audit_id=audit_id,
        url=url,
        user_id=user_id,
    )

    db = SupabaseService(use_admin=True)

    # Update status to processing
    await db.update_audit_status(UUID(audit_id), "processing")

    try:
        # Run Scout Agent analysis
        agent = ScoutAgent()
        results = await agent.analyze(
            url=url,
            competitors=competitors,
            options=options,
        )

        # Save results to database
        await db.save_audit_results(
            audit_id=UUID(audit_id),
            performance=results["performance"],
            seo=results["seo"],
            accessibility=results["accessibility"],
            brand=results["brand"],
            analysis=results["analysis"],
            screenshots=results["screenshots"],
            tokens_used=results["tokens_used"],
            cost_usd=results["cost_usd"],
            processing_time_ms=results["processing_time_ms"],
        )

        logger.info(
            "Audit job completed",
            audit_id=audit_id,
            processing_time_ms=results["processing_time_ms"],
        )

        # Fire webhooks
        await fire_webhooks(
            user_id=UUID(user_id),
            event="audit.completed",
            data={
                "audit_id": audit_id,
                "url": url,
                "status": "completed",
                "performance_score": results["performance"].get("score"),
                "completed_at": datetime.utcnow().isoformat(),
            }
        )

        return results

    except Exception as e:
        error_msg = str(e)
        logger.error(
            "Audit job failed",
            audit_id=audit_id,
            url=url,
            error=error_msg,
        )

        # Update status to failed
        await db.update_audit_status(UUID(audit_id), "failed", error_msg)

        # Fire failure webhook
        await fire_webhooks(
            user_id=UUID(user_id),
            event="audit.failed",
            data={
                "audit_id": audit_id,
                "url": url,
                "status": "failed",
                "error": error_msg,
                "failed_at": datetime.utcnow().isoformat(),
            }
        )

        raise


async def fire_webhooks(
    user_id: UUID,
    event: str,
    data: dict,
) -> None:
    """
    Fire webhooks for a specific event.

    Args:
        user_id: User ID to get webhooks for
        event: Event type (e.g., "audit.completed")
        data: Event data payload
    """
    db = SupabaseService(use_admin=True)

    try:
        webhooks = await db.get_webhooks_for_event(user_id, event)

        if not webhooks:
            return

        payload = {
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            for webhook in webhooks:
                try:
                    headers = {"Content-Type": "application/json"}

                    # Sign payload if secret is configured
                    if webhook.get("secret"):
                        signature = hmac.new(
                            webhook["secret"].encode(),
                            json.dumps(payload).encode(),
                            hashlib.sha256,
                        ).hexdigest()
                        headers["X-Webhook-Signature"] = f"sha256={signature}"

                    response = await client.post(
                        webhook["url"],
                        json=payload,
                        headers=headers,
                    )

                    logger.info(
                        "Webhook fired",
                        webhook_id=webhook["id"],
                        event=event,
                        status_code=response.status_code,
                    )

                except Exception as e:
                    logger.warning(
                        "Webhook delivery failed",
                        webhook_id=webhook["id"],
                        url=webhook["url"],
                        error=str(e),
                    )

    except Exception as e:
        logger.error("Failed to fire webhooks", user_id=str(user_id), error=str(e))
