"""
VLM Analyzer - Vision-Language Model mockup interaction analysis.

Uses Claude Vision to analyze how prospects interact with Room 2 mockups:
1. Fetches tracking data and captured screenshots from discovery_interactions
2. Sends screenshots to Claude Vision API (via the agent's call_llm)
3. Returns structured engagement analysis for personalized follow-up

The tracking script (injected into E2B sandbox mockup URLs) captures:
- Page views / time on page
- Scroll depth
- Click heatmap coordinates
- Screenshots at key moments (page load, 30s, 60s, before exit)
"""
import base64
from typing import Optional, Any, Callable, Awaitable
from uuid import UUID

import structlog

logger = structlog.get_logger()

# Tracking script to inject into E2B mockup sandbox pages
TRACKING_SCRIPT = """
<script>
(function() {
    var leadId = document.querySelector('meta[name="lead-id"]')?.content || 'unknown';
    var apiBase = document.querySelector('meta[name="api-base"]')?.content || '';
    var startTime = Date.now();
    var maxScroll = 0;
    var clicks = [];

    // Track scroll depth
    window.addEventListener('scroll', function() {
        var scrollPct = Math.round(
            (window.scrollY + window.innerHeight) / document.body.scrollHeight * 100
        );
        if (scrollPct > maxScroll) maxScroll = scrollPct;
    });

    // Track clicks
    document.addEventListener('click', function(e) {
        clicks.push({
            x: e.clientX,
            y: e.clientY,
            target: e.target.tagName,
            timestamp: Date.now() - startTime
        });
    });

    // Send beacon on page unload
    window.addEventListener('beforeunload', function() {
        var data = {
            lead_id: leadId,
            time_on_page_ms: Date.now() - startTime,
            max_scroll_depth_pct: maxScroll,
            clicks: clicks,
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            }
        };
        if (apiBase) {
            navigator.sendBeacon(
                apiBase + '/api/tracking/mockup',
                JSON.stringify(data)
            );
        }
    });

    // Log page view immediately
    if (apiBase) {
        fetch(apiBase + '/api/tracking/mockup', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                lead_id: leadId,
                event: 'page_view',
                timestamp: new Date().toISOString()
            })
        }).catch(function() {});
    }
})();
</script>
"""


class VLMAnalyzer:
    """
    Analyze prospect engagement with mockups using Vision-Language Models.

    Requires an LLM call function (typically the agent's call_llm method)
    to send screenshots to Claude Vision for analysis.
    """

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    async def analyze_mockup_engagement(
        self,
        lead_id: UUID,
        call_llm: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> dict:
        """
        Analyze how a prospect interacted with their mockup.

        Args:
            lead_id: Lead UUID
            call_llm: Async function to call the LLM (agent's call_llm method)

        Returns:
            dict with engagement_score, interest_areas, drop_off_points,
            recommended_pitch_angle
        """
        # 1. Fetch mockup interaction data from discovery_interactions
        interactions = await self._get_mockup_interactions(lead_id)

        if not interactions:
            return {
                "engagement_score": 0,
                "has_data": False,
                "interest_areas": [],
                "drop_off_points": [],
                "recommended_pitch_angle": "general",
                "summary": "No mockup engagement data available.",
            }

        # 2. Aggregate interaction metrics
        metrics = self._aggregate_metrics(interactions)

        # 3. If we have screenshots and an LLM function, run vision analysis
        vision_analysis = {}
        screenshot_urls = self._extract_screenshot_urls(interactions)

        if screenshot_urls and call_llm:
            vision_analysis = await self._run_vision_analysis(
                screenshot_urls, metrics, call_llm
            )

        # 4. Combine metrics + vision analysis into engagement result
        engagement_score = self._calculate_engagement_score(metrics, vision_analysis)

        return {
            "engagement_score": engagement_score,
            "has_data": True,
            "metrics": metrics,
            "interest_areas": vision_analysis.get("interest_areas", []),
            "drop_off_points": vision_analysis.get("drop_off_points", []),
            "recommended_pitch_angle": vision_analysis.get(
                "recommended_pitch_angle", self._default_pitch_angle(metrics)
            ),
            "summary": vision_analysis.get("summary", self._metrics_summary(metrics)),
        }

    async def _get_mockup_interactions(self, lead_id: UUID) -> list[dict]:
        """Fetch mockup interaction events from database."""
        if not self.db:
            return []

        try:
            response = self.db.client.table("discovery_interactions").select(
                "*"
            ).eq("lead_id", str(lead_id)).in_(
                "interaction_type", ["mockup_interaction", "proposal_viewed"]
            ).order("created_at", desc=True).limit(50).execute()
            return response.data or []
        except Exception as e:
            logger.warning(
                "Failed to fetch mockup interactions",
                lead_id=str(lead_id),
                error=str(e),
            )
            return []

    def _aggregate_metrics(self, interactions: list[dict]) -> dict:
        """Aggregate raw interaction events into meaningful metrics."""
        total_views = 0
        total_time_ms = 0
        max_scroll_depth = 0
        all_clicks = []
        view_timestamps = []

        for interaction in interactions:
            data = interaction.get("response_data") or {}

            if interaction.get("interaction_type") == "proposal_viewed":
                total_views += 1
                view_timestamps.append(interaction.get("created_at"))

            if interaction.get("interaction_type") == "mockup_interaction":
                total_views += 1
                time_ms = data.get("time_on_page_ms", 0)
                total_time_ms += time_ms

                scroll = data.get("max_scroll_depth_pct", 0)
                if scroll > max_scroll_depth:
                    max_scroll_depth = scroll

                clicks = data.get("clicks", [])
                all_clicks.extend(clicks)

        return {
            "total_views": total_views,
            "total_time_seconds": round(total_time_ms / 1000, 1),
            "avg_time_seconds": round(
                total_time_ms / 1000 / max(total_views, 1), 1
            ),
            "max_scroll_depth_pct": max_scroll_depth,
            "total_clicks": len(all_clicks),
            "click_coordinates": all_clicks[:20],  # Cap at 20 for LLM context
            "view_timestamps": view_timestamps[:10],
        }

    def _extract_screenshot_urls(self, interactions: list[dict]) -> list[str]:
        """Extract screenshot URLs from interaction data."""
        urls = []
        for interaction in interactions:
            data = interaction.get("response_data") or {}
            screenshot_url = data.get("screenshot_url")
            if screenshot_url:
                urls.append(screenshot_url)
            # Also check for array of screenshots
            screenshots = data.get("screenshots", [])
            for s in screenshots:
                if isinstance(s, str):
                    urls.append(s)
                elif isinstance(s, dict) and s.get("url"):
                    urls.append(s["url"])
        return urls[:5]  # Cap at 5 screenshots for LLM context window

    async def _run_vision_analysis(
        self,
        screenshot_urls: list[str],
        metrics: dict,
        call_llm: Callable[..., Awaitable[Any]],
    ) -> dict:
        """Send screenshots to Claude Vision for engagement analysis."""
        # Build content blocks with images
        content_blocks = []

        for url in screenshot_urls:
            # If URL is a base64 data URI, use inline image
            if url.startswith("data:image"):
                media_type = url.split(";")[0].split(":")[1]
                data = url.split(",")[1]
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    },
                })
            else:
                # Use URL-based image reference
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": url,
                    },
                })

        # Add analysis prompt
        content_blocks.append({
            "type": "text",
            "text": f"""Analyze these mockup screenshots to understand prospect engagement.

Engagement Metrics:
- Total views: {metrics['total_views']}
- Average time on page: {metrics['avg_time_seconds']}s
- Max scroll depth: {metrics['max_scroll_depth_pct']}%
- Total clicks: {metrics['total_clicks']}
- Click locations: {metrics['click_coordinates'][:10]}

Based on the screenshots and metrics, provide:
1. Which sections of the mockup caught the most attention
2. Where the prospect appeared to hesitate or drop off
3. The best pitch angle for follow-up based on their interest patterns

Respond with EXACTLY one JSON object:
{{"interest_areas": ["section names or descriptions"],
  "drop_off_points": ["areas they skipped or left quickly"],
  "recommended_pitch_angle": "one-sentence recommendation for follow-up messaging",
  "summary": "2-3 sentence analysis of their engagement pattern"}}""",
        })

        try:
            messages = [{"role": "user", "content": content_blocks}]
            response = await call_llm(messages, max_tokens=500, temperature=0.2)

            # Parse the LLM response
            import json
            text = response.content[0].text
            return json.loads(text)

        except Exception as e:
            logger.warning("VLM analysis failed", error=str(e))
            return {}

    def _calculate_engagement_score(
        self, metrics: dict, vision_analysis: dict
    ) -> int:
        """Calculate 0-100 engagement score from metrics and vision analysis."""
        score = 0

        # Views (max 20 points)
        views = metrics.get("total_views", 0)
        score += min(views * 5, 20)

        # Time spent (max 30 points)
        avg_time = metrics.get("avg_time_seconds", 0)
        if avg_time >= 120:
            score += 30
        elif avg_time >= 60:
            score += 20
        elif avg_time >= 30:
            score += 10
        elif avg_time >= 10:
            score += 5

        # Scroll depth (max 20 points)
        scroll = metrics.get("max_scroll_depth_pct", 0)
        score += int(scroll * 0.2)

        # Clicks (max 15 points)
        clicks = metrics.get("total_clicks", 0)
        score += min(clicks * 3, 15)

        # Vision analysis bonus (max 15 points)
        if vision_analysis.get("interest_areas"):
            score += min(len(vision_analysis["interest_areas"]) * 5, 15)

        return min(score, 100)

    def _default_pitch_angle(self, metrics: dict) -> str:
        """Determine pitch angle from metrics alone (no VLM)."""
        scroll = metrics.get("max_scroll_depth_pct", 0)
        time_s = metrics.get("avg_time_seconds", 0)

        if scroll >= 80 and time_s >= 60:
            return "They reviewed thoroughly — focus on closing with a clear CTA"
        if scroll >= 50:
            return "Good engagement — highlight the value proposition they saw"
        if time_s >= 30:
            return "They spent time but didn't scroll far — lead with the hero section value"
        return "Low engagement — try a different approach or channel"

    def _metrics_summary(self, metrics: dict) -> str:
        """Generate a text summary from metrics."""
        views = metrics.get("total_views", 0)
        time_s = metrics.get("avg_time_seconds", 0)
        scroll = metrics.get("max_scroll_depth_pct", 0)
        clicks = metrics.get("total_clicks", 0)

        return (
            f"Prospect viewed the mockup {views} time(s), spending an average of "
            f"{time_s}s per visit. Scrolled to {scroll}% depth with {clicks} clicks."
        )

    @staticmethod
    def get_tracking_script(lead_id: str, api_base: str = "") -> str:
        """
        Get the tracking script to inject into mockup HTML.

        Args:
            lead_id: Lead UUID to associate tracking data with
            api_base: Base URL of the Sentinel API for beacon endpoints

        Returns:
            HTML script tag with tracking code
        """
        meta_tags = f"""
<meta name="lead-id" content="{lead_id}">
<meta name="api-base" content="{api_base}">
"""
        return meta_tags + TRACKING_SCRIPT
