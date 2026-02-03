"""
Fast Scanner - Quick URL scanning for triage.

Uses lightweight HTTP requests for fast-pass scanning.
For full page rendering, we use Playwright via MCP.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
import structlog

from rooms.triage.tools.signal_detector import SignalDetector, TriageSignals

logger = structlog.get_logger()

# Default timeout for fast-pass scanning
DEFAULT_TIMEOUT = 15.0


@dataclass
class ScanResult:
    """Result of a fast URL scan."""
    url: str
    success: bool
    signals: Optional[TriageSignals] = None
    html: Optional[str] = None
    headers: Optional[dict] = None
    status_code: Optional[int] = None
    load_time_ms: Optional[int] = None
    error: Optional[str] = None
    redirected_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "success": self.success,
            "signals": self.signals.to_dict() if self.signals else None,
            "status_code": self.status_code,
            "load_time_ms": self.load_time_ms,
            "error": self.error,
            "redirected_url": self.redirected_url
        }


class FastScanner:
    """
    Fast URL scanner for triage.

    Performs lightweight HTTP scanning:
    - Follows redirects
    - Extracts HTML content
    - Detects signals from content
    - Measures load time

    For full JavaScript rendering, use Playwright MCP.
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = "Sentinel-Bot/1.0 (+https://sentinel.agency)"
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.signal_detector = SignalDetector()

    async def scan_url(self, url: str) -> ScanResult:
        """
        Perform fast scan of a single URL.

        Args:
            url: URL to scan

        Returns:
            ScanResult with signals if successful
        """
        # Normalize URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        start_time = time.time()

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=True
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": self.user_agent}
                )

                load_time_ms = int((time.time() - start_time) * 1000)

                # Get final URL after redirects
                final_url = str(response.url)
                redirected = final_url != url

                # Get HTML content
                html = response.text
                headers = dict(response.headers)

                # Extract signals
                signals = await self.signal_detector.detect_from_html(
                    url=final_url,
                    html=html,
                    headers=headers,
                    load_time_ms=load_time_ms
                )

                logger.info(
                    "URL scanned successfully",
                    url=url,
                    status_code=response.status_code,
                    load_time_ms=load_time_ms,
                    redirected=redirected
                )

                return ScanResult(
                    url=url,
                    success=True,
                    signals=signals,
                    html=html,
                    headers=headers,
                    status_code=response.status_code,
                    load_time_ms=load_time_ms,
                    redirected_url=final_url if redirected else None
                )

        except httpx.TimeoutException:
            load_time_ms = int((time.time() - start_time) * 1000)
            logger.warning("URL scan timeout", url=url, timeout=self.timeout)
            return ScanResult(
                url=url,
                success=False,
                load_time_ms=load_time_ms,
                error=f"Timeout after {self.timeout}s"
            )

        except httpx.ConnectError as e:
            logger.warning("URL scan connection error", url=url, error=str(e))
            return ScanResult(
                url=url,
                success=False,
                error=f"Connection failed: {str(e)}"
            )

        except Exception as e:
            logger.error("URL scan failed", url=url, error=str(e))
            return ScanResult(
                url=url,
                success=False,
                error=str(e)
            )

    async def scan_batch(
        self,
        urls: list[str],
        concurrency: int = 5
    ) -> list[ScanResult]:
        """
        Scan multiple URLs with concurrency control.

        Args:
            urls: List of URLs to scan
            concurrency: Max concurrent scans

        Returns:
            List of ScanResults
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def scan_with_semaphore(url: str) -> ScanResult:
            async with semaphore:
                return await self.scan_url(url)

        logger.info(
            "Starting batch scan",
            url_count=len(urls),
            concurrency=concurrency
        )

        results = await asyncio.gather(
            *[scan_with_semaphore(url) for url in urls],
            return_exceptions=True
        )

        # Convert exceptions to failed results
        final_results = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                final_results.append(ScanResult(
                    url=url,
                    success=False,
                    error=str(result)
                ))
            else:
                final_results.append(result)

        success_count = sum(1 for r in final_results if r.success)
        logger.info(
            "Batch scan completed",
            total=len(urls),
            success=success_count,
            failed=len(urls) - success_count
        )

        return final_results


async def quick_lighthouse_check(url: str) -> Optional[dict]:
    """
    Quick PageSpeed check using PageSpeed Insights API.

    This is a lightweight alternative to running full Lighthouse.
    Requires PAGESPEED_API_KEY environment variable.

    Args:
        url: URL to check

    Returns:
        Dict with score and metrics, or None if failed
    """
    import os

    api_key = os.getenv("PAGESPEED_API_KEY")
    if not api_key:
        logger.debug("No PageSpeed API key, skipping quick check")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params={
                    "url": url,
                    "key": api_key,
                    "strategy": "mobile",
                    "category": "performance"
                }
            )

            if response.status_code != 200:
                logger.warning(
                    "PageSpeed API error",
                    url=url,
                    status=response.status_code
                )
                return None

            data = response.json()

            # Extract score
            lighthouse = data.get("lighthouseResult", {})
            categories = lighthouse.get("categories", {})
            perf = categories.get("performance", {})

            score = int(perf.get("score", 0) * 100)

            return {
                "score": score,
                "fcp": lighthouse.get("audits", {}).get("first-contentful-paint", {}).get("numericValue"),
                "lcp": lighthouse.get("audits", {}).get("largest-contentful-paint", {}).get("numericValue"),
            }

    except Exception as e:
        logger.debug("PageSpeed check failed", url=url, error=str(e))
        return None
