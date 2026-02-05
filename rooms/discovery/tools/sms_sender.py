"""
SMS Sender Tool - Twilio integration with dry-run mode.

When twilio_account_sid is configured, sends real SMS via Twilio REST API.
When not configured, operates in DRY-RUN mode: logs the full SMS payload
for pipeline testing without external APIs.
"""
from typing import Optional, Any

import structlog

from config import settings

logger = structlog.get_logger()


# SMS template registry
SMS_TEMPLATES = {
    "sms_check_in": (
        "Hi {contact_name}, just checking in on the website proposal "
        "for {company_name}. Any questions? Reply here or view: {proposal_url}"
    ),
    "sms_urgency": (
        "Hi {contact_name}, your website proposal for {company_name} "
        "expires soon. Lock in your spot: {proposal_url}"
    ),
    "sms_payment_reminder": (
        "Hi {contact_name}, your project agreement is ready. "
        "Complete payment here: {checkout_url}"
    ),
}


class SmsSender:
    """
    Send SMS via Twilio API with dry-run fallback.

    Dry-run mode activates when twilio_account_sid is empty.
    In dry-run, SMS payloads are logged but not actually sent.
    """

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    @property
    def is_dry_run(self) -> bool:
        return not settings.twilio_account_sid

    async def send(
        self,
        to_phone: str,
        message: Optional[str] = None,
        template_slug: Optional[str] = None,
        template_data: Optional[dict] = None,
    ) -> dict:
        """
        Send an SMS (or log in dry-run mode).

        Args:
            to_phone: Recipient phone number (E.164 format)
            message: Raw message text
            template_slug: Template key from SMS_TEMPLATES
            template_data: Dict of values to fill template placeholders

        Returns:
            dict with sent, dry_run, sid fields
        """
        template_data = template_data or {}

        # Resolve template
        if template_slug and template_slug in SMS_TEMPLATES:
            template = SMS_TEMPLATES[template_slug]
            try:
                message = template.format(**template_data)
            except KeyError as e:
                logger.warning(
                    "SMS template placeholder missing",
                    template=template_slug,
                    missing_key=str(e),
                )
                message = template

        if not message:
            return {"sent": False, "dry_run": self.is_dry_run, "error": "No message body"}

        if not to_phone:
            return {"sent": False, "dry_run": self.is_dry_run, "error": "No phone number"}

        # DRY-RUN MODE
        if self.is_dry_run:
            return await self._dry_run_send(to_phone, message, template_slug)

        # LIVE MODE: Twilio REST API
        return await self._live_send(to_phone, message, template_slug)

    async def _dry_run_send(
        self,
        to_phone: str,
        message: str,
        template_slug: Optional[str],
    ) -> dict:
        """Log SMS to console/database in dry-run mode."""
        logger.info(
            "SMS DRY-RUN (not sent)",
            to=to_phone,
            template=template_slug,
            message_preview=message[:160],
        )

        return {
            "sent": False,
            "dry_run": True,
            "to_phone": to_phone,
            "message_preview": message[:160],
            "template_slug": template_slug,
        }

    async def _live_send(
        self,
        to_phone: str,
        message: str,
        template_slug: Optional[str],
    ) -> dict:
        """Send SMS via Twilio REST API."""
        import httpx
        from base64 import b64encode

        account_sid = settings.twilio_account_sid
        auth_token = settings.twilio_auth_token
        from_number = settings.twilio_phone_number

        # Basic auth header
        credentials = b64encode(f"{account_sid}:{auth_token}".encode()).decode()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                    data={
                        "To": to_phone,
                        "From": from_number,
                        "Body": message,
                    },
                    headers={
                        "Authorization": f"Basic {credentials}",
                    },
                    timeout=30.0,
                )

            if response.status_code == 201:
                data = response.json()
                logger.info(
                    "SMS sent",
                    to=to_phone,
                    sid=data.get("sid"),
                    template=template_slug,
                )
                return {
                    "sent": True,
                    "dry_run": False,
                    "sid": data.get("sid"),
                    "status": data.get("status"),
                }
            else:
                logger.error(
                    "SMS send failed",
                    to=to_phone,
                    status_code=response.status_code,
                    body=response.text[:500],
                )
                return {
                    "sent": False,
                    "dry_run": False,
                    "status_code": response.status_code,
                    "error": response.text[:500],
                }

        except Exception as e:
            logger.error("SMS send error", error=str(e), to=to_phone)
            return {"sent": False, "dry_run": False, "error": str(e)}
