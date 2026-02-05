"""
Dynamic Pricing Calculator.

Calculates deal_value based on:
- Triage signals (opportunity indicators)
- Brand audit findings (project complexity)
- Industry vertical (from playbook pricing_rules)
- Playbook margins (min/max/discount rules)

Returns: base_price, adjustments, final_price, min_acceptable, close_probability
"""
from typing import Optional

import structlog

logger = structlog.get_logger()


class PricingCalculator:
    """
    Utility-based pricing engine.

    Uses playbook pricing_rules matrix to calculate dynamic deal pricing.
    The agent can apply discounts within margin_rules constraints but
    NEVER below min_acceptable_price — this is a hard floor.
    """

    def calculate(
        self,
        triage_score: Optional[float] = None,
        triage_signals: Optional[dict] = None,
        brand_audit: Optional[dict] = None,
        industry: Optional[str] = None,
        playbook_rules: Optional[dict] = None,
    ) -> dict:
        """
        Calculate dynamic price from playbook rules and lead signals.

        Args:
            triage_score: 0-100 qualification score from Room 1
            triage_signals: Signal dict from triage (pagespeed, ssl, mobile, etc.)
            brand_audit: Brand analysis from Room 2
            industry: Industry vertical string
            playbook_rules: pricing_rules section from playbook config

        Returns:
            dict with base_price, adjustments, final_price,
            min_acceptable_price, max_discount_pct, close_probability
        """
        rules = playbook_rules or {}
        signals = triage_signals or {}

        # 1. Determine base price from project type classification
        base_prices = rules.get("base_prices", {"default": 5000})
        project_type = self._classify_project(signals, brand_audit)
        base = float(base_prices.get(project_type, base_prices.get("default", 5000)))
        original_base = base

        adjustments = []

        # 2. Apply signal multipliers
        signal_multipliers = rules.get("signal_multipliers", {})

        pagespeed = signals.get("pagespeed_score") or signals.get("pagespeed")
        if pagespeed is not None:
            if pagespeed < 30:
                mult = signal_multipliers.get("pagespeed_below_30", 1.2)
                adjustment = base * (mult - 1)
                adjustments.append({
                    "name": "Low PageSpeed Premium",
                    "amount": round(adjustment, 2),
                    "reason": f"PageSpeed {pagespeed}/100 — significant rebuild needed"
                })
                base *= mult
            elif pagespeed < 50:
                mult = signal_multipliers.get("pagespeed_below_50", 1.1)
                adjustment = base * (mult - 1)
                adjustments.append({
                    "name": "PageSpeed Optimization",
                    "amount": round(adjustment, 2),
                    "reason": f"PageSpeed {pagespeed}/100 — optimization required"
                })
                base *= mult

        if not signals.get("ssl_valid", True):
            mult = signal_multipliers.get("no_ssl", 1.1)
            adjustment = base * (mult - 1)
            adjustments.append({
                "name": "SSL Setup",
                "amount": round(adjustment, 2),
                "reason": "No valid SSL certificate detected"
            })
            base *= mult

        if not signals.get("mobile_responsive", True):
            mult = signal_multipliers.get("no_mobile", 1.15)
            adjustment = base * (mult - 1)
            adjustments.append({
                "name": "Mobile Responsive Rebuild",
                "amount": round(adjustment, 2),
                "reason": "Site not mobile responsive"
            })
            base *= mult

        # Check copyright year for outdated sites
        copyright_year = signals.get("copyright_year")
        if copyright_year:
            from datetime import datetime
            years_old = datetime.utcnow().year - copyright_year
            if years_old >= 5:
                mult = signal_multipliers.get("outdated_5plus_years", 1.2)
                adjustment = base * (mult - 1)
                adjustments.append({
                    "name": "Legacy Site Modernization",
                    "amount": round(adjustment, 2),
                    "reason": f"Site {years_old} years outdated"
                })
                base *= mult
            elif years_old >= 3:
                mult = signal_multipliers.get("outdated_3plus_years", 1.1)
                adjustment = base * (mult - 1)
                adjustments.append({
                    "name": "Site Refresh Premium",
                    "amount": round(adjustment, 2),
                    "reason": f"Site {years_old} years outdated"
                })
                base *= mult

        # 3. Industry multiplier
        industry_multipliers = rules.get("industry_multipliers", {})
        industry_key = (industry or "default").lower()
        industry_mult = industry_multipliers.get(
            industry_key,
            industry_multipliers.get("default", 1.0)
        )
        if industry_mult != 1.0:
            adjustment = base * (industry_mult - 1)
            adjustments.append({
                "name": f"Industry Adjustment ({industry_key})",
                "amount": round(adjustment, 2),
                "reason": f"Industry multiplier: {industry_mult}x"
            })
            base *= industry_mult

        # 4. Calculate margin boundaries
        margin_rules = rules.get("margin_rules", {})
        max_discount_pct = float(margin_rules.get("max_discount_pct", 15))

        final_price = round(base, -1)  # Round to nearest $10
        min_acceptable = round(final_price * (1 - max_discount_pct / 100), 2)

        # 5. Estimate close probability based on triage score
        close_prob = 0.3
        if triage_score is not None:
            score = float(triage_score)
            if score >= 80:
                close_prob = 0.5
            elif score >= 60:
                close_prob = 0.35
            elif score >= 40:
                close_prob = 0.25
            else:
                close_prob = 0.15

        result = {
            "base_price": original_base,
            "project_type": project_type,
            "adjustments": adjustments,
            "final_price": final_price,
            "min_acceptable_price": min_acceptable,
            "max_discount_pct": max_discount_pct,
            "close_probability": close_prob,
        }

        logger.info(
            "Price calculated",
            project_type=project_type,
            base=original_base,
            final=final_price,
            min_acceptable=min_acceptable,
            close_probability=close_prob,
            adjustments_count=len(adjustments),
        )

        return result

    def _classify_project(
        self, signals: dict, brand_audit: Optional[dict]
    ) -> str:
        """Classify project type from triage signals and brand audit."""
        # Check CMS detection from signals
        cms = ""
        if signals.get("cms_detected"):
            cms = str(signals["cms_detected"]).lower()

        if any(kw in cms for kw in ("shopify", "woocommerce", "magento", "bigcommerce")):
            return "ecommerce"
        if "wordpress" in cms:
            return "small_business"

        # Check for SaaS indicators
        if brand_audit and isinstance(brand_audit, dict):
            voice = (brand_audit.get("voice") or "").lower()
            if any(kw in voice for kw in ("saas", "platform", "software")):
                return "saas"

        # Check for single-page indicators
        page_count = signals.get("page_count")
        if page_count and int(page_count) <= 3:
            return "landing_page"

        return "small_business"
