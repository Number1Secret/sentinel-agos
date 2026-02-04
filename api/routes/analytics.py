"""
Analytics API Routes

Usage statistics, cost tracking, and pipeline metrics.
"""
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
import structlog

from api.dependencies import get_current_user, get_supabase_service
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# =====================
# Response Models
# =====================

class UsageStats(BaseModel):
    """Token and cost usage statistics."""
    total_tokens: int
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    period_start: datetime
    period_end: datetime


class PipelineStats(BaseModel):
    """Lead pipeline statistics."""
    total_leads: int
    new: int
    scanning: int
    qualified: int
    disqualified: int
    designing: int
    mockup_ready: int
    conversion_rate: float  # qualified / (qualified + disqualified)


class AgentStats(BaseModel):
    """Agent performance statistics."""
    agent_slug: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    avg_duration_ms: float
    total_tokens: int
    total_cost_usd: float
    success_rate: float


class RoomStats(BaseModel):
    """Room throughput statistics."""
    room: str
    processed_today: int
    processed_week: int
    processed_month: int
    avg_processing_time_ms: float
    queue_size: int


class AnalyticsSummary(BaseModel):
    """Complete analytics summary."""
    usage: UsageStats
    pipeline: PipelineStats
    agents: list[AgentStats]
    rooms: list[RoomStats]


# =====================
# Endpoints
# =====================

@router.get(
    "/usage",
    response_model=UsageStats,
    summary="Get token and cost usage"
)
async def get_usage_stats(
    period: str = Query("month", description="Period: day, week, month"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get token usage and cost statistics for the current period.
    """
    user_id = UUID(current_user["id"])

    # Calculate period bounds
    now = datetime.utcnow()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Query agent_runs for the period
    try:
        response = db.client.table("agent_runs").select(
            "input_tokens, output_tokens, cost_usd"
        ).eq(
            "user_id", str(user_id)
        ).gte(
            "created_at", start.isoformat()
        ).execute()

        runs = response.data

        total_input = sum(r.get("input_tokens", 0) or 0 for r in runs)
        total_output = sum(r.get("output_tokens", 0) or 0 for r in runs)
        total_cost = sum(float(r.get("cost_usd", 0) or 0) for r in runs)

        return UsageStats(
            total_tokens=total_input + total_output,
            input_tokens=total_input,
            output_tokens=total_output,
            total_cost_usd=round(total_cost, 4),
            period_start=start,
            period_end=now
        )

    except Exception as e:
        logger.error("Failed to get usage stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics"
        )


@router.get(
    "/pipeline",
    response_model=PipelineStats,
    summary="Get pipeline statistics"
)
async def get_pipeline_stats(
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get lead pipeline statistics showing distribution across statuses.
    """
    user_id = UUID(current_user["id"])

    try:
        # Get counts by status
        response = db.client.table("leads").select(
            "status", count="exact"
        ).eq(
            "user_id", str(user_id)
        ).execute()

        # Count by status
        status_counts = {}
        for lead in response.data:
            status = lead.get("status", "new")
            status_counts[status] = status_counts.get(status, 0) + 1

        total = sum(status_counts.values())
        qualified = status_counts.get("qualified", 0) + status_counts.get("designing", 0) + status_counts.get("mockup_ready", 0)
        disqualified = status_counts.get("disqualified", 0)

        conversion_rate = 0.0
        if qualified + disqualified > 0:
            conversion_rate = qualified / (qualified + disqualified)

        return PipelineStats(
            total_leads=total,
            new=status_counts.get("new", 0),
            scanning=status_counts.get("scanning", 0),
            qualified=status_counts.get("qualified", 0),
            disqualified=disqualified,
            designing=status_counts.get("designing", 0),
            mockup_ready=status_counts.get("mockup_ready", 0),
            conversion_rate=round(conversion_rate, 4)
        )

    except Exception as e:
        logger.error("Failed to get pipeline stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pipeline statistics"
        )


@router.get(
    "/agents",
    response_model=list[AgentStats],
    summary="Get agent performance statistics"
)
async def get_agent_stats(
    period: str = Query("month", description="Period: day, week, month"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get performance statistics for each agent type.
    """
    user_id = UUID(current_user["id"])

    # Calculate period start
    now = datetime.utcnow()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        # Get all agent runs with agent info
        response = db.client.table("agent_runs").select(
            "*, agents(slug)"
        ).eq(
            "user_id", str(user_id)
        ).gte(
            "created_at", start.isoformat()
        ).execute()

        # Aggregate by agent
        agent_data = {}
        for run in response.data:
            agent = run.get("agents", {})
            slug = agent.get("slug", "unknown") if agent else "unknown"

            if slug not in agent_data:
                agent_data[slug] = {
                    "total": 0,
                    "successful": 0,
                    "failed": 0,
                    "durations": [],
                    "tokens": 0,
                    "cost": 0.0
                }

            agent_data[slug]["total"] += 1
            if run.get("status") == "completed":
                agent_data[slug]["successful"] += 1
            elif run.get("status") == "failed":
                agent_data[slug]["failed"] += 1

            if run.get("duration_ms"):
                agent_data[slug]["durations"].append(run["duration_ms"])

            agent_data[slug]["tokens"] += (run.get("input_tokens", 0) or 0) + (run.get("output_tokens", 0) or 0)
            agent_data[slug]["cost"] += float(run.get("cost_usd", 0) or 0)

        # Build response
        stats = []
        for slug, data in agent_data.items():
            avg_duration = 0.0
            if data["durations"]:
                avg_duration = sum(data["durations"]) / len(data["durations"])

            success_rate = 0.0
            if data["total"] > 0:
                success_rate = data["successful"] / data["total"]

            stats.append(AgentStats(
                agent_slug=slug,
                total_runs=data["total"],
                successful_runs=data["successful"],
                failed_runs=data["failed"],
                avg_duration_ms=round(avg_duration, 2),
                total_tokens=data["tokens"],
                total_cost_usd=round(data["cost"], 4),
                success_rate=round(success_rate, 4)
            ))

        return stats

    except Exception as e:
        logger.error("Failed to get agent stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve agent statistics"
        )


@router.get(
    "/rooms",
    response_model=list[RoomStats],
    summary="Get room throughput statistics"
)
async def get_room_stats(
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get throughput statistics for each processing room.
    """
    user_id = UUID(current_user["id"])

    rooms = ["triage", "architect", "discovery", "guardian"]
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stats = []

    try:
        for room in rooms:
            # Get runs for this room
            response = db.client.table("agent_runs").select(
                "created_at, duration_ms, status"
            ).eq(
                "room", room
            ).eq(
                "user_id", str(user_id)
            ).gte(
                "created_at", month_start.isoformat()
            ).execute()

            runs = response.data

            today_count = sum(1 for r in runs if r["created_at"] >= today_start.isoformat())
            week_count = sum(1 for r in runs if r["created_at"] >= week_start.isoformat())
            month_count = len(runs)

            durations = [r["duration_ms"] for r in runs if r.get("duration_ms")]
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            # Get queue size (leads waiting for this room)
            status_map = {
                "triage": ["new"],
                "architect": ["qualified"],
                "discovery": ["mockup_ready"],
                "guardian": ["active_client"]
            }

            queue_response = db.client.table("leads").select(
                "id", count="exact"
            ).eq(
                "user_id", str(user_id)
            ).in_(
                "status", status_map.get(room, [])
            ).execute()

            queue_size = queue_response.count or 0

            stats.append(RoomStats(
                room=room,
                processed_today=today_count,
                processed_week=week_count,
                processed_month=month_count,
                avg_processing_time_ms=round(avg_duration, 2),
                queue_size=queue_size
            ))

        return stats

    except Exception as e:
        logger.error("Failed to get room stats", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve room statistics"
        )


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="Get complete analytics summary"
)
async def get_analytics_summary(
    period: str = Query("month", description="Period for usage/agent stats"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get a complete analytics summary including usage, pipeline, agents, and rooms.
    """
    # Fetch all stats
    usage = await get_usage_stats(period, current_user, db)
    pipeline = await get_pipeline_stats(current_user, db)
    agents = await get_agent_stats(period, current_user, db)
    rooms = await get_room_stats(current_user, db)

    return AnalyticsSummary(
        usage=usage,
        pipeline=pipeline,
        agents=agents,
        rooms=rooms
    )
