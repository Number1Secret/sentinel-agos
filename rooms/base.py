"""
BaseRoom - Abstract base class for all Sentinel processing rooms.

Each room in the AgOS factory:
- Has a dedicated Redis queue
- Processes leads in specific statuses
- Uses a configured agent
- Transitions leads to new statuses
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Type, Any
from uuid import UUID

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext

logger = structlog.get_logger()


@dataclass
class RoomConfig:
    """Configuration for a processing room."""
    name: str                          # Room name (e.g., 'triage')
    queue_name: str                    # Redis queue name (e.g., 'triage_queue')
    agent_slug: str                    # Agent slug in database
    default_playbook_slug: str         # Default playbook slug
    input_statuses: list[str]          # Lead statuses that enter this room
    output_status_success: str         # Status on successful processing
    output_status_failure: str         # Status on failed processing
    processing_status: str             # Status while processing


# Pre-defined room configurations
TRIAGE_ROOM_CONFIG = RoomConfig(
    name="triage",
    queue_name="triage_queue",
    agent_slug="triage",
    default_playbook_slug="triage-standard",
    input_statuses=["new"],
    output_status_success="qualified",
    output_status_failure="disqualified",
    processing_status="scanning"
)

ARCHITECT_ROOM_CONFIG = RoomConfig(
    name="architect",
    queue_name="architect_queue",
    agent_slug="architect",
    default_playbook_slug="architect-full-mockup",
    input_statuses=["qualified"],
    output_status_success="mockup_ready",
    output_status_failure="qualified",  # Stay qualified, retry possible
    processing_status="designing"
)


class BaseRoom(ABC):
    """
    Abstract base class for processing rooms.

    Each room:
    - Receives leads from a Redis queue
    - Validates that leads can enter the room
    - Processes leads using an agent
    - Updates lead status based on results
    """

    config: RoomConfig

    def __init__(
        self,
        db_service: Any,
        agent: Optional[BaseAgent] = None,
    ):
        """
        Initialize the room.

        Args:
            db_service: Supabase service for database operations
            agent: Optional pre-configured agent (loaded from DB if not provided)
        """
        self.db = db_service
        self.agent = agent
        self._playbook_cache: dict[str, dict] = {}

    @abstractmethod
    async def process_lead(
        self,
        lead: dict,
        playbook_id: Optional[UUID] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """
        Process a single lead through this room.

        Args:
            lead: Lead data from database
            playbook_id: Optional specific playbook to use
            context: Additional context for processing

        Returns:
            dict: Processing result with status, score, signals, etc.
        """
        pass

    async def validate_entry(self, lead: dict) -> bool:
        """
        Check if lead can enter this room.

        Args:
            lead: Lead data

        Returns:
            True if lead can be processed, False otherwise
        """
        current_status = lead.get("status")
        if current_status not in self.config.input_statuses:
            logger.warning(
                "Lead cannot enter room",
                room=self.config.name,
                lead_id=lead.get("id"),
                current_status=current_status,
                required_statuses=self.config.input_statuses
            )
            return False
        return True

    async def on_entry(self, lead: dict) -> dict:
        """
        Handle lead entering the room. Updates status to processing.

        Args:
            lead: Lead data

        Returns:
            Updated lead data
        """
        lead_id = UUID(lead["id"])
        await self.db.update_lead_status(
            lead_id=lead_id,
            status=self.config.processing_status,
            current_room=self.config.name
        )
        logger.info(
            "Lead entered room",
            room=self.config.name,
            lead_id=str(lead_id),
            status=self.config.processing_status
        )
        return {**lead, "status": self.config.processing_status, "current_room": self.config.name}

    async def on_success(self, lead: dict, result: dict) -> dict:
        """
        Handle successful processing. Updates lead with results.

        Args:
            lead: Lead data
            result: Processing result from agent

        Returns:
            Updated lead data
        """
        lead_id = UUID(lead["id"])

        # Build update data based on room type
        update_data = {
            "status": self.config.output_status_success,
        }

        # Add room-specific result data
        update_data.update(self._extract_update_data(result))

        await self.db.update_lead(lead_id, update_data)

        logger.info(
            "Lead processing succeeded",
            room=self.config.name,
            lead_id=str(lead_id),
            new_status=self.config.output_status_success
        )

        return {**lead, **update_data}

    async def on_failure(self, lead: dict, error: str) -> dict:
        """
        Handle failed processing.

        Args:
            lead: Lead data
            error: Error message

        Returns:
            Updated lead data
        """
        lead_id = UUID(lead["id"])

        await self.db.update_lead(lead_id, {
            "status": self.config.output_status_failure,
            "metadata": {
                **lead.get("metadata", {}),
                "last_error": error,
                "failed_room": self.config.name
            }
        })

        logger.error(
            "Lead processing failed",
            room=self.config.name,
            lead_id=str(lead_id),
            error=error,
            new_status=self.config.output_status_failure
        )

        return {**lead, "status": self.config.output_status_failure}

    async def execute(
        self,
        lead: dict,
        playbook_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        batch_id: Optional[UUID] = None,
        trigger: str = "queue"
    ) -> dict:
        """
        Full execution flow for processing a lead.

        This is the main entry point called by the worker.

        Args:
            lead: Lead data from database
            playbook_id: Optional playbook override
            user_id: User who owns the lead
            batch_id: Optional batch this lead belongs to
            trigger: How this was triggered ('queue', 'api', 'manual')

        Returns:
            Final lead state after processing
        """
        lead_id = lead.get("id")

        # Validate entry
        if not await self.validate_entry(lead):
            return lead

        # Update to processing status
        lead = await self.on_entry(lead)

        try:
            # Process the lead
            result = await self.process_lead(
                lead=lead,
                playbook_id=playbook_id,
                context={
                    "user_id": user_id,
                    "batch_id": batch_id,
                    "trigger": trigger
                }
            )

            # Check if qualified based on result
            if self._is_qualified(result):
                return await self.on_success(lead, result)
            else:
                # Not qualified = "failure" in terms of progression
                return await self.on_failure(lead, "Did not meet qualification criteria")

        except Exception as e:
            logger.exception(
                "Room processing error",
                room=self.config.name,
                lead_id=lead_id,
                error=str(e)
            )
            return await self.on_failure(lead, str(e))

    async def get_playbook(self, playbook_id: Optional[UUID] = None) -> dict:
        """
        Get playbook configuration.

        Args:
            playbook_id: Specific playbook ID, or None for default

        Returns:
            Playbook config dict
        """
        if playbook_id:
            cache_key = str(playbook_id)
            if cache_key not in self._playbook_cache:
                playbook = await self.db.get_playbook_by_id(playbook_id)
                if playbook:
                    self._playbook_cache[cache_key] = playbook.get("config", {})
            return self._playbook_cache.get(cache_key, {})

        # Get default playbook
        cache_key = f"default:{self.config.default_playbook_slug}"
        if cache_key not in self._playbook_cache:
            playbook = await self.db.get_playbook_by_slug(self.config.default_playbook_slug)
            if playbook:
                self._playbook_cache[cache_key] = playbook.get("config", {})
        return self._playbook_cache.get(cache_key, {})

    def _extract_update_data(self, result: dict) -> dict:
        """
        Extract lead update data from processing result.

        Override in subclasses for room-specific fields.

        Args:
            result: Processing result

        Returns:
            Dict of fields to update on lead
        """
        return {}

    def _is_qualified(self, result: dict) -> bool:
        """
        Determine if result indicates qualification.

        Override in subclasses for room-specific logic.

        Args:
            result: Processing result

        Returns:
            True if lead should progress, False if it should fail
        """
        return result.get("qualified", False)
