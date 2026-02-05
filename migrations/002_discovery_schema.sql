-- =====================================================
-- Room 3 (Discovery) Schema Migration
-- Autonomous Closing Engine tables and seed data
-- =====================================================

-- =====================================================
-- DISCOVERY NEGOTIATIONS TABLE
-- Stateful negotiation context per lead (one-to-one)
-- =====================================================
CREATE TABLE public.discovery_negotiations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID NOT NULL UNIQUE REFERENCES public.leads(id) ON DELETE CASCADE,

    -- Pricing State
    base_price DECIMAL(10,2) NOT NULL,
    current_price DECIMAL(10,2) NOT NULL,
    min_acceptable_price DECIMAL(10,2) NOT NULL,
    max_discount_pct DECIMAL(5,2) NOT NULL DEFAULT 15.0,

    -- Negotiation State Machine
    negotiation_state TEXT DEFAULT 'initial' CHECK (negotiation_state IN (
        'initial',
        'proposal_sent',
        'prospect_engaged',
        'objection_handling',
        'counter_offer',
        'final_offer',
        'accepted',
        'paid',
        'rejected'
    )),

    -- SDR Follow-up State Machine
    sdr_state TEXT DEFAULT 'initial_outreach' CHECK (sdr_state IN (
        'initial_outreach',
        'follow_up_1',
        'follow_up_2',
        'channel_pivot',
        'escalation',
        'cooling_off',
        're_engagement',
        'completed'
    )),

    -- Engagement Counters
    total_touches INT DEFAULT 0,
    emails_sent INT DEFAULT 0,
    sms_sent INT DEFAULT 0,

    -- Timing
    last_contact_at TIMESTAMPTZ,
    last_prospect_action_at TIMESTAMPTZ,
    next_action_at TIMESTAMPTZ,

    -- Deal Intelligence
    objections JSONB DEFAULT '[]',
    upsells_offered JSONB DEFAULT '[]',
    discount_history JSONB DEFAULT '[]',

    -- Stripe
    stripe_checkout_session_id TEXT,
    stripe_payment_intent_id TEXT,
    stripe_customer_id TEXT,

    -- Contract
    contract_pdf_url TEXT,
    contract_signed_at TIMESTAMPTZ,

    -- Outcome
    close_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_discovery_negotiations_lead_id ON public.discovery_negotiations(lead_id);
CREATE INDEX idx_discovery_negotiations_state ON public.discovery_negotiations(negotiation_state);
CREATE INDEX idx_discovery_negotiations_sdr ON public.discovery_negotiations(sdr_state);
CREATE INDEX idx_discovery_negotiations_next_action ON public.discovery_negotiations(next_action_at)
    WHERE next_action_at IS NOT NULL AND sdr_state != 'completed';

-- RLS
ALTER TABLE public.discovery_negotiations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view negotiations for own leads"
    ON public.discovery_negotiations FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.leads
            WHERE leads.id = discovery_negotiations.lead_id
            AND (leads.user_id = auth.uid() OR leads.assigned_to = auth.uid())
        )
    );

CREATE POLICY "Service role full access to negotiations"
    ON public.discovery_negotiations FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);

-- Auto-update updated_at trigger
CREATE TRIGGER discovery_negotiations_updated_at
    BEFORE UPDATE ON public.discovery_negotiations
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


-- =====================================================
-- DISCOVERY INTERACTIONS TABLE
-- Event log for all SDR loop communications
-- =====================================================
CREATE TABLE public.discovery_interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
    agent_run_id UUID REFERENCES public.agent_runs(id) ON DELETE SET NULL,

    -- Interaction Details
    interaction_type TEXT NOT NULL CHECK (interaction_type IN (
        'email_sent',
        'email_opened',
        'email_replied',
        'email_bounced',
        'sms_sent',
        'sms_replied',
        'proposal_viewed',
        'proposal_downloaded',
        'mockup_interaction',
        'checkout_started',
        'checkout_completed',
        'checkout_abandoned',
        'meeting_requested',
        'objection_raised',
        'counter_offer',
        'manual_note'
    )),

    -- Communication Channel
    channel TEXT CHECK (channel IN ('email', 'sms', 'webhook', 'manual', 'tracking')),

    -- Content
    subject TEXT,
    body_preview TEXT,
    template_slug TEXT,

    -- Response Data
    response_data JSONB DEFAULT '{}',

    -- Pricing Context
    offered_price DECIMAL(10,2),
    discount_applied DECIMAL(5,2),

    -- Metadata
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_discovery_interactions_lead_id ON public.discovery_interactions(lead_id);
CREATE INDEX idx_discovery_interactions_type ON public.discovery_interactions(interaction_type);
CREATE INDEX idx_discovery_interactions_created_at ON public.discovery_interactions(created_at DESC);
CREATE INDEX idx_discovery_interactions_channel ON public.discovery_interactions(channel);

-- RLS
ALTER TABLE public.discovery_interactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view interactions for own leads"
    ON public.discovery_interactions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.leads
            WHERE leads.id = discovery_interactions.lead_id
            AND (leads.user_id = auth.uid() OR leads.assigned_to = auth.uid())
        )
    );

CREATE POLICY "Service role full access to interactions"
    ON public.discovery_interactions FOR ALL
    TO service_role
    USING (true) WITH CHECK (true);


-- =====================================================
-- SEED DATA: Discovery Agent
-- =====================================================
INSERT INTO public.agents (slug, name, room, system_prompt, tools, mcp_servers, temperature, max_tokens, timeout_seconds, retry_attempts) VALUES
(
    'discovery',
    'Discovery Agent',
    'discovery',
    'You are the Sentinel Discovery Agent — an autonomous deal closer. You have full memory of triage signals (Room 1) and design decisions (Room 2). Your job is to present proposals, handle objections, negotiate pricing within defined margins, and close deals. Always defend the proposed solution using data from prior rooms. Never offer discounts below the minimum acceptable price. Be professional but persuasive. Use engagement data from VLM analysis to personalize your outreach.',
    ARRAY['calculate_price', 'generate_proposal', 'generate_contract', 'create_checkout', 'send_email', 'send_sms', 'load_memory', 'negotiate', 'analyze_mockup_engagement'],
    ARRAY[]::TEXT[],
    0.4,
    2048,
    300,
    3
);


-- =====================================================
-- SEED DATA: Discovery Playbook
-- =====================================================
INSERT INTO public.playbooks (slug, name, room, config, is_default, is_active, industry_tags) VALUES
(
    'discovery-standard',
    'Standard Discovery Playbook',
    'discovery',
    '{
        "version": "1.0",
        "pricing_rules": {
            "base_prices": {
                "landing_page": 2500,
                "small_business": 5000,
                "ecommerce": 8000,
                "saas": 12000,
                "enterprise": 25000
            },
            "signal_multipliers": {
                "pagespeed_below_30": 1.2,
                "pagespeed_below_50": 1.1,
                "no_ssl": 1.1,
                "no_mobile": 1.15,
                "outdated_3plus_years": 1.1,
                "outdated_5plus_years": 1.2
            },
            "industry_multipliers": {
                "default": 1.0,
                "legal": 1.3,
                "medical": 1.3,
                "saas": 1.2,
                "ecommerce": 1.15,
                "restaurant": 0.9,
                "nonprofit": 0.8
            },
            "margin_rules": {
                "max_discount_pct": 15,
                "min_margin_pct": 40,
                "auto_discount_threshold_days": 5,
                "auto_discount_pct": 5,
                "urgency_premium_pct": 10
            },
            "upsells": {
                "seo_package": {"price": 1500, "trigger": "seo_score_below_50"},
                "monthly_maintenance": {"price": 500, "trigger": "always"},
                "content_writing": {"price": 2000, "trigger": "thin_content"},
                "analytics_setup": {"price": 800, "trigger": "no_analytics"}
            }
        },
        "sdr_loop": {
            "max_touches": 7,
            "channels": ["email", "sms"],
            "timing": {
                "initial_to_follow_up_1": "48h",
                "follow_up_1_to_follow_up_2": "72h",
                "follow_up_2_to_channel_pivot": "48h",
                "channel_pivot_to_escalation": "96h",
                "cooling_off_duration": "168h"
            },
            "templates": {
                "initial_outreach": "initial_proposal",
                "follow_up_1": "follow_up",
                "follow_up_2": "follow_up_urgency",
                "channel_pivot": "sms_check_in",
                "re_engagement": "re_engagement_offer"
            },
            "auto_close_lost_after_touches": 7,
            "escalation_triggers": ["meeting_requested", "objection_raised"],
            "engagement_signals": ["email_opened", "proposal_viewed", "email_replied", "mockup_interaction"]
        },
        "proposal": {
            "template": "modern-professional",
            "include_mockup_preview": true,
            "include_pricing_breakdown": true,
            "include_testimonials": false
        },
        "contract": {
            "template": "standard-web-services",
            "payment_terms": "50% upfront, 50% on delivery",
            "delivery_timeline": "4-6 weeks",
            "revision_rounds": 3
        },
        "vlm": {
            "enabled": true,
            "screenshot_intervals_seconds": [0, 30, 60],
            "track_scroll_depth": true,
            "track_click_heatmap": true
        }
    }',
    true,
    true,
    ARRAY['saas', 'ecommerce', 'local-business', 'professional-services']
);
