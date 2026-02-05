"""
Stripe Checkout Tool - Creates payment sessions for deal closing.

Creates Stripe checkout sessions mapped to the negotiated deal_value.
The session includes lead_id in metadata for webhook reconciliation.
"""
from typing import Optional

import structlog

from config import settings

logger = structlog.get_logger()


class StripeCheckoutTool:
    """Create Stripe checkout sessions for deal payment."""

    async def create_session(
        self,
        lead_id: str,
        amount: float,
        description: str,
        customer_email: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> dict:
        """
        Create a Stripe Checkout Session.

        Args:
            lead_id: Lead UUID string for metadata tracking
            amount: Deal value in dollars (converted to cents internally)
            description: Line item description shown to customer
            customer_email: Pre-fill email on checkout page
            success_url: Redirect URL on successful payment
            cancel_url: Redirect URL if customer cancels

        Returns:
            dict with checkout_url, session_id (or error if unconfigured)
        """
        if not settings.stripe_secret_key:
            logger.warning("Stripe not configured — returning mock checkout")
            return {
                "checkout_url": None,
                "session_id": None,
                "mock": True,
                "error": "Stripe not configured. Set STRIPE_SECRET_KEY to enable payments.",
            }

        import stripe
        stripe.api_key = settings.stripe_secret_key

        amount_cents = int(float(amount) * 100)

        # Default URLs — in production, these should come from app config
        base_url = f"http://{settings.api_host}:{settings.api_port}"
        if settings.is_production:
            base_url = "https://sentinel-api.onrender.com"

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": description,
                        },
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }],
                mode="payment",
                customer_email=customer_email,
                success_url=success_url or f"{base_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=cancel_url or f"{base_url}/checkout/cancel?lead_id={lead_id}",
                metadata={
                    "lead_id": lead_id,
                    "source": "sentinel_discovery",
                },
            )

            logger.info(
                "Stripe checkout session created",
                lead_id=lead_id,
                session_id=session.id,
                amount_cents=amount_cents,
                checkout_url=session.url,
            )

            return {
                "checkout_url": session.url,
                "session_id": session.id,
                "mock": False,
            }

        except Exception as e:
            logger.error(
                "Stripe checkout creation failed",
                error=str(e),
                lead_id=lead_id,
                amount_cents=amount_cents,
            )
            return {
                "checkout_url": None,
                "session_id": None,
                "mock": False,
                "error": str(e),
            }
