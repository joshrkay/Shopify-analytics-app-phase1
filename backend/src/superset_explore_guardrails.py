"""
Superset Explore guardrail validation engine.

This module provides guardrail validation and bypass evaluation logic for
Explore Mode requests. It is designed to be used by services integrating
Superset or Explore workflows.

SECURITY:
- Guardrails are enforced by default.
- Bypass requires an active, approved exception record.
- RLS and tenant isolation are never disabled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class GuardrailLimits:
    """Guardrail limits for Explore queries."""

    max_date_range_days: int
    max_group_by_dimensions: int
    max_metrics_per_query: int
    max_filters: int
    row_limit: int
    query_timeout_seconds: int


@dataclass(frozen=True)
class DatasetRules:
    """Dataset-level rules for Explore queries."""

    allowed_dimensions: Sequence[str]
    allowed_metrics: Sequence[str]
    allowed_visualizations: Sequence[str]
    restricted_columns: Sequence[str]


@dataclass
class GuardrailDecision:
    """Result of guardrail validation."""

    allowed: bool
    error_message: Optional[str] = None
    error_code: Optional[str] = None


class ExploreGuardrailEngine:
    """Validates Explore queries against guardrails with optional bypass."""

    def __init__(self, limits: GuardrailLimits, dataset_rules: Dict[str, DatasetRules]):
        self.limits = limits
        self.dataset_rules = dataset_rules

    def validate_query(
        self,
        *,
        dataset_name: str,
        query_params: Dict,
        bypass_active: bool = False,
    ) -> GuardrailDecision:
        """Validate query parameters, applying bypass if active."""
        rules = self.dataset_rules.get(dataset_name)
        if not rules:
            return GuardrailDecision(False, "Dataset not found", "DATASET_NOT_FOUND")

        dimensions = query_params.get("dimensions", [])
        for dim in dimensions:
            if dim not in rules.allowed_dimensions:
                return GuardrailDecision(
                    False,
                    f"Dimension '{dim}' is not allowed",
                    "DIMENSION_NOT_ALLOWED",
                )
            if dim in rules.restricted_columns:
                return GuardrailDecision(
                    False,
                    f"Column '{dim}' is restricted",
                    "COLUMN_RESTRICTED",
                )

        metrics = query_params.get("metrics", [])
        for metric in metrics:
            if metric not in rules.allowed_metrics:
                return GuardrailDecision(
                    False,
                    f"Metric '{metric}' is not allowed",
                    "METRIC_NOT_ALLOWED",
                )

        if not bypass_active and len(metrics) > self.limits.max_metrics_per_query:
            return GuardrailDecision(
                False,
                f"Maximum {self.limits.max_metrics_per_query} metrics per query",
                "TOO_MANY_METRICS",
            )

        start_date = query_params.get("start_date")
        end_date = query_params.get("end_date")
        if start_date and end_date:
            if end_date < start_date:
                return GuardrailDecision(
                    False,
                    "End date must be after start date",
                    "INVALID_DATE_RANGE",
                )
            if not bypass_active:
                date_range_days = (end_date - start_date).days
                if date_range_days > self.limits.max_date_range_days:
                    return GuardrailDecision(
                        False,
                        f"Date range exceeds maximum of {self.limits.max_date_range_days} days",
                        "DATE_RANGE_EXCEEDED",
                    )

        group_by = query_params.get("group_by", [])
        if not bypass_active and len(group_by) > self.limits.max_group_by_dimensions:
            return GuardrailDecision(
                False,
                f"Maximum {self.limits.max_group_by_dimensions} group-by dimensions allowed",
                "TOO_MANY_GROUP_BY",
            )

        filters = query_params.get("filters", [])
        if not bypass_active and len(filters) > self.limits.max_filters:
            return GuardrailDecision(
                False,
                f"Maximum {self.limits.max_filters} filters allowed",
                "TOO_MANY_FILTERS",
            )

        row_limit = query_params.get("row_limit")
        if row_limit is not None and not bypass_active and row_limit > self.limits.row_limit:
            return GuardrailDecision(
                False,
                f"Row limit of {row_limit} exceeds maximum of {self.limits.row_limit}",
                "ROW_LIMIT_EXCEEDED",
            )

        viz_type = query_params.get("viz_type")
        if viz_type and viz_type not in rules.allowed_visualizations:
            return GuardrailDecision(
                False,
                f"Visualization '{viz_type}' not allowed",
                "VIZ_NOT_ALLOWED",
            )

        return GuardrailDecision(True)


def should_apply_bypass(
    *,
    exception_active: bool,
    now: Optional[datetime] = None,
) -> bool:
    """Evaluate whether a bypass should be applied at runtime."""
    _ = now or datetime.utcnow()
    return exception_active
