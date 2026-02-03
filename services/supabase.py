"""
Supabase client service for database and auth operations.
"""
from functools import lru_cache
from typing import Optional
from uuid import UUID

from supabase import create_client, Client
import structlog

from config import settings

logger = structlog.get_logger()


@lru_cache
def get_supabase_client() -> Client:
    """Get Supabase client with anon key (respects RLS)."""
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key
    )


@lru_cache
def get_supabase_admin_client() -> Client:
    """Get Supabase client with service role key (bypasses RLS)."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key
    )


class SupabaseService:
    """Service for Supabase database operations."""

    def __init__(self, client: Optional[Client] = None, use_admin: bool = False):
        if client:
            self.client = client
        elif use_admin:
            self.client = get_supabase_admin_client()
        else:
            self.client = get_supabase_client()

    # =====================
    # Profile Operations
    # =====================

    async def get_profile(self, user_id: UUID) -> Optional[dict]:
        """Get user profile by ID."""
        try:
            response = self.client.table("profiles").select("*").eq("id", str(user_id)).single().execute()
            return response.data
        except Exception as e:
            logger.error("Failed to get profile", user_id=str(user_id), error=str(e))
            return None

    async def update_profile(self, user_id: UUID, data: dict) -> Optional[dict]:
        """Update user profile."""
        try:
            response = self.client.table("profiles").update(data).eq("id", str(user_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("Failed to update profile", user_id=str(user_id), error=str(e))
            return None

    # =====================
    # Audit Operations
    # =====================

    async def create_audit(self, user_id: UUID, url: str, competitors: list[str] = None, options: dict = None) -> dict:
        """Create a new audit record."""
        data = {
            "user_id": str(user_id),
            "url": url,
            "status": "queued",
            "competitors": competitors or [],
            "options": options or {},
        }
        response = self.client.table("audits").insert(data).execute()
        return response.data[0]

    async def get_audit(self, audit_id: UUID, user_id: Optional[UUID] = None) -> Optional[dict]:
        """Get audit by ID, optionally filtered by user."""
        query = self.client.table("audits").select("*").eq("id", str(audit_id))
        if user_id:
            query = query.eq("user_id", str(user_id))
        try:
            response = query.single().execute()
            return response.data
        except Exception:
            return None

    async def list_audits(
        self,
        user_id: UUID,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[dict], int]:
        """List audits for a user with optional status filter."""
        query = self.client.table("audits").select("*", count="exact").eq("user_id", str(user_id))

        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()

        return response.data, response.count or 0

    async def update_audit(self, audit_id: UUID, data: dict) -> Optional[dict]:
        """Update audit record."""
        try:
            response = self.client.table("audits").update(data).eq("id", str(audit_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("Failed to update audit", audit_id=str(audit_id), error=str(e))
            return None

    async def update_audit_status(
        self,
        audit_id: UUID,
        status: str,
        error: Optional[str] = None
    ) -> Optional[dict]:
        """Update audit status with optional error message."""
        data = {"status": status}
        if status == "processing":
            data["started_at"] = "now()"
        elif status in ("completed", "failed"):
            data["completed_at"] = "now()"
        if error:
            data["error"] = error
        return await self.update_audit(audit_id, data)

    async def save_audit_results(
        self,
        audit_id: UUID,
        performance: dict,
        seo: dict,
        accessibility: dict,
        brand: dict,
        analysis: dict,
        screenshots: dict,
        tokens_used: int,
        cost_usd: float,
        processing_time_ms: int
    ) -> Optional[dict]:
        """Save completed audit results."""
        data = {
            "status": "completed",
            "performance": performance,
            "seo": seo,
            "accessibility": accessibility,
            "brand": brand,
            "analysis": analysis,
            "screenshots": screenshots,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "processing_time_ms": processing_time_ms,
            "completed_at": "now()",
        }
        return await self.update_audit(audit_id, data)

    # =====================
    # Webhook Operations
    # =====================

    async def create_webhook(self, user_id: UUID, url: str, events: list[str], secret: Optional[str] = None) -> dict:
        """Create a new webhook."""
        data = {
            "user_id": str(user_id),
            "url": url,
            "events": events,
            "secret": secret,
        }
        response = self.client.table("webhooks").insert(data).execute()
        return response.data[0]

    async def list_webhooks(self, user_id: UUID) -> list[dict]:
        """List all webhooks for a user."""
        response = self.client.table("webhooks").select("*").eq("user_id", str(user_id)).execute()
        return response.data

    async def get_webhooks_for_event(self, user_id: UUID, event: str) -> list[dict]:
        """Get active webhooks for a specific event."""
        response = (
            self.client.table("webhooks")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("active", True)
            .contains("events", [event])
            .execute()
        )
        return response.data

    async def delete_webhook(self, webhook_id: UUID, user_id: UUID) -> bool:
        """Delete a webhook."""
        try:
            self.client.table("webhooks").delete().eq("id", str(webhook_id)).eq("user_id", str(user_id)).execute()
            return True
        except Exception:
            return False

    # =====================
    # Storage Operations
    # =====================

    async def upload_screenshot(self, audit_id: UUID, image_data: bytes, filename: str) -> str:
        """Upload screenshot to Supabase Storage."""
        path = f"{audit_id}/{filename}"
        self.client.storage.from_("audit-screenshots").upload(path, image_data, {"content-type": "image/png"})
        return self.client.storage.from_("audit-screenshots").get_public_url(path)

    async def upload_report(self, audit_id: UUID, report_data: bytes, filename: str) -> str:
        """Upload report to Supabase Storage."""
        path = f"{audit_id}/{filename}"
        content_type = "application/pdf" if filename.endswith(".pdf") else "application/json"
        self.client.storage.from_("audit-reports").upload(path, report_data, {"content-type": content_type})
        return self.client.storage.from_("audit-reports").create_signed_url(path, 3600)["signedURL"]

    # =====================================================
    # AgOS: Agent Registry Operations
    # =====================================================

    async def get_agent_by_slug(self, slug: str) -> Optional[dict]:
        """Get agent configuration by slug."""
        try:
            response = self.client.table("agents").select("*").eq("slug", slug).eq("is_active", True).single().execute()
            return response.data
        except Exception as e:
            logger.error("Failed to get agent", slug=slug, error=str(e))
            return None

    async def list_agents(self, room: Optional[str] = None) -> list[dict]:
        """List all active agents, optionally filtered by room."""
        query = self.client.table("agents").select("*").eq("is_active", True)
        if room:
            query = query.eq("room", room)
        response = query.execute()
        return response.data

    # =====================================================
    # AgOS: Playbook Operations
    # =====================================================

    async def get_playbook_by_slug(self, slug: str) -> Optional[dict]:
        """Get playbook by slug."""
        try:
            response = self.client.table("playbooks").select("*").eq("slug", slug).eq("is_active", True).single().execute()
            return response.data
        except Exception as e:
            logger.error("Failed to get playbook", slug=slug, error=str(e))
            return None

    async def get_playbook_by_id(self, playbook_id: UUID) -> Optional[dict]:
        """Get playbook by ID."""
        try:
            response = self.client.table("playbooks").select("*").eq("id", str(playbook_id)).single().execute()
            return response.data
        except Exception:
            return None

    async def get_default_playbook(self, room: str) -> Optional[dict]:
        """Get default playbook for a room."""
        try:
            response = (
                self.client.table("playbooks")
                .select("*")
                .eq("room", room)
                .eq("is_default", True)
                .eq("is_active", True)
                .single()
                .execute()
            )
            return response.data
        except Exception:
            return None

    async def list_playbooks(self, room: Optional[str] = None) -> list[dict]:
        """List all active playbooks, optionally filtered by room."""
        query = self.client.table("playbooks").select("*").eq("is_active", True)
        if room:
            query = query.eq("room", room)
        response = query.order("priority", desc=False).execute()
        return response.data

    # =====================================================
    # AgOS: Lead Pipeline Operations
    # =====================================================

    async def create_lead(
        self,
        url: str,
        user_id: Optional[UUID] = None,
        source: str = "api",
        batch_id: Optional[UUID] = None,
        metadata: Optional[dict] = None
    ) -> dict:
        """Create a new lead."""
        data = {
            "url": url,
            "source": source,
            "status": "new",
            "metadata": metadata or {}
        }
        if user_id:
            data["user_id"] = str(user_id)
        if batch_id:
            data["batch_id"] = str(batch_id)

        response = self.client.table("leads").insert(data).execute()
        return response.data[0]

    async def get_lead(self, lead_id: UUID) -> Optional[dict]:
        """Get lead by ID."""
        try:
            response = self.client.table("leads").select("*").eq("id", str(lead_id)).single().execute()
            return response.data
        except Exception:
            return None

    async def list_leads(
        self,
        user_id: Optional[UUID] = None,
        status: Optional[str] = None,
        current_room: Optional[str] = None,
        batch_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[list[dict], int]:
        """List leads with optional filters."""
        query = self.client.table("leads").select("*", count="exact")

        if user_id:
            query = query.eq("user_id", str(user_id))
        if status:
            query = query.eq("status", status)
        if current_room:
            query = query.eq("current_room", current_room)
        if batch_id:
            query = query.eq("batch_id", str(batch_id))

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()

        return response.data, response.count or 0

    async def update_lead(self, lead_id: UUID, data: dict) -> Optional[dict]:
        """Update lead record."""
        try:
            response = self.client.table("leads").update(data).eq("id", str(lead_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("Failed to update lead", lead_id=str(lead_id), error=str(e))
            return None

    async def update_lead_status(
        self,
        lead_id: UUID,
        status: str,
        current_room: Optional[str] = None
    ) -> Optional[dict]:
        """Update lead status and optionally room."""
        data = {"status": status}
        if current_room:
            data["current_room"] = current_room
        return await self.update_lead(lead_id, data)

    async def delete_lead(self, lead_id: UUID) -> bool:
        """Delete a lead."""
        try:
            self.client.table("leads").delete().eq("id", str(lead_id)).execute()
            return True
        except Exception:
            return False

    # =====================================================
    # AgOS: Lead Batch Operations
    # =====================================================

    async def create_lead_batch(
        self,
        user_id: UUID,
        name: str,
        source: str = "csv",
        total_count: int = 0,
        playbook_id: Optional[UUID] = None,
        options: Optional[dict] = None
    ) -> dict:
        """Create a new lead batch."""
        data = {
            "user_id": str(user_id),
            "name": name,
            "source": source,
            "total_count": total_count,
            "status": "pending",
            "options": options or {}
        }
        if playbook_id:
            data["playbook_id"] = str(playbook_id)

        response = self.client.table("lead_batches").insert(data).execute()
        return response.data[0]

    async def get_lead_batch(self, batch_id: UUID) -> Optional[dict]:
        """Get batch by ID."""
        try:
            response = self.client.table("lead_batches").select("*").eq("id", str(batch_id)).single().execute()
            return response.data
        except Exception:
            return None

    async def update_lead_batch(self, batch_id: UUID, data: dict) -> Optional[dict]:
        """Update batch record."""
        try:
            response = self.client.table("lead_batches").update(data).eq("id", str(batch_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("Failed to update batch", batch_id=str(batch_id), error=str(e))
            return None

    async def list_lead_batches(
        self,
        user_id: UUID,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[dict], int]:
        """List batches for a user."""
        query = self.client.table("lead_batches").select("*", count="exact").eq("user_id", str(user_id))

        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()

        return response.data, response.count or 0

    # =====================================================
    # AgOS: Agent Run Operations (Observability)
    # =====================================================

    async def create_agent_run(
        self,
        run_id: UUID,
        agent_id: UUID,
        room: str,
        input_data: dict,
        status: str = "pending",
        lead_id: Optional[UUID] = None,
        audit_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        playbook_id: Optional[UUID] = None,
        batch_id: Optional[UUID] = None,
        trigger: str = "queue",
        started_at: Optional[str] = None
    ) -> dict:
        """Create an agent run record."""
        data = {
            "id": str(run_id),
            "agent_id": str(agent_id),
            "room": room,
            "input_data": input_data,
            "status": status,
            "trigger": trigger
        }
        if lead_id:
            data["lead_id"] = str(lead_id)
        if audit_id:
            data["audit_id"] = str(audit_id)
        if user_id:
            data["user_id"] = str(user_id)
        if playbook_id:
            data["playbook_id"] = str(playbook_id)
        if batch_id:
            data["batch_id"] = str(batch_id)
        if started_at:
            data["started_at"] = started_at.isoformat() if hasattr(started_at, 'isoformat') else started_at

        response = self.client.table("agent_runs").insert(data).execute()
        return response.data[0]

    async def update_agent_run(
        self,
        run_id: UUID,
        status: str,
        output_data: Optional[dict] = None,
        error: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        tools_called: Optional[list] = None,
        mcp_calls: Optional[list] = None,
        completed_at: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> Optional[dict]:
        """Update an agent run record."""
        data = {
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd
        }
        if output_data:
            data["output_data"] = output_data
        if error:
            data["error"] = error
        if tools_called:
            data["tools_called"] = tools_called
        if mcp_calls:
            data["mcp_calls"] = mcp_calls
        if completed_at:
            data["completed_at"] = completed_at.isoformat() if hasattr(completed_at, 'isoformat') else completed_at
        if duration_ms:
            data["duration_ms"] = duration_ms

        try:
            response = self.client.table("agent_runs").update(data).eq("id", str(run_id)).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error("Failed to update agent_run", run_id=str(run_id), error=str(e))
            return None

    async def get_agent_run(self, run_id: UUID) -> Optional[dict]:
        """Get agent run by ID."""
        try:
            response = self.client.table("agent_runs").select("*").eq("id", str(run_id)).single().execute()
            return response.data
        except Exception:
            return None

    async def list_agent_runs(
        self,
        lead_id: Optional[UUID] = None,
        agent_id: Optional[UUID] = None,
        room: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[list[dict], int]:
        """List agent runs with optional filters."""
        query = self.client.table("agent_runs").select("*", count="exact")

        if lead_id:
            query = query.eq("lead_id", str(lead_id))
        if agent_id:
            query = query.eq("agent_id", str(agent_id))
        if room:
            query = query.eq("room", room)
        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()

        return response.data, response.count or 0
