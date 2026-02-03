"""
Authentication routes for Supabase Auth integration.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
import structlog

from api.dependencies import CurrentUser, get_supabase
from schemas.analysis import (
    User,
    MagicLinkRequest,
    MagicLinkResponse,
    ErrorResponse,
)
from config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/login",
    response_model=MagicLinkResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limited"},
    },
    summary="Request magic link login",
)
async def request_magic_link(
    request: MagicLinkRequest,
    supabase=Depends(get_supabase),
):
    """
    Send a magic link to the provided email address.

    The user will receive an email with a link to authenticate.
    The link redirects to /auth/callback with a token.
    """
    try:
        # Determine redirect URL based on environment
        if settings.is_production:
            redirect_url = "https://sentinel-api.onrender.com/auth/callback"
        else:
            redirect_url = f"http://localhost:{settings.api_port}/auth/callback"

        # Send magic link via Supabase
        response = supabase.auth.sign_in_with_otp({
            "email": request.email,
            "options": {
                "email_redirect_to": redirect_url,
            }
        })

        logger.info("Magic link sent", email=request.email)

        return MagicLinkResponse(message="Check your email for login link")

    except Exception as e:
        logger.error("Failed to send magic link", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send magic link"
        )


@router.get(
    "/callback",
    summary="Handle magic link callback",
    include_in_schema=False,  # Hide from OpenAPI docs
)
async def auth_callback(
    access_token: Optional[str] = Query(None),
    refresh_token: Optional[str] = Query(None),
    token_type: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """
    Handle the callback from Supabase magic link authentication.

    On success, redirects to dashboard with tokens.
    On error, redirects to login with error message.
    """
    if error:
        logger.warning("Auth callback error", error=error, description=error_description)
        # Redirect to frontend login page with error
        return RedirectResponse(
            url=f"/login?error={error}&message={error_description or 'Authentication failed'}",
            status_code=status.HTTP_302_FOUND
        )

    if not access_token:
        return RedirectResponse(
            url="/login?error=no_token&message=No access token received",
            status_code=status.HTTP_302_FOUND
        )

    # In production, redirect to frontend dashboard with token
    # For API-only mode, return token info
    logger.info("Auth callback success")

    # Redirect to dashboard (frontend would store the token)
    # In a real app, this would redirect to your frontend URL
    return RedirectResponse(
        url=f"/dashboard?access_token={access_token}",
        status_code=status.HTTP_302_FOUND
    )


@router.get(
    "/me",
    response_model=User,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
    summary="Get current user",
)
async def get_current_user_info(user: CurrentUser):
    """
    Get the current authenticated user's profile.

    Requires a valid JWT token in the Authorization header.
    """
    profile = user["profile"]

    return User(
        id=user["id"],
        email=user["email"],
        fullName=profile.get("full_name"),
        companyName=profile.get("company_name"),
        plan=profile.get("plan", "free"),
        auditsRemaining=profile.get("audits_remaining", 0),
        createdAt=profile.get("created_at", datetime.utcnow()),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout current user",
)
async def logout(
    user: CurrentUser,
    supabase=Depends(get_supabase),
):
    """
    Logout the current user.

    Invalidates the current session on Supabase.
    """
    try:
        supabase.auth.sign_out()
        logger.info("User logged out", user_id=str(user["id"]))
    except Exception as e:
        logger.warning("Logout error", error=str(e))
        # Don't fail on logout errors

    return None


@router.post(
    "/refresh",
    summary="Refresh access token",
)
async def refresh_token(
    refresh_token: str,
    supabase=Depends(get_supabase),
):
    """
    Refresh the access token using a refresh token.
    """
    try:
        response = supabase.auth.refresh_session(refresh_token)

        if not response or not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_at": response.session.expires_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token refresh failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh token"
        )
