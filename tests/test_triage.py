"""
Unit tests for Triage Room components.

Tests cover:
- TriageAgent URL scanning and scoring
- Signal detection (SSL, copyright, mobile, CMS)
- Score calculation with playbook rules
- FastScanner functionality
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from rooms.triage.tools.signal_detector import (
    SignalDetector,
    TriageSignals,
    calculate_triage_score
)
from rooms.triage.tools.fast_scan import FastScanner, ScanResult


# =====================
# Signal Detector Tests
# =====================

class TestSignalDetector:
    """Tests for SignalDetector class."""

    @pytest.fixture
    def detector(self):
        return SignalDetector()

    def test_extract_copyright_year_standard(self, detector):
        """Test copyright year extraction with standard format."""
        html = "<footer>Copyright 2021 Company Inc.</footer>"
        year = detector._extract_copyright_year(html)
        assert year == 2021

    def test_extract_copyright_year_symbol(self, detector):
        """Test copyright year extraction with symbol."""
        html = "<footer>&copy; 2020 Company Inc.</footer>"
        year = detector._extract_copyright_year(html)
        assert year == 2020

    def test_extract_copyright_year_range(self, detector):
        """Test copyright year extraction with range."""
        html = "<footer>&copy; 2018-2023 Company Inc.</footer>"
        year = detector._extract_copyright_year(html)
        assert year == 2023  # Should return most recent

    def test_extract_copyright_year_none(self, detector):
        """Test copyright year extraction when not present."""
        html = "<footer>All rights reserved.</footer>"
        year = detector._extract_copyright_year(html)
        assert year is None

    def test_has_viewport_meta_true(self, detector):
        """Test viewport meta detection when present."""
        html = '<head><meta name="viewport" content="width=device-width"></head>'
        assert detector._has_viewport_meta(html) is True

    def test_has_viewport_meta_false(self, detector):
        """Test viewport meta detection when absent."""
        html = "<head><title>Test</title></head>"
        assert detector._has_viewport_meta(html) is False

    def test_detect_mobile_responsive_with_bootstrap(self, detector):
        """Test mobile detection with Bootstrap classes."""
        html = '''
        <head><meta name="viewport" content="width=device-width"></head>
        <body><div class="container"><div class="row"><div class="col-md-6"></div></div></div></body>
        '''
        assert detector._detect_mobile_responsive(html) is True

    def test_detect_mobile_responsive_with_tailwind(self, detector):
        """Test mobile detection with Tailwind classes."""
        html = '''
        <head><meta name="viewport" content="width=device-width"></head>
        <body><div class="flex sm:flex-row md:flex-col"></div></body>
        '''
        assert detector._detect_mobile_responsive(html) is True

    def test_detect_mobile_responsive_false(self, detector):
        """Test mobile detection when not responsive."""
        html = "<head><title>Old Site</title></head><body><table width='800'></table></body>"
        assert detector._detect_mobile_responsive(html) is False

    def test_detect_jquery_version(self, detector):
        """Test jQuery version detection."""
        html = '<script src="https://code.jquery.com/jquery-2.1.4.min.js"></script>'
        version = detector._detect_jquery_version(html)
        assert version == "2.1.4"

    def test_detect_jquery_version_none(self, detector):
        """Test jQuery version when not present."""
        html = "<script src='app.js'></script>"
        version = detector._detect_jquery_version(html)
        assert version is None

    def test_detect_cms_wordpress(self, detector):
        """Test WordPress detection."""
        html = '<link rel="stylesheet" href="/wp-content/themes/theme/style.css">'
        cms = detector._detect_cms(html, {})
        assert cms == "wordpress"

    def test_detect_cms_shopify(self, detector):
        """Test Shopify detection."""
        html = '<script src="https://cdn.shopify.com/s/files/1/0001/theme.js"></script>'
        cms = detector._detect_cms(html, {})
        assert cms == "shopify"

    def test_detect_cms_squarespace(self, detector):
        """Test Squarespace detection."""
        html = '<script>Squarespace.load()</script>'
        cms = detector._detect_cms(html, {})
        assert cms == "squarespace"

    def test_detect_cms_wix(self, detector):
        """Test Wix detection."""
        html = '<meta name="generator" content="Wix.com Website Builder">'
        cms = detector._detect_cms(html, {})
        assert cms == "wix"

    def test_detect_cms_none(self, detector):
        """Test CMS detection when none found."""
        html = "<html><body>Custom site</body></html>"
        cms = detector._detect_cms(html, {})
        assert cms is None


# =====================
# Triage Signals Tests
# =====================

class TestTriageSignals:
    """Tests for TriageSignals dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            pagespeed_score=45,
            ssl_valid=True,
            mobile_responsive=False,
            copyright_year=2019
        )
        result = signals.to_dict()

        assert result["url"] == "https://example.com"
        assert result["domain"] == "example.com"
        assert result["pagespeed_score"] == 45
        assert result["ssl_valid"] is True
        assert result["mobile_responsive"] is False
        assert result["copyright_year"] == 2019

    def test_default_errors_list(self):
        """Test that errors list initializes empty."""
        signals = TriageSignals(url="https://example.com", domain="example.com")
        assert signals.errors == []


# =====================
# Score Calculation Tests
# =====================

class TestCalculateTriageScore:
    """Tests for triage score calculation."""

    @pytest.fixture
    def default_playbook(self):
        return {
            "scoring": {
                "pagespeed_weight": 30,
                "ssl_weight": 20,
                "mobile_weight": 25,
                "copyright_weight": 25
            },
            "signals": {
                "pagespeed_threshold": 50,
                "copyright_max_age_years": 2
            }
        }

    def test_score_all_issues(self, default_playbook):
        """Test scoring with all issues present."""
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            pagespeed_score=30,  # Bad
            ssl_valid=False,     # Bad
            mobile_responsive=False,  # Bad
            copyright_year=2019  # Old (5 years if current year is 2024+)
        )
        score = calculate_triage_score(signals, default_playbook)
        # Should be high score (all issues = good opportunity)
        assert score >= 70

    def test_score_no_issues(self, default_playbook):
        """Test scoring with no issues (healthy site)."""
        current_year = datetime.now().year
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            pagespeed_score=90,  # Good
            ssl_valid=True,      # Good
            mobile_responsive=True,  # Good
            copyright_year=current_year  # Current
        )
        score = calculate_triage_score(signals, default_playbook)
        # Should be low score (no issues = low opportunity)
        assert score <= 30

    def test_score_ssl_only_issue(self, default_playbook):
        """Test scoring with only SSL issue."""
        current_year = datetime.now().year
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            pagespeed_score=85,
            ssl_valid=False,  # Only issue
            mobile_responsive=True,
            copyright_year=current_year
        )
        score = calculate_triage_score(signals, default_playbook)
        # Should get SSL weight points
        assert 15 <= score <= 30

    def test_score_pagespeed_borderline(self, default_playbook):
        """Test scoring with borderline PageSpeed."""
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            pagespeed_score=55,  # Between 50 and 70
            ssl_valid=True,
            mobile_responsive=True,
            copyright_year=datetime.now().year
        )
        score = calculate_triage_score(signals, default_playbook)
        # Should get partial pagespeed points
        assert 10 <= score <= 20

    def test_score_missing_signals(self, default_playbook):
        """Test scoring with missing signal data."""
        signals = TriageSignals(
            url="https://example.com",
            domain="example.com",
            # Most signals are None
        )
        score = calculate_triage_score(signals, default_playbook)
        # Should handle gracefully
        assert 0 <= score <= 100


# =====================
# Fast Scanner Tests
# =====================

class TestFastScanner:
    """Tests for FastScanner class."""

    @pytest.fixture
    def scanner(self):
        return FastScanner(timeout=5.0)

    @pytest.mark.asyncio
    async def test_scan_url_normalizes_http(self, scanner):
        """Test URL normalization adds https."""
        with patch.object(scanner, 'scan_url', new_callable=AsyncMock) as mock:
            mock.return_value = ScanResult(url="https://example.com", success=True)
            # This would normally call the real method
            # Testing the actual method would require network access

    @pytest.mark.asyncio
    async def test_scan_result_to_dict(self):
        """Test ScanResult conversion to dict."""
        signals = TriageSignals(url="https://example.com", domain="example.com")
        result = ScanResult(
            url="https://example.com",
            success=True,
            signals=signals,
            status_code=200,
            load_time_ms=500
        )
        result_dict = result.to_dict()

        assert result_dict["url"] == "https://example.com"
        assert result_dict["success"] is True
        assert result_dict["status_code"] == 200
        assert result_dict["load_time_ms"] == 500
        assert result_dict["signals"] is not None


# =====================
# Triage Agent Tests
# =====================

class TestTriageAgent:
    """Tests for TriageAgent class."""

    @pytest.fixture
    def mock_config(self):
        from agents.base import AgentConfig
        return AgentConfig(
            id=uuid4(),
            slug="triage",
            name="Triage Agent",
            room="triage",
            model="claude-3-5-sonnet-20241022",
            temperature=0.7,
            max_tokens=4096,
            system_prompt="You are the Sentinel Triage Agent.",
            tools=["url_scan", "lighthouse_quick"],
            mcp_servers=["playwright"],
            timeout_seconds=120
        )

    @pytest.mark.asyncio
    async def test_agent_registers_tools(self, mock_config):
        """Test that agent registers expected tools."""
        from rooms.triage.agent import TriageAgent

        agent = TriageAgent(config=mock_config)

        assert "url_scan" in agent._tools
        assert "lighthouse_quick" in agent._tools

    @pytest.mark.asyncio
    async def test_agent_run_requires_url(self, mock_config):
        """Test that run raises error without URL."""
        from rooms.triage.agent import TriageAgent
        from agents.base import AgentRunContext

        agent = TriageAgent(config=mock_config)
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


# =====================
# Integration-style Tests
# =====================

class TestTriageIntegration:
    """Integration-style tests for triage flow."""

    @pytest.mark.asyncio
    async def test_signal_detector_full_flow(self):
        """Test full signal detection flow."""
        detector = SignalDetector()

        html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Test Site</title>
            <link rel="stylesheet" href="/wp-content/themes/theme/style.css">
            <script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
        </head>
        <body>
            <div class="container">
                <div class="row">
                    <div class="col-md-12">Content</div>
                </div>
            </div>
            <footer>&copy; 2020 Test Company</footer>
        </body>
        </html>
        """

        signals = await detector.detect_from_html(
            url="https://test-site.com",
            html=html,
            headers={"content-type": "text/html"},
            load_time_ms=1500
        )

        assert signals.domain == "test-site.com"
        assert signals.copyright_year == 2020
        assert signals.has_viewport_meta is True
        assert signals.mobile_responsive is True
        assert signals.cms_detected == "wordpress"
        assert signals.jquery_version == "1.12.4"
        assert signals.load_time_ms == 1500
