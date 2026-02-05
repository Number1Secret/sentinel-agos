"""
Pydantic schemas for Lead Pipeline.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


# =====================
# Lead Schemas
# =====================

class LeadBase(BaseModel):
    """Base schema for lead data."""
    url: str = Field(..., description="URL to analyze")
    company_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    industry: Optional[str] = None
    metadata: Optional[dict] = Field(default_factory=dict)


class LeadCreate(LeadBase):
    """Schema for creating a new lead."""
    pass


class LeadUpdate(BaseModel):
    """Schema for updating a lead."""
    company_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    industry: Optional[str] = None
    metadata: Optional[dict] = None
    status: Optional[str] = None
    assigned_to: Optional[UUID] = None


class TriageSignalsSchema(BaseModel):
    """Schema for triage signals."""
    pagespeed_score: Optional[int] = None
    ssl_valid: Optional[bool] = None
    ssl_expires_days: Optional[int] = None
    mobile_responsive: Optional[bool] = None
    copyright_year: Optional[int] = None
    has_viewport_meta: Optional[bool] = None
    jquery_version: Optional[str] = None
    cms_detected: Optional[str] = None
    load_time_ms: Optional[int] = None


class LeadResponse(LeadBase):
    """Schema for lead response."""
    id: UUID
    domain: Optional[str] = None
    source: str
    batch_id: Optional[UUID] = None
    status: str
    current_room: Optional[str] = None

    # Triage results
    triage_score: Optional[float] = None
    triage_signals: Optional[dict] = None
    triage_completed_at: Optional[datetime] = None

    # Architect results
    mockup_url: Optional[str] = None
    mockup_code_url: Optional[str] = None
    brand_audit: Optional[dict] = None
    architect_completed_at: Optional[datetime] = None

    # Discovery results
    proposal_url: Optional[str] = None
    proposal_sent_at: Optional[datetime] = None
    deal_value: Optional[float] = None
    close_probability: Optional[float] = None

    # Attribution
    user_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None

    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime] = None
    status_changed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeadListResponse(BaseModel):
    """Schema for paginated lead list."""
    leads: List[LeadResponse]
    total: int
    limit: int
    offset: int


# =====================
# Bulk Import Schemas
# =====================

class BulkLeadItem(BaseModel):
    """Single item in bulk import."""
    url: str
    company_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    industry: Optional[str] = None


class BulkLeadCreate(BaseModel):
    """Schema for bulk lead import."""
    leads: List[BulkLeadItem] = Field(..., min_length=1, max_length=1000)
    batch_name: Optional[str] = None
    playbook_id: Optional[UUID] = None
    auto_triage: bool = Field(default=True, description="Automatically queue leads for triage")


class BulkLeadResponse(BaseModel):
    """Response for bulk import."""
    batch_id: UUID
    batch_name: str
    total_count: int
    status: str
    message: str


# =====================
# Batch Schemas
# =====================

class BatchCreate(BaseModel):
    """Schema for creating a batch."""
    name: str
    source: str = "api"
    playbook_id: Optional[UUID] = None
    options: Optional[dict] = Field(default_factory=dict)


class BatchResponse(BaseModel):
    """Schema for batch response."""
    id: UUID
    name: str
    source: str
    status: str
    total_count: int
    processed_count: int
    qualified_count: int
    disqualified_count: int
    error_count: int
    playbook_id: Optional[UUID] = None
    options: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BatchListResponse(BaseModel):
    """Schema for paginated batch list."""
    batches: List[BatchResponse]
    total: int
    limit: int
    offset: int


# =====================
# Triage Action Schemas
# =====================

class TriageRequest(BaseModel):
    """Request to manually trigger triage."""
    playbook_id: Optional[UUID] = None


class TriageResponse(BaseModel):
    """Response from triage action."""
    lead_id: UUID
    status: str
    message: str
    queued: bool


# =====================
# Negotiation Schemas
# =====================

class NegotiationResponse(BaseModel):
    """Schema for negotiation state response."""
    id: UUID
    lead_id: UUID
    base_price: Optional[float] = None
    current_price: Optional[float] = None
    min_acceptable_price: Optional[float] = None
    max_discount_pct: Optional[float] = None
    negotiation_state: str = "initial"
    sdr_state: str = "initial_outreach"
    total_touches: int = 0
    emails_sent: int = 0
    sms_sent: int = 0
    last_contact_at: Optional[datetime] = None
    last_prospect_action_at: Optional[datetime] = None
    next_action_at: Optional[datetime] = None
    objections: Optional[list] = None
    discount_history: Optional[list] = None
    stripe_checkout_session_id: Optional[str] = None
    contract_pdf_url: Optional[str] = None
    close_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================
# Agent Run Schemas
# =====================

class AgentRunResponse(BaseModel):
    """Schema for agent run response."""
    id: UUID
    agent_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    room: str
    trigger: str
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
