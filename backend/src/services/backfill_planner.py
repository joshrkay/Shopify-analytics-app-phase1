"""
Backfill planner — determines what needs to be rebuilt for a given
tenant, source system, and date range.

Understands the full dbt dependency chain:
    raw → staging → canonical → semantic → metrics/marts

Produces an ordered execution plan with cost estimates.

Story 3.4 - Backfill Planning
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Layer definitions
# =============================================================================


class ModelLayer(str, Enum):
    """Pipeline layer — execution order follows ordinal value."""
    RAW = "raw"
    STAGING = "staging"
    CANONICAL = "canonical"
    ATTRIBUTION = "attribution"
    SEMANTIC = "semantic"
    METRICS = "metrics"
    MARTS = "marts"

    @property
    def order(self) -> int:
        return list(ModelLayer).index(self)


# =============================================================================
# Model & source registry
# =============================================================================


@dataclass(frozen=True)
class DbtModel:
    """A dbt model with its layer, materialisation, and dependencies."""
    name: str
    layer: ModelLayer
    materialization: str  # "view", "incremental", "table"
    depends_on: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


# Canonical list of raw source tables per source system.
# Keys match SourceSystem enum values from backfill_request.py.
SOURCE_INGESTION_TABLES: dict[str, list[str]] = {
    "shopify": [
        "_airbyte_raw_shopify_orders",
        "_airbyte_raw_shopify_customers",
    ],
    "facebook": [
        "_airbyte_raw_meta_ads",
    ],
    "google": [
        "_airbyte_raw_google_ads",
    ],
    "tiktok": [
        "_airbyte_raw_tiktok_ads",
    ],
    "snapchat": [
        "_airbyte_raw_snapchat_ads",
    ],
    "klaviyo": [
        "_airbyte_raw_klaviyo_events",
    ],
    "recharge": [],
    "pinterest": [],
    "amazon": [],
    "ga4": [],
}


# Staging models that directly consume each source system.
SOURCE_TO_STAGING: dict[str, list[str]] = {
    "shopify": ["stg_shopify_orders", "stg_shopify_customers"],
    "facebook": ["stg_facebook_ads_performance"],
    "google": ["stg_google_ads_performance"],
    "tiktok": ["stg_tiktok_ads_performance"],
    "snapchat": ["stg_snapchat_ads"],
    "klaviyo": ["stg_klaviyo_events", "stg_email_campaigns"],
    "recharge": [],
    "pinterest": [],
    "amazon": [],
    "ga4": [],
}


# Full model registry — encodes the dbt dependency graph.
MODEL_REGISTRY: dict[str, DbtModel] = {
    # --- Staging (Layer 2) ---
    "stg_shopify_orders": DbtModel(
        "stg_shopify_orders", ModelLayer.STAGING, "view",
    ),
    "stg_shopify_customers": DbtModel(
        "stg_shopify_customers", ModelLayer.STAGING, "view",
    ),
    "stg_facebook_ads_performance": DbtModel(
        "stg_facebook_ads_performance", ModelLayer.STAGING, "view",
    ),
    "stg_google_ads_performance": DbtModel(
        "stg_google_ads_performance", ModelLayer.STAGING, "view",
    ),
    "stg_tiktok_ads_performance": DbtModel(
        "stg_tiktok_ads_performance", ModelLayer.STAGING, "view",
    ),
    "stg_snapchat_ads": DbtModel(
        "stg_snapchat_ads", ModelLayer.STAGING, "view",
    ),
    "stg_klaviyo_events": DbtModel(
        "stg_klaviyo_events", ModelLayer.STAGING, "view",
    ),
    "stg_email_campaigns": DbtModel(
        "stg_email_campaigns", ModelLayer.STAGING, "view",
        depends_on=("stg_klaviyo_events",),
    ),
    "dim_ad_accounts": DbtModel(
        "dim_ad_accounts", ModelLayer.STAGING, "table",
        depends_on=("stg_facebook_ads_performance", "stg_google_ads_performance"),
        tags=("dimension",),
    ),
    "dim_campaigns": DbtModel(
        "dim_campaigns", ModelLayer.STAGING, "table",
        depends_on=("stg_facebook_ads_performance", "stg_google_ads_performance"),
        tags=("dimension",),
    ),
    # --- Canonical (Layer 3) ---
    "orders": DbtModel(
        "orders", ModelLayer.CANONICAL, "incremental",
        depends_on=("stg_shopify_orders",),
    ),
    "fact_orders_v1": DbtModel(
        "fact_orders_v1", ModelLayer.CANONICAL, "incremental",
        depends_on=("stg_shopify_orders",),
        tags=("versioned",),
    ),
    "marketing_spend": DbtModel(
        "marketing_spend", ModelLayer.CANONICAL, "incremental",
        depends_on=(
            "stg_facebook_ads_performance",
            "stg_google_ads_performance",
            "stg_tiktok_ads_performance",
            "stg_snapchat_ads",
        ),
    ),
    "fact_marketing_spend_v1": DbtModel(
        "fact_marketing_spend_v1", ModelLayer.CANONICAL, "incremental",
        depends_on=(
            "stg_facebook_ads_performance",
            "stg_google_ads_performance",
            "stg_tiktok_ads_performance",
            "stg_snapchat_ads",
        ),
        tags=("versioned",),
    ),
    "campaign_performance": DbtModel(
        "campaign_performance", ModelLayer.CANONICAL, "incremental",
        depends_on=(
            "stg_facebook_ads_performance",
            "stg_google_ads_performance",
        ),
    ),
    "fact_campaign_performance_v1": DbtModel(
        "fact_campaign_performance_v1", ModelLayer.CANONICAL, "incremental",
        depends_on=(
            "stg_facebook_ads_performance",
            "stg_google_ads_performance",
        ),
        tags=("versioned",),
    ),
    # --- Attribution (Layer 4) ---
    "last_click": DbtModel(
        "last_click", ModelLayer.ATTRIBUTION, "view",
        depends_on=("orders", "campaign_performance"),
    ),
    # --- Semantic (Layer 5) ---
    "sem_orders_v1": DbtModel(
        "sem_orders_v1", ModelLayer.SEMANTIC, "view",
        depends_on=("orders",),
        tags=("semantic", "immutable"),
    ),
    "sem_marketing_spend_v1": DbtModel(
        "sem_marketing_spend_v1", ModelLayer.SEMANTIC, "view",
        depends_on=("marketing_spend",),
        tags=("semantic", "immutable"),
    ),
    "sem_campaign_performance_v1": DbtModel(
        "sem_campaign_performance_v1", ModelLayer.SEMANTIC, "view",
        depends_on=("campaign_performance",),
        tags=("semantic", "immutable"),
    ),
    "fact_orders_current": DbtModel(
        "fact_orders_current", ModelLayer.SEMANTIC, "view",
        depends_on=("sem_orders_v1",),
        tags=("semantic", "governed"),
    ),
    "fact_marketing_spend_current": DbtModel(
        "fact_marketing_spend_current", ModelLayer.SEMANTIC, "view",
        depends_on=("sem_marketing_spend_v1",),
        tags=("semantic", "governed"),
    ),
    "fact_campaign_performance_current": DbtModel(
        "fact_campaign_performance_current", ModelLayer.SEMANTIC, "view",
        depends_on=("sem_campaign_performance_v1",),
        tags=("semantic", "governed"),
    ),
    # --- Metrics (Layer 6) ---
    "fct_revenue": DbtModel(
        "fct_revenue", ModelLayer.METRICS, "view",
        depends_on=("orders",),
    ),
    "fct_roas": DbtModel(
        "fct_roas", ModelLayer.METRICS, "view",
        depends_on=("last_click", "fct_revenue", "marketing_spend"),
    ),
    "fct_cac": DbtModel(
        "fct_cac", ModelLayer.METRICS, "view",
        depends_on=("orders", "last_click", "fct_revenue", "marketing_spend"),
    ),
    "fct_aov": DbtModel(
        "fct_aov", ModelLayer.METRICS, "view",
        depends_on=("fct_revenue",),
    ),
    "fct_marketing_metrics": DbtModel(
        "fct_marketing_metrics", ModelLayer.METRICS, "table",
        depends_on=("marketing_spend", "orders"),
        tags=("marketing",),
    ),
    "metric_roas_v1": DbtModel(
        "metric_roas_v1", ModelLayer.METRICS, "view",
        depends_on=("fct_roas",),
        tags=("immutable",),
    ),
    "metric_roas_v2": DbtModel(
        "metric_roas_v2", ModelLayer.METRICS, "view",
        depends_on=("fct_revenue", "marketing_spend"),
        tags=("immutable",),
    ),
    "metric_roas_current": DbtModel(
        "metric_roas_current", ModelLayer.METRICS, "view",
        depends_on=("metric_roas_v1",),
        tags=("governed",),
    ),
    # --- Marts (Layer 7) ---
    "mart_revenue_metrics": DbtModel(
        "mart_revenue_metrics", ModelLayer.MARTS, "table",
        depends_on=("fct_revenue",),
    ),
    "mart_marketing_metrics": DbtModel(
        "mart_marketing_metrics", ModelLayer.MARTS, "table",
        depends_on=("fct_roas", "fct_cac"),
    ),
}


# Build reverse dependency index once at import time.
_DEPENDENTS: dict[str, set[str]] = {}
for _model_name, _model in MODEL_REGISTRY.items():
    for _dep in _model.depends_on:
        _DEPENDENTS.setdefault(_dep, set()).add(_model_name)


# =============================================================================
# Cost estimation constants
# =============================================================================


# Rough row-per-day estimates by source system (for a typical tenant).
_ROWS_PER_DAY_ESTIMATES: dict[str, int] = {
    "shopify": 500,       # orders + customers
    "facebook": 200,      # ad insights (daily granularity)
    "google": 200,        # ad stats
    "tiktok": 100,        # ad reports
    "snapchat": 50,       # ad reports
    "klaviyo": 300,       # email events
    "recharge": 100,
    "pinterest": 50,
    "amazon": 100,
    "ga4": 1000,
}

# Seconds per 1000 rows by materialisation type.
_SECONDS_PER_1K_ROWS: dict[str, float] = {
    "view": 0.0,          # views are instant (no data moved)
    "incremental": 2.0,   # delete+insert
    "table": 3.0,         # full table rebuild
}


# =============================================================================
# Output data classes
# =============================================================================


@dataclass
class BackfillStep:
    """A single step in the execution plan."""
    order: int
    layer: str
    model_name: str
    materialization: str
    dbt_selector: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class BackfillCostEstimate:
    """Estimated cost for the entire backfill."""
    estimated_raw_rows: int
    estimated_total_rows: int
    estimated_seconds: float
    date_range_days: int


@dataclass
class BackfillPlan:
    """Complete backfill execution plan."""
    tenant_id: str
    source_system: str
    start_date: date
    end_date: date
    ingestion_tables: list[str]
    affected_models: list[str]
    execution_steps: list[BackfillStep]
    cost_estimate: BackfillCostEstimate
    is_partial: bool
    dbt_run_command: str


# =============================================================================
# Planner
# =============================================================================


class BackfillPlanner:
    """
    Determines what needs to be rebuilt for a given (tenant, source, date range).

    Walks the dbt dependency graph forward from the source's staging models
    to find all affected downstream models, then produces an ordered plan.
    """

    def plan(
        self,
        tenant_id: str,
        source_system: str,
        start_date: date,
        end_date: date,
    ) -> BackfillPlan:
        """Build an execution plan for the requested backfill."""
        ingestion_tables = SOURCE_INGESTION_TABLES.get(source_system, [])
        seed_models = SOURCE_TO_STAGING.get(source_system, [])

        if not seed_models:
            logger.warning(
                "No staging models mapped for source system",
                extra={
                    "source_system": source_system,
                    "tenant_id": tenant_id,
                },
            )

        # Walk the graph forward from seed staging models.
        affected = self._resolve_downstream(seed_models)

        # Sort by layer order, then alphabetically within a layer.
        affected_sorted = sorted(
            affected,
            key=lambda name: (
                MODEL_REGISTRY[name].layer.order,
                name,
            ),
        )

        # Build ordered execution steps.
        steps = self._build_steps(affected_sorted)

        # Estimate cost.
        cost = self._estimate_cost(
            source_system, start_date, end_date, affected_sorted
        )

        # Produce dbt command.
        model_selector = " ".join(affected_sorted)
        dbt_vars = (
            f'{{"backfill_start_date": "{start_date.isoformat()}", '
            f'"backfill_end_date": "{end_date.isoformat()}", '
            f'"backfill_tenant_id": "{tenant_id}"}}'
        )
        dbt_cmd = f"dbt run --select {model_selector} --vars '{dbt_vars}'"

        # Check if this is a partial rebuild (not all models in the graph).
        is_partial = len(affected_sorted) < len(MODEL_REGISTRY)

        plan = BackfillPlan(
            tenant_id=tenant_id,
            source_system=source_system,
            start_date=start_date,
            end_date=end_date,
            ingestion_tables=ingestion_tables,
            affected_models=affected_sorted,
            execution_steps=steps,
            cost_estimate=cost,
            is_partial=is_partial,
            dbt_run_command=dbt_cmd,
        )

        logger.info(
            "Backfill plan generated",
            extra={
                "tenant_id": tenant_id,
                "source_system": source_system,
                "affected_model_count": len(affected_sorted),
                "estimated_seconds": cost.estimated_seconds,
                "is_partial": is_partial,
            },
        )

        return plan

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _resolve_downstream(seed_models: list[str]) -> set[str]:
        """
        BFS forward through the dependency graph starting from *seed_models*.

        Returns the set of all affected models (including seeds).
        """
        visited: set[str] = set()
        queue = list(seed_models)

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            if current not in MODEL_REGISTRY:
                continue
            visited.add(current)
            for dependent in _DEPENDENTS.get(current, set()):
                if dependent not in visited:
                    queue.append(dependent)

        return visited

    @staticmethod
    def _build_steps(models_sorted: list[str]) -> list[BackfillStep]:
        """Convert sorted model list into execution steps."""
        steps: list[BackfillStep] = []
        for idx, name in enumerate(models_sorted, start=1):
            model = MODEL_REGISTRY[name]
            steps.append(BackfillStep(
                order=idx,
                layer=model.layer.value,
                model_name=name,
                materialization=model.materialization,
                dbt_selector=name,
                depends_on=list(model.depends_on),
            ))
        return steps

    @staticmethod
    def _estimate_cost(
        source_system: str,
        start_date: date,
        end_date: date,
        affected_models: list[str],
    ) -> BackfillCostEstimate:
        """Rough cost estimate based on date range and model types."""
        days = (end_date - start_date).days + 1
        rows_per_day = _ROWS_PER_DAY_ESTIMATES.get(source_system, 200)
        raw_rows = days * rows_per_day

        # Sum up processing time by materialisation type.
        total_rows = raw_rows
        total_seconds = 0.0
        for name in affected_models:
            model = MODEL_REGISTRY[name]
            sec_per_k = _SECONDS_PER_1K_ROWS.get(
                model.materialization, 1.0
            )
            model_seconds = (raw_rows / 1000) * sec_per_k
            total_seconds += model_seconds
            if model.materialization != "view":
                total_rows += raw_rows

        return BackfillCostEstimate(
            estimated_raw_rows=raw_rows,
            estimated_total_rows=total_rows,
            estimated_seconds=round(total_seconds, 1),
            date_range_days=days,
        )
