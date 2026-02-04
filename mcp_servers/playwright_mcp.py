"""
Playwright MCP Server Configuration and Client.

Provides browser automation capabilities for Sentinel agents:
- URL navigation and page loading
- Screenshot capture (full page and viewport)
- DOM extraction and text content
- JavaScript evaluation
- Page metadata extraction

Used by:
- Triage Room: Fast URL scanning with lightweight settings
- Architect Room: Deep analysis with full-quality settings
"""
import asyncio
import base64
from dataclasses import dataclass, field
from typing import Optional, Any
from contextlib import asynccontextmanager

import structlog

logger = structlog.get_logger()


@dataclass
class PlaywrightMCPConfig:
    """Configuration for Playwright MCP server."""
    name: str = "playwright"
    transport: str = "stdio"
    command: str = "npx"
    args: list[str] = field(default_factory=lambda: ["@anthropic-ai/mcp-server-playwright"])
    timeout_ms: int = 30000
    viewport_width: int = 1920
    viewport_height: int = 1080
    wait_until: str = "networkidle"  # 'load', 'domcontentloaded', 'networkidle'
    headless: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "timeout_ms": self.timeout_ms,
            "viewport": {
                "width": self.viewport_width,
                "height": self.viewport_height
            },
            "wait_until": self.wait_until,
            "headless": self.headless
        }


# Pre-configured settings for different rooms
TRIAGE_PLAYWRIGHT_CONFIG = PlaywrightMCPConfig(
    name="playwright-triage",
    timeout_ms=15000,
    viewport_width=1280,
    viewport_height=720,
    wait_until="domcontentloaded"  # Faster than networkidle
)

ARCHITECT_PLAYWRIGHT_CONFIG = PlaywrightMCPConfig(
    name="playwright-architect",
    timeout_ms=60000,
    viewport_width=1920,
    viewport_height=1080,
    wait_until="networkidle"  # Full page load for accurate screenshots
)


class PlaywrightMCPClient:
    """
    Client for interacting with Playwright MCP server.

    Provides high-level methods for common browser operations.
    Falls back to direct Playwright when MCP is unavailable.
    """

    def __init__(self, config: Optional[PlaywrightMCPConfig] = None):
        self.config = config or PlaywrightMCPConfig()
        self._browser = None
        self._playwright = None
        self._context = None

    async def _ensure_browser(self):
        """Ensure browser is launched."""
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=self.config.headless
                )
                self._context = await self._browser.new_context(
                    viewport={
                        "width": self.config.viewport_width,
                        "height": self.config.viewport_height
                    }
                )
                logger.info("Browser launched", config=self.config.name)
            except Exception as e:
                logger.error("Failed to launch browser", error=str(e))
                raise

    async def close(self):
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._context = None
        logger.info("Browser closed")

    @asynccontextmanager
    async def session(self):
        """Context manager for browser session."""
        await self._ensure_browser()
        try:
            yield self
        finally:
            await self.close()

    async def navigate(
        self,
        url: str,
        wait_until: Optional[str] = None,
        timeout_ms: Optional[int] = None
    ) -> dict:
        """
        Navigate to a URL.

        Args:
            url: URL to navigate to
            wait_until: Override wait condition
            timeout_ms: Override timeout

        Returns:
            Dict with status, final_url, title
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            response = await page.goto(
                url,
                wait_until=wait_until or self.config.wait_until,
                timeout=timeout_ms or self.config.timeout_ms
            )

            return {
                "success": True,
                "status_code": response.status if response else None,
                "final_url": page.url,
                "title": await page.title(),
            }
        except Exception as e:
            logger.warning("Navigation failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "final_url": None,
                "title": None
            }
        finally:
            await page.close()

    async def screenshot(
        self,
        url: str,
        full_page: bool = True,
        wait_until: Optional[str] = None,
        timeout_ms: Optional[int] = None
    ) -> dict:
        """
        Capture screenshot of a URL.

        Args:
            url: URL to screenshot
            full_page: Capture full scrollable page
            wait_until: Override wait condition
            timeout_ms: Override timeout

        Returns:
            Dict with success, image_base64, dimensions
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(
                url,
                wait_until=wait_until or self.config.wait_until,
                timeout=timeout_ms or self.config.timeout_ms
            )

            # Wait a bit for any animations
            await asyncio.sleep(0.5)

            screenshot_bytes = await page.screenshot(
                full_page=full_page,
                type="png"
            )

            return {
                "success": True,
                "image_base64": base64.b64encode(screenshot_bytes).decode(),
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
                "full_page": full_page
            }
        except Exception as e:
            logger.warning("Screenshot failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "image_base64": None
            }
        finally:
            await page.close()

    async def extract_text(
        self,
        url: str,
        selector: Optional[str] = None
    ) -> dict:
        """
        Extract text content from a page.

        Args:
            url: URL to extract from
            selector: Optional CSS selector (defaults to body)

        Returns:
            Dict with success, text content
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(
                url,
                wait_until=self.config.wait_until,
                timeout=self.config.timeout_ms
            )

            if selector:
                element = await page.query_selector(selector)
                text = await element.inner_text() if element else ""
            else:
                text = await page.inner_text("body")

            return {
                "success": True,
                "text": text,
                "selector": selector or "body"
            }
        except Exception as e:
            logger.warning("Text extraction failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "text": None
            }
        finally:
            await page.close()

    async def extract_links(self, url: str) -> dict:
        """
        Extract all links from a page.

        Args:
            url: URL to extract links from

        Returns:
            Dict with success, list of links
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(
                url,
                wait_until=self.config.wait_until,
                timeout=self.config.timeout_ms
            )

            links = await page.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(e => ({ href: e.href, text: e.innerText.trim() }))"
            )

            return {
                "success": True,
                "links": links,
                "count": len(links)
            }
        except Exception as e:
            logger.warning("Link extraction failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "links": []
            }
        finally:
            await page.close()

    async def evaluate_js(
        self,
        url: str,
        script: str
    ) -> dict:
        """
        Execute JavaScript in page context.

        Args:
            url: URL to run script on
            script: JavaScript code to execute

        Returns:
            Dict with success, result
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(
                url,
                wait_until=self.config.wait_until,
                timeout=self.config.timeout_ms
            )

            result = await page.evaluate(script)

            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.warning("JS evaluation failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "result": None
            }
        finally:
            await page.close()

    async def get_page_info(self, url: str) -> dict:
        """
        Get comprehensive page metadata.

        Args:
            url: URL to analyze

        Returns:
            Dict with title, meta tags, headers, performance metrics
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            response = await page.goto(
                url,
                wait_until=self.config.wait_until,
                timeout=self.config.timeout_ms
            )

            # Extract metadata
            info = await page.evaluate("""
                () => {
                    const getMeta = (name) => {
                        const el = document.querySelector(`meta[name="${name}"], meta[property="${name}"]`);
                        return el ? el.content : null;
                    };

                    return {
                        title: document.title,
                        description: getMeta('description'),
                        keywords: getMeta('keywords'),
                        ogTitle: getMeta('og:title'),
                        ogDescription: getMeta('og:description'),
                        ogImage: getMeta('og:image'),
                        viewport: getMeta('viewport'),
                        canonical: document.querySelector('link[rel="canonical"]')?.href,
                        lang: document.documentElement.lang,
                        charset: document.characterSet,
                        scripts: document.scripts.length,
                        stylesheets: document.styleSheets.length,
                        images: document.images.length,
                        links: document.links.length
                    };
                }
            """)

            # Get response headers
            headers = response.headers if response else {}

            return {
                "success": True,
                "url": page.url,
                "status_code": response.status if response else None,
                "headers": dict(headers),
                **info
            }
        except Exception as e:
            logger.warning("Page info extraction failed", url=url, error=str(e))
            return {
                "success": False,
                "error": str(e),
                "url": url
            }
        finally:
            await page.close()


# Convenience function to create client for a room
def create_playwright_client(room: str = "triage") -> PlaywrightMCPClient:
    """
    Create a Playwright client configured for a specific room.

    Args:
        room: 'triage' or 'architect'

    Returns:
        Configured PlaywrightMCPClient
    """
    if room == "architect":
        return PlaywrightMCPClient(ARCHITECT_PLAYWRIGHT_CONFIG)
    return PlaywrightMCPClient(TRIAGE_PLAYWRIGHT_CONFIG)
