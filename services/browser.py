"""
Browser automation service using Playwright.
Captures screenshots and extracts brand elements from websites.
"""
import asyncio
import base64
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
import structlog

logger = structlog.get_logger()


class BrowserService:
    """Service for browser automation and website analysis."""

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Start browser instance."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            logger.info("Browser started")

    async def stop(self):
        """Stop browser instance."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            logger.info("Browser stopped")

    async def capture_screenshots(
        self,
        url: str,
        include_mobile: bool = True,
        timeout_ms: int = 30000,
    ) -> dict[str, str]:
        """
        Capture screenshots of a webpage.

        Returns:
            Dict with 'desktop' and optionally 'mobile' base64-encoded screenshots.
        """
        if not self._browser:
            await self.start()

        screenshots = {}

        # Desktop screenshot
        try:
            page = await self._browser.new_page(
                viewport={"width": 1920, "height": 1080}
            )
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            await asyncio.sleep(1)  # Wait for any animations

            desktop_bytes = await page.screenshot(full_page=True, type="png")
            screenshots["desktop"] = base64.b64encode(desktop_bytes).decode("utf-8")
            await page.close()
            logger.info("Desktop screenshot captured", url=url)
        except PlaywrightTimeout:
            logger.warning("Desktop screenshot timed out", url=url)
        except Exception as e:
            logger.error("Failed to capture desktop screenshot", url=url, error=str(e))

        # Mobile screenshot
        if include_mobile:
            try:
                page = await self._browser.new_page(
                    viewport={"width": 390, "height": 844},  # iPhone 14 Pro
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
                )
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                await asyncio.sleep(1)

                mobile_bytes = await page.screenshot(full_page=True, type="png")
                screenshots["mobile"] = base64.b64encode(mobile_bytes).decode("utf-8")
                await page.close()
                logger.info("Mobile screenshot captured", url=url)
            except PlaywrightTimeout:
                logger.warning("Mobile screenshot timed out", url=url)
            except Exception as e:
                logger.error("Failed to capture mobile screenshot", url=url, error=str(e))

        return screenshots

    async def extract_brand_elements(
        self,
        url: str,
        timeout_ms: int = 30000,
    ) -> dict:
        """
        Extract brand elements from a webpage.

        Returns:
            Dict with colors, fonts, logo URL, and CTAs.
        """
        if not self._browser:
            await self.start()

        brand = {
            "primaryColors": [],
            "secondaryColors": [],
            "fonts": {"headings": None, "body": None},
            "logoUrl": None,
            "ctas": [],
        }

        try:
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            # Extract colors from CSS
            colors = await page.evaluate("""() => {
                const colors = new Set();
                const elements = document.querySelectorAll('*');

                elements.forEach(el => {
                    const style = window.getComputedStyle(el);
                    const bgColor = style.backgroundColor;
                    const textColor = style.color;

                    if (bgColor && bgColor !== 'rgba(0, 0, 0, 0)' && bgColor !== 'transparent') {
                        colors.add(bgColor);
                    }
                    if (textColor) {
                        colors.add(textColor);
                    }
                });

                return Array.from(colors).slice(0, 20);
            }""")

            # Convert RGB to hex and filter
            hex_colors = []
            for color in colors:
                hex_color = self._rgb_to_hex(color)
                if hex_color and hex_color not in ["#000000", "#ffffff", "#FFFFFF"]:
                    hex_colors.append(hex_color)

            if hex_colors:
                brand["primaryColors"] = hex_colors[:5]
                brand["secondaryColors"] = hex_colors[5:10]

            # Extract fonts
            fonts = await page.evaluate("""() => {
                const headingEl = document.querySelector('h1, h2, h3');
                const bodyEl = document.querySelector('p, span, div');

                return {
                    headings: headingEl ? window.getComputedStyle(headingEl).fontFamily.split(',')[0].replace(/['"]/g, '').trim() : null,
                    body: bodyEl ? window.getComputedStyle(bodyEl).fontFamily.split(',')[0].replace(/['"]/g, '').trim() : null
                };
            }""")
            brand["fonts"] = fonts

            # Extract logo
            logo_url = await page.evaluate("""() => {
                // Common logo selectors
                const selectors = [
                    'img[alt*="logo" i]',
                    'img[class*="logo" i]',
                    'img[id*="logo" i]',
                    '.logo img',
                    '#logo img',
                    'header img:first-of-type',
                    'a[href="/"] img',
                ];

                for (const selector of selectors) {
                    const img = document.querySelector(selector);
                    if (img && img.src) {
                        return img.src;
                    }
                }
                return null;
            }""")

            if logo_url:
                brand["logoUrl"] = urljoin(url, logo_url)

            # Extract CTAs
            ctas = await page.evaluate("""() => {
                const ctas = [];
                const buttons = document.querySelectorAll('a.btn, a.button, button, a[class*="cta" i], [role="button"]');

                buttons.forEach((btn, index) => {
                    const text = btn.innerText?.trim();
                    if (text && text.length < 50) {
                        let href = btn.href || btn.closest('a')?.href || '#';
                        ctas.push({
                            text: text,
                            href: href,
                            prominence: index < 2 ? 'primary' : index < 5 ? 'secondary' : 'tertiary'
                        });
                    }
                });

                return ctas.slice(0, 10);
            }""")
            brand["ctas"] = ctas

            await page.close()
            logger.info("Brand elements extracted", url=url)

        except Exception as e:
            logger.error("Failed to extract brand elements", url=url, error=str(e))

        return brand

    def _rgb_to_hex(self, rgb_string: str) -> Optional[str]:
        """Convert RGB/RGBA string to hex color."""
        try:
            # Match rgb(r, g, b) or rgba(r, g, b, a)
            match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', rgb_string)
            if match:
                r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
                return f"#{r:02x}{g:02x}{b:02x}".upper()
            return None
        except Exception:
            return None


# Convenience function for one-off usage
async def analyze_website_visuals(url: str, include_mobile: bool = True) -> dict:
    """Capture screenshots and extract brand elements for a URL."""
    async with BrowserService() as browser:
        screenshots = await browser.capture_screenshots(url, include_mobile)
        brand = await browser.extract_brand_elements(url)

        return {
            "screenshots": screenshots,
            "brand": brand,
        }
