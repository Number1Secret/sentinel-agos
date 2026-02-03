# SENTINEL AgOS Implementation Plan

**Version:** 1.0
**Date:** February 2026
**Status:** Phase 1 Ready

---

## Executive Summary

This document defines the implementation plan for transforming the existing Sentinel MVP into the full **AgOS (Agent Operating System)** as specified in the PRD. The plan covers:

1. **Supabase Schema** - Agent Registry and Lead Pipeline
2. **FastAPI Monorepo Structure** - Supporting Room 1 (Triage) and Room 2 (Architect)
3. **MCP Servers** - Playwright for Triage, E2B for Architect

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Supabase Schema](#2-supabase-schema)
3. [Directory Structure](#3-directory-structure)
4. [MCP Servers](#4-mcp-servers)
5. [Implementation Phases](#5-implementation-phases)
6. [API Endpoints](#6-api-endpoints)
7. [Verification Plan](#7-verification-plan)

---

## 1. Architecture Overview

### The 4-Room Factory Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            THE AgOS FACTORY                                  │
│                                                                             │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐    ┌─────────┐│
│  │   ROOM 1      │    │   ROOM 2      │    │   ROOM 3      │    │ ROOM 4  ││
│  │   TRIAGE      │───▶│   ARCHITECT   │───▶│   DISCOVERY   │───▶│ GUARDIAN││
│  │   ENGINE      │    │   STUDIO      │    │   CHANNEL     │    │         ││
│  │               │    │               │    │   (Future)    │    │(Future) ││
│  │ Fast-pass     │    │ Deep audit +  │    │               │    │         ││
│  │ scanning      │    │ mockup gen    │    │               │    │         ││
│  └───────────────┘    └───────────────┘    └───────────────┘    └─────────┘│
│         │                    │                                              │
│         ▼                    ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     SHARED INFRASTRUCTURE                               ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ││
│  │  │ REGISTRY │  │   BUS    │  │  MEMORY  │  │ SANDBOX  │  │ PLAYBOOK ││  ││
│  │  │ Supabase │  │  Redis   │  │ Supabase │  │   E2B    │  │  YAML    ││  ││
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| API | FastAPI | REST API with async support |
| Database | Supabase (PostgreSQL) | Registry, Memory, Lead Pipeline |
| Queue | Redis | Job queue for room workers |
| Compute | Render | Web service + workers |
| AI | Claude 3.5 Sonnet | Agent intelligence |
| Browser | Playwright | URL scanning, screenshots |
| Sandbox | E2B | Code execution for mockups |

---

## 2. Supabase Schema

### 2.1 Schema Overview

The schema extends the existing MVP tables (`profiles`, `audits`, `webhooks`) with 6 new tables:

| Table | Purpose |
|-------|---------|
| `agents` | Agent Registry - stores agent definitions |
| `playbooks` | Room workflow configurations |
| `leads` | Lead pipeline with status transitions |
| `lead_batches` | Track bulk URL imports |
| `agent_runs` | Execution logs for observability |
| `generated_assets` | Store mockups, reports, screenshots |

### 2.2 Agent Registry Table

```sql
-- ======================
-- AGENT REGISTRY TABLE
-- ======================
-- Stores agent definitions with configurable system prompts, models, and tools

CREATE TABLE public.agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug TEXT UNIQUE NOT NULL,  -- e.g., 'triage', 'architect', 'sentinel'
    name TEXT NOT NULL,
    description TEXT,
    room TEXT NOT NULL CHECK (room IN ('triage', 'architect', 'discovery', 'guardian')),

    -- AI Configuration
    model TEXT NOT NULL DEFAULT 'claude-3-5-sonnet-20241022',
    temperature DECIMAL(3,2) DEFAULT 0.7 CHECK (temperature >= 0 AND temperature <= 2),
    max_tokens INTEGER DEFAULT 4096,
    system_prompt TEXT NOT NULL,

    -- Tools & Capabilities
    tools JSONB DEFAULT '[]',  -- Array of tool names/configs
    mcp_servers TEXT[],  -- MCP server connections required

    -- Operational Settings
    timeout_seconds INTEGER DEFAULT 120,
    retry_attempts INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT true,

    -- Metadata
    version TEXT DEFAULT '1.0.0',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initial agent seeds
INSERT INTO public.agents (slug, name, room, system_prompt, tools, mcp_servers) VALUES
(
    'triage',
    'Triage Agent',
    'triage',
    'You are the Sentinel Triage Agent. Your job is to quickly scan websites and identify high-intent signals that indicate the site owner needs professional help. Focus on: PageSpeed scores, SSL status, mobile responsiveness, and outdated copyright years. Score each URL from 0-100 based on the opportunity.',
    '["url_scan", "lighthouse_quick", "screenshot"]',
    ARRAY['playwright']
),
(
    'architect',
    'Architect Agent',
    'architect',
    'You are the Sentinel Architect Agent. Your job is to perform deep brand audits and generate production-ready mockups. Extract brand DNA (colors, fonts, voice) and create a new site that preserves the brand while fixing all identified issues.',
    '["deep_audit", "brand_extract", "mockup_generate", "code_sandbox"]',
    ARRAY['playwright', 'e2b']
),
(
    'sentinel',
    'Sentinel Scout Agent',
    'guardian',
    'You are the Sentinel Scout Agent. Analyze websites for performance, SEO, accessibility, and brand consistency. Provide actionable recommendations.',
    '["lighthouse", "screenshot", "brand_analyze"]',
    ARRAY['playwright']
);

CREATE INDEX idx_agents_room ON public.agents(room);
CREATE INDEX idx_agents_active ON public.agents(is_active) WHERE is_active = true;
```

### 2.3 Playbooks Table

```sql
-- ======================
-- PLAYBOOKS TABLE
-- ======================
-- YAML/JSON configs for each room's workflow

CREATE TABLE public.playbooks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug TEXT UNIQUE NOT NULL,  -- e.g., 'triage-standard', 'architect-saas'
    name TEXT NOT NULL,
    room TEXT NOT NULL CHECK (room IN ('triage', 'architect', 'discovery', 'guardian')),

    -- Playbook Configuration (JSONB stores the YAML as JSON)
    config JSONB NOT NULL,

    -- Industry/Use-case targeting
    industry_tags TEXT[],  -- e.g., ['saas', 'ecommerce', 'local-business']

    -- Operational
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 100,  -- Lower = higher priority for matching

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default triage playbook
INSERT INTO public.playbooks (slug, name, room, config, is_default) VALUES
(
    'triage-standard',
    'Standard Triage Playbook',
    'triage',
    '{
        "version": "1.0",
        "steps": [
            {"name": "fetch_url", "timeout_seconds": 30},
            {"name": "lighthouse_quick", "categories": ["performance"], "timeout_seconds": 60},
            {"name": "extract_signals", "signals": ["ssl", "copyright", "mobile", "pagespeed"]},
            {"name": "calculate_score", "threshold": 60}
        ],
        "qualification_rules": {
            "minimum_score": 60,
            "required_signals": ["pagespeed_below_50"]
        },
        "output": {
            "pass_to": "architect",
            "store_signals": true
        }
    }',
    true
),
(
    'architect-full-mockup',
    'Full Mockup Generation',
    'architect',
    '{
        "version": "1.0",
        "steps": [
            {"name": "deep_audit", "include": ["lighthouse", "brand", "competitors"]},
            {"name": "brand_extraction", "extract": ["colors", "fonts", "logo", "voice"]},
            {"name": "mockup_generation", "template": "modern-professional", "sandbox": "e2b"},
            {"name": "quality_check", "targets": {"pagespeed": 85, "mobile": 90}}
        ],
        "sandbox_config": {
            "provider": "e2b",
            "template": "nextjs",
            "timeout_hours": 72
        }
    }',
    true
);

CREATE INDEX idx_playbooks_room ON public.playbooks(room);
CREATE INDEX idx_playbooks_industry ON public.playbooks USING GIN(industry_tags);
```

### 2.4 Lead Pipeline Table

```sql
-- ======================
-- LEADS PIPELINE TABLE
-- ======================
-- Lead pipeline with status transitions across rooms

CREATE TABLE public.leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Source & Attribution
    source TEXT NOT NULL DEFAULT 'manual',  -- 'bulk_import', 'api', 'webhook', 'manual'
    source_id TEXT,  -- External reference (e.g., CSV row number)
    batch_id UUID,  -- Links to lead_batches for bulk imports

    -- Lead Information
    url TEXT NOT NULL,
    domain TEXT GENERATED ALWAYS AS (
        regexp_replace(url, '^https?://([^/]+).*$', '\1')
    ) STORED,
    company_name TEXT,
    contact_email TEXT,
    contact_name TEXT,
    industry TEXT,
    metadata JSONB DEFAULT '{}',  -- Flexible additional data

    -- Pipeline Status
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN (
        'new',           -- Just received
        'scanning',      -- Room 1: Being triaged
        'qualified',     -- Room 1: Passed triage
        'disqualified',  -- Room 1: Failed triage
        'designing',     -- Room 2: Architect working
        'mockup_ready',  -- Room 2: Mockup complete
        'presenting',    -- Room 3: In discovery (Future)
        'negotiating',   -- Room 3: Proposal sent (Future)
        'closed_won',    -- Won the deal
        'closed_lost',   -- Lost the deal
        'active_client', -- Room 4: Ongoing maintenance (Future)
        'churned'        -- Former client
    )),
    status_changed_at TIMESTAMPTZ DEFAULT NOW(),

    -- Room Assignments
    current_room TEXT CHECK (current_room IN ('triage', 'architect', 'discovery', 'guardian')),

    -- Triage Results (Room 1)
    triage_score DECIMAL(5,2),  -- 0-100 qualification score
    triage_signals JSONB,  -- High-intent signals detected
    -- Example: {"pagespeed": 34, "ssl_valid": false, "copyright_year": 2019, "mobile_responsive": false}
    triage_completed_at TIMESTAMPTZ,

    -- Architect Results (Room 2)
    mockup_url TEXT,  -- URL to generated mockup (E2B sandbox)
    mockup_code_url TEXT,  -- Storage URL for generated code
    brand_audit JSONB,  -- Deep brand analysis
    -- Example: {"colors": ["#1a1a1a", "#ffffff"], "fonts": ["Inter", "Georgia"], "voice": "professional"}
    architect_completed_at TIMESTAMPTZ,

    -- Discovery/Sales (Room 3 - Future)
    proposal_url TEXT,
    proposal_sent_at TIMESTAMPTZ,
    deal_value DECIMAL(10,2),
    close_probability DECIMAL(3,2),

    -- Guardian (Room 4 - Future)
    client_since TIMESTAMPTZ,
    mrr DECIMAL(10,2),  -- Monthly recurring revenue
    health_score INTEGER,  -- 0-100
    last_health_check TIMESTAMPTZ,

    -- Attribution
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    assigned_to UUID REFERENCES public.profiles(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX idx_leads_status ON public.leads(status);
CREATE INDEX idx_leads_domain ON public.leads(domain);
CREATE INDEX idx_leads_user_id ON public.leads(user_id);
CREATE INDEX idx_leads_batch_id ON public.leads(batch_id);
CREATE INDEX idx_leads_current_room ON public.leads(current_room);
CREATE INDEX idx_leads_triage_score ON public.leads(triage_score DESC) WHERE triage_score IS NOT NULL;
CREATE INDEX idx_leads_created_at ON public.leads(created_at DESC);

-- Function to auto-update status_changed_at
CREATE OR REPLACE FUNCTION public.update_lead_status_changed()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        NEW.status_changed_at = NOW();
    END IF;
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_status_changed
    BEFORE UPDATE ON public.leads
    FOR EACH ROW EXECUTE FUNCTION public.update_lead_status_changed();
```

### 2.5 Lead Batches Table

```sql
-- ======================
-- LEAD BATCHES TABLE
-- ======================
-- Track bulk import batches

CREATE TABLE public.lead_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'csv', 'airtable', 'api'

    -- Statistics
    total_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    qualified_count INTEGER NOT NULL DEFAULT 0,
    disqualified_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),

    -- Config
    playbook_id UUID REFERENCES public.playbooks(id),
    options JSONB DEFAULT '{}',

    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_lead_batches_user_id ON public.lead_batches(user_id);
CREATE INDEX idx_lead_batches_status ON public.lead_batches(status);
```

### 2.6 Agent Runs Table

```sql
-- ======================
-- AGENT RUNS TABLE
-- ======================
-- Track every agent execution for observability and cost tracking

CREATE TABLE public.agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Linkage
    agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
    lead_id UUID REFERENCES public.leads(id) ON DELETE CASCADE,
    audit_id UUID REFERENCES public.audits(id) ON DELETE SET NULL,  -- Backward compat with MVP
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    playbook_id UUID REFERENCES public.playbooks(id) ON DELETE SET NULL,

    -- Execution Context
    room TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'queue',  -- 'api', 'queue', 'scheduled', 'webhook'

    -- Input/Output
    input_data JSONB NOT NULL,
    output_data JSONB,

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'timeout', 'cancelled'
    )),
    error TEXT,
    error_details JSONB,

    -- Token & Cost Tracking
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    cost_usd DECIMAL(10,6) DEFAULT 0,

    -- Tool Usage
    tools_called JSONB DEFAULT '[]',  -- [{name, duration_ms, success, error}]
    mcp_calls JSONB DEFAULT '[]',  -- MCP server interactions

    -- Performance
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for analytics and debugging
CREATE INDEX idx_agent_runs_agent_id ON public.agent_runs(agent_id);
CREATE INDEX idx_agent_runs_lead_id ON public.agent_runs(lead_id);
CREATE INDEX idx_agent_runs_room ON public.agent_runs(room);
CREATE INDEX idx_agent_runs_status ON public.agent_runs(status);
CREATE INDEX idx_agent_runs_created_at ON public.agent_runs(created_at DESC);
CREATE INDEX idx_agent_runs_user_id ON public.agent_runs(user_id);
```

### 2.7 Generated Assets Table

```sql
-- ======================
-- GENERATED ASSETS TABLE
-- ======================
-- Store all generated artifacts (mockups, code, reports)

CREATE TABLE public.generated_assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    lead_id UUID REFERENCES public.leads(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,

    -- Asset Information
    asset_type TEXT NOT NULL CHECK (asset_type IN (
        'mockup_image',    -- Screenshot of generated mockup
        'mockup_code',     -- Source code archive
        'full_site_code',  -- Complete deployable site
        'report_pdf',      -- PDF audit report
        'report_html',     -- HTML audit report
        'screenshot',      -- Page screenshots
        'brand_guide',     -- Extracted brand guide
        'proposal'         -- Sales proposal document
    )),

    -- Storage
    storage_provider TEXT DEFAULT 'supabase',  -- 'supabase', 's3', 'github'
    storage_path TEXT NOT NULL,  -- Path within storage
    public_url TEXT,  -- CDN or signed URL for access

    -- Metadata
    filename TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    metadata JSONB DEFAULT '{}',

    -- Versioning
    version INTEGER DEFAULT 1,
    is_latest BOOLEAN DEFAULT true,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_generated_assets_lead_id ON public.generated_assets(lead_id);
CREATE INDEX idx_generated_assets_type ON public.generated_assets(asset_type);
CREATE INDEX idx_generated_assets_latest ON public.generated_assets(lead_id, asset_type) WHERE is_latest = true;
```

### 2.8 Row Level Security Policies

```sql
-- ======================
-- ROW LEVEL SECURITY
-- ======================

-- Leads
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own leads"
    ON public.leads FOR SELECT
    USING (auth.uid() = user_id OR auth.uid() = assigned_to);

CREATE POLICY "Users can create leads"
    ON public.leads FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own leads"
    ON public.leads FOR UPDATE
    USING (auth.uid() = user_id OR auth.uid() = assigned_to);

-- Service role bypass for workers
CREATE POLICY "Service role full access to leads"
    ON public.leads FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Lead Batches
ALTER TABLE public.lead_batches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own batches"
    ON public.lead_batches FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create batches"
    ON public.lead_batches FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Service role full access to batches"
    ON public.lead_batches FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Agent Runs
ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own agent runs"
    ON public.agent_runs FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to agent runs"
    ON public.agent_runs FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Generated Assets
ALTER TABLE public.generated_assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view assets for own leads"
    ON public.generated_assets FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.leads
            WHERE leads.id = generated_assets.lead_id
            AND (leads.user_id = auth.uid() OR leads.assigned_to = auth.uid())
        )
    );

CREATE POLICY "Service role full access to assets"
    ON public.generated_assets FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Agents and Playbooks are readable by all authenticated users
ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated users can view agents"
    ON public.agents FOR SELECT
    TO authenticated USING (true);

ALTER TABLE public.playbooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated users can view playbooks"
    ON public.playbooks FOR SELECT
    TO authenticated USING (true);
```

### 2.9 Extended Profiles Table

```sql
-- ======================
-- EXTEND PROFILES TABLE
-- ======================

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS organization_id UUID,
ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),

-- Quotas
ADD COLUMN IF NOT EXISTS triage_quota_monthly INTEGER DEFAULT 1000,
ADD COLUMN IF NOT EXISTS triage_used_monthly INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS architect_quota_monthly INTEGER DEFAULT 50,
ADD COLUMN IF NOT EXISTS architect_used_monthly INTEGER DEFAULT 0,

-- Billing
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT,
ADD COLUMN IF NOT EXISTS subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'starter', 'pro', 'agency', 'enterprise')),

-- Settings
ADD COLUMN IF NOT EXISTS default_playbook_id UUID REFERENCES public.playbooks(id),
ADD COLUMN IF NOT EXISTS notification_preferences JSONB DEFAULT '{"email": true, "webhook": true}',

-- Reset tracking
ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMPTZ DEFAULT (date_trunc('month', NOW()) + interval '1 month');
```

---

## 3. Directory Structure

### 3.1 Monorepo Layout

```
sentinel-mvp/                      # Renamed to sentinel-agos in future
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   ├── dependencies.py            # Shared dependencies (auth, db)
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py               # JWT validation (existing)
│   │   └── rate_limit.py         # Per-room rate limiting (existing)
│   └── routes/
│       ├── __init__.py
│       ├── auth.py               # EXISTING: Auth routes
│       ├── audits.py             # EXISTING: Audit routes (backward compat)
│       ├── webhooks.py           # EXISTING: Webhooks
│       ├── leads.py              # NEW: Lead pipeline CRUD
│       ├── agents.py             # NEW: Agent registry endpoints
│       ├── playbooks.py          # NEW: Playbook management
│       ├── batches.py            # NEW: Bulk import management
│       └── analytics.py          # NEW: Usage & cost analytics
│
├── rooms/                         # NEW: Room-based modules
│   ├── __init__.py
│   ├── base.py                   # Abstract room/agent interfaces
│   │
│   ├── triage/                   # Room 1: Triage Engine
│   │   ├── __init__.py
│   │   ├── agent.py              # TriageAgent class
│   │   ├── playbooks/
│   │   │   ├── standard.yaml     # Default triage playbook
│   │   │   ├── saas.yaml         # SaaS-focused signals
│   │   │   └── local_business.yaml
│   │   ├── prompts/
│   │   │   └── triage_system.md  # System prompt for triage
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── fast_scan.py      # Quick URL scanning
│   │   │   └── signal_detector.py # High-intent signal detection
│   │   └── schemas.py            # Triage-specific Pydantic models
│   │
│   ├── architect/                # Room 2: Architect Studio
│   │   ├── __init__.py
│   │   ├── agent.py              # ArchitectAgent class
│   │   ├── playbooks/
│   │   │   ├── full_mockup.yaml
│   │   │   └── quick_concept.yaml
│   │   ├── prompts/
│   │   │   ├── brand_audit.md
│   │   │   └── mockup_generation.md
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── deep_audit.py     # Comprehensive site analysis
│   │   │   ├── brand_extractor.py # Brand DNA extraction
│   │   │   ├── mockup_generator.py # E2B-powered generation
│   │   │   └── code_builder.py   # Site code generation
│   │   └── schemas.py
│   │
│   ├── discovery/                # Room 3: Discovery Channel (Future)
│   │   ├── __init__.py
│   │   ├── agent.py              # Placeholder
│   │   └── README.md             # Future implementation notes
│   │
│   └── guardian/                 # Room 4: Guardian (Future)
│       ├── __init__.py
│       ├── agent.py              # SentinelAgent for monitoring
│       └── README.md
│
├── agents/                        # EXISTING: Refactored agent base
│   ├── __init__.py
│   ├── base.py                   # NEW: BaseAgent abstract class
│   ├── scout.py                  # EXISTING: Now extends BaseAgent
│   ├── sandbox.py                # EXISTING: E2B integration
│   └── prompts/
│       └── scout_analysis.md     # EXISTING
│
├── services/                      # EXISTING: Shared services
│   ├── __init__.py
│   ├── supabase.py              # EXISTING: Extended for new tables
│   ├── anthropic.py             # EXISTING: Add streaming support
│   ├── browser.py               # EXISTING: Playwright service
│   ├── lighthouse.py            # EXISTING
│   ├── mcp_client.py            # NEW: MCP client wrapper
│   └── e2b_sandbox.py           # NEW: Enhanced E2B service
│
├── worker/                        # EXISTING: Background workers
│   ├── __init__.py
│   ├── main.py                  # MODIFIED: Multi-queue support
│   ├── queues.py                # NEW: Queue definitions per room
│   └── tasks/
│       ├── __init__.py
│       ├── audit.py             # EXISTING: Scout audit task
│       ├── triage.py            # NEW: Triage processing
│       ├── architect.py         # NEW: Architect processing
│       └── guardian.py          # NEW: Scheduled monitoring (Future)
│
├── schemas/                       # EXISTING: Pydantic models
│   ├── __init__.py
│   ├── audit.py                 # EXISTING
│   ├── analysis.py              # EXISTING
│   ├── leads.py                 # NEW: Lead models
│   ├── agents.py                # NEW: Agent/Playbook models
│   └── analytics.py             # NEW: Analytics models
│
├── config/
│   ├── __init__.py
│   └── settings.py              # EXISTING: Extended with new settings
│
├── mcp_servers/                   # NEW: MCP server configurations
│   ├── __init__.py
│   ├── playwright_mcp.py        # Playwright MCP wrapper
│   └── e2b_mcp.py               # E2B MCP wrapper
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py              # EXISTING
│   ├── test_scout.py            # EXISTING
│   ├── test_triage.py           # NEW
│   ├── test_architect.py        # NEW
│   └── fixtures/
│       ├── sample_urls.json
│       └── mock_responses.json
│
├── docs/                          # NEW
│   ├── IMPLEMENTATION_PLAN.md   # This document
│   └── API.md                   # API documentation
│
├── render.yaml                   # MODIFIED: Multi-worker setup
├── pyproject.toml               # MODIFIED: New dependencies
├── requirements.txt
├── supabase_schema.sql          # MODIFIED: Full schema
└── README.md
```

### 3.2 Key New Components

#### Base Agent Class (`agents/base.py`)

```python
"""
Base Agent class for all Sentinel agents.
Provides common functionality for LLM calls, tool execution, and observability.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
from uuid import UUID
import structlog
from anthropic import Anthropic

logger = structlog.get_logger()


@dataclass
class AgentConfig:
    """Configuration loaded from agents table."""
    id: UUID
    slug: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    tools: list[str]
    mcp_servers: list[str]
    timeout_seconds: int


@dataclass
class AgentRunContext:
    """Context for a single agent execution."""
    run_id: UUID
    lead_id: Optional[UUID]
    user_id: UUID
    playbook_id: Optional[UUID]
    input_data: dict


class BaseAgent(ABC):
    """Abstract base class for all Sentinel agents."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._tools: dict[str, callable] = {}
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    @abstractmethod
    async def run(self, context: AgentRunContext) -> dict:
        """Execute the agent's main logic."""
        pass

    def register_tool(self, name: str, func: callable, schema: dict):
        """Register a tool for use by the agent."""
        self._tools[name] = {"func": func, "schema": schema}

    async def call_llm(self, messages: list[dict], **kwargs) -> dict:
        """Make an LLM call with automatic token tracking."""
        # Implementation details...
        pass
```

#### Base Room Class (`rooms/base.py`)

```python
"""
Base Room class defining the interface for all processing rooms.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Type
from uuid import UUID


@dataclass
class RoomConfig:
    """Configuration for a room."""
    name: str
    queue_name: str
    agent_class: type
    default_playbook: str
    input_statuses: list[str]
    output_status_success: str
    output_status_failure: str


class BaseRoom(ABC):
    """Abstract base class for processing rooms."""

    config: RoomConfig

    @abstractmethod
    async def process_lead(self, lead, playbook_id: Optional[UUID] = None) -> dict:
        """Process a single lead through this room."""
        pass

    @abstractmethod
    async def on_success(self, lead, result: dict):
        """Handle successful processing."""
        pass

    @abstractmethod
    async def on_failure(self, lead, error: str):
        """Handle failed processing."""
        pass
```

---

## 4. MCP Servers

### 4.1 Overview

| Room | MCP Server | Purpose |
|------|------------|---------|
| Triage | Playwright MCP | Fast URL scanning, screenshot capture, DOM extraction |
| Architect | Playwright MCP | Deep website analysis, full-page screenshots |
| Architect | E2B MCP | Sandboxed code execution for mockup generation |
| Discovery (Future) | GitHub MCP | Push generated code to repos |
| Guardian (Future) | Vercel MCP | Deploy and monitor sites |

### 4.2 Playwright MCP

**Purpose:** Browser automation for URL scanning and visual capture

**Tools Available:**

| Tool | Description | Parameters |
|------|-------------|------------|
| `navigate` | Navigate browser to URL | `url`, `wait_until`, `timeout_ms` |
| `screenshot` | Capture page screenshot | `full_page`, `viewport` |
| `extract_text` | Extract text content | `selector` |
| `extract_links` | Get all links from page | - |
| `evaluate_js` | Execute JavaScript in page | `script` |
| `get_page_info` | Get page metadata | - |

**Configuration:**

```python
# mcp_servers/playwright_mcp.py

PLAYWRIGHT_CONFIG = {
    "name": "playwright",
    "transport": "stdio",
    "command": "npx",
    "args": ["@anthropic-ai/mcp-server-playwright"],
    "timeout_ms": 30000,
    "viewport": {
        "width": 1920,
        "height": 1080
    }
}

# Triage-optimized settings (faster, lighter)
TRIAGE_PLAYWRIGHT_CONFIG = {
    **PLAYWRIGHT_CONFIG,
    "timeout_ms": 15000,
    "viewport": {"width": 1280, "height": 720},
    "wait_until": "domcontentloaded"  # Faster than networkidle
}

# Architect settings (full quality)
ARCHITECT_PLAYWRIGHT_CONFIG = {
    **PLAYWRIGHT_CONFIG,
    "timeout_ms": 60000,
    "wait_until": "networkidle"
}
```

### 4.3 E2B MCP

**Purpose:** Sandboxed code execution for generating and previewing mockups

**Tools Available:**

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_sandbox` | Create execution sandbox | `template`, `timeout_seconds` |
| `run_code` | Execute code in sandbox | `sandbox_id`, `code`, `language` |
| `install_packages` | Install npm/pip packages | `sandbox_id`, `packages` |
| `write_file` | Write file to sandbox | `sandbox_id`, `path`, `content` |
| `read_file` | Read file from sandbox | `sandbox_id`, `path` |
| `get_preview_url` | Get public preview URL | `sandbox_id`, `port` |
| `close_sandbox` | Cleanup sandbox | `sandbox_id` |

**Configuration:**

```python
# mcp_servers/e2b_mcp.py

E2B_CONFIG = {
    "name": "e2b",
    "api_key_env": "E2B_API_KEY",
    "templates": {
        "nextjs": "nextjs-developer",
        "react": "react-developer",
        "python": "python3"
    },
    "default_timeout_seconds": 300,
    "max_timeout_hours": 72
}

# Sandbox templates for mockup generation
MOCKUP_TEMPLATES = {
    "modern-professional": {
        "base": "nextjs",
        "packages": ["tailwindcss", "lucide-react", "framer-motion"],
        "starter_files": ["tailwind.config.js", "globals.css"]
    },
    "minimal-clean": {
        "base": "nextjs",
        "packages": ["tailwindcss"],
        "starter_files": ["tailwind.config.js"]
    }
}
```

### 4.4 MCP Client Wrapper

```python
# services/mcp_client.py

"""
Unified MCP client for Sentinel agents.
"""
from dataclasses import dataclass
from typing import Optional, Any
import structlog

logger = structlog.get_logger()


@dataclass
class MCPServerConfig:
    name: str
    transport: str  # 'stdio', 'http'
    endpoint: str
    auth_token: Optional[str] = None
    timeout_ms: int = 30000


class MCPClient:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._connections: dict[str, Any] = {}

    def register_server(self, config: MCPServerConfig):
        """Register an MCP server configuration."""
        self._servers[config.name] = config

    async def connect(self, server_name: str):
        """Establish connection to an MCP server."""
        if server_name not in self._servers:
            raise ValueError(f"Unknown MCP server: {server_name}")
        # Connection logic...

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict
    ) -> dict:
        """Execute a tool on an MCP server."""
        logger.info("MCP tool call", server=server_name, tool=tool_name)
        # Tool execution logic...

    async def disconnect(self, server_name: str):
        """Disconnect from an MCP server."""
        pass
```

---

## 5. Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Goals:**
- Set up expanded Supabase schema
- Create base classes for agents and rooms
- Implement multi-queue worker infrastructure

**Tasks:**

| Task | Priority | Effort |
|------|----------|--------|
| Run expanded schema SQL in Supabase | High | 2h |
| Create `agents/base.py` BaseAgent class | High | 4h |
| Create `rooms/base.py` BaseRoom class | High | 4h |
| Update `worker/main.py` for multi-queue | High | 4h |
| Create `worker/queues.py` definitions | Medium | 2h |
| Add leads CRUD to `services/supabase.py` | High | 4h |
| Create `api/routes/leads.py` endpoints | High | 6h |
| Create `schemas/leads.py` Pydantic models | Medium | 2h |

**Deliverables:**
- [ ] All new tables created in Supabase
- [ ] Base classes ready for room implementations
- [ ] Worker can process multiple queues
- [ ] Leads API endpoints functional

### Phase 2: Triage Room (Week 3-4)

**Goals:**
- Implement TriageAgent with fast-scan capability
- Integrate Playwright MCP for URL scanning
- Build qualification scoring system

**Tasks:**

| Task | Priority | Effort |
|------|----------|--------|
| Create `rooms/triage/agent.py` | High | 8h |
| Create `rooms/triage/tools/fast_scan.py` | High | 6h |
| Create `rooms/triage/tools/signal_detector.py` | High | 6h |
| Create `mcp_servers/playwright_mcp.py` | High | 4h |
| Create `worker/tasks/triage.py` | High | 4h |
| Write triage system prompt | Medium | 2h |
| Create standard playbook YAML | Medium | 2h |
| Add bulk import endpoint | Medium | 6h |
| Unit tests for triage | Medium | 4h |

**High-Intent Signals (Phase 1 - Core Technical):**
- PageSpeed score < 50
- SSL certificate invalid/expired
- Not mobile responsive
- Copyright year > 2 years old

**Deliverables:**
- [ ] TriageAgent processes URLs and scores them
- [ ] Qualified leads transition to `qualified` status
- [ ] Bulk CSV import working
- [ ] Target: 100 URLs/hour throughput

### Phase 3: Architect Room (Week 5-7)

**Goals:**
- Implement ArchitectAgent with deep audit
- Integrate E2B sandbox for mockup generation
- Build brand extraction and code generation

**Tasks:**

| Task | Priority | Effort |
|------|----------|--------|
| Create `rooms/architect/agent.py` | High | 12h |
| Create `rooms/architect/tools/deep_audit.py` | High | 8h |
| Create `rooms/architect/tools/brand_extractor.py` | High | 8h |
| Create `rooms/architect/tools/mockup_generator.py` | High | 12h |
| Create `mcp_servers/e2b_mcp.py` | High | 6h |
| Create `services/e2b_sandbox.py` | High | 6h |
| Create `worker/tasks/architect.py` | High | 4h |
| Create mockup playbooks | Medium | 4h |
| Unit tests for architect | Medium | 6h |
| Integration test: triage → architect | High | 4h |

**Deliverables:**
- [ ] ArchitectAgent generates mockups from qualified leads
- [ ] Brand extraction captures colors, fonts, voice
- [ ] E2B sandbox generates live preview URLs
- [ ] Generated assets stored in Supabase Storage

### Phase 4: Integration & Polish (Week 8)

**Goals:**
- End-to-end testing
- Analytics and monitoring
- Documentation

**Tasks:**

| Task | Priority | Effort |
|------|----------|--------|
| End-to-end integration tests | High | 8h |
| Create `api/routes/analytics.py` | Medium | 6h |
| Cost tracking per agent run | Medium | 4h |
| Quota enforcement | Medium | 4h |
| Update render.yaml with room workers | High | 2h |
| API documentation | Medium | 4h |
| README updates | Low | 2h |

**Deliverables:**
- [ ] Full pipeline: URL → Triage → Architect → Mockup
- [ ] Analytics dashboard data available
- [ ] Quotas enforced per user
- [ ] Production-ready deployment config

---

## 6. API Endpoints

### 6.1 Leads Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/leads` | Create single lead |
| `POST` | `/leads/bulk` | Bulk import (CSV) |
| `GET` | `/leads` | List leads with filters |
| `GET` | `/leads/{id}` | Get lead details |
| `PATCH` | `/leads/{id}` | Update lead |
| `DELETE` | `/leads/{id}` | Delete lead |
| `POST` | `/leads/{id}/triage` | Manually trigger triage |
| `POST` | `/leads/{id}/architect` | Manually trigger architect |

### 6.2 Batches Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/batches` | Create batch import |
| `GET` | `/batches` | List batches |
| `GET` | `/batches/{id}` | Get batch status |
| `POST` | `/batches/{id}/cancel` | Cancel batch |

### 6.3 Agents Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/agents` | List all agents |
| `GET` | `/agents/{slug}` | Get agent details |

### 6.4 Playbooks Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/playbooks` | List playbooks |
| `GET` | `/playbooks/{slug}` | Get playbook config |

### 6.5 Analytics Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/analytics/usage` | Token/cost usage |
| `GET` | `/analytics/pipeline` | Lead pipeline stats |
| `GET` | `/analytics/agents` | Agent performance |

---

## 7. Verification Plan

### 7.1 Unit Tests

```python
# tests/test_triage.py

async def test_triage_agent_scores_url():
    """Test that triage agent correctly scores a URL."""
    agent = TriageAgent(config)
    result = await agent.run(context)
    assert "score" in result
    assert 0 <= result["score"] <= 100

async def test_signal_detector_finds_pagespeed():
    """Test PageSpeed signal detection."""
    signals = await detect_signals("https://slow-site.com")
    assert "pagespeed" in signals
    assert signals["pagespeed"] < 50

# tests/test_architect.py

async def test_architect_generates_mockup():
    """Test mockup generation for qualified lead."""
    agent = ArchitectAgent(config)
    result = await agent.run(context)
    assert "mockup_url" in result
    assert result["mockup_url"].startswith("https://")
```

### 7.2 Integration Tests

```python
# tests/test_integration.py

async def test_full_pipeline():
    """Test URL → Triage → Architect → Mockup."""
    # 1. Create lead
    lead = await create_lead(url="https://old-site.com")
    assert lead.status == "new"

    # 2. Process through triage
    await process_triage(lead.id)
    lead = await get_lead(lead.id)
    assert lead.status in ["qualified", "disqualified"]

    # 3. If qualified, process through architect
    if lead.status == "qualified":
        await process_architect(lead.id)
        lead = await get_lead(lead.id)
        assert lead.status == "mockup_ready"
        assert lead.mockup_url is not None
```

### 7.3 Manual Testing Checklist

- [ ] Submit 10 URLs via API, verify triage scoring
- [ ] Submit 100 URLs via CSV bulk import
- [ ] Verify qualified leads have correct signals
- [ ] Generate mockup for qualified lead
- [ ] Access mockup preview URL
- [ ] Check Render dashboard for worker logs
- [ ] Verify agent_runs table has execution data
- [ ] Check cost tracking in agent_runs

---

## 8. Render Deployment

### 8.1 Updated render.yaml

```yaml
services:
  # API Service
  - type: web
    name: sentinel-api
    runtime: python
    region: oregon
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn api.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: "3.11"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: E2B_API_KEY
        sync: false
      - key: REDIS_URL
        fromService:
          type: redis
          name: sentinel-redis
          property: connectionString
      - key: ENVIRONMENT
        value: production
    autoDeploy: true

  # Triage Worker (HIGH VOLUME)
  - type: worker
    name: sentinel-triage-worker
    runtime: python
    region: oregon
    plan: standard
    buildCommand: |
      pip install -r requirements.txt
      npx playwright install chromium --with-deps
    startCommand: python -m worker.main --queue triage_queue
    envVars:
      - key: WORKER_TYPE
        value: triage
      - key: WORKER_CONCURRENCY
        value: "10"
      - key: PYTHON_VERSION
        value: "3.11"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: REDIS_URL
        fromService:
          type: redis
          name: sentinel-redis
          property: connectionString
    autoDeploy: true

  # Architect Worker
  - type: worker
    name: sentinel-architect-worker
    runtime: python
    region: oregon
    plan: standard
    buildCommand: |
      pip install -r requirements.txt
      npx playwright install chromium --with-deps
    startCommand: python -m worker.main --queue architect_queue
    envVars:
      - key: WORKER_TYPE
        value: architect
      - key: WORKER_CONCURRENCY
        value: "3"
      - key: PYTHON_VERSION
        value: "3.11"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: E2B_API_KEY
        sync: false
      - key: REDIS_URL
        fromService:
          type: redis
          name: sentinel-redis
          property: connectionString
    autoDeploy: true

  # Legacy Audit Worker (backward compatibility)
  - type: worker
    name: sentinel-worker
    runtime: python
    region: oregon
    plan: starter
    buildCommand: |
      pip install -r requirements.txt
      npx playwright install chromium --with-deps
    startCommand: python -m worker.main --queue audit_queue
    envVars:
      - key: WORKER_TYPE
        value: audit
      - key: PYTHON_VERSION
        value: "3.11"
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: REDIS_URL
        fromService:
          type: redis
          name: sentinel-redis
          property: connectionString
    autoDeploy: true

  # Redis (Job Queue)
  - type: redis
    name: sentinel-redis
    region: oregon
    plan: starter
    maxmemoryPolicy: allkeys-lru
```

---

## Appendix A: Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_ANON_KEY` | Supabase anon/public key | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | Yes |
| `ANTHROPIC_API_KEY` | Anthropic API key | Yes |
| `E2B_API_KEY` | E2B API key | Yes (Architect) |
| `REDIS_URL` | Redis connection string | Yes |
| `ENVIRONMENT` | `development` or `production` | Yes |
| `WORKER_TYPE` | `triage`, `architect`, `audit` | Workers only |
| `WORKER_CONCURRENCY` | Number of concurrent jobs | Workers only |

---

## Appendix B: Cost Estimates

### Per-URL Costs

| Stage | Operation | Est. Cost |
|-------|-----------|-----------|
| Triage | Lighthouse quick + screenshot | $0.005 |
| Triage | Claude analysis (500 tokens) | $0.002 |
| **Triage Total** | | **~$0.007** |
| Architect | Full Lighthouse + screenshots | $0.01 |
| Architect | Claude deep analysis (4000 tokens) | $0.015 |
| Architect | E2B sandbox (5 min) | $0.05 |
| **Architect Total** | | **~$0.075** |

### Monthly Projections (1000 URLs triaged, 100 mockups)

| Item | Quantity | Unit Cost | Total |
|------|----------|-----------|-------|
| Triage | 1000 | $0.007 | $7 |
| Architect | 100 | $0.075 | $7.50 |
| Render Workers | 3 | ~$25/mo | $75 |
| Redis | 1 | $10/mo | $10 |
| **Monthly Total** | | | **~$100** |

---

*Document generated for SENTINEL AgOS - February 2026*
