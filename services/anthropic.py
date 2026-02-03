"""
Anthropic Claude client service for AI analysis.
"""
from functools import lru_cache
from typing import Optional
import json

from anthropic import Anthropic
import structlog

from config import settings

logger = structlog.get_logger()

# Pricing per million tokens (as of late 2024)
PRICING = {
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 1.0, "output": 5.0},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
}


@lru_cache
def get_anthropic_client() -> Anthropic:
    """Get Anthropic client instance."""
    return Anthropic(api_key=settings.anthropic_api_key)


class AnthropicService:
    """Service for Claude AI operations."""

    def __init__(self, client: Optional[Anthropic] = None):
        self.client = client or get_anthropic_client()
        self.default_model = "claude-3-5-sonnet-20241022"

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for token usage."""
        pricing = PRICING.get(model, PRICING[self.default_model])
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 6)

    async def analyze_website(
        self,
        url: str,
        lighthouse_data: dict,
        screenshot_base64: Optional[str] = None,
        brand_data: Optional[dict] = None,
        custom_prompt: Optional[str] = None,
    ) -> tuple[dict, int, float]:
        """
        Analyze website using Claude.

        Returns:
            Tuple of (analysis_dict, tokens_used, cost_usd)
        """
        system_prompt = """You are an expert website analyst and digital marketing consultant.
Your task is to analyze websites and provide actionable recommendations for improvement.

You have access to:
1. Lighthouse performance and SEO audit data
2. Screenshots of the website (if provided)
3. Extracted brand elements (if provided)

Provide analysis in the following JSON structure:
{
    "summary": "Executive summary of findings (2-3 sentences)",
    "strengths": ["List of 3-5 key strengths"],
    "weaknesses": ["List of 3-5 key weaknesses"],
    "recommendations": [
        {
            "category": "performance|seo|ux|content|technical|brand",
            "priority": "critical|high|medium|low",
            "issue": "Description of the issue",
            "recommendation": "Specific action to take",
            "estimatedImpact": "Expected improvement"
        }
    ]
}

Be specific, actionable, and prioritize recommendations by impact."""

        # Build user message content
        content = []

        # Add screenshot if available
        if screenshot_base64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_base64,
                },
            })

        # Build text content
        text_parts = [f"Analyze the website: {url}\n"]

        if lighthouse_data:
            text_parts.append(f"\n## Lighthouse Audit Results\n```json\n{json.dumps(lighthouse_data, indent=2)}\n```")

        if brand_data:
            text_parts.append(f"\n## Extracted Brand Elements\n```json\n{json.dumps(brand_data, indent=2)}\n```")

        if custom_prompt:
            text_parts.append(f"\n## Additional Analysis Instructions\n{custom_prompt}")

        text_parts.append("\n\nProvide your analysis as JSON only, no additional text.")

        content.append({"type": "text", "text": "\n".join(text_parts)})

        try:
            response = self.client.messages.create(
                model=self.default_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )

            # Parse response
            response_text = response.content[0].text

            # Extract JSON from response
            try:
                # Try to parse directly
                analysis = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code block
                import re
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
                if json_match:
                    analysis = json.loads(json_match.group(1))
                else:
                    # Return raw text as summary
                    analysis = {
                        "summary": response_text[:500],
                        "strengths": [],
                        "weaknesses": [],
                        "recommendations": [],
                    }

            # Calculate metrics
            tokens_used = response.usage.input_tokens + response.usage.output_tokens
            cost_usd = self.calculate_cost(
                self.default_model,
                response.usage.input_tokens,
                response.usage.output_tokens
            )

            logger.info(
                "Website analysis completed",
                url=url,
                tokens_used=tokens_used,
                cost_usd=cost_usd,
            )

            return analysis, tokens_used, cost_usd

        except Exception as e:
            logger.error("Failed to analyze website", url=url, error=str(e))
            raise

    async def compare_competitors(
        self,
        main_url: str,
        main_analysis: dict,
        competitor_analyses: list[dict],
    ) -> tuple[list[dict], int, float]:
        """
        Compare main website against competitors.

        Returns:
            Tuple of (comparison_list, tokens_used, cost_usd)
        """
        system_prompt = """You are an expert competitive analyst.
Compare the main website against its competitors and provide insights.

Return JSON array with competitor comparisons:
[
    {
        "url": "competitor URL",
        "strengths": ["What they do better than the main site"],
        "weaknesses": ["What the main site does better"]
    }
]"""

        user_content = f"""Main website: {main_url}
Main analysis: {json.dumps(main_analysis, indent=2)}

Competitor analyses:
{json.dumps(competitor_analyses, indent=2)}

Provide competitor comparison as JSON array only."""

        try:
            response = self.client.messages.create(
                model=self.default_model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )

            response_text = response.content[0].text

            try:
                comparison = json.loads(response_text)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
                if json_match:
                    comparison = json.loads(json_match.group(1))
                else:
                    comparison = []

            tokens_used = response.usage.input_tokens + response.usage.output_tokens
            cost_usd = self.calculate_cost(
                self.default_model,
                response.usage.input_tokens,
                response.usage.output_tokens
            )

            return comparison, tokens_used, cost_usd

        except Exception as e:
            logger.error("Failed to compare competitors", error=str(e))
            raise
