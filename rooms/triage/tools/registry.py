"""
Dynamic Tool Registry for SDR Engine.

Tools are registered globally and loaded dynamically based on playbook configuration.
This enables agencies to customize which tools are available for their workflows.

Usage:
    # Register a tool using the decorator
    @register_tool(
        name="my_tool",
        category="scan",
        description="Does something useful",
        schema={"url": {"type": "string"}}
    )
    async def my_tool_func(url: str) -> dict:
        return {"result": "data"}

    # Get a tool by name
    tool = get_tool("my_tool")
    result = await tool.func(url="https://example.com")
"""
from typing import Dict, Callable, Any, Optional, List
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class ToolDefinition:
    """Definition of a registered tool."""
    name: str
    func: Callable
    schema: dict
    description: str
    category: str  # 'scan', 'enrich', 'inlet', 'verify', 'analyze'
    requires_api_key: Optional[str] = None  # Environment variable name if API key required
    tags: List[str] = field(default_factory=list)  # For filtering/discovery


# Global tool registry
_TOOL_REGISTRY: Dict[str, ToolDefinition] = {}


def register_tool(
    name: str,
    category: str,
    description: str,
    schema: Optional[dict] = None,
    requires_api_key: Optional[str] = None,
    tags: Optional[List[str]] = None
):
    """
    Decorator to register a tool in the global registry.

    Args:
        name: Unique tool identifier (used in playbook configs)
        category: Tool category for organization ('scan', 'enrich', 'inlet', 'verify', 'analyze')
        description: Human-readable description of what the tool does
        schema: JSON schema for tool parameters
        requires_api_key: Environment variable name if an API key is required
        tags: Optional tags for filtering/discovery

    Returns:
        Decorator function

    Example:
        @register_tool(
            name="url_scan",
            category="scan",
            description="Fast HTTP scan of a URL",
            schema={"url": {"type": "string", "required": True}}
        )
        async def url_scan(url: str) -> dict:
            # Implementation
            pass
    """
    def decorator(func: Callable) -> Callable:
        if name in _TOOL_REGISTRY:
            logger.warning(
                "Tool already registered, overwriting",
                name=name,
                previous_func=_TOOL_REGISTRY[name].func.__name__
            )

        _TOOL_REGISTRY[name] = ToolDefinition(
            name=name,
            func=func,
            schema=schema or {},
            description=description,
            category=category,
            requires_api_key=requires_api_key,
            tags=tags or []
        )
        logger.debug("Tool registered", name=name, category=category)
        return func
    return decorator


def get_tool(name: str) -> ToolDefinition:
    """
    Get a tool definition by name.

    Args:
        name: Tool name

    Returns:
        ToolDefinition

    Raises:
        ValueError: If tool is not found
    """
    if name not in _TOOL_REGISTRY:
        available = ", ".join(_TOOL_REGISTRY.keys()) or "none"
        raise ValueError(f"Tool '{name}' not found in registry. Available tools: {available}")
    return _TOOL_REGISTRY[name]


def get_tools_by_category(category: str) -> List[ToolDefinition]:
    """
    Get all tools in a specific category.

    Args:
        category: Category to filter by

    Returns:
        List of matching ToolDefinitions
    """
    return [t for t in _TOOL_REGISTRY.values() if t.category == category]


def get_tools_by_tag(tag: str) -> List[ToolDefinition]:
    """
    Get all tools with a specific tag.

    Args:
        tag: Tag to filter by

    Returns:
        List of matching ToolDefinitions
    """
    return [t for t in _TOOL_REGISTRY.values() if tag in t.tags]


def list_available_tools() -> List[str]:
    """
    List all registered tool names.

    Returns:
        List of tool names
    """
    return list(_TOOL_REGISTRY.keys())


def list_tools_with_metadata() -> List[dict]:
    """
    List all tools with their metadata (for API/discovery endpoints).

    Returns:
        List of tool metadata dicts
    """
    return [
        {
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "schema": t.schema,
            "requires_api_key": t.requires_api_key,
            "tags": t.tags
        }
        for t in _TOOL_REGISTRY.values()
    ]


def validate_tools_available(tool_names: List[str]) -> tuple[List[str], List[str]]:
    """
    Validate that a list of tool names are available in the registry.

    Args:
        tool_names: List of tool names to validate

    Returns:
        Tuple of (available_tools, missing_tools)
    """
    available = []
    missing = []
    for name in tool_names:
        if name in _TOOL_REGISTRY:
            available.append(name)
        else:
            missing.append(name)
    return available, missing


def check_api_keys_available(tool_names: List[str]) -> dict[str, bool]:
    """
    Check if required API keys are available for given tools.

    Args:
        tool_names: List of tool names to check

    Returns:
        Dict mapping tool name to API key availability
    """
    import os

    results = {}
    for name in tool_names:
        if name not in _TOOL_REGISTRY:
            results[name] = False
            continue

        tool = _TOOL_REGISTRY[name]
        if tool.requires_api_key:
            results[name] = bool(os.getenv(tool.requires_api_key))
        else:
            results[name] = True  # No API key required

    return results


# Category constants for consistency
class ToolCategory:
    SCAN = "scan"          # URL/page scanning tools
    ENRICH = "enrich"      # Data enrichment (contacts, company info)
    INLET = "inlet"        # Lead ingestion (CSV, API, scraping)
    VERIFY = "verify"      # Verification tools (email, phone)
    ANALYZE = "analyze"    # Analysis tools (competitors, market)
