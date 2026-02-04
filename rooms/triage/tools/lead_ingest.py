"""
LeadIngestNode - Imports leads from CSV files or external APIs.

Supports:
- CSV file content (direct upload)
- API endpoint fetching (with custom field mapping)
- Airtable integration

Enables agencies to bring their own lead lists into the SDR engine.
"""
import csv
import io
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import httpx
import structlog

from rooms.triage.tools.registry import register_tool, ToolCategory

logger = structlog.get_logger()


# Default field mappings (source field -> lead field)
DEFAULT_FIELD_MAPPING = {
    "url": ["url", "website", "site_url", "domain", "web", "site", "homepage"],
    "company_name": ["company", "business_name", "company_name", "name", "business", "organization"],
    "contact_email": ["email", "contact_email", "owner_email", "primary_email", "e-mail"],
    "contact_name": ["contact", "contact_name", "owner_name", "owner", "full_name", "person"],
    "industry": ["industry", "category", "business_type", "vertical", "sector"],
    "phone": ["phone", "telephone", "phone_number", "tel", "mobile"],
    "address": ["address", "location", "street_address", "full_address"],
    "city": ["city", "town"],
    "state": ["state", "province", "region"],
    "country": ["country", "nation"],
    "notes": ["notes", "description", "comments", "remarks"],
}


@dataclass
class IngestResult:
    """Results of lead ingestion."""
    success: bool = False
    leads_imported: int = 0
    leads_skipped: int = 0
    leads_duplicates: int = 0
    leads_invalid: int = 0
    errors: List[str] = field(default_factory=list)
    sample_leads: List[dict] = field(default_factory=list)  # First 3 for preview

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "leads_imported": self.leads_imported,
            "leads_skipped": self.leads_skipped,
            "leads_duplicates": self.leads_duplicates,
            "leads_invalid": self.leads_invalid,
            "total_processed": self.leads_imported + self.leads_skipped,
            "errors": self.errors[:10],  # Limit errors in output
            "sample_leads": self.sample_leads
        }


def normalize_url(url: str) -> Optional[str]:
    """
    Normalize a URL to consistent format.

    Args:
        url: Raw URL string

    Returns:
        Normalized URL or None if invalid
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()

    # Skip empty or obviously invalid
    if not url or url.lower() in ('n/a', 'na', 'none', '-', ''):
        return None

    # Add https if no protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)
        # Must have a domain
        if not parsed.netloc or '.' not in parsed.netloc:
            return None
        # Rebuild clean URL
        clean_url = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.path and parsed.path != '/':
            clean_url += parsed.path.rstrip('/')
        return clean_url
    except Exception:
        return None


def extract_domain(url: str) -> Optional[str]:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return None


def map_row_to_lead(row: dict, field_mapping: dict) -> dict:
    """
    Map a source row to lead fields using field mapping.

    Args:
        row: Source data row
        field_mapping: Mapping of lead_field -> [source_field_options]

    Returns:
        Mapped lead dict
    """
    lead = {}
    row_lower = {k.lower().strip(): v for k, v in row.items()}

    for lead_field, source_options in field_mapping.items():
        for source_field in source_options:
            source_key = source_field.lower().strip()
            if source_key in row_lower and row_lower[source_key]:
                value = row_lower[source_key]
                if isinstance(value, str):
                    value = value.strip()
                if value:
                    lead[lead_field] = value
                    break

    return lead


async def process_csv_content(
    content: str,
    field_mapping: Optional[dict] = None,
    skip_duplicates: bool = True
) -> IngestResult:
    """
    Process CSV content and extract leads.

    Args:
        content: CSV file content as string
        field_mapping: Custom field mapping (merged with defaults)
        skip_duplicates: Whether to skip duplicate domains

    Returns:
        IngestResult with processed leads
    """
    result = IngestResult()

    # Merge custom mapping with defaults
    mapping = {**DEFAULT_FIELD_MAPPING}
    if field_mapping:
        for key, value in field_mapping.items():
            if key in mapping:
                # Prepend custom mappings
                mapping[key] = value + mapping[key]
            else:
                mapping[key] = value

    seen_domains = set()
    leads = []

    try:
        # Try to detect delimiter
        sample = content[:2000]
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample)
        except csv.Error:
            dialect = csv.excel  # Default

        reader = csv.DictReader(io.StringIO(content), dialect=dialect)

        for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 is header)
            try:
                lead = map_row_to_lead(row, mapping)

                # URL is required
                url = lead.get("url")
                if not url:
                    result.leads_invalid += 1
                    if len(result.errors) < 10:
                        result.errors.append(f"Row {row_num}: Missing URL")
                    continue

                # Normalize URL
                normalized_url = normalize_url(url)
                if not normalized_url:
                    result.leads_invalid += 1
                    if len(result.errors) < 10:
                        result.errors.append(f"Row {row_num}: Invalid URL '{url}'")
                    continue

                lead["url"] = normalized_url
                lead["domain"] = extract_domain(normalized_url)

                # Check for duplicates
                if skip_duplicates and lead["domain"]:
                    if lead["domain"] in seen_domains:
                        result.leads_duplicates += 1
                        continue
                    seen_domains.add(lead["domain"])

                # Add metadata
                lead["source"] = "csv"
                lead["source_row"] = row_num
                lead["status"] = "new"
                lead["imported_at"] = datetime.utcnow().isoformat()

                leads.append(lead)
                result.leads_imported += 1

                # Store sample for preview
                if len(result.sample_leads) < 3:
                    result.sample_leads.append(lead)

            except Exception as e:
                result.leads_invalid += 1
                if len(result.errors) < 10:
                    result.errors.append(f"Row {row_num}: {str(e)}")

        result.success = result.leads_imported > 0

    except Exception as e:
        result.errors.append(f"CSV parsing error: {str(e)}")
        logger.error("CSV parsing failed", error=str(e))

    return result


async def fetch_from_api(
    url: str,
    field_mapping: Optional[dict] = None,
    headers: Optional[dict] = None,
    params: Optional[dict] = None
) -> IngestResult:
    """
    Fetch leads from an API endpoint.

    Args:
        url: API endpoint URL
        field_mapping: Custom field mapping
        headers: Optional request headers (e.g., for auth)
        params: Optional query parameters

    Returns:
        IngestResult with fetched leads
    """
    result = IngestResult()

    mapping = {**DEFAULT_FIELD_MAPPING}
    if field_mapping:
        for key, value in field_mapping.items():
            if key in mapping:
                mapping[key] = value + mapping[key]
            else:
                mapping[key] = value

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers or {}, params=params or {})

            if response.status_code != 200:
                result.errors.append(f"API returned status {response.status_code}")
                return result

            data = response.json()

            # Handle different response structures
            records = []
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                # Try common keys for list data
                for key in ['data', 'records', 'results', 'items', 'leads']:
                    if key in data and isinstance(data[key], list):
                        records = data[key]
                        break
                if not records and 'rows' in data:
                    records = data['rows']

            if not records:
                result.errors.append("No records found in API response")
                return result

            seen_domains = set()

            for idx, row in enumerate(records):
                if not isinstance(row, dict):
                    continue

                lead = map_row_to_lead(row, mapping)

                url_val = lead.get("url")
                if not url_val:
                    result.leads_invalid += 1
                    continue

                normalized = normalize_url(url_val)
                if not normalized:
                    result.leads_invalid += 1
                    continue

                lead["url"] = normalized
                lead["domain"] = extract_domain(normalized)

                if lead["domain"] in seen_domains:
                    result.leads_duplicates += 1
                    continue
                seen_domains.add(lead["domain"])

                lead["source"] = "api"
                lead["source_index"] = idx
                lead["status"] = "new"
                lead["imported_at"] = datetime.utcnow().isoformat()

                result.leads_imported += 1
                if len(result.sample_leads) < 3:
                    result.sample_leads.append(lead)

            result.success = result.leads_imported > 0

    except httpx.TimeoutException:
        result.errors.append("API request timed out")
    except json.JSONDecodeError:
        result.errors.append("Invalid JSON response from API")
    except Exception as e:
        result.errors.append(f"API fetch error: {str(e)}")
        logger.error("API fetch failed", url=url, error=str(e))

    return result


async def fetch_from_airtable(
    base_url: str,
    field_mapping: Optional[dict] = None,
    api_key: Optional[str] = None
) -> IngestResult:
    """
    Fetch leads from Airtable.

    Args:
        base_url: Airtable API URL (e.g., https://api.airtable.com/v0/BASE_ID/TABLE_NAME)
        field_mapping: Custom field mapping
        api_key: Airtable API key (or from AIRTABLE_API_KEY env var)

    Returns:
        IngestResult with fetched leads
    """
    import os
    result = IngestResult()

    api_key = api_key or os.getenv("AIRTABLE_API_KEY")
    if not api_key:
        result.errors.append("Airtable API key not provided")
        return result

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    mapping = {**DEFAULT_FIELD_MAPPING}
    if field_mapping:
        for key, value in field_mapping.items():
            if key in mapping:
                mapping[key] = value + mapping[key]
            else:
                mapping[key] = value

    try:
        all_records = []
        offset = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {}
                if offset:
                    params["offset"] = offset

                response = await client.get(base_url, headers=headers, params=params)

                if response.status_code != 200:
                    result.errors.append(f"Airtable returned status {response.status_code}")
                    break

                data = response.json()
                records = data.get("records", [])
                all_records.extend(records)

                # Check for pagination
                offset = data.get("offset")
                if not offset:
                    break

        seen_domains = set()

        for idx, record in enumerate(all_records):
            fields = record.get("fields", {})
            lead = map_row_to_lead(fields, mapping)

            url_val = lead.get("url")
            if not url_val:
                result.leads_invalid += 1
                continue

            normalized = normalize_url(url_val)
            if not normalized:
                result.leads_invalid += 1
                continue

            lead["url"] = normalized
            lead["domain"] = extract_domain(normalized)

            if lead["domain"] in seen_domains:
                result.leads_duplicates += 1
                continue
            seen_domains.add(lead["domain"])

            lead["source"] = "airtable"
            lead["source_id"] = record.get("id")
            lead["status"] = "new"
            lead["imported_at"] = datetime.utcnow().isoformat()

            result.leads_imported += 1
            if len(result.sample_leads) < 3:
                result.sample_leads.append(lead)

        result.success = result.leads_imported > 0

    except Exception as e:
        result.errors.append(f"Airtable fetch error: {str(e)}")
        logger.error("Airtable fetch failed", url=base_url, error=str(e))

    return result


@register_tool(
    name="lead_ingest",
    category=ToolCategory.INLET,
    description="Imports leads from CSV files, API endpoints, or Airtable",
    schema={
        "source_type": {
            "type": "string",
            "required": True,
            "enum": ["csv", "api", "airtable"],
            "description": "Type of data source"
        },
        "source_url": {
            "type": "string",
            "required": False,
            "description": "API/Airtable URL (required for api/airtable types)"
        },
        "csv_content": {
            "type": "string",
            "required": False,
            "description": "CSV file content (required for csv type)"
        },
        "field_mapping": {
            "type": "object",
            "required": False,
            "description": "Custom field mapping (lead_field -> [source_fields])"
        },
        "headers": {
            "type": "object",
            "required": False,
            "description": "HTTP headers for API requests (e.g., auth)"
        },
        "api_key": {
            "type": "string",
            "required": False,
            "description": "API key for Airtable (or use AIRTABLE_API_KEY env var)"
        }
    },
    tags=["inlet", "csv", "api", "airtable", "import"]
)
async def lead_ingest_node(
    source_type: str,
    source_url: Optional[str] = None,
    csv_content: Optional[str] = None,
    field_mapping: Optional[dict] = None,
    headers: Optional[dict] = None,
    api_key: Optional[str] = None
) -> dict:
    """
    Import leads from various sources.

    Args:
        source_type: Type of source ("csv", "api", "airtable")
        source_url: URL for API/Airtable sources
        csv_content: CSV content for csv source
        field_mapping: Custom field mapping
        headers: HTTP headers for API requests
        api_key: API key for Airtable

    Returns:
        Dict with import results
    """
    if source_type == "csv":
        if not csv_content:
            return IngestResult(errors=["csv_content required for csv source"]).to_dict()
        result = await process_csv_content(csv_content, field_mapping)

    elif source_type == "api":
        if not source_url:
            return IngestResult(errors=["source_url required for api source"]).to_dict()
        result = await fetch_from_api(source_url, field_mapping, headers)

    elif source_type == "airtable":
        if not source_url:
            return IngestResult(errors=["source_url required for airtable source"]).to_dict()
        result = await fetch_from_airtable(source_url, field_mapping, api_key)

    else:
        return IngestResult(errors=[f"Unknown source_type: {source_type}"]).to_dict()

    return result.to_dict()
