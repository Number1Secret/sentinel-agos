"""
Architect Room - Room 2 in the AgOS Factory.

Receives qualified leads from Triage and:
1. Performs deep audit
2. Extracts brand DNA
3. Generates mockups
4. Updates lead with results
"""
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from rooms.base import BaseRoom, ARCHITECT_ROOM_CONFIG
from rooms.architect.agent import ArchitectAgent, create_architect_agent
from agents.base import AgentRunContext

logger = structlog.get_logger()


class ArchitectRoom(BaseRoom):
    """
    Architect Room for deep audit and mockup generation.

    Processes qualified leads through:
    - Deep Lighthouse audit
    - Brand DNA extraction
    - AI-powered mockup generation
    - Live preview deployment
    """

    config = ARCHITECT_ROOM_CONFIG

    def __init__(
        self,
        db_service: Any,
        agent: Optional[ArchitectAgent] = None,
        e2b_service: Optional[Any] = None
    ):
        super().__init__(db_service, agent)
        self.e2b = e2b_service

    async def process_lead(
        self,
        lead: dict,
        playbook_id: Optional[UUID] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Process a qualified lead through the architect workflow.

        Args:
            lead: Lead data from database
            playbook_id: Optional specific playbook to use
            context: Additional context (user_id, batch_id, trigger)

        Returns:
            dict: Processing result with mockup, audit, brand data
        """
        context = context or {}
        lead_id = UUID(lead["id"])
        url = lead.get("url")
        triage_signals = lead.get("triage_signals", {})

        logger.info(
            "Processing lead in Architect room",
            lead_id=str(lead_id),
            url=url
        )

        # Get playbook configuration
        playbook_config = await self.get_playbook(playbook_id)

        # Create run context
        run_context = AgentRunContext(
            run_id=uuid4(),
            lead_id=lead_id,
            user_id=UUID(context["user_id"]) if context.get("user_id") else None,
            playbook_id=playbook_id,
            batch_id=UUID(context["batch_id"]) if context.get("batch_id") else None,
            input_data={
                "url": url,
                "triage_signals": triage_signals,
                "playbook_config": playbook_config
            },
            trigger=context.get("trigger", "queue")
        )

        # Execute the agent
        result = await self.agent.execute(run_context)

        return result

    def _extract_update_data(self, result: dict) -> dict:
        """
        Extract lead update data from architect result.

        Maps architect output to lead table fields.
        """
        update_data = {}

        # Store mockup URL
        if result.get("mockup_url"):
            update_data["mockup_url"] = result["mockup_url"]

        # Store mockup code URL (if we saved it to storage)
        if result.get("mockup_code_url"):
            update_data["mockup_code_url"] = result["mockup_code_url"]

        # Store brand audit data
        if result.get("brand"):
            update_data["brand_audit"] = result["brand"]

        # Mark completion time
        update_data["architect_completed_at"] = "now()"

        return update_data

    def _is_qualified(self, result: dict) -> bool:
        """
        Determine if architect processing succeeded.

        For architect room, success means we generated a mockup
        or at least extracted brand data.
        """
        # Success if we have either mockup or brand data
        has_mockup = result.get("mockup_url") is not None
        has_brand = result.get("brand") is not None

        if has_mockup:
            logger.info("Architect succeeded with mockup")
            return True

        if has_brand:
            logger.info("Architect succeeded with brand extraction (no mockup)")
            return True

        logger.warning("Architect failed - no mockup or brand data")
        return False


async def create_architect_room(
    db_service: Any,
    e2b_service: Optional[Any] = None
) -> ArchitectRoom:
    """
    Factory function to create an ArchitectRoom.

    Args:
        db_service: Supabase service instance
        e2b_service: Optional E2B service for sandbox

    Returns:
        Configured ArchitectRoom
    """
    agent = await create_architect_agent(db_service, e2b_service)
    return ArchitectRoom(
        db_service=db_service,
        agent=agent,
        e2b_service=e2b_service
    )
