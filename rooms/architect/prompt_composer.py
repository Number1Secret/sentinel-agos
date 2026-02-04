"""
Prompt Composer - Composes cascading prompts (Cursor-style) for layered generation.

Layers prompts in order:
1. Base system prompt
2. House style rules (agency-specific)
3. Niche prompts (industry-specific)
4. Component prompts (section-specific)
5. Regeneration focus (if iterating)

Supports three cascade modes:
- append: Add to existing prompt
- prepend: Add before existing prompt
- replace: Replace existing prompt section
"""
from dataclasses import dataclass, field
from typing import Optional, Any
from uuid import UUID

import structlog

logger = structlog.get_logger()


@dataclass
class PromptLayer:
    """A single layer in the prompt cascade."""
    name: str
    content: str
    priority: int = 100  # Lower = applied first
    cascade_mode: str = "append"  # append, prepend, replace
    category: str = "base"  # base, house_style, niche, component, focus


@dataclass
class ComposedPrompt:
    """Result of prompt composition."""
    full_prompt: str
    layers_applied: list[str]
    layer_count: int
    total_tokens_estimate: int  # Rough estimate

    def to_dict(self) -> dict:
        return {
            "full_prompt": self.full_prompt,
            "layers_applied": self.layers_applied,
            "layer_count": self.layer_count,
            "total_tokens_estimate": self.total_tokens_estimate
        }


class PromptComposer:
    """
    Composes cascading prompts (Cursor-style) for mockup generation.

    Layers prompts from most general to most specific:
    - Base: Core mockup generation instructions
    - House Style: Agency-specific design rules
    - Niche: Industry-specific guidelines
    - Component: Section-specific requirements
    - Focus: Regeneration focus areas (if iterating)
    """

    # Default base prompt for mockup generation
    DEFAULT_BASE_PROMPT = """You are an expert web designer and developer. Generate a complete, production-ready website mockup based on the provided specifications.

## Core Requirements
- Modern, professional design that converts visitors
- Mobile-first responsive approach
- Semantic HTML5 structure
- Clean, maintainable CSS/Tailwind
- Accessibility best practices (WCAG 2.1 AA)

## Output Format
Generate a complete Next.js/React component with:
1. Full JSX structure with Tailwind CSS classes
2. Proper semantic HTML elements
3. Responsive breakpoints (sm, md, lg, xl)
4. All placeholder content filled with realistic text
5. Image placeholders using proper dimensions

## Quality Standards
- PageSpeed score target: 90+
- Proper heading hierarchy (h1 → h2 → h3)
- Touch targets at least 44x44px
- Sufficient color contrast
- Focus visible states for interactive elements
"""

    def __init__(self, db_service=None):
        """
        Initialize PromptComposer.

        Args:
            db_service: Database service for loading custom prompts
        """
        self.db_service = db_service
        self._prompt_cache: dict[str, list[PromptLayer]] = {}

    async def compose(
        self,
        base_prompt: Optional[str] = None,
        house_style: Optional[dict] = None,
        niche: Optional[str] = None,
        component_types: Optional[list[str]] = None,
        regeneration_focus: Optional[list[str]] = None,
        user_id: Optional[UUID] = None,
        brand_dna: Optional[dict] = None,
        pitch_strategy: Optional[dict] = None
    ) -> ComposedPrompt:
        """
        Compose a complete prompt from cascading layers.

        Args:
            base_prompt: Override for base prompt (uses default if not provided)
            house_style: Agency-specific style rules
            niche: Industry/niche for niche prompts
            component_types: Specific components being generated
            regeneration_focus: Focus areas for regeneration iterations
            user_id: User ID for loading custom prompts
            brand_dna: Extracted brand DNA for context
            pitch_strategy: Pitch strategy for content guidance

        Returns:
            ComposedPrompt with full composed prompt
        """
        layers: list[PromptLayer] = []

        # 1. Base layer
        base = base_prompt or self.DEFAULT_BASE_PROMPT
        layers.append(PromptLayer(
            name="base",
            content=base,
            priority=0,
            category="base"
        ))

        # 2. Brand DNA context
        if brand_dna:
            brand_layer = self._compose_brand_layer(brand_dna)
            if brand_layer:
                layers.append(brand_layer)

        # 3. Pitch strategy context
        if pitch_strategy:
            strategy_layer = self._compose_strategy_layer(pitch_strategy)
            if strategy_layer:
                layers.append(strategy_layer)

        # 4. House style layer
        if house_style:
            house_layer = self._compose_house_style_layer(house_style)
            if house_layer:
                layers.append(house_layer)

        # 5. Load custom prompts from database
        if self.db_service and user_id:
            custom_layers = await self._load_custom_prompts(user_id, niche, component_types)
            layers.extend(custom_layers)

        # 6. Niche layer (built-in fallback)
        if niche and not any(l.category == "niche" for l in layers):
            niche_layer = self._compose_niche_layer(niche)
            if niche_layer:
                layers.append(niche_layer)

        # 7. Component layers
        if component_types:
            for component in component_types:
                comp_layer = self._compose_component_layer(component)
                if comp_layer:
                    layers.append(comp_layer)

        # 8. Regeneration focus (highest priority, applied last)
        if regeneration_focus:
            focus_layer = self._compose_focus_layer(regeneration_focus)
            if focus_layer:
                layers.append(focus_layer)

        # Sort by priority
        layers.sort(key=lambda x: x.priority)

        # Compose final prompt
        composed = self._merge_layers(layers)

        logger.info(
            "Prompt composed",
            layers_count=len(layers),
            categories=[l.category for l in layers],
            estimated_tokens=composed.total_tokens_estimate
        )

        return composed

    def _compose_brand_layer(self, brand_dna: dict) -> Optional[PromptLayer]:
        """Compose brand DNA context layer."""
        parts = ["## Brand Context"]

        colors = brand_dna.get("colors", {})
        if colors:
            parts.append(f"""
### Color Palette
- Primary: {colors.get('primary', '#3B82F6')}
- Secondary: {colors.get('secondary', '#6B7280')}
- Accent: {colors.get('accent', '#10B981')}
- Background: {colors.get('background', '#FFFFFF')}
- Text: {colors.get('text', '#1F2937')}

Use these exact colors throughout the design. The primary color should be used sparingly for CTAs and key highlights.""")

        typography = brand_dna.get("typography", {})
        if typography:
            parts.append(f"""
### Typography
- Primary Font: {typography.get('primary_font', 'Inter')}
- Secondary Font: {typography.get('secondary_font', 'system-ui')}

Apply consistent typography throughout. Use the primary font for headings and the secondary for body text.""")

        voice = brand_dna.get("voice", {})
        if voice:
            parts.append(f"""
### Brand Voice
- Tone: {voice.get('tone', 'professional')}
- Industry: {voice.get('industry', 'general')}
- Description: {voice.get('description', '')}

Ensure all copy matches this brand voice.""")

        if len(parts) > 1:
            return PromptLayer(
                name="brand_dna",
                content="\n".join(parts),
                priority=10,
                category="brand"
            )
        return None

    def _compose_strategy_layer(self, pitch_strategy: dict) -> Optional[PromptLayer]:
        """Compose pitch strategy context layer."""
        parts = ["## Content Strategy"]

        if pitch_strategy.get("headline"):
            parts.append(f"### Hero Headline\n{pitch_strategy['headline']}")

        if pitch_strategy.get("tagline"):
            parts.append(f"### Tagline\n{pitch_strategy['tagline']}")

        if pitch_strategy.get("elevator_pitch"):
            parts.append(f"### Value Proposition\n{pitch_strategy['elevator_pitch']}")

        if pitch_strategy.get("cta_text"):
            parts.append(f"### Primary CTA\n\"{pitch_strategy['cta_text']}\"")
            if pitch_strategy.get("cta_secondary"):
                parts.append(f"### Secondary CTA\n\"{pitch_strategy['cta_secondary']}\"")

        sections = pitch_strategy.get("recommended_sections", [])
        if sections:
            parts.append("### Page Structure")
            for section in sections:
                if isinstance(section, dict):
                    parts.append(f"- {section.get('name', 'Section')}: {section.get('purpose', '')}")

        avoid = pitch_strategy.get("avoid_phrases", [])
        if avoid:
            parts.append(f"### Avoid These Phrases\n{', '.join(avoid)}")

        if len(parts) > 1:
            return PromptLayer(
                name="pitch_strategy",
                content="\n\n".join(parts),
                priority=15,
                category="strategy"
            )
        return None

    def _compose_house_style_layer(self, house_style: dict) -> Optional[PromptLayer]:
        """Compose house style layer from agency config."""
        parts = ["## House Style Rules"]

        design_rules = house_style.get("design_rules", {})
        if design_rules:
            parts.append("### Design System")
            for key, value in design_rules.items():
                parts.append(f"- {key.replace('_', ' ').title()}: {value}")

        brand_voice = house_style.get("brand_voice", {})
        if brand_voice:
            parts.append("### Agency Voice Guidelines")
            if brand_voice.get("tone"):
                parts.append(f"- Tone: {brand_voice['tone']}")
            if brand_voice.get("avoid_words"):
                parts.append(f"- Avoid: {', '.join(brand_voice['avoid_words'])}")
            if brand_voice.get("prefer_words"):
                parts.append(f"- Prefer: {', '.join(brand_voice['prefer_words'])}")

        component_prefs = house_style.get("component_preferences", {})
        if component_prefs:
            parts.append("### Component Preferences")
            for key, value in component_prefs.items():
                parts.append(f"- {key.replace('_', ' ').title()}: {value}")

        if len(parts) > 1:
            return PromptLayer(
                name="house_style",
                content="\n".join(parts),
                priority=20,
                category="house_style"
            )
        return None

    def _compose_niche_layer(self, niche: str) -> Optional[PromptLayer]:
        """Compose built-in niche layer."""
        niche_prompts = {
            "saas": """## SaaS Landing Page Guidelines
- Hero: Clear value proposition in 8 words or less
- Show social proof early (logos, testimonials, user counts)
- Features: 3-6 key features with icons
- Pricing: Highlight recommended tier
- CTA: Free trial or demo, not "Contact Us"
- Trust: Security badges, compliance logos
- FAQ: Address pricing and features questions""",

            "ecommerce": """## E-commerce Store Guidelines
- Hero: Featured products with clear CTA
- Navigation: Categories clearly visible
- Products: High-quality images, prices visible
- Trust: Shipping info, returns policy, secure checkout badges
- Reviews: Product ratings visible
- Cart: Always accessible, show item count
- Mobile: Easy add-to-cart, quick checkout""",

            "healthcare": """## Healthcare Website Guidelines
- Hero: Caring imagery, clear services
- Trust: Credentials, certifications prominently displayed
- Accessibility: WCAG AAA compliance where possible
- Contact: Multiple ways to reach (phone, form, chat)
- HIPAA: Privacy statement visible
- Appointments: Easy booking flow
- Emergency: Clear emergency contact info""",

            "local": """## Local Business Guidelines
- Hero: Service/product imagery with location
- Contact: Phone number highly visible, click-to-call
- Hours: Business hours in header or footer
- Map: Embedded map with location
- Reviews: Google/Yelp reviews or testimonials
- Services: Clear list with brief descriptions
- CTA: "Call Now", "Get Directions", "Book Appointment\"""",

            "technology": """## Technology Company Guidelines
- Hero: Product screenshot or demo
- Tech specs: Clear, organized documentation style
- Integrations: Show compatible platforms
- Security: Compliance and security features
- API/Developer: Developer resources if applicable
- Pricing: Clear tiers with feature comparison
- Support: Multiple support channels""",

            "finance": """## Financial Services Guidelines
- Hero: Trust and security messaging
- Compliance: Required disclosures visible
- Security: SSL, encryption, security badges
- Simplicity: Complex products made simple
- Calculator: Interactive tools if applicable
- Contact: Multiple channels, regulated hours
- Privacy: Clear privacy and data policies"""
        }

        niche_lower = niche.lower()
        if niche_lower in niche_prompts:
            return PromptLayer(
                name=f"niche_{niche_lower}",
                content=niche_prompts[niche_lower],
                priority=30,
                category="niche"
            )
        return None

    def _compose_component_layer(self, component: str) -> Optional[PromptLayer]:
        """Compose component-specific layer."""
        component_prompts = {
            "hero": """## Hero Section Requirements
- Full viewport height on desktop (100vh)
- Compelling headline (max 8 words)
- Subheadline explaining the value proposition
- Primary CTA button (high contrast)
- Optional secondary CTA (text link or ghost button)
- Background: Image/gradient/pattern that doesn't compete with text
- Mobile: Stack vertically, adjust font sizes""",

            "features": """## Features Section Requirements
- 3-6 feature cards in a grid
- Icon + Title + Description format
- Consistent card styling
- Benefits-focused copy (not feature-focused)
- Visual hierarchy: Icon draws eye, title explains, description provides detail
- Responsive: 3 cols → 2 cols → 1 col""",

            "testimonials": """## Testimonials Section Requirements
- Real quotes with attribution
- Photos of customers if available
- Company names/roles for B2B
- Star ratings if applicable
- Carousel for multiple testimonials
- Social proof numbers if impressive""",

            "pricing": """## Pricing Section Requirements
- 2-4 pricing tiers
- Clear feature comparison
- Recommended tier highlighted
- Annual/monthly toggle if applicable
- CTA for each tier
- FAQ or objection handling nearby""",

            "cta": """## CTA Section Requirements
- Reinforce value proposition
- Create urgency if appropriate
- Reduce friction (no CC required, etc.)
- High-contrast button
- Secondary action for not-ready visitors
- Full-width on mobile""",

            "footer": """## Footer Section Requirements
- Navigation links organized by category
- Contact information
- Social media links
- Legal links (Privacy, Terms)
- Copyright with current year
- Newsletter signup if applicable"""
        }

        component_lower = component.lower()
        if component_lower in component_prompts:
            return PromptLayer(
                name=f"component_{component_lower}",
                content=component_prompts[component_lower],
                priority=50,
                category="component"
            )
        return None

    def _compose_focus_layer(self, focus_areas: list[str]) -> Optional[PromptLayer]:
        """Compose regeneration focus layer."""
        if not focus_areas:
            return None

        parts = [
            "## CRITICAL: Regeneration Focus",
            "The previous iteration had issues. Focus specifically on fixing these areas:",
            ""
        ]

        for i, focus in enumerate(focus_areas, 1):
            parts.append(f"{i}. **{focus}**")

        parts.append("")
        parts.append("Prioritize these improvements while maintaining the overall design quality.")

        return PromptLayer(
            name="regeneration_focus",
            content="\n".join(parts),
            priority=100,  # Highest priority - applied last
            cascade_mode="append",
            category="focus"
        )

    async def _load_custom_prompts(
        self,
        user_id: UUID,
        niche: Optional[str],
        component_types: Optional[list[str]]
    ) -> list[PromptLayer]:
        """Load custom prompts from database."""
        if not self.db_service:
            return []

        layers = []

        try:
            # Query prompt library for this user
            # This is a placeholder - actual implementation depends on db_service
            prompts = await self.db_service.get_user_prompts(
                user_id=user_id,
                is_active=True
            )

            for prompt in prompts:
                # Filter by niche tags
                if niche and prompt.get("niche_tags"):
                    if niche.lower() not in [t.lower() for t in prompt["niche_tags"]]:
                        continue

                # Filter by component tags
                if component_types and prompt.get("component_tags"):
                    if not any(c.lower() in [t.lower() for t in prompt["component_tags"]] for c in component_types):
                        continue

                layer = PromptLayer(
                    name=prompt["slug"],
                    content=prompt["prompt_text"],
                    priority=prompt.get("priority", 100),
                    cascade_mode=prompt.get("cascade_mode", "append"),
                    category=prompt.get("category", "custom")
                )
                layers.append(layer)

        except Exception as e:
            logger.warning("Failed to load custom prompts", error=str(e))

        return layers

    def _merge_layers(self, layers: list[PromptLayer]) -> ComposedPrompt:
        """Merge all layers into final prompt."""
        sections: dict[str, list[str]] = {
            "base": [],
            "brand": [],
            "strategy": [],
            "house_style": [],
            "niche": [],
            "component": [],
            "focus": [],
            "custom": []
        }

        for layer in layers:
            category = layer.category if layer.category in sections else "custom"

            if layer.cascade_mode == "replace":
                sections[category] = [layer.content]
            elif layer.cascade_mode == "prepend":
                sections[category].insert(0, layer.content)
            else:  # append
                sections[category].append(layer.content)

        # Build final prompt in order
        final_parts = []
        order = ["base", "brand", "strategy", "house_style", "niche", "component", "custom", "focus"]

        for category in order:
            if sections.get(category):
                final_parts.extend(sections[category])

        full_prompt = "\n\n---\n\n".join(final_parts)

        # Estimate tokens (rough: ~4 chars per token)
        estimated_tokens = len(full_prompt) // 4

        return ComposedPrompt(
            full_prompt=full_prompt,
            layers_applied=[l.name for l in layers],
            layer_count=len(layers),
            total_tokens_estimate=estimated_tokens
        )


class PromptLibraryService:
    """Service for managing prompt library entries."""

    def __init__(self, db_service):
        self.db = db_service

    async def create_prompt(
        self,
        user_id: UUID,
        slug: str,
        name: str,
        category: str,
        prompt_text: str,
        niche_tags: Optional[list[str]] = None,
        component_tags: Optional[list[str]] = None,
        priority: int = 100,
        cascade_mode: str = "append"
    ) -> dict:
        """Create a new prompt in the library."""
        # Validate category
        valid_categories = ["house_style", "niche", "component", "audit", "brand"]
        if category not in valid_categories:
            raise ValueError(f"Invalid category: {category}. Must be one of {valid_categories}")

        # Validate cascade_mode
        valid_modes = ["append", "prepend", "replace"]
        if cascade_mode not in valid_modes:
            raise ValueError(f"Invalid cascade_mode: {cascade_mode}. Must be one of {valid_modes}")

        # Create in database
        prompt_data = {
            "user_id": str(user_id),
            "slug": slug,
            "name": name,
            "category": category,
            "prompt_text": prompt_text,
            "niche_tags": niche_tags or [],
            "component_tags": component_tags or [],
            "priority": priority,
            "cascade_mode": cascade_mode,
            "is_active": True
        }

        return await self.db.create_prompt(prompt_data)

    async def get_user_prompts(
        self,
        user_id: UUID,
        category: Optional[str] = None,
        is_active: bool = True
    ) -> list[dict]:
        """Get all prompts for a user."""
        return await self.db.get_user_prompts(
            user_id=user_id,
            category=category,
            is_active=is_active
        )

    async def update_prompt(self, prompt_id: UUID, updates: dict) -> dict:
        """Update a prompt."""
        return await self.db.update_prompt(prompt_id, updates)

    async def delete_prompt(self, prompt_id: UUID) -> bool:
        """Delete a prompt."""
        return await self.db.delete_prompt(prompt_id)
