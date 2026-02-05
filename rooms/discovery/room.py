"""
DiscoveryRoom - Room 3 of the AgOS Factory.

Processes leads through the autonomous closing pipeline:
proposal generation -> outreach -> negotiation -> payment -> contract

This room is RE-ENTRANT: leads can enter in statuses mockup_ready,
presenting, or negotiating. The SDR cron job and API endpoints push
re-entrant leads back through the queue for iterative processing.

Status transitions:
  mockup_ready -> presenting (initial proposal sent)
  presenting   -> presenting (SDR follow-up)
  presenting   -> negotiating (prospect engaged)
  presenting   -> closed_lost (no engagement after max touches)
  negotiating  -> negotiating (discount/counter-offer)
  negotiating  -> closed_won (payment received via Stripe webhook)
  negotiating  -> closed_lost (negotiation failed)
  closed_won   -> (handoff to Room 4 Guardian via guardian_queue)
"""
import json
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import AgentRunContext
from rooms.base import BaseRoom, RoomConfig

logger = structlog.get_logger()


DISCOVERY_ROOM_CONFIG = RoomConfig(
    name="discovery",
    queue_name="discovery_queue",
    agent_slug="discovery",
    default_playbook_slug="discovery-standard",
    input_statuses=["mockup_ready", "presenting", "negotiating"],
    output_status_success="closed_won",
    output_status_failure="closed_lost",
    processing_status="presenting",
)


class DiscoveryRoom(BaseRoom):
    """
    Discovery Room — Autonomous closing engine.

    Input: Leads with status 'mockup_ready' (from Architect) or
           re-entrant statuses 'presenting'/'negotiating' (SDR loop)
    Output: Leads with status 'closed_won' or 'closed_lost'
    """

    config = DISCOVERY_ROOM_CONFIG

    def __init__(
        self,
        db_service: Any,
        agent: Optional[Any] = None,
    ):
        super().__init__(db_service, agent)
        self._agent_initialized = agent is not None

    async def _ensure_agent(self):
        """Lazy initialization of agent from database config."""
        if not self._agent_initialized:
            from rooms.discovery.agent import create_discovery_agent
            self.agent = await create_discovery_agent(self.db)
            self._agent_initialized = True

    async def process_lead(
        self,
        lead: dict,
        playbook_id: Optional[UUID] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Process a lead through the discovery/closing pipeline.

        Args:
            lead: Lead data with triage_signals, brand_audit, mockup_url
            playbook_id: Optional playbook override
            context: Additional context (user_id, batch_id, trigger)

        Returns:
            dict with outcome, proposal_url, deal_value, etc.
        """
        await self._ensure_agent()

        context = context or {}
        lead_id = UUID(lead["id"])

        # Get playbook config
        playbook_config = await self.get_playbook(playbook_id)

        # Build comprehensive input from all prior rooms
        run_context = AgentRunContext(
            run_id=uuid4(),
            lead_id=lead_id,
            user_id=UUID(context["user_id"]) if context.get("user_id") else None,
            playbook_id=playbook_id,
            batch_id=UUID(context["batch_id"]) if context.get("batch_id") else None,
            input_data={
                "url": lead.get("url"),
                "lead_status": lead.get("status"),
                "company_name": lead.get("company_name"),
                "contact_email": lead.get("contact_email"),
                "contact_name": lead.get("contact_name"),
                "industry": lead.get("industry"),
                # Room 1 memory
                "triage_score": lead.get("triage_score"),
                "triage_signals": lead.get("triage_signals", {}),
                # Room 2 memory
                "mockup_url": lead.get("mockup_url"),
                "mockup_code_url": lead.get("mockup_code_url"),
                "brand_audit": lead.get("brand_audit", {}),
                # Room 3 existing state (for re-entry)
                "proposal_url": lead.get("proposal_url"),
                "deal_value": float(lead["deal_value"]) if lead.get("deal_value") else None,
                "close_probability": float(lead["close_probability"]) if lead.get("close_probability") else None,
                # Playbook
                "playbook_config": playbook_config,
                # Lead metadata
                "metadata": lead.get("metadata", {}),
            },
            trigger=context.get("trigger", "queue"),
        )

        result = await self.agent.execute(run_context)
        return result

    def _extract_update_data(self, result: dict) -> dict:
        """Extract lead update fields from discovery result."""
        update_data = {}

        if result.get("proposal_url"):
            update_data["proposal_url"] = result["proposal_url"]

        if result.get("proposal_sent_at"):
            update_data["proposal_sent_at"] = result["proposal_sent_at"]

        if result.get("deal_value") is not None:
            update_data["deal_value"] = result["deal_value"]

        if result.get("close_probability") is not None:
            update_data["close_probability"] = result["close_probability"]

        return update_data

    def _is_qualified(self, result: dict) -> bool:
        """
        For discovery, 'qualified' means the lead should keep progressing.
        Only closed_lost counts as unqualified.
        """
        outcome = result.get("outcome", "presenting")
        if outcome == "closed_lost":
            return False
        return True

    async def on_success(self, lead: dict, result: dict) -> dict:
        """
        Override to handle intermediate statuses.

        Discovery doesn't always go to closed_won. It progresses through
        presenting -> negotiating -> closed_won with intermediate updates.
        """
        lead_id = UUID(lead["id"])
        outcome = result.get("outcome", "presenting")

        # Map outcome to lead status
        status_map = {
            "closed_won": "closed_won",
            "closed_lost": "closed_lost",
            "presenting": "presenting",
            "negotiating": "negotiating",
        }
        new_status = status_map.get(outcome, "presenting")

        # Build update data
        update_data = {"status": new_status}
        update_data.update(self._extract_update_data(result))

        await self.db.update_lead(lead_id, update_data)

        logger.info(
            "Discovery processing step completed",
            room=self.config.name,
            lead_id=str(lead_id),
            new_status=new_status,
            outcome=outcome,
        )

        # If closed_won, trigger Room 4 handoff
        if new_status == "closed_won":
            await self._trigger_guardian_handoff(lead_id, result)

        return {**lead, **update_data}

    async def on_failure(self, lead: dict, error: str) -> dict:
        """Handle failure — mark as closed_lost with error context."""
        lead_id = UUID(lead["id"])

        await self.db.update_lead(lead_id, {
            "status": "closed_lost",
            "metadata": {
                **lead.get("metadata", {}),
                "last_error": error,
                "failed_room": self.config.name,
            },
        })

        logger.error(
            "Discovery processing failed",
            room=self.config.name,
            lead_id=str(lead_id),
            error=error,
        )

        return {**lead, "status": "closed_lost"}

    async def _trigger_guardian_handoff(self, lead_id: UUID, result: dict):
        """
        Queue closed_won lead for Room 4 (Guardian).

        Pushes to guardian_queue for future processing.
        The Guardian room will handle deployment and maintenance.
        """
        import redis
        from config import settings

        try:
            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            job_data = {
                "lead_id": str(lead_id),
                "trigger": "room3_handoff",
                "deal_value": result.get("deal_value"),
                "contract_url": result.get("contract_pdf_url"),
            }
            redis_client.rpush("guardian_queue", json.dumps(job_data))

            logger.info(
                "Lead handed off to Guardian (Room 4)",
                lead_id=str(lead_id),
                deal_value=result.get("deal_value"),
            )
        except Exception as e:
            # Don't fail the room if guardian handoff fails
            logger.error(
                "Failed to queue guardian handoff — lead is still closed_won",
                lead_id=str(lead_id),
                error=str(e),
            )


async def create_discovery_room(db_service: Any) -> DiscoveryRoom:
    """
    Factory function to create a DiscoveryRoom.

    Args:
        db_service: Supabase service instance

    Returns:
        Configured DiscoveryRoom (agent loaded lazily on first use)
    """
    return DiscoveryRoom(db_service=db_service)
