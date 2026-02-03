"""
TriageRoom - Room 1 of the AgOS Factory.

Processes leads through fast-pass URL scanning and qualification.
"""
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import AgentRunContext
from rooms.base import BaseRoom, RoomConfig, TRIAGE_ROOM_CONFIG
from rooms.triage.agent import TriageAgent, create_triage_agent

logger = structlog.get_logger()


class TriageRoom(BaseRoom):
    """
    Triage Room - Fast-pass URL qualification.

    Input: Leads with status 'new'
    Output: Leads with status 'qualified' or 'disqualified'

    Processing:
    1. Validates lead can enter room
    2. Updates status to 'scanning'
    3. Runs TriageAgent to extract signals and score
    4. Updates lead with triage_score and triage_signals
    5. Transitions to 'qualified' or 'disqualified'
    """

    config = TRIAGE_ROOM_CONFIG

    def __init__(
        self,
        db_service: Any,
        agent: Optional[TriageAgent] = None,
    ):
        super().__init__(db_service, agent)
        self._agent_initialized = False

    async def _ensure_agent(self):
        """Lazy initialization of agent from database."""
        if not self._agent_initialized:
            if self.agent is None:
                self.agent = await create_triage_agent(self.db)
            self._agent_initialized = True

    async def process_lead(
        self,
        lead: dict,
        playbook_id: Optional[UUID] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Process a lead through triage.

        Args:
            lead: Lead data with 'url' field
            playbook_id: Optional playbook to use
            context: Additional context (user_id, batch_id, trigger)

        Returns:
            Triage result with score, signals, and qualification status
        """
        await self._ensure_agent()

        context = context or {}
        lead_id = UUID(lead["id"])
        url = lead.get("url")
        user_id = context.get("user_id") or (UUID(lead["user_id"]) if lead.get("user_id") else None)
        batch_id = context.get("batch_id") or (UUID(lead["batch_id"]) if lead.get("batch_id") else None)

        if not url:
            raise ValueError(f"Lead {lead_id} has no URL")

        # Get playbook configuration
        playbook_config = await self.get_playbook(playbook_id)

        # Create agent run context
        run_context = AgentRunContext(
            run_id=uuid4(),
            lead_id=lead_id,
            user_id=user_id,
            playbook_id=playbook_id,
            batch_id=batch_id,
            input_data={
                "url": url,
                "playbook_config": playbook_config,
                "lead_metadata": lead.get("metadata", {})
            },
            trigger=context.get("trigger", "queue")
        )

        # Execute the agent
        result = await self.agent.execute(run_context)

        return result

    def _extract_update_data(self, result: dict) -> dict:
        """
        Extract lead update data from triage result.

        Args:
            result: Triage agent result

        Returns:
            Fields to update on lead
        """
        return {
            "triage_score": result.get("score"),
            "triage_signals": result.get("signals"),
            "triage_completed_at": datetime.utcnow().isoformat(),
            "metadata": {
                "triage_recommendation": result.get("recommendation"),
                "triage_load_time_ms": result.get("load_time_ms")
            }
        }

    def _is_qualified(self, result: dict) -> bool:
        """
        Determine if triage result indicates qualification.

        Args:
            result: Triage agent result

        Returns:
            True if lead should proceed to Architect room
        """
        return result.get("qualified", False)


async def create_triage_room(db_service) -> TriageRoom:
    """
    Factory function to create a TriageRoom.

    Args:
        db_service: Supabase service instance

    Returns:
        Configured TriageRoom
    """
    return TriageRoom(db_service=db_service)
