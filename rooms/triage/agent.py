"""
TriageAgent - Fast-pass URL scanning and qualification.

This agent:
1. Scans URLs quickly to extract high-intent signals
2. Calculates a triage score based on playbook rules
3. Qualifies or disqualifies leads for the Architect room

Uses Playwright MCP for browser automation when needed.
"""
from datetime import datetime
from typing import Optional, Any
from uuid import UUID, uuid4

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext, load_agent_config
from rooms.triage.tools.fast_scan import FastScanner, ScanResult, quick_lighthouse_check
from rooms.triage.tools.signal_detector import (
    SignalDetector,
    TriageSignals,
    calculate_triage_score
)

logger = structlog.get_logger()


class TriageAgent(BaseAgent):
    """
    Triage Agent for fast-pass URL qualification.

    Workflow:
    1. Fast scan the URL (HTTP request)
    2. Extract signals (SSL, copyright, mobile, etc.)
    3. Optional: Get PageSpeed score via API
    4. Calculate triage score
    5. Return qualified/disqualified status

    For complex pages, can use Playwright MCP for full rendering.
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        scanner: Optional[FastScanner] = None,
    ):
        super().__init__(config, db_service)
        self.scanner = scanner or FastScanner()

        # Register tools
        self.register_tool(
            name="url_scan",
            func=self._tool_url_scan,
            schema={"url": {"type": "string"}}
        )
        self.register_tool(
            name="lighthouse_quick",
            func=self._tool_lighthouse_quick,
            schema={"url": {"type": "string"}}
        )

    async def run(self, context: AgentRunContext) -> dict:
        """
        Execute triage on a URL.

        Args:
            context: AgentRunContext with input_data containing:
                - url: URL to triage
                - playbook_config: Optional playbook configuration

        Returns:
            dict with:
                - qualified: bool
                - score: int (0-100)
                - signals: dict of detected signals
                - recommendation: str
        """
        url = context.input_data.get("url")
        playbook_config = context.input_data.get("playbook_config", {})

        if not url:
            raise ValueError("No URL provided in input_data")

        logger.info(
            "Starting triage",
            run_id=str(context.run_id),
            url=url
        )

        # Step 1: Fast scan the URL
        scan_result = await self.call_tool("url_scan", url=url)

        if not scan_result.success:
            # URL is unreachable - auto-disqualify
            return {
                "qualified": False,
                "score": 0,
                "signals": None,
                "error": scan_result.error,
                "recommendation": f"URL unreachable: {scan_result.error}"
            }

        signals = scan_result.signals

        # Step 2: Try to get PageSpeed score
        pagespeed = await self.call_tool("lighthouse_quick", url=url)
        if pagespeed:
            signals.pagespeed_score = pagespeed.get("score")

        # Step 3: Calculate triage score
        score = calculate_triage_score(signals, playbook_config)

        # Step 4: Determine qualification
        qualification_rules = playbook_config.get("qualification", {})
        min_score = qualification_rules.get("minimum_score", 60)
        auto_qualify = qualification_rules.get("auto_qualify_above", 80)
        auto_disqualify = qualification_rules.get("auto_disqualify_below", 30)

        if score >= auto_qualify:
            qualified = True
            recommendation = f"Auto-qualified with score {score}. High opportunity detected."
        elif score < auto_disqualify:
            qualified = False
            recommendation = f"Auto-disqualified with score {score}. Low opportunity."
        elif score >= min_score:
            qualified = True
            recommendation = f"Qualified with score {score}. Worth pursuing."
        else:
            qualified = False
            recommendation = f"Disqualified with score {score}. Below threshold of {min_score}."

        # Step 5: Optional - Use LLM to enhance recommendation
        if qualified and score >= 70:
            # For high-value leads, get AI-enhanced recommendation
            try:
                enhanced = await self._get_ai_recommendation(url, signals, score)
                if enhanced:
                    recommendation = enhanced
            except Exception as e:
                logger.warning("AI recommendation failed", error=str(e))

        result = {
            "qualified": qualified,
            "score": score,
            "signals": signals.to_dict(),
            "recommendation": recommendation,
            "scan_success": True,
            "load_time_ms": scan_result.load_time_ms
        }

        logger.info(
            "Triage completed",
            run_id=str(context.run_id),
            url=url,
            qualified=qualified,
            score=score
        )

        return result

    async def _tool_url_scan(self, url: str) -> ScanResult:
        """Tool wrapper for URL scanning."""
        return await self.scanner.scan_url(url)

    async def _tool_lighthouse_quick(self, url: str) -> Optional[dict]:
        """Tool wrapper for quick PageSpeed check."""
        return await quick_lighthouse_check(url)

    async def _get_ai_recommendation(
        self,
        url: str,
        signals: TriageSignals,
        score: int
    ) -> Optional[str]:
        """
        Get AI-enhanced recommendation for high-value leads.

        Uses the LLM to generate a more detailed recommendation.
        """
        messages = [
            {
                "role": "user",
                "content": f"""Analyze this website opportunity and provide a brief recommendation (2-3 sentences).

URL: {url}
Triage Score: {score}/100

Detected Issues:
- PageSpeed Score: {signals.pagespeed_score or 'Unknown'}
- SSL Valid: {signals.ssl_valid}
- Mobile Responsive: {signals.mobile_responsive}
- Copyright Year: {signals.copyright_year}
- CMS: {signals.cms_detected or 'Unknown'}

Based on these signals, explain why this is a good opportunity and what the main improvement areas are."""
            }
        ]

        response = await self.call_llm(messages, max_tokens=200)

        if response.content and len(response.content) > 0:
            return response.content[0].text

        return None


async def create_triage_agent(db_service) -> TriageAgent:
    """
    Factory function to create a TriageAgent with config from database.

    Args:
        db_service: Supabase service instance

    Returns:
        Configured TriageAgent
    """
    config = await load_agent_config(db_service, "triage")
    return TriageAgent(config=config, db_service=db_service)
