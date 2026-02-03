"""
Scout Agent tests.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestScoutAgent:
    """Tests for Scout Agent."""

    @pytest.mark.asyncio
    async def test_scout_agent_initialization(self):
        """Should initialize Scout Agent with services."""
        from agents.scout import ScoutAgent

        agent = ScoutAgent()

        assert agent.anthropic is not None
        assert agent.browser is not None
        assert agent.lighthouse is not None

    @pytest.mark.asyncio
    @patch("agents.scout.AnthropicService")
    @patch("agents.scout.BrowserService")
    @patch("agents.scout.LighthouseService")
    async def test_scout_analysis_flow(
        self,
        mock_lighthouse_cls,
        mock_browser_cls,
        mock_anthropic_cls,
    ):
        """Should run complete analysis flow."""
        from agents.scout import ScoutAgent

        # Setup mocks
        mock_anthropic = MagicMock()
        mock_anthropic.analyze_website = AsyncMock(return_value=(
            {
                "summary": "Test summary",
                "strengths": ["Good design"],
                "weaknesses": ["Slow loading"],
                "recommendations": [],
            },
            500,  # tokens
            0.05,  # cost
        ))
        mock_anthropic_cls.return_value = mock_anthropic

        mock_browser = MagicMock()
        mock_browser.start = AsyncMock()
        mock_browser.stop = AsyncMock()
        mock_browser.capture_screenshots = AsyncMock(return_value={
            "desktop": "base64-desktop",
            "mobile": "base64-mobile",
        })
        mock_browser.extract_brand_elements = AsyncMock(return_value={
            "primaryColors": ["#2563EB"],
            "secondaryColors": [],
            "fonts": {"headings": "Inter", "body": "Open Sans"},
            "logoUrl": None,
            "ctas": [],
        })
        mock_browser_cls.return_value = mock_browser

        mock_lighthouse = MagicMock()
        mock_lighthouse.run_audit = AsyncMock(return_value={
            "performance": {"score": 85},
            "seo": {"score": 90},
            "accessibility": {"score": 80},
        })
        mock_lighthouse_cls.return_value = mock_lighthouse

        # Run agent
        agent = ScoutAgent(
            anthropic_service=mock_anthropic,
            browser_service=mock_browser,
            lighthouse_service=mock_lighthouse,
        )

        results = await agent.analyze("https://example.com")

        # Verify results
        assert results["performance"]["score"] == 85
        assert results["seo"]["score"] == 90
        assert results["analysis"]["summary"] == "Test summary"
        assert results["tokens_used"] == 500
        assert "processing_time_ms" in results

        # Verify services were called
        mock_browser.start.assert_called_once()
        mock_browser.stop.assert_called_once()
        mock_lighthouse.run_audit.assert_called()
        mock_anthropic.analyze_website.assert_called_once()


class TestLighthouseService:
    """Tests for Lighthouse service."""

    @pytest.mark.asyncio
    async def test_fallback_audit(self):
        """Should perform fallback audit when Lighthouse unavailable."""
        from services.lighthouse import LighthouseService

        service = LighthouseService()

        # This will use the fallback since lighthouse CLI won't be available in tests
        results = await service._fallback_audit("https://httpbin.org/html")

        assert "performance" in results
        assert "seo" in results
        assert "accessibility" in results

    def test_empty_audit_structure(self):
        """Should return valid empty audit structure."""
        from services.lighthouse import LighthouseService

        service = LighthouseService()
        empty = service._empty_audit()

        assert empty["performance"]["score"] == 0
        assert empty["seo"]["score"] == 0
        assert empty["accessibility"]["score"] == 0


class TestBrowserService:
    """Tests for Browser service."""

    @pytest.mark.asyncio
    async def test_rgb_to_hex_conversion(self):
        """Should convert RGB to hex correctly."""
        from services.browser import BrowserService

        service = BrowserService()

        assert service._rgb_to_hex("rgb(37, 99, 235)") == "#2563EB"
        assert service._rgb_to_hex("rgba(255, 255, 255, 1)") == "#FFFFFF"
        assert service._rgb_to_hex("invalid") is None


class TestAnthropicService:
    """Tests for Anthropic service."""

    def test_cost_calculation(self):
        """Should calculate costs correctly."""
        from services.anthropic import AnthropicService

        service = AnthropicService()

        # Test with Sonnet pricing ($3/$15 per million)
        cost = service.calculate_cost(
            "claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=1_000_000
        )

        assert cost == 18.0  # $3 input + $15 output


class TestE2BSandbox:
    """Tests for E2B Sandbox."""

    @pytest.mark.asyncio
    async def test_mock_python_execution(self):
        """Should perform mock execution without E2B API key."""
        from agents.sandbox import E2BSandbox

        sandbox = E2BSandbox(api_key="")  # No API key

        result = await sandbox.execute_python("print('hello')")

        # Mock execution should succeed for valid syntax
        assert result.success is True

    @pytest.mark.asyncio
    async def test_mock_python_syntax_error(self):
        """Should detect syntax errors in mock mode."""
        from agents.sandbox import E2BSandbox

        sandbox = E2BSandbox(api_key="")

        result = await sandbox.execute_python("def broken(")

        assert result.success is False
        assert "SYNTAX_ERROR" in result.stderr

    @pytest.mark.asyncio
    async def test_validate_code(self):
        """Should validate code syntax."""
        from agents.sandbox import E2BSandbox

        sandbox = E2BSandbox(api_key="")

        # Valid code
        valid_result = await sandbox.validate_generated_code(
            "def hello():\n    return 'world'",
            language="python"
        )
        assert valid_result["syntax_ok"] is True
        assert valid_result["valid"] is True

        # Invalid code
        invalid_result = await sandbox.validate_generated_code(
            "def broken(",
            language="python"
        )
        assert invalid_result["syntax_ok"] is False
        assert invalid_result["valid"] is False
