"""
Quality threshold configuration loader.

Loads plan-tier-aware thresholds for volume anomaly detection and
metric consistency checks from config/quality_thresholds.yml.

Consumers:
  - DQService: volume anomaly detection and metric consistency checks

Usage:
    from src.config.quality_thresholds import get_quality_thresholds_loader

    loader = get_quality_thresholds_loader()
    threshold = loader.get_volume_anomaly_threshold("growth")  # 30
    constraints = loader.get_metric_constraints()
"""

import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Fallback: free tier threshold (most permissive)
_FALLBACK_VOLUME_THRESHOLD_PCT = 50


class QualityThresholdsLoader:
    """
    Thread-safe singleton loader for config/quality_thresholds.yml.

    Provides lookup for volume anomaly thresholds by billing tier
    and metric consistency constraint definitions.
    """

    _instance: Optional["QualityThresholdsLoader"] = None
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
        self._default_tier: str = "free"
        self._load_lock = Lock()

        self._load()
        self._initialized = True

    def _resolve_path(self) -> Path:
        if self._config_path:
            return Path(self._config_path)

        candidates = [
            Path(__file__).parent.parent.parent.parent / "config" / "quality_thresholds.yml",
            Path(os.getcwd()) / "config" / "quality_thresholds.yml",
            Path(os.getcwd()) / ".." / "config" / "quality_thresholds.yml",
        ]

        for p in candidates:
            resolved = p.resolve()
            if resolved.exists():
                return resolved

        raise FileNotFoundError(
            f"quality_thresholds.yml not found in: {[str(p) for p in candidates]}"
        )

    def _load(self) -> None:
        with self._load_lock:
            try:
                path = self._resolve_path()
                logger.info("Loading quality thresholds from %s", path)

                with open(path, "r") as f:
                    self._raw = yaml.safe_load(f) or {}

                self._default_tier = self._raw.get("default_tier", "free")

                logger.info(
                    "Loaded quality thresholds: volume_anomaly tiers=%s, metric_constraints=%d",
                    list(self._raw.get("volume_anomaly", {}).keys()),
                    len(self._raw.get("metric_constraints", {})),
                )
            except FileNotFoundError:
                logger.warning(
                    "quality_thresholds.yml not found, using fallback defaults"
                )
                self._raw = {}
                self._default_tier = "free"

    def reload(self) -> None:
        """Re-read the YAML from disk."""
        self._load()

    def get_volume_anomaly_threshold(self, billing_tier: Optional[str] = None) -> float:
        """
        Return volume anomaly threshold_pct for a billing tier.

        Args:
            billing_tier: 'free', 'growth', or 'enterprise'. Falls back to default.

        Returns:
            Threshold percentage (e.g. 50.0, 30.0, 15.0)
        """
        effective_tier = billing_tier or self._default_tier
        vol_config = self._raw.get("volume_anomaly", {})
        tier_config = vol_config.get(effective_tier) or vol_config.get("free", {})
        return float(tier_config.get("threshold_pct", _FALLBACK_VOLUME_THRESHOLD_PCT))

    def get_severity_mapping(self) -> Dict[str, Dict[str, float]]:
        """
        Return severity score thresholds.

        Returns:
            {"low": {"max_score": 0.5}, "medium": {"max_score": 0.8}, "high": {"min_score": 0.8}}
        """
        return self._raw.get("severity_mapping", {
            "low": {"max_score": 0.5},
            "medium": {"max_score": 0.8},
            "high": {"min_score": 0.8},
        })

    def get_metric_constraints(self) -> Dict[str, Dict[str, Any]]:
        """
        Return all metric consistency constraint definitions.

        Returns:
            Dict of constraint_name -> constraint config
        """
        return self._raw.get("metric_constraints", {})

    def get_all(self) -> Dict[str, Any]:
        """Return the full config for API exposure."""
        return {
            "version": self._raw.get("version", 1),
            "default_tier": self._default_tier,
            "volume_anomaly": self._raw.get("volume_anomaly", {}),
            "severity_mapping": self.get_severity_mapping(),
            "metric_constraints": self.get_metric_constraints(),
        }


def get_quality_thresholds_loader(
    config_path: Optional[str] = None,
) -> QualityThresholdsLoader:
    """Return the singleton QualityThresholdsLoader."""
    return QualityThresholdsLoader(config_path)


def reset_quality_thresholds_loader() -> None:
    """Reset singleton (for tests only)."""
    QualityThresholdsLoader._instance = None
