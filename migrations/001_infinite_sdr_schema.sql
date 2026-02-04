-- Migration: Infinite SDR Engine Schema Updates
-- Version: 001
-- Description: Adds dynamic pricing to agents, workflows table, and extended playbook schema support
-- Run this in Supabase SQL Editor after the initial schema

-- =====================================================
-- STEP 1: Add pricing columns to agents table
-- =====================================================
-- Allows per-model pricing instead of hard-coded values

ALTER TABLE public.agents
ADD COLUMN IF NOT EXISTS input_price_per_1m DECIMAL(10,4) DEFAULT 3.00,
ADD COLUMN IF NOT EXISTS output_price_per_1m DECIMAL(10,4) DEFAULT 15.00,
ADD COLUMN IF NOT EXISTS pricing_model TEXT DEFAULT 'anthropic'
    CHECK (pricing_model IN ('anthropic', 'openai', 'google', 'custom'));

-- Update existing agents with appropriate pricing
-- Claude 3.5 Sonnet pricing
UPDATE public.agents
SET input_price_per_1m = 3.00, output_price_per_1m = 15.00, pricing_model = 'anthropic'
WHERE model LIKE '%sonnet%' AND input_price_per_1m IS NULL;

-- Claude 3.5 Haiku pricing (if any)
UPDATE public.agents
SET input_price_per_1m = 0.25, output_price_per_1m = 1.25, pricing_model = 'anthropic'
WHERE model LIKE '%haiku%' AND input_price_per_1m IS NULL;

-- Claude 3 Opus pricing (if any)
UPDATE public.agents
SET input_price_per_1m = 15.00, output_price_per_1m = 75.00, pricing_model = 'anthropic'
WHERE model LIKE '%opus%' AND input_price_per_1m IS NULL;

COMMENT ON COLUMN public.agents.input_price_per_1m IS 'Cost per 1M input tokens in USD';
COMMENT ON COLUMN public.agents.output_price_per_1m IS 'Cost per 1M output tokens in USD';
COMMENT ON COLUMN public.agents.pricing_model IS 'Pricing model provider for reference';


-- =====================================================
-- STEP 2: Create workflows table for graph-based execution
-- =====================================================
-- Allows agencies to define custom processing graphs (Inlet -> Triage -> Enrich -> Architect)

CREATE TABLE IF NOT EXISTS public.workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,

    -- Graph definition (JSON adjacency list)
    -- Example: {"inlet": "triage", "triage": ["enrich", "architect"], "enrich": "architect"}
    graph JSONB NOT NULL DEFAULT '{}',

    -- Entry conditions for starting the workflow
    entry_conditions JSONB DEFAULT '{}',
    -- Example: {"source": ["api", "csv"], "has_url": true}

    -- Human approval gates - nodes that require manual approval before proceeding
    approval_gates TEXT[] DEFAULT '{}',

    -- Workflow ownership and status
    is_active BOOLEAN DEFAULT true,
    is_default BOOLEAN DEFAULT false,
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for workflow lookups
CREATE INDEX IF NOT EXISTS idx_workflows_slug ON public.workflows(slug);
CREATE INDEX IF NOT EXISTS idx_workflows_active ON public.workflows(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_workflows_default ON public.workflows(is_default) WHERE is_default = true;
CREATE INDEX IF NOT EXISTS idx_workflows_user_id ON public.workflows(user_id);

-- RLS for workflows
ALTER TABLE public.workflows ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own workflows"
    ON public.workflows FOR SELECT
    USING (auth.uid() = user_id OR is_default = true);

CREATE POLICY "Users can create workflows"
    ON public.workflows FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own workflows"
    ON public.workflows FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own workflows"
    ON public.workflows FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to workflows"
    ON public.workflows FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Trigger for updated_at
CREATE TRIGGER workflows_updated_at
    BEFORE UPDATE ON public.workflows
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


-- =====================================================
-- STEP 3: Insert default workflow
-- =====================================================

INSERT INTO public.workflows (slug, name, description, graph, is_default, is_active)
VALUES (
    'standard-sdr-flow',
    'Standard SDR Flow',
    'Default lead processing: Triage -> Architect (Gold leads get auto-enrichment)',
    '{
        "inlet": "triage",
        "triage": {
            "qualified": "architect",
            "gold": ["enrich", "architect"]
        },
        "enrich": "architect",
        "architect": "complete"
    }',
    true,
    true
)
ON CONFLICT (slug) DO NOTHING;


-- =====================================================
-- STEP 4: Create human_approval_queue table
-- =====================================================
-- Stores leads awaiting human approval at workflow gates

CREATE TABLE IF NOT EXISTS public.human_approval_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    lead_id UUID REFERENCES public.leads(id) ON DELETE CASCADE,
    workflow_id UUID REFERENCES public.workflows(id) ON DELETE SET NULL,

    -- Approval context
    gate_name TEXT NOT NULL,  -- Which gate triggered approval
    current_room TEXT NOT NULL,
    next_room TEXT,

    -- Approval data
    approval_data JSONB DEFAULT '{}',  -- Data for reviewer to see

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),

    -- Reviewer info
    reviewed_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,

    -- Expiration
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approval_queue_lead ON public.human_approval_queue(lead_id);
CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON public.human_approval_queue(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approval_queue_expires ON public.human_approval_queue(expires_at) WHERE status = 'pending';

-- RLS for approval queue
ALTER TABLE public.human_approval_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own approval items"
    ON public.human_approval_queue FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.leads
            WHERE leads.id = human_approval_queue.lead_id
            AND (leads.user_id = auth.uid() OR leads.assigned_to = auth.uid())
        )
    );

CREATE POLICY "Users can update own approval items"
    ON public.human_approval_queue FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.leads
            WHERE leads.id = human_approval_queue.lead_id
            AND (leads.user_id = auth.uid() OR leads.assigned_to = auth.uid())
        )
    );

CREATE POLICY "Service role full access to approval queue"
    ON public.human_approval_queue FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- =====================================================
-- STEP 5: Add enrichment columns to leads table
-- =====================================================

ALTER TABLE public.leads
ADD COLUMN IF NOT EXISTS enrichment_data JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS enrichment_source TEXT,  -- 'apollo', 'hunter', 'manual'
ADD COLUMN IF NOT EXISTS enrichment_completed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS workflow_id UUID REFERENCES public.workflows(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS workflow_position TEXT;  -- Current position in workflow graph

COMMENT ON COLUMN public.leads.enrichment_data IS 'Contact verification data from Apollo/Hunter APIs';
COMMENT ON COLUMN public.leads.workflow_id IS 'Active workflow processing this lead';
COMMENT ON COLUMN public.leads.workflow_position IS 'Current node position in workflow graph';


-- =====================================================
-- STEP 6: Update playbook with sample v2.0 config
-- =====================================================

-- Insert a sample v2.0 playbook with required_tools and logic_gates
INSERT INTO public.playbooks (slug, name, room, config, is_default, is_active)
VALUES (
    'triage-infinite-sdr',
    'Infinite SDR Triage Playbook',
    'triage',
    '{
        "version": "2.0",
        "required_tools": ["url_scan", "lighthouse_quick", "ad_pixel_sensor"],
        "logic_gates": {
            "qualification": {
                "operator": "AND",
                "conditions": [
                    {"field": "triage_score", "op": ">=", "value": 60},
                    {"field": "scan_success", "op": "==", "value": true}
                ]
            },
            "gold_lead": {
                "operator": "OR",
                "conditions": [
                    {"field": "triage_score", "op": ">=", "value": 85},
                    {
                        "operator": "AND",
                        "conditions": [
                            {"field": "signals.cms_detected", "op": "==", "value": "shopify"},
                            {"field": "triage_score", "op": ">=", "value": 70}
                        ]
                    }
                ]
            },
            "high_ad_spend": {
                "operator": "AND",
                "conditions": [
                    {"field": "signals.has_meta_pixel", "op": "==", "value": true},
                    {"field": "signals.has_google_ads", "op": "==", "value": true}
                ]
            }
        },
        "auto_enrich": {
            "trigger": "gold_lead",
            "tools": ["contact_verification"]
        },
        "signals": {
            "pagespeed_threshold": 50,
            "copyright_max_age_years": 2,
            "ssl_required": true,
            "mobile_required": true
        },
        "scoring": {
            "pagespeed_weight": 25,
            "ssl_weight": 15,
            "mobile_weight": 20,
            "copyright_weight": 20,
            "ad_pixel_weight": 20
        },
        "qualification": {
            "minimum_score": 60,
            "auto_qualify_above": 80,
            "auto_disqualify_below": 30
        },
        "output": {
            "pass_to_room": "architect",
            "store_signals": true,
            "store_enrichment": true
        }
    }',
    false,
    true
)
ON CONFLICT (slug) DO UPDATE SET
    config = EXCLUDED.config,
    updated_at = NOW();


-- =====================================================
-- STEP 7: Add tool_calls tracking to agent_runs
-- =====================================================
-- Ensure tools_called column exists with proper structure

-- The column already exists, but let's add a comment for clarity
COMMENT ON COLUMN public.agent_runs.tools_called IS 'Array of tool calls: [{name, duration_ms, success, error, result_summary}]';


-- =====================================================
-- DONE
-- =====================================================
-- To verify migration success, run:
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'agents' AND column_name LIKE '%price%';
-- SELECT * FROM public.workflows;
-- SELECT slug, config->>'version' as version FROM public.playbooks;
