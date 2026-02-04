"""
MCP (Model Context Protocol) Server configurations for Sentinel AgOS.

MCP servers provide tool capabilities to agents:
- Playwright MCP: Browser automation for URL scanning, screenshots
- E2B MCP: Sandboxed code execution for mockup generation
"""

from mcp_servers.playwright_mcp import (
    PlaywrightMCPConfig,
    TRIAGE_PLAYWRIGHT_CONFIG,
    ARCHITECT_PLAYWRIGHT_CONFIG,
    PlaywrightMCPClient,
)
from mcp_servers.e2b_mcp import (
    E2BMCPConfig,
    E2B_CONFIG,
    MOCKUP_TEMPLATES,
    E2BMCPClient,
)

__all__ = [
    "PlaywrightMCPConfig",
    "TRIAGE_PLAYWRIGHT_CONFIG",
    "ARCHITECT_PLAYWRIGHT_CONFIG",
    "PlaywrightMCPClient",
    "E2BMCPConfig",
    "E2B_CONFIG",
    "MOCKUP_TEMPLATES",
    "E2BMCPClient",
]
