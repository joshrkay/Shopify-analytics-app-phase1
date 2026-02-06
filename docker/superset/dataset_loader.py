"""
Dataset Loader for YAML-defined Superset datasets.

Reads dataset YAML configs and registers them in Superset via API.
Canonical dataset sync from dbt manifest is in backend (src.services.superset_dataset_sync).
This loader enforces column allow-lists: only columns defined in YAML are exposed.

Usage:
    loader = DatasetLoader(datasets_dir="/app/datasets")
    configs = loader.load_all()
    is_valid, issues = loader.validate_all()

Story 5.1.4 - Register Canonical Datasets
"""

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# PII columns that must NEVER appear in dataset configs
PII_COLUMNS = frozenset({
    "customer_id",
    "customer_key",
    "customer_email",
    "customer_phone",
    "customer_address",
    "customer_ip",
    "payment_method_details",
    "api_credentials",
    "account_id",
    "access_token",
    "refresh_token",
})

# Internal columns that should not be exposed in Superset
INTERNAL_COLUMNS = frozenset({
    "source_system",
    "source_primary_key",
    "ingested_at",
    "dbt_updated_at",
    "airbyte_record_id",
})


@dataclass(frozen=True)
class DatasetColumnConfig:
    """Configuration for a single dataset column."""

    column_name: str
    type: str = "VARCHAR"
    description: str = ""
    filterable: bool = False
    groupby: bool = False
    is_rls_column: bool = False
    is_dttm: bool = False


@dataclass(frozen=True)
class DatasetMetricConfig:
    """Configuration for a predefined metric."""

    metric_name: str
    expression: str
    description: str = ""


@dataclass(frozen=True)
class DatasetConfig:
    """Complete configuration for a Superset dataset."""

    table_name: str
    schema: str
    description: str
    dbt_model: str
    metric_version: str
    version_status: str
    columns: tuple
    metrics: tuple
    rls_enabled: bool
    rls_clause: str
    guardrails: dict
    visualizations_allowed: tuple
    visualizations_disallowed: tuple

    @property
    def column_names(self) -> frozenset:
        """All column names in this dataset."""
        return frozenset(c.column_name for c in self.columns)

    @property
    def has_rls_column(self) -> bool:
        """Whether the dataset has an RLS column defined."""
        return any(c.is_rls_column for c in self.columns)

    @property
    def date_column(self) -> Optional[str]:
        """Primary date/time column for this dataset."""
        for c in self.columns:
            if c.is_dttm:
                return c.column_name
        return None


class DatasetLoader:
    """Loads dataset YAML configs and validates them."""

    def __init__(self, datasets_dir: str = "/app/datasets"):
        self.datasets_dir = Path(datasets_dir)
        self._configs: dict[str, DatasetConfig] = {}

    def load_yaml(self, yaml_path: Path) -> DatasetConfig:
        """Parse a single YAML file into a DatasetConfig."""
        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f)

        ds = raw["dataset"]

        columns = tuple(
            DatasetColumnConfig(
                column_name=c["column_name"],
                type=c.get("type", "VARCHAR"),
                description=c.get("description", ""),
                filterable=c.get("filterable", False),
                groupby=c.get("groupby", False),
                is_rls_column=c.get("is_rls_column", False),
                is_dttm=c.get("is_dttm", False),
            )
            for c in ds.get("columns", [])
        )

        metrics = tuple(
            DatasetMetricConfig(
                metric_name=m["metric_name"],
                expression=m["expression"],
                description=m.get("description", ""),
            )
            for m in ds.get("metrics", [])
        )

        rls = ds.get("rls", {})

        config = DatasetConfig(
            table_name=ds["table_name"],
            schema=ds.get("schema", "analytics"),
            description=ds.get("description", ""),
            dbt_model=ds.get("dbt_model", ""),
            metric_version=ds.get("metric_version", ""),
            version_status=ds.get("version_status", ""),
            columns=columns,
            metrics=metrics,
            rls_enabled=rls.get("enabled", False),
            rls_clause=rls.get("clause", ""),
            guardrails=ds.get("guardrails", {}),
            visualizations_allowed=tuple(ds.get("visualizations_allowed", [])),
            visualizations_disallowed=tuple(ds.get("visualizations_disallowed", [])),
        )

        self._configs[config.table_name] = config
        return config

    def load_all(self) -> list[DatasetConfig]:
        """Load all YAML files from datasets_dir."""
        configs = []
        if not self.datasets_dir.exists():
            logger.warning("Datasets directory not found: %s", self.datasets_dir)
            return configs

        for yaml_file in sorted(self.datasets_dir.glob("*.yaml")):
            try:
                config = self.load_yaml(yaml_file)
                configs.append(config)
                logger.info("Loaded dataset config: %s from %s", config.table_name, yaml_file.name)
            except Exception as e:
                logger.error("Failed to load dataset config from %s: %s", yaml_file, e)
                raise

        return configs

    def register_dataset(self, config: DatasetConfig, superset_client, database_id: int) -> dict:
        """Register a single dataset in Superset via API.

        Only creates columns listed in the YAML (column allow-list enforcement).
        """
        columns = [
            {
                "column_name": c.column_name,
                "type": c.type,
                "description": c.description,
                "filterable": c.filterable,
                "groupby": c.groupby,
                "is_dttm": c.is_dttm,
            }
            for c in config.columns
        ]

        payload = {
            "table_name": config.table_name,
            "database_id": database_id,
            "schema": config.schema,
            "columns": columns,
            "description": config.description,
        }

        response = superset_client.post(
            "/api/v1/datasets",
            json=payload,
        )

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to register dataset {config.table_name}: {response.text}"
            )

        result = response.json()
        dataset_id = result.get("id")

        # Register metrics
        if dataset_id and config.metrics:
            self.register_metrics(dataset_id, config, superset_client)

        logger.info("Registered dataset: %s (id=%s)", config.table_name, dataset_id)
        return result

    def register_metrics(self, dataset_id: int, config: DatasetConfig, superset_client) -> None:
        """Register predefined metrics for a dataset."""
        for metric in config.metrics:
            payload = {
                "metric_name": metric.metric_name,
                "expression": metric.expression,
                "description": metric.description,
            }
            superset_client.post(
                f"/api/v1/datasets/{dataset_id}/metrics",
                json=payload,
            )

    def validate_all(self) -> tuple[bool, list[str]]:
        """Validate all loaded configs.

        Checks:
        - Every dataset has RLS enabled
        - No PII columns exposed
        - All column types are valid
        - Version metadata is present
        - Has at least one date column

        Returns:
            (is_valid, list_of_issues)
        """
        issues = []

        if not self._configs:
            issues.append("No dataset configs loaded")
            return False, issues

        valid_types = {"VARCHAR", "NUMERIC", "INTEGER", "BOOLEAN", "TIMESTAMP", "DATE", "TEXT"}

        for name, config in self._configs.items():
            # RLS must be enabled
            if not config.rls_enabled:
                issues.append(f"{name}: RLS not enabled")

            if not config.rls_clause:
                issues.append(f"{name}: RLS clause is empty")

            # No PII columns
            for col in config.columns:
                if col.column_name in PII_COLUMNS:
                    issues.append(f"{name}: PII column exposed: {col.column_name}")

            # No internal columns
            for col in config.columns:
                if col.column_name in INTERNAL_COLUMNS:
                    issues.append(f"{name}: internal column exposed: {col.column_name}")

            # Valid column types
            for col in config.columns:
                if col.type not in valid_types:
                    issues.append(f"{name}: invalid column type '{col.type}' for {col.column_name}")

            # Version metadata
            if not config.metric_version:
                issues.append(f"{name}: missing metric_version")

            if not config.version_status:
                issues.append(f"{name}: missing version_status")

            # Must have a date column
            if not config.date_column:
                issues.append(f"{name}: no date column (is_dttm) defined")

            # Must have an RLS column
            if not config.has_rls_column:
                issues.append(f"{name}: no RLS column (is_rls_column) defined")

            # Metrics must have expressions
            for metric in config.metrics:
                if not metric.expression:
                    issues.append(f"{name}: metric '{metric.metric_name}' has no expression")

        return len(issues) == 0, issues

    def get_config(self, table_name: str) -> Optional[DatasetConfig]:
        """Get config for a specific dataset."""
        return self._configs.get(table_name)
