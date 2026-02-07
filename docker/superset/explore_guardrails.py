"""
Superset Explore Mode Configuration with Guardrails
Constrains user-driven analysis to safe dimensions, measures, and performance limits.

This module enforces:
- Persona-based access control (merchant vs agency)
- Dataset and column restrictions
- Performance guardrails (date range, row limits, timeouts)
- Visualization type constraints

SECURITY: RLS rules from rls_rules.py are applied independently and always enforced.
"""

import json
import os
import re
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Iterable

from performance_config import PERFORMANCE_LIMITS


class ExplorePersona(str, Enum):
    """
    Exploration personas with different access levels.

    MERCHANT: Standard store owner with basic explore capabilities
    AGENCY: Agency user with slightly expanded metrics access (e.g., ROAS calculations)
    """
    MERCHANT = "merchant"
    AGENCY = "agency"


class VisualizationType(str, Enum):
    """Allowed visualization types in Explore mode."""
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    TABLE = "table"
    NUMBER = "number"
    AREA = "area"


# =============================================================================
# PERFORMANCE GUARDRAILS (Hard Limits)
# =============================================================================

@dataclass(frozen=True)
class PerformanceGuardrails:
    """
    Immutable performance guardrails configuration.

    These are hard limits that cannot be overridden by users.
    """
    max_date_range_days: int = 90
    query_timeout_seconds: int = 20
    row_limit: int = 50000
    max_group_by_dimensions: int = 2
    cache_ttl_minutes: int = 30

    # Additional safety limits
    max_filters: int = 10
    max_metrics_per_query: int = 5


# Default guardrails instance — values sourced from centralized performance_config.py
PERFORMANCE_GUARDRAILS = PerformanceGuardrails(
    max_date_range_days=PERFORMANCE_LIMITS.max_date_range_days,
    query_timeout_seconds=PERFORMANCE_LIMITS.query_timeout_seconds,
    row_limit=PERFORMANCE_LIMITS.row_limit,
    max_group_by_dimensions=PERFORMANCE_LIMITS.max_group_by_dimensions,
    cache_ttl_minutes=PERFORMANCE_LIMITS.cache_ttl_minutes,
    max_filters=PERFORMANCE_LIMITS.max_filters,
    max_metrics_per_query=PERFORMANCE_LIMITS.max_metrics_per_query,
)


# =============================================================================
# DATASET EXPLORE CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class DatasetGuardrailOverrides:
    """
    Per-dataset guardrail overrides loaded from YAML configs.

    Values set here override the global PERFORMANCE_GUARDRAILS for this
    dataset only. None means "use global default".
    """
    max_date_range_days: Optional[int] = None
    query_timeout_seconds: Optional[int] = None
    row_limit: Optional[int] = None
    cache_ttl_minutes: Optional[int] = None


@dataclass(frozen=True)
class DatasetExploreConfig:
    """Configuration for a single explorable dataset."""
    enabled: bool
    allowed_dimensions: FrozenSet[str]
    allowed_metrics: FrozenSet[str]
    allowed_visualizations: FrozenSet[VisualizationType]
    restricted_columns: FrozenSet[str]  # Columns to never expose
    description: str
    date_column: str  # Primary date column for date range filtering
    guardrail_overrides: Optional[DatasetGuardrailOverrides] = None


# Dataset configurations by name
DATASET_EXPLORE_CONFIGS: Dict[str, DatasetExploreConfig] = {
    'fact_orders': DatasetExploreConfig(
        enabled=True,
        allowed_dimensions=frozenset([
            'order_date',
            'channel',
            'campaign_id',
            'product_category',
        ]),
        allowed_metrics=frozenset([
            'SUM(revenue)',
            'COUNT(order_id)',
            'AVG(revenue)',
            'COUNT(DISTINCT customer_id)',
        ]),
        allowed_visualizations=frozenset([
            VisualizationType.LINE,
            VisualizationType.BAR,
            VisualizationType.PIE,
            VisualizationType.TABLE,
            VisualizationType.NUMBER,
        ]),
        restricted_columns=frozenset([
            'payment_method_details',
            'customer_email',
            'customer_phone',
            'customer_address',
            'customer_ip',
        ]),
        description="Explore merchant orders with guardrails",
        date_column='order_date',
        guardrail_overrides=DatasetGuardrailOverrides(
            max_date_range_days=90,
            query_timeout_seconds=20,
            row_limit=50000,
            cache_ttl_minutes=30,
        ),
    ),
    'fact_marketing_spend': DatasetExploreConfig(
        enabled=True,
        allowed_dimensions=frozenset([
            'spend_date',
            'channel',
            'campaign_id',
        ]),
        allowed_metrics=frozenset([
            'SUM(spend)',
            'AVG(spend)',
            'SUM(impressions)',
            'SUM(clicks)',
        ]),
        allowed_visualizations=frozenset([
            VisualizationType.LINE,
            VisualizationType.BAR,
            VisualizationType.TABLE,
            VisualizationType.NUMBER,
        ]),
        restricted_columns=frozenset([
            'api_credentials',
            'account_id',
            'access_token',
        ]),
        description="Explore marketing spend with guardrails",
        date_column='spend_date',
        guardrail_overrides=DatasetGuardrailOverrides(
            max_date_range_days=90,
            query_timeout_seconds=20,
            row_limit=50000,
            cache_ttl_minutes=30,
        ),
    ),
    'fact_campaign_performance': DatasetExploreConfig(
        enabled=True,
        allowed_dimensions=frozenset([
            'campaign_date',
            'campaign_id',
            'channel',
        ]),
        allowed_metrics=frozenset([
            'SUM(revenue)',
            'SUM(spend)',
            'SUM(revenue)/NULLIF(SUM(spend), 0)',  # ROAS
            'SUM(conversions)',
            'AVG(cpa)',
        ]),
        allowed_visualizations=frozenset([
            VisualizationType.LINE,
            VisualizationType.BAR,
            VisualizationType.TABLE,
            VisualizationType.NUMBER,
        ]),
        restricted_columns=frozenset([
            'internal_campaign_id',
            'platform_campaign_id',
        ]),
        description="Explore campaign performance with guardrails",
        date_column='campaign_date',
        guardrail_overrides=DatasetGuardrailOverrides(
            max_date_range_days=90,
            query_timeout_seconds=20,
            row_limit=50000,
            cache_ttl_minutes=30,
        ),
    ),
    # Disabled datasets (PII or sensitive data)
    'dim_customers': DatasetExploreConfig(
        enabled=False,
        allowed_dimensions=frozenset(),
        allowed_metrics=frozenset(),
        allowed_visualizations=frozenset(),
        restricted_columns=frozenset(['*']),  # All columns restricted
        description="Customer PII - Explore disabled",
        date_column='',
    ),
    'dim_products': DatasetExploreConfig(
        enabled=False,
        allowed_dimensions=frozenset(),
        allowed_metrics=frozenset(),
        allowed_visualizations=frozenset(),
        restricted_columns=frozenset(['*']),
        description="Product catalog - Explore disabled",
        date_column='',
    ),
}


# =============================================================================
# PERSONA CONFIGURATIONS
# =============================================================================

@dataclass(frozen=True)
class PersonaConfig:
    """Configuration for an exploration persona."""
    name: str
    allowed_datasets: FrozenSet[str]
    additional_metrics: Dict[str, FrozenSet[str]]  # Dataset -> extra metrics


PERSONA_CONFIGS: Dict[ExplorePersona, PersonaConfig] = {
    ExplorePersona.MERCHANT: PersonaConfig(
        name="Merchant User",
        allowed_datasets=frozenset([
            'fact_orders',
            'fact_marketing_spend',
            'fact_campaign_performance',
        ]),
        additional_metrics={},  # No extra metrics beyond base config
    ),
    ExplorePersona.AGENCY: PersonaConfig(
        name="Agency User",
        allowed_datasets=frozenset([
            'fact_orders',
            'fact_marketing_spend',
            'fact_campaign_performance',
        ]),
        additional_metrics={
            # Agency gets access to ROAS calculation in campaign performance
            'fact_campaign_performance': frozenset([
                'SUM(revenue)/NULLIF(SUM(spend), 0)',  # ROAS
            ]),
        },
    ),
}


# =============================================================================
# SUPERSET FEATURE FLAGS FOR EXPLORE MODE
# =============================================================================

EXPLORE_FEATURE_FLAGS: Dict[str, bool] = {
    # Disable dangerous features
    'ENABLE_CUSTOM_METRICS': False,
    'SQLLAB_BACKEND_PERSISTENCE': False,
    'ALLOW_USER_METRIC_EDIT': False,
    'ENABLE_EXPLORE_JSON_CSRF_PROTECTION': True,
    'SQL_QUERIES_ALLOWED': False,
    'EXPLORE_ALLOW_SUBQUERY': False,
    'ENABLE_ADVANCED_DATA_TYPES': False,
    'ALLOW_ADHOC_SUBQUERY': False,

    # Disable data export
    'ENABLE_PIVOT_TABLE_DATA_EXPORT': False,
    'CSV_EXPORT': False,

    # Enable constrained explore
    'EMBEDDED_SUPERSET': True,
    'ENABLE_TEMPLATE_PROCESSING': False,  # No Jinja in user queries
}


# =============================================================================
# VALIDATION CLASSES
# =============================================================================

@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    should_cancel: bool = True


@dataclass(frozen=True)
class GuardrailBypassException:
    """Approved guardrail bypass exception."""
    id: str
    user_id: str
    requested_by_role: str
    approved_by: str
    approved_by_role: str
    dataset_names: Tuple[str, ...]
    expires_at: datetime
    reason: str
    created_at: datetime


class GuardrailBypassStore:
    """Base store for guardrail bypass exceptions."""

    ALLOWED_REQUESTOR_ROLES = {"super_admin"}
    ALLOWED_APPROVER_ROLES = {"analytics_tech_lead", "security_engineer"}

    @classmethod
    def _is_valid_exception(cls, exception: GuardrailBypassException) -> bool:
        if not exception.id or not exception.user_id:
            return False
        if exception.requested_by_role not in cls.ALLOWED_REQUESTOR_ROLES:
            return False
        if exception.approved_by_role not in cls.ALLOWED_APPROVER_ROLES:
            return False
        if not exception.approved_by:
            return False
        if not exception.dataset_names:
            return False
        if exception.expires_at <= exception.created_at:
            return False
        if exception.expires_at - exception.created_at > timedelta(minutes=60):
            return False
        return True

    def get_active_exception(
        self,
        user_id: str,
        dataset_name: str,
        now: Optional[datetime] = None,
    ) -> Optional[GuardrailBypassException]:
        raise NotImplementedError

    def log_usage(
        self,
        exception: GuardrailBypassException,
        dataset_name: str,
        query_params: Dict,
    ) -> None:
        raise NotImplementedError


class EnvGuardrailBypassStore(GuardrailBypassStore):
    """Loads bypass exceptions from an environment variable payload."""

    def __init__(self, env_var: str = "EXPLORE_GUARDRAIL_EXCEPTIONS"):
        self.env_var = env_var
        self.logger = logging.getLogger("explore_guardrails.bypass")

    def _parse_payload(self, payload: Iterable[dict]) -> List[GuardrailBypassException]:
        exceptions: List[GuardrailBypassException] = []
        for entry in payload:
            try:
                created_at = datetime.fromisoformat(entry["created_at"])
                expires_at = datetime.fromisoformat(entry["expires_at"])
            except (KeyError, ValueError, TypeError):
                continue
            exception = GuardrailBypassException(
                id=str(entry.get("id")),
                user_id=str(entry.get("user_id")),
                requested_by_role=str(entry.get("requested_by_role", "")),
                approved_by=str(entry.get("approved_by", "")),
                approved_by_role=str(entry.get("approved_by_role", "")),
                dataset_names=tuple(entry.get("dataset_names") or []),
                expires_at=expires_at,
                reason=str(entry.get("reason", "")),
                created_at=created_at,
            )
            if not self._is_valid_exception(exception):
                continue
            exceptions.append(exception)
        return exceptions

    def _load_exceptions(self) -> List[GuardrailBypassException]:
        raw = os.getenv(self.env_var)
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.logger.warning("Invalid bypass exceptions payload; ignoring")
            return []
        if not isinstance(payload, list):
            self.logger.warning("Bypass exceptions payload must be a list; ignoring")
            return []
        return self._parse_payload(payload)

    def get_active_exception(
        self,
        user_id: str,
        dataset_name: str,
        now: Optional[datetime] = None,
    ) -> Optional[GuardrailBypassException]:
        now = now or datetime.utcnow()
        for exception in self._load_exceptions():
            if exception.user_id != user_id:
                continue
            if dataset_name not in exception.dataset_names:
                continue
            if exception.expires_at <= now:
                continue
            return exception
        return None

    def log_usage(
        self,
        exception: GuardrailBypassException,
        dataset_name: str,
        query_params: Dict,
    ) -> None:
        self.logger.info(
            "Explore guardrail bypass used",
            extra={
                "exception_id": exception.id,
                "user_id": exception.user_id,
                "requested_by_role": exception.requested_by_role,
                "approved_by": exception.approved_by,
                "approved_by_role": exception.approved_by_role,
                "dataset_name": dataset_name,
                "expires_at": exception.expires_at.isoformat(),
                "reason": exception.reason,
                "query_params": query_params,
            },
        )


class InMemoryGuardrailBypassStore(GuardrailBypassStore):
    """Simple bypass store for tests and local usage."""

    def __init__(self, exceptions: Iterable[GuardrailBypassException]):
        self.exceptions = [
            exception for exception in exceptions if self._is_valid_exception(exception)
        ]
        self.logger = logging.getLogger("explore_guardrails.bypass")

    def get_active_exception(
        self,
        user_id: str,
        dataset_name: str,
        now: Optional[datetime] = None,
    ) -> Optional[GuardrailBypassException]:
        now = now or datetime.utcnow()
        for exception in self.exceptions:
            if exception.user_id != user_id:
                continue
            if dataset_name not in exception.dataset_names:
                continue
            if exception.expires_at <= now:
                continue
            return exception
        return None

    def log_usage(
        self,
        exception: GuardrailBypassException,
        dataset_name: str,
        query_params: Dict,
    ) -> None:
        self.logger.info(
            "Explore guardrail bypass used",
            extra={
                "exception_id": exception.id,
                "user_id": exception.user_id,
                "requested_by_role": exception.requested_by_role,
                "approved_by": exception.approved_by,
                "approved_by_role": exception.approved_by_role,
                "dataset_name": dataset_name,
                "expires_at": exception.expires_at.isoformat(),
                "reason": exception.reason,
                "query_params": query_params,
            },
        )


class ExplorePermissionValidator:
    """
    Validates Explore queries against guardrails.

    Use this validator before executing any Explore query to ensure
    the request complies with persona permissions and performance limits.
    """

    def __init__(
        self,
        persona: ExplorePersona,
        guardrails: PerformanceGuardrails = PERFORMANCE_GUARDRAILS,
        bypass_store: Optional[GuardrailBypassStore] = None,
    ):
        if persona not in PERSONA_CONFIGS:
            raise ValueError(f"Invalid persona: {persona}")
        self.persona = persona
        self.persona_config = PERSONA_CONFIGS[persona]
        self.guardrails = guardrails
        self.bypass_store = bypass_store or EnvGuardrailBypassStore()
        self.logger = logging.getLogger("explore_guardrails.validation")

    def _get_effective_guardrails(
        self,
        dataset_name: str,
    ) -> PerformanceGuardrails:
        """
        Return guardrails for a specific dataset.

        If the dataset has per-dataset overrides, return a PerformanceGuardrails
        with those overrides applied on top of the global defaults. Per-dataset
        limits can only be stricter than (or equal to) global defaults.
        """
        config = DATASET_EXPLORE_CONFIGS.get(dataset_name)
        if config is None or config.guardrail_overrides is None:
            return self.guardrails

        overrides = config.guardrail_overrides
        return PerformanceGuardrails(
            max_date_range_days=min(
                overrides.max_date_range_days or self.guardrails.max_date_range_days,
                self.guardrails.max_date_range_days,
            ),
            query_timeout_seconds=min(
                overrides.query_timeout_seconds or self.guardrails.query_timeout_seconds,
                self.guardrails.query_timeout_seconds,
            ),
            row_limit=min(
                overrides.row_limit or self.guardrails.row_limit,
                self.guardrails.row_limit,
            ),
            cache_ttl_minutes=min(
                overrides.cache_ttl_minutes or self.guardrails.cache_ttl_minutes,
                self.guardrails.cache_ttl_minutes,
            ),
            max_group_by_dimensions=self.guardrails.max_group_by_dimensions,
            max_filters=self.guardrails.max_filters,
            max_metrics_per_query=self.guardrails.max_metrics_per_query,
        )

    def validate_dataset(self, dataset_name: str) -> ValidationResult:
        """Check if dataset is allowed for this persona."""
        # Check if dataset exists
        if dataset_name not in DATASET_EXPLORE_CONFIGS:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' not found",
                error_code="DATASET_NOT_FOUND",
            )

        # Check if dataset is enabled for explore
        config = DATASET_EXPLORE_CONFIGS[dataset_name]
        if not config.enabled:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' is not available for exploration",
                error_code="DATASET_DISABLED",
            )

        # Check if persona has access
        if dataset_name not in self.persona_config.allowed_datasets:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' not allowed for {self.persona_config.name}",
                error_code="DATASET_NOT_ALLOWED",
            )

        return ValidationResult(is_valid=True)

    def validate_dimensions(
        self,
        dataset_name: str,
        dimensions: List[str]
    ) -> ValidationResult:
        """Validate that all dimensions are allowed."""
        if dataset_name not in DATASET_EXPLORE_CONFIGS:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' not found",
                error_code="DATASET_NOT_FOUND",
            )

        config = DATASET_EXPLORE_CONFIGS[dataset_name]
        allowed_dims = config.allowed_dimensions

        for dim in dimensions:
            if dim not in allowed_dims:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Dimension '{dim}' is not allowed. Allowed: {sorted(allowed_dims)}",
                    error_code="DIMENSION_NOT_ALLOWED",
                )

            # Check if dimension is in restricted columns
            if dim in config.restricted_columns:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Column '{dim}' is restricted",
                    error_code="COLUMN_RESTRICTED",
                )

        return ValidationResult(is_valid=True)

    def validate_metrics(
        self,
        dataset_name: str,
        metrics: List[str],
        max_metrics_per_query: Optional[int] = None,
    ) -> ValidationResult:
        """Validate that all metrics are allowed."""
        if dataset_name not in DATASET_EXPLORE_CONFIGS:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' not found",
                error_code="DATASET_NOT_FOUND",
            )

        config = DATASET_EXPLORE_CONFIGS[dataset_name]
        allowed_metrics = set(config.allowed_metrics)

        # Add persona-specific additional metrics
        extra_metrics = self.persona_config.additional_metrics.get(dataset_name, frozenset())
        allowed_metrics.update(extra_metrics)

        max_metrics = max_metrics_per_query or self.guardrails.max_metrics_per_query
        if len(metrics) > max_metrics:
            return ValidationResult(
                is_valid=False,
                error_message=f"Maximum {max_metrics} metrics per query",
                error_code="TOO_MANY_METRICS",
            )

        for metric in metrics:
            # Normalize metric for comparison (remove extra spaces)
            normalized_metric = ' '.join(metric.split())
            if normalized_metric not in allowed_metrics:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Metric '{metric}' is not allowed",
                    error_code="METRIC_NOT_ALLOWED",
                )

        return ValidationResult(is_valid=True)

    def validate_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> ValidationResult:
        """Check date range does not exceed max."""
        if end_date < start_date:
            return ValidationResult(
                is_valid=False,
                error_message="End date must be after start date",
                error_code="INVALID_DATE_RANGE",
            )

        date_range_days = (end_date - start_date).days
        if date_range_days > self.guardrails.max_date_range_days:
            return ValidationResult(
                is_valid=False,
                error_message=f"Date range of {date_range_days} days exceeds maximum of {self.guardrails.max_date_range_days} days",
                error_code="DATE_RANGE_EXCEEDED",
            )

        return ValidationResult(is_valid=True)

    def validate_group_by_count(
        self,
        group_by_dimensions: List[str]
    ) -> ValidationResult:
        """Ensure max group-by dimensions limit."""
        if len(group_by_dimensions) > self.guardrails.max_group_by_dimensions:
            return ValidationResult(
                is_valid=False,
                error_message=f"Maximum {self.guardrails.max_group_by_dimensions} group-by dimensions allowed, got {len(group_by_dimensions)}",
                error_code="TOO_MANY_GROUP_BY",
            )
        return ValidationResult(is_valid=True)

    def validate_visualization(
        self,
        dataset_name: str,
        viz_type: str
    ) -> ValidationResult:
        """Validate visualization type is allowed for dataset."""
        if dataset_name not in DATASET_EXPLORE_CONFIGS:
            return ValidationResult(
                is_valid=False,
                error_message=f"Dataset '{dataset_name}' not found",
                error_code="DATASET_NOT_FOUND",
            )

        config = DATASET_EXPLORE_CONFIGS[dataset_name]

        try:
            viz_enum = VisualizationType(viz_type.lower())
        except ValueError:
            return ValidationResult(
                is_valid=False,
                error_message=f"Visualization type '{viz_type}' is not recognized",
                error_code="VIZ_NOT_RECOGNIZED",
            )

        if viz_enum not in config.allowed_visualizations:
            allowed = [v.value for v in config.allowed_visualizations]
            return ValidationResult(
                is_valid=False,
                error_message=f"Visualization '{viz_type}' not allowed. Allowed: {sorted(allowed)}",
                error_code="VIZ_NOT_ALLOWED",
            )

        return ValidationResult(is_valid=True)

    def validate_filters_count(
        self,
        filters: List[dict],
        max_filters: Optional[int] = None,
    ) -> ValidationResult:
        """Validate number of filters doesn't exceed limit."""
        limit = max_filters or self.guardrails.max_filters
        if len(filters) > limit:
            return ValidationResult(
                is_valid=False,
                error_message=f"Maximum {limit} filters allowed",
                error_code="TOO_MANY_FILTERS",
            )
        return ValidationResult(is_valid=True)

    def validate_query(
        self,
        dataset_name: str,
        query_params: Dict,
        user_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Comprehensive query validation.

        Uses per-dataset guardrail overrides when available, falling back
        to global PERFORMANCE_GUARDRAILS.

        Args:
            dataset_name: Name of the dataset being queried
            query_params: Dictionary containing:
                - dimensions: List of dimension columns
                - metrics: List of metric expressions
                - group_by: List of group-by dimensions
                - start_date: Query start date (datetime)
                - end_date: Query end date (datetime)
                - viz_type: Visualization type (string)
                - filters: List of filter dictionaries

        Returns:
            ValidationResult with is_valid=True if query passes all checks
        """
        # Resolve per-dataset guardrails (may differ from global defaults)
        effective = self._get_effective_guardrails(dataset_name)
        bypass_exception: Optional[GuardrailBypassException] = None
        if user_id:
            bypass_exception = self.bypass_store.get_active_exception(
                user_id=user_id,
                dataset_name=dataset_name,
            )
            if bypass_exception:
                self.bypass_store.log_usage(
                    bypass_exception,
                    dataset_name,
                    query_params,
                )
                self.logger.info(
                    "Bypass exception applied for user %s on dataset %s",
                    user_id,
                    dataset_name,
                )

        # 1. Validate dataset access
        result = self.validate_dataset(dataset_name)
        if not result.is_valid:
            return result

        # 2. Validate dimensions
        dimensions = query_params.get('dimensions', [])
        result = self.validate_dimensions(dataset_name, dimensions)
        if not result.is_valid:
            return result

        # 3. Validate metrics (uses effective guardrails for max count)
        metrics = query_params.get('metrics', [])
        max_metrics = None if bypass_exception else effective.max_metrics_per_query
        result = self.validate_metrics(
            dataset_name,
            metrics,
            max_metrics_per_query=max_metrics,
        )
        if not result.is_valid:
            return result

        # 4. Validate date range (uses effective guardrails for max days)
        start_date = query_params.get('start_date')
        end_date = query_params.get('end_date')
        if start_date and end_date and not bypass_exception:
            if end_date < start_date:
                return ValidationResult(
                    is_valid=False,
                    error_message="End date must be after start date",
                    error_code="INVALID_DATE_RANGE",
                )
            date_range_days = (end_date - start_date).days
            if date_range_days > effective.max_date_range_days:
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Date range of {date_range_days} days exceeds maximum "
                        f"of {effective.max_date_range_days} days"
                    ),
                    error_code="DATE_RANGE_EXCEEDED",
                )

        # 5. Validate group-by count (uses effective guardrails)
        group_by = query_params.get('group_by', [])
        if not bypass_exception and len(group_by) > effective.max_group_by_dimensions:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Maximum {effective.max_group_by_dimensions} group-by "
                    f"dimensions allowed, got {len(group_by)}"
                ),
                error_code="TOO_MANY_GROUP_BY",
            )

        # 6. Validate visualization type
        viz_type = query_params.get('viz_type')
        if viz_type:
            result = self.validate_visualization(dataset_name, viz_type)
            if not result.is_valid:
                return result

        # 7. Validate filters count (uses effective guardrails)
        filters = query_params.get('filters', [])
        if not bypass_exception:
            result = self.validate_filters_count(filters, max_filters=effective.max_filters)
            if not result.is_valid:
                return result

        # 8. Validate row limit if explicitly requested
        row_limit = query_params.get('row_limit')
        if row_limit is not None and not bypass_exception:
            if row_limit > effective.row_limit:
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Row limit of {row_limit} exceeds maximum of {effective.row_limit}"
                    ),
                    error_code="ROW_LIMIT_EXCEEDED",
                )

        return ValidationResult(is_valid=True)


# =============================================================================
# QUERY ENFORCEMENT
# =============================================================================

class ExploreGuardrailEnforcer:
    """
    Enforces guardrails at query execution time.

    This class modifies queries and Superset settings to ensure
    guardrails are applied regardless of user input.
    """

    def __init__(self, guardrails: PerformanceGuardrails = PERFORMANCE_GUARDRAILS):
        self.guardrails = guardrails

    def add_row_limit(self, query: str) -> str:
        """
        Add or enforce LIMIT clause to prevent large data exports.

        If query already has LIMIT, ensures it doesn't exceed max.
        """
        limit = self.guardrails.row_limit

        # Check for existing LIMIT clause
        limit_pattern = re.compile(r'\bLIMIT\s+(\d+)', re.IGNORECASE)
        match = limit_pattern.search(query)

        if match:
            existing_limit = int(match.group(1))
            if existing_limit > limit:
                raise ValueError(
                    f"Row limit {existing_limit} exceeds maximum of {limit}"
                )
        else:
            # Add LIMIT clause
            query = f"{query.rstrip().rstrip(';')} LIMIT {limit}"

        return query

    def add_date_filter(
        self,
        query: str,
        date_column: str,
        max_days: Optional[int] = None
    ) -> str:
        """
        Ensure date filter restricts to max allowed range.

        Note: This is a safety net; primary validation should happen
        in ExplorePermissionValidator.
        """
        if max_days is None:
            max_days = self.guardrails.max_date_range_days

        # This is a simplified example; actual implementation would
        # parse and modify the WHERE clause appropriately
        return query

    def get_timeout_config(self) -> Dict[str, int]:
        """Return Superset config for query timeout."""
        timeout = self.guardrails.query_timeout_seconds
        return {
            'SQLLAB_ASYNC_TIME_LIMIT_SEC': timeout,
            'SQLLAB_TIMEOUT': timeout,
            'SUPERSET_WEBSERVER_TIMEOUT': timeout + 10,  # Buffer for processing
        }

    def get_cache_config(self) -> Dict:
        """Return cache configuration based on guardrails."""
        ttl_seconds = self.guardrails.cache_ttl_minutes * 60
        return {
            'CACHE_DEFAULT_TIMEOUT': ttl_seconds,
            'DATA_CACHE_CONFIG': {
                'CACHE_TYPE': 'RedisCache',
                'CACHE_DEFAULT_TIMEOUT': ttl_seconds,
                'CACHE_KEY_PREFIX': 'explore_',
            },
        }

    @staticmethod
    def get_superset_feature_flags() -> Dict[str, bool]:
        """Return feature flags to disable dangerous operations."""
        return EXPLORE_FEATURE_FLAGS.copy()


# =============================================================================
# TOOLTIP / USER GUIDANCE
# =============================================================================

EXPLORE_TOOLTIPS: Dict[str, str] = {
    'date_range': f"Select a date range up to {PERFORMANCE_GUARDRAILS.max_date_range_days} days",
    'group_by': f"Group by up to {PERFORMANCE_GUARDRAILS.max_group_by_dimensions} dimensions (e.g., date + channel)",
    'metrics': "Select from predefined metrics - custom metrics are not available",
    'filters': f"Add up to {PERFORMANCE_GUARDRAILS.max_filters} filters to refine your data",
    'visualization': "Choose from available chart types for this dataset",
    'timeout': f"Queries are limited to {PERFORMANCE_GUARDRAILS.query_timeout_seconds} seconds",
    'row_limit': f"Results are capped at {PERFORMANCE_GUARDRAILS.row_limit:,} rows",
    'export': "Raw data export is not available - use aggregated views",
    'custom_sql': "Custom SQL queries are not available in Explore mode",
}


def get_allowed_dimensions_for_dataset(dataset_name: str) -> List[str]:
    """Get list of allowed dimensions for a dataset (for UI dropdowns)."""
    config = DATASET_EXPLORE_CONFIGS.get(dataset_name)
    if not config or not config.enabled:
        return []
    return sorted(config.allowed_dimensions)


def get_allowed_metrics_for_dataset(
    dataset_name: str,
    persona: ExplorePersona = ExplorePersona.MERCHANT
) -> List[str]:
    """Get list of allowed metrics for a dataset and persona."""
    config = DATASET_EXPLORE_CONFIGS.get(dataset_name)
    if not config or not config.enabled:
        return []

    metrics = set(config.allowed_metrics)

    # Add persona-specific metrics
    persona_config = PERSONA_CONFIGS.get(persona)
    if persona_config:
        extra = persona_config.additional_metrics.get(dataset_name, frozenset())
        metrics.update(extra)

    return sorted(metrics)


def get_allowed_visualizations_for_dataset(dataset_name: str) -> List[str]:
    """Get list of allowed visualization types for a dataset."""
    config = DATASET_EXPLORE_CONFIGS.get(dataset_name)
    if not config or not config.enabled:
        return []
    return sorted([v.value for v in config.allowed_visualizations])


def get_explorable_datasets(
    persona: ExplorePersona = ExplorePersona.MERCHANT
) -> List[str]:
    """Get list of datasets available for exploration by persona."""
    persona_config = PERSONA_CONFIGS.get(persona)
    if not persona_config:
        return []

    explorable = []
    for dataset_name in persona_config.allowed_datasets:
        config = DATASET_EXPLORE_CONFIGS.get(dataset_name)
        if config and config.enabled:
            explorable.append(dataset_name)

    return sorted(explorable)


# =============================================================================
# SUPERSET INTEGRATION HELPERS
# =============================================================================

def get_superset_explore_config() -> Dict:
    """
    Get complete Superset configuration for Explore mode with guardrails.

    Merge this with superset_config.py settings.
    """
    enforcer = ExploreGuardrailEnforcer()

    config = {
        # Feature flags
        'FEATURE_FLAGS': enforcer.get_superset_feature_flags(),

        # Timeout settings
        **enforcer.get_timeout_config(),

        # Cache settings
        **enforcer.get_cache_config(),

        # Row limits
        'SQL_MAX_ROW': PERFORMANCE_GUARDRAILS.row_limit,
        'ROW_LIMIT': PERFORMANCE_GUARDRAILS.row_limit,

        # Disable exports
        'ALLOW_FILE_EXPORT': False,
        'ENABLE_PIVOT_TABLE_DATA_EXPORT': False,
    }

    return config


def validate_explore_request(
    persona: str,
    dataset_name: str,
    query_params: Dict,
    user_id: Optional[str] = None,
    bypass_store: Optional[GuardrailBypassStore] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate an explore request.

    Args:
        persona: Persona name ('merchant' or 'agency')
        dataset_name: Name of the dataset
        query_params: Query parameters dict

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        persona_enum = ExplorePersona(persona.lower())
    except ValueError:
        return False, f"Invalid persona: {persona}"

    validator = ExplorePermissionValidator(
        persona_enum,
        bypass_store=bypass_store,
    )
    result = validator.validate_query(
        dataset_name,
        query_params,
        user_id=user_id,
    )

    return result.is_valid, result.error_message
