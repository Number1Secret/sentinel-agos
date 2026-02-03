"""
Sentinel AgOS API - FastAPI Entry Point

This is the main entry point for the Sentinel Agent Operating System.
It provides a 4-room factory architecture for lead qualification and conversion.
"""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from api.middleware.auth import AuthMiddleware, RateLimitMiddleware
from api.routes import auth_router, audits_router, webhooks_router, leads_router, batches_router
from config import settings
from schemas.analysis import HealthResponse, ErrorResponse

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if settings.is_production else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(
        "Starting Sentinel AgOS API",
        environment=settings.environment,
        version="0.2.0",
    )

    yield

    # Shutdown
    logger.info("Shutting down Sentinel AgOS API")


# Create FastAPI application
app = FastAPI(
    title="Sentinel AgOS API",
    description="""
API for the Sentinel Agent Operating System - a 4-room factory for lead qualification and conversion.

## Rooms

- **Room 1 - Triage Engine**: Mass URL scanning, fast-pass qualification (0-100 score)
- **Room 2 - Architect Studio**: Deep audit + mockup generation
- **Room 3 - Discovery Channel**: Interactive closing (Future)
- **Room 4 - Guardian**: Autonomous maintenance (Future)

## Features

- **Lead Pipeline**: Full lead lifecycle from new → qualified → mockup_ready → closed
- **Bulk Import**: Import up to 1000 leads per batch with auto-triage
- **Agent Observability**: Track tokens, costs, and execution time per agent run
- **Website Audits**: Comprehensive analysis using Lighthouse and Claude AI
- **AI Recommendations**: Actionable insights for improvement

## Authentication

This API uses Supabase Auth with JWT tokens. Include your token in the
`Authorization` header:

```
Authorization: Bearer <your-jwt-token>
```
    """,
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "https://sentinel-api.onrender.com",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add custom middleware
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "details": str(exc) if settings.is_development else None,
        }
    )


# Health check endpoint
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
)
async def health_check():
    """
    Check if the service is healthy.

    Returns service status, timestamp, and version.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="0.2.0",
    )


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to docs or return API info."""
    return {
        "name": "Sentinel AgOS API",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/health",
    }


# Include routers
app.include_router(auth_router)
app.include_router(audits_router)
app.include_router(webhooks_router)
app.include_router(leads_router)
app.include_router(batches_router)


# Development server
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )
