"""
Triage Room Tools - Infinite SDR Engine

Fast-pass scanning tools for URL qualification and the
modular node-based SDR engine toolset.

Core Tools (always available):
- FastScanner: HTTP-based URL scanning
- SignalDetector: Extract high-intent signals
- TriageSignals: Signal data structure

Infrastructure:
- ToolRegistry: Dynamic tool registration/loading
- ConditionEvaluator: Logic gate evaluation

Niche Tools (loaded via playbook):
- ShopifyStoreScanner: Shopify store analysis
- ContactVerificationNode: Apollo.io contact enrichment
- LeadIngestNode: CSV/API lead ingestion
- AdPixelSensor: Advertising pixel detection
"""
# Core tools
from rooms.triage.tools.fast_scan import FastScanner, ScanResult, quick_lighthouse_check
from rooms.triage.tools.signal_detector import (
    SignalDetector,
    TriageSignals,
    calculate_triage_score
)

# Infrastructure
from rooms.triage.tools.registry import (
    register_tool,
    get_tool,
    get_tools_by_category,
    list_available_tools,
    list_tools_with_metadata,
    validate_tools_available,
    ToolDefinition,
    ToolCategory
)
from rooms.triage.tools.condition_evaluator import (
    ConditionEvaluator,
    EvaluationResult,
    ConditionResult,
    calculate_score_from_signals
)

# Import niche tools to register them in the registry
# (they register themselves via the @register_tool decorator)
from rooms.triage.tools import shopify_scanner
from rooms.triage.tools import contact_verification
from rooms.triage.tools import lead_ingest
from rooms.triage.tools import ad_pixel_sensor

__all__ = [
    # Core
    "FastScanner",
    "ScanResult",
    "quick_lighthouse_check",
    "SignalDetector",
    "TriageSignals",
    "calculate_triage_score",
    # Infrastructure
    "register_tool",
    "get_tool",
    "get_tools_by_category",
    "list_available_tools",
    "list_tools_with_metadata",
    "validate_tools_available",
    "ToolDefinition",
    "ToolCategory",
    "ConditionEvaluator",
    "EvaluationResult",
    "ConditionResult",
    "calculate_score_from_signals",
]
