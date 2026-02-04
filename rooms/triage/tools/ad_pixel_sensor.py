"""
AdPixelSensor - Detects advertising pixels and tracking scripts on websites.

Identifies:
- Meta Pixel (Facebook)
- Google Ads conversion tracking
- Google Analytics 4
- TikTok Pixel
- LinkedIn Insight Tag
- Pinterest Tag
- Twitter/X Pixel
- Snapchat Pixel
- Other common tracking pixels

Businesses with ad pixels but broken funnels = high-value prospects.
They're already spending money on ads but may have optimization opportunities.
"""
import re
from typing import Optional, List, Dict
from dataclasses import dataclass, field

import httpx
import structlog

from rooms.triage.tools.registry import register_tool, ToolCategory

logger = structlog.get_logger()


@dataclass
class PixelInfo:
    """Information about a detected pixel."""
    name: str
    platform: str
    pixel_id: Optional[str] = None
    version: Optional[str] = None
    confidence: str = "high"  # 'high', 'medium', 'low'

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "platform": self.platform,
            "pixel_id": self.pixel_id,
            "version": self.version,
            "confidence": self.confidence
        }


@dataclass
class AdPixelAnalysis:
    """Results of ad pixel detection."""
    url: str
    total_pixels_found: int = 0
    pixels: List[PixelInfo] = field(default_factory=list)

    # Platform-specific flags (for easy filtering)
    has_meta_pixel: bool = False
    has_google_ads: bool = False
    has_google_analytics: bool = False
    has_ga4: bool = False
    has_tiktok_pixel: bool = False
    has_linkedin_pixel: bool = False
    has_pinterest_pixel: bool = False
    has_twitter_pixel: bool = False
    has_snapchat_pixel: bool = False

    # Analysis
    ad_spend_indicator: str = "none"  # 'none', 'low', 'medium', 'high'
    tracking_maturity: str = "none"  # 'none', 'basic', 'intermediate', 'advanced'
    opportunities: List[str] = field(default_factory=list)

    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "total_pixels_found": self.total_pixels_found,
            "pixels": [p.to_dict() for p in self.pixels],
            "has_meta_pixel": self.has_meta_pixel,
            "has_google_ads": self.has_google_ads,
            "has_google_analytics": self.has_google_analytics,
            "has_ga4": self.has_ga4,
            "has_tiktok_pixel": self.has_tiktok_pixel,
            "has_linkedin_pixel": self.has_linkedin_pixel,
            "has_pinterest_pixel": self.has_pinterest_pixel,
            "has_twitter_pixel": self.has_twitter_pixel,
            "has_snapchat_pixel": self.has_snapchat_pixel,
            "ad_spend_indicator": self.ad_spend_indicator,
            "tracking_maturity": self.tracking_maturity,
            "opportunities": self.opportunities,
            "errors": self.errors
        }


# Pixel detection patterns
PIXEL_PATTERNS = {
    "meta_pixel": {
        "platform": "Meta (Facebook)",
        "patterns": [
            (r'fbq\s*\(\s*["\']init["\']\s*,\s*["\'](\d+)["\']', "high"),
            (r'connect\.facebook\.net.*fbevents\.js', "high"),
            (r'facebook\.com/tr\?id=(\d+)', "high"),
            (r'_fbq', "medium"),
            (r'fbPixelId', "medium"),
        ],
        "id_pattern": r'fbq\s*\(\s*["\']init["\']\s*,\s*["\'](\d+)["\']'
    },
    "google_ads": {
        "platform": "Google Ads",
        "patterns": [
            (r'gtag\s*\(\s*["\']config["\']\s*,\s*["\']AW-(\d+)["\']', "high"),
            (r'googleadservices\.com/pagead/conversion/(\d+)', "high"),
            (r'google_conversion_id\s*=\s*(\d+)', "high"),
            (r'AW-\d+', "medium"),
        ],
        "id_pattern": r'AW-(\d+)'
    },
    "google_analytics_ua": {
        "platform": "Google Analytics (Universal)",
        "patterns": [
            (r'google-analytics\.com/analytics\.js', "high"),
            (r'ga\s*\(\s*["\']create["\']\s*,\s*["\']UA-(\d+-\d+)["\']', "high"),
            (r'UA-\d+-\d+', "medium"),
        ],
        "id_pattern": r'UA-(\d+-\d+)'
    },
    "google_analytics_ga4": {
        "platform": "Google Analytics 4",
        "patterns": [
            (r'gtag\s*\(\s*["\']config["\']\s*,\s*["\']G-([A-Z0-9]+)["\']', "high"),
            (r'googletagmanager\.com/gtag/js\?id=G-([A-Z0-9]+)', "high"),
            (r'G-[A-Z0-9]{10}', "medium"),
        ],
        "id_pattern": r'G-([A-Z0-9]+)'
    },
    "google_tag_manager": {
        "platform": "Google Tag Manager",
        "patterns": [
            (r'googletagmanager\.com/gtm\.js\?id=GTM-([A-Z0-9]+)', "high"),
            (r'GTM-[A-Z0-9]+', "medium"),
        ],
        "id_pattern": r'GTM-([A-Z0-9]+)'
    },
    "tiktok_pixel": {
        "platform": "TikTok",
        "patterns": [
            (r'ttq\.load\s*\(\s*["\']([A-Z0-9]+)["\']', "high"),
            (r'analytics\.tiktok\.com', "high"),
            (r'tiktok.*pixel', "medium"),
        ],
        "id_pattern": r'ttq\.load\s*\(\s*["\']([A-Z0-9]+)["\']'
    },
    "linkedin_pixel": {
        "platform": "LinkedIn",
        "patterns": [
            (r'_linkedin_partner_id\s*=\s*["\']?(\d+)', "high"),
            (r'snap\.licdn\.com/li\.lms-analytics', "high"),
            (r'linkedin.*insight', "medium"),
        ],
        "id_pattern": r'_linkedin_partner_id\s*=\s*["\']?(\d+)'
    },
    "pinterest_pixel": {
        "platform": "Pinterest",
        "patterns": [
            (r'pintrk\s*\(\s*["\']load["\']\s*,\s*["\'](\d+)["\']', "high"),
            (r'ct\.pinterest\.com', "high"),
            (r'pinterest.*tag', "medium"),
        ],
        "id_pattern": r'pintrk\s*\(\s*["\']load["\']\s*,\s*["\'](\d+)["\']'
    },
    "twitter_pixel": {
        "platform": "Twitter/X",
        "patterns": [
            (r'twq\s*\(\s*["\']init["\']\s*,\s*["\']([a-z0-9]+)["\']', "high"),
            (r'static\.ads-twitter\.com', "high"),
            (r'twitter.*pixel', "medium"),
        ],
        "id_pattern": r'twq\s*\(\s*["\']init["\']\s*,\s*["\']([a-z0-9]+)["\']'
    },
    "snapchat_pixel": {
        "platform": "Snapchat",
        "patterns": [
            (r'snaptr\s*\(\s*["\']init["\']\s*,\s*["\']([a-f0-9-]+)["\']', "high"),
            (r'sc-static\.net/scevent\.min\.js', "high"),
        ],
        "id_pattern": r'snaptr\s*\(\s*["\']init["\']\s*,\s*["\']([a-f0-9-]+)["\']'
    },
    "hotjar": {
        "platform": "Hotjar",
        "patterns": [
            (r'hotjar\.com.*hjid=(\d+)', "high"),
            (r'static\.hotjar\.com', "high"),
            (r'hj\s*\(\s*["\']identify["\']', "medium"),
        ],
        "id_pattern": r'hjid=(\d+)'
    },
    "hubspot": {
        "platform": "HubSpot",
        "patterns": [
            (r'js\.hs-scripts\.com/(\d+)\.js', "high"),
            (r'js\.hs-analytics\.net', "high"),
            (r'_hsq', "medium"),
        ],
        "id_pattern": r'js\.hs-scripts\.com/(\d+)\.js'
    },
    "klaviyo": {
        "platform": "Klaviyo",
        "patterns": [
            (r'static\.klaviyo\.com', "high"),
            (r'klaviyo.*company.*([A-Za-z0-9]+)', "high"),
            (r'_learnq', "medium"),
        ],
        "id_pattern": r'company.*["\']([A-Za-z0-9]+)["\']'
    },
    "microsoft_clarity": {
        "platform": "Microsoft Clarity",
        "patterns": [
            (r'clarity\.ms/tag/([a-z0-9]+)', "high"),
            (r'microsoft.*clarity', "medium"),
        ],
        "id_pattern": r'clarity\.ms/tag/([a-z0-9]+)'
    },
}


class AdPixelScanner:
    """Scanner for detecting advertising pixels."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def scan(self, url: str) -> AdPixelAnalysis:
        """
        Scan a URL for advertising pixels.

        Args:
            url: URL to scan

        Returns:
            AdPixelAnalysis with detected pixels
        """
        result = AdPixelAnalysis(url=url)

        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                html = response.text

                # Detect all pixels
                for pixel_key, config in PIXEL_PATTERNS.items():
                    pixel_info = self._detect_pixel(html, pixel_key, config)
                    if pixel_info:
                        result.pixels.append(pixel_info)

                        # Set platform-specific flags
                        if pixel_key == "meta_pixel":
                            result.has_meta_pixel = True
                        elif pixel_key == "google_ads":
                            result.has_google_ads = True
                        elif pixel_key == "google_analytics_ua":
                            result.has_google_analytics = True
                        elif pixel_key == "google_analytics_ga4":
                            result.has_ga4 = True
                            result.has_google_analytics = True
                        elif pixel_key == "tiktok_pixel":
                            result.has_tiktok_pixel = True
                        elif pixel_key == "linkedin_pixel":
                            result.has_linkedin_pixel = True
                        elif pixel_key == "pinterest_pixel":
                            result.has_pinterest_pixel = True
                        elif pixel_key == "twitter_pixel":
                            result.has_twitter_pixel = True
                        elif pixel_key == "snapchat_pixel":
                            result.has_snapchat_pixel = True

                result.total_pixels_found = len(result.pixels)

                # Analyze tracking maturity and ad spend indicator
                result.ad_spend_indicator = self._calculate_ad_spend_indicator(result)
                result.tracking_maturity = self._calculate_tracking_maturity(result)
                result.opportunities = self._identify_opportunities(result)

        except httpx.TimeoutException:
            result.errors.append(f"Timeout after {self.timeout}s")
        except Exception as e:
            result.errors.append(str(e))
            logger.warning("Ad pixel scan error", url=url, error=str(e))

        return result

    def _detect_pixel(self, html: str, pixel_key: str, config: dict) -> Optional[PixelInfo]:
        """Detect a specific pixel in HTML."""
        html_lower = html.lower()
        best_confidence = None
        pixel_id = None

        for pattern, confidence in config["patterns"]:
            if re.search(pattern, html, re.IGNORECASE):
                if best_confidence is None or confidence == "high":
                    best_confidence = confidence

                # Try to extract pixel ID
                if "id_pattern" in config and not pixel_id:
                    id_match = re.search(config["id_pattern"], html, re.IGNORECASE)
                    if id_match:
                        pixel_id = id_match.group(1)

                if best_confidence == "high":
                    break

        if best_confidence:
            return PixelInfo(
                name=pixel_key.replace("_", " ").title(),
                platform=config["platform"],
                pixel_id=pixel_id,
                confidence=best_confidence
            )

        return None

    def _calculate_ad_spend_indicator(self, result: AdPixelAnalysis) -> str:
        """Calculate likely ad spend level based on pixels."""
        # Count paid advertising pixels
        paid_platforms = sum([
            result.has_meta_pixel,
            result.has_google_ads,
            result.has_tiktok_pixel,
            result.has_linkedin_pixel,
            result.has_pinterest_pixel,
            result.has_twitter_pixel,
            result.has_snapchat_pixel,
        ])

        if paid_platforms >= 3:
            return "high"
        elif paid_platforms >= 2:
            return "medium"
        elif paid_platforms >= 1:
            return "low"
        else:
            return "none"

    def _calculate_tracking_maturity(self, result: AdPixelAnalysis) -> str:
        """Calculate tracking/analytics maturity level."""
        score = 0

        # Basic analytics
        if result.has_google_analytics:
            score += 1
        if result.has_ga4:
            score += 1

        # Tag management
        gtm_found = any(p.name.lower() == "google tag manager" for p in result.pixels)
        if gtm_found:
            score += 2

        # Marketing automation
        hubspot = any("hubspot" in p.name.lower() for p in result.pixels)
        klaviyo = any("klaviyo" in p.name.lower() for p in result.pixels)
        if hubspot or klaviyo:
            score += 2

        # Heatmaps/session recording
        hotjar = any("hotjar" in p.name.lower() for p in result.pixels)
        clarity = any("clarity" in p.name.lower() for p in result.pixels)
        if hotjar or clarity:
            score += 1

        # Multiple ad platforms
        if result.ad_spend_indicator in ("medium", "high"):
            score += 1

        if score >= 5:
            return "advanced"
        elif score >= 3:
            return "intermediate"
        elif score >= 1:
            return "basic"
        else:
            return "none"

    def _identify_opportunities(self, result: AdPixelAnalysis) -> List[str]:
        """Identify tracking/optimization opportunities."""
        opportunities = []

        # Missing basic analytics
        if not result.has_google_analytics and not result.has_ga4:
            opportunities.append("Add Google Analytics for basic website tracking")
        elif result.has_google_analytics and not result.has_ga4:
            opportunities.append("Upgrade to Google Analytics 4 (UA deprecated)")

        # Running ads without proper tracking
        if result.has_meta_pixel and not result.has_google_analytics:
            opportunities.append("Add analytics to measure Meta ad performance")
        if result.has_google_ads and not result.has_google_analytics:
            opportunities.append("Add analytics to measure Google Ads ROI")

        # Missing heatmaps
        hotjar = any("hotjar" in p.name.lower() for p in result.pixels)
        clarity = any("clarity" in p.name.lower() for p in result.pixels)
        if result.has_meta_pixel or result.has_google_ads:
            if not hotjar and not clarity:
                opportunities.append("Add heatmap tool (Hotjar/Clarity) to optimize landing pages")

        # Missing marketing automation
        hubspot = any("hubspot" in p.name.lower() for p in result.pixels)
        klaviyo = any("klaviyo" in p.name.lower() for p in result.pixels)
        if result.ad_spend_indicator in ("medium", "high") and not hubspot and not klaviyo:
            opportunities.append("Add marketing automation for better lead nurturing")

        # Missing retargeting platforms
        if result.has_meta_pixel and not result.has_google_ads:
            opportunities.append("Add Google Ads for cross-platform retargeting")
        if result.has_google_ads and not result.has_meta_pixel:
            opportunities.append("Add Meta Pixel for Facebook/Instagram retargeting")

        # High spend but basic tracking
        if result.ad_spend_indicator == "high" and result.tracking_maturity == "basic":
            opportunities.append("Implement advanced attribution tracking for multi-platform campaigns")

        return opportunities


# Singleton scanner
_scanner = AdPixelScanner()


@register_tool(
    name="ad_pixel_sensor",
    category=ToolCategory.SCAN,
    description="Detects Meta/Google/TikTok ad pixels and tracking scripts to identify ad spend",
    schema={
        "url": {
            "type": "string",
            "required": True,
            "description": "URL to scan for ad pixels"
        }
    },
    tags=["scan", "advertising", "pixels", "tracking", "analytics"]
)
async def ad_pixel_sensor(url: str) -> dict:
    """
    Scan a URL for advertising pixels and tracking scripts.

    Args:
        url: URL to scan

    Returns:
        Dict with detected pixels and analysis
    """
    result = await _scanner.scan(url)
    return result.to_dict()
