"""
Strategy Synthesizer - Cross-references Room 1 signals with brand DNA to create pitch strategy.

Creates compelling value propositions by:
- Analyzing triage signals (PageSpeed, SSL, mobile issues)
- Matching with brand DNA and industry
- Generating targeted pain points and solutions
- Recommending page sections and CTAs
"""
import json
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

import structlog

logger = structlog.get_logger()


class SignalSeverity(Enum):
    """Severity of detected issues."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class PainPoint:
    """Identified pain point from signals."""
    signal: str  # Original signal name
    severity: SignalSeverity
    headline: str  # User-facing pain point headline
    description: str  # Detailed description
    impact: str  # Business impact
    solution_hint: str  # How mockup addresses this

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "severity": self.severity.value,
            "headline": self.headline,
            "description": self.description,
            "impact": self.impact,
            "solution_hint": self.solution_hint
        }


@dataclass
class ValueProposition:
    """Generated value proposition."""
    headline: str
    subheadline: str
    key_benefits: list[str]
    target_audience: str
    differentiator: str

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "subheadline": self.subheadline,
            "key_benefits": self.key_benefits,
            "target_audience": self.target_audience,
            "differentiator": self.differentiator
        }


@dataclass
class RecommendedSection:
    """Recommended page section."""
    name: str
    purpose: str
    priority: int  # 1-10, lower = higher priority
    content_suggestions: list[str]
    component_type: str  # hero, features, testimonials, etc.

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "priority": self.priority,
            "content_suggestions": self.content_suggestions,
            "component_type": self.component_type
        }


@dataclass
class PitchStrategy:
    """Complete pitch strategy for mockup generation."""
    # Core messaging
    headline: str
    tagline: str
    elevator_pitch: str

    # Pain points and solutions
    pain_points: list[PainPoint] = field(default_factory=list)
    value_propositions: list[ValueProposition] = field(default_factory=list)

    # Page structure
    recommended_sections: list[RecommendedSection] = field(default_factory=list)
    cta_text: str = "Get Started"
    cta_secondary: Optional[str] = None

    # Tone and style
    tone_guidance: str = "professional"
    voice_keywords: list[str] = field(default_factory=list)
    avoid_phrases: list[str] = field(default_factory=list)

    # Impact estimates
    estimated_impact: dict = field(default_factory=dict)

    # Metadata
    industry: Optional[str] = None
    target_persona: Optional[str] = None
    confidence_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "tagline": self.tagline,
            "elevator_pitch": self.elevator_pitch,
            "pain_points": [p.to_dict() for p in self.pain_points],
            "value_propositions": [v.to_dict() for v in self.value_propositions],
            "recommended_sections": [s.to_dict() for s in self.recommended_sections],
            "cta_text": self.cta_text,
            "cta_secondary": self.cta_secondary,
            "tone_guidance": self.tone_guidance,
            "voice_keywords": self.voice_keywords,
            "avoid_phrases": self.avoid_phrases,
            "estimated_impact": self.estimated_impact,
            "industry": self.industry,
            "target_persona": self.target_persona,
            "confidence_score": self.confidence_score
        }


class StrategySynthesizer:
    """
    Cross-references Room 1 triage signals with brand DNA to create pitch strategy.

    The "Unfair Pitch" - we know their problems before they tell us!
    """

    # Signal to pain point mapping
    SIGNAL_PAIN_POINTS = {
        "pagespeed": {
            "critical_threshold": 40,
            "high_threshold": 60,
            "headline": "Your Website is Losing Customers to Slow Loading",
            "impact": "53% of visitors leave if a page takes longer than 3 seconds to load",
            "solution": "Lightning-fast performance with optimized images and modern code"
        },
        "ssl_valid": {
            "headline": "Security Warnings Are Scaring Away Your Customers",
            "impact": "85% of users will not proceed if they see 'Not Secure' warning",
            "solution": "Fully secured with SSL/HTTPS to build instant trust"
        },
        "mobile_responsive": {
            "headline": "You're Invisible to Mobile Users",
            "impact": "60% of web traffic is mobile - a non-responsive site loses the majority",
            "solution": "Mobile-first design that looks perfect on any device"
        },
        "copyright_year": {
            "critical_years": 2,
            "headline": "Your Website Looks Outdated",
            "impact": "Users judge credibility in 0.05 seconds - dated design loses trust",
            "solution": "Modern, professional design that reflects your current success"
        },
        "accessibility": {
            "critical_threshold": 70,
            "headline": "Accessibility Issues Limit Your Reach",
            "impact": "15% of population has disabilities - inaccessible sites lose customers and risk legal issues",
            "solution": "WCAG-compliant design accessible to everyone"
        },
        "seo": {
            "critical_threshold": 60,
            "headline": "You're Invisible in Search Results",
            "impact": "75% of users never scroll past the first page of search results",
            "solution": "SEO-optimized structure to help customers find you"
        }
    }

    # Industry-specific CTA suggestions
    INDUSTRY_CTAS = {
        "technology": ["Start Free Trial", "Request Demo", "See it in Action"],
        "healthcare": ["Book Consultation", "Find a Provider", "Get Care Now"],
        "finance": ["Get a Quote", "Calculate Savings", "Open Account"],
        "ecommerce": ["Shop Now", "View Collection", "Get 10% Off"],
        "education": ["Enroll Now", "Start Learning", "Get Free Course"],
        "real_estate": ["Schedule Viewing", "Find Your Home", "Get Property Alerts"],
        "local": ["Call Now", "Book Appointment", "Get Directions"],
        "saas": ["Start Free Trial", "See Pricing", "Watch Demo"]
    }

    # Industry-specific tone guidance
    INDUSTRY_TONES = {
        "technology": "innovative, clear, forward-thinking",
        "healthcare": "trustworthy, caring, professional",
        "finance": "secure, reliable, authoritative",
        "ecommerce": "exciting, urgent, value-focused",
        "education": "inspiring, supportive, knowledgeable",
        "real_estate": "aspirational, local, trustworthy",
        "local": "friendly, reliable, community-focused",
        "saas": "efficient, modern, solution-oriented"
    }

    def __init__(self, anthropic_client=None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize StrategySynthesizer.

        Args:
            anthropic_client: Optional Anthropic client for AI-enhanced synthesis
            model: Model to use for AI enhancement
        """
        self.client = anthropic_client
        self.model = model

    async def synthesize(
        self,
        triage_signals: dict,
        brand_dna: dict,
        industry: Optional[str] = None,
        company_name: Optional[str] = None,
        use_ai_enhancement: bool = True
    ) -> PitchStrategy:
        """
        Synthesize pitch strategy from triage signals and brand DNA.

        Args:
            triage_signals: Dict with keys like pagespeed, ssl_valid, mobile_responsive, etc.
            brand_dna: Extracted brand DNA (colors, fonts, voice)
            industry: Target industry (auto-detected if not provided)
            company_name: Company name for personalization
            use_ai_enhancement: Whether to use AI for enhanced synthesis

        Returns:
            PitchStrategy with messaging and recommendations
        """
        # Auto-detect industry if not provided
        if not industry:
            industry = self._detect_industry(brand_dna, triage_signals)

        # Extract pain points from signals
        pain_points = self._extract_pain_points(triage_signals)

        # Generate base strategy
        strategy = self._generate_base_strategy(
            pain_points=pain_points,
            brand_dna=brand_dna,
            industry=industry,
            company_name=company_name
        )

        # Enhance with AI if available and requested
        if self.client and use_ai_enhancement:
            strategy = await self._enhance_with_ai(
                strategy=strategy,
                triage_signals=triage_signals,
                brand_dna=brand_dna,
                industry=industry,
                company_name=company_name
            )

        logger.info(
            "Strategy synthesized",
            industry=industry,
            pain_points_count=len(pain_points),
            sections_count=len(strategy.recommended_sections),
            confidence=strategy.confidence_score
        )

        return strategy

    def _detect_industry(self, brand_dna: dict, signals: dict) -> Optional[str]:
        """Auto-detect industry from brand DNA."""
        voice = brand_dna.get("voice", {})
        industry = voice.get("industry")

        if industry:
            # Normalize industry names
            industry_mapping = {
                "technology": "technology",
                "tech": "technology",
                "software": "technology",
                "healthcare": "healthcare",
                "health": "healthcare",
                "medical": "healthcare",
                "finance": "finance",
                "financial": "finance",
                "banking": "finance",
                "ecommerce": "ecommerce",
                "e-commerce": "ecommerce",
                "retail": "ecommerce",
                "education": "education",
                "learning": "education",
                "real_estate": "real_estate",
                "property": "real_estate",
                "local": "local",
                "restaurant": "local",
                "service": "local"
            }
            return industry_mapping.get(industry.lower(), industry.lower())

        return None

    def _extract_pain_points(self, signals: dict) -> list[PainPoint]:
        """Extract pain points from triage signals."""
        pain_points = []

        for signal_name, signal_value in signals.items():
            if signal_name not in self.SIGNAL_PAIN_POINTS:
                continue

            config = self.SIGNAL_PAIN_POINTS[signal_name]

            # Determine severity
            severity = self._calculate_signal_severity(signal_name, signal_value, config)
            if severity is None:
                continue  # Signal is fine, not a pain point

            pain_point = PainPoint(
                signal=signal_name,
                severity=severity,
                headline=config["headline"],
                description=self._generate_pain_description(signal_name, signal_value),
                impact=config["impact"],
                solution_hint=config["solution"]
            )
            pain_points.append(pain_point)

        # Sort by severity
        severity_order = {
            SignalSeverity.CRITICAL: 0,
            SignalSeverity.HIGH: 1,
            SignalSeverity.MEDIUM: 2,
            SignalSeverity.LOW: 3
        }
        pain_points.sort(key=lambda x: severity_order[x.severity])

        return pain_points

    def _calculate_signal_severity(
        self,
        signal_name: str,
        signal_value: Any,
        config: dict
    ) -> Optional[SignalSeverity]:
        """Calculate severity of a signal."""
        if signal_name == "pagespeed":
            score = signal_value if isinstance(signal_value, (int, float)) else 100
            if score < config.get("critical_threshold", 40):
                return SignalSeverity.CRITICAL
            elif score < config.get("high_threshold", 60):
                return SignalSeverity.HIGH
            elif score < 80:
                return SignalSeverity.MEDIUM
            return None  # Good score

        elif signal_name == "ssl_valid":
            if signal_value is False or signal_value == "false":
                return SignalSeverity.CRITICAL
            return None

        elif signal_name == "mobile_responsive":
            if signal_value is False or signal_value == "false":
                return SignalSeverity.HIGH
            return None

        elif signal_name == "copyright_year":
            try:
                year = int(signal_value)
                from datetime import datetime
                current_year = datetime.now().year
                age = current_year - year

                if age >= config.get("critical_years", 2):
                    return SignalSeverity.HIGH if age >= 3 else SignalSeverity.MEDIUM
            except (ValueError, TypeError):
                pass
            return None

        elif signal_name in ["accessibility", "seo"]:
            score = signal_value if isinstance(signal_value, (int, float)) else 100
            threshold = config.get("critical_threshold", 70)
            if score < threshold:
                return SignalSeverity.HIGH
            elif score < threshold + 15:
                return SignalSeverity.MEDIUM
            return None

        return None

    def _generate_pain_description(self, signal_name: str, signal_value: Any) -> str:
        """Generate detailed pain point description."""
        descriptions = {
            "pagespeed": f"Your site scores {signal_value}/100 on PageSpeed. Google considers anything below 50 as 'poor' and will rank you lower in search results.",
            "ssl_valid": "Your site shows a 'Not Secure' warning in browsers. This immediately destroys trust and many users will leave without engaging.",
            "mobile_responsive": "Your site doesn't adapt to mobile screens. On mobile devices, content is hard to read and buttons are hard to tap.",
            "copyright_year": f"Your website footer shows © {signal_value}. This signals to visitors that your business may not be active or current.",
            "accessibility": f"Your site scores {signal_value}/100 on accessibility. This means some users cannot navigate or read your content.",
            "seo": f"Your site scores {signal_value}/100 on SEO. You're missing key optimizations that help customers find you in search."
        }
        return descriptions.get(signal_name, f"Issue detected with {signal_name}: {signal_value}")

    def _generate_base_strategy(
        self,
        pain_points: list[PainPoint],
        brand_dna: dict,
        industry: Optional[str],
        company_name: Optional[str]
    ) -> PitchStrategy:
        """Generate base strategy without AI enhancement."""
        # Generate headline based on top pain point
        primary_pain = pain_points[0] if pain_points else None
        headline = self._generate_headline(primary_pain, company_name)

        # Generate tagline
        tagline = self._generate_tagline(industry, brand_dna)

        # Generate elevator pitch
        elevator_pitch = self._generate_elevator_pitch(
            pain_points, industry, company_name
        )

        # Generate value propositions
        value_props = self._generate_value_propositions(pain_points, industry)

        # Generate recommended sections
        sections = self._generate_recommended_sections(pain_points, industry)

        # Get CTA text
        cta_text, cta_secondary = self._get_cta_suggestions(industry)

        # Get tone guidance
        tone = self.INDUSTRY_TONES.get(industry, "professional, trustworthy, clear")

        # Extract voice keywords from brand DNA
        voice_keywords = brand_dna.get("voice", {}).get("keywords", [])

        # Calculate estimated impact
        estimated_impact = self._calculate_estimated_impact(pain_points)

        return PitchStrategy(
            headline=headline,
            tagline=tagline,
            elevator_pitch=elevator_pitch,
            pain_points=pain_points,
            value_propositions=value_props,
            recommended_sections=sections,
            cta_text=cta_text,
            cta_secondary=cta_secondary,
            tone_guidance=tone,
            voice_keywords=voice_keywords[:10],
            estimated_impact=estimated_impact,
            industry=industry,
            confidence_score=0.7  # Base confidence without AI
        )

    def _generate_headline(
        self,
        primary_pain: Optional[PainPoint],
        company_name: Optional[str]
    ) -> str:
        """Generate compelling headline."""
        if primary_pain:
            # Solution-focused headline
            headlines = {
                "pagespeed": "A Faster Website That Converts More Visitors",
                "ssl_valid": "Build Instant Trust With a Secure, Professional Website",
                "mobile_responsive": "Reach Customers on Every Device",
                "copyright_year": "A Modern Website That Reflects Your Success",
                "accessibility": "A Website Everyone Can Use",
                "seo": "Get Found by Customers Searching for You"
            }
            return headlines.get(primary_pain.signal, "Your New Website, Designed to Convert")

        return "A Website Built for Growth"

    def _generate_tagline(self, industry: Optional[str], brand_dna: dict) -> str:
        """Generate tagline based on industry."""
        taglines = {
            "technology": "Innovation meets simplicity",
            "healthcare": "Care you can trust, online",
            "finance": "Your financial partner, online",
            "ecommerce": "Shop the experience",
            "education": "Learn without limits",
            "real_estate": "Find your perfect space",
            "local": "Your neighbors, at your service",
            "saas": "Work smarter, not harder"
        }
        return taglines.get(industry, "Excellence, delivered digitally")

    def _generate_elevator_pitch(
        self,
        pain_points: list[PainPoint],
        industry: Optional[str],
        company_name: Optional[str]
    ) -> str:
        """Generate concise elevator pitch."""
        if not pain_points:
            return f"A modern, professional website designed to grow your business."

        pain_summary = pain_points[0].headline if pain_points else "common issues"
        solution_summary = pain_points[0].solution_hint if pain_points else "modern design"

        name_part = f"for {company_name}" if company_name else "for your business"

        return f"We've identified that {pain_summary.lower()}. Our redesign {name_part} delivers {solution_summary.lower()}, helping you win more customers and grow your business."

    def _generate_value_propositions(
        self,
        pain_points: list[PainPoint],
        industry: Optional[str]
    ) -> list[ValueProposition]:
        """Generate value propositions from pain points."""
        value_props = []

        # Create a VP for each pain point (max 3)
        for pain in pain_points[:3]:
            vp = ValueProposition(
                headline=self._pain_to_value_headline(pain),
                subheadline=pain.solution_hint,
                key_benefits=self._generate_benefits(pain),
                target_audience=self._get_target_audience(industry),
                differentiator="Identified through our comprehensive site audit"
            )
            value_props.append(vp)

        return value_props

    def _pain_to_value_headline(self, pain: PainPoint) -> str:
        """Convert pain point to positive value headline."""
        conversions = {
            "pagespeed": "Lightning-Fast Performance",
            "ssl_valid": "Bank-Level Security",
            "mobile_responsive": "Perfect on Any Device",
            "copyright_year": "Modern, Professional Design",
            "accessibility": "Accessible to Everyone",
            "seo": "Search Engine Optimized"
        }
        return conversions.get(pain.signal, "Professional Quality")

    def _generate_benefits(self, pain: PainPoint) -> list[str]:
        """Generate key benefits for a pain point."""
        benefits_map = {
            "pagespeed": [
                "2x faster page loads",
                "Higher Google rankings",
                "Lower bounce rates",
                "Better user experience"
            ],
            "ssl_valid": [
                "Secure customer data",
                "Trust badges and indicators",
                "No browser warnings",
                "PCI compliance ready"
            ],
            "mobile_responsive": [
                "Touch-optimized interface",
                "Readable on all screens",
                "Mobile-first design",
                "Consistent experience"
            ],
            "copyright_year": [
                "Fresh, modern look",
                "Current design trends",
                "Professional imagery",
                "Updated branding"
            ],
            "accessibility": [
                "WCAG compliance",
                "Screen reader support",
                "Keyboard navigation",
                "Color contrast optimization"
            ],
            "seo": [
                "Proper meta tags",
                "Semantic HTML structure",
                "Fast loading times",
                "Mobile-friendly"
            ]
        }
        return benefits_map.get(pain.signal, ["Professional quality", "Modern design"])

    def _get_target_audience(self, industry: Optional[str]) -> str:
        """Get target audience description for industry."""
        audiences = {
            "technology": "Tech-savvy decision makers and early adopters",
            "healthcare": "Patients seeking trusted healthcare providers",
            "finance": "Individuals and businesses seeking financial services",
            "ecommerce": "Online shoppers looking for quality products",
            "education": "Learners seeking to advance their skills",
            "real_estate": "Home buyers and property seekers",
            "local": "Local community members needing services",
            "saas": "Businesses looking to improve their workflows"
        }
        return audiences.get(industry, "Potential customers seeking your services")

    def _generate_recommended_sections(
        self,
        pain_points: list[PainPoint],
        industry: Optional[str]
    ) -> list[RecommendedSection]:
        """Generate recommended page sections."""
        sections = []

        # Always include hero
        sections.append(RecommendedSection(
            name="Hero Section",
            purpose="Capture attention and communicate core value proposition",
            priority=1,
            content_suggestions=[
                "Compelling headline addressing main pain point",
                "Clear subheadline with specific benefit",
                "Strong call-to-action button",
                "Trust indicators (logos, certifications)"
            ],
            component_type="hero"
        ))

        # Add problem/solution section if we have pain points
        if pain_points:
            sections.append(RecommendedSection(
                name="Problem & Solution",
                purpose="Show understanding of customer challenges",
                priority=2,
                content_suggestions=[
                    f"Address: {pain_points[0].headline}" if pain_points else "Address common challenges",
                    "Show empathy for the problem",
                    "Present your solution clearly",
                    "Include relevant statistics"
                ],
                component_type="features"
            ))

        # Industry-specific sections
        if industry == "ecommerce":
            sections.append(RecommendedSection(
                name="Featured Products",
                purpose="Showcase best products immediately",
                priority=3,
                content_suggestions=[
                    "Top-selling items",
                    "New arrivals",
                    "Special offers",
                    "Quick add-to-cart"
                ],
                component_type="product_grid"
            ))
        elif industry == "saas":
            sections.append(RecommendedSection(
                name="How It Works",
                purpose="Simplify the product for prospects",
                priority=3,
                content_suggestions=[
                    "3-step process",
                    "Simple icons and visuals",
                    "Brief explanations",
                    "Link to detailed docs"
                ],
                component_type="steps"
            ))

        # Social proof section
        sections.append(RecommendedSection(
            name="Social Proof",
            purpose="Build trust through third-party validation",
            priority=4,
            content_suggestions=[
                "Customer testimonials",
                "Client logos",
                "Review scores",
                "Case study highlights"
            ],
            component_type="testimonials"
        ))

        # CTA section
        sections.append(RecommendedSection(
            name="Call to Action",
            purpose="Drive conversions with clear next step",
            priority=5,
            content_suggestions=[
                "Reinforce value proposition",
                "Create urgency if appropriate",
                "Reduce friction (no credit card required, etc.)",
                "Secondary action for not-ready visitors"
            ],
            component_type="cta"
        ))

        return sections

    def _get_cta_suggestions(self, industry: Optional[str]) -> tuple[str, Optional[str]]:
        """Get CTA text suggestions for industry."""
        ctas = self.INDUSTRY_CTAS.get(industry, ["Get Started", "Learn More"])
        primary = ctas[0] if ctas else "Get Started"
        secondary = ctas[1] if len(ctas) > 1 else "Learn More"
        return primary, secondary

    def _calculate_estimated_impact(self, pain_points: list[PainPoint]) -> dict:
        """Calculate estimated improvement impact."""
        impact = {}

        for pain in pain_points:
            if pain.signal == "pagespeed":
                impact["performance"] = "+50-100%"
                impact["bounce_rate"] = "-20-40%"
            elif pain.signal == "ssl_valid":
                impact["trust"] = "+30%"
                impact["conversions"] = "+10-15%"
            elif pain.signal == "mobile_responsive":
                impact["mobile_traffic"] = "+40-60%"
            elif pain.signal == "seo":
                impact["search_visibility"] = "+30-50%"
            elif pain.signal == "accessibility":
                impact["audience_reach"] = "+15%"

        return impact

    async def _enhance_with_ai(
        self,
        strategy: PitchStrategy,
        triage_signals: dict,
        brand_dna: dict,
        industry: Optional[str],
        company_name: Optional[str]
    ) -> PitchStrategy:
        """Enhance strategy using AI for better messaging."""
        prompt = f"""You are a conversion copywriting expert. Enhance this pitch strategy with more compelling messaging.

Current Strategy:
- Headline: {strategy.headline}
- Tagline: {strategy.tagline}
- Industry: {industry or 'Unknown'}
- Company: {company_name or 'Unknown'}

Brand Voice: {brand_dna.get('voice', {}).get('tone', 'professional')}

Pain Points Identified:
{json.dumps([p.to_dict() for p in strategy.pain_points], indent=2)}

Triage Signals:
{json.dumps(triage_signals, indent=2)}

Improve the messaging to be more compelling. Focus on:
1. Make the headline more emotionally resonant (8 words or less)
2. Make the tagline memorable and unique
3. Enhance the elevator pitch to be more persuasive

Respond with JSON:
```json
{{
  "headline": "Improved headline here",
  "tagline": "Improved tagline here",
  "elevator_pitch": "Improved elevator pitch here",
  "cta_text": "Primary CTA text",
  "cta_secondary": "Secondary CTA text",
  "avoid_phrases": ["phrases to avoid based on brand"],
  "voice_keywords": ["additional keywords to use"]
}}
```"""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            # Parse JSON from response
            json_match = response_text
            if "```json" in response_text:
                json_match = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_match = response_text.split("```")[1].split("```")[0]

            data = json.loads(json_match.strip())

            # Update strategy with AI enhancements
            strategy.headline = data.get("headline", strategy.headline)
            strategy.tagline = data.get("tagline", strategy.tagline)
            strategy.elevator_pitch = data.get("elevator_pitch", strategy.elevator_pitch)
            strategy.cta_text = data.get("cta_text", strategy.cta_text)
            strategy.cta_secondary = data.get("cta_secondary", strategy.cta_secondary)
            strategy.avoid_phrases = data.get("avoid_phrases", [])
            strategy.voice_keywords.extend(data.get("voice_keywords", []))
            strategy.confidence_score = 0.9  # Higher confidence with AI

        except Exception as e:
            logger.warning("AI enhancement failed, using base strategy", error=str(e))

        return strategy
