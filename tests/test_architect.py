"""
Unit tests for Architect Room components.

Tests cover:
- DeepAuditor Lighthouse integration
- BrandExtractor color/font/voice extraction
- MockupGenerator code generation
- ArchitectAgent workflow
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from rooms.architect.tools.deep_audit import (
    DeepAuditor,
    AuditResult,
    PerformanceMetrics,
    SEOMetrics,
    AccessibilityMetrics
)
from rooms.architect.tools.brand_extractor import (
    BrandExtractor,
    BrandDNA,
    ColorPalette,
    Typography,
    BrandVoice
)
from rooms.architect.tools.mockup_generator import (
    MockupGenerator,
    MockupConfig,
    MockupResult,
    TEMPLATES
)


# =====================
# Deep Auditor Tests
# =====================

class TestDeepAuditor:
    """Tests for DeepAuditor class."""

    @pytest.fixture
    def auditor(self):
        return DeepAuditor(timeout_seconds=30)

    def test_performance_metrics_to_dict(self):
        """Test PerformanceMetrics conversion."""
        metrics = PerformanceMetrics(
            score=75,
            first_contentful_paint=1200,
            largest_contentful_paint=2500,
            cumulative_layout_shift=0.1,
            total_blocking_time=150
        )
        result = metrics.to_dict()

        assert result["score"] == 75
        assert result["fcp"] == 1200
        assert result["lcp"] == 2500
        assert result["cls"] == 0.1

    def test_seo_metrics_to_dict(self):
        """Test SEOMetrics conversion."""
        metrics = SEOMetrics(
            score=90,
            has_title=True,
            has_meta_description=True,
            has_viewport=True,
            is_crawlable=True,
            issues=["Missing hreflang"]
        )
        result = metrics.to_dict()

        assert result["score"] == 90
        assert result["has_title"] is True
        assert result["issues"] == ["Missing hreflang"]

    def test_accessibility_metrics_to_dict(self):
        """Test AccessibilityMetrics conversion."""
        metrics = AccessibilityMetrics(
            score=85,
            issues=[{"id": "color-contrast", "title": "Low contrast"}],
            passing_audits=20,
            failing_audits=3
        )
        result = metrics.to_dict()

        assert result["score"] == 85
        assert len(result["issues"]) == 1
        assert result["passing_audits"] == 20

    def test_audit_result_overall_score(self):
        """Test overall score calculation."""
        result = AuditResult(
            url="https://example.com",
            success=True,
            performance=PerformanceMetrics(score=80),
            seo=SEOMetrics(score=90),
            accessibility=AccessibilityMetrics(score=70),
            best_practices_score=85
        )

        # Average of 80, 90, 70, 85 = 81.25 -> 81
        assert result.overall_score == 81

    def test_audit_result_overall_score_partial(self):
        """Test overall score with missing categories."""
        result = AuditResult(
            url="https://example.com",
            success=True,
            performance=PerformanceMetrics(score=80),
            seo=None,
            accessibility=None
        )

        assert result.overall_score == 80

    def test_audit_result_to_dict(self):
        """Test AuditResult conversion to dict."""
        result = AuditResult(
            url="https://example.com",
            success=True,
            performance=PerformanceMetrics(score=75),
            audit_time_ms=5000
        )
        data = result.to_dict()

        assert data["url"] == "https://example.com"
        assert data["success"] is True
        assert data["performance"]["score"] == 75
        assert data["audit_time_ms"] == 5000


# =====================
# Brand Extractor Tests
# =====================

class TestBrandExtractor:
    """Tests for BrandExtractor class."""

    @pytest.fixture
    def extractor(self):
        return BrandExtractor()

    def test_extract_company_name_from_title(self, extractor):
        """Test company name extraction from title."""
        html = "<title>Acme Corp - Leading Innovation</title>"
        name = extractor._extract_company_name(html)
        assert name == "Acme Corp"

    def test_extract_company_name_from_og(self, extractor):
        """Test company name from og:site_name."""
        html = '<meta property="og:site_name" content="Tech Startup Inc">'
        name = extractor._extract_company_name(html)
        assert name == "Tech Startup Inc"

    def test_extract_colors_hex(self, extractor):
        """Test hex color extraction."""
        html = """
        <style>
            .primary { color: #3B82F6; }
            .secondary { background-color: #1E40AF; }
            .accent { border-color: #F59E0B; }
        </style>
        """
        colors = extractor._extract_colors(html, None)

        assert "#3b82f6" in colors.all_colors
        assert "#1e40af" in colors.all_colors
        assert "#f59e0b" in colors.all_colors

    def test_extract_colors_rgb(self, extractor):
        """Test RGB color extraction."""
        html = """
        <style>
            .bg { background: rgb(59, 130, 246); }
            .text { color: rgba(30, 64, 175, 0.9); }
        </style>
        """
        colors = extractor._extract_colors(html, None)

        assert "#3b82f6" in colors.all_colors
        assert "#1e40af" in colors.all_colors

    def test_extract_typography(self, extractor):
        """Test font extraction."""
        html = """
        <style>
            body { font-family: 'Inter', sans-serif; }
            h1 { font-family: 'Playfair Display', serif; }
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap">
        """
        typography = extractor._extract_typography(html, None)

        assert "Inter" in typography.font_families
        assert "Playfair Display" in typography.font_families
        assert "Inter" in typography.google_fonts

    def test_extract_voice_keywords(self, extractor):
        """Test voice/keywords extraction."""
        html = """
        <meta name="keywords" content="innovation, technology, startup, AI">
        <meta name="description" content="Leading innovation in AI technology">
        """
        voice = extractor._extract_voice(html)

        assert "innovation" in voice.keywords
        assert "technology" in voice.keywords
        assert voice.description == "Leading innovation in AI technology"

    def test_extract_voice_tone_detection(self, extractor):
        """Test brand tone detection."""
        html = "<body>We deliver innovative and cutting-edge solutions</body>"
        voice = extractor._extract_voice(html)
        assert voice.tone == "innovative"

        html2 = "<body>Trusted by thousands of businesses worldwide</body>"
        voice2 = extractor._extract_voice(html2)
        assert voice2.tone == "trustworthy"

    def test_extract_logo(self, extractor):
        """Test logo URL extraction."""
        html = '''
        <a class="logo" href="/">
            <img src="/images/logo.png" alt="Company Logo">
        </a>
        '''
        logo = extractor._extract_logo(html, "https://example.com")
        assert logo == "https://example.com/images/logo.png"

    def test_extract_favicon(self, extractor):
        """Test favicon extraction."""
        html = '<link rel="icon" href="/favicon.ico">'
        favicon = extractor._extract_favicon(html, "https://example.com")
        assert favicon == "https://example.com/favicon.ico"

    def test_extract_social_links(self, extractor):
        """Test social media link extraction."""
        html = '''
        <a href="https://twitter.com/company">Twitter</a>
        <a href="https://facebook.com/company">Facebook</a>
        <a href="https://linkedin.com/company/company">LinkedIn</a>
        '''
        links = extractor._extract_social_links(html)

        assert len(links) == 3
        assert any("twitter" in l for l in links)
        assert any("facebook" in l for l in links)
        assert any("linkedin" in l for l in links)

    def test_calculate_confidence(self, extractor):
        """Test confidence score calculation."""
        # All components present
        confidence = extractor._calculate_confidence(
            company_name="Test Co",
            colors=ColorPalette(all_colors=["#000", "#111", "#222"]),
            typography=Typography(primary_font="Inter"),
            logo_url="https://example.com/logo.png"
        )
        assert confidence == 1.0

        # Only company name
        confidence = extractor._calculate_confidence(
            company_name="Test Co",
            colors=None,
            typography=None,
            logo_url=None
        )
        assert confidence == 0.25

    @pytest.mark.asyncio
    async def test_full_extraction(self, extractor):
        """Test complete brand extraction flow."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Awesome Startup</title>
            <meta name="description" content="Building the future">
            <meta property="og:site_name" content="Awesome Startup">
            <link rel="icon" href="/favicon.png">
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700">
            <style>
                body { font-family: 'Inter', sans-serif; color: #1a1a1a; }
                .primary { background: #3B82F6; }
            </style>
        </head>
        <body>
            <header>
                <img class="logo" src="/logo.svg" alt="Logo">
            </header>
            <footer>
                <a href="https://twitter.com/awesome">Twitter</a>
            </footer>
        </body>
        </html>
        """

        brand = await extractor.extract_from_html(
            url="https://awesome-startup.com",
            html=html
        )

        assert brand.company_name == "Awesome Startup"
        assert brand.domain == "awesome-startup.com"
        assert brand.colors.primary is not None
        assert brand.typography.primary_font is not None
        assert brand.favicon_url is not None
        assert len(brand.social_links) > 0
        assert brand.extraction_confidence > 0


# =====================
# Mockup Generator Tests
# =====================

class TestMockupGenerator:
    """Tests for MockupGenerator class."""

    @pytest.fixture
    def generator(self):
        return MockupGenerator()

    def test_mockup_config_defaults(self):
        """Test MockupConfig default values."""
        config = MockupConfig()

        assert config.template == "modern-professional"
        assert config.framework == "nextjs"
        assert config.include_hero is True
        assert config.responsive is True

    def test_mockup_config_to_dict(self):
        """Test MockupConfig conversion."""
        config = MockupConfig(
            template="bold-startup",
            include_pricing=True
        )
        data = config.to_dict()

        assert data["template"] == "bold-startup"
        assert data["include_pricing"] is True

    def test_templates_defined(self):
        """Test that all templates are defined."""
        assert "modern-professional" in TEMPLATES
        assert "minimal-clean" in TEMPLATES
        assert "bold-startup" in TEMPLATES
        assert "corporate-trust" in TEMPLATES

    def test_mockup_result_to_dict(self):
        """Test MockupResult conversion."""
        result = MockupResult(
            success=True,
            preview_url="https://preview.e2b.dev/123",
            sandbox_id="sandbox-123",
            code_files={"page.tsx": "code here"},
            generation_time_ms=5000
        )
        data = result.to_dict()

        assert data["success"] is True
        assert data["preview_url"] == "https://preview.e2b.dev/123"
        assert data["sandbox_id"] == "sandbox-123"
        assert "page.tsx" in data["code_files"]

    def test_generate_from_template(self, generator):
        """Test template-based code generation."""
        brand = BrandDNA(
            url="https://example.com",
            domain="example.com",
            company_name="Test Company",
            colors=ColorPalette(primary="#3B82F6", secondary="#1E40AF"),
            typography=Typography(primary_font="Inter")
        )
        config = MockupConfig()

        files = generator._generate_from_template(brand, config)

        assert "page.tsx" in files
        assert "globals.css" in files
        assert "tailwind.config.js" in files

        # Check content includes brand values
        assert "Test Company" in files["page.tsx"]
        assert "#3B82F6" in files["globals.css"] or "#3b82f6" in files["globals.css"].lower()
        assert "Inter" in files["globals.css"]

    def test_build_generation_prompt(self, generator):
        """Test AI prompt building."""
        brand = BrandDNA(
            url="https://example.com",
            domain="example.com",
            company_name="Acme Corp",
            colors=ColorPalette(primary="#FF0000"),
            voice=BrandVoice(tone="professional")
        )
        config = MockupConfig(
            include_hero=True,
            include_features=True,
            include_pricing=False
        )

        prompt = generator._build_generation_prompt(brand, None, config)

        assert "Acme Corp" in prompt
        assert "#FF0000" in prompt
        assert "professional" in prompt
        assert "hero section" in prompt
        assert "features" in prompt

    def test_parse_code_response(self, generator):
        """Test parsing AI response for code blocks."""
        response = """
Here's the generated code:

```page.tsx
import React from 'react';
export default function Page() { return <div>Hello</div>; }
```

```globals.css
body { margin: 0; }
```

```tailwind.config.js
module.exports = { content: [] };
```
"""
        config = MockupConfig()
        files = generator._parse_code_response(response, config)

        assert "page.tsx" in files
        assert "globals.css" in files
        assert "tailwind.config.js" in files
        assert "React" in files["page.tsx"]


# =====================
# Architect Agent Tests
# =====================

class TestArchitectAgent:
    """Tests for ArchitectAgent class."""

    @pytest.fixture
    def mock_config(self):
        from agents.base import AgentConfig
        return AgentConfig(
            id=uuid4(),
            slug="architect",
            name="Architect Agent",
            room="architect",
            model="claude-3-5-sonnet-20241022",
            temperature=0.7,
            max_tokens=8000,
            system_prompt="You are the Sentinel Architect Agent.",
            tools=["deep_audit", "brand_extract", "mockup_generate"],
            mcp_servers=["playwright", "e2b"],
            timeout_seconds=300
        )

    @pytest.mark.asyncio
    async def test_agent_registers_tools(self, mock_config):
        """Test that agent registers expected tools."""
        from rooms.architect.agent import ArchitectAgent

        agent = ArchitectAgent(config=mock_config)

        assert "deep_audit" in agent._tools
        assert "brand_extract" in agent._tools
        assert "mockup_generate" in agent._tools

    @pytest.mark.asyncio
    async def test_agent_run_requires_url(self, mock_config):
        """Test that run raises error without URL."""
        from rooms.architect.agent import ArchitectAgent
        from agents.base import AgentRunContext

        agent = ArchitectAgent(config=mock_config)
        context = AgentRunContext(
            run_id=uuid4(),
            lead_id=uuid4(),
            user_id=uuid4(),
            playbook_id=None,
            batch_id=None,
            input_data={}  # No URL
        )

        with pytest.raises(ValueError, match="No URL provided"):
            await agent.run(context)

    def test_build_mockup_config(self, mock_config):
        """Test mockup config building from playbook."""
        from rooms.architect.agent import ArchitectAgent

        agent = ArchitectAgent(config=mock_config)

        playbook = {
            "mockup": {
                "template": "bold-startup",
                "include_pricing": True
            }
        }

        config = agent._build_mockup_config(playbook)

        assert config.template == "bold-startup"
        assert config.include_pricing is True
        assert config.include_hero is True  # Default

    def test_generate_fallback_recommendations(self, mock_config):
        """Test fallback recommendation generation."""
        from rooms.architect.agent import ArchitectAgent

        agent = ArchitectAgent(config=mock_config)

        audit = AuditResult(
            url="https://example.com",
            success=True,
            performance=PerformanceMetrics(score=40),
            seo=SEOMetrics(score=60, has_meta_description=False),
            accessibility=AccessibilityMetrics(score=50)
        )

        brand = BrandDNA(
            url="https://example.com",
            domain="example.com"
        )

        recommendations = agent._generate_fallback_recommendations(audit, brand)

        assert "items" in recommendations
        assert len(recommendations["items"]) > 0
        # Should include performance recommendations due to low score
        assert any("image" in r.lower() or "optim" in r.lower() for r in recommendations["items"])


# =====================
# Color Palette Tests
# =====================

class TestColorPalette:
    """Tests for ColorPalette dataclass."""

    def test_to_dict(self):
        """Test ColorPalette conversion."""
        palette = ColorPalette(
            primary="#3B82F6",
            secondary="#1E40AF",
            accent="#F59E0B",
            all_colors=["#3B82F6", "#1E40AF", "#F59E0B", "#111", "#222"]
        )
        data = palette.to_dict()

        assert data["primary"] == "#3B82F6"
        assert data["secondary"] == "#1E40AF"
        assert data["accent"] == "#F59E0B"
        # Should limit to 10 colors
        assert len(data["all_colors"]) <= 10


# =====================
# Typography Tests
# =====================

class TestTypography:
    """Tests for Typography dataclass."""

    def test_to_dict(self):
        """Test Typography conversion."""
        typography = Typography(
            primary_font="Inter",
            secondary_font="Georgia",
            font_families=["Inter", "Georgia", "Arial", "Helvetica", "Times", "Courier"],
            google_fonts=["Inter"]
        )
        data = typography.to_dict()

        assert data["primary_font"] == "Inter"
        assert data["secondary_font"] == "Georgia"
        # Should limit to 5 font families
        assert len(data["font_families"]) <= 5
        assert "Inter" in data["google_fonts"]


# =====================
# BrandDNA Tests
# =====================

class TestBrandDNA:
    """Tests for BrandDNA dataclass."""

    def test_to_dict_complete(self):
        """Test BrandDNA full conversion."""
        brand = BrandDNA(
            url="https://example.com",
            domain="example.com",
            company_name="Test Co",
            colors=ColorPalette(primary="#000"),
            typography=Typography(primary_font="Arial"),
            voice=BrandVoice(tone="professional"),
            logo_url="https://example.com/logo.png",
            social_links=["https://twitter.com/test"],
            extraction_confidence=0.75
        )
        data = brand.to_dict()

        assert data["company_name"] == "Test Co"
        assert data["colors"]["primary"] == "#000"
        assert data["typography"]["primary_font"] == "Arial"
        assert data["voice"]["tone"] == "professional"
        assert data["extraction_confidence"] == 0.75
