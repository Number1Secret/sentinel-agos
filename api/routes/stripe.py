"""
Stripe Webhook Routes

Handles Stripe payment events for the Discovery room.
"""
import json

import stripe
import structlog
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse

from config import settings
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/stripe", tags=["Stripe"])


@router.post(
    "/webhook",
    summary="Stripe webhook handler",
    include_in_schema=False,
)
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.

    Processes checkout.session.completed events to:
    1. Update lead status to closed_won
    2. Update discovery_negotiations to paid/completed
    3. Push guardian handoff job to queue
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not settings.stripe_webhook_secret:
        logger.warning("Stripe webhook secret not configured, skipping verification")
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload",
            )
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload",
            )
        except stripe.error.SignatureVerificationError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature",
            )

    event_type = event.get("type", "")

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(event["data"]["object"])
    else:
        logger.debug("Unhandled Stripe event type", event_type=event_type)

    return JSONResponse(content={"status": "ok"})


async def _handle_checkout_completed(session: dict):
    """
    Handle a completed checkout session.

    Updates lead to closed_won and triggers guardian handoff.
    """
    metadata = session.get("metadata", {})
    lead_id = metadata.get("lead_id")

    if not lead_id:
        logger.warning(
            "Checkout session missing lead_id in metadata",
            session_id=session.get("id"),
        )
        return

    logger.info(
        "Processing checkout completion",
        lead_id=lead_id,
        session_id=session.get("id"),
        amount_total=session.get("amount_total"),
    )

    db = SupabaseService(use_admin=True)

    try:
        # 1. Update lead status to closed_won
        db.client.table("leads").update({
            "status": "closed_won",
            "current_room": "guardian",
            "status_changed_at": "now()",
        }).eq("id", lead_id).execute()

        # 2. Update discovery_negotiations
        db.client.table("discovery_negotiations").update({
            "negotiation_state": "paid",
            "sdr_state": "completed",
            "stripe_payment_intent_id": session.get("payment_intent"),
            "close_reason": "Stripe checkout completed",
        }).eq("lead_id", lead_id).execute()

        # 3. Log the interaction
        db.client.table("discovery_interactions").insert({
            "lead_id": lead_id,
            "interaction_type": "checkout_completed",
            "channel": "webhook",
            "response_data": {
                "session_id": session.get("id"),
                "payment_intent": session.get("payment_intent"),
                "amount_total": session.get("amount_total"),
                "currency": session.get("currency"),
                "customer_email": session.get("customer_details", {}).get("email"),
            },
        }).execute()

        # 4. Push to guardian queue for handoff
        import redis as redis_lib
        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)

        # Get deal value from negotiation
        neg_resp = db.client.table("discovery_negotiations").select(
            "current_price, contract_pdf_url"
        ).eq("lead_id", lead_id).single().execute()

        guardian_job = {
            "lead_id": lead_id,
            "trigger": "stripe_webhook",
            "deal_value": neg_resp.data.get("current_price") if neg_resp.data else None,
            "contract_url": neg_resp.data.get("contract_pdf_url") if neg_resp.data else None,
        }
        redis_client.rpush("guardian_queue", json.dumps(guardian_job))

        logger.info(
            "Checkout completed — lead closed_won, guardian handoff queued",
            lead_id=lead_id,
        )

    except Exception as e:
        logger.error(
            "Failed to process checkout completion",
            lead_id=lead_id,
            error=str(e),
            exc_info=True,
        )
