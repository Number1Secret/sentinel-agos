"""
Scout Agent - Website Analysis Agent

The Scout Agent performs comprehensive website analysis including:
- Lighthouse performance/SEO/accessibility audits
- Screenshot capture (desktop and mobile)
- Brand element extraction
- AI-powered analysis and recommendations
"""
import asyncio
import time
from pathlib import Path
from typing import Optional
from uuid import UUID

import structlog

from services.anthropic import AnthropicService
from services.browser import BrowserService
from services.lighthouse import LighthouseService

logger = structlog.get_logger()

# Load system prompt
PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "scout_analysis.md").read_text()


class ScoutAgent:
    """
    Scout Agent for website analysis.

    Coordinates Lighthouse audits, screenshot capture, brand extraction,
    and AI analysis to produce comprehensive website audit reports.
    """

    def __init__(
        self,
        anthropic_service: Optional[AnthropicService] = None,
        browser_service: Optional[BrowserService] = None,
        lighthouse_service: Optional[LighthouseService] = None,
    ):
        self.anthropic = anthropic_service or AnthropicService()
        self.browser = browser_service or BrowserService()
        self.lighthouse = lighthouse_service or LighthouseService()

    async def analyze(
        self,
        url: str,
        competitors: list[str] = None,
        options: dict = None,
    ) -> dict:
        """
        Perform comprehensive website analysis.

        Args:
            url: Primary URL to analyze
            competitors: Optional list of competitor URLs for comparison
            options: Analysis options (includeMobile, includeSeo, includeAccessibility, customPrompt)

        Returns:
            Complete audit results dict
        """
        options = options or {}
        include_mobile = options.get("includeMobile", True)
        include_seo = options.get("includeSeo", True)
        include_accessibility = options.get("includeAccessibility", True)
        custom_prompt = options.get("customPrompt")

        start_time = time.time()
        total_tokens = 0
        total_cost = 0.0

        logger.info("Starting Scout analysis", url=url, options=options)

        try:
            # Start browser
            await self.browser.start()

            # Run tasks concurrently
            lighthouse_task = self._run_lighthouse(
                url, include_seo, include_accessibility
            )
            visual_task = self._capture_visuals(url, include_mobile)

            lighthouse_results, visual_results = await asyncio.gather(
                lighthouse_task,
                visual_task,
                return_exceptions=True,
            )

            # Handle exceptions
            if isinstance(lighthouse_results, Exception):
                logger.error("Lighthouse audit failed", error=str(lighthouse_results))
                lighthouse_results = self._empty_lighthouse()

            if isinstance(visual_results, Exception):
                logger.error("Visual capture failed", error=str(visual_results))
                visual_results = {"screenshots": {}, "brand": {}}

            # Run AI analysis
            analysis, tokens, cost = await self.anthropic.analyze_website(
                url=url,
                lighthouse_data={
                    "performance": lighthouse_results.get("performance", {}),
                    "seo": lighthouse_results.get("seo", {}),
                    "accessibility": lighthouse_results.get("accessibility", {}),
                },
                screenshot_base64=visual_results["screenshots"].get("desktop"),
                brand_data=visual_results["brand"],
                custom_prompt=custom_prompt,
            )
            total_tokens += tokens
            total_cost += cost

            # Analyze competitors if provided
            competitor_comparison = None
            if competitors:
                competitor_comparison, comp_tokens, comp_cost = await self._analyze_competitors(
                    url, analysis, competitors
                )
                total_tokens += comp_tokens
                total_cost += comp_cost
                if competitor_comparison:
                    analysis["competitorComparison"] = competitor_comparison

            processing_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "Scout analysis completed",
                url=url,
                processing_time_ms=processing_time_ms,
                tokens_used=total_tokens,
                cost_usd=total_cost,
            )

            return {
                "performance": lighthouse_results.get("performance"),
                "seo": lighthouse_results.get("seo"),
                "accessibility": lighthouse_results.get("accessibility"),
                "brand": visual_results["brand"],
                "analysis": analysis,
                "screenshots": visual_results["screenshots"],
                "tokens_used": total_tokens,
                "cost_usd": total_cost,
                "processing_time_ms": processing_time_ms,
            }

        except Exception as e:
            logger.error("Scout analysis failed", url=url, error=str(e))
            raise

        finally:
            await self.browser.stop()

    async def _run_lighthouse(
        self,
        url: str,
        include_seo: bool,
        include_accessibility: bool,
    ) -> dict:
        """Run Lighthouse audit."""
        categories = ["performance"]
        if include_seo:
            categories.append("seo")
        if include_accessibility:
            categories.append("accessibility")

        return await self.lighthouse.run_audit(url, categories=categories)

    async def _capture_visuals(
        self,
        url: str,
        include_mobile: bool,
    ) -> dict:
        """Capture screenshots and extract brand elements."""
        screenshots = await self.browser.capture_screenshots(url, include_mobile)
        brand = await self.browser.extract_brand_elements(url)

        return {
            "screenshots": screenshots,
            "brand": brand,
        }

    async def _analyze_competitors(
        self,
        main_url: str,
        main_analysis: dict,
        competitor_urls: list[str],
    ) -> tuple[list[dict], int, float]:
        """Analyze competitor websites and compare."""
        total_tokens = 0
        total_cost = 0.0
        competitor_analyses = []

        # Analyze each competitor (simplified - just get basic data)
        for comp_url in competitor_urls[:3]:  # Limit to 3 competitors
            try:
                # Run simplified lighthouse for competitors
                comp_lighthouse = await self.lighthouse.run_audit(
                    comp_url, categories=["performance", "seo"]
                )

                competitor_analyses.append({
                    "url": comp_url,
                    "performance_score": comp_lighthouse.get("performance", {}).get("score", 0),
                    "seo_score": comp_lighthouse.get("seo", {}).get("score", 0),
                })

            except Exception as e:
                logger.warning(
                    "Competitor analysis failed",
                    competitor_url=comp_url,
                    error=str(e),
                )

        # Compare with AI
        if competitor_analyses:
            comparison, tokens, cost = await self.anthropic.compare_competitors(
                main_url, main_analysis, competitor_analyses
            )
            total_tokens += tokens
            total_cost += cost
            return comparison, total_tokens, total_cost

        return [], total_tokens, total_cost

    def _empty_lighthouse(self) -> dict:
        """Return empty Lighthouse structure."""
        return {
            "performance": {
                "score": 0,
                "firstContentfulPaint": 0,
                "largestContentfulPaint": 0,
                "totalBlockingTime": 0,
                "cumulativeLayoutShift": 0,
                "speedIndex": 0,
            },
            "seo": {
                "score": 0,
                "title": "",
                "metaDescription": "",
                "h1Tags": [],
                "missingAltTexts": 0,
                "issues": [],
            },
            "accessibility": {
                "score": 0,
                "issues": [],
            },
        }


async def run_scout_analysis(
    url: str,
    competitors: list[str] = None,
    options: dict = None,
) -> dict:
    """
    Convenience function to run Scout Agent analysis.

    Example:
        result = await run_scout_analysis(
            "https://example.com",
            competitors=["https://competitor.com"],
            options={"includeMobile": True}
        )
    """
    agent = ScoutAgent()
    return await agent.analyze(url, competitors, options)
