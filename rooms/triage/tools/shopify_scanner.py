"""
ShopifyStoreScanner - Detects and analyzes Shopify stores.

Identifies:
- Shopify theme name and version
- Theme age and last update indicators
- Missing revenue-generating apps (Klaviyo, Yotpo, ReCharge, etc.)
- Checkout optimization opportunities
- Performance issues specific to Shopify

This tool helps identify Shopify stores that could benefit from
professional optimization and app integration services.
"""
import re
from typing import Optional, List
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import structlog

from rooms.triage.tools.registry import register_tool, ToolCategory

logger = structlog.get_logger()


@dataclass
class ShopifyAnalysis:
    """Results of Shopify store analysis."""
    is_shopify: bool = False
    theme_name: Optional[str] = None
    theme_id: Optional[str] = None
    theme_version: Optional[str] = None
    shop_id: Optional[str] = None

    # App detection
    detected_apps: List[str] = field(default_factory=list)
    missing_essential_apps: List[str] = field(default_factory=list)

    # Opportunities
    opportunities: List[str] = field(default_factory=list)
    opportunity_score: int = 0  # 0-100

    # Technical details
    uses_shopify_payments: Optional[bool] = None
    has_abandoned_cart: Optional[bool] = None
    has_email_capture: Optional[bool] = None
    has_reviews_app: Optional[bool] = None
    has_subscription_app: Optional[bool] = None
    has_upsell_app: Optional[bool] = None

    # Errors
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_shopify": self.is_shopify,
            "theme_name": self.theme_name,
            "theme_id": self.theme_id,
            "theme_version": self.theme_version,
            "shop_id": self.shop_id,
            "detected_apps": self.detected_apps,
            "missing_essential_apps": self.missing_essential_apps,
            "opportunities": self.opportunities,
            "opportunity_score": self.opportunity_score,
            "uses_shopify_payments": self.uses_shopify_payments,
            "has_abandoned_cart": self.has_abandoned_cart,
            "has_email_capture": self.has_email_capture,
            "has_reviews_app": self.has_reviews_app,
            "has_subscription_app": self.has_subscription_app,
            "has_upsell_app": self.has_upsell_app,
            "errors": self.errors
        }


# Essential apps that revenue-focused stores typically need
ESSENTIAL_APPS = {
    "email_marketing": ["klaviyo", "omnisend", "mailchimp", "drip", "sendlane"],
    "reviews": ["yotpo", "judge.me", "loox", "stamped", "okendo"],
    "subscriptions": ["recharge", "bold-subscriptions", "yotpo-subscriptions", "loop", "appstle"],
    "upsell": ["rebuy", "bold-upsell", "reconvert", "aftersell", "zipify"],
    "sms": ["postscript", "attentive", "smsbump", "klaviyo-sms"],
    "loyalty": ["smile.io", "yotpo-loyalty", "loyaltylion", "growave"],
    "analytics": ["triple-whale", "lifetimely", "polar-analytics", "northbeam"],
}

# Patterns to detect apps in HTML
APP_DETECTION_PATTERNS = {
    "klaviyo": [r"klaviyo", r"klav_", r"KlaviyoSubscribe"],
    "omnisend": [r"omnisend", r"omnisrc"],
    "yotpo": [r"yotpo", r"staticw2\.yotpo\.com"],
    "judge.me": [r"judge\.me", r"judgeme"],
    "loox": [r"loox\.io", r"looxcdn"],
    "recharge": [r"recharge", r"rechargepayments"],
    "rebuy": [r"rebuy", r"rebuyengine"],
    "postscript": [r"postscript\.io", r"postscriptapp"],
    "attentive": [r"attentive\.ly", r"attentivemobile"],
    "smile.io": [r"smile\.io", r"smile-io"],
    "triple-whale": [r"triplewhale", r"triple-whale"],
    "gorgias": [r"gorgias", r"gorgias\.chat"],
    "afterpay": [r"afterpay", r"clearpay"],
    "klarna": [r"klarna"],
    "affirm": [r"affirm"],
    "shopify-payments": [r"shopify.*payments", r"shop_pay"],
}


class ShopifyScanner:
    """Scanner for Shopify store analysis."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def scan(self, url: str) -> ShopifyAnalysis:
        """
        Scan a URL to detect and analyze Shopify store.

        Args:
            url: URL to scan

        Returns:
            ShopifyAnalysis with findings
        """
        result = ShopifyAnalysis()

        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                html = response.text
                headers = dict(response.headers)

                # Check if it's Shopify
                result.is_shopify = self._detect_shopify(html, headers)

                if not result.is_shopify:
                    return result

                # Extract Shopify-specific data
                result.theme_name = self._extract_theme_name(html)
                result.theme_id = self._extract_theme_id(html)
                result.shop_id = self._extract_shop_id(html)

                # Detect installed apps
                result.detected_apps = self._detect_apps(html)

                # Identify missing essential apps
                result.missing_essential_apps = self._identify_missing_apps(result.detected_apps)

                # Check specific capabilities
                result.has_email_capture = self._has_email_capture(html)
                result.has_reviews_app = any(app in result.detected_apps for app in ESSENTIAL_APPS["reviews"])
                result.has_subscription_app = any(app in result.detected_apps for app in ESSENTIAL_APPS["subscriptions"])
                result.has_upsell_app = any(app in result.detected_apps for app in ESSENTIAL_APPS["upsell"])
                result.uses_shopify_payments = self._detect_shopify_payments(html)

                # Generate opportunities
                result.opportunities = self._generate_opportunities(result)
                result.opportunity_score = self._calculate_opportunity_score(result)

        except httpx.TimeoutException:
            result.errors.append(f"Timeout after {self.timeout}s")
        except Exception as e:
            result.errors.append(str(e))
            logger.warning("Shopify scan error", url=url, error=str(e))

        return result

    def _detect_shopify(self, html: str, headers: dict) -> bool:
        """Detect if site is running on Shopify."""
        shopify_indicators = [
            "cdn.shopify.com",
            "Shopify.theme",
            "shopify-section",
            "myshopify.com",
            "/cdn/shop/",
            "Shopify.checkout",
        ]

        html_lower = html.lower()
        for indicator in shopify_indicators:
            if indicator.lower() in html_lower:
                return True

        # Check headers
        if "x-shopid" in headers or "x-shardid" in headers:
            return True

        return False

    def _extract_theme_name(self, html: str) -> Optional[str]:
        """Extract Shopify theme name."""
        patterns = [
            r'Shopify\.theme\s*=\s*{[^}]*"name"\s*:\s*"([^"]+)"',
            r'data-theme-name="([^"]+)"',
            r'theme_name.*?["\']([^"\']+)["\']',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _extract_theme_id(self, html: str) -> Optional[str]:
        """Extract Shopify theme ID."""
        patterns = [
            r'Shopify\.theme\s*=\s*{[^}]*"id"\s*:\s*(\d+)',
            r'data-theme-id="(\d+)"',
            r'theme_store_id.*?(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None

    def _extract_shop_id(self, html: str) -> Optional[str]:
        """Extract Shopify shop ID."""
        patterns = [
            r'"shopId"\s*:\s*(\d+)',
            r'Shopify\.shop\s*=\s*"([^"]+)"',
            r'data-shop-id="(\d+)"',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None

    def _detect_apps(self, html: str) -> List[str]:
        """Detect installed Shopify apps from HTML content."""
        detected = []
        html_lower = html.lower()

        for app_name, patterns in APP_DETECTION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, html_lower):
                    if app_name not in detected:
                        detected.append(app_name)
                    break

        return detected

    def _identify_missing_apps(self, detected_apps: List[str]) -> List[str]:
        """Identify essential apps that are missing."""
        missing = []
        detected_lower = [app.lower() for app in detected_apps]

        for category, apps in ESSENTIAL_APPS.items():
            has_category_app = any(
                any(app_pattern in detected for detected in detected_lower)
                for app_pattern in apps
            )
            if not has_category_app:
                missing.append(f"No {category.replace('_', ' ')} app detected")

        return missing

    def _has_email_capture(self, html: str) -> bool:
        """Check if store has email capture functionality."""
        patterns = [
            r'type=["\']email["\']',
            r'newsletter',
            r'subscribe',
            r'signup.*email',
            r'email.*capture',
            r'klaviyo',
            r'omnisend',
        ]

        html_lower = html.lower()
        return any(re.search(p, html_lower) for p in patterns)

    def _detect_shopify_payments(self, html: str) -> bool:
        """Check if store uses Shopify Payments / Shop Pay."""
        patterns = [
            r'shop.?pay',
            r'shopify.*payments',
            r'accelerated_checkout',
        ]

        html_lower = html.lower()
        return any(re.search(p, html_lower) for p in patterns)

    def _generate_opportunities(self, result: ShopifyAnalysis) -> List[str]:
        """Generate list of improvement opportunities."""
        opportunities = []

        if not result.has_email_capture:
            opportunities.append("Add email capture/popup for list building")

        if not result.has_reviews_app:
            opportunities.append("Add reviews/social proof app to increase conversions")

        if not result.has_subscription_app:
            opportunities.append("Consider subscription model for recurring revenue")

        if not result.has_upsell_app:
            opportunities.append("Add upsell/cross-sell app to increase AOV")

        if "klaviyo" not in result.detected_apps and "omnisend" not in result.detected_apps:
            opportunities.append("Upgrade to advanced email marketing (Klaviyo/Omnisend)")

        if not result.uses_shopify_payments:
            opportunities.append("Enable Shop Pay for faster checkout")

        # Check for analytics
        has_analytics = any(
            app in result.detected_apps
            for app in ESSENTIAL_APPS.get("analytics", [])
        )
        if not has_analytics:
            opportunities.append("Add analytics app for better attribution")

        return opportunities

    def _calculate_opportunity_score(self, result: ShopifyAnalysis) -> int:
        """Calculate opportunity score (0-100)."""
        if not result.is_shopify:
            return 0

        score = 0
        max_score = 100

        # Missing apps = opportunities (each worth ~12 points)
        score += min(len(result.missing_essential_apps) * 12, 60)

        # Missing specific high-value features
        if not result.has_email_capture:
            score += 15
        if not result.has_reviews_app:
            score += 10
        if not result.has_upsell_app:
            score += 8
        if not result.uses_shopify_payments:
            score += 7

        return min(score, max_score)


# Create singleton scanner instance
_scanner = ShopifyScanner()


@register_tool(
    name="shopify_scanner",
    category=ToolCategory.SCAN,
    description="Analyzes Shopify stores for theme age, missing revenue apps, and optimization opportunities",
    schema={
        "url": {"type": "string", "required": True, "description": "URL of the store to scan"}
    },
    tags=["shopify", "ecommerce", "scan"]
)
async def shopify_store_scanner(url: str) -> dict:
    """
    Scan and analyze a Shopify store.

    Args:
        url: URL of the store to scan

    Returns:
        Dict with Shopify analysis results
    """
    result = await _scanner.scan(url)
    return result.to_dict()
