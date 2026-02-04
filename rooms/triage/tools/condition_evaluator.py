"""
ConditionEvaluator - Modular Logic Processor for SDR Engine.

Replaces the hard-coded calculate_triage_score function with a flexible
logic gate evaluator that processes AND/OR conditions defined in playbook JSON.

This enables agencies to define custom qualification rules without code changes.

Usage:
    evaluator = ConditionEvaluator(playbook_config.get("logic_gates", {}))

    # Evaluate a gate
    result = evaluator.evaluate_gate("qualification", {
        "triage_score": 75,
        "signals": {"ssl_valid": True, "cms_detected": "shopify"}
    })

    if result.passed:
        # Lead qualifies
        pass
"""
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
import operator
import re
import structlog

logger = structlog.get_logger()


# Supported comparison operators
OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a in b if b else False,
    "not_in": lambda a, b: a not in b if b else True,
    "contains": lambda a, b: b in a if a else False,
    "not_contains": lambda a, b: b not in a if a else True,
    "startswith": lambda a, b: str(a).startswith(str(b)) if a else False,
    "endswith": lambda a, b: str(a).endswith(str(b)) if a else False,
    "matches": lambda a, b: bool(re.search(b, str(a))) if a else False,
    "exists": lambda a, _: a is not None,
    "not_exists": lambda a, _: a is None,
    "empty": lambda a, _: not a,
    "not_empty": lambda a, _: bool(a),
    "between": lambda a, b: b[0] <= a <= b[1] if a is not None and isinstance(b, (list, tuple)) and len(b) == 2 else False,
}


@dataclass
class ConditionResult:
    """Result of evaluating a single condition."""
    field: str
    operator: str
    expected: Any
    actual: Any
    passed: bool
    error: Optional[str] = None


@dataclass
class EvaluationResult:
    """Result of evaluating a logic gate."""
    passed: bool
    gate_name: str
    operator: str
    condition_results: List[ConditionResult] = field(default_factory=list)
    nested_results: List['EvaluationResult'] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            "passed": self.passed,
            "gate_name": self.gate_name,
            "operator": self.operator,
            "condition_results": [
                {
                    "field": cr.field,
                    "operator": cr.operator,
                    "expected": cr.expected,
                    "actual": cr.actual,
                    "passed": cr.passed,
                    "error": cr.error
                }
                for cr in self.condition_results
            ],
            "nested_results": [nr.to_dict() for nr in self.nested_results],
            "error": self.error
        }


class ConditionEvaluator:
    """
    Evaluates playbook logic gates against lead/signal data.

    Supports:
    - Simple conditions: {"field": "score", "op": ">=", "value": 60}
    - AND/OR operators: {"operator": "AND", "conditions": [...]}
    - Nested conditions: Conditions can contain sub-gates
    - Dot notation for nested fields: "signals.ssl_valid"
    """

    def __init__(self, logic_gates: Dict[str, Any]):
        """
        Initialize the evaluator with logic gates from playbook config.

        Args:
            logic_gates: Dict of gate_name -> gate_definition
        """
        self.logic_gates = logic_gates

    def get_nested_value(self, data: dict, field_path: str) -> Any:
        """
        Get value from nested dict using dot notation.

        Args:
            data: Data dictionary to traverse
            field_path: Dot-separated path (e.g., 'signals.ssl_valid')

        Returns:
            Value at path or None if not found
        """
        keys = field_path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif hasattr(value, key):
                value = getattr(value, key)
            else:
                return None
        return value

    def evaluate_condition(self, condition: dict, data: dict) -> ConditionResult:
        """
        Evaluate a single condition against data.

        Args:
            condition: Condition dict with field, op, value
            data: Data to evaluate against

        Returns:
            ConditionResult with pass/fail status
        """
        field_path = condition.get("field", "")
        op = condition.get("op", "==")
        expected = condition.get("value")

        actual = self.get_nested_value(data, field_path)

        if op not in OPERATORS:
            return ConditionResult(
                field=field_path,
                operator=op,
                expected=expected,
                actual=actual,
                passed=False,
                error=f"Unknown operator: {op}"
            )

        try:
            passed = OPERATORS[op](actual, expected)
            return ConditionResult(
                field=field_path,
                operator=op,
                expected=expected,
                actual=actual,
                passed=passed
            )
        except Exception as e:
            logger.warning(
                "Condition evaluation error",
                field=field_path,
                op=op,
                error=str(e)
            )
            return ConditionResult(
                field=field_path,
                operator=op,
                expected=expected,
                actual=actual,
                passed=False,
                error=str(e)
            )

    def evaluate_gate(
        self,
        gate_name: str,
        data: dict,
        _depth: int = 0
    ) -> EvaluationResult:
        """
        Evaluate a named logic gate.

        Args:
            gate_name: Name of the gate to evaluate
            data: Data to evaluate against
            _depth: Recursion depth (for cycle detection)

        Returns:
            EvaluationResult with pass/fail status and details
        """
        if _depth > 10:
            return EvaluationResult(
                passed=False,
                gate_name=gate_name,
                operator="ERROR",
                error="Max recursion depth exceeded - check for circular gate references"
            )

        if gate_name not in self.logic_gates:
            return EvaluationResult(
                passed=False,
                gate_name=gate_name,
                operator="ERROR",
                error=f"Gate '{gate_name}' not found in logic_gates"
            )

        gate = self.logic_gates[gate_name]
        return self._evaluate_gate_definition(gate, gate_name, data, _depth)

    def _evaluate_gate_definition(
        self,
        gate: Union[dict, list],
        gate_name: str,
        data: dict,
        _depth: int
    ) -> EvaluationResult:
        """
        Evaluate a gate definition (can be called recursively for nested conditions).

        Args:
            gate: Gate definition (dict with operator/conditions or condition dict)
            gate_name: Name for logging
            data: Data to evaluate against
            _depth: Recursion depth

        Returns:
            EvaluationResult
        """
        # Handle simple condition (no operator, just field/op/value)
        if "field" in gate and "operator" not in gate:
            condition_result = self.evaluate_condition(gate, data)
            return EvaluationResult(
                passed=condition_result.passed,
                gate_name=gate_name,
                operator="SINGLE",
                condition_results=[condition_result]
            )

        # Handle gate with operator (AND/OR/NOT)
        gate_operator = gate.get("operator", "AND").upper()
        conditions = gate.get("conditions", [])

        if not conditions:
            return EvaluationResult(
                passed=True,  # Empty conditions = always pass
                gate_name=gate_name,
                operator=gate_operator,
                error="No conditions defined"
            )

        condition_results = []
        nested_results = []
        passes = []

        for condition in conditions:
            # Check if condition is a nested gate (has 'operator' key)
            if "operator" in condition and "conditions" in condition:
                nested_result = self._evaluate_gate_definition(
                    condition,
                    f"{gate_name}.nested",
                    data,
                    _depth + 1
                )
                nested_results.append(nested_result)
                passes.append(nested_result.passed)
            # Check if condition references another gate by name
            elif "gate" in condition:
                ref_gate_name = condition["gate"]
                ref_result = self.evaluate_gate(ref_gate_name, data, _depth + 1)
                nested_results.append(ref_result)
                passes.append(ref_result.passed)
            # Simple condition
            else:
                result = self.evaluate_condition(condition, data)
                condition_results.append(result)
                passes.append(result.passed)

        # Apply operator
        if gate_operator == "AND":
            passed = all(passes)
        elif gate_operator == "OR":
            passed = any(passes)
        elif gate_operator == "NOT":
            passed = not any(passes)
        elif gate_operator == "XOR":
            passed = sum(passes) == 1
        elif gate_operator == "NAND":
            passed = not all(passes)
        elif gate_operator == "NOR":
            passed = not any(passes)
        else:
            passed = all(passes)  # Default to AND

        return EvaluationResult(
            passed=passed,
            gate_name=gate_name,
            operator=gate_operator,
            condition_results=condition_results,
            nested_results=nested_results
        )

    def evaluate_all_gates(self, data: dict) -> Dict[str, EvaluationResult]:
        """
        Evaluate all defined gates against data.

        Args:
            data: Data to evaluate against

        Returns:
            Dict mapping gate_name to EvaluationResult
        """
        results = {}
        for gate_name in self.logic_gates:
            results[gate_name] = self.evaluate_gate(gate_name, data)
        return results


def calculate_score_from_signals(
    signals: dict,
    scoring_config: dict,
    thresholds_config: dict
) -> int:
    """
    Calculate a numeric score from signals using weighted scoring.

    This provides backward compatibility with the old calculate_triage_score function
    while allowing dynamic weight configuration from playbooks.

    Args:
        signals: Signal data dict
        scoring_config: Weights dict (e.g., {"pagespeed_weight": 30, "ssl_weight": 20})
        thresholds_config: Thresholds dict (e.g., {"pagespeed_threshold": 50})

    Returns:
        Score from 0-100
    """
    score = 0
    max_score = 0

    # PageSpeed (lower is worse = higher opportunity score)
    pagespeed_weight = scoring_config.get("pagespeed_weight", 30)
    max_score += pagespeed_weight
    pagespeed = signals.get("pagespeed_score")
    if pagespeed is not None:
        threshold = thresholds_config.get("pagespeed_threshold", 50)
        if pagespeed < threshold:
            score += int(pagespeed_weight * (1 - pagespeed / 100))
        elif pagespeed < 70:
            score += int(pagespeed_weight * 0.5)

    # SSL (invalid = high opportunity)
    ssl_weight = scoring_config.get("ssl_weight", 20)
    max_score += ssl_weight
    ssl_valid = signals.get("ssl_valid")
    if ssl_valid is False:
        score += ssl_weight
    elif signals.get("ssl_expires_days") is not None and signals.get("ssl_expires_days") < 30:
        score += int(ssl_weight * 0.7)

    # Mobile (not responsive = high opportunity)
    mobile_weight = scoring_config.get("mobile_weight", 25)
    max_score += mobile_weight
    if signals.get("mobile_responsive") is False:
        score += mobile_weight
    elif signals.get("has_viewport_meta") is False:
        score += int(mobile_weight * 0.8)

    # Copyright year (older = higher opportunity)
    copyright_weight = scoring_config.get("copyright_weight", 25)
    max_score += copyright_weight
    copyright_year = signals.get("copyright_year")
    if copyright_year is not None:
        current_year = datetime.now().year
        max_age = thresholds_config.get("copyright_max_age_years", 2)
        years_old = current_year - copyright_year
        if years_old >= max_age:
            age_factor = min(years_old / 5, 1.0)
            score += int(copyright_weight * age_factor)

    # Ad pixels (present = business spending money = opportunity)
    ad_pixel_weight = scoring_config.get("ad_pixel_weight", 0)
    if ad_pixel_weight > 0:
        max_score += ad_pixel_weight
        if signals.get("has_meta_pixel") or signals.get("has_google_ads"):
            score += int(ad_pixel_weight * 0.7)
            if signals.get("has_meta_pixel") and signals.get("has_google_ads"):
                score += int(ad_pixel_weight * 0.3)

    # Normalize to 0-100
    if max_score > 0:
        final_score = int((score / max_score) * 100)
    else:
        final_score = 0

    return final_score
