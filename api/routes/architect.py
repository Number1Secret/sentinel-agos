"""
Architect Room API Routes

Endpoints for the Autonomous Production Forge:
- MCP Tools CRUD
- Architect Workflows CRUD
- Prompt Library CRUD
- Lead mockup preview and regeneration
- Iteration history
"""
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from pydantic import BaseModel, Field
import structlog

from api.dependencies import get_current_user, get_supabase_service
from services.supabase import SupabaseService

logger = structlog.get_logger()

router = APIRouter(prefix="/architect", tags=["Architect"])


# ====================
# Request/Response Models
# ====================

class MCPToolCreate(BaseModel):
    """Create MCP tool request."""
    slug: str = Field(..., description="Unique slug for the tool")
    name: str = Field(..., description="Display name")
    description: Optional[str] = None
    category: str = Field(..., description="Tool category: brand, code, audit, content, integration")
    mcp_server_config: dict = Field(..., description="MCP server connection config")
    tool_schema: dict = Field(..., description="JSON Schema for tool parameters")
    timeout_ms: int = Field(default=30000, description="Execution timeout in ms")
    retry_attempts: int = Field(default=2, description="Number of retries on failure")


class MCPToolResponse(BaseModel):
    """MCP tool response."""
    id: str
    slug: str
    name: str
    description: Optional[str]
    category: str
    mcp_server_config: dict
    tool_schema: dict
    timeout_ms: int
    retry_attempts: int
    is_active: bool
    usage_count: int
    created_at: str


class ArchitectWorkflowCreate(BaseModel):
    """Create architect workflow request."""
    slug: str = Field(..., description="Unique slug")
    name: str = Field(..., description="Display name")
    description: Optional[str] = None
    graph: dict = Field(..., description="Workflow graph (nodes and edges)")
    quality_threshold: int = Field(default=85, ge=0, le=100)
    max_iterations: int = Field(default=3, ge=1, le=10)
    self_audit_model: str = Field(default="claude-sonnet-4-20250514")
    code_gen_model: str = Field(default="claude-sonnet-4-20250514")


class ArchitectWorkflowResponse(BaseModel):
    """Architect workflow response."""
    id: str
    slug: str
    name: str
    description: Optional[str]
    graph: dict
    quality_threshold: int
    max_iterations: int
    self_audit_model: str
    code_gen_model: Optional[str]
    is_default: bool
    is_active: bool
    usage_count: int
    average_quality_score: Optional[float]
    average_iterations: Optional[float]
    created_at: str


class PromptCreate(BaseModel):
    """Create prompt library entry request."""
    slug: str = Field(..., description="Unique slug")
    name: str = Field(..., description="Display name")
    description: Optional[str] = None
    category: str = Field(..., description="Category: house_style, niche, component, audit, brand")
    prompt_text: str = Field(..., description="The prompt content")
    niche_tags: Optional[List[str]] = None
    component_tags: Optional[List[str]] = None
    priority: int = Field(default=100, description="Lower = higher priority")
    cascade_mode: str = Field(default="append", description="append, prepend, replace")


class PromptResponse(BaseModel):
    """Prompt library entry response."""
    id: str
    slug: str
    name: str
    description: Optional[str]
    category: str
    prompt_text: str
    niche_tags: Optional[List[str]]
    component_tags: Optional[List[str]]
    priority: int
    cascade_mode: str
    is_active: bool
    created_at: str


class MockupAssetResponse(BaseModel):
    """Mockup asset response."""
    id: str
    lead_id: str
    preview_url: Optional[str]
    sandbox_id: Optional[str]
    quality_score: Optional[int]
    iteration_count: int
    brand_dna: dict
    audit_results: Optional[dict]
    created_at: str


class RegenerateRequest(BaseModel):
    """Regenerate mockup request."""
    focus_areas: Optional[List[str]] = Field(
        None,
        description="Specific areas to focus on during regeneration"
    )


class ApprovalItemResponse(BaseModel):
    """Approval item response."""
    id: str
    lead_id: Optional[str]
    asset_id: Optional[str]
    type: str
    status: str
    title: str
    description: Optional[str]
    preview_data: Optional[dict]
    quality_score: Optional[int]
    created_at: str


# ====================
# MCP Tools CRUD
# ====================

@router.post(
    "/mcp-tools",
    response_model=MCPToolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a custom MCP tool"
)
async def create_mcp_tool(
    tool_data: MCPToolCreate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Register a new custom MCP tool for use in architect workflows.

    Categories:
    - brand: Brand extraction/analysis tools
    - code: Code generation tools
    - audit: Quality audit tools
    - content: Content generation tools
    - integration: External service integrations
    """
    user_id = current_user["id"]

    # Validate category
    valid_categories = ["brand", "code", "audit", "content", "integration"]
    if tool_data.category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {valid_categories}"
        )

    try:
        tool = await db.create_mcp_tool({
            "user_id": user_id,
            "slug": tool_data.slug,
            "name": tool_data.name,
            "description": tool_data.description,
            "category": tool_data.category,
            "mcp_server_config": tool_data.mcp_server_config,
            "tool_schema": tool_data.tool_schema,
            "timeout_ms": tool_data.timeout_ms,
            "retry_attempts": tool_data.retry_attempts,
            "is_active": True,
            "usage_count": 0
        })

        logger.info("MCP tool created", tool_id=tool["id"], slug=tool_data.slug)
        return MCPToolResponse(**tool)

    except Exception as e:
        if "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tool with slug '{tool_data.slug}' already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get(
    "/mcp-tools",
    response_model=List[MCPToolResponse],
    summary="List MCP tools"
)
async def list_mcp_tools(
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """List all MCP tools registered by the current user."""
    user_id = current_user["id"]

    tools = await db.get_mcp_tools(
        user_id=user_id,
        categories=[category] if category else None
    )

    return [MCPToolResponse(**tool) for tool in tools]


@router.delete(
    "/mcp-tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete MCP tool"
)
async def delete_mcp_tool(
    tool_id: str,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """Delete a custom MCP tool."""
    user_id = current_user["id"]

    # Verify ownership
    tool = await db.get_mcp_tool(tool_id)
    if not tool or tool.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found"
        )

    await db.delete_mcp_tool(tool_id)
    logger.info("MCP tool deleted", tool_id=tool_id)


# ====================
# Architect Workflows CRUD
# ====================

@router.post(
    "/workflows",
    response_model=ArchitectWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create architect workflow"
)
async def create_workflow(
    workflow_data: ArchitectWorkflowCreate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Create a custom architect workflow with n8n-style graph.

    The workflow graph should contain:
    - nodes: Array of node definitions with id, type, tool, conditions
    - edges: Array of edge definitions with source, target, label
    - entry: ID of the entry node
    """
    user_id = current_user["id"]

    # Validate graph structure
    graph = workflow_data.graph
    if "nodes" not in graph or "edges" not in graph:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Graph must contain 'nodes' and 'edges'"
        )

    try:
        workflow = await db.create_architect_workflow({
            "user_id": user_id,
            "slug": workflow_data.slug,
            "name": workflow_data.name,
            "description": workflow_data.description,
            "graph": graph,
            "quality_threshold": workflow_data.quality_threshold,
            "max_iterations": workflow_data.max_iterations,
            "self_audit_model": workflow_data.self_audit_model,
            "code_gen_model": workflow_data.code_gen_model,
            "is_default": False,
            "is_active": True,
            "usage_count": 0
        })

        logger.info("Architect workflow created", workflow_id=workflow["id"])
        return ArchitectWorkflowResponse(**workflow)

    except Exception as e:
        if "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Workflow with slug '{workflow_data.slug}' already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get(
    "/workflows",
    response_model=List[ArchitectWorkflowResponse],
    summary="List architect workflows"
)
async def list_workflows(
    include_system: bool = Query(True, description="Include system default workflows"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """List all architect workflows available to the user."""
    user_id = current_user["id"]

    workflows = await db.get_architect_workflows(
        user_id=user_id,
        include_system=include_system
    )

    return [ArchitectWorkflowResponse(**w) for w in workflows]


@router.put(
    "/workflows/{workflow_id}",
    response_model=ArchitectWorkflowResponse,
    summary="Update architect workflow"
)
async def update_workflow(
    workflow_id: str,
    updates: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """Update an architect workflow."""
    user_id = current_user["id"]

    # Verify ownership
    workflow = await db.get_architect_workflow(workflow_id)
    if not workflow or workflow.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    # Don't allow updating system workflows
    if workflow.get("user_id") is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update system workflows"
        )

    updated = await db.update_architect_workflow(workflow_id, updates)
    return ArchitectWorkflowResponse(**updated)


# ====================
# Prompt Library CRUD
# ====================

@router.post(
    "/prompts",
    response_model=PromptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create prompt library entry"
)
async def create_prompt(
    prompt_data: PromptCreate,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Create a new prompt in the library.

    Categories:
    - house_style: Agency-specific design rules
    - niche: Industry-specific guidelines
    - component: Section-specific requirements
    - audit: Quality audit criteria
    - brand: Brand-related prompts
    """
    user_id = current_user["id"]

    valid_categories = ["house_style", "niche", "component", "audit", "brand"]
    if prompt_data.category not in valid_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {valid_categories}"
        )

    valid_modes = ["append", "prepend", "replace"]
    if prompt_data.cascade_mode not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cascade_mode. Must be one of: {valid_modes}"
        )

    try:
        prompt = await db.create_prompt({
            "user_id": user_id,
            "slug": prompt_data.slug,
            "name": prompt_data.name,
            "description": prompt_data.description,
            "category": prompt_data.category,
            "prompt_text": prompt_data.prompt_text,
            "niche_tags": prompt_data.niche_tags,
            "component_tags": prompt_data.component_tags,
            "priority": prompt_data.priority,
            "cascade_mode": prompt_data.cascade_mode,
            "is_active": True
        })

        logger.info("Prompt created", prompt_id=prompt["id"])
        return PromptResponse(**prompt)

    except Exception as e:
        if "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Prompt with slug '{prompt_data.slug}' already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get(
    "/prompts",
    response_model=List[PromptResponse],
    summary="List prompt library"
)
async def list_prompts(
    category: Optional[str] = Query(None, description="Filter by category"),
    include_system: bool = Query(True, description="Include system default prompts"),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """List all prompts in the library."""
    user_id = current_user["id"]

    prompts = await db.get_prompts(
        user_id=user_id,
        category=category,
        include_system=include_system
    )

    return [PromptResponse(**p) for p in prompts]


@router.put(
    "/prompts/{prompt_id}",
    response_model=PromptResponse,
    summary="Update prompt"
)
async def update_prompt(
    prompt_id: str,
    updates: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """Update a prompt library entry."""
    user_id = current_user["id"]

    prompt = await db.get_prompt(prompt_id)
    if not prompt or prompt.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt not found"
        )

    updated = await db.update_prompt(prompt_id, updates)
    return PromptResponse(**updated)


# ====================
# Lead Preview & Regeneration
# ====================

@router.get(
    "/leads/{lead_id}/preview",
    response_model=MockupAssetResponse,
    summary="Get live preview for lead"
)
async def get_lead_preview(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get the live E2B preview URL and mockup details for a lead.

    Returns the latest generated asset with preview URL.
    """
    user_id = current_user["id"]

    # Verify lead ownership
    lead = await db.get_lead(lead_id)
    if not lead or lead.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    # Get latest asset
    asset = await db.get_latest_asset_for_lead(lead_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mockup generated for this lead yet"
        )

    return MockupAssetResponse(**asset)


@router.post(
    "/leads/{lead_id}/regenerate",
    response_model=MockupAssetResponse,
    summary="Trigger mockup regeneration"
)
async def regenerate_mockup(
    lead_id: str,
    request: RegenerateRequest = Body(default=RegenerateRequest()),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Trigger regeneration of mockup for a lead.

    Optionally specify focus_areas to guide the regeneration:
    - "Improve visual hierarchy - clearer CTA and logical flow"
    - "Better match brand colors and typography"
    - "Fix spacing and alignment issues"
    - "Improve mobile responsiveness"
    """
    user_id = current_user["id"]

    # Verify lead ownership
    lead = await db.get_lead(lead_id)
    if not lead or lead.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    # Queue regeneration job
    # In production, this would queue a background job
    # For now, we create a placeholder response

    logger.info(
        "Regeneration requested",
        lead_id=lead_id,
        focus_areas=request.focus_areas
    )

    # Get current asset to determine iteration count
    current_asset = await db.get_latest_asset_for_lead(lead_id)
    current_iteration = current_asset.get("iteration_count", 1) if current_asset else 0

    # Create a pending asset record
    new_asset = await db.create_generated_asset({
        "lead_id": lead_id,
        "asset_type": "mockup_image",
        "storage_provider": "e2b",
        "storage_path": "",
        "iteration_count": current_iteration + 1,
        "parent_asset_id": current_asset.get("id") if current_asset else None,
        "is_latest": True,
        "metadata": {
            "status": "regenerating",
            "focus_areas": request.focus_areas
        }
    })

    return MockupAssetResponse(**new_asset)


@router.get(
    "/leads/{lead_id}/iterations",
    response_model=List[MockupAssetResponse],
    summary="Get iteration history"
)
async def get_iteration_history(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """
    Get the iteration history for a lead's mockups.

    Returns all generated assets in chronological order.
    """
    user_id = current_user["id"]

    # Verify lead ownership
    lead = await db.get_lead(lead_id)
    if not lead or lead.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )

    assets = await db.get_assets_for_lead(lead_id)
    return [MockupAssetResponse(**asset) for asset in assets]


# ====================
# Approval Queue
# ====================

@router.get(
    "/approvals",
    response_model=List[ApprovalItemResponse],
    summary="List approval items"
)
async def list_approvals(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    type: Optional[str] = Query(None, description="Filter by type: workflow_gate, mockup, etc."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """List approval items for the current user."""
    user_id = current_user["id"]

    approvals = await db.get_approval_items(
        user_id=user_id,
        status=status,
        type=type,
        limit=limit,
        offset=offset
    )

    return [ApprovalItemResponse(**a) for a in approvals]


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalItemResponse,
    summary="Approve an item"
)
async def approve_item(
    approval_id: str,
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """Approve an approval item."""
    user_id = current_user["id"]

    approval = await db.get_approval_item(approval_id)
    if not approval or approval.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval item not found"
        )

    if approval.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item is not pending approval"
        )

    updated = await db.update_approval_item(approval_id, {
        "status": "approved",
        "decided_by": user_id,
        "decided_at": "now()"
    })

    logger.info("Approval item approved", approval_id=approval_id)
    return ApprovalItemResponse(**updated)


@router.post(
    "/approvals/{approval_id}/reject",
    response_model=ApprovalItemResponse,
    summary="Reject an item"
)
async def reject_item(
    approval_id: str,
    reason: Optional[str] = Body(None, embed=True),
    current_user: dict = Depends(get_current_user),
    db: SupabaseService = Depends(get_supabase_service),
):
    """Reject an approval item with optional reason."""
    user_id = current_user["id"]

    approval = await db.get_approval_item(approval_id)
    if not approval or approval.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval item not found"
        )

    if approval.get("status") != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item is not pending approval"
        )

    updated = await db.update_approval_item(approval_id, {
        "status": "rejected",
        "decided_by": user_id,
        "decided_at": "now()",
        "decision_reason": reason
    })

    logger.info("Approval item rejected", approval_id=approval_id, reason=reason)
    return ApprovalItemResponse(**updated)
