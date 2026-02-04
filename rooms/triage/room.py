"""
TriageRoom - Room 1 of the AgOS Factory (Infinite SDR Engine).

Processes leads through fast-pass URL scanning and qualification.

The "Infinite SDR" refactoring adds:
- Auto-enrichment for Gold leads (score > 85 or gold_lead gate passed)
- Dynamic playbook-driven behavior
- Workflow graph support for next-room handoff
"""
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import AgentRunContext
from rooms.base import BaseRoom, RoomConfig, TRIAGE_ROOM_CONFIG
from rooms.triage.agent import TriageAgent, create_triage_agent
from rooms.triage.tools.condition_evaluator import ConditionEvaluator

logger = structlog.get_logger()


class TriageRoom(BaseRoom):
    """
    Triage Room - Fast-pass URL qualification (Infinite SDR Engine).

    Input: Leads with status 'new'
    Output: Leads with status 'qualified' or 'disqualified'

    Processing:
    1. Validates lead can enter room
    2. Updates status to 'scanning'
    3. Runs TriageAgent to extract signals and score
    4. If Gold lead, auto-enriches with contact verification
    5. Updates lead with triage_score, triage_signals, and enrichment data
    6. Transitions to 'qualified' or 'disqualified'
    """

    config = TRIAGE_ROOM_CONFIG

    def __init__(
        self,
        db_service: Any,
        agent: Optional[TriageAgent] = None,
    ):
        super().__init__(db_service, agent)
        self._agent_initialized = False
        self._current_playbook_config: dict = {}  # Stored for on_success auto-enrich

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
        self._current_playbook_config = playbook_config  # Store for on_success

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
        update_data = {
            "triage_score": result.get("score"),
            "triage_signals": result.get("signals"),
            "triage_completed_at": datetime.utcnow().isoformat(),
            "metadata": {
                "triage_recommendation": result.get("recommendation"),
                "triage_load_time_ms": result.get("load_time_ms"),
                "playbook_version": result.get("playbook_version"),
            }
        }

        # Add v2.0 specific data
        if result.get("logic_gate_results"):
            update_data["metadata"]["logic_gate_results"] = result.get("logic_gate_results")

        if result.get("additional_signals"):
            update_data["metadata"]["additional_signals"] = result.get("additional_signals")

        # Add enrichment data if present
        if result.get("enrichment"):
            update_data["enrichment_data"] = result.get("enrichment")
            update_data["enrichment_source"] = "apollo"
            update_data["enrichment_completed_at"] = datetime.utcnow().isoformat()

        return update_data

    def _is_qualified(self, result: dict) -> bool:
        """
        Determine if triage result indicates qualification.

        Args:
            result: Triage agent result

        Returns:
            True if lead should proceed to Architect room
        """
        return result.get("qualified", False)

    def _is_gold_lead(self, result: dict) -> bool:
        """
        Determine if lead is a "Gold" lead eligible for auto-enrichment.

        Args:
            result: Triage agent result

        Returns:
            True if lead should be auto-enriched
        """
        # Check logic gate result first (v2.0 playbooks)
        logic_gates = result.get("logic_gate_results", {})
        gold_result = logic_gates.get("gold_lead", {})
        if gold_result.get("passed"):
            return True

        # Fallback to score threshold
        score = result.get("score", 0)
        return score >= 85

    async def on_success(self, lead: dict, result: dict) -> dict:
        """
        Handle successful triage with auto-enrichment for Gold leads.

        Overrides BaseRoom.on_success to add auto-enrichment logic.

        Args:
            lead: Lead data
            result: Triage agent result

        Returns:
            Updated lead data
        """
        lead_id = UUID(lead["id"])

        # Check for auto-enrich configuration
        auto_enrich = self._current_playbook_config.get("auto_enrich", {})

        if auto_enrich and self._is_gold_lead(result):
            logger.info(
                "Gold lead detected, running auto-enrichment",
                lead_id=str(lead_id),
                score=result.get("score")
            )

            # Run enrichment tools
            enrichment_result = await self._run_auto_enrichment(lead, result)
            if enrichment_result:
                result["enrichment"] = enrichment_result

        # Call parent on_success
        return await super().on_success(lead, result)

    async def _run_auto_enrichment(self, lead: dict, result: dict) -> Optional[dict]:
        """
        Run auto-enrichment tools for Gold leads.

        Args:
            lead: Lead data
            result: Triage agent result

        Returns:
            Enrichment result dict or None
        """
        auto_enrich = self._current_playbook_config.get("auto_enrich", {})
        tools_to_run = auto_enrich.get("tools", ["contact_verification"])

        domain = lead.get("domain")
        if not domain:
            # Extract from URL
            url = lead.get("url", "")
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith("www."):
                domain = domain[4:]

        if not domain:
            logger.warning("Cannot enrich lead without domain", lead_id=lead.get("id"))
            return None

        enrichment = {}

        for tool_name in tools_to_run:
            try:
                if tool_name == "contact_verification":
                    # Import here to avoid circular imports
                    from rooms.triage.tools.contact_verification import contact_verification_node

                    enrich_result = await contact_verification_node(
                        domain=domain,
                        company_name=lead.get("company_name"),
                        limit=5
                    )

                    if enrich_result.get("success"):
                        enrichment["contacts"] = enrich_result
                        logger.info(
                            "Contact enrichment successful",
                            lead_id=lead.get("id"),
                            contacts_found=enrich_result.get("total_contacts_found", 0)
                        )
                    else:
                        logger.warning(
                            "Contact enrichment failed",
                            lead_id=lead.get("id"),
                            error=enrich_result.get("error")
                        )

            except Exception as e:
                logger.error(
                    "Auto-enrichment tool failed",
                    tool=tool_name,
                    lead_id=lead.get("id"),
                    error=str(e)
                )

        return enrichment if enrichment else None


async def create_triage_room(db_service) -> TriageRoom:
    """
    Factory function to create a TriageRoom.

    Args:
        db_service: Supabase service instance

    Returns:
        Configured TriageRoom
    """
    return TriageRoom(db_service=db_service)
