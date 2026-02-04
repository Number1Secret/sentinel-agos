"""
Quota Enforcement Middleware

Enforces usage quotas based on user subscription tier:
- Free: 100 triage / 5 architect per month
- Starter: 500 triage / 25 architect per month
- Pro: 2000 triage / 100 architect per month
- Agency: 10000 triage / 500 architect per month
- Enterprise: Unlimited

Quotas are tracked in the profiles table and reset monthly.
"""
from datetime import datetime
from functools import wraps
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status, Depends
import structlog

from api.dependencies import get_current_user, get_supabase_service
from services.supabase import SupabaseService

logger = structlog.get_logger()


# Quota limits by tier
QUOTA_LIMITS = {
    "free": {
        "triage_monthly": 100,
        "architect_monthly": 5,
    },
    "starter": {
        "triage_monthly": 500,
        "architect_monthly": 25,
    },
    "pro": {
        "triage_monthly": 2000,
        "architect_monthly": 100,
    },
    "agency": {
        "triage_monthly": 10000,
        "architect_monthly": 500,
    },
    "enterprise": {
        "triage_monthly": float("inf"),
        "architect_monthly": float("inf"),
    }
}


class QuotaExceededError(HTTPException):
    """Exception raised when quota is exceeded."""

    def __init__(self, quota_type: str, limit: int, used: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "quota_type": quota_type,
                "limit": limit,
                "used": used,
                "message": f"Monthly {quota_type} quota exceeded. Used {used}/{limit}. Please upgrade your plan."
            }
        )


async def check_quota(
    user_id: UUID,
    quota_type: str,
    db: SupabaseService
) -> dict:
    """
    Check if user has remaining quota.

    Args:
        user_id: User ID
        quota_type: 'triage' or 'architect'
        db: Database service

    Returns:
        Dict with limit, used, remaining

    Raises:
        QuotaExceededError if quota is exceeded
    """
    # Get user profile with quota info
    profile = await db.get_profile(user_id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )

    tier = profile.get("subscription_tier", "free")
    limits = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["free"])

    # Check if quota needs reset
    quota_reset_at = profile.get("quota_reset_at")
    if quota_reset_at:
        reset_time = datetime.fromisoformat(quota_reset_at.replace("Z", "+00:00"))
        if datetime.utcnow() >= reset_time.replace(tzinfo=None):
            # Reset quotas
            await _reset_quotas(user_id, db)
            profile = await db.get_profile(user_id)

    # Get current usage
    if quota_type == "triage":
        limit = limits["triage_monthly"]
        used = profile.get("triage_used_monthly", 0)
    elif quota_type == "architect":
        limit = limits["architect_monthly"]
        used = profile.get("architect_used_monthly", 0)
    else:
        raise ValueError(f"Unknown quota type: {quota_type}")

    remaining = max(0, limit - used) if limit != float("inf") else float("inf")

    # Check if exceeded
    if limit != float("inf") and used >= limit:
        logger.warning(
            "Quota exceeded",
            user_id=str(user_id),
            quota_type=quota_type,
            limit=limit,
            used=used
        )
        raise QuotaExceededError(quota_type, int(limit), used)

    return {
        "limit": limit if limit != float("inf") else -1,  # -1 = unlimited
        "used": used,
        "remaining": remaining if remaining != float("inf") else -1,
        "tier": tier
    }


async def increment_quota(
    user_id: UUID,
    quota_type: str,
    amount: int,
    db: SupabaseService
) -> dict:
    """
    Increment quota usage.

    Args:
        user_id: User ID
        quota_type: 'triage' or 'architect'
        amount: Amount to increment
        db: Database service

    Returns:
        Updated quota info
    """
    field_name = f"{quota_type}_used_monthly"

    profile = await db.get_profile(user_id)
    current_used = profile.get(field_name, 0)
    new_used = current_used + amount

    await db.update_profile(user_id, {field_name: new_used})

    logger.info(
        "Quota incremented",
        user_id=str(user_id),
        quota_type=quota_type,
        amount=amount,
        new_total=new_used
    )

    return await check_quota(user_id, quota_type, db)


async def _reset_quotas(user_id: UUID, db: SupabaseService):
    """Reset monthly quotas for a user."""
    # Calculate next reset date (first of next month)
    now = datetime.utcnow()
    if now.month == 12:
        next_reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    await db.update_profile(user_id, {
        "triage_used_monthly": 0,
        "architect_used_monthly": 0,
        "quota_reset_at": next_reset.isoformat()
    })

    logger.info(
        "Quotas reset",
        user_id=str(user_id),
        next_reset=next_reset.isoformat()
    )


def require_quota(quota_type: str):
    """
    Decorator to enforce quota check before endpoint execution.

    Usage:
        @router.post("/leads/{id}/triage")
        @require_quota("triage")
        async def queue_for_triage(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(
            *args,
            current_user: dict = Depends(get_current_user),
            db: SupabaseService = Depends(get_supabase_service),
            **kwargs
        ):
            user_id = UUID(current_user["id"])

            # Check quota before proceeding
            await check_quota(user_id, quota_type, db)

            # Execute the endpoint
            result = await func(*args, current_user=current_user, db=db, **kwargs)

            # Increment quota after successful execution
            await increment_quota(user_id, quota_type, 1, db)

            return result

        return wrapper
    return decorator


async def get_quota_status(
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
) -> dict:
    """
    Get current quota status for a user.

    Returns dict with triage and architect quotas.
    """
    user_id = UUID(current_user["id"])

    profile = await db.get_profile(user_id)
    tier = profile.get("subscription_tier", "free")
    limits = QUOTA_LIMITS.get(tier, QUOTA_LIMITS["free"])

    triage_limit = limits["triage_monthly"]
    triage_used = profile.get("triage_used_monthly", 0)

    architect_limit = limits["architect_monthly"]
    architect_used = profile.get("architect_used_monthly", 0)

    return {
        "tier": tier,
        "triage": {
            "limit": triage_limit if triage_limit != float("inf") else -1,
            "used": triage_used,
            "remaining": max(0, triage_limit - triage_used) if triage_limit != float("inf") else -1
        },
        "architect": {
            "limit": architect_limit if architect_limit != float("inf") else -1,
            "used": architect_used,
            "remaining": max(0, architect_limit - architect_used) if architect_limit != float("inf") else -1
        },
        "reset_at": profile.get("quota_reset_at")
    }
