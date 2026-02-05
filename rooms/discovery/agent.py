"""
DiscoveryAgent - Autonomous Closing Engine (Negotiator).

This agent orchestrates the entire Room 3 pipeline:
1. Loads cross-room memory (triage signals + architect output)
2. Calculates dynamic pricing from playbook rules
3. Generates and sends proposals
4. Manages the SDR follow-up loop with VLM engagement analysis
5. Handles objections using LLM with full deal context
6. Creates Stripe checkout sessions on acceptance
7. Generates PDF contracts

The agent routes behavior based on lead status:
- mockup_ready: Initial presentation (price + proposal + outreach)
- presenting: SDR loop (adaptive follow-up with VLM analysis)
- negotiating: Negotiation handling (objections, discounts, close)
"""
import json
from datetime import datetime, timedelta
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext, load_agent_config
from rooms.discovery.tools.pricing_calculator import PricingCalculator
from rooms.discovery.tools.proposal_generator import ProposalGenerator
from rooms.discovery.tools.contract_generator import ContractGenerator
from rooms.discovery.tools.stripe_checkout import StripeCheckoutTool
from rooms.discovery.tools.email_sender import EmailSender
from rooms.discovery.tools.sms_sender import SmsSender
from rooms.discovery.tools.memory_loader import MemoryLoader
from rooms.discovery.tools.vlm_analyzer import VLMAnalyzer

logger = structlog.get_logger()


class DiscoveryAgent(BaseAgent):
    """
    Discovery Agent for autonomous deal closing.

    Implements a Utility-Based logic model: maximizes "likelihood of close"
    vs "compute cost" at each decision point. The agent has agentic power
    to apply discounts within playbook-defined margins without human approval,
    but NEVER below min_acceptable_price (hard floor enforced in code).
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        pricing: Optional[PricingCalculator] = None,
        proposal_gen: Optional[ProposalGenerator] = None,
        contract_gen: Optional[ContractGenerator] = None,
        stripe_tool: Optional[StripeCheckoutTool] = None,
        email_sender: Optional[EmailSender] = None,
        sms_sender: Optional[SmsSender] = None,
        memory_loader: Optional[MemoryLoader] = None,
        vlm_analyzer: Optional[VLMAnalyzer] = None,
        **kwargs,
    ):
        super().__init__(config, db_service)

        self.pricing = pricing or PricingCalculator()
        self.proposal_gen = proposal_gen or ProposalGenerator(db_service)
        self.contract_gen = contract_gen or ContractGenerator(db_service)
        self.stripe_tool = stripe_tool or StripeCheckoutTool()
        self.email_sender = email_sender or EmailSender(db_service)
        self.sms_sender = sms_sender or SmsSender(db_service)
        self.memory_loader = memory_loader or MemoryLoader(db_service)
        self.vlm_analyzer = vlm_analyzer or VLMAnalyzer(db_service)

        # Register tools for observability tracking
        self.register_tool("calculate_price", self._tool_calculate_price)
        self.register_tool("generate_proposal", self._tool_generate_proposal)
        self.register_tool("generate_contract", self._tool_generate_contract)
        self.register_tool("create_checkout", self._tool_create_checkout)
        self.register_tool("send_email", self._tool_send_email)
        self.register_tool("send_sms", self._tool_send_sms)
        self.register_tool("load_memory", self._tool_load_memory)
        self.register_tool("negotiate", self._tool_negotiate)
        self.register_tool("analyze_mockup_engagement", self._tool_analyze_vlm)

    async def run(self, context: AgentRunContext) -> dict:
        """
        Main execution — routes based on lead status.

        Args:
            context: AgentRunContext with lead data and playbook config

        Returns:
            dict with outcome, deal_value, close_probability, and other fields
        """
        lead_status = context.input_data.get("lead_status", "mockup_ready")
        playbook_config = context.input_data.get("playbook_config", {})

        logger.info(
            "Discovery agent processing",
            lead_id=str(context.lead_id),
            status=lead_status,
        )

        if lead_status == "mockup_ready":
            return await self._handle_initial_presentation(context, playbook_config)
        elif lead_status == "presenting":
            return await self._handle_sdr_loop(context, playbook_config)
        elif lead_status == "negotiating":
            return await self._handle_negotiation(context, playbook_config)
        else:
            raise ValueError(f"Unexpected lead status for discovery: {lead_status}")

    # =========================================================================
    # HANDLER: Initial Presentation (mockup_ready -> presenting)
    # =========================================================================

    async def _handle_initial_presentation(
        self, context: AgentRunContext, playbook: dict
    ) -> dict:
        """
        First entry into Room 3.
        Calculate price, generate proposal, send initial outreach.
        """
        input_data = context.input_data

        # Step 1: Calculate dynamic price
        pricing_result = await self.call_tool(
            "calculate_price",
            triage_score=input_data.get("triage_score"),
            triage_signals=input_data.get("triage_signals", {}),
            brand_audit=input_data.get("brand_audit", {}),
            industry=input_data.get("industry"),
            playbook_rules=playbook.get("pricing_rules", {}),
        )

        # Step 2: Generate proposal PDF
        proposal_result = await self.call_tool(
            "generate_proposal",
            lead_data=input_data,
            pricing=pricing_result,
            playbook_config=playbook,
        )

        # Step 3: Send initial outreach email
        contact_email = input_data.get("contact_email")
        contact_name = input_data.get("contact_name", "")
        company_name = input_data.get("company_name", "")

        email_result = None
        if contact_email:
            email_result = await self.call_tool(
                "send_email",
                to_email=contact_email,
                to_name=contact_name,
                template_slug="initial_proposal",
                template_data={
                    "contact_name": contact_name or "there",
                    "company_name": company_name,
                    "proposal_url": proposal_result.get("public_url", ""),
                    "deal_value": pricing_result.get("final_price", 0),
                    "mockup_url": input_data.get("mockup_url", ""),
                },
            )

        # Step 4: Log interaction
        if context.lead_id:
            await self.memory_loader.log_interaction(context.lead_id, {
                "interaction_type": "email_sent",
                "channel": "email",
                "subject": f"Website proposal for {company_name}",
                "body_preview": f"Initial proposal sent with deal value ${pricing_result.get('final_price', 0):,.0f}",
                "template_slug": "initial_proposal",
                "offered_price": pricing_result.get("final_price"),
                "response_data": email_result or {},
            })

        # Step 5: Create negotiation record
        final_price = pricing_result.get("final_price", 0)
        next_follow_up = datetime.utcnow() + timedelta(hours=48)

        await self.memory_loader.save_negotiation(context.lead_id, {
            "base_price": pricing_result.get("base_price", final_price),
            "current_price": final_price,
            "min_acceptable_price": pricing_result.get("min_acceptable_price", final_price * 0.85),
            "max_discount_pct": pricing_result.get("max_discount_pct", 15),
            "negotiation_state": "proposal_sent",
            "sdr_state": "initial_outreach",
            "total_touches": 1,
            "emails_sent": 1 if contact_email else 0,
            "last_contact_at": datetime.utcnow().isoformat(),
            "next_action_at": next_follow_up.isoformat(),
        })

        return {
            "outcome": "presenting",
            "proposal_url": proposal_result.get("public_url"),
            "proposal_sent_at": datetime.utcnow().isoformat(),
            "deal_value": final_price,
            "close_probability": pricing_result.get("close_probability", 0.3),
            "pricing_breakdown": pricing_result,
            "qualified": True,
        }

    # =========================================================================
    # HANDLER: SDR Loop (presenting -> presenting | negotiating | closed_lost)
    # =========================================================================

    async def _handle_sdr_loop(
        self, context: AgentRunContext, playbook: dict
    ) -> dict:
        """
        Re-entrant SDR loop: decide and execute next follow-up action.
        Uses VLM engagement analysis to personalize outreach.
        """
        input_data = context.input_data
        sdr_config = playbook.get("sdr_loop", {})

        # Load current negotiation state
        negotiation = await self.call_tool("load_memory", lead_id=context.lead_id)
        neg_state = await self.memory_loader.get_negotiation_state(context.lead_id)

        # Run VLM analysis for engagement data
        vlm_result = {}
        vlm_config = playbook.get("vlm", {})
        if vlm_config.get("enabled", True) and context.lead_id:
            vlm_result = await self.call_tool(
                "analyze_mockup_engagement",
                lead_id=context.lead_id,
            )

        # Use LLM to decide next SDR action
        next_action = await self._decide_sdr_action(
            input_data, neg_state, sdr_config, vlm_result
        )

        action = next_action.get("action", "follow_up_email")
        contact_email = input_data.get("contact_email", "")
        contact_name = input_data.get("contact_name", "")

        # Execute the decided action
        if action == "follow_up_email":
            template_slug = next_action.get("template", "follow_up")
            subject = next_action.get("subject")
            await self.call_tool(
                "send_email",
                to_email=contact_email,
                to_name=contact_name,
                subject=subject,
                template_slug=template_slug,
                template_data={
                    "contact_name": contact_name or "there",
                    "company_name": input_data.get("company_name", ""),
                    "proposal_url": input_data.get("proposal_url", ""),
                },
            )
            # Update SDR state
            await self._advance_sdr_state(context.lead_id, neg_state, "email")
            return {"outcome": "presenting", "qualified": True}

        elif action == "pivot_to_sms":
            phone = (input_data.get("metadata") or {}).get("phone")
            if phone:
                await self.call_tool(
                    "send_sms",
                    to_phone=phone,
                    template_slug="sms_check_in",
                    template_data={
                        "contact_name": contact_name or "there",
                        "company_name": input_data.get("company_name", ""),
                        "proposal_url": input_data.get("proposal_url", ""),
                    },
                )
                await self._advance_sdr_state(context.lead_id, neg_state, "sms")
            else:
                # No phone — fallback to email
                await self.call_tool(
                    "send_email",
                    to_email=contact_email,
                    to_name=contact_name,
                    template_slug="follow_up_urgency",
                    template_data={
                        "contact_name": contact_name or "there",
                        "company_name": input_data.get("company_name", ""),
                        "proposal_url": input_data.get("proposal_url", ""),
                    },
                )
                await self._advance_sdr_state(context.lead_id, neg_state, "email")
            return {"outcome": "presenting", "qualified": True}

        elif action == "escalate":
            return {
                "outcome": "presenting",
                "qualified": True,
                "close_probability": 0.15,
                "metadata": {"needs_human_review": True},
            }

        elif action == "close_lost":
            await self.memory_loader.save_negotiation(context.lead_id, {
                "negotiation_state": "rejected",
                "sdr_state": "completed",
                "close_reason": next_action.get("reason", "No engagement after max touches"),
            })
            return {
                "outcome": "closed_lost",
                "qualified": False,
                "close_reason": next_action.get("reason", "No engagement"),
            }

        elif action == "move_to_negotiating":
            await self.memory_loader.save_negotiation(context.lead_id, {
                "negotiation_state": "prospect_engaged",
            })
            return {
                "outcome": "negotiating",
                "qualified": True,
                "close_probability": 0.6,
            }

        # Default: keep presenting
        return {"outcome": "presenting", "qualified": True}

    async def _decide_sdr_action(
        self,
        lead_data: dict,
        negotiation: dict,
        sdr_config: dict,
        vlm_result: dict,
    ) -> dict:
        """Use LLM to decide next SDR action based on engagement signals."""
        sdr_state = negotiation.get("sdr_state", "initial_outreach")
        total_touches = negotiation.get("total_touches", 0)
        max_touches = sdr_config.get("max_touches", 7)

        # Hard limit: auto close-lost after max touches
        if total_touches >= max_touches:
            return {"action": "close_lost", "reason": f"Reached max touches ({max_touches})"}

        # Build VLM context string
        vlm_context = ""
        if vlm_result.get("has_data"):
            vlm_context = f"""
VLM Engagement Analysis:
- Engagement Score: {vlm_result.get('engagement_score', 0)}/100
- Interest Areas: {vlm_result.get('interest_areas', [])}
- Drop-off Points: {vlm_result.get('drop_off_points', [])}
- Recommended Pitch: {vlm_result.get('recommended_pitch_angle', 'N/A')}
- Summary: {vlm_result.get('summary', 'N/A')}"""

        messages = [
            {
                "role": "user",
                "content": f"""You are a sales development representative. Decide the next outreach action.

Current SDR State: {sdr_state}
Total Touches: {total_touches}/{max_touches}
Last Contact: {negotiation.get('last_contact_at', 'Never')}
Last Prospect Action: {negotiation.get('last_prospect_action_at', 'None')}
Company: {lead_data.get('company_name')}
Contact: {lead_data.get('contact_name')}
Deal Value: ${lead_data.get('deal_value', 0)}
{vlm_context}

Available actions:
- follow_up_email: Send a follow-up email
- pivot_to_sms: Switch to SMS channel
- escalate: Flag for human review
- close_lost: Give up on this lead
- move_to_negotiating: Prospect is engaged, move to active negotiation

Respond with EXACTLY one JSON object:
{{"action": "follow_up_email|pivot_to_sms|escalate|close_lost|move_to_negotiating",
  "reason": "brief explanation",
  "subject": "email subject if applicable",
  "template": "template_slug if applicable"}}""",
            }
        ]

        response = await self.call_llm(messages, max_tokens=300, temperature=0.3)

        try:
            text = response.content[0].text
            # Strip markdown code fences if present
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError, AttributeError):
            # Fallback: simple follow-up
            return {
                "action": "follow_up_email",
                "template": "follow_up",
                "subject": f"Following up on your website proposal",
                "reason": "Default follow-up action",
            }

    async def _advance_sdr_state(
        self, lead_id: UUID, current_neg: dict, channel: str
    ) -> None:
        """Advance the SDR state machine and schedule next action."""
        current_state = current_neg.get("sdr_state", "initial_outreach")
        total_touches = current_neg.get("total_touches", 0)

        # State transition map
        next_state_map = {
            "initial_outreach": "follow_up_1",
            "follow_up_1": "follow_up_2",
            "follow_up_2": "channel_pivot",
            "channel_pivot": "escalation",
            "escalation": "cooling_off",
            "cooling_off": "re_engagement",
            "re_engagement": "completed",
        }

        next_state = next_state_map.get(current_state, current_state)

        # Schedule next action (default 48h)
        timing_map = {
            "follow_up_1": 48,
            "follow_up_2": 72,
            "channel_pivot": 48,
            "escalation": 96,
            "cooling_off": 168,
            "re_engagement": 336,
        }
        hours_until_next = timing_map.get(next_state, 48)
        next_action_at = datetime.utcnow() + timedelta(hours=hours_until_next)

        update_data = {
            "sdr_state": next_state,
            "total_touches": total_touches + 1,
            "last_contact_at": datetime.utcnow().isoformat(),
            "next_action_at": next_action_at.isoformat(),
        }
        if channel == "email":
            update_data["emails_sent"] = current_neg.get("emails_sent", 0) + 1
        elif channel == "sms":
            update_data["sms_sent"] = current_neg.get("sms_sent", 0) + 1

        await self.memory_loader.save_negotiation(lead_id, update_data)

    # =========================================================================
    # HANDLER: Negotiation (negotiating -> negotiating | closed_won | closed_lost)
    # =========================================================================

    async def _handle_negotiation(
        self, context: AgentRunContext, playbook: dict
    ) -> dict:
        """
        Handle active negotiation: objections, counter-offers, close.
        """
        input_data = context.input_data
        pricing_rules = playbook.get("pricing_rules", {})

        # Load negotiation state
        neg_state = await self.memory_loader.get_negotiation_state(context.lead_id)

        # Use LLM to decide negotiation action
        negotiation_result = await self.call_tool(
            "negotiate",
            lead_data=input_data,
            negotiation_state=neg_state,
            pricing_rules=pricing_rules,
        )

        action = negotiation_result.get("action", "hold")
        contact_email = input_data.get("contact_email", "")
        contact_name = input_data.get("contact_name", "")
        company_name = input_data.get("company_name", "")

        if action == "apply_discount":
            new_price = float(negotiation_result.get("new_price", 0))
            min_price = float(neg_state.get("min_acceptable_price", 0))

            # HARD CONSTRAINT: never go below floor
            if new_price < min_price:
                logger.warning(
                    "Discount would breach floor — clamping",
                    requested=new_price,
                    floor=min_price,
                )
                new_price = min_price

            # Send revised offer
            await self.call_tool(
                "send_email",
                to_email=contact_email,
                to_name=contact_name,
                template_slug="revised_offer",
                template_data={
                    "contact_name": contact_name or "there",
                    "company_name": company_name,
                    "new_price": new_price,
                    "discount_reason": negotiation_result.get("reason", ""),
                },
            )

            # Update negotiation state
            discount_pct = round(
                (1 - new_price / float(neg_state.get("current_price", new_price))) * 100, 1
            )
            discount_history = neg_state.get("discount_history", [])
            discount_history.append({
                "amount": discount_pct,
                "new_price": new_price,
                "reason": negotiation_result.get("reason", ""),
                "timestamp": datetime.utcnow().isoformat(),
            })

            await self.memory_loader.save_negotiation(context.lead_id, {
                "current_price": new_price,
                "negotiation_state": "counter_offer",
                "discount_history": json.dumps(discount_history),
            })

            return {
                "outcome": "negotiating",
                "deal_value": new_price,
                "close_probability": 0.65,
                "qualified": True,
            }

        elif action == "create_checkout":
            deal_value = float(input_data.get("deal_value") or neg_state.get("current_price", 0))

            # Create Stripe checkout session
            checkout = await self.call_tool(
                "create_checkout",
                lead_id=str(context.lead_id),
                amount=deal_value,
                description=f"Website project for {company_name}",
                customer_email=contact_email,
            )

            # Generate contract PDF
            contract = await self.call_tool(
                "generate_contract",
                lead_data=input_data,
                deal_value=deal_value,
                playbook_config=playbook,
            )

            # Send checkout + contract email
            await self.call_tool(
                "send_email",
                to_email=contact_email,
                to_name=contact_name,
                template_slug="checkout_and_contract",
                template_data={
                    "contact_name": contact_name or "there",
                    "company_name": company_name,
                    "checkout_url": checkout.get("checkout_url", "[payment link pending]"),
                    "contract_url": contract.get("public_url", "[contract pending]"),
                    "deal_value": deal_value,
                },
            )

            # Update negotiation
            await self.memory_loader.save_negotiation(context.lead_id, {
                "negotiation_state": "accepted",
                "stripe_checkout_session_id": checkout.get("session_id"),
                "contract_pdf_url": contract.get("public_url"),
            })

            # Log interaction
            await self.memory_loader.log_interaction(context.lead_id, {
                "interaction_type": "checkout_started",
                "channel": "email",
                "offered_price": deal_value,
                "response_data": {
                    "checkout_url": checkout.get("checkout_url"),
                    "session_id": checkout.get("session_id"),
                    "contract_url": contract.get("public_url"),
                },
            })

            return {
                "outcome": "negotiating",  # Still negotiating until payment
                "deal_value": deal_value,
                "close_probability": 0.85,
                "contract_pdf_url": contract.get("public_url"),
                "qualified": True,
            }

        elif action == "close_lost":
            await self.memory_loader.save_negotiation(context.lead_id, {
                "negotiation_state": "rejected",
                "sdr_state": "completed",
                "close_reason": negotiation_result.get("reason", "Negotiation failed"),
            })
            return {
                "outcome": "closed_lost",
                "qualified": False,
                "close_reason": negotiation_result.get("reason"),
            }

        # Default: hold position
        return {"outcome": "negotiating", "qualified": True}

    # =========================================================================
    # Tool Wrappers (for BaseAgent tool tracking)
    # =========================================================================

    async def _tool_calculate_price(self, **kwargs) -> dict:
        return self.pricing.calculate(**kwargs)

    async def _tool_generate_proposal(self, **kwargs) -> dict:
        return await self.proposal_gen.generate(**kwargs)

    async def _tool_generate_contract(self, **kwargs) -> dict:
        return await self.contract_gen.generate(**kwargs)

    async def _tool_create_checkout(self, **kwargs) -> dict:
        return await self.stripe_tool.create_session(**kwargs)

    async def _tool_send_email(self, **kwargs) -> dict:
        return await self.email_sender.send(**kwargs)

    async def _tool_send_sms(self, **kwargs) -> dict:
        return await self.sms_sender.send(**kwargs)

    async def _tool_load_memory(self, **kwargs) -> dict:
        lead_id = kwargs.get("lead_id")
        if lead_id:
            return await self.memory_loader.load(lead_id)
        return {}

    async def _tool_negotiate(self, **kwargs) -> dict:
        return await self._llm_negotiate(**kwargs)

    async def _tool_analyze_vlm(self, **kwargs) -> dict:
        lead_id = kwargs.get("lead_id")
        if lead_id:
            return await self.vlm_analyzer.analyze_mockup_engagement(
                lead_id, call_llm=self.call_llm
            )
        return {"engagement_score": 0, "has_data": False}

    async def _llm_negotiate(
        self,
        lead_data: dict,
        negotiation_state: dict,
        pricing_rules: dict,
    ) -> dict:
        """LLM-driven negotiation decision with hard price floor constraint."""
        current_price = negotiation_state.get("current_price", 0)
        min_price = negotiation_state.get("min_acceptable_price", 0)
        objections = negotiation_state.get("objections", [])
        max_discount = pricing_rules.get("margin_rules", {}).get("max_discount_pct", 15)

        messages = [
            {
                "role": "user",
                "content": f"""You are a deal negotiator for a web agency. Analyze the situation and decide the next action.

Company: {lead_data.get('company_name')}
Current Price: ${current_price:,.0f}
Minimum Acceptable Price (hard floor): ${min_price:,.0f}
Maximum Discount: {max_discount}%
Objections Raised: {objections}
Negotiation State: {negotiation_state.get('negotiation_state')}
Total Touches: {negotiation_state.get('total_touches', 0)}
Discount History: {negotiation_state.get('discount_history', [])}

Rules:
- You CANNOT offer a price below ${min_price:,.0f} under any circumstances
- Prefer creating a checkout (closing) over applying more discounts
- If the prospect seems engaged but hasn't committed, try creating checkout
- Only close_lost if negotiation is clearly dead

Respond with EXACTLY one JSON object:
{{"action": "apply_discount|create_checkout|close_lost|hold",
  "new_price": 0,
  "reason": "brief explanation"}}""",
            }
        ]

        response = await self.call_llm(messages, max_tokens=200, temperature=0.2)

        try:
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            result = json.loads(text.strip())

            # Enforce price floor in parsed result
            if result.get("action") == "apply_discount":
                new_price = float(result.get("new_price", current_price))
                if new_price < min_price:
                    result["new_price"] = min_price
                    result["reason"] += f" (clamped to floor ${min_price:,.0f})"

            return result
        except (json.JSONDecodeError, IndexError, AttributeError):
            return {"action": "hold", "reason": "Could not determine action"}


async def create_discovery_agent(db_service, **kwargs) -> DiscoveryAgent:
    """
    Factory function to create a DiscoveryAgent with config from database.

    Args:
        db_service: Supabase service instance

    Returns:
        Configured DiscoveryAgent
    """
    config = await load_agent_config(db_service, "discovery")
    return DiscoveryAgent(config=config, db_service=db_service, **kwargs)
