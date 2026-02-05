"""
Data freshness SLA configuration loader.

Loads freshness SLA thresholds from config/data_freshness_sla.yml,
the single source of truth for per-source, per-tier freshness expectations.

Consumers:
  - FreshnessService: tier-aware staleness classification
  - Data health API: expose SLA definitions to frontend/dashboard
  - dbt macros: load the same YAML via get_freshness_threshold()

Usage:
    from src.config.freshness_sla import get_freshness_sla_loader

    loader = get_freshness_sla_loader()
    warn = loader.get_threshold("shopify_orders", "growth", "warn_after_minutes")
    error = loader.get_threshold("shopify_orders", "growth", "error_after_minutes")
    all_slas = loader.get_all()
"""

import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Fallback thresholds when a source/tier is not configured (24h warn, 48h error)
_FALLBACK_WARN_MINUTES = 1440
_FALLBACK_ERROR_MINUTES = 2880


class FreshnessSLALoader:
    """
    Thread-safe singleton loader for config/data_freshness_sla.yml.

    Provides lookup by (source_name, tier, threshold_type) and bulk access
    for the API layer.
    """

    _instance: Optional["FreshnessSLALoader"] = None
    _lock = Lock()

    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return

        self._config_path = config_path
        self._raw: Dict[str, Any] = {}
        self._sources: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._default_tier: str = "free"
        self._tiers: List[str] = []
        self._load_lock = Lock()

        self._load()
        self._initialized = True

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    def _resolve_path(self) -> Path:
        if self._config_path:
            return Path(self._config_path)

        candidates = [
            # From backend/ directory (typical working dir)
            Path(__file__).parent.parent.parent.parent / "config" / "data_freshness_sla.yml",
            Path(os.getcwd()) / "config" / "data_freshness_sla.yml",
            Path(os.getcwd()) / ".." / "config" / "data_freshness_sla.yml",
        ]

        for p in candidates:
            resolved = p.resolve()
            if resolved.exists():
                return resolved

        raise FileNotFoundError(
            f"data_freshness_sla.yml not found in: {[str(p) for p in candidates]}"
        )

    def _load(self) -> None:
        with self._load_lock:
            path = self._resolve_path()
            logger.info("Loading freshness SLA config from %s", path)

            with open(path, "r") as f:
                self._raw = yaml.safe_load(f) or {}

            self._default_tier = self._raw.get("default_tier", "free")
            self._sources = self._raw.get("sources", {})

            # Derive the set of tiers from the config
            tier_set: set = set()
            for source_cfg in self._sources.values():
                tier_set.update(source_cfg.keys())
            self._tiers = sorted(tier_set)

            logger.info(
                "Loaded freshness SLAs for %d sources, tiers=%s",
                len(self._sources),
                self._tiers,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read the YAML from disk (e.g. after a config change)."""
        self._load()

    @property
    def default_tier(self) -> str:
        return self._default_tier

    @property
    def tiers(self) -> List[str]:
        return list(self._tiers)

    @property
    def source_names(self) -> List[str]:
        return list(self._sources.keys())

    def get_threshold(
        self,
        source_name: str,
        tier: Optional[str] = None,
        threshold_type: str = "warn_after_minutes",
    ) -> int:
        """
        Return a single threshold value in minutes.

        Resolution order:
          1. Exact (source_name, tier, threshold_type)
          2. Fall back to free tier for the source
          3. Hard-coded fallback (24h warn / 48h error)

        Args:
            source_name:    e.g. 'shopify_orders', 'email'
            tier:           'free', 'growth', 'enterprise'. Defaults to default_tier.
            threshold_type: 'warn_after_minutes' or 'error_after_minutes'
        """
        effective_tier = tier or self._default_tier
        source_cfg = self._sources.get(source_name, {})

        tier_cfg = source_cfg.get(effective_tier) or source_cfg.get("free", {})

        fallback = (
            _FALLBACK_WARN_MINUTES
            if threshold_type == "warn_after_minutes"
            else _FALLBACK_ERROR_MINUTES
        )
        return tier_cfg.get(threshold_type, fallback)

    def get_source_sla(
        self, source_name: str, tier: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Return both warn and error thresholds for a source/tier combo.

        Returns:
            {"warn_after_minutes": N, "error_after_minutes": M}
        """
        return {
            "warn_after_minutes": self.get_threshold(
                source_name, tier, "warn_after_minutes"
            ),
            "error_after_minutes": self.get_threshold(
                source_name, tier, "error_after_minutes"
            ),
        }

    def get_source_all_tiers(self, source_name: str) -> Dict[str, Dict[str, int]]:
        """
        Return thresholds for every tier of a given source.

        Returns:
            {"free": {"warn_after_minutes": ..., "error_after_minutes": ...}, ...}
        """
        source_cfg = self._sources.get(source_name, {})
        result: Dict[str, Dict[str, int]] = {}
        for t in self._tiers:
            tier_cfg = source_cfg.get(t, {})
            result[t] = {
                "warn_after_minutes": tier_cfg.get(
                    "warn_after_minutes", _FALLBACK_WARN_MINUTES
                ),
                "error_after_minutes": tier_cfg.get(
                    "error_after_minutes", _FALLBACK_ERROR_MINUTES
                ),
            }
        return result

    def get_all(self) -> Dict[str, Any]:
        """
        Return the full SLA config as a serialisable dict.

        Useful for the API endpoint that exposes SLAs to the frontend.
        """
        return {
            "version": self._raw.get("version", 1),
            "default_tier": self._default_tier,
            "tiers": self._tiers,
            "sources": {
                name: self.get_source_all_tiers(name) for name in self._sources
            },
        }


# ------------------------------------------------------------------
# Module-level accessors
# ------------------------------------------------------------------

def get_freshness_sla_loader(
    config_path: Optional[str] = None,
) -> FreshnessSLALoader:
    """Return the singleton FreshnessSLALoader."""
    return FreshnessSLALoader(config_path)


def reset_freshness_sla_loader() -> None:
    """Reset singleton (for tests only)."""
    FreshnessSLALoader._instance = None
