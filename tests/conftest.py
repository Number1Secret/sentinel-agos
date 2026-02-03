"""
Pytest configuration and fixtures.
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

# Set test environment variables
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    mock = MagicMock()

    # Mock auth
    mock.auth.get_user.return_value = MagicMock(
        user=MagicMock(
            id="test-user-id",
            email="test@example.com",
        )
    )

    # Mock table operations
    mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={
            "id": "test-user-id",
            "email": "test@example.com",
            "plan": "free",
            "audits_remaining": 5,
        }
    )

    return mock


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic client."""
    mock = MagicMock()

    mock.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"summary": "Test summary", "strengths": [], "weaknesses": [], "recommendations": []}')],
        usage=MagicMock(input_tokens=100, output_tokens=200),
    )

    return mock


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = MagicMock()
    mock.rpush.return_value = 1
    mock.blpop.return_value = None
    return mock


@pytest.fixture
def sample_audit_data():
    """Sample audit data for testing."""
    return {
        "id": "test-audit-id",
        "user_id": "test-user-id",
        "url": "https://example.com",
        "status": "completed",
        "created_at": "2024-01-01T00:00:00Z",
        "completed_at": "2024-01-01T00:05:00Z",
        "performance": {
            "score": 85,
            "firstContentfulPaint": 1.2,
            "largestContentfulPaint": 2.5,
            "totalBlockingTime": 100,
            "cumulativeLayoutShift": 0.1,
            "speedIndex": 3.0,
        },
        "seo": {
            "score": 90,
            "title": "Example Site",
            "metaDescription": "An example website",
            "h1Tags": ["Welcome"],
            "missingAltTexts": 2,
            "issues": [],
        },
        "accessibility": {
            "score": 80,
            "issues": [],
        },
        "brand": {
            "primaryColors": ["#2563EB"],
            "secondaryColors": [],
            "fonts": {"headings": "Inter", "body": "Open Sans"},
            "logoUrl": None,
            "ctas": [],
        },
        "analysis": {
            "summary": "Test summary",
            "strengths": ["Good performance"],
            "weaknesses": ["Missing meta descriptions"],
            "recommendations": [],
        },
        "screenshots": {
            "desktop": "base64-data",
            "mobile": "base64-data",
        },
        "tokens_used": 500,
        "cost_usd": 0.05,
        "processing_time_ms": 30000,
    }


@pytest.fixture
def auth_headers():
    """Authentication headers for testing."""
    return {"Authorization": "Bearer test-token"}
