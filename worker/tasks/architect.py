"""
Architect Task Processor

Processes architect jobs from the architect_queue.
Each job contains a lead_id to process through the Architect Room.
"""
from uuid import UUID

import structlog

from services.supabase import SupabaseService
from services.e2b_sandbox import create_e2b_service
from rooms.architect.room import create_architect_room

logger = structlog.get_logger()


async def process_architect_job(job_data: dict) -> None:
    """
    Process an architect job from the queue.

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
        "Processing architect job",
        lead_id=lead_id,
        batch_id=str(batch_id) if batch_id else None
    )

    # Get database service (with admin access for worker)
    db = SupabaseService(use_admin=True)

    # Get E2B service for sandbox execution
    e2b = create_e2b_service(supabase_service=db)

    try:
        # Fetch the lead
        lead = await db.get_lead(lead_uuid)
        if not lead:
            logger.error("Lead not found", lead_id=lead_id)
            return

        # Verify lead is qualified
        if lead.get("status") != "qualified":
            logger.warning(
                "Lead not qualified for architect",
                lead_id=lead_id,
                status=lead.get("status")
            )
            return

        # Create architect room
        room = await create_architect_room(db, e2b_service=e2b)

        # Execute architect workflow
        result = await room.execute(
            lead=lead,
            playbook_id=playbook_id,
            user_id=user_id,
            batch_id=batch_id,
            trigger=trigger
        )

        # Save generated code to storage if we have a mockup
        if result.get("mockup") and result["mockup"].get("code_files"):
            sandbox_id = result.get("sandbox_id")
            if sandbox_id:
                storage_result = await e2b.save_to_storage(
                    sandbox_id=sandbox_id,
                    lead_id=lead_uuid
                )
                if storage_result.get("success"):
                    # Update lead with code URL
                    await db.update_lead(lead_uuid, {
                        "mockup_code_url": storage_result.get("public_url")
                    })

        logger.info(
            "Architect job completed",
            lead_id=lead_id,
            status=result.get("status"),
            has_mockup=result.get("mockup_url") is not None
        )

    except Exception as e:
        logger.exception(
            "Architect job failed",
            lead_id=lead_id,
            error=str(e)
        )
        raise

    finally:
        # Cleanup any sandboxes
        await e2b.close_all()
