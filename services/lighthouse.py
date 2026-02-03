"""
Lighthouse audit service for performance and SEO analysis.
Uses Chrome DevTools Protocol via Playwright.
"""
import asyncio
import json
import subprocess
import tempfile
from typing import Optional
from pathlib import Path

import structlog

logger = structlog.get_logger()


class LighthouseService:
    """Service for running Lighthouse audits."""

    def __init__(self, chrome_path: Optional[str] = None):
        self.chrome_path = chrome_path or self._find_chrome()

    def _find_chrome(self) -> str:
        """Find Chrome/Chromium executable path."""
        # Common paths
        paths = [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]

        for path in paths:
            if Path(path).exists():
                return path

        # Try to find via which
        try:
            result = subprocess.run(
                ["which", "chromium"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        # Default fallback
        return "chromium"

    async def run_audit(
        self,
        url: str,
        categories: list[str] = None,
        timeout_seconds: int = 60,
    ) -> dict:
        """
        Run Lighthouse audit on a URL.

        Args:
            url: Website URL to audit
            categories: List of categories to audit (performance, seo, accessibility, best-practices)
            timeout_seconds: Timeout for the audit

        Returns:
            Dict with audit results
        """
        if categories is None:
            categories = ["performance", "seo", "accessibility"]

        logger.info("Starting Lighthouse audit", url=url, categories=categories)

        try:
            # Create temp file for output
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                output_path = f.name

            # Build lighthouse command
            cmd = [
                "npx",
                "lighthouse",
                url,
                "--output=json",
                f"--output-path={output_path}",
                "--chrome-flags=--headless --no-sandbox --disable-gpu",
                f"--only-categories={','.join(categories)}",
                "--quiet",
            ]

            # Run lighthouse
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                logger.error("Lighthouse audit timed out", url=url)
                return self._empty_audit()

            if process.returncode != 0:
                logger.error(
                    "Lighthouse audit failed",
                    url=url,
                    stderr=stderr.decode() if stderr else None
                )
                return self._empty_audit()

            # Read and parse results
            with open(output_path, 'r') as f:
                raw_results = json.load(f)

            # Clean up temp file
            Path(output_path).unlink(missing_ok=True)

            return self._parse_results(raw_results)

        except FileNotFoundError:
            logger.warning("Lighthouse not found, using fallback audit")
            return await self._fallback_audit(url)
        except Exception as e:
            logger.error("Lighthouse audit error", url=url, error=str(e))
            return self._empty_audit()

    async def _fallback_audit(self, url: str) -> dict:
        """Fallback audit using basic checks when Lighthouse is unavailable."""
        import httpx

        result = self._empty_audit()

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                # Time the request
                import time
                start = time.time()
                response = await client.get(url)
                load_time = time.time() - start

                # Basic performance estimate
                result["performance"]["score"] = max(0, min(100, int(100 - (load_time * 20))))
                result["performance"]["firstContentfulPaint"] = load_time
                result["performance"]["largestContentfulPaint"] = load_time * 1.5

                # Basic SEO checks
                html = response.text.lower()

                # Check for title
                if "<title>" in html and "</title>" in html:
                    import re
                    title_match = re.search(r'<title>(.*?)</title>', response.text, re.IGNORECASE)
                    if title_match:
                        result["seo"]["title"] = title_match.group(1).strip()

                # Check for meta description
                desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', response.text, re.IGNORECASE)
                if desc_match:
                    result["seo"]["metaDescription"] = desc_match.group(1)

                # Check for H1
                h1_matches = re.findall(r'<h1[^>]*>(.*?)</h1>', response.text, re.IGNORECASE | re.DOTALL)
                result["seo"]["h1Tags"] = [h.strip() for h in h1_matches[:5]]

                # Count images without alt
                img_total = len(re.findall(r'<img', html))
                img_with_alt = len(re.findall(r'<img[^>]+alt=', html))
                result["seo"]["missingAltTexts"] = img_total - img_with_alt

                # Calculate SEO score
                seo_score = 50
                if result["seo"]["title"]:
                    seo_score += 20
                if result["seo"]["metaDescription"]:
                    seo_score += 15
                if result["seo"]["h1Tags"]:
                    seo_score += 10
                if result["seo"]["missingAltTexts"] == 0:
                    seo_score += 5
                result["seo"]["score"] = min(100, seo_score)

                # Accessibility (basic)
                result["accessibility"]["score"] = 70  # Default estimate

                logger.info("Fallback audit completed", url=url)

        except Exception as e:
            logger.error("Fallback audit failed", url=url, error=str(e))

        return result

    def _parse_results(self, raw: dict) -> dict:
        """Parse raw Lighthouse results into our schema."""
        categories = raw.get("categories", {})
        audits = raw.get("audits", {})

        return {
            "performance": {
                "score": int((categories.get("performance", {}).get("score", 0) or 0) * 100),
                "firstContentfulPaint": audits.get("first-contentful-paint", {}).get("numericValue", 0) / 1000,
                "largestContentfulPaint": audits.get("largest-contentful-paint", {}).get("numericValue", 0) / 1000,
                "totalBlockingTime": audits.get("total-blocking-time", {}).get("numericValue", 0),
                "cumulativeLayoutShift": audits.get("cumulative-layout-shift", {}).get("numericValue", 0),
                "speedIndex": audits.get("speed-index", {}).get("numericValue", 0) / 1000,
            },
            "seo": {
                "score": int((categories.get("seo", {}).get("score", 0) or 0) * 100),
                "title": audits.get("document-title", {}).get("details", {}).get("items", [{}])[0].get("text", ""),
                "metaDescription": audits.get("meta-description", {}).get("details", {}).get("items", [{}])[0].get("text", ""),
                "h1Tags": [],  # Lighthouse doesn't provide this directly
                "missingAltTexts": len(audits.get("image-alt", {}).get("details", {}).get("items", [])),
                "issues": self._extract_seo_issues(audits),
            },
            "accessibility": {
                "score": int((categories.get("accessibility", {}).get("score", 0) or 0) * 100),
                "issues": self._extract_accessibility_issues(audits),
            },
        }

    def _extract_seo_issues(self, audits: dict) -> list[dict]:
        """Extract SEO issues from Lighthouse audits."""
        issues = []
        seo_audits = [
            "document-title",
            "meta-description",
            "link-text",
            "crawlable-anchors",
            "is-crawlable",
            "robots-txt",
            "hreflang",
            "canonical",
        ]

        for audit_name in seo_audits:
            audit = audits.get(audit_name, {})
            if audit.get("score") == 0:
                issues.append({
                    "severity": "critical" if audit_name in ["document-title", "is-crawlable"] else "warning",
                    "message": audit.get("title", audit_name),
                })

        return issues

    def _extract_accessibility_issues(self, audits: dict) -> list[dict]:
        """Extract accessibility issues from Lighthouse audits."""
        issues = []
        a11y_audits = [
            "image-alt",
            "button-name",
            "link-name",
            "color-contrast",
            "heading-order",
            "html-has-lang",
            "label",
        ]

        for audit_name in a11y_audits:
            audit = audits.get(audit_name, {})
            if audit.get("score") == 0:
                items = audit.get("details", {}).get("items", [])
                for item in items[:5]:  # Limit to 5 issues per audit
                    issues.append({
                        "severity": "critical" if audit_name in ["image-alt", "color-contrast"] else "warning",
                        "element": item.get("selector", item.get("node", {}).get("selector", "")),
                        "message": audit.get("title", audit_name),
                    })

        return issues

    def _empty_audit(self) -> dict:
        """Return empty audit structure."""
        return {
            "performance": {
                "score": 0,
                "firstContentfulPaint": 0,
                "largestContentfulPaint": 0,
                "totalBlockingTime": 0,
                "cumulativeLayoutShift": 0,
                "speedIndex": 0,
            },
            "seo": {
                "score": 0,
                "title": "",
                "metaDescription": "",
                "h1Tags": [],
                "missingAltTexts": 0,
                "issues": [],
            },
            "accessibility": {
                "score": 0,
                "issues": [],
            },
        }


# Convenience function
async def run_lighthouse_audit(url: str) -> dict:
    """Run a Lighthouse audit on a URL."""
    service = LighthouseService()
    return await service.run_audit(url)
