"""
Authentication middleware for rate limiting and request tracking.
"""
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from config import settings

logger = structlog.get_logger()


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for authentication-related concerns:
    - Rate limiting
    - Request logging
    - CORS headers (if not using CORSMiddleware)
    """

    def __init__(self, app):
        super().__init__(app)
        # Simple in-memory rate limiting (use Redis in production)
        self._request_counts: dict[str, list[float]] = defaultdict(list)
        self._rate_limit_window = 3600  # 1 hour
        self._rate_limit_max = settings.max_audits_per_hour

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Add request ID for tracing
        request_id = request.headers.get("X-Request-ID", str(time.time_ns()))
        request.state.request_id = request_id

        # Log incoming request
        logger.info(
            "Request started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        # Log response
        logger.info(
            "Request completed",
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response

    def check_rate_limit(self, identifier: str, endpoint: str = "default") -> tuple[bool, int]:
        """
        Check if request is within rate limit.

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        key = f"{identifier}:{endpoint}"
        current_time = time.time()
        window_start = current_time - self._rate_limit_window

        # Clean old entries
        self._request_counts[key] = [
            t for t in self._request_counts[key]
            if t > window_start
        ]

        # Check limit
        count = len(self._request_counts[key])
        if count >= self._rate_limit_max:
            return False, 0

        # Add current request
        self._request_counts[key].append(current_time)
        return True, self._rate_limit_max - count - 1


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Dedicated rate limiting middleware.
    Uses in-memory storage; replace with Redis for distributed deployments.
    """

    # Endpoints with rate limits
    RATE_LIMITS = {
        "/audits": {"window": 3600, "max": 10},  # 10 audits per hour
        "/auth/login": {"window": 300, "max": 5},  # 5 login attempts per 5 min
    }

    def __init__(self, app):
        super().__init__(app)
        self._request_counts: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only rate limit POST requests
        if request.method != "POST":
            return await call_next(request)

        # Check if endpoint has rate limit
        path = request.url.path
        limit_config = None
        for endpoint, config in self.RATE_LIMITS.items():
            if path.startswith(endpoint):
                limit_config = config
                break

        if not limit_config:
            return await call_next(request)

        # Get identifier (IP or user ID from JWT)
        identifier = request.client.host if request.client else "unknown"

        # Check rate limit
        is_allowed, remaining = self._check_limit(
            identifier,
            path,
            limit_config["window"],
            limit_config["max"]
        )

        if not is_allowed:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "retry_after": limit_config["window"]},
                headers={
                    "X-RateLimit-Limit": str(limit_config["max"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + limit_config["window"])),
                    "Retry-After": str(limit_config["window"]),
                }
            )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit_config["max"])
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

    def _check_limit(self, identifier: str, endpoint: str, window: int, max_requests: int) -> tuple[bool, int]:
        """Check and update rate limit."""
        key = f"{identifier}:{endpoint}"
        current_time = time.time()
        window_start = current_time - window

        # Clean old entries
        self._request_counts[key] = [
            t for t in self._request_counts[key]
            if t > window_start
        ]

        count = len(self._request_counts[key])
        if count >= max_requests:
            return False, 0

        self._request_counts[key].append(current_time)
        return True, max_requests - count - 1
