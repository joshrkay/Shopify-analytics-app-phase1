"""
Unit tests for quality thresholds config loader (Story 4.1).

Tests cover:
- Config loading from YAML
- Volume anomaly threshold lookup by tier
- Metric constraint retrieval
- Fallback behavior on missing config/tier
"""

import pytest
import os
import tempfile
from unittest.mock import patch

import yaml

from src.config.quality_thresholds import (
    QualityThresholdsLoader,
    get_quality_thresholds_loader,
    reset_quality_thresholds_loader,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    reset_quality_thresholds_loader()
    yield
    reset_quality_thresholds_loader()


@pytest.fixture
def sample_config():
    """Sample quality thresholds config."""
    return {
        "version": 1,
        "default_tier": "free",
        "volume_anomaly": {
            "free": {"threshold_pct": 50},
            "growth": {"threshold_pct": 30},
            "enterprise": {"threshold_pct": 15},
        },
        "severity_mapping": {
            "low": {"max_score": 0.5},
            "medium": {"max_score": 0.8},
            "high": {"min_score": 0.8},
        },
        "metric_constraints": {
            "roas_check": {
                "type": "ratio",
                "description": "ROAS = revenue / spend",
                "tolerance_pct": 1.0,
            },
            "spend_non_negative": {
                "type": "non_negative",
                "description": "Spend >= 0",
            },
        },
    }


@pytest.fixture
def config_file(sample_config):
    """Write sample config to a temp file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False
    ) as f:
        yaml.dump(sample_config, f)
        path = f.name

    yield path
    os.unlink(path)


class TestQualityThresholdsLoader:
    """Tests for the QualityThresholdsLoader."""

    def test_load_from_file(self, config_file):
        """Loads config from YAML file."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold("free") == 50.0
        assert loader.get_volume_anomaly_threshold("growth") == 30.0
        assert loader.get_volume_anomaly_threshold("enterprise") == 15.0

    def test_free_tier_threshold(self, config_file):
        """Free tier returns 50%."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold("free") == 50.0

    def test_growth_tier_threshold(self, config_file):
        """Growth tier returns 30%."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold("growth") == 30.0

    def test_enterprise_tier_threshold(self, config_file):
        """Enterprise tier returns 15%."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold("enterprise") == 15.0

    def test_unknown_tier_falls_back_to_free(self, config_file):
        """Unknown tier falls back to free tier threshold."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold("premium") == 50.0

    def test_none_tier_uses_default(self, config_file):
        """None tier uses default_tier from config."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.get_volume_anomaly_threshold(None) == 50.0

    def test_get_metric_constraints(self, config_file):
        """Returns all metric constraints."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        constraints = loader.get_metric_constraints()
        assert "roas_check" in constraints
        assert "spend_non_negative" in constraints
        assert constraints["roas_check"]["type"] == "ratio"
        assert constraints["roas_check"]["tolerance_pct"] == 1.0

    def test_get_severity_mapping(self, config_file):
        """Returns severity score mapping."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        mapping = loader.get_severity_mapping()
        assert mapping["low"]["max_score"] == 0.5
        assert mapping["high"]["min_score"] == 0.8

    def test_get_all(self, config_file):
        """Returns full config for API exposure."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        result = loader.get_all()
        assert result["version"] == 1
        assert result["default_tier"] == "free"
        assert "volume_anomaly" in result
        assert "metric_constraints" in result

    def test_missing_file_uses_fallback(self):
        """Missing config file gracefully falls back to defaults."""
        loader = get_quality_thresholds_loader(
            config_path="/nonexistent/path/quality_thresholds.yml"
        )
        # Falls back to hardcoded 50%
        assert loader.get_volume_anomaly_threshold("free") == 50.0
        assert loader.get_metric_constraints() == {}

    def test_singleton_pattern(self, config_file):
        """Loader is a singleton."""
        loader1 = get_quality_thresholds_loader(config_path=config_file)
        loader2 = get_quality_thresholds_loader()
        assert loader1 is loader2

    def test_resolve_severity_label_low(self, config_file):
        """Score < 0.5 resolves to 'low'."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.resolve_severity_label(0.0) == "low"
        assert loader.resolve_severity_label(0.2) == "low"
        assert loader.resolve_severity_label(0.49) == "low"

    def test_resolve_severity_label_medium(self, config_file):
        """Score 0.5-0.8 resolves to 'medium'."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.resolve_severity_label(0.5) == "medium"
        assert loader.resolve_severity_label(0.6) == "medium"
        assert loader.resolve_severity_label(0.79) == "medium"

    def test_resolve_severity_label_high(self, config_file):
        """Score >= 0.8 resolves to 'high'."""
        loader = get_quality_thresholds_loader(config_path=config_file)
        assert loader.resolve_severity_label(0.8) == "high"
        assert loader.resolve_severity_label(0.9) == "high"
        assert loader.resolve_severity_label(1.0) == "high"
