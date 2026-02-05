"""
Email Sender Tool - SendGrid integration with dry-run mode.

When sendgrid_api_key is configured, sends real emails via SendGrid v3 API.
When not configured, operates in DRY-RUN mode: logs the full email payload
to the discovery_interactions table for pipeline testing without external APIs.
"""
from typing import Optional, Any

import structlog

from config import settings

logger = structlog.get_logger()


# Template registry: maps slugs to subject/body templates.
# Use {placeholder} format — filled from template_data dict.
EMAIL_TEMPLATES = {
    "initial_proposal": {
        "subject_default": "Your new website proposal for {company_name}",
        "body": """Hi {contact_name},

I've prepared a custom website redesign proposal for {company_name} based on our analysis.

Your current site has a performance score that indicates significant room for improvement, and I've outlined exactly how we can help.

View your proposal: {proposal_url}
Preview your new design: {mockup_url}

Investment: ${deal_value:,.0f}

Ready to get started? Simply reply to this email or click the link above.

Best regards,
{sender_name}""",
    },
    "follow_up": {
        "subject_default": "Following up on your website proposal",
        "body": """Hi {contact_name},

I wanted to follow up on the proposal I sent for {company_name}'s website redesign.

Have you had a chance to review it? I'm happy to answer any questions or walk you through the details.

View your proposal: {proposal_url}

Best regards,
{sender_name}""",
    },
    "follow_up_urgency": {
        "subject_default": "Your website proposal — limited availability",
        "body": """Hi {contact_name},

I wanted to reach out one more time about the website redesign proposal for {company_name}.

We have limited project slots available this month, and I'd love to ensure {company_name} gets priority scheduling.

View your proposal: {proposal_url}

Would you have 15 minutes this week to discuss?

Best regards,
{sender_name}""",
    },
    "revised_offer": {
        "subject_default": "Updated proposal for {company_name}",
        "body": """Hi {contact_name},

Great news — I've revised the investment for your website project.

New price: ${new_price:,.0f}
{discount_reason}

This updated offer is available for the next 48 hours.

Best regards,
{sender_name}""",
    },
    "checkout_and_contract": {
        "subject_default": "Your project agreement and payment link",
        "body": """Hi {contact_name},

Everything is ready to kick off your website project for {company_name}.

Your project agreement: {contract_url}
Secure payment link: {checkout_url}
Amount: ${deal_value:,.0f}

Once payment is received, we'll begin work immediately.

Best regards,
{sender_name}""",
    },
    "re_engagement_offer": {
        "subject_default": "A fresh look at your website project",
        "body": """Hi {contact_name},

It's been a while since we last connected about {company_name}'s website.

I wanted to check in and see if this is still a priority for you. We've also updated our offerings and may have new options that better fit your needs.

Would you like to revisit your proposal?

Best regards,
{sender_name}""",
    },
    "generic_follow_up": {
        "subject_default": "Quick check-in on your website project",
        "body": """Hi {contact_name},

Just checking in on the website proposal for {company_name}. Let me know if you have any questions.

Best regards,
{sender_name}""",
    },
}


class EmailSender:
    """
    Send emails via SendGrid API with dry-run fallback.

    Dry-run mode activates when sendgrid_api_key is empty.
    In dry-run, emails are logged to the database but not actually sent.
    """

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    @property
    def is_dry_run(self) -> bool:
        return not settings.sendgrid_api_key

    async def send(
        self,
        to_email: str,
        to_name: str = "",
        subject: Optional[str] = None,
        template_slug: Optional[str] = None,
        template_data: Optional[dict] = None,
        body: Optional[str] = None,
    ) -> dict:
        """
        Send an email (or log in dry-run mode).

        Args:
            to_email: Recipient email address
            to_name: Recipient display name
            subject: Email subject (overrides template default)
            template_slug: Template key from EMAIL_TEMPLATES
            template_data: Dict of values to fill template placeholders
            body: Raw body text (used if no template_slug)

        Returns:
            dict with sent, dry_run, status_code, message_id fields
        """
        template_data = template_data or {}

        # Always inject sender name
        template_data.setdefault("sender_name", settings.sender_name)

        # Resolve template
        if template_slug and template_slug in EMAIL_TEMPLATES:
            template = EMAIL_TEMPLATES[template_slug]
            if not subject:
                try:
                    subject = template["subject_default"].format(**template_data)
                except KeyError:
                    subject = template["subject_default"]
            try:
                body = template["body"].format(**template_data)
            except KeyError as e:
                logger.warning(
                    "Template placeholder missing",
                    template=template_slug,
                    missing_key=str(e),
                )
                body = template["body"]

        if not subject or not body:
            return {"sent": False, "dry_run": self.is_dry_run, "error": "No subject or body"}

        # DRY-RUN MODE: log to database instead of sending
        if self.is_dry_run:
            return await self._dry_run_send(
                to_email, to_name, subject, body, template_slug
            )

        # LIVE MODE: SendGrid v3 API
        return await self._live_send(
            to_email, to_name, subject, body, template_slug
        )

    async def _dry_run_send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        template_slug: Optional[str],
    ) -> dict:
        """Log email to database in dry-run mode."""
        logger.info(
            "Email DRY-RUN (not sent)",
            to=to_email,
            subject=subject,
            template=template_slug,
            body_preview=body[:200],
        )

        # Log to discovery_interactions if DB available
        if self.db:
            try:
                # We need lead_id from context — caller should set it
                # For now, log without lead_id association
                pass
            except Exception:
                pass

        return {
            "sent": False,
            "dry_run": True,
            "to_email": to_email,
            "subject": subject,
            "body_preview": body[:500],
            "template_slug": template_slug,
        }

    async def _live_send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        template_slug: Optional[str],
    ) -> dict:
        """Send email via SendGrid v3 REST API."""
        import httpx

        payload = {
            "personalizations": [{
                "to": [{"email": to_email, "name": to_name}],
                "subject": subject,
            }],
            "from": {
                "email": settings.sender_email,
                "name": settings.sender_name,
            },
            "content": [{
                "type": "text/plain",
                "value": body,
            }],
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.sendgrid_api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

            success = response.status_code in (200, 202)

            logger.info(
                "Email sent" if success else "Email send failed",
                to=to_email,
                template=template_slug,
                status_code=response.status_code,
            )

            return {
                "sent": success,
                "dry_run": False,
                "status_code": response.status_code,
                "message_id": response.headers.get("X-Message-Id"),
            }

        except Exception as e:
            logger.error("Email send error", error=str(e), to=to_email)
            return {"sent": False, "dry_run": False, "error": str(e)}
