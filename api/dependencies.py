"""
FastAPI dependencies for authentication and services.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Header, status
from supabase import Client
import structlog

from config import settings
from services.supabase import get_supabase_client, get_supabase_admin_client, SupabaseService

logger = structlog.get_logger()


async def get_supabase() -> Client:
    """Get Supabase client dependency."""
    return get_supabase_client()


async def get_supabase_admin() -> Client:
    """Get Supabase admin client dependency."""
    return get_supabase_admin_client()


async def get_db_service(
    use_admin: bool = False
) -> SupabaseService:
    """Get database service dependency."""
    return SupabaseService(use_admin=use_admin)


async def get_supabase_service() -> SupabaseService:
    """Get Supabase service dependency."""
    return SupabaseService()


async def get_current_user(
    authorization: Annotated[Optional[str], Header()] = None,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """
    Validate JWT token and return current user.

    Extracts user from Supabase JWT token in Authorization header.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token from "Bearer <token>"
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("Invalid auth scheme")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Verify JWT with Supabase
        user_response = supabase.auth.get_user(token)

        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = user_response.user

        # Get profile data
        db = SupabaseService(client=supabase)
        profile = await db.get_profile(UUID(user.id))

        if not profile:
            # Profile should be created by trigger, but handle edge case
            logger.warning("Profile not found for user", user_id=user.id)
            profile = {
                "id": user.id,
                "email": user.email,
                "plan": "free",
                "audits_remaining": 5,
            }

        return {
            "id": UUID(user.id),
            "email": user.email,
            "profile": profile,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Auth error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(
    authorization: Annotated[Optional[str], Header()] = None,
    supabase: Client = Depends(get_supabase),
) -> Optional[dict]:
    """
    Optionally validate JWT token if present.
    Returns None if no token or invalid token.
    """
    if not authorization:
        return None

    try:
        return await get_current_user(authorization, supabase)
    except HTTPException:
        return None


# Type aliases for cleaner route signatures
CurrentUser = Annotated[dict, Depends(get_current_user)]
OptionalUser = Annotated[Optional[dict], Depends(get_optional_user)]
DBService = Annotated[SupabaseService, Depends(get_db_service)]
