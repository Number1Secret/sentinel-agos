"""
BaseAgent - Abstract base class for all Sentinel agents.

CRITICAL: Every agent execution MUST log to the agent_runs table with:
- input_tokens, output_tokens, cost_usd (tracked automatically)
- All tool calls and MCP interactions

This is infrastructure-first: observability is non-negotiable.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
from uuid import UUID, uuid4
import time

import structlog
from anthropic import Anthropic

from config import settings

logger = structlog.get_logger()

# Pricing per 1M tokens (Claude 3.5 Sonnet)
SONNET_INPUT_PRICE_PER_1M = Decimal("3.00")
SONNET_OUTPUT_PRICE_PER_1M = Decimal("15.00")


@dataclass
class AgentConfig:
    """Configuration loaded from the agents table."""
    id: UUID
    slug: str
    name: str
    room: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    tools: list[str]
    mcp_servers: list[str]
    timeout_seconds: int
    retry_attempts: int = 3


@dataclass
class AgentRunContext:
    """Context for a single agent execution."""
    run_id: UUID
    lead_id: Optional[UUID]
    user_id: Optional[UUID]
    playbook_id: Optional[UUID]
    batch_id: Optional[UUID]
    input_data: dict
    trigger: str = "queue"  # 'api', 'queue', 'scheduled', 'webhook', 'manual'


@dataclass
class TokenUsage:
    """Tracks token usage across multiple LLM calls."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> Decimal:
        """Calculate cost based on Claude 3.5 Sonnet pricing."""
        input_cost = (Decimal(self.input_tokens) / Decimal(1_000_000)) * SONNET_INPUT_PRICE_PER_1M
        output_cost = (Decimal(self.output_tokens) / Decimal(1_000_000)) * SONNET_OUTPUT_PRICE_PER_1M
        return input_cost + output_cost

    def add(self, input_tokens: int, output_tokens: int):
        """Add tokens from an LLM call."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


@dataclass
class ToolCall:
    """Record of a tool call during agent execution."""
    name: str
    duration_ms: int
    success: bool
    error: Optional[str] = None
    result: Optional[Any] = None


class BaseAgent(ABC):
    """
    Abstract base class for all Sentinel agents.

    Provides:
    - Configuration loading from database
    - LLM call abstraction with AUTOMATIC token tracking
    - Tool registration and execution with timing
    - Run logging and observability (writes to agent_runs table)

    IMPORTANT: Subclasses must call super().__init__() and implement run()
    """

    def __init__(
        self,
        config: AgentConfig,
        db_service: Optional[Any] = None,
        anthropic_client: Optional[Anthropic] = None,
    ):
        self.config = config
        self.db = db_service
        self.anthropic = anthropic_client or Anthropic(api_key=settings.anthropic_api_key)

        # Token tracking (reset for each run)
        self._token_usage = TokenUsage()

        # Tool tracking
        self._tools: dict[str, dict] = {}
        self._tool_calls: list[ToolCall] = []
        self._mcp_calls: list[dict] = []

        # Run timing
        self._run_started_at: Optional[datetime] = None
        self._run_id: Optional[UUID] = None

    @abstractmethod
    async def run(self, context: AgentRunContext) -> dict:
        """
        Execute the agent's main logic.

        Subclasses MUST implement this method.

        Args:
            context: AgentRunContext with run_id, lead_id, input_data, etc.

        Returns:
            dict: Output data to store in agent_runs.output_data
        """
        pass

    def register_tool(self, name: str, func: callable, schema: Optional[dict] = None):
        """
        Register a tool for use by the agent.

        Args:
            name: Tool name (must match what's in agents.tools)
            func: Async callable to execute
            schema: Optional JSON schema for tool parameters
        """
        self._tools[name] = {
            "func": func,
            "schema": schema or {}
        }
        logger.debug("Tool registered", agent=self.config.slug, tool=name)

    async def call_tool(self, name: str, **kwargs) -> Any:
        """
        Execute a registered tool with timing and error tracking.

        Args:
            name: Tool name
            **kwargs: Tool parameters

        Returns:
            Tool result
        """
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not registered")

        start_time = time.time()
        tool_call = ToolCall(name=name, duration_ms=0, success=False)

        try:
            result = await self._tools[name]["func"](**kwargs)
            tool_call.success = True
            tool_call.result = result
            return result
        except Exception as e:
            tool_call.error = str(e)
            logger.error("Tool call failed", agent=self.config.slug, tool=name, error=str(e))
            raise
        finally:
            tool_call.duration_ms = int((time.time() - start_time) * 1000)
            self._tool_calls.append(tool_call)

    async def call_llm(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """
        Make an LLM call with AUTOMATIC token tracking.

        Tokens and cost are tracked automatically and will be written
        to agent_runs when the run completes.

        Args:
            messages: List of message dicts
            tools: Optional tool definitions for function calling
            system: Override system prompt (defaults to config.system_prompt)
            max_tokens: Override max tokens
            temperature: Override temperature

        Returns:
            Anthropic Message response
        """
        try:
            kwargs = {
                "model": self.config.model,
                "max_tokens": max_tokens or self.config.max_tokens,
                "temperature": temperature if temperature is not None else self.config.temperature,
                "system": system or self.config.system_prompt,
                "messages": messages,
            }

            if tools:
                kwargs["tools"] = tools

            response = self.anthropic.messages.create(**kwargs)

            # CRITICAL: Track tokens automatically
            self._token_usage.add(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens
            )

            logger.debug(
                "LLM call completed",
                agent=self.config.slug,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=self._token_usage.total_tokens,
                cost_usd=float(self._token_usage.cost_usd)
            )

            return response

        except Exception as e:
            logger.error("LLM call failed", agent=self.config.slug, error=str(e))
            raise

    async def execute(self, context: AgentRunContext) -> dict:
        """
        Execute the agent with full observability.

        This is the main entry point that wraps run() with:
        - Run logging to agent_runs table (before and after)
        - Token/cost tracking
        - Error handling
        - Duration calculation

        Args:
            context: AgentRunContext

        Returns:
            dict: Output data
        """
        self._run_id = context.run_id
        self._run_started_at = datetime.utcnow()
        self._token_usage = TokenUsage()  # Reset for this run
        self._tool_calls = []
        self._mcp_calls = []

        # Log run start to database
        if self.db:
            await self._log_run_start(context)

        logger.info(
            "Agent run started",
            agent=self.config.slug,
            run_id=str(context.run_id),
            lead_id=str(context.lead_id) if context.lead_id else None,
            room=self.config.room
        )

        try:
            # Execute the agent's main logic
            output = await self.run(context)

            # Log successful completion
            if self.db:
                await self._log_run_complete(context, output)

            logger.info(
                "Agent run completed",
                agent=self.config.slug,
                run_id=str(context.run_id),
                total_tokens=self._token_usage.total_tokens,
                cost_usd=float(self._token_usage.cost_usd),
                duration_ms=self._calculate_duration_ms()
            )

            return output

        except Exception as e:
            # Log failure
            if self.db:
                await self._log_run_failed(context, str(e))

            logger.error(
                "Agent run failed",
                agent=self.config.slug,
                run_id=str(context.run_id),
                error=str(e),
                total_tokens=self._token_usage.total_tokens,
                cost_usd=float(self._token_usage.cost_usd)
            )
            raise

    async def _log_run_start(self, context: AgentRunContext):
        """Log the start of an agent run to the database."""
        await self.db.create_agent_run(
            run_id=context.run_id,
            agent_id=self.config.id,
            lead_id=context.lead_id,
            user_id=context.user_id,
            playbook_id=context.playbook_id,
            batch_id=context.batch_id,
            room=self.config.room,
            trigger=context.trigger,
            input_data=context.input_data,
            status="running",
            started_at=self._run_started_at
        )

    async def _log_run_complete(self, context: AgentRunContext, output: dict):
        """Log the completion of an agent run to the database."""
        await self.db.update_agent_run(
            run_id=context.run_id,
            status="completed",
            output_data=output,
            input_tokens=self._token_usage.input_tokens,
            output_tokens=self._token_usage.output_tokens,
            cost_usd=float(self._token_usage.cost_usd),
            tools_called=[
                {
                    "name": tc.name,
                    "duration_ms": tc.duration_ms,
                    "success": tc.success,
                    "error": tc.error
                }
                for tc in self._tool_calls
            ],
            mcp_calls=self._mcp_calls,
            completed_at=datetime.utcnow(),
            duration_ms=self._calculate_duration_ms()
        )

    async def _log_run_failed(self, context: AgentRunContext, error: str):
        """Log a failed agent run to the database."""
        await self.db.update_agent_run(
            run_id=context.run_id,
            status="failed",
            error=error,
            input_tokens=self._token_usage.input_tokens,
            output_tokens=self._token_usage.output_tokens,
            cost_usd=float(self._token_usage.cost_usd),
            tools_called=[
                {
                    "name": tc.name,
                    "duration_ms": tc.duration_ms,
                    "success": tc.success,
                    "error": tc.error
                }
                for tc in self._tool_calls
            ],
            mcp_calls=self._mcp_calls,
            completed_at=datetime.utcnow(),
            duration_ms=self._calculate_duration_ms()
        )

    def _calculate_duration_ms(self) -> int:
        """Calculate duration since run started."""
        if self._run_started_at:
            delta = datetime.utcnow() - self._run_started_at
            return int(delta.total_seconds() * 1000)
        return 0

    @property
    def token_usage(self) -> TokenUsage:
        """Get current token usage for this run."""
        return self._token_usage

    @property
    def cost_usd(self) -> Decimal:
        """Get current cost for this run."""
        return self._token_usage.cost_usd


async def load_agent_config(db_service, agent_slug: str) -> AgentConfig:
    """
    Load agent configuration from the database.

    Args:
        db_service: Supabase service instance
        agent_slug: Agent slug (e.g., 'triage', 'architect')

    Returns:
        AgentConfig
    """
    agent_data = await db_service.get_agent_by_slug(agent_slug)

    if not agent_data:
        raise ValueError(f"Agent '{agent_slug}' not found in database")

    return AgentConfig(
        id=UUID(agent_data["id"]),
        slug=agent_data["slug"],
        name=agent_data["name"],
        room=agent_data["room"],
        model=agent_data["model"],
        temperature=float(agent_data["temperature"]),
        max_tokens=agent_data["max_tokens"],
        system_prompt=agent_data["system_prompt"],
        tools=agent_data["tools"] if isinstance(agent_data["tools"], list) else [],
        mcp_servers=agent_data["mcp_servers"] or [],
        timeout_seconds=agent_data["timeout_seconds"],
        retry_attempts=agent_data["retry_attempts"]
    )
