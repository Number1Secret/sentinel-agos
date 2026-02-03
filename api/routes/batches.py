"""
Batch Import API Routes

Bulk lead import and batch management.
"""
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
import redis
import structlog

from api.dependencies import get_current_user, get_supabase_service
from config import settings
from schemas.leads import (
    BulkLeadCreate,
    BulkLeadResponse,
    BatchResponse,
    BatchListResponse,
)
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/batches", tags=["Batches"])


def get_redis_client():
    """Get Redis client for queueing jobs."""
    return redis.from_url(settings.redis_url, decode_responses=True)


@router.post(
    "/bulk",
    response_model=BulkLeadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Bulk import leads"
)
async def bulk_import_leads(
    bulk_data: BulkLeadCreate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Bulk import leads from a list.

    This endpoint:
    1. Creates a batch record to track the import
    2. Creates all leads in the database
    3. Optionally queues all leads for triage (if auto_triage=True)

    Maximum 1000 leads per request.
    """
    user_id = UUID(current_user["id"])

    # Create batch record
    batch_name = bulk_data.batch_name or f"Bulk Import - {len(bulk_data.leads)} leads"

    batch = await db.create_lead_batch(
        user_id=user_id,
        name=batch_name,
        source="api",
        total_count=len(bulk_data.leads),
        playbook_id=bulk_data.playbook_id,
        options={"auto_triage": bulk_data.auto_triage}
    )

    batch_id = UUID(batch["id"])

    logger.info(
        "Starting bulk import",
        batch_id=str(batch_id),
        lead_count=len(bulk_data.leads),
        user_id=str(user_id)
    )

    # Update batch to processing
    await db.update_lead_batch(batch_id, {"status": "processing", "started_at": "now()"})

    # Create leads
    created_count = 0
    error_count = 0
    redis_client = get_redis_client() if bulk_data.auto_triage else None

    for i, lead_item in enumerate(bulk_data.leads):
        try:
            # Create lead
            lead = await db.create_lead(
                url=lead_item.url,
                user_id=user_id,
                source="bulk_import",
                batch_id=batch_id,
                metadata={
                    "company_name": lead_item.company_name,
                    "contact_email": lead_item.contact_email,
                    "contact_name": lead_item.contact_name,
                    "industry": lead_item.industry,
                    "source_row": i + 1
                }
            )

            created_count += 1

            # Queue for triage if enabled
            if bulk_data.auto_triage and redis_client:
                job_data = {
                    "lead_id": lead["id"],
                    "user_id": str(user_id),
                    "batch_id": str(batch_id),
                    "trigger": "queue"
                }
                if bulk_data.playbook_id:
                    job_data["playbook_id"] = str(bulk_data.playbook_id)

                redis_client.rpush("triage_queue", json.dumps(job_data))

        except Exception as e:
            error_count += 1
            logger.warning(
                "Failed to create lead in batch",
                batch_id=str(batch_id),
                url=lead_item.url,
                error=str(e)
            )

    # Update batch with final counts
    final_status = "completed" if error_count == 0 else "completed"
    await db.update_lead_batch(batch_id, {
        "status": final_status,
        "processed_count": created_count,
        "error_count": error_count,
        "completed_at": "now()"
    })

    logger.info(
        "Bulk import completed",
        batch_id=str(batch_id),
        created=created_count,
        errors=error_count,
        queued=created_count if bulk_data.auto_triage else 0
    )

    message = f"Created {created_count} leads"
    if bulk_data.auto_triage:
        message += f", queued {created_count} for triage"
    if error_count > 0:
        message += f" ({error_count} errors)"

    return BulkLeadResponse(
        batch_id=batch_id,
        batch_name=batch_name,
        total_count=len(bulk_data.leads),
        status=final_status,
        message=message
    )


@router.get(
    "",
    response_model=BatchListResponse,
    summary="List batches"
)
async def list_batches(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    List all batches for the current user.
    """
    user_id = UUID(current_user["id"])

    batches, total = await db.list_lead_batches(
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset
    )

    return BatchListResponse(
        batches=[BatchResponse(**batch) for batch in batches],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get(
    "/{batch_id}",
    response_model=BatchResponse,
    summary="Get batch details"
)
async def get_batch(
    batch_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get detailed information about a batch.
    """
    batch = await db.get_lead_batch(batch_id)

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found"
        )

    if batch.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this batch"
        )

    return BatchResponse(**batch)


@router.post(
    "/{batch_id}/cancel",
    response_model=BatchResponse,
    summary="Cancel a batch"
)
async def cancel_batch(
    batch_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Cancel a running batch.

    This will update the batch status but will not
    remove leads that have already been created.
    """
    batch = await db.get_lead_batch(batch_id)

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch not found"
        )

    if batch.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this batch"
        )

    if batch.get("status") not in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel batch with status: {batch.get('status')}"
        )

    updated_batch = await db.update_lead_batch(batch_id, {
        "status": "cancelled",
        "completed_at": "now()"
    })

    logger.info("Batch cancelled", batch_id=str(batch_id))

    return BatchResponse(**updated_batch)
