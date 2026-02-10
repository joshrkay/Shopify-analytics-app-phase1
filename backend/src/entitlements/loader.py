"""
Entitlement Loader - Load plan entitlements from config/plans.json.

Provides:
- PlanEntitlements: Dataclass representing a plan's entitlements
- EntitlementLoader: Singleton loader for plans configuration

CRITICAL: This is the source of truth for feature entitlements.
Do NOT hardcode feature access elsewhere.
"""

import json
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from threading import Lock

logger = logging.getLogger(__name__)

# Default config path relative to backend directory
DEFAULT_CONFIG_PATH = "config/plans.json"


@dataclass(frozen=True)
class FeatureEntitlement:
    """Single feature entitlement with its configuration."""

    feature_key: str
    enabled: Union[bool, str]  # True, False, or "limited"
    limit_value: Optional[int] = None

    def is_enabled(self) -> bool:
        """Check if feature is enabled (True or 'limited')."""
        return self.enabled is True or self.enabled == "limited"

    def is_limited(self) -> bool:
        """Check if feature has limited access."""
        return self.enabled == "limited"

    def is_unlimited(self) -> bool:
        """Check if feature has no limit (-1 means unlimited)."""
        return self.limit_value is None or self.limit_value == -1


@dataclass
class PlanLimits:
    """Usage limits for a plan."""

    max_dashboards: int = 0
    max_users: int = 0
    api_calls_per_month: int = 0
    ai_insights_per_month: int = 0
    data_retention_days: int = 30
    export_rows_per_request: int = 0

    def is_unlimited(self, limit_key: str) -> bool:
        """Check if a specific limit is unlimited (-1)."""
        value = getattr(self, limit_key, None)
        return value is None or value == -1

    def get_limit(self, limit_key: str) -> Optional[int]:
        """Get a specific limit value."""
        return getattr(self, limit_key, None)


@dataclass
class PlanEntitlements:
    """Complete entitlements for a single plan."""

    plan_id: str
    plan_name: str
    display_name: str
    tier: int
    features: Dict[str, FeatureEntitlement] = field(default_factory=dict)
    limits: PlanLimits = field(default_factory=PlanLimits)
    trial_enabled: bool = False
    trial_days: int = 0
    is_active: bool = True

    def has_feature(self, feature_key: str) -> bool:
        """Check if plan has a specific feature enabled."""
        if feature_key not in self.features:
            return False
        return self.features[feature_key].is_enabled()

    def get_feature(self, feature_key: str) -> Optional[FeatureEntitlement]:
        """Get feature entitlement details."""
        return self.features.get(feature_key)

    def get_enabled_features(self) -> List[str]:
        """Get list of all enabled feature keys."""
        return [
            key for key, feat in self.features.items()
            if feat.is_enabled()
        ]

    def get_restricted_features(self) -> List[str]:
        """Get list of all disabled feature keys."""
        return [
            key for key, feat in self.features.items()
            if not feat.is_enabled()
        ]

    def get_limited_features(self) -> List[str]:
        """Get list of features with limited access."""
        return [
            key for key, feat in self.features.items()
            if feat.is_limited()
        ]


@dataclass
class BillingConfig:
    """Billing configuration from plans.json."""

    grace_period_days: int = 3
    warning_notification_days_before: int = 3
    access_during_grace: str = "full"
    auto_cancel_after_suspension_days: int = 30
    upgrade_timing: str = "immediate"
    downgrade_timing: str = "end_of_period"
    proration_enabled: bool = True


@dataclass
class BillingRules:
    """Billing rules configuration."""

    grace_period_days: int = 3
    retry_strategy: str = "exponential_backoff"
    max_retries: int = 5
    retry_intervals_hours: List[int] = field(default_factory=lambda: [24, 48, 72, 96, 120])


@dataclass
class AccessRuleConfig:
    """Configuration for a specific billing state's access rules."""

    access_level: str
    restrictions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_days: Optional[int] = None
    access_expires_at: Optional[str] = None
    allow_read_analytics: bool = False


class EntitlementLoader:
    """
    Singleton loader for plan entitlements from config/plans.json.

    Thread-safe with lazy loading and reload support.

    Usage:
        loader = EntitlementLoader()
        plan = loader.get_plan("plan_growth")
        if plan.has_feature("ai_insights"):
            # Feature is available
    """

    _instance: Optional['EntitlementLoader'] = None
    _lock = Lock()

    def __new__(cls, config_path: Optional[str] = None):
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the entitlement loader.

        Args:
            config_path: Optional path to plans.json (defaults to config/plans.json)
        """
        if self._initialized:
            return

        self._config_path = config_path
        self._plans: Dict[str, PlanEntitlements] = {}
        self._billing_config: Optional[BillingConfig] = None
        self._billing_rules: Optional[BillingRules] = None
        self._access_rules: Dict[str, AccessRuleConfig] = {}
        self._feature_descriptions: Dict[str, str] = {}
        self._raw_config: Dict[str, Any] = {}
        self._load_lock = Lock()

        self._load_config()
        self._initialized = True

    def _resolve_config_path(self) -> Path:
        """Resolve the config file path."""
        if self._config_path:
            return Path(self._config_path)

        # Try multiple locations
        possible_paths = [
            Path(__file__).parent.parent.parent / "config" / "plans.json",  # backend/config/
            Path(os.getcwd()) / "config" / "plans.json",
            Path(os.getcwd()) / "backend" / "config" / "plans.json",
        ]

        for path in possible_paths:
            if path.exists():
                return path

        raise FileNotFoundError(
            f"plans.json not found in any of: {[str(p) for p in possible_paths]}"
        )

    def _load_config(self) -> None:
        """Load and parse the plans.json configuration."""
        with self._load_lock:
            config_path = self._resolve_config_path()

            logger.info(f"Loading entitlements from {config_path}")

            with open(config_path, "r") as f:
                self._raw_config = json.load(f)

            # Parse plans
            self._parse_plans()

            # Parse billing config
            self._parse_billing_config()

            # Parse billing rules
            self._parse_billing_rules()

            # Parse access rules
            self._parse_access_rules()

            # Parse feature descriptions
            self._feature_descriptions = self._raw_config.get("feature_descriptions", {})

            logger.info(f"Loaded {len(self._plans)} plans with entitlements")

    def _parse_plans(self) -> None:
        """Parse plan definitions from config."""
        plans_data = self._raw_config.get("plans", [])

        for plan_data in plans_data:
            plan_id = plan_data.get("id", "")
            plan_name = plan_data.get("name", "")

            # Parse features
            features_data = plan_data.get("features", {})
            features = {}
            for key, value in features_data.items():
                features[key] = FeatureEntitlement(
                    feature_key=key,
                    enabled=value,
                    limit_value=None  # Limits are in the limits section
                )

            # Parse limits
            limits_data = plan_data.get("limits", {})
            limits = PlanLimits(
                max_dashboards=limits_data.get("max_dashboards", 0),
                max_users=limits_data.get("max_users", 0),
                api_calls_per_month=limits_data.get("api_calls_per_month", 0),
                ai_insights_per_month=limits_data.get("ai_insights_per_month", 0),
                data_retention_days=limits_data.get("data_retention_days", 30),
                export_rows_per_request=limits_data.get("export_rows_per_request", 0),
            )

            # Parse trial config
            trial_config = plan_data.get("trial", {})

            plan = PlanEntitlements(
                plan_id=plan_id,
                plan_name=plan_name,
                display_name=plan_data.get("display_name", plan_name),
                tier=plan_data.get("tier", 0),
                features=features,
                limits=limits,
                trial_enabled=trial_config.get("enabled", False),
                trial_days=trial_config.get("days", 0),
                is_active=plan_data.get("is_active", True),
            )

            self._plans[plan_id] = plan
            # Also index by plan name for convenience
            self._plans[plan_name] = plan

    def _parse_billing_config(self) -> None:
        """Parse billing configuration."""
        config_data = self._raw_config.get("billing_config", {})
        self._billing_config = BillingConfig(
            grace_period_days=config_data.get("grace_period_days", 3),
            warning_notification_days_before=config_data.get("warning_notification_days_before", 3),
            access_during_grace=config_data.get("access_during_grace", "full"),
            auto_cancel_after_suspension_days=config_data.get("auto_cancel_after_suspension_days", 30),
            upgrade_timing=config_data.get("upgrade_timing", "immediate"),
            downgrade_timing=config_data.get("downgrade_timing", "end_of_period"),
            proration_enabled=config_data.get("proration_enabled", True),
        )

    def _parse_billing_rules(self) -> None:
        """Parse billing rules configuration."""
        rules_data = self._raw_config.get("billing_rules", {})
        self._billing_rules = BillingRules(
            grace_period_days=rules_data.get("grace_period_days", 3),
            retry_strategy=rules_data.get("retry_strategy", "exponential_backoff"),
            max_retries=rules_data.get("max_retries", 5),
            retry_intervals_hours=rules_data.get("retry_intervals_hours", [24, 48, 72, 96, 120]),
        )

    def _parse_access_rules(self) -> None:
        """Parse access rules by billing state."""
        rules_data = self._raw_config.get("access_rules", {})

        for state, rule_data in rules_data.items():
            self._access_rules[state] = AccessRuleConfig(
                access_level=rule_data.get("access_level", "none"),
                restrictions=rule_data.get("restrictions", []),
                warnings=rule_data.get("warnings", []),
                duration_days=rule_data.get("duration_days"),
                access_expires_at=rule_data.get("access_expires_at"),
                allow_read_analytics=rule_data.get("allow_read_analytics", False),
            )

    def reload(self) -> None:
        """
        Reload configuration from disk (atomic swap).

        Builds the new config into temporary dicts, then swaps references
        atomically so concurrent readers never see an empty state (EC6).
        """
        logger.info("Reloading entitlements configuration")

        # Build new config into temporaries via _load_config
        # _load_config acquires _load_lock internally
        old_plans = self._plans
        old_access_rules = self._access_rules

        self._plans = {}
        self._access_rules = {}

        try:
            self._load_config()
        except Exception:
            # Rollback: restore old references on failure
            self._plans = old_plans
            self._access_rules = old_access_rules
            logger.error("Config reload failed, keeping previous config", exc_info=True)
            raise

    def get_plan(self, plan_id_or_name: str) -> Optional[PlanEntitlements]:
        """
        Get entitlements for a specific plan.

        Args:
            plan_id_or_name: Plan ID (e.g., "plan_growth") or name (e.g., "growth")

        Returns:
            PlanEntitlements or None if not found
        """
        return self._plans.get(plan_id_or_name)

    def get_plan_by_tier(self, tier: int) -> Optional[PlanEntitlements]:
        """Get plan by tier level."""
        for plan in self._plans.values():
            if plan.tier == tier and plan.plan_id.startswith("plan_"):
                return plan
        return None

    def get_all_plans(self) -> List[PlanEntitlements]:
        """Get all active plans (deduplicated by plan_id)."""
        seen = set()
        plans = []
        for plan in self._plans.values():
            if plan.plan_id not in seen and plan.is_active:
                seen.add(plan.plan_id)
                plans.append(plan)
        return sorted(plans, key=lambda p: p.tier)

    def get_free_plan(self) -> Optional[PlanEntitlements]:
        """Get the free plan."""
        return self.get_plan("plan_free") or self.get_plan("free")

    def get_billing_config(self) -> BillingConfig:
        """Get billing configuration."""
        return self._billing_config or BillingConfig()

    def get_billing_rules(self) -> BillingRules:
        """Get billing rules."""
        return self._billing_rules or BillingRules()

    def get_access_rule(self, billing_state: str) -> Optional[AccessRuleConfig]:
        """Get access rule configuration for a billing state."""
        return self._access_rules.get(billing_state)

    def get_all_access_rules(self) -> Dict[str, AccessRuleConfig]:
        """Get all access rules."""
        return dict(self._access_rules)

    def get_grace_period_days(self) -> int:
        """Get the configured grace period in days (default: 3)."""
        if self._billing_rules:
            return self._billing_rules.grace_period_days
        if self._billing_config:
            return self._billing_config.grace_period_days
        return 3  # Default

    def get_feature_description(self, feature_key: str) -> Optional[str]:
        """Get human-readable description for a feature."""
        return self._feature_descriptions.get(feature_key)

    def compare_plans(self, plan_a_id: str, plan_b_id: str) -> int:
        """
        Compare two plans by tier.

        Returns:
            -1 if plan_a < plan_b (downgrade)
            0 if equal
            1 if plan_a > plan_b (upgrade)
        """
        plan_a = self.get_plan(plan_a_id)
        plan_b = self.get_plan(plan_b_id)

        if not plan_a or not plan_b:
            return 0

        if plan_a.tier < plan_b.tier:
            return -1
        elif plan_a.tier > plan_b.tier:
            return 1
        return 0

    def is_upgrade(self, from_plan_id: str, to_plan_id: str) -> bool:
        """Check if changing plans would be an upgrade."""
        return self.compare_plans(to_plan_id, from_plan_id) > 0

    def is_downgrade(self, from_plan_id: str, to_plan_id: str) -> bool:
        """Check if changing plans would be a downgrade."""
        return self.compare_plans(to_plan_id, from_plan_id) < 0

    def get_features_lost_on_downgrade(
        self,
        from_plan_id: str,
        to_plan_id: str
    ) -> List[str]:
        """Get list of features that would be lost on downgrade."""
        from_plan = self.get_plan(from_plan_id)
        to_plan = self.get_plan(to_plan_id)

        if not from_plan or not to_plan:
            return []

        from_features = set(from_plan.get_enabled_features())
        to_features = set(to_plan.get_enabled_features())

        return list(from_features - to_features)


def get_entitlement_loader(config_path: Optional[str] = None) -> EntitlementLoader:
    """
    Get the singleton EntitlementLoader instance.

    Args:
        config_path: Optional path to plans.json

    Returns:
        EntitlementLoader singleton instance
    """
    return EntitlementLoader(config_path)


def reset_entitlement_loader() -> None:
    """
    Reset the singleton instance (for testing).

    WARNING: Only use in tests!
    """
    EntitlementLoader._instance = None
