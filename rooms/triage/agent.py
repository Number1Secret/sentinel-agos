"""
TriageAgent - Fast-pass URL scanning and qualification.

This agent:
1. Scans URLs quickly to extract high-intent signals
2. Calculates a triage score based on playbook rules
3. Qualifies or disqualifies leads for the Architect room
4. Supports dynamic tool loading from playbook configuration

Uses Playwright MCP for browser automation when needed.

The "Infinite SDR" refactoring enables:
- Dynamic tool loading based on playbook.required_tools
- Modular logic gates via ConditionEvaluator
- Automatic enrichment for high-value leads
"""
from datetime import datetime
from typing import Optional, Any, List
from uuid import UUID, uuid4

import structlog

from agents.base import BaseAgent, AgentConfig, AgentRunContext, load_agent_config
from rooms.triage.tools.fast_scan import FastScanner, ScanResult, quick_lighthouse_check
from rooms.triage.tools.signal_detector import (
    SignalDetector,
    TriageSignals,
    calculate_triage_score
)
from rooms.triage.tools.condition_evaluator import (
    ConditionEvaluator,
    calculate_score_from_signals
)
from rooms.triage.tools.registry import get_tool, list_available_tools, validate_tools_available

logger = structlog.get_logger()


class TriageAgent(BaseAgent):
    """
    Triage Agent for fast-pass URL qualification.

    Workflow:
    1. Fast scan the URL (HTTP request)
    2. Extract signals (SSL, copyright, mobile, etc.)
    3. Optional: Get PageSpeed score via API
    4. Run playbook-specified tools (ad pixel detection, Shopify scanner, etc.)
    5. Calculate triage score using ConditionEvaluator or legacy scoring
    6. Return qualified/disqualified status

    For complex pages, can use Playwright MCP for full rendering.

    Supports dynamic tool loading from playbook.required_tools for the
    "Infinite SDR" customization capability.
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        scanner: Optional[FastScanner] = None,
    ):
        super().__init__(config, db_service)
        self.scanner = scanner or FastScanner()
        self._playbook_tools: List[str] = []  # Dynamically loaded tools
        self._condition_evaluator: Optional[ConditionEvaluator] = None

        # Register CORE tools (always available)
        self._register_core_tools()

    def _register_core_tools(self):
        """Register tools that are always available regardless of playbook."""
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

    async def load_playbook_tools(self, playbook_config: dict) -> List[str]:
        """
        Dynamically load tools specified in playbook configuration.

        Args:
            playbook_config: Playbook config with optional required_tools list

        Returns:
            List of successfully loaded tool names
        """
        required_tools = playbook_config.get("required_tools", [])
        if not required_tools:
            return []

        # Validate which tools are available
        available, missing = validate_tools_available(required_tools)

        if missing:
            logger.warning(
                "Some playbook tools not available",
                missing=missing,
                available=available
            )

        loaded = []
        for tool_name in available:
            if tool_name not in self._tools:
                try:
                    tool_def = get_tool(tool_name)
                    self.register_tool(
                        name=tool_name,
                        func=tool_def.func,
                        schema=tool_def.schema
                    )
                    loaded.append(tool_name)
                    logger.debug("Loaded playbook tool", tool=tool_name)
                except ValueError as e:
                    logger.warning("Failed to load tool", tool=tool_name, error=str(e))

        self._playbook_tools = loaded
        return loaded

    def _setup_condition_evaluator(self, playbook_config: dict):
        """Set up the condition evaluator from playbook logic gates."""
        logic_gates = playbook_config.get("logic_gates", {})
        if logic_gates:
            self._condition_evaluator = ConditionEvaluator(logic_gates)
        else:
            self._condition_evaluator = None

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
                - logic_gate_results: dict of evaluated gates (if using v2.0 playbook)
        """
        url = context.input_data.get("url")
        playbook_config = context.input_data.get("playbook_config", {})

        if not url:
            raise ValueError("No URL provided in input_data")

        # Check playbook version for v2.0 features
        playbook_version = playbook_config.get("version", "1.0")
        is_v2 = playbook_version.startswith("2")

        logger.info(
            "Starting triage",
            run_id=str(context.run_id),
            url=url,
            playbook_version=playbook_version
        )

        # Step 1: Load dynamic tools from playbook (v2.0 feature)
        if is_v2:
            loaded_tools = await self.load_playbook_tools(playbook_config)
            self._setup_condition_evaluator(playbook_config)
            logger.debug("Loaded playbook tools", tools=loaded_tools)

        # Step 2: Fast scan the URL
        scan_result = await self.call_tool("url_scan", url=url)

        if not scan_result.success:
            # URL is unreachable - auto-disqualify
            return {
                "qualified": False,
                "score": 0,
                "signals": None,
                "error": scan_result.error,
                "recommendation": f"URL unreachable: {scan_result.error}",
                "scan_success": False
            }

        signals = scan_result.signals
        signals_dict = signals.to_dict()

        # Step 3: Try to get PageSpeed score
        pagespeed = await self.call_tool("lighthouse_quick", url=url)
        if pagespeed:
            signals.pagespeed_score = pagespeed.get("score")
            signals_dict["pagespeed_score"] = pagespeed.get("score")

        # Step 4: Run additional playbook tools (v2.0 feature)
        additional_signals = {}
        if is_v2 and self._playbook_tools:
            additional_signals = await self._run_playbook_tools(url, signals_dict)
            signals_dict.update(additional_signals)

        # Step 5: Calculate triage score
        scoring_config = playbook_config.get("scoring", {})
        thresholds_config = playbook_config.get("signals", {})

        if is_v2 and scoring_config:
            # Use new scoring function that supports ad_pixel_weight etc.
            score = calculate_score_from_signals(signals_dict, scoring_config, thresholds_config)
        else:
            # Legacy scoring
            score = calculate_triage_score(signals, playbook_config)

        # Step 6: Determine qualification using logic gates (v2.0) or legacy rules
        logic_gate_results = {}

        if is_v2 and self._condition_evaluator:
            # Build evaluation data
            eval_data = {
                "triage_score": score,
                "signals": signals_dict,
                "scan_success": True,
                **additional_signals
            }

            # Evaluate qualification gate
            qualification_result = self._condition_evaluator.evaluate_gate("qualification", eval_data)
            logic_gate_results["qualification"] = qualification_result.to_dict()
            qualified = qualification_result.passed

            # Check for gold_lead gate (for auto-enrichment trigger)
            if "gold_lead" in self._condition_evaluator.logic_gates:
                gold_result = self._condition_evaluator.evaluate_gate("gold_lead", eval_data)
                logic_gate_results["gold_lead"] = gold_result.to_dict()

            recommendation = self._generate_recommendation_v2(
                qualified, score, logic_gate_results, signals_dict
            )
        else:
            # Legacy qualification
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

        # Step 7: Optional - Use LLM to enhance recommendation for high-value leads
        if qualified and score >= 70:
            try:
                enhanced = await self._get_ai_recommendation(url, signals, score)
                if enhanced:
                    recommendation = enhanced
            except Exception as e:
                logger.warning("AI recommendation failed", error=str(e))

        result = {
            "qualified": qualified,
            "score": score,
            "signals": signals_dict,
            "recommendation": recommendation,
            "scan_success": True,
            "load_time_ms": scan_result.load_time_ms,
            "playbook_version": playbook_version
        }

        # Add v2.0 specific data
        if is_v2:
            result["logic_gate_results"] = logic_gate_results
            result["playbook_tools_used"] = self._playbook_tools
            if additional_signals:
                result["additional_signals"] = additional_signals

        logger.info(
            "Triage completed",
            run_id=str(context.run_id),
            url=url,
            qualified=qualified,
            score=score,
            playbook_version=playbook_version
        )

        return result

    async def _run_playbook_tools(self, url: str, signals: dict) -> dict:
        """
        Run additional tools specified in the playbook.

        Args:
            url: URL being processed
            signals: Current signals dict

        Returns:
            Dict of additional signals from tools
        """
        additional = {}

        for tool_name in self._playbook_tools:
            try:
                if tool_name == "ad_pixel_sensor":
                    result = await self.call_tool("ad_pixel_sensor", url=url)
                    additional["ad_pixels"] = result
                    additional["has_meta_pixel"] = result.get("has_meta_pixel", False)
                    additional["has_google_ads"] = result.get("has_google_ads", False)
                    additional["ad_spend_indicator"] = result.get("ad_spend_indicator", "none")

                elif tool_name == "shopify_scanner":
                    result = await self.call_tool("shopify_scanner", url=url)
                    additional["shopify"] = result
                    if result.get("is_shopify"):
                        signals["cms_detected"] = "shopify"
                        additional["shopify_opportunity_score"] = result.get("opportunity_score", 0)

                # Add more tool handlers as needed

            except Exception as e:
                logger.warning(
                    "Playbook tool failed",
                    tool=tool_name,
                    url=url,
                    error=str(e)
                )

        return additional

    def _generate_recommendation_v2(
        self,
        qualified: bool,
        score: int,
        logic_gate_results: dict,
        signals: dict
    ) -> str:
        """Generate recommendation based on v2.0 logic gate results."""
        if qualified:
            # Check if it's a gold lead
            gold_result = logic_gate_results.get("gold_lead", {})
            if gold_result.get("passed"):
                return f"Gold lead! Score {score}. High-value opportunity with strong signals. Auto-enrichment triggered."
            return f"Qualified with score {score}. Meets all qualification criteria."
        else:
            # Find which conditions failed
            qual_result = logic_gate_results.get("qualification", {})
            failed_conditions = []
            for cr in qual_result.get("condition_results", []):
                if not cr.get("passed"):
                    failed_conditions.append(f"{cr.get('field')} {cr.get('operator')} {cr.get('expected')}")

            if failed_conditions:
                return f"Disqualified with score {score}. Failed conditions: {', '.join(failed_conditions[:3])}"
            return f"Disqualified with score {score}. Did not meet qualification criteria."

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
