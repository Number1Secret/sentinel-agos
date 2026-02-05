"""
Lead Pipeline API Routes

CRUD operations for leads in the AgOS pipeline.
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
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
    NegotiationResponse,
    TriageRequest,
    TriageResponse,
)
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/leads", tags=["Leads"])


def get_redis_client():
    """Get Redis client for queueing jobs."""
    return redis.from_url(settings.redis_url, decode_responses=True)


@router.post(
    "",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lead"
)
async def create_lead(
    lead_data: LeadCreate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Create a new lead in the pipeline.

    The lead will be created with status 'new' and can be
    queued for triage using POST /leads/{id}/triage.
    """
    user_id = UUID(current_user["id"])

    lead = await db.create_lead(
        url=lead_data.url,
        user_id=user_id,
        source="api",
        metadata={
            "company_name": lead_data.company_name,
            "contact_email": lead_data.contact_email,
            "contact_name": lead_data.contact_name,
            "industry": lead_data.industry,
            **(lead_data.metadata or {})
        }
    )

    logger.info("Lead created", lead_id=lead["id"], user_id=str(user_id))

    return LeadResponse(**lead)


@router.get(
    "",
    response_model=LeadListResponse,
    summary="List leads"
)
async def list_leads(
    status: Optional[str] = Query(None, description="Filter by status"),
    current_room: Optional[str] = Query(None, description="Filter by current room"),
    batch_id: Optional[UUID] = Query(None, description="Filter by batch ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    List leads for the current user with optional filters.
    """
    user_id = UUID(current_user["id"])

    leads, total = await db.list_leads(
        user_id=user_id,
        status=status,
        current_room=current_room,
        batch_id=batch_id,
        limit=limit,
        offset=offset
    )

    return LeadListResponse(
        leads=[LeadResponse(**lead) for lead in leads],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Get lead details"
)
async def get_lead(
    lead_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get detailed information about a specific lead.
    """
    lead = await db.get_lead(lead_id)

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    # Check ownership
    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this lead"
        )

    return LeadResponse(**lead)


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    summary="Update lead"
)
async def update_lead(
    lead_id: UUID,
    lead_update: LeadUpdate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Update lead information.

    Cannot change triage_score, triage_signals, or other
    system-managed fields through this endpoint.
    """
    # Check lead exists and user owns it
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this lead"
        )

    # Build update data
    update_data = lead_update.model_dump(exclude_unset=True)

    if not update_data:
        return LeadResponse(**lead)

    updated_lead = await db.update_lead(lead_id, update_data)

    if not updated_lead:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lead"
        )

    return LeadResponse(**updated_lead)


@router.delete(
    "/{lead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete lead"
)
async def delete_lead(
    lead_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Delete a lead.

    This will also delete associated agent_runs and generated_assets.
    """
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this lead"
        )

    success = await db.delete_lead(lead_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete lead"
        )

    logger.info("Lead deleted", lead_id=str(lead_id))


@router.post(
    "/{lead_id}/triage",
    response_model=TriageResponse,
    summary="Queue lead for triage"
)
async def queue_for_triage(
    lead_id: UUID,
    triage_request: Optional[TriageRequest] = None,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Queue a lead for triage processing.

    The lead must have status 'new' to be queued.
    """
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to triage this lead"
        )

    if lead.get("status") != "new":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lead cannot be triaged. Current status: {lead.get('status')}"
        )

    # Queue the job
    redis_client = get_redis_client()
    job_data = {
        "lead_id": str(lead_id),
        "user_id": current_user["id"],
        "trigger": "api"
    }

    if triage_request and triage_request.playbook_id:
        job_data["playbook_id"] = str(triage_request.playbook_id)

    redis_client.rpush("triage_queue", json.dumps(job_data))

    logger.info(
        "Lead queued for triage",
        lead_id=str(lead_id),
        user_id=current_user["id"]
    )

    return TriageResponse(
        lead_id=lead_id,
        status="queued",
        message="Lead has been queued for triage",
        queued=True
    )


@router.post(
    "/{lead_id}/architect",
    response_model=TriageResponse,
    summary="Queue lead for architect"
)
async def queue_for_architect(
    lead_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Queue a qualified lead for architect processing.

    The lead must have status 'qualified' to be queued.
    """
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to process this lead"
        )

    if lead.get("status") != "qualified":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lead must be qualified first. Current status: {lead.get('status')}"
        )

    # Queue the job
    redis_client = get_redis_client()
    job_data = {
        "lead_id": str(lead_id),
        "user_id": current_user["id"],
        "trigger": "api"
    }

    redis_client.rpush("architect_queue", json.dumps(job_data))

    logger.info(
        "Lead queued for architect",
        lead_id=str(lead_id),
        user_id=current_user["id"]
    )

    return TriageResponse(
        lead_id=lead_id,
        status="queued",
        message="Lead has been queued for architect processing",
        queued=True
    )


@router.post(
    "/{lead_id}/discovery",
    response_model=TriageResponse,
    summary="Queue lead for discovery"
)
async def queue_for_discovery(
    lead_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Queue a lead for discovery (closing) processing.

    The lead must have status 'mockup_ready', 'presenting', or 'negotiating'.
    """
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to process this lead"
        )

    allowed_statuses = ["mockup_ready", "presenting", "negotiating"]
    if lead.get("status") not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lead must be in one of {allowed_statuses}. Current status: {lead.get('status')}"
        )

    # Queue the job
    redis_client = get_redis_client()
    job_data = {
        "lead_id": str(lead_id),
        "user_id": current_user["id"],
        "trigger": "api"
    }

    redis_client.rpush("discovery_queue", json.dumps(job_data))

    logger.info(
        "Lead queued for discovery",
        lead_id=str(lead_id),
        user_id=current_user["id"]
    )

    return TriageResponse(
        lead_id=lead_id,
        status="queued",
        message="Lead has been queued for discovery processing",
        queued=True
    )


@router.get(
    "/{lead_id}/negotiation",
    response_model=NegotiationResponse,
    summary="Get negotiation state"
)
async def get_negotiation_state(
    lead_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get the current negotiation state for a lead.

    Returns pricing, SDR state, contact history, and deal status.
    """
    lead = await db.get_lead(lead_id)
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    if lead.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this lead"
        )

    # Fetch negotiation state
    try:
        response = db.client.table("discovery_negotiations").select(
            "*"
        ).eq("lead_id", str(lead_id)).single().execute()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No negotiation record found for this lead"
        )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No negotiation record found for this lead"
        )

    return NegotiationResponse(**response.data)
