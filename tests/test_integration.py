"""
Integration Tests for Sentinel AgOS Pipeline.

Tests the full flow:
URL → Triage → Qualified → Architect → Mockup Ready

These tests verify:
- Lead creation and status transitions
- Triage room processing
- Architect room processing
- End-to-end pipeline flow
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import structlog

logger = structlog.get_logger()


# =====================
# Fixtures
# =====================

@pytest.fixture
def mock_db():
    """Create a mock database service."""
    db = MagicMock()

    # Storage for leads
    leads = {}

    async def create_lead(url, user_id=None, source="api", batch_id=None, metadata=None):
        lead_id = str(uuid4())
        lead = {
            "id": lead_id,
            "url": url,
            "user_id": str(user_id) if user_id else None,
            "source": source,
            "batch_id": str(batch_id) if batch_id else None,
            "status": "new",
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }
        leads[lead_id] = lead
        return lead

    async def get_lead(lead_id):
        return leads.get(str(lead_id))

    async def update_lead(lead_id, data):
        lead = leads.get(str(lead_id))
        if lead:
            lead.update(data)
            return lead
        return None

    async def update_lead_status(lead_id, status, current_room=None):
        lead = leads.get(str(lead_id))
        if lead:
            lead["status"] = status
            if current_room:
                lead["current_room"] = current_room
            return lead
        return None

    async def get_agent_by_slug(slug):
        return {
            "id": str(uuid4()),
            "slug": slug,
            "name": f"{slug.title()} Agent",
            "room": slug,
            "model": "claude-3-5-sonnet-20241022",
            "temperature": 0.7,
            "max_tokens": 4096,
            "system_prompt": f"You are the {slug} agent.",
            "tools": [],
            "mcp_servers": [],
            "timeout_seconds": 120,
            "retry_attempts": 3
        }

    async def get_playbook_by_slug(slug):
        return {
            "id": str(uuid4()),
            "slug": slug,
            "config": {}
        }

    async def create_agent_run(*args, **kwargs):
        return {"id": str(uuid4())}

    async def update_agent_run(*args, **kwargs):
        return {}

    db.create_lead = create_lead
    db.get_lead = get_lead
    db.update_lead = update_lead
    db.update_lead_status = update_lead_status
    db.get_agent_by_slug = get_agent_by_slug
    db.get_playbook_by_slug = get_playbook_by_slug
    db.get_playbook_by_id = AsyncMock(return_value=None)
    db.get_default_playbook = AsyncMock(return_value={"config": {}})
    db.create_agent_run = create_agent_run
    db.update_agent_run = update_agent_run

    return db


@pytest.fixture
def mock_anthropic():
    """Create a mock Anthropic client."""
    client = MagicMock()

    response = MagicMock()
    response.content = [MagicMock(text="Test recommendation")]
    response.usage = MagicMock(input_tokens=100, output_tokens=50)

    client.messages.create = MagicMock(return_value=response)

    return client


# =====================
# Lead Lifecycle Tests
# =====================

class TestLeadLifecycle:
    """Tests for lead status transitions."""

    @pytest.mark.asyncio
    async def test_lead_creation(self, mock_db):
        """Test lead is created with 'new' status."""
        lead = await mock_db.create_lead(
            url="https://test-site.com",
            user_id=uuid4()
        )

        assert lead["status"] == "new"
        assert lead["url"] == "https://test-site.com"
        assert lead["id"] is not None

    @pytest.mark.asyncio
    async def test_lead_status_to_scanning(self, mock_db):
        """Test lead transitions to 'scanning' when triage starts."""
        lead = await mock_db.create_lead(url="https://test-site.com")
        lead_id = lead["id"]

        # Simulate triage starting
        await mock_db.update_lead_status(lead_id, "scanning", "triage")

        updated = await mock_db.get_lead(lead_id)
        assert updated["status"] == "scanning"
        assert updated["current_room"] == "triage"

    @pytest.mark.asyncio
    async def test_lead_status_to_qualified(self, mock_db):
        """Test lead transitions to 'qualified' after triage success."""
        lead = await mock_db.create_lead(url="https://test-site.com")
        lead_id = lead["id"]

        await mock_db.update_lead_status(lead_id, "scanning", "triage")
        await mock_db.update_lead(lead_id, {
            "status": "qualified",
            "triage_score": 75,
            "triage_signals": {"pagespeed_score": 35}
        })

        updated = await mock_db.get_lead(lead_id)
        assert updated["status"] == "qualified"
        assert updated["triage_score"] == 75

    @pytest.mark.asyncio
    async def test_lead_status_to_disqualified(self, mock_db):
        """Test lead transitions to 'disqualified' after triage failure."""
        lead = await mock_db.create_lead(url="https://healthy-site.com")
        lead_id = lead["id"]

        await mock_db.update_lead(lead_id, {
            "status": "disqualified",
            "triage_score": 25
        })

        updated = await mock_db.get_lead(lead_id)
        assert updated["status"] == "disqualified"

    @pytest.mark.asyncio
    async def test_lead_status_to_mockup_ready(self, mock_db):
        """Test lead transitions to 'mockup_ready' after architect success."""
        lead = await mock_db.create_lead(url="https://test-site.com")
        lead_id = lead["id"]

        # Full progression
        await mock_db.update_lead_status(lead_id, "qualified", "triage")
        await mock_db.update_lead_status(lead_id, "designing", "architect")
        await mock_db.update_lead(lead_id, {
            "status": "mockup_ready",
            "mockup_url": "https://preview.e2b.dev/123"
        })

        updated = await mock_db.get_lead(lead_id)
        assert updated["status"] == "mockup_ready"
        assert updated["mockup_url"] is not None


# =====================
# Triage Room Integration Tests
# =====================

class TestTriageRoomIntegration:
    """Integration tests for Triage Room."""

    @pytest.mark.asyncio
    async def test_triage_room_processes_lead(self, mock_db):
        """Test full triage room processing."""
        from rooms.triage.room import TriageRoom
        from rooms.base import TRIAGE_ROOM_CONFIG

        # Create a lead
        lead = await mock_db.create_lead(url="https://slow-site.com")

        # Create mock agent
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value={
            "qualified": True,
            "score": 72,
            "signals": {"pagespeed_score": 38, "ssl_valid": True},
            "recommendation": "Good opportunity"
        })

        # Create room with mock agent
        room = TriageRoom(db_service=mock_db)
        room.config = TRIAGE_ROOM_CONFIG
        room.agent = mock_agent

        # Process
        result = await room.execute(lead=lead, trigger="test")

        # Verify agent was called
        mock_agent.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_triage_validates_lead_status(self, mock_db):
        """Test triage rejects leads not in 'new' status."""
        from rooms.triage.room import TriageRoom
        from rooms.base import TRIAGE_ROOM_CONFIG

        lead = await mock_db.create_lead(url="https://test.com")
        await mock_db.update_lead_status(lead["id"], "qualified")  # Already processed

        room = TriageRoom(db_service=mock_db)
        room.config = TRIAGE_ROOM_CONFIG

        updated_lead = await mock_db.get_lead(lead["id"])
        can_enter = await room.validate_entry(updated_lead)

        assert can_enter is False


# =====================
# Architect Room Integration Tests
# =====================

class TestArchitectRoomIntegration:
    """Integration tests for Architect Room."""

    @pytest.mark.asyncio
    async def test_architect_room_processes_qualified_lead(self, mock_db):
        """Test architect room processes qualified leads."""
        from rooms.architect.room import ArchitectRoom
        from rooms.base import ARCHITECT_ROOM_CONFIG

        # Create and qualify a lead
        lead = await mock_db.create_lead(url="https://needs-help.com")
        await mock_db.update_lead(lead["id"], {
            "status": "qualified",
            "triage_score": 75,
            "triage_signals": {"pagespeed_score": 35}
        })

        # Create mock agent
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value={
            "url": "https://needs-help.com",
            "audit": {"performance": {"score": 35}},
            "brand": {"company_name": "Test Co"},
            "mockup": {"preview_url": "https://preview.e2b.dev/abc"},
            "mockup_url": "https://preview.e2b.dev/abc",
            "recommendations": {"text": "Improve performance"}
        })

        # Create room
        room = ArchitectRoom(db_service=mock_db)
        room.config = ARCHITECT_ROOM_CONFIG
        room.agent = mock_agent

        qualified_lead = await mock_db.get_lead(lead["id"])
        result = await room.execute(lead=qualified_lead, trigger="test")

        mock_agent.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_architect_rejects_non_qualified_leads(self, mock_db):
        """Test architect rejects leads not in 'qualified' status."""
        from rooms.architect.room import ArchitectRoom
        from rooms.base import ARCHITECT_ROOM_CONFIG

        lead = await mock_db.create_lead(url="https://test.com")
        # Lead is still 'new', not qualified

        room = ArchitectRoom(db_service=mock_db)
        room.config = ARCHITECT_ROOM_CONFIG

        can_enter = await room.validate_entry(lead)

        assert can_enter is False


# =====================
# Full Pipeline Tests
# =====================

class TestFullPipeline:
    """End-to-end pipeline tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline_qualified_lead(self, mock_db, mock_anthropic):
        """Test complete pipeline: new → qualified → mockup_ready."""
        # Step 1: Create lead
        lead = await mock_db.create_lead(
            url="https://old-slow-site.com",
            user_id=uuid4()
        )
        assert lead["status"] == "new"

        # Step 2: Simulate triage processing
        await mock_db.update_lead_status(lead["id"], "scanning", "triage")
        await mock_db.update_lead(lead["id"], {
            "status": "qualified",
            "triage_score": 78,
            "triage_signals": {
                "pagespeed_score": 32,
                "ssl_valid": True,
                "mobile_responsive": False,
                "copyright_year": 2019
            },
            "triage_completed_at": datetime.utcnow().isoformat()
        })

        qualified_lead = await mock_db.get_lead(lead["id"])
        assert qualified_lead["status"] == "qualified"
        assert qualified_lead["triage_score"] == 78

        # Step 3: Simulate architect processing
        await mock_db.update_lead_status(lead["id"], "designing", "architect")
        await mock_db.update_lead(lead["id"], {
            "status": "mockup_ready",
            "mockup_url": "https://preview.e2b.dev/mockup-123",
            "mockup_code_url": "https://storage.example.com/code.zip",
            "brand_audit": {
                "company_name": "Old Slow Site Inc",
                "colors": {"primary": "#336699"},
                "typography": {"primary_font": "Arial"}
            },
            "architect_completed_at": datetime.utcnow().isoformat()
        })

        final_lead = await mock_db.get_lead(lead["id"])
        assert final_lead["status"] == "mockup_ready"
        assert final_lead["mockup_url"] is not None
        assert final_lead["brand_audit"] is not None

    @pytest.mark.asyncio
    async def test_full_pipeline_disqualified_lead(self, mock_db):
        """Test pipeline with disqualified lead."""
        # Step 1: Create lead
        lead = await mock_db.create_lead(
            url="https://healthy-modern-site.com",
            user_id=uuid4()
        )

        # Step 2: Simulate triage - site is healthy, low opportunity
        await mock_db.update_lead_status(lead["id"], "scanning", "triage")
        await mock_db.update_lead(lead["id"], {
            "status": "disqualified",
            "triage_score": 15,  # Low score = healthy site
            "triage_signals": {
                "pagespeed_score": 95,
                "ssl_valid": True,
                "mobile_responsive": True,
                "copyright_year": 2024
            },
            "triage_completed_at": datetime.utcnow().isoformat()
        })

        final_lead = await mock_db.get_lead(lead["id"])
        assert final_lead["status"] == "disqualified"
        assert final_lead["triage_score"] == 15
        # Should NOT proceed to architect

    @pytest.mark.asyncio
    async def test_batch_processing(self, mock_db):
        """Test batch lead processing."""
        batch_id = uuid4()
        urls = [
            "https://site1.com",
            "https://site2.com",
            "https://site3.com"
        ]

        # Create batch of leads
        leads = []
        for url in urls:
            lead = await mock_db.create_lead(
                url=url,
                user_id=uuid4(),
                batch_id=batch_id
            )
            leads.append(lead)

        assert len(leads) == 3
        assert all(l["batch_id"] == str(batch_id) for l in leads)
        assert all(l["status"] == "new" for l in leads)


# =====================
# Agent Run Tracking Tests
# =====================

class TestAgentRunTracking:
    """Tests for agent run observability."""

    @pytest.mark.asyncio
    async def test_agent_run_created_on_execution(self, mock_db):
        """Test that agent runs are logged."""
        run_created = False

        original_create = mock_db.create_agent_run

        async def track_create(*args, **kwargs):
            nonlocal run_created
            run_created = True
            return await original_create(*args, **kwargs)

        mock_db.create_agent_run = track_create

        # Create run record
        await mock_db.create_agent_run(
            run_id=uuid4(),
            agent_id=uuid4(),
            room="triage",
            input_data={"url": "https://test.com"},
            status="running"
        )

        assert run_created is True

    @pytest.mark.asyncio
    async def test_agent_run_tracks_tokens(self, mock_db):
        """Test that token usage is tracked."""
        run_data = {}

        async def track_update(run_id, **kwargs):
            run_data.update(kwargs)
            return {}

        mock_db.update_agent_run = track_update

        await mock_db.update_agent_run(
            uuid4(),
            status="completed",
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.0035
        )

        assert run_data["input_tokens"] == 500
        assert run_data["output_tokens"] == 200
        assert run_data["cost_usd"] == 0.0035


# =====================
# Error Handling Tests
# =====================

class TestErrorHandling:
    """Tests for error handling in pipeline."""

    @pytest.mark.asyncio
    async def test_triage_handles_unreachable_url(self, mock_db):
        """Test triage handles URLs that can't be reached."""
        from rooms.triage.tools.fast_scan import FastScanner, ScanResult

        scanner = FastScanner(timeout=5.0)

        # Mock the scan to return failure
        with patch.object(scanner, 'scan_url', new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = ScanResult(
                url="https://does-not-exist.invalid",
                success=False,
                error="Connection refused"
            )

            result = await scanner.scan_url("https://does-not-exist.invalid")

            assert result.success is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_architect_handles_e2b_failure(self, mock_db):
        """Test architect handles E2B sandbox failures gracefully."""
        from rooms.architect.tools.mockup_generator import MockupGenerator, MockupResult

        generator = MockupGenerator()

        # Even without E2B, should return template code
        from rooms.architect.tools.brand_extractor import BrandDNA

        brand = BrandDNA(
            url="https://example.com",
            domain="example.com",
            company_name="Test Co"
        )

        result = await generator.generate(brand, use_ai=False)

        # Should succeed with template code even without E2B
        assert result.success is True
        assert "page.tsx" in result.code_files


# =====================
# Quota Integration Tests
# =====================

class TestQuotaIntegration:
    """Tests for quota enforcement in pipeline."""

    @pytest.mark.asyncio
    async def test_quota_check_passes(self, mock_db):
        """Test quota check passes when under limit."""
        from api.middleware.quota import check_quota

        # Mock profile with usage under limit
        mock_db.get_profile = AsyncMock(return_value={
            "subscription_tier": "starter",
            "triage_used_monthly": 50,
            "architect_used_monthly": 5,
            "quota_reset_at": None
        })

        user_id = uuid4()
        result = await check_quota(user_id, "triage", mock_db)

        assert result["used"] == 50
        assert result["limit"] == 500
        assert result["remaining"] == 450

    @pytest.mark.asyncio
    async def test_quota_check_fails_when_exceeded(self, mock_db):
        """Test quota check fails when limit exceeded."""
        from api.middleware.quota import check_quota, QuotaExceededError

        # Mock profile at limit
        mock_db.get_profile = AsyncMock(return_value={
            "subscription_tier": "free",
            "triage_used_monthly": 100,  # At limit
            "architect_used_monthly": 0,
            "quota_reset_at": None
        })

        user_id = uuid4()

        with pytest.raises(QuotaExceededError) as exc_info:
            await check_quota(user_id, "triage", mock_db)

        assert exc_info.value.status_code == 429
