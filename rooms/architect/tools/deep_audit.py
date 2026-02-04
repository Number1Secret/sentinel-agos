"""
Deep Auditor - Comprehensive website analysis for Architect room.

Performs full Lighthouse audits and extracts detailed metrics:
- Performance (Core Web Vitals)
- SEO analysis
- Accessibility audit
- Best practices check
"""
import asyncio
import subprocess
import json
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Any
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class PerformanceMetrics:
    """Core Web Vitals and performance metrics."""
    score: int  # 0-100
    first_contentful_paint: Optional[float] = None  # ms
    largest_contentful_paint: Optional[float] = None  # ms
    cumulative_layout_shift: Optional[float] = None
    total_blocking_time: Optional[float] = None  # ms
    speed_index: Optional[float] = None  # ms
    time_to_interactive: Optional[float] = None  # ms

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "fcp": self.first_contentful_paint,
            "lcp": self.largest_contentful_paint,
            "cls": self.cumulative_layout_shift,
            "tbt": self.total_blocking_time,
            "speed_index": self.speed_index,
            "tti": self.time_to_interactive
        }


@dataclass
class SEOMetrics:
    """SEO audit results."""
    score: int  # 0-100
    has_title: bool = False
    has_meta_description: bool = False
    has_viewport: bool = False
    has_hreflang: bool = False
    is_crawlable: bool = True
    has_canonical: bool = False
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "has_title": self.has_title,
            "has_meta_description": self.has_meta_description,
            "has_viewport": self.has_viewport,
            "has_hreflang": self.has_hreflang,
            "is_crawlable": self.is_crawlable,
            "has_canonical": self.has_canonical,
            "issues": self.issues
        }


@dataclass
class AccessibilityMetrics:
    """Accessibility audit results."""
    score: int  # 0-100
    issues: list[dict] = field(default_factory=list)  # {id, title, description}
    passing_audits: int = 0
    failing_audits: int = 0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "issues": self.issues,
            "passing_audits": self.passing_audits,
            "failing_audits": self.failing_audits
        }


@dataclass
class AuditResult:
    """Complete deep audit result."""
    url: str
    success: bool
    performance: Optional[PerformanceMetrics] = None
    seo: Optional[SEOMetrics] = None
    accessibility: Optional[AccessibilityMetrics] = None
    best_practices_score: Optional[int] = None
    screenshot_base64: Optional[str] = None
    audit_time_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "success": self.success,
            "performance": self.performance.to_dict() if self.performance else None,
            "seo": self.seo.to_dict() if self.seo else None,
            "accessibility": self.accessibility.to_dict() if self.accessibility else None,
            "best_practices_score": self.best_practices_score,
            "has_screenshot": self.screenshot_base64 is not None,
            "audit_time_ms": self.audit_time_ms,
            "error": self.error
        }

    @property
    def overall_score(self) -> int:
        """Calculate overall score averaging all categories."""
        scores = []
        if self.performance:
            scores.append(self.performance.score)
        if self.seo:
            scores.append(self.seo.score)
        if self.accessibility:
            scores.append(self.accessibility.score)
        if self.best_practices_score:
            scores.append(self.best_practices_score)

        if not scores:
            return 0
        return int(sum(scores) / len(scores))


class DeepAuditor:
    """
    Performs comprehensive website audits using Lighthouse.

    Provides detailed metrics for:
    - Performance (Core Web Vitals)
    - SEO
    - Accessibility
    - Best Practices
    """

    def __init__(
        self,
        timeout_seconds: int = 120,
        categories: list[str] = None
    ):
        self.timeout_seconds = timeout_seconds
        self.categories = categories or ["performance", "seo", "accessibility", "best-practices"]

    async def audit_url(
        self,
        url: str,
        include_screenshot: bool = True
    ) -> AuditResult:
        """
        Perform full Lighthouse audit on a URL.

        Args:
            url: URL to audit
            include_screenshot: Whether to capture screenshot

        Returns:
            AuditResult with all metrics
        """
        import time
        start_time = time.time()

        try:
            # Run Lighthouse via CLI
            lighthouse_result = await self._run_lighthouse(url)

            if not lighthouse_result:
                return AuditResult(
                    url=url,
                    success=False,
                    error="Lighthouse audit failed"
                )

            # Parse results
            performance = self._parse_performance(lighthouse_result)
            seo = self._parse_seo(lighthouse_result)
            accessibility = self._parse_accessibility(lighthouse_result)
            best_practices = self._parse_best_practices(lighthouse_result)

            # Get screenshot if requested
            screenshot = None
            if include_screenshot:
                screenshot = lighthouse_result.get("audits", {}).get(
                    "final-screenshot", {}
                ).get("details", {}).get("data")

            audit_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "Deep audit completed",
                url=url,
                performance_score=performance.score if performance else None,
                audit_time_ms=audit_time_ms
            )

            return AuditResult(
                url=url,
                success=True,
                performance=performance,
                seo=seo,
                accessibility=accessibility,
                best_practices_score=best_practices,
                screenshot_base64=screenshot,
                audit_time_ms=audit_time_ms
            )

        except Exception as e:
            logger.error("Deep audit failed", url=url, error=str(e))
            return AuditResult(
                url=url,
                success=False,
                error=str(e),
                audit_time_ms=int((time.time() - start_time) * 1000)
            )

    async def _run_lighthouse(self, url: str) -> Optional[dict]:
        """
        Run Lighthouse CLI and return JSON results.

        Falls back to PageSpeed Insights API if CLI unavailable.
        """
        # Try CLI first
        try:
            return await self._run_lighthouse_cli(url)
        except FileNotFoundError:
            logger.warning("Lighthouse CLI not found, trying PageSpeed API")
            return await self._run_pagespeed_api(url)

    async def _run_lighthouse_cli(self, url: str) -> Optional[dict]:
        """Run Lighthouse via CLI."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            categories_arg = ",".join(self.categories)
            cmd = [
                "npx", "lighthouse", url,
                f"--output-path={output_path}",
                "--output=json",
                f"--only-categories={categories_arg}",
                "--chrome-flags='--headless --no-sandbox'",
                "--quiet"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                raise TimeoutError(f"Lighthouse timed out after {self.timeout_seconds}s")

            if process.returncode != 0:
                return None

            with open(output_path, "r") as f:
                return json.load(f)

        finally:
            Path(output_path).unlink(missing_ok=True)

    async def _run_pagespeed_api(self, url: str) -> Optional[dict]:
        """Run audit via PageSpeed Insights API."""
        import os
        import httpx

        api_key = os.getenv("PAGESPEED_API_KEY")
        if not api_key:
            logger.warning("No PageSpeed API key available")
            return None

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {
                    "url": url,
                    "key": api_key,
                    "strategy": "mobile",
                    "category": self.categories
                }

                response = await client.get(
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                    params=params
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("lighthouseResult", {})

        except Exception as e:
            logger.error("PageSpeed API failed", error=str(e))

        return None

    def _parse_performance(self, lighthouse: dict) -> Optional[PerformanceMetrics]:
        """Parse performance metrics from Lighthouse result."""
        categories = lighthouse.get("categories", {})
        perf = categories.get("performance", {})
        audits = lighthouse.get("audits", {})

        if not perf:
            return None

        return PerformanceMetrics(
            score=int(perf.get("score", 0) * 100),
            first_contentful_paint=audits.get("first-contentful-paint", {}).get("numericValue"),
            largest_contentful_paint=audits.get("largest-contentful-paint", {}).get("numericValue"),
            cumulative_layout_shift=audits.get("cumulative-layout-shift", {}).get("numericValue"),
            total_blocking_time=audits.get("total-blocking-time", {}).get("numericValue"),
            speed_index=audits.get("speed-index", {}).get("numericValue"),
            time_to_interactive=audits.get("interactive", {}).get("numericValue")
        )

    def _parse_seo(self, lighthouse: dict) -> Optional[SEOMetrics]:
        """Parse SEO metrics from Lighthouse result."""
        categories = lighthouse.get("categories", {})
        seo = categories.get("seo", {})
        audits = lighthouse.get("audits", {})

        if not seo:
            return None

        issues = []
        for audit_id, audit_data in audits.items():
            if audit_data.get("score") == 0 and "seo" in str(audit_data.get("id", "")):
                issues.append(audit_data.get("title", audit_id))

        return SEOMetrics(
            score=int(seo.get("score", 0) * 100),
            has_title=audits.get("document-title", {}).get("score") == 1,
            has_meta_description=audits.get("meta-description", {}).get("score") == 1,
            has_viewport=audits.get("viewport", {}).get("score") == 1,
            has_hreflang=audits.get("hreflang", {}).get("score") == 1,
            is_crawlable=audits.get("is-crawlable", {}).get("score") == 1,
            has_canonical=audits.get("canonical", {}).get("score") == 1,
            issues=issues
        )

    def _parse_accessibility(self, lighthouse: dict) -> Optional[AccessibilityMetrics]:
        """Parse accessibility metrics from Lighthouse result."""
        categories = lighthouse.get("categories", {})
        a11y = categories.get("accessibility", {})
        audits = lighthouse.get("audits", {})

        if not a11y:
            return None

        issues = []
        passing = 0
        failing = 0

        for audit_ref in a11y.get("auditRefs", []):
            audit_id = audit_ref.get("id")
            audit_data = audits.get(audit_id, {})

            if audit_data.get("score") == 0:
                failing += 1
                issues.append({
                    "id": audit_id,
                    "title": audit_data.get("title", ""),
                    "description": audit_data.get("description", "")
                })
            elif audit_data.get("score") == 1:
                passing += 1

        return AccessibilityMetrics(
            score=int(a11y.get("score", 0) * 100),
            issues=issues[:10],  # Limit to top 10 issues
            passing_audits=passing,
            failing_audits=failing
        )

    def _parse_best_practices(self, lighthouse: dict) -> Optional[int]:
        """Parse best practices score."""
        categories = lighthouse.get("categories", {})
        bp = categories.get("best-practices", {})

        if not bp:
            return None

        return int(bp.get("score", 0) * 100)
