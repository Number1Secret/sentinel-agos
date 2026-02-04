-- =====================================================
-- MIGRATION 002: AUTONOMOUS PRODUCTION FORGE (Room 2)
-- Transforms Architect Studio into hyper-customizable forge
-- =====================================================

-- ======================
-- 1. EXTEND AGENTS TABLE
-- ======================
-- Add customization columns for house styles, niche prompts, and quality thresholds

ALTER TABLE public.agents
ADD COLUMN IF NOT EXISTS house_styles JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS niche_prompts JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS quality_threshold INTEGER DEFAULT 85;

-- Add pricing columns for unit economics
ALTER TABLE public.agents
ADD COLUMN IF NOT EXISTS cost_per_input_token DECIMAL(10,8) DEFAULT 0.000003,
ADD COLUMN IF NOT EXISTS cost_per_output_token DECIMAL(10,8) DEFAULT 0.000015;

COMMENT ON COLUMN public.agents.house_styles IS 'Agency-specific design rules, brand voice, and component preferences';
COMMENT ON COLUMN public.agents.niche_prompts IS 'Industry-specific prompts that layer on top of base prompts';
COMMENT ON COLUMN public.agents.quality_threshold IS 'Minimum quality score (0-100) required to pass self-audit';

-- Example house_styles structure:
-- {
--   "design_rules": {
--     "spacing_scale": "4px base",
--     "corner_radius": "0.5rem",
--     "shadow_style": "subtle"
--   },
--   "brand_voice": {
--     "tone": "professional-friendly",
--     "avoid_words": ["synergy"],
--     "prefer_words": ["streamline"]
--   },
--   "component_preferences": {
--     "cta_style": "rounded-full",
--     "navigation": "sticky-header"
--   }
-- }


-- ======================
-- 2. EXTEND GENERATED_ASSETS TABLE
-- ======================
-- Add sandbox, preview, quality, and iteration tracking

ALTER TABLE public.generated_assets
ADD COLUMN IF NOT EXISTS sandbox_id TEXT,
ADD COLUMN IF NOT EXISTS preview_url TEXT,
ADD COLUMN IF NOT EXISTS source_code_archive_url TEXT,
ADD COLUMN IF NOT EXISTS quality_score INTEGER,
ADD COLUMN IF NOT EXISTS iteration_count INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS parent_asset_id UUID REFERENCES public.generated_assets(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS audit_results JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS brand_dna JSONB DEFAULT '{}';

COMMENT ON COLUMN public.generated_assets.sandbox_id IS 'E2B sandbox instance ID for live preview';
COMMENT ON COLUMN public.generated_assets.preview_url IS 'Live preview URL from E2B sandbox';
COMMENT ON COLUMN public.generated_assets.source_code_archive_url IS 'URL to downloadable source code archive';
COMMENT ON COLUMN public.generated_assets.quality_score IS 'Vision audit quality score (0-100)';
COMMENT ON COLUMN public.generated_assets.iteration_count IS 'Number of regeneration iterations';
COMMENT ON COLUMN public.generated_assets.parent_asset_id IS 'Previous iteration asset ID for version tracking';
COMMENT ON COLUMN public.generated_assets.audit_results IS 'Detailed vision audit breakdown scores';
COMMENT ON COLUMN public.generated_assets.brand_dna IS 'Extracted brand DNA used for this asset';

-- Index for sandbox lookups
CREATE INDEX IF NOT EXISTS idx_generated_assets_sandbox ON public.generated_assets(sandbox_id) WHERE sandbox_id IS NOT NULL;

-- Index for iteration tracking
CREATE INDEX IF NOT EXISTS idx_generated_assets_parent ON public.generated_assets(parent_asset_id) WHERE parent_asset_id IS NOT NULL;

-- Index for quality-based queries
CREATE INDEX IF NOT EXISTS idx_generated_assets_quality ON public.generated_assets(quality_score DESC) WHERE quality_score IS NOT NULL;


-- ======================
-- 3. CREATE MCP_TOOL_REGISTRY TABLE
-- ======================
-- Allows agencies to register custom MCP tools

CREATE TABLE IF NOT EXISTS public.mcp_tool_registry (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,

    -- Tool Identity
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT CHECK (category IN ('brand', 'code', 'audit', 'content', 'integration')),

    -- MCP Configuration
    mcp_server_config JSONB NOT NULL,  -- Connection config for MCP server
    tool_schema JSONB NOT NULL,         -- JSON Schema for tool parameters

    -- Operational Settings
    is_active BOOLEAN DEFAULT true,
    timeout_ms INTEGER DEFAULT 30000,
    retry_attempts INTEGER DEFAULT 2,

    -- Usage Tracking
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    average_duration_ms INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, slug)
);

COMMENT ON TABLE public.mcp_tool_registry IS 'Custom MCP tools registered by agencies for use in architect workflows';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mcp_tools_user ON public.mcp_tool_registry(user_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_category ON public.mcp_tool_registry(category);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_active ON public.mcp_tool_registry(user_id, is_active) WHERE is_active = true;


-- ======================
-- 4. CREATE ARCHITECT_WORKFLOWS TABLE
-- ======================
-- n8n-style workflow graphs for architect room

CREATE TABLE IF NOT EXISTS public.architect_workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,

    -- Workflow Identity
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,

    -- Workflow Graph (n8n-style)
    graph JSONB NOT NULL,

    -- Quality Settings
    quality_threshold INTEGER DEFAULT 85 CHECK (quality_threshold >= 0 AND quality_threshold <= 100),
    max_iterations INTEGER DEFAULT 3 CHECK (max_iterations >= 1 AND max_iterations <= 10),

    -- Model Configuration
    self_audit_model TEXT DEFAULT 'claude-sonnet-4-20250514',
    code_gen_model TEXT DEFAULT 'claude-sonnet-4-20250514',

    -- Operational
    is_default BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,

    -- Stats
    usage_count INTEGER DEFAULT 0,
    average_quality_score DECIMAL(5,2),
    average_iterations DECIMAL(3,2),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, slug)
);

COMMENT ON TABLE public.architect_workflows IS 'Custom workflow graphs for architect room execution';

-- Workflow graph structure example:
-- {
--   "nodes": [
--     {"id": "brand_dna", "type": "tool", "tool": "brand_extract"},
--     {"id": "strategy", "type": "tool", "tool": "strategy_synthesis"},
--     {"id": "code_forge", "type": "tool", "tool": "mockup_generate"},
--     {"id": "self_audit", "type": "audit", "tool": "vision_audit"},
--     {"id": "quality_gate", "type": "condition", "conditions": [
--       {"field": "quality_score", "op": ">=", "value": 90, "target": "complete"},
--       {"field": "iteration_count", "op": "<", "value": 3, "target": "code_forge"}
--     ]}
--   ],
--   "edges": [
--     {"source": "brand_dna", "target": "strategy"},
--     {"source": "strategy", "target": "code_forge"},
--     {"source": "code_forge", "target": "self_audit"},
--     {"source": "self_audit", "target": "quality_gate"}
--   ],
--   "entry": "brand_dna"
-- }

-- Indexes
CREATE INDEX IF NOT EXISTS idx_architect_workflows_user ON public.architect_workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_architect_workflows_default ON public.architect_workflows(user_id, is_default) WHERE is_default = true;
CREATE INDEX IF NOT EXISTS idx_architect_workflows_active ON public.architect_workflows(user_id, is_active) WHERE is_active = true;


-- ======================
-- 5. CREATE PROMPT_LIBRARY TABLE
-- ======================
-- Cascading prompts (Cursor-style) for layered generation

CREATE TABLE IF NOT EXISTS public.prompt_library (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,

    -- Prompt Identity
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,

    -- Prompt Content
    category TEXT NOT NULL CHECK (category IN ('house_style', 'niche', 'component', 'audit', 'brand')),
    prompt_text TEXT NOT NULL,

    -- Targeting
    niche_tags TEXT[],           -- e.g., ['saas', 'ecommerce', 'healthcare']
    component_tags TEXT[],       -- e.g., ['hero', 'pricing', 'testimonials']

    -- Cascade Settings
    priority INTEGER DEFAULT 100,  -- Lower = higher priority
    cascade_mode TEXT DEFAULT 'append' CHECK (cascade_mode IN ('append', 'prepend', 'replace')),

    -- Operational
    is_active BOOLEAN DEFAULT true,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, slug)
);

COMMENT ON TABLE public.prompt_library IS 'Cascading prompts for layered mockup generation (house_style → niche → component)';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prompt_library_user ON public.prompt_library(user_id);
CREATE INDEX IF NOT EXISTS idx_prompt_library_category ON public.prompt_library(user_id, category);
CREATE INDEX IF NOT EXISTS idx_prompt_library_niche ON public.prompt_library USING GIN(niche_tags);
CREATE INDEX IF NOT EXISTS idx_prompt_library_component ON public.prompt_library USING GIN(component_tags);
CREATE INDEX IF NOT EXISTS idx_prompt_library_priority ON public.prompt_library(user_id, category, priority);


-- ======================
-- 6. CREATE APPROVAL_ITEMS TABLE
-- ======================
-- Items requiring human approval at quality gates

CREATE TABLE IF NOT EXISTS public.approval_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Linkage
    lead_id UUID REFERENCES public.leads(id) ON DELETE CASCADE,
    asset_id UUID REFERENCES public.generated_assets(id) ON DELETE SET NULL,
    agent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,
    workflow_id UUID REFERENCES public.architect_workflows(id) ON DELETE SET NULL,
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,

    -- Approval Context
    type TEXT NOT NULL CHECK (type IN (
        'workflow_gate',   -- Quality gate in workflow
        'enrichment',      -- Data enrichment approval
        'mockup',          -- Mockup approval before delivery
        'discovery',       -- Discovery material approval
        'final_report'     -- Final report approval
    )),

    -- Status
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),

    -- Content
    title TEXT NOT NULL,
    description TEXT,
    preview_data JSONB,           -- Data to display in preview
    approval_metadata JSONB,      -- Additional context for decision

    -- Decision
    decided_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ,
    decision_reason TEXT,

    -- Expiration
    expires_at TIMESTAMPTZ,

    -- Priority
    priority INTEGER DEFAULT 100,  -- Lower = higher priority

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.approval_items IS 'Items requiring human approval at various quality gates';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_approval_items_user ON public.approval_items(user_id);
CREATE INDEX IF NOT EXISTS idx_approval_items_lead ON public.approval_items(lead_id);
CREATE INDEX IF NOT EXISTS idx_approval_items_status ON public.approval_items(status);
CREATE INDEX IF NOT EXISTS idx_approval_items_type ON public.approval_items(type);
CREATE INDEX IF NOT EXISTS idx_approval_items_pending ON public.approval_items(user_id, status, priority) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approval_items_created ON public.approval_items(created_at DESC);


-- ======================
-- 7. ROW LEVEL SECURITY
-- ======================

-- MCP Tool Registry
ALTER TABLE public.mcp_tool_registry ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own MCP tools"
    ON public.mcp_tool_registry FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create MCP tools"
    ON public.mcp_tool_registry FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own MCP tools"
    ON public.mcp_tool_registry FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own MCP tools"
    ON public.mcp_tool_registry FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to MCP tools"
    ON public.mcp_tool_registry FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- Architect Workflows
ALTER TABLE public.architect_workflows ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own workflows"
    ON public.architect_workflows FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create workflows"
    ON public.architect_workflows FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own workflows"
    ON public.architect_workflows FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own workflows"
    ON public.architect_workflows FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to workflows"
    ON public.architect_workflows FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- Prompt Library
ALTER TABLE public.prompt_library ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own prompts"
    ON public.prompt_library FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create prompts"
    ON public.prompt_library FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own prompts"
    ON public.prompt_library FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own prompts"
    ON public.prompt_library FOR DELETE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to prompts"
    ON public.prompt_library FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- Approval Items
ALTER TABLE public.approval_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own approval items"
    ON public.approval_items FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create approval items"
    ON public.approval_items FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own approval items"
    ON public.approval_items FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to approval items"
    ON public.approval_items FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- ======================
-- 8. TRIGGERS
-- ======================

-- Auto-update updated_at for MCP tools
CREATE TRIGGER mcp_tool_registry_updated_at
    BEFORE UPDATE ON public.mcp_tool_registry
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-update updated_at for architect workflows
CREATE TRIGGER architect_workflows_updated_at
    BEFORE UPDATE ON public.architect_workflows
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-update updated_at for prompt library
CREATE TRIGGER prompt_library_updated_at
    BEFORE UPDATE ON public.prompt_library
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Auto-update updated_at for approval items
CREATE TRIGGER approval_items_updated_at
    BEFORE UPDATE ON public.approval_items
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


-- ======================
-- 9. DEFAULT WORKFLOW SEED
-- ======================
-- Insert a default architect workflow for all users

INSERT INTO public.architect_workflows (user_id, slug, name, description, graph, is_default, is_active)
VALUES (
    NULL,  -- NULL user_id means system default
    'default-forge',
    'Default Production Forge',
    'Standard 4-step workflow with vision self-audit and quality gates',
    '{
        "nodes": [
            {"id": "brand_dna", "type": "tool", "tool": "brand_extract", "label": "Extract Brand DNA"},
            {"id": "strategy", "type": "tool", "tool": "strategy_synthesis", "label": "Synthesize Strategy"},
            {"id": "code_forge", "type": "tool", "tool": "mockup_generate", "label": "Generate Mockup"},
            {"id": "self_audit", "type": "audit", "tool": "vision_audit", "label": "Vision Self-Audit"},
            {"id": "quality_gate", "type": "condition", "label": "Quality Gate", "conditions": [
                {"field": "quality_score", "op": ">=", "value": 85, "target": "complete"},
                {"field": "iteration_count", "op": "<", "value": 3, "target": "code_forge"}
            ]},
            {"id": "complete", "type": "end", "label": "Complete"}
        ],
        "edges": [
            {"source": "brand_dna", "target": "strategy"},
            {"source": "strategy", "target": "code_forge"},
            {"source": "code_forge", "target": "self_audit"},
            {"source": "self_audit", "target": "quality_gate"},
            {"source": "quality_gate", "target": "complete", "label": "pass"},
            {"source": "quality_gate", "target": "code_forge", "label": "fail"}
        ],
        "entry": "brand_dna"
    }',
    true,
    true
)
ON CONFLICT DO NOTHING;


-- ======================
-- 10. DEFAULT PROMPT SEEDS
-- ======================

-- House Style: Modern Professional
INSERT INTO public.prompt_library (user_id, slug, name, category, prompt_text, priority, is_active)
VALUES (
    NULL,
    'modern-professional',
    'Modern Professional Style',
    'house_style',
    'Design Guidelines:
- Use generous whitespace (minimum 2rem between sections)
- Prefer subtle shadows over harsh borders
- Use a consistent 4px spacing scale
- Corner radius: 0.5rem for cards, 0.25rem for buttons
- Typography: Clear hierarchy with distinct heading sizes
- Colors: Use brand primary sparingly, mostly for CTAs
- Animations: Subtle fade-ins, no jarring movements
- Mobile-first: Stack gracefully, maintain touch targets',
    100,
    true
)
ON CONFLICT DO NOTHING;

-- Niche: SaaS
INSERT INTO public.prompt_library (user_id, slug, name, category, prompt_text, niche_tags, priority, is_active)
VALUES (
    NULL,
    'niche-saas',
    'SaaS Landing Page',
    'niche',
    'SaaS-Specific Guidelines:
- Hero: Clear value proposition in 8 words or less
- Social proof: Logos, testimonials, or user counts
- Features: 3-6 key features with icons
- Pricing: Highlight recommended tier
- CTA: Free trial or demo, not "Contact Us"
- Trust: Security badges, compliance logos
- FAQ: Address pricing and features questions',
    ARRAY['saas', 'software', 'startup'],
    200,
    true
)
ON CONFLICT DO NOTHING;

-- Niche: E-commerce
INSERT INTO public.prompt_library (user_id, slug, name, category, prompt_text, niche_tags, priority, is_active)
VALUES (
    NULL,
    'niche-ecommerce',
    'E-commerce Store',
    'niche',
    'E-commerce Guidelines:
- Hero: Seasonal/featured products with clear CTA
- Navigation: Categories clearly visible
- Products: High-quality images, prices visible
- Trust: Shipping info, returns policy, secure checkout
- Reviews: Product ratings visible
- Cart: Always accessible, show item count
- Mobile: Easy add-to-cart, quick checkout',
    ARRAY['ecommerce', 'retail', 'store', 'shop'],
    200,
    true
)
ON CONFLICT DO NOTHING;

-- Niche: Local Business
INSERT INTO public.prompt_library (user_id, slug, name, category, prompt_text, niche_tags, priority, is_active)
VALUES (
    NULL,
    'niche-local',
    'Local Business',
    'niche',
    'Local Business Guidelines:
- Hero: Service/product imagery with location
- Contact: Phone number highly visible, click-to-call
- Hours: Business hours in header or footer
- Map: Embedded Google Map with location
- Reviews: Google/Yelp reviews or testimonials
- Services: Clear list with brief descriptions
- CTA: "Call Now", "Get Directions", "Book Appointment"',
    ARRAY['local', 'restaurant', 'service', 'brick-and-mortar'],
    200,
    true
)
ON CONFLICT DO NOTHING;


-- ======================
-- MIGRATION COMPLETE
-- ======================
-- Run this migration with: psql -d your_database -f migrations/002_autonomous_production_forge.sql
