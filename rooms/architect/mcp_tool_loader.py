"""
MCP Tool Loader - Loads custom agency MCP tools from registry.

Allows agencies to register and use custom MCP tools in architect workflows.
Supports:
- Loading tools from database registry
- Tool validation and schema verification
- Tool execution with timeout handling
- Usage tracking and statistics
"""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Awaitable
from uuid import UUID
from datetime import datetime

import structlog

logger = structlog.get_logger()


@dataclass
class MCPToolConfig:
    """Configuration for an MCP tool."""
    id: str
    slug: str
    name: str
    description: Optional[str]
    category: str
    mcp_server_config: dict
    tool_schema: dict
    timeout_ms: int = 30000
    retry_attempts: int = 2
    is_active: bool = True


@dataclass
class MCPToolResult:
    """Result from executing an MCP tool."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    retries_used: int = 0


class MCPToolWrapper:
    """Wrapper that makes an MCP tool callable."""

    def __init__(
        self,
        config: MCPToolConfig,
        mcp_client: Any = None,
        db_service: Any = None
    ):
        """
        Initialize MCPToolWrapper.

        Args:
            config: Tool configuration
            mcp_client: MCP client for tool execution
            db_service: Database service for usage tracking
        """
        self.config = config
        self.mcp_client = mcp_client
        self.db_service = db_service

    async def __call__(self, context: Any, **kwargs) -> MCPToolResult:
        """
        Execute the MCP tool.

        Args:
            context: Workflow context
            **kwargs: Additional arguments for the tool

        Returns:
            MCPToolResult with output or error
        """
        import time
        start_time = time.time()
        retries = 0

        while retries <= self.config.retry_attempts:
            try:
                # Execute tool via MCP client
                result = await self._execute_tool(context, kwargs)

                duration_ms = int((time.time() - start_time) * 1000)

                # Track usage
                await self._track_usage(duration_ms, success=True)

                return MCPToolResult(
                    success=True,
                    output=result,
                    duration_ms=duration_ms,
                    retries_used=retries
                )

            except asyncio.TimeoutError:
                retries += 1
                logger.warning(
                    "MCP tool timeout, retrying",
                    tool=self.config.slug,
                    retry=retries
                )

            except Exception as e:
                retries += 1
                if retries > self.config.retry_attempts:
                    duration_ms = int((time.time() - start_time) * 1000)
                    await self._track_usage(duration_ms, success=False)

                    return MCPToolResult(
                        success=False,
                        error=str(e),
                        duration_ms=duration_ms,
                        retries_used=retries
                    )

                logger.warning(
                    "MCP tool error, retrying",
                    tool=self.config.slug,
                    error=str(e),
                    retry=retries
                )

        # Should not reach here, but just in case
        return MCPToolResult(
            success=False,
            error="Max retries exceeded",
            duration_ms=int((time.time() - start_time) * 1000),
            retries_used=retries
        )

    async def _execute_tool(self, context: Any, params: dict) -> Any:
        """Execute the tool via MCP client."""
        if not self.mcp_client:
            raise RuntimeError("MCP client not configured")

        # Validate params against schema
        self._validate_params(params)

        # Build MCP request
        server_config = self.config.mcp_server_config
        tool_name = server_config.get("tool_name", self.config.slug)

        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                self.mcp_client.call_tool(
                    server=server_config.get("server"),
                    tool=tool_name,
                    arguments=params
                ),
                timeout=self.config.timeout_ms / 1000
            )
            return result
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"Tool {self.config.slug} timed out after {self.config.timeout_ms}ms"
            )

    def _validate_params(self, params: dict):
        """Validate parameters against tool schema."""
        schema = self.config.tool_schema

        # Basic required field validation
        required = schema.get("required", [])
        for field in required:
            if field not in params:
                raise ValueError(f"Missing required parameter: {field}")

        # Type validation for properties
        properties = schema.get("properties", {})
        for key, value in params.items():
            if key in properties:
                prop_schema = properties[key]
                expected_type = prop_schema.get("type")

                if expected_type and not self._check_type(value, expected_type):
                    raise ValueError(
                        f"Parameter {key} has wrong type. Expected {expected_type}"
                    )

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON schema type."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None)
        }

        expected = type_map.get(expected_type)
        if expected is None:
            return True  # Unknown type, allow

        return isinstance(value, expected)

    async def _track_usage(self, duration_ms: int, success: bool):
        """Track tool usage statistics."""
        if not self.db_service:
            return

        try:
            await self.db_service.update_mcp_tool_usage(
                tool_id=self.config.id,
                duration_ms=duration_ms,
                success=success
            )
        except Exception as e:
            logger.warning("Failed to track MCP tool usage", error=str(e))


class MCPToolLoader:
    """
    Loads custom agency MCP tools from registry.

    Provides:
    - Tool discovery from database
    - Tool instantiation with proper configuration
    - Caching for performance
    - Tool validation
    """

    def __init__(self, db_service: Any, mcp_client: Any = None):
        """
        Initialize MCPToolLoader.

        Args:
            db_service: Database service for querying tool registry
            mcp_client: MCP client for tool execution
        """
        self.db_service = db_service
        self.mcp_client = mcp_client
        self._tool_cache: dict[str, dict[str, MCPToolWrapper]] = {}

    async def load_user_tools(
        self,
        user_id: UUID,
        categories: Optional[list[str]] = None
    ) -> dict[str, Callable[..., Awaitable[Any]]]:
        """
        Load all active MCP tools for a user.

        Args:
            user_id: User ID to load tools for
            categories: Optional filter by categories

        Returns:
            Dict mapping tool slugs to callable wrappers
        """
        cache_key = str(user_id)

        # Check cache
        if cache_key in self._tool_cache:
            cached = self._tool_cache[cache_key]
            if categories:
                return {
                    k: v for k, v in cached.items()
                    if v.config.category in categories
                }
            return cached

        # Load from database
        tools = await self._load_tools_from_db(user_id, categories)

        # Cache the tools
        self._tool_cache[cache_key] = tools

        return tools

    async def load_tool(
        self,
        user_id: UUID,
        tool_slug: str
    ) -> Optional[Callable[..., Awaitable[Any]]]:
        """
        Load a specific tool by slug.

        Args:
            user_id: User ID
            tool_slug: Tool slug to load

        Returns:
            Callable tool wrapper or None if not found
        """
        tools = await self.load_user_tools(user_id)
        return tools.get(tool_slug)

    async def _load_tools_from_db(
        self,
        user_id: UUID,
        categories: Optional[list[str]] = None
    ) -> dict[str, MCPToolWrapper]:
        """Load tools from database registry."""
        tools: dict[str, MCPToolWrapper] = {}

        try:
            # Query the mcp_tool_registry table
            query_params = {
                "user_id": str(user_id),
                "is_active": True
            }
            if categories:
                query_params["categories"] = categories

            records = await self.db_service.get_mcp_tools(**query_params)

            for record in records:
                config = MCPToolConfig(
                    id=record["id"],
                    slug=record["slug"],
                    name=record["name"],
                    description=record.get("description"),
                    category=record["category"],
                    mcp_server_config=record["mcp_server_config"],
                    tool_schema=record["tool_schema"],
                    timeout_ms=record.get("timeout_ms", 30000),
                    retry_attempts=record.get("retry_attempts", 2),
                    is_active=record.get("is_active", True)
                )

                wrapper = MCPToolWrapper(
                    config=config,
                    mcp_client=self.mcp_client,
                    db_service=self.db_service
                )

                tools[config.slug] = wrapper

            logger.info(
                "Loaded MCP tools for user",
                user_id=str(user_id),
                tool_count=len(tools),
                tool_slugs=list(tools.keys())
            )

        except Exception as e:
            logger.error("Failed to load MCP tools", error=str(e))

        return tools

    def clear_cache(self, user_id: Optional[UUID] = None):
        """Clear the tool cache."""
        if user_id:
            cache_key = str(user_id)
            self._tool_cache.pop(cache_key, None)
        else:
            self._tool_cache.clear()

    async def validate_tool_config(self, config: dict) -> tuple[bool, list[str]]:
        """
        Validate a tool configuration before saving.

        Args:
            config: Tool configuration dict

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Required fields
        required_fields = ["slug", "name", "category", "mcp_server_config", "tool_schema"]
        for field in required_fields:
            if field not in config:
                errors.append(f"Missing required field: {field}")

        # Validate category
        valid_categories = ["brand", "code", "audit", "content", "integration"]
        if config.get("category") and config["category"] not in valid_categories:
            errors.append(f"Invalid category: {config['category']}. Must be one of {valid_categories}")

        # Validate mcp_server_config
        server_config = config.get("mcp_server_config", {})
        if not isinstance(server_config, dict):
            errors.append("mcp_server_config must be a dict")
        elif not server_config.get("server"):
            errors.append("mcp_server_config must include 'server' field")

        # Validate tool_schema
        tool_schema = config.get("tool_schema", {})
        if not isinstance(tool_schema, dict):
            errors.append("tool_schema must be a dict")

        # Validate slug format
        slug = config.get("slug", "")
        if slug and not slug.replace("-", "").replace("_", "").isalnum():
            errors.append("Slug must be alphanumeric with hyphens or underscores only")

        return len(errors) == 0, errors


class MCPToolRegistryService:
    """Service for managing MCP tool registry."""

    def __init__(self, db_service: Any):
        self.db = db_service
        self.loader = MCPToolLoader(db_service)

    async def register_tool(
        self,
        user_id: UUID,
        slug: str,
        name: str,
        category: str,
        mcp_server_config: dict,
        tool_schema: dict,
        description: Optional[str] = None,
        timeout_ms: int = 30000,
        retry_attempts: int = 2
    ) -> dict:
        """
        Register a new MCP tool.

        Args:
            user_id: User registering the tool
            slug: Unique slug for the tool
            name: Display name
            category: Tool category
            mcp_server_config: MCP server connection config
            tool_schema: JSON Schema for tool parameters
            description: Tool description
            timeout_ms: Execution timeout
            retry_attempts: Number of retries on failure

        Returns:
            Created tool record
        """
        # Validate config
        config = {
            "slug": slug,
            "name": name,
            "category": category,
            "mcp_server_config": mcp_server_config,
            "tool_schema": tool_schema
        }
        is_valid, errors = await self.loader.validate_tool_config(config)
        if not is_valid:
            raise ValueError(f"Invalid tool config: {', '.join(errors)}")

        # Create tool record
        tool_data = {
            "user_id": str(user_id),
            "slug": slug,
            "name": name,
            "description": description,
            "category": category,
            "mcp_server_config": mcp_server_config,
            "tool_schema": tool_schema,
            "timeout_ms": timeout_ms,
            "retry_attempts": retry_attempts,
            "is_active": True,
            "usage_count": 0
        }

        result = await self.db.create_mcp_tool(tool_data)

        # Clear cache for this user
        self.loader.clear_cache(user_id)

        logger.info(
            "MCP tool registered",
            user_id=str(user_id),
            tool_slug=slug,
            category=category
        )

        return result

    async def get_user_tools(
        self,
        user_id: UUID,
        category: Optional[str] = None
    ) -> list[dict]:
        """Get all tools for a user."""
        categories = [category] if category else None
        tools = await self.db.get_mcp_tools(
            user_id=str(user_id),
            categories=categories
        )
        return tools

    async def update_tool(
        self,
        tool_id: str,
        user_id: UUID,
        updates: dict
    ) -> dict:
        """Update a tool."""
        # Validate if config fields are being updated
        if any(k in updates for k in ["mcp_server_config", "tool_schema", "category"]):
            is_valid, errors = await self.loader.validate_tool_config({
                **updates,
                "slug": updates.get("slug", "placeholder"),
                "name": updates.get("name", "placeholder"),
                "category": updates.get("category", "brand"),
                "mcp_server_config": updates.get("mcp_server_config", {"server": "x"}),
                "tool_schema": updates.get("tool_schema", {})
            })
            if not is_valid:
                raise ValueError(f"Invalid updates: {', '.join(errors)}")

        result = await self.db.update_mcp_tool(tool_id, updates)

        # Clear cache
        self.loader.clear_cache(user_id)

        return result

    async def delete_tool(self, tool_id: str, user_id: UUID) -> bool:
        """Delete a tool."""
        result = await self.db.delete_mcp_tool(tool_id)
        self.loader.clear_cache(user_id)
        return result

    async def test_tool(
        self,
        tool_id: str,
        user_id: UUID,
        test_params: dict
    ) -> MCPToolResult:
        """
        Test a tool with sample parameters.

        Args:
            tool_id: Tool ID to test
            user_id: User ID
            test_params: Test parameters

        Returns:
            MCPToolResult from test execution
        """
        tools = await self.loader.load_user_tools(user_id)

        # Find the tool
        tool_wrapper = None
        for wrapper in tools.values():
            if wrapper.config.id == tool_id:
                tool_wrapper = wrapper
                break

        if not tool_wrapper:
            return MCPToolResult(
                success=False,
                error=f"Tool not found: {tool_id}"
            )

        # Execute test
        return await tool_wrapper(None, **test_params)
