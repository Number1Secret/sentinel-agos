"""
ContactVerificationNode - Apollo.io API integration for B2B contact enrichment.

Finds verified owner/decision-maker contact information:
- Domain-based company lookup
- Decision-maker identification (Owner, CEO, Founder, etc.)
- Verified email addresses
- LinkedIn profile URLs
- Phone numbers with confidence scores

Requires APOLLO_API_KEY environment variable.
"""
import os
from typing import Optional, List
from dataclasses import dataclass, field

import httpx
import structlog

from rooms.triage.tools.registry import register_tool, ToolCategory

logger = structlog.get_logger()

APOLLO_API_URL = "https://api.apollo.io/v1"

# Default titles to search for (decision makers)
DEFAULT_DECISION_MAKER_TITLES = [
    "owner",
    "founder",
    "co-founder",
    "ceo",
    "chief executive officer",
    "president",
    "managing director",
    "principal",
    "partner",
    "director",
    "vp marketing",
    "head of marketing",
    "cmo",
    "chief marketing officer",
]


@dataclass
class Contact:
    """A verified contact."""
    name: str
    email: Optional[str] = None
    email_status: Optional[str] = None  # 'verified', 'guessed', 'unavailable'
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    phone: Optional[str] = None
    phone_type: Optional[str] = None  # 'direct', 'mobile', 'hq'
    confidence_score: float = 0.0  # 0-1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "email_status": self.email_status,
            "title": self.title,
            "linkedin_url": self.linkedin_url,
            "phone": self.phone,
            "phone_type": self.phone_type,
            "confidence_score": self.confidence_score
        }


@dataclass
class OrganizationInfo:
    """Company/organization information from Apollo."""
    name: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    employee_range: Optional[str] = None
    linkedin_url: Optional[str] = None
    website_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    founded_year: Optional[int] = None
    annual_revenue: Optional[str] = None
    technologies: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "employee_count": self.employee_count,
            "employee_range": self.employee_range,
            "linkedin_url": self.linkedin_url,
            "website_url": self.website_url,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "founded_year": self.founded_year,
            "annual_revenue": self.annual_revenue,
            "technologies": self.technologies,
            "keywords": self.keywords
        }


@dataclass
class EnrichmentResult:
    """Results of contact verification/enrichment."""
    success: bool = False
    organization: Optional[OrganizationInfo] = None
    contacts: List[Contact] = field(default_factory=list)
    total_contacts_found: int = 0
    error: Optional[str] = None
    api_credits_used: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "organization": self.organization.to_dict() if self.organization else None,
            "contacts": [c.to_dict() for c in self.contacts],
            "total_contacts_found": self.total_contacts_found,
            "error": self.error,
            "api_credits_used": self.api_credits_used
        }


class ApolloClient:
    """Client for Apollo.io API."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("APOLLO_API_KEY")
        self.timeout = timeout

    def _get_headers(self) -> dict:
        """Get API request headers."""
        return {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }

    async def enrich_organization(self, domain: str) -> Optional[OrganizationInfo]:
        """
        Enrich organization data by domain.

        Args:
            domain: Company domain (e.g., "acme.com")

        Returns:
            OrganizationInfo or None if not found
        """
        if not self.api_key:
            logger.warning("Apollo API key not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{APOLLO_API_URL}/organizations/enrich",
                    headers=self._get_headers(),
                    json={"domain": domain}
                )

                if response.status_code != 200:
                    logger.warning(
                        "Apollo organization enrich failed",
                        status=response.status_code,
                        domain=domain
                    )
                    return None

                data = response.json()
                org = data.get("organization", {})

                if not org:
                    return None

                return OrganizationInfo(
                    name=org.get("name"),
                    domain=org.get("primary_domain") or domain,
                    industry=org.get("industry"),
                    employee_count=org.get("estimated_num_employees"),
                    employee_range=org.get("employee_range"),
                    linkedin_url=org.get("linkedin_url"),
                    website_url=org.get("website_url"),
                    city=org.get("city"),
                    state=org.get("state"),
                    country=org.get("country"),
                    founded_year=org.get("founded_year"),
                    annual_revenue=org.get("annual_revenue_printed"),
                    technologies=org.get("technologies", []) or [],
                    keywords=org.get("keywords", []) or []
                )

        except Exception as e:
            logger.error("Apollo organization enrich error", error=str(e), domain=domain)
            return None

    async def search_people(
        self,
        domain: str,
        titles: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[Contact]:
        """
        Search for people at a company by domain.

        Args:
            domain: Company domain
            titles: List of job titles to search for (decision makers)
            limit: Max results to return

        Returns:
            List of Contact objects
        """
        if not self.api_key:
            logger.warning("Apollo API key not configured")
            return []

        titles = titles or DEFAULT_DECISION_MAKER_TITLES

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{APOLLO_API_URL}/mixed_people/search",
                    headers=self._get_headers(),
                    json={
                        "organization_domains": [domain],
                        "person_titles": titles,
                        "per_page": limit
                    }
                )

                if response.status_code != 200:
                    logger.warning(
                        "Apollo people search failed",
                        status=response.status_code,
                        domain=domain
                    )
                    return []

                data = response.json()
                people = data.get("people", [])

                contacts = []
                for person in people:
                    # Calculate confidence score
                    confidence = 0.5  # Base score
                    email_status = person.get("email_status")
                    if email_status == "verified":
                        confidence = 0.95
                    elif email_status == "guessed":
                        confidence = 0.7

                    # Boost for direct phone
                    if person.get("phone_numbers"):
                        confidence = min(confidence + 0.1, 1.0)

                    # Get best phone number
                    phone = None
                    phone_type = None
                    phone_numbers = person.get("phone_numbers", [])
                    if phone_numbers:
                        # Prefer mobile/direct over HQ
                        for p in phone_numbers:
                            if p.get("type") in ("mobile", "direct_dial"):
                                phone = p.get("sanitized_number") or p.get("number")
                                phone_type = p.get("type")
                                break
                        if not phone and phone_numbers:
                            phone = phone_numbers[0].get("sanitized_number") or phone_numbers[0].get("number")
                            phone_type = phone_numbers[0].get("type")

                    contact = Contact(
                        name=person.get("name", ""),
                        email=person.get("email"),
                        email_status=email_status,
                        title=person.get("title"),
                        linkedin_url=person.get("linkedin_url"),
                        phone=phone,
                        phone_type=phone_type,
                        confidence_score=confidence
                    )
                    contacts.append(contact)

                # Sort by confidence score (highest first)
                contacts.sort(key=lambda c: c.confidence_score, reverse=True)

                return contacts

        except Exception as e:
            logger.error("Apollo people search error", error=str(e), domain=domain)
            return []


# Singleton client
_apollo_client = ApolloClient()


async def verify_contacts(
    domain: str,
    company_name: Optional[str] = None,
    titles: Optional[List[str]] = None,
    limit: int = 5
) -> EnrichmentResult:
    """
    Verify and enrich contacts for a domain.

    Args:
        domain: Company domain (e.g., "acme.com")
        company_name: Optional company name hint
        titles: Optional list of job titles to search
        limit: Max contacts to return

    Returns:
        EnrichmentResult with organization and contacts
    """
    result = EnrichmentResult()

    # Check for API key
    if not _apollo_client.api_key:
        result.error = "APOLLO_API_KEY not configured"
        return result

    # Clean domain
    domain = domain.lower().strip()
    if domain.startswith("http://"):
        domain = domain[7:]
    if domain.startswith("https://"):
        domain = domain[8:]
    if domain.startswith("www."):
        domain = domain[4:]
    domain = domain.split("/")[0]  # Remove path

    try:
        # Enrich organization
        org_info = await _apollo_client.enrich_organization(domain)
        if org_info:
            result.organization = org_info
            result.api_credits_used += 1

        # Search for decision makers
        contacts = await _apollo_client.search_people(domain, titles, limit)
        result.contacts = contacts
        result.total_contacts_found = len(contacts)
        result.api_credits_used += 1

        result.success = bool(org_info or contacts)

    except Exception as e:
        result.error = str(e)
        logger.error("Contact verification failed", domain=domain, error=str(e))

    return result


@register_tool(
    name="contact_verification",
    category=ToolCategory.ENRICH,
    description="Finds verified owner contact info via Apollo.io API - emails, LinkedIn, phone numbers",
    schema={
        "domain": {
            "type": "string",
            "required": True,
            "description": "Company domain (e.g., 'acme.com')"
        },
        "company_name": {
            "type": "string",
            "required": False,
            "description": "Optional company name hint"
        },
        "titles": {
            "type": "array",
            "required": False,
            "description": "Job titles to search for (defaults to decision makers)"
        },
        "limit": {
            "type": "integer",
            "required": False,
            "default": 5,
            "description": "Max contacts to return"
        }
    },
    requires_api_key="APOLLO_API_KEY",
    tags=["enrichment", "contacts", "apollo", "b2b"]
)
async def contact_verification_node(
    domain: str,
    company_name: Optional[str] = None,
    titles: Optional[List[str]] = None,
    limit: int = 5
) -> dict:
    """
    Verify and enrich contacts for a domain using Apollo.io.

    Args:
        domain: Company domain (e.g., "acme.com")
        company_name: Optional company name hint
        titles: Optional list of job titles to search
        limit: Max contacts to return

    Returns:
        Dict with organization info and verified contacts
    """
    result = await verify_contacts(domain, company_name, titles, limit)
    return result.to_dict()
