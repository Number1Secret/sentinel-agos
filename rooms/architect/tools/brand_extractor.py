"""
Brand Extractor - Extract brand DNA from websites.

Extracts:
- Color palette (primary, secondary, accent colors)
- Typography (fonts, sizes, weights)
- Logo detection and extraction
- Brand voice analysis
- Visual style assessment
"""
import re
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import Counter

import structlog

logger = structlog.get_logger()


@dataclass
class ColorPalette:
    """Extracted color palette."""
    primary: Optional[str] = None  # Hex color
    secondary: Optional[str] = None
    accent: Optional[str] = None
    background: Optional[str] = None
    text: Optional[str] = None
    all_colors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "background": self.background,
            "text": self.text,
            "all_colors": self.all_colors[:10]  # Top 10
        }


@dataclass
class Typography:
    """Extracted typography information."""
    primary_font: Optional[str] = None
    secondary_font: Optional[str] = None
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    font_families: list[str] = field(default_factory=list)
    google_fonts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary_font": self.primary_font,
            "secondary_font": self.secondary_font,
            "heading_font": self.heading_font,
            "body_font": self.body_font,
            "font_families": self.font_families[:5],
            "google_fonts": self.google_fonts
        }


@dataclass
class BrandVoice:
    """Brand voice and tone analysis."""
    tone: str = "professional"  # professional, casual, playful, formal, etc.
    industry: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    tagline: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tone": self.tone,
            "industry": self.industry,
            "keywords": self.keywords[:10],
            "tagline": self.tagline,
            "description": self.description
        }


@dataclass
class BrandDNA:
    """Complete brand DNA extraction result."""
    url: str
    domain: str
    company_name: Optional[str] = None
    colors: Optional[ColorPalette] = None
    typography: Optional[Typography] = None
    voice: Optional[BrandVoice] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    social_links: list[str] = field(default_factory=list)
    extraction_confidence: float = 0.0  # 0-1

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "domain": self.domain,
            "company_name": self.company_name,
            "colors": self.colors.to_dict() if self.colors else None,
            "typography": self.typography.to_dict() if self.typography else None,
            "voice": self.voice.to_dict() if self.voice else None,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "social_links": self.social_links,
            "extraction_confidence": self.extraction_confidence
        }


class BrandExtractor:
    """
    Extracts brand DNA from website HTML and CSS.

    Uses pattern matching and heuristics to identify:
    - Color schemes from inline styles and CSS
    - Font families from stylesheets
    - Company name from title/meta tags
    - Logo from common selectors
    """

    def __init__(self):
        # Common color property names
        self.color_properties = [
            "color", "background-color", "background", "border-color",
            "fill", "stroke"
        ]

        # Font property patterns
        self.font_properties = ["font-family", "font"]

        # Social media patterns
        self.social_patterns = {
            "facebook": r"facebook\.com",
            "twitter": r"twitter\.com|x\.com",
            "instagram": r"instagram\.com",
            "linkedin": r"linkedin\.com",
            "youtube": r"youtube\.com"
        }

    async def extract_from_html(
        self,
        url: str,
        html: str,
        css: Optional[str] = None
    ) -> BrandDNA:
        """
        Extract brand DNA from HTML content.

        Args:
            url: Source URL
            html: HTML content
            css: Optional external CSS content

        Returns:
            BrandDNA with extracted information
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        domain = parsed.netloc

        # Extract components
        company_name = self._extract_company_name(html)
        colors = self._extract_colors(html, css)
        typography = self._extract_typography(html, css)
        voice = self._extract_voice(html)
        logo_url = self._extract_logo(html, url)
        favicon_url = self._extract_favicon(html, url)
        social_links = self._extract_social_links(html)

        # Calculate confidence based on what we found
        confidence = self._calculate_confidence(
            company_name, colors, typography, logo_url
        )

        logger.info(
            "Brand DNA extracted",
            url=url,
            company_name=company_name,
            colors_found=len(colors.all_colors) if colors else 0,
            confidence=confidence
        )

        return BrandDNA(
            url=url,
            domain=domain,
            company_name=company_name,
            colors=colors,
            typography=typography,
            voice=voice,
            logo_url=logo_url,
            favicon_url=favicon_url,
            social_links=social_links,
            extraction_confidence=confidence
        )

    def _extract_company_name(self, html: str) -> Optional[str]:
        """Extract company name from HTML."""
        # Try title tag
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            # Clean up common patterns
            title = re.sub(r"\s*[-|–]\s*.*$", "", title)  # Remove after dash
            title = re.sub(r"\s*\|\s*.*$", "", title)  # Remove after pipe
            if len(title) < 50:  # Reasonable length
                return title

        # Try og:site_name
        og_match = re.search(
            r'<meta\s+property=["\']og:site_name["\']\s+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if og_match:
            return og_match.group(1).strip()

        return None

    def _extract_colors(self, html: str, css: Optional[str] = None) -> ColorPalette:
        """Extract color palette from HTML and CSS."""
        colors = []

        # Combine HTML inline styles and CSS
        content = html + (css or "")

        # Find hex colors
        hex_colors = re.findall(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", content)
        for color in hex_colors:
            if len(color) == 3:
                color = "".join([c * 2 for c in color])
            colors.append(f"#{color.lower()}")

        # Find rgb/rgba colors
        rgb_matches = re.findall(
            r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
            content
        )
        for r, g, b in rgb_matches:
            hex_color = f"#{int(r):02x}{int(g):02x}{int(b):02x}"
            colors.append(hex_color)

        # Count occurrences and get most common
        color_counts = Counter(colors)
        top_colors = [c for c, _ in color_counts.most_common(20)]

        # Filter out pure black/white
        filtered = [c for c in top_colors if c not in ["#000000", "#ffffff", "#fff", "#000"]]

        # Assign to palette
        palette = ColorPalette(all_colors=filtered)

        if len(filtered) >= 1:
            palette.primary = filtered[0]
        if len(filtered) >= 2:
            palette.secondary = filtered[1]
        if len(filtered) >= 3:
            palette.accent = filtered[2]

        # Try to identify background/text colors
        if "#ffffff" in top_colors or "#fff" in top_colors:
            palette.background = "#ffffff"
        if "#000000" in top_colors or "#000" in top_colors:
            palette.text = "#000000"

        return palette

    def _extract_typography(self, html: str, css: Optional[str] = None) -> Typography:
        """Extract typography information."""
        content = html + (css or "")

        # Find font-family declarations
        font_matches = re.findall(
            r'font-family\s*:\s*([^;}"\']+)',
            content, re.IGNORECASE
        )

        all_fonts = []
        for match in font_matches:
            # Split by comma and clean
            fonts = [f.strip().strip("'\"") for f in match.split(",")]
            all_fonts.extend(fonts)

        # Count occurrences
        font_counts = Counter(all_fonts)

        # Filter out generic fonts
        generic = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "inherit", "initial"}
        specific_fonts = [f for f, _ in font_counts.most_common(10) if f.lower() not in generic]

        # Find Google Fonts
        google_fonts = re.findall(
            r"fonts\.googleapis\.com/css[^\"']*family=([^\"'&]+)",
            content
        )
        google_fonts = [f.replace("+", " ").split(":")[0] for f in google_fonts]

        typography = Typography(
            font_families=specific_fonts,
            google_fonts=google_fonts
        )

        if specific_fonts:
            typography.primary_font = specific_fonts[0]
        if len(specific_fonts) > 1:
            typography.secondary_font = specific_fonts[1]

        # Guess heading/body fonts from common patterns
        for font in specific_fonts:
            font_lower = font.lower()
            if any(word in font_lower for word in ["display", "heading", "title"]):
                typography.heading_font = font
            elif any(word in font_lower for word in ["text", "body", "paragraph"]):
                typography.body_font = font

        return typography

    def _extract_voice(self, html: str) -> BrandVoice:
        """Extract brand voice indicators."""
        voice = BrandVoice()

        # Extract meta description
        desc_match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if desc_match:
            voice.description = desc_match.group(1).strip()

        # Extract tagline from common locations
        tagline_patterns = [
            r'<(?:h1|h2)[^>]*class=["\'][^"\']*(?:tagline|slogan|hero)[^"\']*["\'][^>]*>([^<]+)',
            r'<(?:p|span)[^>]*class=["\'][^"\']*(?:tagline|slogan)[^"\']*["\'][^>]*>([^<]+)'
        ]
        for pattern in tagline_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                voice.tagline = match.group(1).strip()
                break

        # Extract keywords from meta
        keywords_match = re.search(
            r'<meta\s+name=["\']keywords["\']\s+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if keywords_match:
            voice.keywords = [k.strip() for k in keywords_match.group(1).split(",")][:10]

        # Analyze tone (simple heuristic)
        html_lower = html.lower()
        if any(word in html_lower for word in ["innovative", "cutting-edge", "revolutionary"]):
            voice.tone = "innovative"
        elif any(word in html_lower for word in ["trusted", "reliable", "established"]):
            voice.tone = "trustworthy"
        elif any(word in html_lower for word in ["fun", "exciting", "awesome"]):
            voice.tone = "playful"
        elif any(word in html_lower for word in ["luxury", "premium", "exclusive"]):
            voice.tone = "luxury"

        # Detect industry
        industry_keywords = {
            "technology": ["software", "tech", "digital", "app", "platform"],
            "healthcare": ["health", "medical", "doctor", "patient", "clinic"],
            "finance": ["bank", "financial", "invest", "money", "loan"],
            "ecommerce": ["shop", "store", "cart", "buy", "product"],
            "education": ["learn", "course", "student", "teach", "education"],
            "real_estate": ["property", "real estate", "home", "apartment", "rent"]
        }

        for industry, keywords in industry_keywords.items():
            if any(word in html_lower for word in keywords):
                voice.industry = industry
                break

        return voice

    def _extract_logo(self, html: str, base_url: str) -> Optional[str]:
        """Extract logo URL."""
        from urllib.parse import urljoin

        # Common logo patterns
        logo_patterns = [
            r'<img[^>]*class=["\'][^"\']*logo[^"\']*["\'][^>]*src=["\']([^"\']+)["\']',
            r'<img[^>]*src=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*logo',
            r'<a[^>]*class=["\'][^"\']*logo[^"\']*["\'][^>]*>.*?<img[^>]*src=["\']([^"\']+)["\']',
            r'<img[^>]*alt=["\'][^"\']*logo[^"\']*["\'][^>]*src=["\']([^"\']+)["\']',
            r'<img[^>]*id=["\'][^"\']*logo[^"\']*["\'][^>]*src=["\']([^"\']+)["\']'
        ]

        for pattern in logo_patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                logo_path = match.group(1)
                return urljoin(base_url, logo_path)

        return None

    def _extract_favicon(self, html: str, base_url: str) -> Optional[str]:
        """Extract favicon URL."""
        from urllib.parse import urljoin

        favicon_patterns = [
            r'<link[^>]*rel=["\'](?:shortcut )?icon["\'][^>]*href=["\']([^"\']+)["\']',
            r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\'](?:shortcut )?icon["\']'
        ]

        for pattern in favicon_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return urljoin(base_url, match.group(1))

        return None

    def _extract_social_links(self, html: str) -> list[str]:
        """Extract social media links."""
        social_links = []

        for platform, pattern in self.social_patterns.items():
            matches = re.findall(f'href=["\']([^"\']*{pattern}[^"\']*)["\']', html, re.IGNORECASE)
            for match in matches:
                if match not in social_links:
                    social_links.append(match)

        return social_links[:10]

    def _calculate_confidence(
        self,
        company_name: Optional[str],
        colors: Optional[ColorPalette],
        typography: Optional[Typography],
        logo_url: Optional[str]
    ) -> float:
        """Calculate extraction confidence score."""
        score = 0.0

        if company_name:
            score += 0.25
        if colors and len(colors.all_colors) >= 3:
            score += 0.25
        if typography and typography.primary_font:
            score += 0.25
        if logo_url:
            score += 0.25

        return score
