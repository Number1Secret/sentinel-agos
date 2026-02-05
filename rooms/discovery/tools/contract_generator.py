"""
Contract Generator - PDF contract creation.

Generates legally structured contracts incorporating:
- Agency and client details
- Scope of work from architect output
- Pricing from negotiation
- Payment terms from playbook
- Standard terms and conditions
- Signature blocks

Uses WeasyPrint for HTML->PDF conversion.
"""
from datetime import datetime
from typing import Optional, Any
import io

import structlog

logger = structlog.get_logger()


class ContractGenerator:
    """Generate PDF contracts from lead data + deal terms."""

    def __init__(self, db_service: Optional[Any] = None):
        self.db = db_service

    async def generate(
        self,
        lead_data: dict,
        deal_value: float,
        playbook_config: Optional[dict] = None,
    ) -> dict:
        """
        Generate a contract PDF.

        Args:
            lead_data: Full lead data including company info
            deal_value: Final negotiated deal value
            playbook_config: Playbook with contract template config

        Returns:
            dict with public_url, storage_path, size_bytes
        """
        playbook_config = playbook_config or {}
        contract_config = playbook_config.get("contract", {})

        # 1. Build HTML from legal template
        html = self._render_contract_html(lead_data, deal_value, contract_config)

        # 2. Convert to PDF
        pdf_bytes = self._html_to_pdf(html)

        # 3. Build storage path
        company = lead_data.get("company_name", "unknown").replace(" ", "_").lower()
        date_str = datetime.utcnow().strftime("%Y%m%d")
        filename = f"contract_{company}_{date_str}.pdf"
        storage_path = f"contracts/{filename}"

        # 4. Upload to storage
        if self.db:
            try:
                self.db.client.storage.from_("contracts").upload(
                    storage_path, pdf_bytes,
                    {"content-type": "application/pdf"}
                )
                public_url = self.db.client.storage.from_("contracts").get_public_url(
                    storage_path
                )
            except Exception as e:
                logger.warning("Failed to upload contract to storage", error=str(e))
                public_url = f"/storage/contracts/{storage_path}"
        else:
            public_url = f"/storage/contracts/{storage_path}"

        result = {
            "success": True,
            "storage_path": storage_path,
            "public_url": public_url,
            "filename": filename,
            "size_bytes": len(pdf_bytes),
        }

        logger.info(
            "Contract generated",
            company=company,
            deal_value=deal_value,
            size_bytes=len(pdf_bytes),
        )

        return result

    def _render_contract_html(
        self, lead_data: dict, deal_value: float, contract_config: dict
    ) -> str:
        """Render contract HTML template."""
        company = lead_data.get("company_name", "Client Company")
        contact_name = lead_data.get("contact_name", "Authorized Representative")
        contact_email = lead_data.get("contact_email", "")
        url = lead_data.get("url", "")

        payment_terms = contract_config.get("payment_terms", "100% upon completion")
        delivery_timeline = contract_config.get("delivery_timeline", "4-6 weeks")
        revision_rounds = contract_config.get("revision_rounds", 3)

        date_str = datetime.utcnow().strftime("%B %d, %Y")

        # Calculate payment split if applicable
        if "50%" in payment_terms:
            upfront = deal_value / 2
            completion = deal_value / 2
            payment_schedule = f"""
            <tr><td>Upon signing</td><td>${upfront:,.2f}</td><td>50% deposit</td></tr>
            <tr><td>Upon delivery</td><td>${completion:,.2f}</td><td>Final payment</td></tr>
            """
        else:
            payment_schedule = f"""
            <tr><td>Upon completion</td><td>${deal_value:,.2f}</td><td>Full payment</td></tr>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: 'Georgia', 'Times New Roman', serif;
            color: #1e293b;
            line-height: 1.7;
            padding: 50px;
            font-size: 14px;
        }}
        h1 {{
            text-align: center;
            font-size: 24px;
            color: #0f172a;
            margin-bottom: 5px;
        }}
        .subtitle {{
            text-align: center;
            color: #64748b;
            margin-bottom: 30px;
        }}
        h2 {{
            font-size: 16px;
            color: #0f172a;
            margin-top: 25px;
            margin-bottom: 10px;
        }}
        .parties {{
            background: #f8fafc;
            padding: 20px;
            border-radius: 4px;
            margin: 20px 0;
        }}
        .parties strong {{ color: #0f172a; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border: 1px solid #e2e8f0;
        }}
        th {{
            background: #f1f5f9;
            font-weight: 600;
        }}
        .total {{
            font-weight: 700;
            font-size: 16px;
        }}
        .signature-block {{
            display: flex;
            justify-content: space-between;
            margin-top: 60px;
        }}
        .signature {{
            width: 45%;
        }}
        .signature .line {{
            border-top: 1px solid #0f172a;
            margin-top: 60px;
            padding-top: 8px;
        }}
        .signature .label {{
            color: #64748b;
            font-size: 12px;
        }}
        ol {{ padding-left: 20px; }}
        ol li {{ margin-bottom: 8px; }}
        .footer {{
            margin-top: 40px;
            padding-top: 15px;
            border-top: 1px solid #e2e8f0;
            color: #94a3b8;
            font-size: 11px;
            text-align: center;
        }}
        @page {{ margin: 40px; }}
    </style>
</head>
<body>
    <h1>Web Services Agreement</h1>
    <p class="subtitle">Effective Date: {date_str}</p>

    <div class="parties">
        <p><strong>Service Provider ("Agency"):</strong> [Agency Name]</p>
        <p><strong>Client:</strong> {company}</p>
        <p><strong>Contact:</strong> {contact_name} ({contact_email})</p>
        <p><strong>Project URL:</strong> {url}</p>
    </div>

    <h2>1. Scope of Work</h2>
    <p>The Agency agrees to provide the following services for the Client's website ({url}):</p>
    <ol>
        <li>Complete website redesign and development</li>
        <li>Mobile-responsive implementation</li>
        <li>Performance optimization (targeting PageSpeed score of 85+)</li>
        <li>SSL certificate setup and configuration</li>
        <li>Content migration from existing site</li>
        <li>Up to {revision_rounds} rounds of design revisions</li>
        <li>Quality assurance testing across browsers and devices</li>
        <li>Deployment to production environment</li>
    </ol>

    <h2>2. Project Timeline</h2>
    <p>The estimated delivery timeline is <strong>{delivery_timeline}</strong> from the
       date of this agreement and receipt of initial deposit.</p>

    <h2>3. Investment & Payment Schedule</h2>
    <table>
        <thead>
            <tr><th>Milestone</th><th>Amount</th><th>Description</th></tr>
        </thead>
        <tbody>
            {payment_schedule}
        </tbody>
        <tfoot>
            <tr class="total">
                <td>Total</td>
                <td colspan="2">${deal_value:,.2f} USD</td>
            </tr>
        </tfoot>
    </table>

    <h2>4. Revisions</h2>
    <p>This agreement includes {revision_rounds} rounds of revisions. Additional revision
       rounds will be billed at an agreed-upon hourly rate.</p>

    <h2>5. Ownership & Intellectual Property</h2>
    <p>Upon full payment, the Client receives full ownership of all deliverables including
       source code, design assets, and content created specifically for this project.</p>

    <h2>6. Termination</h2>
    <p>Either party may terminate this agreement with 14 days written notice. In the event
       of termination, the Client is responsible for payment of all work completed up to
       the date of termination.</p>

    <h2>7. Limitation of Liability</h2>
    <p>The Agency's total liability under this agreement shall not exceed the total
       project value of ${deal_value:,.2f}.</p>

    <div style="display: flex; justify-content: space-between; margin-top: 60px;">
        <div style="width: 45%;">
            <div style="border-top: 1px solid #0f172a; margin-top: 60px; padding-top: 8px;">
                <p><strong>Agency Representative</strong></p>
                <p style="color: #64748b; font-size: 12px;">Signature / Date</p>
            </div>
        </div>
        <div style="width: 45%;">
            <div style="border-top: 1px solid #0f172a; margin-top: 60px; padding-top: 8px;">
                <p><strong>{contact_name}</strong></p>
                <p style="color: #64748b; font-size: 12px;">Client Signature / Date</p>
            </div>
        </div>
    </div>

    <div class="footer">
        <p>This agreement is governed by the laws of the state in which the Agency operates.</p>
        <p>Generated by Sentinel AgOS on {date_str}</p>
    </div>
</body>
</html>"""

    def _html_to_pdf(self, html: str) -> bytes:
        """Convert HTML string to PDF bytes using WeasyPrint."""
        from weasyprint import HTML
        pdf_buffer = io.BytesIO()
        HTML(string=html).write_pdf(pdf_buffer)
        return pdf_buffer.getvalue()
