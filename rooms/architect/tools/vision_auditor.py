"""
Vision Auditor - Self-audits mockups using Claude's vision capabilities.

Analyzes generated mockups for:
- Visual hierarchy and layout
- Brand consistency (colors, fonts)
- Spacing and alignment
- Mobile readiness
- Overall quality score

Uses this score to determine if regeneration is needed.
"""
import base64
import json
from dataclasses import dataclass, field
from typing import Optional, Any
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class VisualHierarchyScore:
    """Visual hierarchy assessment."""
    score: int  # 0-100
    has_clear_cta: bool = False
    has_logical_flow: bool = False
    text_readable: bool = True
    contrast_adequate: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "has_clear_cta": self.has_clear_cta,
            "has_logical_flow": self.has_logical_flow,
            "text_readable": self.text_readable,
            "contrast_adequate": self.contrast_adequate,
            "issues": self.issues
        }


@dataclass
class BrandConsistencyScore:
    """Brand consistency assessment."""
    score: int  # 0-100
    colors_match: bool = False
    fonts_match: bool = False
    voice_appropriate: bool = True
    style_cohesive: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "colors_match": self.colors_match,
            "fonts_match": self.fonts_match,
            "voice_appropriate": self.voice_appropriate,
            "style_cohesive": self.style_cohesive,
            "issues": self.issues
        }


@dataclass
class SpacingScore:
    """Spacing and alignment assessment."""
    score: int  # 0-100
    consistent_margins: bool = True
    proper_padding: bool = True
    elements_aligned: bool = True
    whitespace_balanced: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "consistent_margins": self.consistent_margins,
            "proper_padding": self.proper_padding,
            "elements_aligned": self.elements_aligned,
            "whitespace_balanced": self.whitespace_balanced,
            "issues": self.issues
        }


@dataclass
class MobileReadinessScore:
    """Mobile responsiveness assessment."""
    score: int  # 0-100
    touch_targets_adequate: bool = True
    text_not_too_small: bool = True
    no_horizontal_scroll: bool = True
    navigation_accessible: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "touch_targets_adequate": self.touch_targets_adequate,
            "text_not_too_small": self.text_not_too_small,
            "no_horizontal_scroll": self.no_horizontal_scroll,
            "navigation_accessible": self.navigation_accessible,
            "issues": self.issues
        }


@dataclass
class VisionAuditResult:
    """Complete vision audit result."""
    quality_score: int  # 0-100 overall score
    visual_hierarchy: Optional[VisualHierarchyScore] = None
    brand_consistency: Optional[BrandConsistencyScore] = None
    spacing: Optional[SpacingScore] = None
    mobile_readiness: Optional[MobileReadinessScore] = None
    all_issues: list[dict] = field(default_factory=list)  # [{category, severity, description}]
    suggestions: list[str] = field(default_factory=list)
    should_regenerate: bool = False
    regeneration_focus: list[str] = field(default_factory=list)  # Areas to focus on
    audit_confidence: float = 0.0  # 0-1 confidence in assessment

    def to_dict(self) -> dict:
        return {
            "quality_score": self.quality_score,
            "visual_hierarchy": self.visual_hierarchy.to_dict() if self.visual_hierarchy else None,
            "brand_consistency": self.brand_consistency.to_dict() if self.brand_consistency else None,
            "spacing": self.spacing.to_dict() if self.spacing else None,
            "mobile_readiness": self.mobile_readiness.to_dict() if self.mobile_readiness else None,
            "all_issues": self.all_issues,
            "suggestions": self.suggestions,
            "should_regenerate": self.should_regenerate,
            "regeneration_focus": self.regeneration_focus,
            "audit_confidence": self.audit_confidence
        }

    @property
    def breakdown(self) -> dict:
        """Get score breakdown by category."""
        return {
            "visual_hierarchy": self.visual_hierarchy.score if self.visual_hierarchy else 0,
            "brand_consistency": self.brand_consistency.score if self.brand_consistency else 0,
            "spacing": self.spacing.score if self.spacing else 0,
            "mobile_readiness": self.mobile_readiness.score if self.mobile_readiness else 0
        }


class VisionAuditor:
    """
    Self-audits mockups using Claude's vision capabilities.

    Analyzes screenshots of generated mockups and evaluates:
    - Visual hierarchy and layout
    - Brand consistency with provided brand DNA
    - Spacing and alignment quality
    - Mobile responsiveness indicators

    Returns a quality score that determines if regeneration is needed.
    """

    def __init__(
        self,
        anthropic_client,
        model: str = "claude-sonnet-4-20250514",
        quality_threshold: int = 85
    ):
        """
        Initialize VisionAuditor.

        Args:
            anthropic_client: Anthropic API client
            model: Vision-capable model to use
            quality_threshold: Score below which regeneration is triggered
        """
        self.client = anthropic_client
        self.model = model
        self.quality_threshold = quality_threshold

    async def audit_screenshot(
        self,
        screenshot_base64: str,
        brand_colors: list[str] = None,
        brand_fonts: list[str] = None,
        house_style_rules: Optional[dict] = None,
        target_industry: Optional[str] = None,
        iteration_count: int = 1
    ) -> VisionAuditResult:
        """
        Audit a mockup screenshot using vision capabilities.

        Args:
            screenshot_base64: Base64-encoded screenshot image
            brand_colors: Expected brand colors (hex)
            brand_fonts: Expected brand fonts
            house_style_rules: Agency-specific style rules
            target_industry: Industry for context
            iteration_count: Current iteration number

        Returns:
            VisionAuditResult with quality score and issues
        """
        try:
            # Build the audit prompt
            prompt = self._build_audit_prompt(
                brand_colors=brand_colors,
                brand_fonts=brand_fonts,
                house_style_rules=house_style_rules,
                target_industry=target_industry
            )

            # Ensure proper base64 format
            if screenshot_base64.startswith("data:"):
                # Extract just the base64 part
                screenshot_base64 = screenshot_base64.split(",", 1)[1]

            # Call Claude with vision
            response = await self._call_vision_api(screenshot_base64, prompt)

            # Parse the response
            result = self._parse_audit_response(response)

            # Determine if regeneration is needed
            result.should_regenerate = (
                result.quality_score < self.quality_threshold and
                iteration_count < 3  # Don't regenerate infinitely
            )

            # Identify focus areas for regeneration
            if result.should_regenerate:
                result.regeneration_focus = self._identify_focus_areas(result)

            logger.info(
                "Vision audit completed",
                quality_score=result.quality_score,
                should_regenerate=result.should_regenerate,
                issues_count=len(result.all_issues),
                iteration=iteration_count
            )

            return result

        except Exception as e:
            logger.error("Vision audit failed", error=str(e))
            # Return a default result that allows proceeding
            return VisionAuditResult(
                quality_score=70,  # Assume passable but not great
                should_regenerate=False,
                suggestions=["Vision audit failed - manual review recommended"],
                audit_confidence=0.0
            )

    async def audit_from_file(
        self,
        screenshot_path: str,
        **kwargs
    ) -> VisionAuditResult:
        """
        Audit a mockup from a file path.

        Args:
            screenshot_path: Path to screenshot image
            **kwargs: Additional arguments for audit_screenshot

        Returns:
            VisionAuditResult
        """
        path = Path(screenshot_path)
        if not path.exists():
            raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

        with open(path, "rb") as f:
            screenshot_bytes = f.read()

        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        return await self.audit_screenshot(screenshot_base64, **kwargs)

    async def audit_from_url(
        self,
        screenshot_url: str,
        **kwargs
    ) -> VisionAuditResult:
        """
        Audit a mockup from a URL.

        Args:
            screenshot_url: URL to screenshot image
            **kwargs: Additional arguments for audit_screenshot

        Returns:
            VisionAuditResult
        """
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(screenshot_url)
            response.raise_for_status()

        screenshot_base64 = base64.b64encode(response.content).decode("utf-8")
        return await self.audit_screenshot(screenshot_base64, **kwargs)

    def _build_audit_prompt(
        self,
        brand_colors: list[str] = None,
        brand_fonts: list[str] = None,
        house_style_rules: Optional[dict] = None,
        target_industry: Optional[str] = None
    ) -> str:
        """Build the vision audit prompt."""
        prompt = """You are a professional web design auditor. Analyze this website mockup screenshot and provide a detailed quality assessment.

Evaluate the following aspects and provide scores from 0-100:

1. **Visual Hierarchy** (0-100):
   - Is there a clear call-to-action?
   - Does the layout have logical flow?
   - Is text readable with good contrast?
   - Are important elements emphasized?

2. **Brand Consistency** (0-100):
   - Are the colors appropriate and consistent?
   - Is typography professional and consistent?
   - Does the voice/tone seem appropriate?
   - Is the overall style cohesive?

3. **Spacing & Alignment** (0-100):
   - Are margins consistent throughout?
   - Is padding appropriate around elements?
   - Are elements properly aligned?
   - Is whitespace balanced?

4. **Mobile Readiness** (0-100):
   - Do interactive elements appear large enough for touch?
   - Is text large enough to read?
   - Does the layout appear responsive?
   - Is navigation accessible?
"""

        if brand_colors:
            colors_str = ", ".join(brand_colors[:5])
            prompt += f"\n**Expected Brand Colors**: {colors_str}"

        if brand_fonts:
            fonts_str = ", ".join(brand_fonts[:3])
            prompt += f"\n**Expected Brand Fonts**: {fonts_str}"

        if target_industry:
            prompt += f"\n**Target Industry**: {target_industry}"

        if house_style_rules:
            prompt += f"\n**House Style Rules**: {json.dumps(house_style_rules, indent=2)}"

        prompt += """

Respond with a JSON object in this exact format:
```json
{
  "quality_score": <overall 0-100>,
  "visual_hierarchy": {
    "score": <0-100>,
    "has_clear_cta": <true/false>,
    "has_logical_flow": <true/false>,
    "text_readable": <true/false>,
    "contrast_adequate": <true/false>,
    "issues": ["issue 1", "issue 2"]
  },
  "brand_consistency": {
    "score": <0-100>,
    "colors_match": <true/false>,
    "fonts_match": <true/false>,
    "voice_appropriate": <true/false>,
    "style_cohesive": <true/false>,
    "issues": ["issue 1"]
  },
  "spacing": {
    "score": <0-100>,
    "consistent_margins": <true/false>,
    "proper_padding": <true/false>,
    "elements_aligned": <true/false>,
    "whitespace_balanced": <true/false>,
    "issues": ["issue 1"]
  },
  "mobile_readiness": {
    "score": <0-100>,
    "touch_targets_adequate": <true/false>,
    "text_not_too_small": <true/false>,
    "no_horizontal_scroll": <true/false>,
    "navigation_accessible": <true/false>,
    "issues": ["issue 1"]
  },
  "all_issues": [
    {"category": "visual_hierarchy", "severity": "high|medium|low", "description": "..."}
  ],
  "suggestions": ["Specific improvement suggestion 1", "Suggestion 2"],
  "audit_confidence": <0.0-1.0>
}
```

Be specific about issues and provide actionable suggestions. The quality_score should be a weighted average favoring visual_hierarchy and brand_consistency."""

        return prompt

    async def _call_vision_api(self, screenshot_base64: str, prompt: str) -> str:
        """Call Claude vision API with the screenshot."""
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )

        return message.content[0].text

    def _parse_audit_response(self, response: str) -> VisionAuditResult:
        """Parse the vision API response into structured result."""
        try:
            # Extract JSON from response
            json_match = response
            if "```json" in response:
                json_match = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_match = response.split("```")[1].split("```")[0]

            data = json.loads(json_match.strip())

            # Build component scores
            visual_hierarchy = None
            if "visual_hierarchy" in data:
                vh = data["visual_hierarchy"]
                visual_hierarchy = VisualHierarchyScore(
                    score=vh.get("score", 70),
                    has_clear_cta=vh.get("has_clear_cta", False),
                    has_logical_flow=vh.get("has_logical_flow", False),
                    text_readable=vh.get("text_readable", True),
                    contrast_adequate=vh.get("contrast_adequate", True),
                    issues=vh.get("issues", [])
                )

            brand_consistency = None
            if "brand_consistency" in data:
                bc = data["brand_consistency"]
                brand_consistency = BrandConsistencyScore(
                    score=bc.get("score", 70),
                    colors_match=bc.get("colors_match", False),
                    fonts_match=bc.get("fonts_match", False),
                    voice_appropriate=bc.get("voice_appropriate", True),
                    style_cohesive=bc.get("style_cohesive", True),
                    issues=bc.get("issues", [])
                )

            spacing = None
            if "spacing" in data:
                sp = data["spacing"]
                spacing = SpacingScore(
                    score=sp.get("score", 70),
                    consistent_margins=sp.get("consistent_margins", True),
                    proper_padding=sp.get("proper_padding", True),
                    elements_aligned=sp.get("elements_aligned", True),
                    whitespace_balanced=sp.get("whitespace_balanced", True),
                    issues=sp.get("issues", [])
                )

            mobile_readiness = None
            if "mobile_readiness" in data:
                mr = data["mobile_readiness"]
                mobile_readiness = MobileReadinessScore(
                    score=mr.get("score", 70),
                    touch_targets_adequate=mr.get("touch_targets_adequate", True),
                    text_not_too_small=mr.get("text_not_too_small", True),
                    no_horizontal_scroll=mr.get("no_horizontal_scroll", True),
                    navigation_accessible=mr.get("navigation_accessible", True),
                    issues=mr.get("issues", [])
                )

            return VisionAuditResult(
                quality_score=data.get("quality_score", 70),
                visual_hierarchy=visual_hierarchy,
                brand_consistency=brand_consistency,
                spacing=spacing,
                mobile_readiness=mobile_readiness,
                all_issues=data.get("all_issues", []),
                suggestions=data.get("suggestions", []),
                audit_confidence=data.get("audit_confidence", 0.8)
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to parse vision audit response", error=str(e))
            # Return a default result
            return VisionAuditResult(
                quality_score=70,
                suggestions=["Could not fully parse audit - manual review recommended"],
                audit_confidence=0.3
            )

    def _identify_focus_areas(self, result: VisionAuditResult) -> list[str]:
        """Identify areas that need focus in regeneration."""
        focus_areas = []
        breakdown = result.breakdown

        # Find the weakest areas
        sorted_areas = sorted(breakdown.items(), key=lambda x: x[1])

        for area, score in sorted_areas:
            if score < self.quality_threshold:
                # Map to actionable focus areas
                if area == "visual_hierarchy":
                    focus_areas.append("Improve visual hierarchy - clearer CTA and logical flow")
                elif area == "brand_consistency":
                    focus_areas.append("Better match brand colors and typography")
                elif area == "spacing":
                    focus_areas.append("Fix spacing and alignment issues")
                elif area == "mobile_readiness":
                    focus_areas.append("Improve mobile responsiveness")

        # Add specific issues as focus areas
        for issue in result.all_issues[:3]:  # Top 3 issues
            if issue.get("severity") == "high":
                focus_areas.append(f"Fix: {issue.get('description', 'Unknown issue')}")

        return focus_areas[:5]  # Limit to top 5 focus areas


class VisionAuditComparator:
    """
    Compares original website to generated mockup.

    Provides side-by-side quality comparison and improvement metrics.
    """

    def __init__(self, anthropic_client, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic_client
        self.model = model

    async def compare(
        self,
        original_screenshot_base64: str,
        mockup_screenshot_base64: str,
        brand_colors: list[str] = None
    ) -> dict:
        """
        Compare original website to generated mockup.

        Args:
            original_screenshot_base64: Base64 screenshot of original site
            mockup_screenshot_base64: Base64 screenshot of generated mockup
            brand_colors: Expected brand colors for consistency

        Returns:
            Comparison result with improvement metrics
        """
        prompt = """Compare these two website screenshots:
- Image 1 (left/first): The ORIGINAL website
- Image 2 (right/second): The GENERATED mockup

Analyze improvements and regressions across these dimensions:

1. **Visual Appeal**: Which looks more modern/professional?
2. **Brand Preservation**: Does the mockup maintain the original brand identity?
3. **Layout Improvements**: Is the mockup's layout better organized?
4. **Content Preservation**: Is important content maintained?

Respond with JSON:
```json
{
  "overall_improvement_score": <-100 to +100, positive means mockup is better>,
  "visual_appeal_delta": <-100 to +100>,
  "brand_preservation": <0-100, how well brand is maintained>,
  "layout_improvement": <-100 to +100>,
  "content_preservation": <0-100>,
  "key_improvements": ["list of specific improvements"],
  "potential_issues": ["list of potential concerns"],
  "recommendation": "approve|refine|reject"
}
```"""

        # Clean base64 strings
        if original_screenshot_base64.startswith("data:"):
            original_screenshot_base64 = original_screenshot_base64.split(",", 1)[1]
        if mockup_screenshot_base64.startswith("data:"):
            mockup_screenshot_base64 = mockup_screenshot_base64.split(",", 1)[1]

        message = await self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": original_screenshot_base64
                            }
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": mockup_screenshot_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )

        response = message.content[0].text

        try:
            json_match = response
            if "```json" in response:
                json_match = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_match = response.split("```")[1].split("```")[0]

            return json.loads(json_match.strip())
        except (json.JSONDecodeError, IndexError):
            return {
                "overall_improvement_score": 0,
                "recommendation": "refine",
                "error": "Could not parse comparison result"
            }
