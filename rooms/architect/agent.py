"""
ArchitectAgent - Autonomous Production Forge.

Multi-tool coordinator that orchestrates the "Unfair Pitch" workflow:
1. Extract Brand DNA
2. Synthesize Pitch Strategy (using triage signals)
3. Generate Production Mockup with cascading prompts
4. Vision Self-Audit with quality gates
5. Autonomous Iteration until quality threshold met

Uses:
- WorkflowExecutor for n8n-style graph execution
- PromptComposer for cascading prompts (Cursor-style)
- VisionAuditor for self-audit
- MCPToolLoader for custom agency tools
"""
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext, load_agent_config
from rooms.architect.tools.deep_audit import DeepAuditor, AuditResult
from rooms.architect.tools.brand_extractor import BrandExtractor, BrandDNA
from rooms.architect.tools.mockup_generator import MockupGenerator, MockupConfig, MockupResult
from rooms.architect.tools.vision_auditor import VisionAuditor, VisionAuditResult
from rooms.architect.tools.strategy_synthesizer import StrategySynthesizer, PitchStrategy
from rooms.architect.workflow_executor import (
    WorkflowExecutor,
    WorkflowGraph,
    WorkflowContext,
    WorkflowResult,
    DefaultWorkflowBuilder
)
from rooms.architect.prompt_composer import PromptComposer, ComposedPrompt
from rooms.architect.mcp_tool_loader import MCPToolLoader

logger = structlog.get_logger()


class ArchitectAgent(BaseAgent):
    """
    Architect Agent - Autonomous Production Forge.

    Multi-tool coordinator that transforms qualified leads into
    production-ready mockups with self-auditing capabilities.

    Features:
    - Workflow graph execution with quality gates
    - Vision-based self-audit for autonomous iteration
    - Cascading prompts for hyper-customization
    - Custom MCP tool loading for agency extensions

    Workflow:
    1. Load custom workflow (or use default)
    2. Load custom MCP tools for this user
    3. Compose cascading prompts (house style + niche + component)
    4. Execute workflow graph:
       - Extract Brand DNA
       - Synthesize Pitch Strategy
       - Generate Mockup
       - Vision Self-Audit
       - Quality Gate → Iterate or Complete
    5. Return results with live preview URL
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        # Core tools
        auditor: Optional[DeepAuditor] = None,
        extractor: Optional[BrandExtractor] = None,
        generator: Optional[MockupGenerator] = None,
        e2b_service: Optional[Any] = None,
        # New tools for autonomous forge
        vision_auditor: Optional[VisionAuditor] = None,
        strategy_synthesizer: Optional[StrategySynthesizer] = None,
        # Orchestration components
        workflow_executor: Optional[WorkflowExecutor] = None,
        prompt_composer: Optional[PromptComposer] = None,
        mcp_tool_loader: Optional[MCPToolLoader] = None,
    ):
        super().__init__(config, db_service)

        # Core tools
        self.auditor = auditor or DeepAuditor()
        self.extractor = extractor or BrandExtractor()
        self.e2b_service = e2b_service

        # Generator needs anthropic client for AI generation
        self.generator = generator or MockupGenerator(
            e2b_service=e2b_service,
            anthropic_client=self.anthropic
        )

        # New autonomous forge tools
        self.vision_auditor = vision_auditor or VisionAuditor(
            anthropic_client=self.anthropic,
            quality_threshold=config.extra_config.get("quality_threshold", 85)
        )
        self.strategy_synthesizer = strategy_synthesizer or StrategySynthesizer(
            anthropic_client=self.anthropic
        )

        # Orchestration components
        self.workflow_executor = workflow_executor or WorkflowExecutor(
            max_iterations=config.extra_config.get("max_iterations", 3),
            quality_threshold=config.extra_config.get("quality_threshold", 85)
        )
        self.prompt_composer = prompt_composer or PromptComposer(db_service)
        self.mcp_loader = mcp_tool_loader or MCPToolLoader(db_service) if db_service else None

        # Register core tools with workflow executor
        self._register_workflow_tools()

    def _register_workflow_tools(self):
        """Register tools with the workflow executor."""
        # Brand extraction tool
        async def brand_extract_tool(context: WorkflowContext, **kwargs) -> dict:
            html = await self._fetch_html(context.lead_id)  # We'll get URL from context
            url = context.node_results.get("url", "")
            result = await self.extractor.extract_from_html(url, html)
            return result.to_dict() if hasattr(result, "to_dict") else result

        # Strategy synthesis tool
        async def strategy_synthesis_tool(context: WorkflowContext, **kwargs) -> dict:
            result = await self.strategy_synthesizer.synthesize(
                triage_signals=context.triage_signals,
                brand_dna=context.brand_dna,
                industry=context.brand_dna.get("voice", {}).get("industry")
            )
            return result.to_dict() if hasattr(result, "to_dict") else result

        # Mockup generation tool
        async def mockup_generate_tool(context: WorkflowContext, **kwargs) -> dict:
            # Compose prompts with cascading layers
            composed = await self.prompt_composer.compose(
                house_style=context.house_style,
                niche=context.brand_dna.get("voice", {}).get("industry"),
                brand_dna=context.brand_dna,
                pitch_strategy=context.pitch_strategy,
                regeneration_focus=kwargs.get("regeneration_focus"),
                user_id=UUID(context.user_id) if context.user_id else None
            )

            # Build brand object
            brand = self._build_brand_from_context(context)

            # Build config from pitch strategy
            mockup_config = self._build_mockup_config_from_strategy(context.pitch_strategy)

            # Generate mockup
            result = await self.generator.generate(
                brand=brand,
                audit=None,  # We don't need audit for generation
                config=mockup_config,
                use_ai=True,
                custom_prompt=composed.full_prompt
            )

            return {
                "preview_url": result.preview_url if hasattr(result, "preview_url") else None,
                "sandbox_id": result.sandbox_id if hasattr(result, "sandbox_id") else None,
                "screenshot": result.screenshot if hasattr(result, "screenshot") else None,
                "code": result.generated_code if hasattr(result, "generated_code") else None
            }

        # Vision audit tool
        async def vision_audit_tool(context: WorkflowContext, **kwargs) -> dict:
            if not context.current_screenshot:
                return {"quality_score": 70, "should_regenerate": False}

            # Get brand colors and fonts
            colors = context.brand_dna.get("colors", {})
            brand_colors = [
                colors.get("primary"),
                colors.get("secondary"),
                colors.get("accent")
            ]
            brand_colors = [c for c in brand_colors if c]

            typography = context.brand_dna.get("typography", {})
            brand_fonts = [
                typography.get("primary_font"),
                typography.get("secondary_font")
            ]
            brand_fonts = [f for f in brand_fonts if f]

            result = await self.vision_auditor.audit_screenshot(
                screenshot_base64=context.current_screenshot,
                brand_colors=brand_colors,
                brand_fonts=brand_fonts,
                house_style_rules=context.house_style,
                target_industry=context.brand_dna.get("voice", {}).get("industry"),
                iteration_count=context.iteration_count
            )

            return result.to_dict() if hasattr(result, "to_dict") else result

        # Register tools
        self.workflow_executor.register_tool("brand_extract", brand_extract_tool)
        self.workflow_executor.register_tool("strategy_synthesis", strategy_synthesis_tool)
        self.workflow_executor.register_tool("mockup_generate", mockup_generate_tool)
        self.workflow_executor.register_tool("vision_audit", vision_audit_tool)

        # Also register with base agent for direct calls
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
        Execute autonomous production forge workflow.

        Args:
            context: AgentRunContext with input_data containing:
                - url: URL to architect
                - lead_id: Lead ID for tracking
                - triage_signals: Signals from triage
                - user_id: User ID for custom tools/prompts
                - workflow_id: Optional custom workflow ID
                - playbook_config: Optional playbook configuration

        Returns:
            dict with:
                - url: Original URL
                - brand_dna: Extracted brand DNA
                - pitch_strategy: Synthesized pitch strategy
                - mockup: Generated mockup with preview URL
                - quality_score: Final quality score
                - iteration_count: Number of iterations taken
                - audit_results: Vision audit breakdown
        """
        url = context.input_data.get("url")
        lead_id = context.input_data.get("lead_id", str(uuid4()))
        user_id = context.input_data.get("user_id")
        triage_signals = context.input_data.get("triage_signals", {})
        workflow_id = context.input_data.get("workflow_id")
        playbook_config = context.input_data.get("playbook_config", {})

        if not url:
            raise ValueError("No URL provided in input_data")

        logger.info(
            "Starting autonomous production forge",
            run_id=str(context.run_id),
            url=url,
            lead_id=lead_id,
            has_custom_workflow=workflow_id is not None
        )

        # Load custom workflow or use default
        workflow = await self._load_workflow(workflow_id, user_id)

        # Load custom MCP tools for this user
        custom_tools = {}
        if self.mcp_loader and user_id:
            custom_tools = await self.mcp_loader.load_user_tools(UUID(user_id))
            # Register custom tools with workflow executor
            for tool_name, tool_wrapper in custom_tools.items():
                self.workflow_executor.register_tool(tool_name, tool_wrapper)

        # Load house style from playbook or database
        house_style = await self._load_house_style(user_id, playbook_config)

        # Build workflow context
        workflow_context = WorkflowContext(
            lead_id=lead_id,
            user_id=user_id,
            triage_signals=triage_signals,
            house_style=house_style
        )
        workflow_context.node_results["url"] = url

        # Execute workflow
        result = await self.workflow_executor.execute(
            workflow=workflow,
            context=workflow_context,
            tools=custom_tools
        )

        # Build final output
        output = {
            "url": url,
            "success": result.success,
            "brand_dna": workflow_context.brand_dna,
            "pitch_strategy": workflow_context.pitch_strategy,
            "mockup_url": result.preview_url,
            "sandbox_id": result.sandbox_id,
            "quality_score": result.quality_score,
            "iteration_count": result.iteration_count,
            "audit_results": workflow_context.node_results.get("self_audit", {}),
            "total_duration_ms": result.total_duration_ms
        }

        # Store generated assets if we have db_service
        if self.db_service and result.success:
            await self._store_generated_asset(
                lead_id=lead_id,
                preview_url=result.preview_url,
                sandbox_id=result.sandbox_id,
                quality_score=result.quality_score,
                iteration_count=result.iteration_count,
                brand_dna=workflow_context.brand_dna,
                audit_results=workflow_context.node_results.get("self_audit", {})
            )

        logger.info(
            "Autonomous production forge completed",
            run_id=str(context.run_id),
            url=url,
            success=result.success,
            quality_score=result.quality_score,
            iterations=result.iteration_count,
            duration_ms=result.total_duration_ms
        )

        return output

    async def run_simple(self, context: AgentRunContext) -> dict:
        """
        Execute simple (non-workflow) architect process.

        Useful for quick mockups without quality gates.
        Falls back to original 4-step linear workflow.
        """
        url = context.input_data.get("url")
        triage_signals = context.input_data.get("triage_signals", {})
        playbook_config = context.input_data.get("playbook_config", {})

        if not url:
            raise ValueError("No URL provided in input_data")

        logger.info(
            "Starting simple architect workflow",
            run_id=str(context.run_id),
            url=url
        )

        # Step 1: Deep audit
        audit_result = await self.call_tool("deep_audit", url=url)

        # Step 2: Extract brand DNA
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

        return {
            "url": url,
            "audit": audit_result.to_dict() if hasattr(audit_result, 'to_dict') else audit_result,
            "brand": brand_result.to_dict() if hasattr(brand_result, 'to_dict') else brand_result,
            "mockup": mockup_result.to_dict() if hasattr(mockup_result, 'to_dict') else mockup_result,
            "recommendations": recommendations,
            "mockup_url": mockup_result.preview_url if hasattr(mockup_result, 'preview_url') else None,
            "sandbox_id": mockup_result.sandbox_id if hasattr(mockup_result, 'sandbox_id') else None,
        }

    async def regenerate(
        self,
        lead_id: str,
        focus_areas: list[str] = None,
        user_id: Optional[str] = None
    ) -> dict:
        """
        Regenerate mockup for a lead with specific focus areas.

        Args:
            lead_id: Lead ID to regenerate for
            focus_areas: Specific areas to focus on
            user_id: User ID for custom prompts

        Returns:
            Regeneration result
        """
        # Load existing context from database
        existing = await self._load_existing_context(lead_id)
        if not existing:
            raise ValueError(f"No existing context for lead: {lead_id}")

        # Build regeneration context
        workflow_context = WorkflowContext(
            lead_id=lead_id,
            user_id=user_id,
            brand_dna=existing.get("brand_dna", {}),
            triage_signals=existing.get("triage_signals", {}),
            house_style=existing.get("house_style", {}),
            iteration_count=existing.get("iteration_count", 1) + 1,
            pitch_strategy=existing.get("pitch_strategy", {})
        )

        # Compose prompts with regeneration focus
        composed = await self.prompt_composer.compose(
            house_style=workflow_context.house_style,
            niche=workflow_context.brand_dna.get("voice", {}).get("industry"),
            brand_dna=workflow_context.brand_dna,
            pitch_strategy=workflow_context.pitch_strategy,
            regeneration_focus=focus_areas,
            user_id=UUID(user_id) if user_id else None
        )

        # Build brand object
        brand = self._build_brand_from_context(workflow_context)

        # Generate new mockup
        mockup_config = self._build_mockup_config_from_strategy(workflow_context.pitch_strategy)
        result = await self.generator.generate(
            brand=brand,
            audit=None,
            config=mockup_config,
            use_ai=True,
            custom_prompt=composed.full_prompt
        )

        # Vision audit the new mockup
        if hasattr(result, "screenshot") and result.screenshot:
            audit_result = await self.vision_auditor.audit_screenshot(
                screenshot_base64=result.screenshot,
                brand_colors=[
                    workflow_context.brand_dna.get("colors", {}).get("primary"),
                ],
                iteration_count=workflow_context.iteration_count
            )
        else:
            audit_result = VisionAuditResult(quality_score=70, should_regenerate=False)

        return {
            "lead_id": lead_id,
            "mockup_url": result.preview_url if hasattr(result, "preview_url") else None,
            "sandbox_id": result.sandbox_id if hasattr(result, "sandbox_id") else None,
            "quality_score": audit_result.quality_score,
            "iteration_count": workflow_context.iteration_count,
            "should_regenerate": audit_result.should_regenerate
        }

    # ==================
    # Tool Wrappers
    # ==================

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
            use_ai=True
        )

    # ==================
    # Helper Methods
    # ==================

    async def _load_workflow(
        self,
        workflow_id: Optional[str],
        user_id: Optional[str]
    ) -> WorkflowGraph:
        """Load workflow from database or use default."""
        if workflow_id and self.db_service:
            try:
                workflow_data = await self.db_service.get_architect_workflow(workflow_id)
                if workflow_data:
                    return WorkflowGraph.from_dict(workflow_data["graph"])
            except Exception as e:
                logger.warning("Failed to load custom workflow", error=str(e))

        # Use default workflow
        return DefaultWorkflowBuilder.build_default_workflow(
            quality_threshold=self.config.extra_config.get("quality_threshold", 85),
            max_iterations=self.config.extra_config.get("max_iterations", 3)
        )

    async def _load_house_style(
        self,
        user_id: Optional[str],
        playbook_config: dict
    ) -> dict:
        """Load house style from playbook or database."""
        # Check playbook first
        if playbook_config.get("house_style"):
            return playbook_config["house_style"]

        # Try to load from agent config in database
        if user_id and self.db_service:
            try:
                agent_data = await self.db_service.get_agent_for_user(
                    user_id=user_id,
                    slug="architect"
                )
                if agent_data and agent_data.get("house_styles"):
                    return agent_data["house_styles"]
            except Exception as e:
                logger.warning("Failed to load house style", error=str(e))

        return {}

    async def _load_existing_context(self, lead_id: str) -> Optional[dict]:
        """Load existing context for a lead."""
        if not self.db_service:
            return None

        try:
            # Get the most recent generated asset for this lead
            asset = await self.db_service.get_latest_asset_for_lead(lead_id)
            if asset:
                return {
                    "brand_dna": asset.get("brand_dna", {}),
                    "triage_signals": {},  # Would need to load from lead
                    "house_style": {},
                    "iteration_count": asset.get("iteration_count", 1),
                    "pitch_strategy": {}
                }
        except Exception as e:
            logger.warning("Failed to load existing context", error=str(e))

        return None

    async def _store_generated_asset(
        self,
        lead_id: str,
        preview_url: Optional[str],
        sandbox_id: Optional[str],
        quality_score: int,
        iteration_count: int,
        brand_dna: dict,
        audit_results: dict
    ):
        """Store generated asset in database."""
        if not self.db_service:
            return

        try:
            await self.db_service.create_generated_asset({
                "lead_id": lead_id,
                "asset_type": "mockup_image",
                "storage_provider": "e2b",
                "storage_path": sandbox_id or "",
                "public_url": preview_url,
                "sandbox_id": sandbox_id,
                "preview_url": preview_url,
                "quality_score": quality_score,
                "iteration_count": iteration_count,
                "brand_dna": brand_dna,
                "audit_results": audit_results,
                "is_latest": True
            })
        except Exception as e:
            logger.warning("Failed to store generated asset", error=str(e))

    def _build_brand_from_context(self, context: WorkflowContext) -> BrandDNA:
        """Build BrandDNA object from workflow context."""
        from rooms.architect.tools.brand_extractor import (
            BrandDNA, ColorPalette, Typography, BrandVoice
        )

        brand_data = context.brand_dna

        colors = brand_data.get("colors", {})
        color_palette = ColorPalette(
            primary=colors.get("primary"),
            secondary=colors.get("secondary"),
            accent=colors.get("accent"),
            background=colors.get("background"),
            text=colors.get("text"),
            all_colors=colors.get("all_colors", [])
        )

        typography_data = brand_data.get("typography", {})
        typography = Typography(
            primary_font=typography_data.get("primary_font"),
            secondary_font=typography_data.get("secondary_font"),
            heading_font=typography_data.get("heading_font"),
            body_font=typography_data.get("body_font"),
            font_families=typography_data.get("font_families", []),
            google_fonts=typography_data.get("google_fonts", [])
        )

        voice_data = brand_data.get("voice", {})
        voice = BrandVoice(
            tone=voice_data.get("tone", "professional"),
            industry=voice_data.get("industry"),
            keywords=voice_data.get("keywords", []),
            tagline=voice_data.get("tagline"),
            description=voice_data.get("description")
        )

        return BrandDNA(
            url=brand_data.get("url", ""),
            domain=brand_data.get("domain", ""),
            company_name=brand_data.get("company_name"),
            colors=color_palette,
            typography=typography,
            voice=voice,
            logo_url=brand_data.get("logo_url"),
            favicon_url=brand_data.get("favicon_url"),
            social_links=brand_data.get("social_links", []),
            extraction_confidence=brand_data.get("extraction_confidence", 0.0)
        )

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

    def _build_mockup_config_from_strategy(self, pitch_strategy: dict) -> MockupConfig:
        """Build mockup configuration from pitch strategy."""
        sections = pitch_strategy.get("recommended_sections", [])
        section_names = [s.get("component_type", "").lower() for s in sections if isinstance(s, dict)]

        return MockupConfig(
            template="modern-professional",
            framework="nextjs",
            include_hero="hero" in section_names or True,  # Always include hero
            include_features="features" in section_names,
            include_testimonials="testimonials" in section_names,
            include_pricing="pricing" in section_names,
            include_contact="cta" in section_names,
            include_footer=True,
            responsive=True
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

    async def _generate_recommendations(
        self,
        url: str,
        audit: AuditResult,
        brand: BrandDNA,
        triage_signals: dict
    ) -> dict:
        """Generate AI-powered recommendations based on audit and brand."""
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
