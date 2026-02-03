"""
Pydantic models for audit requests and responses.
Based on OpenAPI specification from the implementation plan.
"""
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class AuditOptions(BaseModel):
    """Options for customizing audit behavior."""
    includeMobile: bool = Field(default=True, description="Include mobile viewport analysis")
    includeSeo: bool = Field(default=True, description="Include SEO analysis")
    includeAccessibility: bool = Field(default=True, description="Include accessibility audit")
    customPrompt: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Additional analysis instructions for AI"
    )


class CreateAuditRequest(BaseModel):
    """Request body for creating a new audit."""
    url: HttpUrl = Field(..., description="Website URL to audit")
    competitors: Optional[list[HttpUrl]] = Field(
        default=None,
        max_length=5,
        description="Optional competitor URLs for comparison"
    )
    options: Optional[AuditOptions] = Field(default_factory=AuditOptions)


class AuditJob(BaseModel):
    """Response for queued audit job."""
    id: UUID
    status: Literal["queued", "processing", "completed", "failed"]
    url: str
    createdAt: datetime
    estimatedCompletionSeconds: int = Field(default=120)


class AuditSummary(BaseModel):
    """Summary view of an audit for list endpoints."""
    id: UUID
    url: str
    status: Literal["queued", "processing", "completed", "failed"]
    performanceScore: Optional[int] = Field(default=None, ge=0, le=100)
    createdAt: datetime
    completedAt: Optional[datetime] = None


class PerformanceMetrics(BaseModel):
    """Lighthouse performance metrics."""
    score: int = Field(ge=0, le=100)
    firstContentfulPaint: float = Field(description="Seconds")
    largestContentfulPaint: float
    totalBlockingTime: float
    cumulativeLayoutShift: float
    speedIndex: float


class SEOIssue(BaseModel):
    """SEO issue detail."""
    severity: Literal["critical", "warning", "info"]
    message: str


class SEOMetrics(BaseModel):
    """SEO audit results."""
    score: int = Field(ge=0, le=100)
    title: str = ""
    metaDescription: Optional[str] = None
    h1Tags: list[str] = Field(default_factory=list)
    missingAltTexts: int = 0
    issues: list[SEOIssue] = Field(default_factory=list)


class AccessibilityIssue(BaseModel):
    """Accessibility issue detail."""
    severity: str
    element: Optional[str] = None
    message: str


class AccessibilityMetrics(BaseModel):
    """Accessibility audit results."""
    score: int = Field(ge=0, le=100)
    issues: list[AccessibilityIssue] = Field(default_factory=list)


class CTA(BaseModel):
    """Call-to-action element."""
    text: str
    href: str
    prominence: Literal["primary", "secondary", "tertiary"]


class BrandElements(BaseModel):
    """Extracted brand elements."""
    primaryColors: list[str] = Field(default_factory=list, description="Hex color codes")
    secondaryColors: list[str] = Field(default_factory=list)
    fonts: dict = Field(default_factory=lambda: {"headings": None, "body": None})
    logoUrl: Optional[str] = None
    ctas: list[CTA] = Field(default_factory=list)


class Recommendation(BaseModel):
    """AI-generated recommendation."""
    category: Literal["performance", "seo", "ux", "content", "technical", "brand"]
    priority: Literal["critical", "high", "medium", "low"]
    issue: str
    recommendation: str
    estimatedImpact: str


class CompetitorComparison(BaseModel):
    """Comparison with a competitor."""
    url: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """AI analysis results."""
    summary: str = Field(description="Executive summary of findings")
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    competitorComparison: Optional[list[CompetitorComparison]] = None


class Screenshots(BaseModel):
    """Screenshot URLs."""
    desktop: Optional[str] = None
    mobile: Optional[str] = None


class AuditResult(BaseModel):
    """Complete audit result."""
    id: UUID
    url: str
    status: Literal["queued", "processing", "completed", "failed"]
    createdAt: datetime
    completedAt: Optional[datetime] = None

    # Lighthouse metrics
    performance: Optional[PerformanceMetrics] = None
    seo: Optional[SEOMetrics] = None
    accessibility: Optional[AccessibilityMetrics] = None

    # Brand extraction
    brand: Optional[BrandElements] = None

    # AI analysis
    analysis: Optional[AnalysisResult] = None

    # Screenshots
    screenshots: Optional[Screenshots] = None

    # Metadata
    tokensUsed: Optional[int] = None
    costUsd: Optional[float] = None
    processingTimeMs: Optional[int] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True
