"""
Proposal Generator - HTML-to-PDF proposal creation.

Generates branded proposals incorporating:
- Company analysis from triage/architect
- Mockup preview image
- Pricing breakdown with adjustments
- Next steps / CTA with payment link

Uses WeasyPrint for HTML->PDF conversion.
"""
from datetime import datetime
from typing import Optional, Any
import io

import structlog

logger = structlog.get_logger()


class ProposalGenerator:
    """Generate PDF proposals from lead data + pricing."""

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    async def generate(
        self,
        lead_data: dict,
        pricing: dict,
        playbook_config: Optional[dict] = None,
    ) -> dict:
        """
        Generate a proposal PDF.

        Args:
            lead_data: Full lead data including triage/architect results
            pricing: PricingResult dict from pricing calculator
            playbook_config: Playbook with template config

        Returns:
            dict with public_url, storage_path, size_bytes
        """
        playbook_config = playbook_config or {}

        # 1. Build HTML from template
        html = self._render_proposal_html(lead_data, pricing, playbook_config)

        # 2. Convert to PDF via WeasyPrint
        pdf_bytes = self._html_to_pdf(html)

        # 3. Build storage path
        company = lead_data.get("company_name", "unknown").replace(" ", "_").lower()
        date_str = datetime.utcnow().strftime("%Y%m%d")
        filename = f"proposal_{company}_{date_str}.pdf"
        storage_path = f"proposals/{filename}"

        # 4. Store as generated asset if DB available
        if self.db:
            try:
                # Upload to Supabase Storage
                self.db.client.storage.from_("proposals").upload(
                    storage_path, pdf_bytes,
                    {"content-type": "application/pdf"}
                )
                public_url = self.db.client.storage.from_("proposals").get_public_url(
                    storage_path
                )
            except Exception as e:
                logger.warning("Failed to upload proposal to storage", error=str(e))
                public_url = f"/storage/proposals/{storage_path}"
        else:
            public_url = f"/storage/proposals/{storage_path}"

        result = {
            "success": True,
            "storage_path": storage_path,
            "public_url": public_url,
            "filename": filename,
            "size_bytes": len(pdf_bytes),
        }

        logger.info(
            "Proposal generated",
            company=company,
            size_bytes=len(pdf_bytes),
            storage_path=storage_path,
        )

        return result

    def _render_proposal_html(
        self, lead_data: dict, pricing: dict, playbook_config: dict
    ) -> str:
        """Render proposal HTML template with lead data and pricing."""
        company = lead_data.get("company_name", "Your Company")
        contact_name = lead_data.get("contact_name", "")
        mockup_url = lead_data.get("mockup_url", "")
        triage_score = lead_data.get("triage_score", 0)
        url = lead_data.get("url", "")

        # Extract brand colors if available
        brand = lead_data.get("brand_audit") or {}
        if isinstance(brand, dict):
            colors = brand.get("colors", {})
            if isinstance(colors, dict):
                primary_color = colors.get("primary", "#2563eb")
            elif isinstance(colors, list) and colors:
                primary_color = colors[0]
            else:
                primary_color = "#2563eb"
        else:
            primary_color = "#2563eb"

        # Build pricing table rows
        pricing_rows = ""
        for adj in pricing.get("adjustments", []):
            pricing_rows += f"""
            <tr>
                <td>{adj['name']}</td>
                <td class="amount">+${adj['amount']:,.0f}</td>
                <td class="detail">{adj['reason']}</td>
            </tr>"""

        # Build triage findings
        signals = lead_data.get("triage_signals") or {}
        findings = []
        if signals.get("pagespeed_score") is not None:
            score = signals["pagespeed_score"]
            findings.append(f"PageSpeed Score: {score}/100")
        if not signals.get("ssl_valid", True):
            findings.append("Missing SSL certificate")
        if not signals.get("mobile_responsive", True):
            findings.append("Not mobile responsive")
        if signals.get("copyright_year"):
            findings.append(f"Last updated: {signals['copyright_year']}")

        findings_html = "".join(f"<li>{f}</li>" for f in findings) if findings else "<li>Analysis complete</li>"

        # Mockup section
        mockup_section = ""
        if mockup_url and playbook_config.get("proposal", {}).get("include_mockup_preview", True):
            mockup_section = f"""
    <div class="section">
        <h2>Your New Design</h2>
        <p>We've created a custom mockup based on your brand identity:</p>
        <div class="mockup-frame">
            <img src="{mockup_url}" alt="Website Mockup Preview" />
        </div>
        <p class="caption">Live preview available — ask for the link.</p>
    </div>"""

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Helvetica Neue', Arial, sans-serif;
            color: #1e293b;
            line-height: 1.6;
            padding: 0;
        }}
        .header {{
            background: linear-gradient(135deg, {primary_color}, {primary_color}dd);
            color: white;
            padding: 50px 40px;
        }}
        .header h1 {{ font-size: 32px; font-weight: 700; margin-bottom: 8px; }}
        .header p {{ font-size: 16px; opacity: 0.9; }}
        .content {{ padding: 40px; }}
        .section {{ margin-bottom: 35px; }}
        .section h2 {{
            color: {primary_color};
            font-size: 22px;
            border-bottom: 2px solid {primary_color};
            padding-bottom: 8px;
            margin-bottom: 16px;
        }}
        .findings {{ list-style: none; padding: 0; }}
        .findings li {{
            padding: 8px 0 8px 24px;
            position: relative;
            border-bottom: 1px solid #f1f5f9;
        }}
        .findings li::before {{
            content: "\\2022";
            color: {primary_color};
            font-weight: bold;
            position: absolute;
            left: 0;
        }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #f8fafc; font-weight: 600; color: #475569; font-size: 13px; text-transform: uppercase; }}
        .amount {{ font-weight: 600; white-space: nowrap; }}
        .detail {{ color: #64748b; font-size: 14px; }}
        .total-row {{
            background: {primary_color}0d;
            font-size: 20px;
            font-weight: 700;
        }}
        .total-row td {{ color: {primary_color}; padding: 16px 12px; }}
        .mockup-frame {{
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            overflow: hidden;
            margin: 16px 0;
        }}
        .mockup-frame img {{ width: 100%; display: block; }}
        .caption {{ color: #94a3b8; font-size: 13px; font-style: italic; }}
        .cta {{
            background: {primary_color};
            color: white;
            padding: 30px;
            border-radius: 8px;
            text-align: center;
            margin-top: 40px;
        }}
        .cta h2 {{ font-size: 24px; margin-bottom: 10px; }}
        .cta p {{ font-size: 16px; opacity: 0.9; }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e2e8f0;
            color: #94a3b8;
            font-size: 12px;
        }}
        @page {{ margin: 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Website Redesign Proposal</h1>
        <p>Prepared for {company}{' — ' + contact_name if contact_name else ''}</p>
        <p>{datetime.utcnow().strftime('%B %d, %Y')}</p>
    </div>

    <div class="content">
        <div class="section">
            <h2>Current Site Analysis</h2>
            <p>Our automated analysis of <strong>{url}</strong> identified a
               triage opportunity score of <strong>{triage_score}/100</strong>,
               indicating significant room for improvement.</p>
            <ul class="findings">
                {findings_html}
            </ul>
        </div>

        {mockup_section}

        <div class="section">
            <h2>Investment Breakdown</h2>
            <table>
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Amount</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Base Project ({pricing.get('project_type', 'standard')})</td>
                        <td class="amount">${pricing.get('base_price', 0):,.0f}</td>
                        <td class="detail">Full website redesign</td>
                    </tr>
                    {pricing_rows}
                </tbody>
                <tfoot>
                    <tr class="total-row">
                        <td>Total Investment</td>
                        <td colspan="2">${pricing.get('final_price', 0):,.0f}</td>
                    </tr>
                </tfoot>
            </table>
        </div>

        <div class="cta">
            <h2>Ready to Transform Your Online Presence?</h2>
            <p>Reply to this email or click the payment link to secure your project slot.</p>
        </div>

        <div class="footer">
            <p>This proposal is valid for 30 days from the date above.</p>
            <p>Generated by Sentinel AgOS</p>
        </div>
    </div>
</body>
</html>"""

    def _html_to_pdf(self, html: str) -> bytes:
        """Convert HTML string to PDF bytes using WeasyPrint."""
        from weasyprint import HTML
        pdf_buffer = io.BytesIO()
        HTML(string=html).write_pdf(pdf_buffer)
        return pdf_buffer.getvalue()
