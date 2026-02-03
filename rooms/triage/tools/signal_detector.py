"""
Signal Detector - Extract high-intent signals from websites.

High-intent signals indicate the site owner needs professional help:
- PageSpeed score < 50: Performance problems
- SSL issues: Security/trust problems
- Not mobile responsive: Lost mobile traffic
- Copyright year > 2 years old: Neglected site
"""
import re
import ssl
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()


@dataclass
class TriageSignals:
    """High-intent signals extracted from a URL."""
    url: str
    domain: str

    # Core signals
    pagespeed_score: Optional[int] = None  # 0-100
    ssl_valid: Optional[bool] = None
    ssl_expires_days: Optional[int] = None
    mobile_responsive: Optional[bool] = None
    copyright_year: Optional[int] = None

    # Additional signals
    has_viewport_meta: Optional[bool] = None
    jquery_version: Optional[str] = None
    cms_detected: Optional[str] = None  # 'wordpress', 'shopify', etc.
    load_time_ms: Optional[int] = None

    # Errors during detection
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "url": self.url,
            "domain": self.domain,
            "pagespeed_score": self.pagespeed_score,
            "ssl_valid": self.ssl_valid,
            "ssl_expires_days": self.ssl_expires_days,
            "mobile_responsive": self.mobile_responsive,
            "copyright_year": self.copyright_year,
            "has_viewport_meta": self.has_viewport_meta,
            "jquery_version": self.jquery_version,
            "cms_detected": self.cms_detected,
            "load_time_ms": self.load_time_ms,
            "errors": self.errors
        }


class SignalDetector:
    """
    Detects high-intent signals from HTML content and metadata.

    Uses lightweight extraction - no full page rendering required.
    For fast-pass triage, we extract signals from:
    - Raw HTML content
    - HTTP headers
    - SSL certificate
    """

    def __init__(self):
        self.current_year = datetime.now().year

    async def detect_from_html(
        self,
        url: str,
        html: str,
        headers: Optional[dict] = None,
        load_time_ms: Optional[int] = None
    ) -> TriageSignals:
        """
        Extract signals from HTML content.

        Args:
            url: The URL being analyzed
            html: Raw HTML content
            headers: HTTP response headers
            load_time_ms: Page load time in milliseconds

        Returns:
            TriageSignals with detected values
        """
        parsed = urlparse(url)
        domain = parsed.netloc

        signals = TriageSignals(
            url=url,
            domain=domain,
            load_time_ms=load_time_ms
        )

        # Extract signals
        signals.copyright_year = self._extract_copyright_year(html)
        signals.has_viewport_meta = self._has_viewport_meta(html)
        signals.mobile_responsive = self._detect_mobile_responsive(html)
        signals.jquery_version = self._detect_jquery_version(html)
        signals.cms_detected = self._detect_cms(html, headers)

        # Check SSL
        if parsed.scheme == "https":
            ssl_info = await self._check_ssl(parsed.netloc)
            signals.ssl_valid = ssl_info.get("valid", False)
            signals.ssl_expires_days = ssl_info.get("expires_days")
        else:
            signals.ssl_valid = False

        logger.debug(
            "Signals extracted",
            url=url,
            copyright_year=signals.copyright_year,
            mobile_responsive=signals.mobile_responsive,
            ssl_valid=signals.ssl_valid
        )

        return signals

    def _extract_copyright_year(self, html: str) -> Optional[int]:
        """
        Extract copyright year from HTML.

        Looks for patterns like:
        - (c) 2019
        - copyright 2020
        - &copy; 2021
        """
        patterns = [
            r'(?:©|&copy;|\(c\)|copyright)\s*(\d{4})',
            r'(\d{4})\s*(?:©|&copy;|\(c\)|copyright)',
            r'(?:©|&copy;)\s*\d{4}\s*[-–]\s*(\d{4})',  # Range: 2019-2023
        ]

        html_lower = html.lower()

        for pattern in patterns:
            matches = re.findall(pattern, html_lower, re.IGNORECASE)
            if matches:
                # Return the most recent year found
                years = [int(y) for y in matches if 1990 <= int(y) <= self.current_year + 1]
                if years:
                    return max(years)

        return None

    def _has_viewport_meta(self, html: str) -> bool:
        """Check if page has viewport meta tag for mobile."""
        viewport_patterns = [
            r'<meta[^>]*name=["\']viewport["\']',
            r'<meta[^>]*viewport',
        ]
        for pattern in viewport_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return True
        return False

    def _detect_mobile_responsive(self, html: str) -> bool:
        """
        Detect if site appears to be mobile responsive.

        Indicators:
        - Viewport meta tag
        - Bootstrap/Tailwind classes
        - Media queries in inline styles
        - Responsive framework detection
        """
        # Must have viewport meta
        if not self._has_viewport_meta(html):
            return False

        # Check for responsive indicators
        responsive_patterns = [
            r'class=["\'][^"\']*(?:container|row|col-|grid|flex)',  # Grid systems
            r'(?:bootstrap|tailwind|foundation)',  # Frameworks
            r'@media\s*\([^)]*(?:max-width|min-width)',  # Media queries
            r'class=["\'][^"\']*(?:sm:|md:|lg:|xl:)',  # Tailwind breakpoints
            r'class=["\'][^"\']*(?:hidden-xs|visible-)',  # Bootstrap visibility
        ]

        for pattern in responsive_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return True

        return False

    def _detect_jquery_version(self, html: str) -> Optional[str]:
        """
        Detect jQuery version from script tags.

        Old jQuery versions (< 3.0) indicate technical debt.
        """
        patterns = [
            r'jquery[.-]?(\d+\.\d+(?:\.\d+)?)',
            r'jquery\.min\.js\?ver=(\d+\.\d+(?:\.\d+)?)',
            r'jquery/(\d+\.\d+(?:\.\d+)?)/jquery',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _detect_cms(self, html: str, headers: Optional[dict] = None) -> Optional[str]:
        """
        Detect the CMS/platform powering the site.

        Common CMS detection patterns.
        """
        html_lower = html.lower()
        headers = headers or {}

        # WordPress
        if 'wp-content' in html_lower or 'wordpress' in html_lower:
            return 'wordpress'

        # Shopify
        if 'shopify' in html_lower or 'cdn.shopify' in html_lower:
            return 'shopify'

        # Squarespace
        if 'squarespace' in html_lower:
            return 'squarespace'

        # Wix
        if 'wix.com' in html_lower or 'wixsite' in html_lower:
            return 'wix'

        # Webflow
        if 'webflow' in html_lower:
            return 'webflow'

        # Check headers
        x_powered_by = headers.get('x-powered-by', '').lower()
        if 'wordpress' in x_powered_by:
            return 'wordpress'

        return None

    async def _check_ssl(self, hostname: str, port: int = 443) -> dict:
        """
        Check SSL certificate validity and expiration.

        Args:
            hostname: Domain to check
            port: Port (default 443)

        Returns:
            Dict with 'valid' and 'expires_days'
        """
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()

                    # Parse expiration date
                    not_after = cert.get('notAfter')
                    if not_after:
                        # Format: 'Mar 15 12:00:00 2024 GMT'
                        exp_date = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                        days_until_expiry = (exp_date - datetime.now()).days

                        return {
                            "valid": True,
                            "expires_days": days_until_expiry
                        }

                    return {"valid": True, "expires_days": None}

        except ssl.SSLError:
            return {"valid": False, "expires_days": None}
        except socket.timeout:
            return {"valid": None, "expires_days": None}  # Unknown
        except Exception as e:
            logger.debug("SSL check failed", hostname=hostname, error=str(e))
            return {"valid": None, "expires_days": None}


def calculate_triage_score(signals: TriageSignals, playbook_config: dict) -> int:
    """
    Calculate triage score based on signals and playbook rules.

    Args:
        signals: Extracted signals
        playbook_config: Scoring weights from playbook

    Returns:
        Score from 0-100 (higher = better opportunity)
    """
    scoring = playbook_config.get("scoring", {})
    thresholds = playbook_config.get("signals", {})

    score = 0
    max_score = 0

    # PageSpeed (lower is worse = higher score)
    pagespeed_weight = scoring.get("pagespeed_weight", 30)
    max_score += pagespeed_weight
    if signals.pagespeed_score is not None:
        threshold = thresholds.get("pagespeed_threshold", 50)
        if signals.pagespeed_score < threshold:
            # Score inversely - lower pagespeed = higher opportunity
            score += int(pagespeed_weight * (1 - signals.pagespeed_score / 100))
        elif signals.pagespeed_score < 70:
            score += int(pagespeed_weight * 0.5)

    # SSL (invalid = high score)
    ssl_weight = scoring.get("ssl_weight", 20)
    max_score += ssl_weight
    if signals.ssl_valid is False:
        score += ssl_weight  # Full points for SSL issues
    elif signals.ssl_expires_days is not None and signals.ssl_expires_days < 30:
        score += int(ssl_weight * 0.7)  # Expiring soon

    # Mobile (not responsive = high score)
    mobile_weight = scoring.get("mobile_weight", 25)
    max_score += mobile_weight
    if signals.mobile_responsive is False:
        score += mobile_weight
    elif signals.has_viewport_meta is False:
        score += int(mobile_weight * 0.8)

    # Copyright year (older = higher score)
    copyright_weight = scoring.get("copyright_weight", 25)
    max_score += copyright_weight
    if signals.copyright_year is not None:
        current_year = datetime.now().year
        max_age = thresholds.get("copyright_max_age_years", 2)
        years_old = current_year - signals.copyright_year

        if years_old >= max_age:
            # Scale based on how old
            age_factor = min(years_old / 5, 1.0)  # Max out at 5 years
            score += int(copyright_weight * age_factor)

    # Normalize to 0-100
    if max_score > 0:
        final_score = int((score / max_score) * 100)
    else:
        final_score = 0

    logger.debug(
        "Triage score calculated",
        url=signals.url,
        raw_score=score,
        max_score=max_score,
        final_score=final_score
    )

    return final_score
