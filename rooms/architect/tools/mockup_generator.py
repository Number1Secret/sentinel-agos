"""
Mockup Generator - Generate production-ready mockups via E2B sandbox.

Uses E2B (Code Interpreter) to:
- Generate Next.js/React code based on brand DNA
- Run the code in a sandboxed environment
- Provide a live preview URL
- Export the generated code
"""
import json
from dataclasses import dataclass, field
from typing import Optional, Any
from uuid import UUID

import structlog

from rooms.architect.tools.brand_extractor import BrandDNA
from rooms.architect.tools.deep_audit import AuditResult

logger = structlog.get_logger()


@dataclass
class MockupConfig:
    """Configuration for mockup generation."""
    template: str = "modern-professional"  # Template style
    framework: str = "nextjs"  # nextjs, react, html
    include_hero: bool = True
    include_features: bool = True
    include_testimonials: bool = False
    include_pricing: bool = False
    include_contact: bool = True
    include_footer: bool = True
    responsive: bool = True

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "framework": self.framework,
            "include_hero": self.include_hero,
            "include_features": self.include_features,
            "include_testimonials": self.include_testimonials,
            "include_pricing": self.include_pricing,
            "include_contact": self.include_contact,
            "include_footer": self.include_footer,
            "responsive": self.responsive
        }


@dataclass
class MockupResult:
    """Result of mockup generation."""
    success: bool
    preview_url: Optional[str] = None
    sandbox_id: Optional[str] = None
    code_files: dict[str, str] = field(default_factory=dict)  # filename -> content
    screenshot_base64: Optional[str] = None
    generation_time_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "preview_url": self.preview_url,
            "sandbox_id": self.sandbox_id,
            "code_files": list(self.code_files.keys()),
            "has_screenshot": self.screenshot_base64 is not None,
            "generation_time_ms": self.generation_time_ms,
            "error": self.error
        }


# Template definitions
TEMPLATES = {
    "modern-professional": {
        "description": "Clean, modern design with subtle animations",
        "colors": "primary-focused with neutral backgrounds",
        "layout": "single-page with smooth scroll sections"
    },
    "minimal-clean": {
        "description": "Minimalist design with lots of whitespace",
        "colors": "muted palette, focus on typography",
        "layout": "centered content, simple navigation"
    },
    "bold-startup": {
        "description": "Bold colors and large typography",
        "colors": "vibrant accent colors, dark mode friendly",
        "layout": "asymmetric layouts, animated elements"
    },
    "corporate-trust": {
        "description": "Professional, trustworthy appearance",
        "colors": "blues and grays, subtle gradients",
        "layout": "traditional grid, clear hierarchy"
    }
}


class MockupGenerator:
    """
    Generates website mockups based on brand DNA.

    Uses E2B sandbox for code execution and preview generation.
    Falls back to static code generation if E2B unavailable.
    """

    def __init__(
        self,
        e2b_service: Optional[Any] = None,
        anthropic_client: Optional[Any] = None
    ):
        self.e2b = e2b_service
        self.anthropic = anthropic_client

    async def generate(
        self,
        brand: BrandDNA,
        audit: Optional[AuditResult] = None,
        config: Optional[MockupConfig] = None,
        use_ai: bool = True
    ) -> MockupResult:
        """
        Generate a mockup based on brand DNA.

        Args:
            brand: Extracted brand DNA
            audit: Optional audit results for improvement hints
            config: Mockup configuration
            use_ai: Whether to use AI for code generation

        Returns:
            MockupResult with preview URL and code
        """
        import time
        start_time = time.time()

        config = config or MockupConfig()

        try:
            # Generate the code
            if use_ai and self.anthropic:
                code_files = await self._generate_with_ai(brand, audit, config)
            else:
                code_files = self._generate_from_template(brand, config)

            # Try to deploy to E2B sandbox
            preview_url = None
            sandbox_id = None
            screenshot = None

            if self.e2b:
                try:
                    sandbox_result = await self.e2b.create_sandbox(
                        template="nextjs" if config.framework == "nextjs" else "react",
                        files=code_files
                    )
                    preview_url = sandbox_result.get("preview_url")
                    sandbox_id = sandbox_result.get("sandbox_id")

                    # Capture screenshot
                    if preview_url:
                        screenshot = await self._capture_screenshot(preview_url)

                except Exception as e:
                    logger.warning("E2B sandbox creation failed", error=str(e))

            generation_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "Mockup generated",
                brand=brand.company_name,
                preview_url=preview_url,
                files_generated=len(code_files),
                generation_time_ms=generation_time_ms
            )

            return MockupResult(
                success=True,
                preview_url=preview_url,
                sandbox_id=sandbox_id,
                code_files=code_files,
                screenshot_base64=screenshot,
                generation_time_ms=generation_time_ms
            )

        except Exception as e:
            logger.error("Mockup generation failed", error=str(e))
            return MockupResult(
                success=False,
                error=str(e),
                generation_time_ms=int((time.time() - start_time) * 1000)
            )

    async def _generate_with_ai(
        self,
        brand: BrandDNA,
        audit: Optional[AuditResult],
        config: MockupConfig
    ) -> dict[str, str]:
        """Generate code using Claude."""
        # Build the prompt
        prompt = self._build_generation_prompt(brand, audit, config)

        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=8000,
            system="You are an expert frontend developer. Generate clean, production-ready code.",
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse code from response
        code_files = self._parse_code_response(response.content[0].text, config)

        return code_files

    def _build_generation_prompt(
        self,
        brand: BrandDNA,
        audit: Optional[AuditResult],
        config: MockupConfig
    ) -> str:
        """Build the code generation prompt."""
        colors = brand.colors.to_dict() if brand.colors else {}
        typography = brand.typography.to_dict() if brand.typography else {}

        sections = []
        if config.include_hero:
            sections.append("hero section with headline and CTA")
        if config.include_features:
            sections.append("features/benefits section")
        if config.include_testimonials:
            sections.append("testimonials section")
        if config.include_pricing:
            sections.append("pricing section")
        if config.include_contact:
            sections.append("contact form section")
        if config.include_footer:
            sections.append("footer with links")

        improvements = []
        if audit and audit.performance:
            if audit.performance.score < 50:
                improvements.append("optimize for fast loading")
            if audit.performance.largest_contentful_paint and audit.performance.largest_contentful_paint > 2500:
                improvements.append("improve LCP with optimized images")

        prompt = f"""Generate a {config.framework} website mockup for {brand.company_name or 'a company'}.

## Brand DNA
- Company: {brand.company_name or 'Unknown'}
- Primary Color: {colors.get('primary', '#3B82F6')}
- Secondary Color: {colors.get('secondary', '#1E40AF')}
- Accent Color: {colors.get('accent', '#F59E0B')}
- Primary Font: {typography.get('primary_font', 'Inter')}
- Brand Tone: {brand.voice.tone if brand.voice else 'professional'}

## Template Style
{TEMPLATES.get(config.template, TEMPLATES['modern-professional'])['description']}

## Required Sections
{chr(10).join(f'- {s}' for s in sections)}

## Technical Requirements
- Use Tailwind CSS for styling
- Make it fully responsive
- Include smooth scroll behavior
- Add subtle hover animations
- Use semantic HTML
{chr(10).join(f'- {i}' for i in improvements) if improvements else ''}

Generate the following files:
1. page.tsx (or index.tsx) - Main page component
2. globals.css - Global styles with Tailwind
3. tailwind.config.js - Tailwind configuration with brand colors

Return each file in this format:
```filename.ext
code here
```"""

        return prompt

    def _parse_code_response(self, response: str, config: MockupConfig) -> dict[str, str]:
        """Parse code blocks from AI response."""
        import re

        code_files = {}

        # Find all code blocks with filenames
        pattern = r"```(\S+)\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL)

        for filename, code in matches:
            # Clean up filename
            filename = filename.strip()
            if filename in ["tsx", "jsx", "js", "css"]:
                # Guess filename from extension
                if filename == "tsx":
                    filename = "page.tsx"
                elif filename == "css":
                    filename = "globals.css"
                elif filename == "js":
                    filename = "tailwind.config.js"

            code_files[filename] = code.strip()

        # Ensure we have at least a main file
        if not code_files:
            code_files = self._generate_from_template(
                BrandDNA(url="", domain=""),
                config
            )

        return code_files

    def _generate_from_template(
        self,
        brand: BrandDNA,
        config: MockupConfig
    ) -> dict[str, str]:
        """Generate code from static template."""
        colors = brand.colors if brand.colors else ColorPalette()
        typography = brand.typography if brand.typography else Typography()

        primary = colors.primary or "#3B82F6"
        secondary = colors.secondary or "#1E40AF"
        font = typography.primary_font or "Inter"
        company = brand.company_name or "Company Name"

        # Main page component
        page_tsx = f'''import React from 'react';

export default function HomePage() {{
  return (
    <div className="min-h-screen bg-white">
      {{/* Hero Section */}}
      <section className="relative py-20 px-4 bg-gradient-to-br from-primary to-secondary text-white">
        <div className="max-w-6xl mx-auto text-center">
          <h1 className="text-5xl md:text-6xl font-bold mb-6">
            {company}
          </h1>
          <p className="text-xl md:text-2xl mb-8 opacity-90">
            Transform your business with our innovative solutions
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button className="px-8 py-3 bg-white text-primary font-semibold rounded-lg hover:bg-opacity-90 transition">
              Get Started
            </button>
            <button className="px-8 py-3 border-2 border-white rounded-lg hover:bg-white hover:text-primary transition">
              Learn More
            </button>
          </div>
        </div>
      </section>

      {{/* Features Section */}}
      <section className="py-20 px-4">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl md:text-4xl font-bold text-center mb-12 text-gray-900">
            Why Choose Us
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            {{[
              {{ title: 'Fast & Reliable', desc: 'Lightning-fast performance you can count on' }},
              {{ title: 'Secure', desc: 'Enterprise-grade security for your peace of mind' }},
              {{ title: 'Scalable', desc: 'Grows with your business needs' }}
            ].map((feature, i) => (
              <div key={{i}} className="p-6 rounded-xl border border-gray-200 hover:shadow-lg transition">
                <h3 className="text-xl font-semibold mb-3 text-gray-900">{{feature.title}}</h3>
                <p className="text-gray-600">{{feature.desc}}</p>
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* Contact Section */}}
      <section className="py-20 px-4 bg-gray-50">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-6 text-gray-900">
            Get in Touch
          </h2>
          <p className="text-gray-600 mb-8">
            Ready to get started? Contact us today.
          </p>
          <form className="space-y-4">
            <input
              type="email"
              placeholder="Enter your email"
              className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-primary focus:border-transparent"
            />
            <button
              type="submit"
              className="w-full px-8 py-3 bg-primary text-white font-semibold rounded-lg hover:bg-opacity-90 transition"
            >
              Contact Us
            </button>
          </form>
        </div>
      </section>

      {{/* Footer */}}
      <footer className="py-8 px-4 bg-gray-900 text-gray-400">
        <div className="max-w-6xl mx-auto text-center">
          <p>&copy; {{new Date().getFullYear()}} {company}. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}}
'''

        # Global CSS
        globals_css = f'''@tailwind base;
@tailwind components;
@tailwind utilities;

@import url('https://fonts.googleapis.com/css2?family={font.replace(" ", "+")}:wght@400;500;600;700&display=swap');

:root {{
  --color-primary: {primary};
  --color-secondary: {secondary};
}}

body {{
  font-family: '{font}', system-ui, sans-serif;
}}

html {{
  scroll-behavior: smooth;
}}
'''

        # Tailwind config
        tailwind_config = f'''/** @type {{import('tailwindcss').Config}} */
module.exports = {{
  content: [
    './pages/**/*.{{js,ts,jsx,tsx,mdx}}',
    './components/**/*.{{js,ts,jsx,tsx,mdx}}',
    './app/**/*.{{js,ts,jsx,tsx,mdx}}',
  ],
  theme: {{
    extend: {{
      colors: {{
        primary: '{primary}',
        secondary: '{secondary}',
      }},
      fontFamily: {{
        sans: ['{font}', 'system-ui', 'sans-serif'],
      }},
    }},
  }},
  plugins: [],
}}
'''

        return {
            "page.tsx": page_tsx,
            "globals.css": globals_css,
            "tailwind.config.js": tailwind_config
        }

    async def _capture_screenshot(self, url: str) -> Optional[str]:
        """Capture screenshot of preview URL."""
        try:
            from mcp_servers.playwright_mcp import PlaywrightMCPClient

            async with PlaywrightMCPClient().session() as client:
                result = await client.screenshot(url, full_page=False)
                if result.get("success"):
                    return result.get("image_base64")
        except Exception as e:
            logger.warning("Screenshot capture failed", error=str(e))

        return None


# Need to import these for the fallback template
from rooms.architect.tools.brand_extractor import ColorPalette, Typography
