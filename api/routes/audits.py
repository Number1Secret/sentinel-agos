"""
Audit routes for Scout Agent website analysis.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
import redis
import json
import structlog

from api.dependencies import CurrentUser, get_db_service
from schemas.audit import (
    CreateAuditRequest,
    AuditJob,
    AuditSummary,
    AuditResult,
    PerformanceMetrics,
    SEOMetrics,
    AccessibilityMetrics,
    BrandElements,
    AnalysisResult,
    Screenshots,
)
from schemas.analysis import AuditListResponse, ErrorResponse
from services.supabase import SupabaseService
from config import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/audits", tags=["Audits"])


def get_redis_client():
    """Get Redis client for job queue."""
    return redis.from_url(settings.redis_url, decode_responses=True)


@router.post(
    "",
    response_model=AuditJob,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        429: {"description": "Rate limit exceeded (max 10 audits/hour)"},
    },
    summary="Create new website audit",
    description="""
Queues a new website audit job. The Scout Agent will:
1. Capture screenshots (desktop + mobile)
2. Run Lighthouse performance/SEO audit
3. Extract brand elements (colors, fonts, CTAs)
4. Generate AI-powered recommendations

Returns immediately with job ID. Poll /audits/{id} for results.
    """,
)
async def create_audit(
    request: CreateAuditRequest,
    user: CurrentUser,
):
    """Create a new website audit job."""
    # Check if user has audits remaining
    profile = user["profile"]
    if profile.get("audits_remaining", 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No audits remaining. Please upgrade your plan.",
        )

    # Validate URL
    url = str(request.url)
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must start with http:// or https://",
        )

    # Create audit record in database
    db = SupabaseService(use_admin=True)

    competitors = [str(c) for c in request.competitors] if request.competitors else []
    options = request.options.model_dump() if request.options else {}

    audit = await db.create_audit(
        user_id=user["id"],
        url=url,
        competitors=competitors,
        options=options,
    )

    audit_id = audit["id"]

    # Queue job in Redis
    try:
        redis_client = get_redis_client()
        job_data = {
            "audit_id": audit_id,
            "url": url,
            "user_id": str(user["id"]),
            "competitors": competitors,
            "options": options,
            "created_at": datetime.utcnow().isoformat(),
        }
        redis_client.rpush("audit_queue", json.dumps(job_data))
        logger.info("Audit job queued", audit_id=audit_id, url=url)
    except Exception as e:
        logger.error("Failed to queue job", audit_id=audit_id, error=str(e))
        # Update audit status to failed
        await db.update_audit_status(UUID(audit_id), "failed", f"Failed to queue: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue audit job",
        )

    return AuditJob(
        id=UUID(audit_id),
        status="queued",
        url=url,
        createdAt=datetime.fromisoformat(audit["created_at"].replace("Z", "+00:00")),
        estimatedCompletionSeconds=120,
    )


@router.get(
    "",
    response_model=AuditListResponse,
    summary="List user's audits",
)
async def list_audits(
    user: CurrentUser,
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all audits for the authenticated user."""
    db = SupabaseService(use_admin=True)

    audits, total = await db.list_audits(
        user_id=user["id"],
        status=status_filter,
        limit=limit,
        offset=offset,
    )

    # Convert to response format
    audit_summaries = []
    for audit in audits:
        performance = audit.get("performance") or {}
        audit_summaries.append(AuditSummary(
            id=UUID(audit["id"]),
            url=audit["url"],
            status=audit["status"],
            performanceScore=performance.get("score"),
            createdAt=datetime.fromisoformat(audit["created_at"].replace("Z", "+00:00")),
            completedAt=datetime.fromisoformat(audit["completed_at"].replace("Z", "+00:00")) if audit.get("completed_at") else None,
        ))

    return AuditListResponse(
        audits=audit_summaries,
        total=total,
        hasMore=offset + len(audits) < total,
    )


@router.get(
    "/{audit_id}",
    response_model=AuditResult,
    responses={
        404: {"model": ErrorResponse, "description": "Audit not found"},
    },
    summary="Get audit details and results",
)
async def get_audit(
    audit_id: UUID,
    user: CurrentUser,
):
    """Get detailed audit results."""
    db = SupabaseService(use_admin=True)

    audit = await db.get_audit(audit_id, user_id=user["id"])

    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit not found",
        )

    return _audit_to_response(audit)


@router.get(
    "/{audit_id}/report",
    responses={
        200: {
            "content": {
                "application/json": {},
                "application/pdf": {},
                "text/markdown": {},
            }
        },
        404: {"model": ErrorResponse, "description": "Audit not found"},
    },
    summary="Download audit report",
)
async def download_report(
    audit_id: UUID,
    user: CurrentUser,
    format: str = Query("json", description="Report format", enum=["json", "pdf", "markdown"]),
):
    """Download the audit report in various formats."""
    db = SupabaseService(use_admin=True)

    audit = await db.get_audit(audit_id, user_id=user["id"])

    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit not found",
        )

    if audit["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audit not completed. Current status: {audit['status']}",
        )

    if format == "json":
        return _audit_to_response(audit)

    elif format == "markdown":
        md_content = _generate_markdown_report(audit)
        return StreamingResponse(
            iter([md_content.encode()]),
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="audit-{audit_id}.md"'
            },
        )

    elif format == "pdf":
        # Generate PDF from markdown
        md_content = _generate_markdown_report(audit)
        pdf_bytes = _generate_pdf_from_markdown(md_content)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="audit-{audit_id}.pdf"'
            },
        )


@router.post(
    "/{audit_id}/retry",
    response_model=AuditJob,
    responses={
        400: {"description": "Audit not in failed state"},
        404: {"model": ErrorResponse, "description": "Audit not found"},
    },
    summary="Retry failed audit",
)
async def retry_audit(
    audit_id: UUID,
    user: CurrentUser,
):
    """Retry a failed audit."""
    db = SupabaseService(use_admin=True)

    audit = await db.get_audit(audit_id, user_id=user["id"])

    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit not found",
        )

    if audit["status"] != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only failed audits can be retried. Current status: {audit['status']}",
        )

    # Reset status and re-queue
    await db.update_audit(audit_id, {
        "status": "queued",
        "error": None,
        "started_at": None,
        "completed_at": None,
    })

    # Queue job in Redis
    try:
        redis_client = get_redis_client()
        job_data = {
            "audit_id": str(audit_id),
            "url": audit["url"],
            "user_id": str(user["id"]),
            "competitors": audit.get("competitors", []),
            "options": audit.get("options", {}),
            "created_at": datetime.utcnow().isoformat(),
            "retry": True,
        }
        redis_client.rpush("audit_queue", json.dumps(job_data))
        logger.info("Audit job re-queued", audit_id=str(audit_id))
    except Exception as e:
        logger.error("Failed to re-queue job", audit_id=str(audit_id), error=str(e))
        await db.update_audit_status(audit_id, "failed", f"Failed to re-queue: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to re-queue audit job",
        )

    return AuditJob(
        id=audit_id,
        status="queued",
        url=audit["url"],
        createdAt=datetime.fromisoformat(audit["created_at"].replace("Z", "+00:00")),
        estimatedCompletionSeconds=120,
    )


def _audit_to_response(audit: dict) -> AuditResult:
    """Convert database audit record to API response."""
    performance_data = audit.get("performance")
    seo_data = audit.get("seo")
    accessibility_data = audit.get("accessibility")
    brand_data = audit.get("brand")
    analysis_data = audit.get("analysis")
    screenshots_data = audit.get("screenshots")

    return AuditResult(
        id=UUID(audit["id"]),
        url=audit["url"],
        status=audit["status"],
        createdAt=datetime.fromisoformat(audit["created_at"].replace("Z", "+00:00")),
        completedAt=datetime.fromisoformat(audit["completed_at"].replace("Z", "+00:00")) if audit.get("completed_at") else None,
        performance=PerformanceMetrics(**performance_data) if performance_data else None,
        seo=SEOMetrics(**seo_data) if seo_data else None,
        accessibility=AccessibilityMetrics(**accessibility_data) if accessibility_data else None,
        brand=BrandElements(**brand_data) if brand_data else None,
        analysis=AnalysisResult(**analysis_data) if analysis_data else None,
        screenshots=Screenshots(**screenshots_data) if screenshots_data else None,
        tokensUsed=audit.get("tokens_used"),
        costUsd=float(audit["cost_usd"]) if audit.get("cost_usd") else None,
        processingTimeMs=audit.get("processing_time_ms"),
        error=audit.get("error"),
    )


def _generate_markdown_report(audit: dict) -> str:
    """Generate a markdown report from audit data."""
    analysis = audit.get("analysis", {})
    performance = audit.get("performance", {})
    seo = audit.get("seo", {})
    brand = audit.get("brand", {})

    md = f"""# Website Audit Report

**URL:** {audit['url']}
**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

---

## Executive Summary

{analysis.get('summary', 'No summary available.')}

## Performance Scores

| Metric | Score |
|--------|-------|
| Performance | {performance.get('score', 'N/A')} |
| SEO | {seo.get('score', 'N/A')} |
| Accessibility | {audit.get('accessibility', {}).get('score', 'N/A')} |

## Performance Metrics

- **First Contentful Paint:** {performance.get('firstContentfulPaint', 'N/A')}s
- **Largest Contentful Paint:** {performance.get('largestContentfulPaint', 'N/A')}s
- **Total Blocking Time:** {performance.get('totalBlockingTime', 'N/A')}ms
- **Cumulative Layout Shift:** {performance.get('cumulativeLayoutShift', 'N/A')}

## Strengths

"""

    for strength in analysis.get('strengths', []):
        md += f"- {strength}\n"

    md += "\n## Weaknesses\n\n"

    for weakness in analysis.get('weaknesses', []):
        md += f"- {weakness}\n"

    md += "\n## Recommendations\n\n"

    for rec in analysis.get('recommendations', []):
        md += f"""### {rec.get('category', 'General').title()} - {rec.get('priority', 'medium').upper()}

**Issue:** {rec.get('issue', 'N/A')}

**Recommendation:** {rec.get('recommendation', 'N/A')}

**Expected Impact:** {rec.get('estimatedImpact', 'N/A')}

---

"""

    md += f"""
## Brand Elements

**Primary Colors:** {', '.join(brand.get('primaryColors', [])) or 'Not detected'}

**Fonts:**
- Headings: {brand.get('fonts', {}).get('headings', 'Not detected')}
- Body: {brand.get('fonts', {}).get('body', 'Not detected')}

---

*Report generated by Sentinel Scout Agent*
"""

    return md


def _generate_pdf_from_markdown(md_content: str) -> bytes:
    """Generate PDF from markdown content."""
    try:
        import markdown
        from weasyprint import HTML

        # Convert markdown to HTML
        html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])

        # Add basic styling
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 40px;
                    line-height: 1.6;
                    color: #333;
                }}
                h1 {{ color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 10px; }}
                h2 {{ color: #1e40af; margin-top: 30px; }}
                h3 {{ color: #3b82f6; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #f8fafc; }}
                hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 30px 0; }}
                ul {{ padding-left: 20px; }}
                li {{ margin: 8px 0; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        # Generate PDF
        pdf = HTML(string=styled_html).write_pdf()
        return pdf

    except ImportError:
        logger.warning("weasyprint not available, returning markdown as PDF placeholder")
        return md_content.encode()
