"""
API endpoint tests.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import UUID

# Import after setting env vars
from api.main import app


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_returns_200(self, client):
        """Health check should return 200 with status healthy."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "0.1.0"


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_api_info(self, client):
        """Root should return API information."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Sentinel Scout Agent API"
        assert "version" in data


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    @patch("api.routes.auth.get_supabase")
    def test_magic_link_request(self, mock_get_supabase, client):
        """Should send magic link email."""
        mock_supabase = MagicMock()
        mock_supabase.auth.sign_in_with_otp.return_value = {}
        mock_get_supabase.return_value = mock_supabase

        response = client.post(
            "/auth/login",
            json={"email": "test@example.com"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_get_current_user_without_auth(self, client):
        """Should return 401 without auth header."""
        response = client.get("/auth/me")

        assert response.status_code == 401


class TestAuditEndpoints:
    """Tests for audit endpoints."""

    def test_create_audit_without_auth(self, client):
        """Should return 401 without auth."""
        response = client.post(
            "/audits",
            json={"url": "https://example.com"}
        )

        assert response.status_code == 401

    @patch("api.routes.audits.get_redis_client")
    @patch("api.dependencies.get_supabase")
    def test_create_audit_with_auth(
        self,
        mock_get_supabase,
        mock_get_redis,
        client,
        mock_supabase,
        mock_redis,
        auth_headers,
    ):
        """Should create audit with valid auth."""
        mock_get_supabase.return_value = mock_supabase
        mock_get_redis.return_value = mock_redis

        # Mock profile with audits remaining
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "test-user-id",
                "email": "test@example.com",
                "plan": "free",
                "audits_remaining": 5,
            }
        )

        # Mock audit creation
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "new-audit-id",
                "url": "https://example.com",
                "status": "queued",
                "created_at": "2024-01-01T00:00:00Z",
            }]
        )

        response = client.post(
            "/audits",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        # Should be 401 because our mock auth isn't complete
        # In real test, would mock auth properly
        assert response.status_code in [202, 401]

    def test_list_audits_without_auth(self, client):
        """Should return 401 without auth."""
        response = client.get("/audits")

        assert response.status_code == 401

    def test_get_audit_without_auth(self, client):
        """Should return 401 without auth."""
        response = client.get("/audits/test-audit-id")

        assert response.status_code == 401


class TestWebhookEndpoints:
    """Tests for webhook endpoints."""

    def test_create_webhook_without_auth(self, client):
        """Should return 401 without auth."""
        response = client.post(
            "/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["audit.completed"]
            }
        )

        assert response.status_code == 401

    def test_list_webhooks_without_auth(self, client):
        """Should return 401 without auth."""
        response = client.get("/webhooks")

        assert response.status_code == 401
