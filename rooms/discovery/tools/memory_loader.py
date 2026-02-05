"""
Memory Loader - Cross-room context aggregation.

Loads and aggregates context from Room 1 (triage) and Room 2 (architect)
so the Discovery agent can "defend" the solution with full knowledge.
Also loads the current negotiation state for re-entrant processing.
"""
from typing import Optional, Any
from uuid import UUID

import structlog

logger = structlog.get_logger()


class MemoryLoader:
    """Load cross-room memory and negotiation state for discovery agent."""

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    async def load(self, lead_id: UUID) -> dict:
        """
        Load full context for a lead across all rooms.

        Args:
            lead_id: Lead UUID

        Returns:
            dict with triage_context, architect_context, and agent_history
        """
        lead = {}
        if self.db:
            lead = await self.db.get_lead(lead_id) or {}

        # Load prior agent runs for decision context
        agent_runs = []
        if self.db:
            try:
                runs_data = self.db.client.table("agent_runs").select(
                    "room, status, output_data, cost_usd, created_at"
                ).eq("lead_id", str(lead_id)).order(
                    "created_at", desc=True
                ).limit(10).execute()
                agent_runs = runs_data.data or []
            except Exception as e:
                logger.warning("Failed to load agent runs", error=str(e))

        return {
            "lead": lead,
            "triage_context": {
                "score": lead.get("triage_score"),
                "signals": lead.get("triage_signals"),
                "completed_at": lead.get("triage_completed_at"),
            },
            "architect_context": {
                "mockup_url": lead.get("mockup_url"),
                "mockup_code_url": lead.get("mockup_code_url"),
                "brand_audit": lead.get("brand_audit"),
                "completed_at": lead.get("architect_completed_at"),
            },
            "agent_history": [
                {
                    "room": r.get("room"),
                    "status": r.get("status"),
                    "cost_usd": r.get("cost_usd"),
                    "created_at": r.get("created_at"),
                }
                for r in agent_runs
            ],
        }

    async def get_negotiation_state(self, lead_id: UUID) -> dict:
        """
        Load the current negotiation state for a lead.

        Args:
            lead_id: Lead UUID

        Returns:
            dict with full negotiation state, or empty dict if none exists
        """
        if not self.db:
            return {}

        try:
            response = self.db.client.table("discovery_negotiations").select(
                "*"
            ).eq("lead_id", str(lead_id)).maybe_single().execute()
            return response.data or {}
        except Exception as e:
            logger.warning(
                "Failed to load negotiation state",
                lead_id=str(lead_id),
                error=str(e),
            )
            return {}

    async def get_interactions(
        self, lead_id: UUID, limit: int = 20
    ) -> list[dict]:
        """
        Load recent interactions for a lead.

        Args:
            lead_id: Lead UUID
            limit: Max interactions to return

        Returns:
            List of interaction dicts ordered by created_at desc
        """
        if not self.db:
            return []

        try:
            response = self.db.client.table("discovery_interactions").select(
                "*"
            ).eq("lead_id", str(lead_id)).order(
                "created_at", desc=True
            ).limit(limit).execute()
            return response.data or []
        except Exception as e:
            logger.warning(
                "Failed to load interactions",
                lead_id=str(lead_id),
                error=str(e),
            )
            return []

    async def save_negotiation(self, lead_id: UUID, data: dict) -> dict:
        """
        Create or update the negotiation record for a lead.

        Args:
            lead_id: Lead UUID
            data: Negotiation fields to upsert

        Returns:
            Saved negotiation record
        """
        if not self.db:
            return data

        try:
            upsert_data = {"lead_id": str(lead_id), **data}
            response = self.db.client.table("discovery_negotiations").upsert(
                upsert_data, on_conflict="lead_id"
            ).execute()
            return (response.data[0] if response.data else data)
        except Exception as e:
            logger.error(
                "Failed to save negotiation",
                lead_id=str(lead_id),
                error=str(e),
            )
            return data

    async def log_interaction(self, lead_id: UUID, interaction: dict) -> dict:
        """
        Log a discovery interaction event.

        Args:
            lead_id: Lead UUID
            interaction: Interaction data (interaction_type, channel, etc.)

        Returns:
            Created interaction record
        """
        if not self.db:
            logger.info("Interaction logged (no DB)", **interaction)
            return interaction

        try:
            insert_data = {"lead_id": str(lead_id), **interaction}
            response = self.db.client.table("discovery_interactions").insert(
                insert_data
            ).execute()
            return (response.data[0] if response.data else interaction)
        except Exception as e:
            logger.error(
                "Failed to log interaction",
                lead_id=str(lead_id),
                error=str(e),
            )
            return interaction
