"""
ArchitectAgent - Deep audit and mockup generation.

This agent:
1. Performs comprehensive Lighthouse audit
2. Extracts brand DNA (colors, fonts, voice)
3. Generates production-ready mockups
4. Provides live preview via E2B sandbox

Uses Playwright MCP for screenshots and E2B MCP for code execution.
"""
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext, load_agent_config
from rooms.architect.tools.deep_audit import DeepAuditor, AuditResult
from rooms.architect.tools.brand_extractor import BrandExtractor, BrandDNA
from rooms.architect.tools.mockup_generator import MockupGenerator, MockupConfig, MockupResult

logger = structlog.get_logger()


class ArchitectAgent(BaseAgent):
    """
    Architect Agent for deep analysis and mockup generation.

    Workflow:
    1. Deep audit the URL (full Lighthouse)
    2. Extract brand DNA (colors, fonts, voice)
    3. Generate mockup based on brand + improvements
    4. Deploy to E2B sandbox for preview
    5. Return results with preview URL

    For complex sites, uses AI to generate custom code.
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        auditor: Optional[DeepAuditor] = None,
        extractor: Optional[BrandExtractor] = None,
        generator: Optional[MockupGenerator] = None,
        e2b_service: Optional[Any] = None,
    ):
        super().__init__(config, db_service)
        self.auditor = auditor or DeepAuditor()
        self.extractor = extractor or BrandExtractor()

        # Generator needs anthropic client for AI generation
        self.generator = generator or MockupGenerator(
            e2b_service=e2b_service,
            anthropic_client=self.anthropic
        )

        # Register tools
        self.register_tool(
            name="deep_audit",
            func=self._tool_deep_audit,
            schema={"url": {"type": "string"}}
        )
        self.register_tool(
            name="brand_extract",
            func=self._tool_brand_extract,
            schema={"url": {"type": "string"}, "html": {"type": "string"}}
        )
        self.register_tool(
            name="mockup_generate",
            func=self._tool_mockup_generate,
            schema={"brand": {"type": "object"}, "audit": {"type": "object"}}
        )

    async def run(self, context: AgentRunContext) -> dict:
        """
        Execute architect workflow on a qualified lead.

        Args:
            context: AgentRunContext with input_data containing:
                - url: URL to architect
                - triage_signals: Signals from triage (optional)
                - playbook_config: Optional playbook configuration

        Returns:
            dict with:
                - audit: Deep audit results
                - brand: Brand DNA extraction
                - mockup: Generated mockup with preview URL
                - recommendations: AI-generated recommendations
        """
        url = context.input_data.get("url")
        triage_signals = context.input_data.get("triage_signals", {})
        playbook_config = context.input_data.get("playbook_config", {})

        if not url:
            raise ValueError("No URL provided in input_data")

        logger.info(
            "Starting architect workflow",
            run_id=str(context.run_id),
            url=url
        )

        # Step 1: Deep audit
        audit_result = await self.call_tool("deep_audit", url=url)

        # Step 2: Extract brand DNA
        # We need to fetch HTML for brand extraction
        html = await self._fetch_html(url)
        brand_result = await self.call_tool(
            "brand_extract",
            url=url,
            html=html
        )

        # Step 3: Generate mockup
        mockup_config = self._build_mockup_config(playbook_config)
        mockup_result = await self.call_tool(
            "mockup_generate",
            brand=brand_result,
            audit=audit_result,
            config=mockup_config
        )

        # Step 4: Generate AI recommendations
        recommendations = await self._generate_recommendations(
            url=url,
            audit=audit_result,
            brand=brand_result,
            triage_signals=triage_signals
        )

        result = {
            "url": url,
            "audit": audit_result.to_dict() if hasattr(audit_result, 'to_dict') else audit_result,
            "brand": brand_result.to_dict() if hasattr(brand_result, 'to_dict') else brand_result,
            "mockup": mockup_result.to_dict() if hasattr(mockup_result, 'to_dict') else mockup_result,
            "recommendations": recommendations,
            "mockup_url": mockup_result.preview_url if hasattr(mockup_result, 'preview_url') else None,
            "sandbox_id": mockup_result.sandbox_id if hasattr(mockup_result, 'sandbox_id') else None,
        }

        logger.info(
            "Architect workflow completed",
            run_id=str(context.run_id),
            url=url,
            has_mockup=result.get("mockup_url") is not None,
            audit_score=audit_result.overall_score if hasattr(audit_result, 'overall_score') else None
        )

        return result

    async def _tool_deep_audit(self, url: str) -> AuditResult:
        """Tool wrapper for deep audit."""
        return await self.auditor.audit_url(url, include_screenshot=True)

    async def _tool_brand_extract(self, url: str, html: str) -> BrandDNA:
        """Tool wrapper for brand extraction."""
        return await self.extractor.extract_from_html(url, html)

    async def _tool_mockup_generate(
        self,
        brand: BrandDNA,
        audit: AuditResult,
        config: Optional[MockupConfig] = None
    ) -> MockupResult:
        """Tool wrapper for mockup generation."""
        return await self.generator.generate(
            brand=brand,
            audit=audit,
            config=config,
            use_ai=True  # Use AI for better results
        )

    async def _fetch_html(self, url: str) -> str:
        """Fetch HTML content from URL."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                return response.text
        except Exception as e:
            logger.warning("Failed to fetch HTML", url=url, error=str(e))
            return ""

    def _build_mockup_config(self, playbook_config: dict) -> MockupConfig:
        """Build mockup configuration from playbook."""
        mockup_settings = playbook_config.get("mockup", {})

        return MockupConfig(
            template=mockup_settings.get("template", "modern-professional"),
            framework=mockup_settings.get("framework", "nextjs"),
            include_hero=mockup_settings.get("include_hero", True),
            include_features=mockup_settings.get("include_features", True),
            include_testimonials=mockup_settings.get("include_testimonials", False),
            include_pricing=mockup_settings.get("include_pricing", False),
            include_contact=mockup_settings.get("include_contact", True),
            include_footer=mockup_settings.get("include_footer", True),
            responsive=mockup_settings.get("responsive", True)
        )

    async def _generate_recommendations(
        self,
        url: str,
        audit: AuditResult,
        brand: BrandDNA,
        triage_signals: dict
    ) -> dict:
        """
        Generate AI-powered recommendations based on audit and brand.

        Returns prioritized list of improvements.
        """
        # Build context for LLM
        context_parts = [
            f"URL: {url}",
            f"Company: {brand.company_name or 'Unknown'}",
        ]

        if audit.performance:
            context_parts.append(f"Performance Score: {audit.performance.score}/100")
            if audit.performance.largest_contentful_paint:
                context_parts.append(f"LCP: {audit.performance.largest_contentful_paint:.0f}ms")

        if audit.seo:
            context_parts.append(f"SEO Score: {audit.seo.score}/100")
            if audit.seo.issues:
                context_parts.append(f"SEO Issues: {', '.join(audit.seo.issues[:3])}")

        if audit.accessibility:
            context_parts.append(f"Accessibility Score: {audit.accessibility.score}/100")

        if brand.colors and brand.colors.primary:
            context_parts.append(f"Brand Colors: {brand.colors.primary}, {brand.colors.secondary}")

        if triage_signals:
            if triage_signals.get("pagespeed_score"):
                context_parts.append(f"Original PageSpeed: {triage_signals['pagespeed_score']}")
            if not triage_signals.get("mobile_responsive"):
                context_parts.append("Issue: Not mobile responsive")
            if not triage_signals.get("ssl_valid"):
                context_parts.append("Issue: SSL certificate problems")

        messages = [
            {
                "role": "user",
                "content": f"""Based on this website analysis, provide specific improvement recommendations.

{chr(10).join(context_parts)}

Provide recommendations in these categories:
1. Performance (top 3 quick wins)
2. SEO (top 3 improvements)
3. Design/UX (top 3 suggestions)
4. Business Value (estimated impact)

Be specific and actionable. Focus on high-impact, achievable improvements."""
            }
        ]

        try:
            response = await self.call_llm(messages, max_tokens=1000)

            if response.content and len(response.content) > 0:
                return {
                    "text": response.content[0].text,
                    "generated": True
                }
        except Exception as e:
            logger.warning("Failed to generate recommendations", error=str(e))

        # Fallback to rule-based recommendations
        return self._generate_fallback_recommendations(audit, brand)

    def _generate_fallback_recommendations(
        self,
        audit: AuditResult,
        brand: BrandDNA
    ) -> dict:
        """Generate basic recommendations without AI."""
        recommendations = []

        if audit.performance and audit.performance.score < 50:
            recommendations.append("Optimize images and enable compression")
            recommendations.append("Implement lazy loading for below-fold content")
            recommendations.append("Minimize JavaScript bundle size")

        if audit.seo and audit.seo.score < 70:
            if not audit.seo.has_meta_description:
                recommendations.append("Add meta description to improve search snippets")
            if not audit.seo.has_canonical:
                recommendations.append("Add canonical URL to prevent duplicate content")

        if audit.accessibility and audit.accessibility.score < 70:
            recommendations.append("Add alt text to all images")
            recommendations.append("Improve color contrast for readability")
            recommendations.append("Ensure all interactive elements are keyboard accessible")

        if not brand.colors or len(brand.colors.all_colors) < 3:
            recommendations.append("Establish a consistent color palette")

        if not brand.typography or not brand.typography.primary_font:
            recommendations.append("Define consistent typography hierarchy")

        return {
            "text": "\n".join(f"- {r}" for r in recommendations),
            "generated": False,
            "items": recommendations
        }


async def create_architect_agent(
    db_service,
    e2b_service: Optional[Any] = None
) -> ArchitectAgent:
    """
    Factory function to create an ArchitectAgent with config from database.

    Args:
        db_service: Supabase service instance
        e2b_service: Optional E2B service for sandbox execution

    Returns:
        Configured ArchitectAgent
    """
    config = await load_agent_config(db_service, "architect")
    return ArchitectAgent(
        config=config,
        db_service=db_service,
        e2b_service=e2b_service
    )
