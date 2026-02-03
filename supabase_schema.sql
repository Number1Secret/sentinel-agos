-- Sentinel MVP Database Schema for Supabase
-- Run this in the Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================
-- PROFILES TABLE
-- =====================
-- Extends Supabase auth.users with application-specific data
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT,
    company_name TEXT,
    plan TEXT DEFAULT 'free' CHECK (plan IN ('free', 'starter', 'pro')),
    audits_remaining INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================
-- AUDITS TABLE
-- =====================
-- Stores website audit jobs and results
CREATE TABLE public.audits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    status TEXT DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'completed', 'failed')),

    -- Configuration
    competitors TEXT[], -- Array of competitor URLs
    options JSONB DEFAULT '{}',

    -- Results (populated on completion)
    performance JSONB,
    seo JSONB,
    accessibility JSONB,
    brand JSONB,
    analysis JSONB,
    screenshots JSONB,

    -- Metadata
    tokens_used INTEGER,
    cost_usd DECIMAL(10, 4),
    processing_time_ms INTEGER,
    error TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- =====================
-- WEBHOOKS TABLE
-- =====================
-- User-registered webhooks for audit notifications
CREATE TABLE public.webhooks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    events TEXT[] NOT NULL,
    secret TEXT,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================
-- INDEXES
-- =====================
CREATE INDEX idx_audits_user_id ON public.audits(user_id);
CREATE INDEX idx_audits_status ON public.audits(status);
CREATE INDEX idx_audits_created_at ON public.audits(created_at DESC);
CREATE INDEX idx_webhooks_user_id ON public.webhooks(user_id);
CREATE INDEX idx_webhooks_active ON public.webhooks(active) WHERE active = true;

-- =====================
-- ROW LEVEL SECURITY
-- =====================
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhooks ENABLE ROW LEVEL SECURITY;

-- Profiles policies
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- Audits policies
CREATE POLICY "Users can view own audits"
    ON public.audits FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create own audits"
    ON public.audits FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Service role can update audits (for worker)
CREATE POLICY "Service role can update audits"
    ON public.audits FOR UPDATE
    USING (true)
    WITH CHECK (true);

-- Webhooks policies
CREATE POLICY "Users can view own webhooks"
    ON public.webhooks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create own webhooks"
    ON public.webhooks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own webhooks"
    ON public.webhooks FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own webhooks"
    ON public.webhooks FOR DELETE
    USING (auth.uid() = user_id);

-- =====================
-- FUNCTIONS
-- =====================

-- Auto-create profile on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email)
    VALUES (NEW.id, NEW.email);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger for new user signup
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for profiles updated_at
CREATE TRIGGER profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Decrement audits_remaining when audit is created
CREATE OR REPLACE FUNCTION public.decrement_audits_remaining()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE public.profiles
    SET audits_remaining = audits_remaining - 1
    WHERE id = NEW.user_id AND audits_remaining > 0;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_audit_created
    AFTER INSERT ON public.audits
    FOR EACH ROW EXECUTE FUNCTION public.decrement_audits_remaining();

-- =====================
-- STORAGE BUCKETS
-- =====================
-- Run these separately in Supabase Storage settings or via API

-- Create bucket for audit screenshots
-- INSERT INTO storage.buckets (id, name, public) VALUES ('audit-screenshots', 'audit-screenshots', true);

-- Create bucket for generated reports
-- INSERT INTO storage.buckets (id, name, public) VALUES ('audit-reports', 'audit-reports', false);


-- =====================================================
-- =====================================================
-- SENTINEL AgOS SCHEMA EXTENSION
-- The Agency Operating System - 4-Room Factory
-- =====================================================
-- =====================================================

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
CREATE INDEX idx_agents_slug ON public.agents(slug);
CREATE INDEX idx_agents_active ON public.agents(is_active) WHERE is_active = true;


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
        "signals": {
            "pagespeed_threshold": 50,
            "copyright_max_age_years": 2,
            "ssl_required": true,
            "mobile_required": true
        },
        "scoring": {
            "pagespeed_weight": 30,
            "ssl_weight": 20,
            "mobile_weight": 25,
            "copyright_weight": 25
        },
        "qualification": {
            "minimum_score": 60,
            "auto_qualify_above": 80,
            "auto_disqualify_below": 30
        },
        "output": {
            "pass_to_room": "architect",
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
CREATE INDEX idx_playbooks_slug ON public.playbooks(slug);
CREATE INDEX idx_playbooks_default ON public.playbooks(room, is_default) WHERE is_default = true;
CREATE INDEX idx_playbooks_industry ON public.playbooks USING GIN(industry_tags);


-- ======================
-- LEAD BATCHES TABLE
-- ======================
-- Track bulk import batches (created before leads table for FK reference)

CREATE TABLE public.lead_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'csv',  -- 'csv', 'airtable', 'api'

    -- Statistics
    total_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    qualified_count INTEGER NOT NULL DEFAULT 0,
    disqualified_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),

    -- Config
    playbook_id UUID REFERENCES public.playbooks(id) ON DELETE SET NULL,
    options JSONB DEFAULT '{}',

    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_lead_batches_user_id ON public.lead_batches(user_id);
CREATE INDEX idx_lead_batches_status ON public.lead_batches(status);
CREATE INDEX idx_lead_batches_created_at ON public.lead_batches(created_at DESC);


-- ======================
-- LEADS PIPELINE TABLE
-- ======================
-- Lead pipeline with status transitions across rooms

CREATE TABLE public.leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Source & Attribution
    source TEXT NOT NULL DEFAULT 'manual',  -- 'bulk_import', 'api', 'webhook', 'manual'
    source_id TEXT,  -- External reference (e.g., CSV row number)
    batch_id UUID REFERENCES public.lead_batches(id) ON DELETE SET NULL,

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
CREATE INDEX idx_leads_status_room ON public.leads(status, current_room);


-- ======================
-- AGENT RUNS TABLE
-- ======================
-- Track every agent execution for observability and cost tracking
-- THIS IS CRITICAL FOR THE INFRASTRUCTURE-FIRST APPROACH

CREATE TABLE public.agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Linkage
    agent_id UUID REFERENCES public.agents(id) ON DELETE SET NULL,
    lead_id UUID REFERENCES public.leads(id) ON DELETE CASCADE,
    audit_id UUID REFERENCES public.audits(id) ON DELETE SET NULL,  -- Backward compat with MVP
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    playbook_id UUID REFERENCES public.playbooks(id) ON DELETE SET NULL,
    batch_id UUID REFERENCES public.lead_batches(id) ON DELETE SET NULL,

    -- Execution Context
    room TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'queue',  -- 'api', 'queue', 'scheduled', 'webhook', 'manual'

    -- Input/Output
    input_data JSONB NOT NULL,
    output_data JSONB,

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'timeout', 'cancelled'
    )),
    error TEXT,
    error_details JSONB,

    -- Token & Cost Tracking (NON-NEGOTIABLE - logged after every LLM call)
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
CREATE INDEX idx_agent_runs_audit_id ON public.agent_runs(audit_id);
CREATE INDEX idx_agent_runs_room ON public.agent_runs(room);
CREATE INDEX idx_agent_runs_status ON public.agent_runs(status);
CREATE INDEX idx_agent_runs_created_at ON public.agent_runs(created_at DESC);
CREATE INDEX idx_agent_runs_user_id ON public.agent_runs(user_id);
CREATE INDEX idx_agent_runs_batch_id ON public.agent_runs(batch_id);


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
CREATE INDEX idx_generated_assets_agent_run ON public.generated_assets(agent_run_id);
CREATE INDEX idx_generated_assets_latest ON public.generated_assets(lead_id, asset_type) WHERE is_latest = true;


-- ======================
-- EXTEND PROFILES TABLE
-- ======================
-- Add AgOS-specific columns for quotas and settings

ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS organization_id UUID,
ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),

-- Room Quotas
ADD COLUMN IF NOT EXISTS triage_quota_monthly INTEGER DEFAULT 1000,
ADD COLUMN IF NOT EXISTS triage_used_monthly INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS architect_quota_monthly INTEGER DEFAULT 50,
ADD COLUMN IF NOT EXISTS architect_used_monthly INTEGER DEFAULT 0,

-- Billing
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT,
ADD COLUMN IF NOT EXISTS subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'starter', 'pro', 'agency', 'enterprise')),

-- Settings
ADD COLUMN IF NOT EXISTS default_playbook_id UUID REFERENCES public.playbooks(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS notification_preferences JSONB DEFAULT '{"email": true, "webhook": true, "slack": false}',

-- Reset tracking
ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMPTZ DEFAULT (date_trunc('month', NOW()) + interval '1 month');


-- ======================
-- ROW LEVEL SECURITY FOR NEW TABLES
-- ======================

-- Agents (readable by all authenticated users)
ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can view agents"
    ON public.agents FOR SELECT
    TO authenticated USING (true);

CREATE POLICY "Service role can manage agents"
    ON public.agents FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Playbooks (readable by all authenticated users)
ALTER TABLE public.playbooks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can view playbooks"
    ON public.playbooks FOR SELECT
    TO authenticated USING (true);

CREATE POLICY "Service role can manage playbooks"
    ON public.playbooks FOR ALL
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

CREATE POLICY "Users can update own batches"
    ON public.lead_batches FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to batches"
    ON public.lead_batches FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

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

CREATE POLICY "Users can delete own leads"
    ON public.leads FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to leads"
    ON public.leads FOR ALL
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


-- ======================
-- TRIGGERS FOR NEW TABLES
-- ======================

-- Auto-update updated_at for leads
CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON public.leads
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-update updated_at for agents
CREATE TRIGGER agents_updated_at
    BEFORE UPDATE ON public.agents
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-update updated_at for playbooks
CREATE TRIGGER playbooks_updated_at
    BEFORE UPDATE ON public.playbooks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Function to auto-update lead status_changed_at
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

-- Function to update batch statistics when lead status changes
CREATE OR REPLACE FUNCTION public.update_batch_stats()
RETURNS TRIGGER AS $$
BEGIN
    -- Only update if lead has a batch_id and status changed
    IF NEW.batch_id IS NOT NULL AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
        UPDATE public.lead_batches
        SET
            processed_count = (
                SELECT COUNT(*) FROM public.leads
                WHERE batch_id = NEW.batch_id
                AND status NOT IN ('new', 'scanning')
            ),
            qualified_count = (
                SELECT COUNT(*) FROM public.leads
                WHERE batch_id = NEW.batch_id
                AND status IN ('qualified', 'designing', 'mockup_ready', 'presenting', 'negotiating', 'closed_won', 'active_client')
            ),
            disqualified_count = (
                SELECT COUNT(*) FROM public.leads
                WHERE batch_id = NEW.batch_id
                AND status = 'disqualified'
            )
        WHERE id = NEW.batch_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER update_batch_on_lead_change
    AFTER INSERT OR UPDATE ON public.leads
    FOR EACH ROW EXECUTE FUNCTION public.update_batch_stats();

-- Function to calculate agent run duration
CREATE OR REPLACE FUNCTION public.calculate_agent_run_duration()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.completed_at IS NOT NULL AND NEW.started_at IS NOT NULL THEN
        NEW.duration_ms = EXTRACT(EPOCH FROM (NEW.completed_at - NEW.started_at)) * 1000;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agent_runs_duration
    BEFORE UPDATE ON public.agent_runs
    FOR EACH ROW EXECUTE FUNCTION public.calculate_agent_run_duration();


-- ======================
-- STORAGE BUCKETS FOR AgOS
-- ======================
-- Run these separately in Supabase Storage settings or via API

-- Create bucket for mockup screenshots
-- INSERT INTO storage.buckets (id, name, public) VALUES ('mockups', 'mockups', true);

-- Create bucket for generated code archives
-- INSERT INTO storage.buckets (id, name, public) VALUES ('generated-code', 'generated-code', false);

-- Create bucket for brand assets
-- INSERT INTO storage.buckets (id, name, public) VALUES ('brand-assets', 'brand-assets', false);
