"""
Discovery Task Processor

Processes discovery jobs from the discovery_queue.
Each job contains a lead_id to process through the Discovery Room.
"""
from uuid import UUID

import structlog

from services.supabase import SupabaseService
from rooms.discovery.room import create_discovery_room

logger = structlog.get_logger()


async def process_discovery_job(job_data: dict) -> None:
    """
    Process a discovery job from the queue.

    Job data format:
    {
        "lead_id": "uuid",
        "user_id": "uuid" (optional),
        "batch_id": "uuid" (optional),
        "playbook_id": "uuid" (optional),
        "trigger": "queue" | "api" | "manual" | "sdr_cron" | "stripe_webhook"
    }

    Args:
        job_data: Job data from Redis queue
    """
    lead_id = job_data.get("lead_id")
    if not lead_id:
        raise ValueError("Job missing required field: lead_id")

    lead_uuid = UUID(lead_id)
    user_id = UUID(job_data["user_id"]) if job_data.get("user_id") else None
    batch_id = UUID(job_data["batch_id"]) if job_data.get("batch_id") else None
    playbook_id = UUID(job_data["playbook_id"]) if job_data.get("playbook_id") else None
    trigger = job_data.get("trigger", "queue")

    logger.info(
        "Processing discovery job",
        lead_id=lead_id,
        trigger=trigger,
    )

    # Get database service (with admin access for worker)
    db = SupabaseService(use_admin=True)

    try:
        # Fetch the lead
        lead = await db.get_lead(lead_uuid)
        if not lead:
            logger.error("Lead not found", lead_id=lead_id)
            return

        # Verify lead is in valid state for discovery
        valid_statuses = ["mockup_ready", "presenting", "negotiating"]
        if lead.get("status") not in valid_statuses:
            logger.warning(
                "Lead not ready for discovery",
                lead_id=lead_id,
                status=lead.get("status"),
                valid_statuses=valid_statuses,
            )
            return

        # Create discovery room (agent loaded lazily)
        room = await create_discovery_room(db)

        # Execute discovery
        result = await room.execute(
            lead=lead,
            playbook_id=playbook_id,
            user_id=user_id,
            batch_id=batch_id,
            trigger=trigger,
        )

        logger.info(
            "Discovery job completed",
            lead_id=lead_id,
            status=result.get("status"),
            outcome=result.get("outcome", "unknown"),
        )

    except Exception as e:
        logger.exception(
            "Discovery job failed",
            lead_id=lead_id,
            error=str(e),
        )
        raise
