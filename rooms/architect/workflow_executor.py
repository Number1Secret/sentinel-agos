"""
Workflow Executor - n8n-style workflow graph execution with quality gates.

Executes architect workflows with:
- DAG-based node execution
- Conditional branching (quality gates)
- Iterative regeneration loops
- Tool orchestration
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Awaitable
from enum import Enum
from collections import defaultdict

import structlog

logger = structlog.get_logger()


class NodeType(Enum):
    """Types of workflow nodes."""
    TOOL = "tool"           # Executes a tool
    AUDIT = "audit"         # Runs a quality audit
    CONDITION = "condition" # Branching based on conditions
    APPROVAL = "approval"   # Requires human approval
    END = "end"             # Terminal node


class ConditionOperator(Enum):
    """Condition operators for quality gates."""
    GTE = ">="
    LTE = "<="
    GT = ">"
    LT = "<"
    EQ = "=="
    NEQ = "!="


@dataclass
class WorkflowNode:
    """A node in the workflow graph."""
    id: str
    type: NodeType
    tool: Optional[str] = None  # Tool name for TOOL/AUDIT nodes
    label: Optional[str] = None
    config: dict = field(default_factory=dict)  # Node-specific config
    conditions: list[dict] = field(default_factory=list)  # For CONDITION nodes


@dataclass
class WorkflowEdge:
    """An edge connecting two nodes."""
    source: str
    target: str
    label: Optional[str] = None  # "pass", "fail", etc.


@dataclass
class WorkflowGraph:
    """Complete workflow graph."""
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    entry: str  # Entry node ID

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowGraph":
        """Create workflow graph from dictionary."""
        nodes = []
        for node_data in data.get("nodes", []):
            node = WorkflowNode(
                id=node_data["id"],
                type=NodeType(node_data.get("type", "tool")),
                tool=node_data.get("tool"),
                label=node_data.get("label"),
                config=node_data.get("config", {}),
                conditions=node_data.get("conditions", [])
            )
            nodes.append(node)

        edges = []
        for edge_data in data.get("edges", []):
            edge = WorkflowEdge(
                source=edge_data["source"],
                target=edge_data["target"],
                label=edge_data.get("label")
            )
            edges.append(edge)

        return cls(
            nodes=nodes,
            edges=edges,
            entry=data.get("entry", nodes[0].id if nodes else "")
        )

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        """Get node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_outgoing_edges(self, node_id: str) -> list[WorkflowEdge]:
        """Get all edges leaving a node."""
        return [e for e in self.edges if e.source == node_id]


@dataclass
class NodeResult:
    """Result of executing a single node."""
    node_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    next_node: Optional[str] = None  # Determined by conditions


@dataclass
class WorkflowContext:
    """Context passed through workflow execution."""
    lead_id: str
    user_id: Optional[str] = None
    brand_dna: dict = field(default_factory=dict)
    triage_signals: dict = field(default_factory=dict)
    house_style: dict = field(default_factory=dict)

    # Execution state
    iteration_count: int = 1
    quality_score: int = 0
    current_screenshot: Optional[str] = None
    current_preview_url: Optional[str] = None
    current_sandbox_id: Optional[str] = None

    # Results from each node
    node_results: dict = field(default_factory=dict)

    # Strategy (from strategy synthesizer)
    pitch_strategy: dict = field(default_factory=dict)

    # Generated assets
    generated_code: Optional[str] = None
    generated_assets: list = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value by key."""
        if hasattr(self, key):
            return getattr(self, key)
        return self.node_results.get(key, default)

    def set(self, key: str, value: Any):
        """Set a context value."""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self.node_results[key] = value


@dataclass
class WorkflowResult:
    """Result of complete workflow execution."""
    success: bool
    final_output: Any = None
    quality_score: int = 0
    iteration_count: int = 1
    node_results: dict = field(default_factory=dict)
    total_duration_ms: int = 0
    error: Optional[str] = None

    # Final assets
    preview_url: Optional[str] = None
    sandbox_id: Optional[str] = None
    screenshot_base64: Optional[str] = None
    generated_code: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "quality_score": self.quality_score,
            "iteration_count": self.iteration_count,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "preview_url": self.preview_url,
            "sandbox_id": self.sandbox_id,
            "has_screenshot": self.screenshot_base64 is not None,
            "node_results": {
                k: {"success": v.success, "duration_ms": v.duration_ms}
                for k, v in self.node_results.items()
            }
        }


class WorkflowExecutor:
    """
    Executes n8n-style workflow graphs with quality gates.

    Supports:
    - Sequential and conditional execution
    - Quality-based regeneration loops
    - Tool orchestration
    - Human approval gates
    """

    def __init__(
        self,
        tools: dict[str, Callable[..., Awaitable[Any]]] = None,
        max_iterations: int = 3,
        quality_threshold: int = 85,
        timeout_seconds: int = 300
    ):
        """
        Initialize WorkflowExecutor.

        Args:
            tools: Dict mapping tool names to async callables
            max_iterations: Maximum regeneration iterations
            quality_threshold: Quality score threshold for passing
            timeout_seconds: Overall workflow timeout
        """
        self.tools = tools or {}
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold
        self.timeout_seconds = timeout_seconds

    def register_tool(self, name: str, tool: Callable[..., Awaitable[Any]]):
        """Register a tool for workflow execution."""
        self.tools[name] = tool

    async def execute(
        self,
        workflow: WorkflowGraph,
        context: WorkflowContext,
        tools: dict[str, Callable[..., Awaitable[Any]]] = None
    ) -> WorkflowResult:
        """
        Execute a workflow graph.

        Args:
            workflow: The workflow graph to execute
            context: Execution context with lead data
            tools: Additional tools (merged with registered tools)

        Returns:
            WorkflowResult with final output and metrics
        """
        start_time = time.time()

        # Merge tools
        all_tools = {**self.tools}
        if tools:
            all_tools.update(tools)

        # Track node results
        node_results: dict[str, NodeResult] = {}

        try:
            # Start from entry node
            current_node_id = workflow.entry
            iterations = 0

            while current_node_id and iterations < 100:  # Safety limit
                iterations += 1
                node = workflow.get_node(current_node_id)

                if not node:
                    raise ValueError(f"Node not found: {current_node_id}")

                logger.info(
                    "Executing workflow node",
                    node_id=node.id,
                    node_type=node.type.value,
                    iteration=context.iteration_count
                )

                # Execute the node
                result = await self._execute_node(node, context, all_tools)
                node_results[node.id] = result

                if not result.success:
                    logger.error("Node execution failed", node_id=node.id, error=result.error)
                    return WorkflowResult(
                        success=False,
                        error=f"Node {node.id} failed: {result.error}",
                        node_results=node_results,
                        total_duration_ms=int((time.time() - start_time) * 1000)
                    )

                # Determine next node
                if node.type == NodeType.END:
                    # Workflow complete
                    break

                current_node_id = result.next_node
                if not current_node_id:
                    # Find default next node from edges
                    edges = workflow.get_outgoing_edges(node.id)
                    if edges:
                        current_node_id = edges[0].target

                # Check for timeout
                if time.time() - start_time > self.timeout_seconds:
                    raise TimeoutError("Workflow execution timed out")

            total_duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "Workflow execution completed",
                total_nodes=len(node_results),
                quality_score=context.quality_score,
                iterations=context.iteration_count,
                duration_ms=total_duration_ms
            )

            return WorkflowResult(
                success=True,
                final_output=context.node_results,
                quality_score=context.quality_score,
                iteration_count=context.iteration_count,
                node_results=node_results,
                total_duration_ms=total_duration_ms,
                preview_url=context.current_preview_url,
                sandbox_id=context.current_sandbox_id,
                screenshot_base64=context.current_screenshot,
                generated_code=context.generated_code
            )

        except Exception as e:
            logger.error("Workflow execution failed", error=str(e))
            return WorkflowResult(
                success=False,
                error=str(e),
                node_results=node_results,
                total_duration_ms=int((time.time() - start_time) * 1000)
            )

    async def _execute_node(
        self,
        node: WorkflowNode,
        context: WorkflowContext,
        tools: dict
    ) -> NodeResult:
        """Execute a single workflow node."""
        start_time = time.time()

        try:
            if node.type == NodeType.TOOL:
                return await self._execute_tool_node(node, context, tools)

            elif node.type == NodeType.AUDIT:
                return await self._execute_audit_node(node, context, tools)

            elif node.type == NodeType.CONDITION:
                return await self._execute_condition_node(node, context)

            elif node.type == NodeType.APPROVAL:
                return await self._execute_approval_node(node, context)

            elif node.type == NodeType.END:
                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output={"status": "completed"},
                    duration_ms=int((time.time() - start_time) * 1000)
                )

            else:
                raise ValueError(f"Unknown node type: {node.type}")

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )

    async def _execute_tool_node(
        self,
        node: WorkflowNode,
        context: WorkflowContext,
        tools: dict
    ) -> NodeResult:
        """Execute a tool node."""
        start_time = time.time()

        tool_name = node.tool
        if not tool_name or tool_name not in tools:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Tool not found: {tool_name}",
                duration_ms=int((time.time() - start_time) * 1000)
            )

        tool = tools[tool_name]

        # Execute the tool with context
        try:
            result = await tool(context, **node.config)

            # Update context with result
            context.node_results[node.id] = result

            # Handle specific tool outputs
            if tool_name == "brand_extract" and result:
                context.brand_dna = result if isinstance(result, dict) else result.to_dict()

            elif tool_name == "strategy_synthesis" and result:
                context.pitch_strategy = result if isinstance(result, dict) else result.to_dict()

            elif tool_name == "mockup_generate" and result:
                if isinstance(result, dict):
                    context.current_preview_url = result.get("preview_url")
                    context.current_sandbox_id = result.get("sandbox_id")
                    context.current_screenshot = result.get("screenshot")
                    context.generated_code = result.get("code")

            return NodeResult(
                node_id=node.id,
                success=True,
                output=result,
                duration_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )

    async def _execute_audit_node(
        self,
        node: WorkflowNode,
        context: WorkflowContext,
        tools: dict
    ) -> NodeResult:
        """Execute an audit node (e.g., vision audit)."""
        start_time = time.time()

        tool_name = node.tool or "vision_audit"
        if tool_name not in tools:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=f"Audit tool not found: {tool_name}",
                duration_ms=int((time.time() - start_time) * 1000)
            )

        tool = tools[tool_name]

        try:
            # Run the audit
            result = await tool(context, **node.config)

            # Update context with audit results
            if isinstance(result, dict):
                context.quality_score = result.get("quality_score", 0)
            elif hasattr(result, "quality_score"):
                context.quality_score = result.quality_score

            context.node_results[node.id] = result

            return NodeResult(
                node_id=node.id,
                success=True,
                output=result,
                duration_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )

    async def _execute_condition_node(
        self,
        node: WorkflowNode,
        context: WorkflowContext
    ) -> NodeResult:
        """Execute a condition node (quality gate)."""
        start_time = time.time()

        # Evaluate conditions in order
        for condition in node.conditions:
            field = condition.get("field")
            op = condition.get("op", ">=")
            value = condition.get("value")
            target = condition.get("target")

            # Get field value from context
            field_value = context.get(field)

            # Evaluate condition
            if self._evaluate_condition(field_value, op, value):
                logger.info(
                    "Condition matched",
                    node_id=node.id,
                    field=field,
                    field_value=field_value,
                    op=op,
                    value=value,
                    target=target
                )

                # Handle iteration loop
                if target != "complete" and field == "iteration_count":
                    context.iteration_count += 1

                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output={"condition": f"{field} {op} {value}", "matched": True},
                    duration_ms=int((time.time() - start_time) * 1000),
                    next_node=target
                )

        # No condition matched - default to first edge target
        return NodeResult(
            node_id=node.id,
            success=True,
            output={"matched": False},
            duration_ms=int((time.time() - start_time) * 1000)
        )

    def _evaluate_condition(self, field_value: Any, op: str, value: Any) -> bool:
        """Evaluate a single condition."""
        if field_value is None:
            return False

        try:
            if op in (">=", "gte"):
                return field_value >= value
            elif op in ("<=", "lte"):
                return field_value <= value
            elif op in (">", "gt"):
                return field_value > value
            elif op in ("<", "lt"):
                return field_value < value
            elif op in ("==", "eq"):
                return field_value == value
            elif op in ("!=", "neq"):
                return field_value != value
            else:
                return False
        except (TypeError, ValueError):
            return False

    async def _execute_approval_node(
        self,
        node: WorkflowNode,
        context: WorkflowContext
    ) -> NodeResult:
        """Execute an approval node (creates approval item)."""
        start_time = time.time()

        # In a real implementation, this would create an approval item in the database
        # and pause workflow execution until approved

        # For now, auto-approve if quality score meets threshold
        if context.quality_score >= self.quality_threshold:
            return NodeResult(
                node_id=node.id,
                success=True,
                output={"status": "auto_approved", "quality_score": context.quality_score},
                duration_ms=int((time.time() - start_time) * 1000)
            )

        # Otherwise, create pending approval
        approval_data = {
            "node_id": node.id,
            "lead_id": context.lead_id,
            "quality_score": context.quality_score,
            "preview_url": context.current_preview_url,
            "status": "pending_approval"
        }

        return NodeResult(
            node_id=node.id,
            success=True,
            output=approval_data,
            duration_ms=int((time.time() - start_time) * 1000)
        )


class DefaultWorkflowBuilder:
    """Builder for creating default architect workflows."""

    @staticmethod
    def build_default_workflow(
        quality_threshold: int = 85,
        max_iterations: int = 3
    ) -> WorkflowGraph:
        """Build the default production forge workflow."""
        return WorkflowGraph.from_dict({
            "nodes": [
                {
                    "id": "brand_dna",
                    "type": "tool",
                    "tool": "brand_extract",
                    "label": "Extract Brand DNA"
                },
                {
                    "id": "strategy",
                    "type": "tool",
                    "tool": "strategy_synthesis",
                    "label": "Synthesize Strategy"
                },
                {
                    "id": "code_forge",
                    "type": "tool",
                    "tool": "mockup_generate",
                    "label": "Generate Mockup"
                },
                {
                    "id": "self_audit",
                    "type": "audit",
                    "tool": "vision_audit",
                    "label": "Vision Self-Audit"
                },
                {
                    "id": "quality_gate",
                    "type": "condition",
                    "label": "Quality Gate",
                    "conditions": [
                        {
                            "field": "quality_score",
                            "op": ">=",
                            "value": quality_threshold,
                            "target": "complete"
                        },
                        {
                            "field": "iteration_count",
                            "op": "<",
                            "value": max_iterations,
                            "target": "code_forge"
                        },
                        {
                            "field": "iteration_count",
                            "op": ">=",
                            "value": max_iterations,
                            "target": "approval"
                        }
                    ]
                },
                {
                    "id": "approval",
                    "type": "approval",
                    "label": "Human Approval",
                    "config": {
                        "type": "mockup",
                        "title": "Review Generated Mockup"
                    }
                },
                {
                    "id": "complete",
                    "type": "end",
                    "label": "Complete"
                }
            ],
            "edges": [
                {"source": "brand_dna", "target": "strategy"},
                {"source": "strategy", "target": "code_forge"},
                {"source": "code_forge", "target": "self_audit"},
                {"source": "self_audit", "target": "quality_gate"},
                {"source": "quality_gate", "target": "complete", "label": "pass"},
                {"source": "quality_gate", "target": "code_forge", "label": "retry"},
                {"source": "quality_gate", "target": "approval", "label": "max_iterations"},
                {"source": "approval", "target": "complete"}
            ],
            "entry": "brand_dna"
        })

    @staticmethod
    def build_simple_workflow() -> WorkflowGraph:
        """Build a simplified workflow without quality gates."""
        return WorkflowGraph.from_dict({
            "nodes": [
                {
                    "id": "brand_dna",
                    "type": "tool",
                    "tool": "brand_extract",
                    "label": "Extract Brand DNA"
                },
                {
                    "id": "code_forge",
                    "type": "tool",
                    "tool": "mockup_generate",
                    "label": "Generate Mockup"
                },
                {
                    "id": "complete",
                    "type": "end",
                    "label": "Complete"
                }
            ],
            "edges": [
                {"source": "brand_dna", "target": "code_forge"},
                {"source": "code_forge", "target": "complete"}
            ],
            "entry": "brand_dna"
        })
