"""
Triage Task Processor

Processes triage jobs from the triage_queue.
Each job contains a lead_id to process through the Triage Room.
"""
from uuid import UUID

import structlog

from services.supabase import SupabaseService
from rooms.triage.room import create_triage_room

logger = structlog.get_logger()


async def process_triage_job(job_data: dict) -> None:
    """
    Process a triage job from the queue.

    Job data format:
    {
        "lead_id": "uuid",
        "user_id": "uuid" (optional),
        "batch_id": "uuid" (optional),
        "playbook_id": "uuid" (optional),
        "trigger": "queue" | "api" | "manual"
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
        "Processing triage job",
        lead_id=lead_id,
        batch_id=str(batch_id) if batch_id else None
    )

    # Get database service (with admin access for worker)
    db = SupabaseService(use_admin=True)

    try:
        # Fetch the lead
        lead = await db.get_lead(lead_uuid)
        if not lead:
            logger.error("Lead not found", lead_id=lead_id)
            return

        # Create triage room
        room = await create_triage_room(db)

        # Execute triage
        result = await room.execute(
            lead=lead,
            playbook_id=playbook_id,
            user_id=user_id,
            batch_id=batch_id,
            trigger=trigger
        )

        logger.info(
            "Triage job completed",
            lead_id=lead_id,
            status=result.get("status"),
            qualified=result.get("triage_score") is not None
        )

    except Exception as e:
        logger.exception(
            "Triage job failed",
            lead_id=lead_id,
            error=str(e)
        )
        raise
