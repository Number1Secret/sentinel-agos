"""
Discovery Room Tools.

- pricing_calculator: Dynamic pricing based on playbook rules
- proposal_generator: HTML-to-PDF proposal generation
- contract_generator: PDF contract generation with WeasyPrint
- stripe_checkout: Stripe checkout session creation
- email_sender: SendGrid email dispatch (with dry-run mode)
- sms_sender: Twilio SMS dispatch (with dry-run mode)
- memory_loader: Cross-room memory aggregation
- vlm_analyzer: Vision-Language Model mockup interaction analysis
"""
from rooms.discovery.tools.pricing_calculator import PricingCalculator
from rooms.discovery.tools.proposal_generator import ProposalGenerator
from rooms.discovery.tools.contract_generator import ContractGenerator
from rooms.discovery.tools.stripe_checkout import StripeCheckoutTool
from rooms.discovery.tools.email_sender import EmailSender
from rooms.discovery.tools.sms_sender import SmsSender
from rooms.discovery.tools.memory_loader import MemoryLoader
from rooms.discovery.tools.vlm_analyzer import VLMAnalyzer

__all__ = [
    "PricingCalculator",
    "ProposalGenerator",
    "ContractGenerator",
    "StripeCheckoutTool",
    "EmailSender",
    "SmsSender",
    "MemoryLoader",
    "VLMAnalyzer",
]
