"""
Root cause signal model for data quality anomaly diagnostics.

Provides:
- RootCauseType: Enum of root cause categories
- RootCauseHypothesis: Dataclass for individual hypotheses
- RootCauseSignal: SQLAlchemy model for persisted root cause analysis

Story 4.2 - Data Quality Root Cause Signals

SECURITY: All tables are tenant-scoped via tenant_id from JWT.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime,
    Numeric, Index, JSON,
)

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin, generate_uuid


class RootCauseType(str, Enum):
    """Root cause categories for data quality anomalies."""
    INGESTION_FAILURE = "ingestion_failure"
    SCHEMA_DRIFT = "schema_drift"
    TRANSFORMATION_REGRESSION = "transformation_regression"
    UPSTREAM_DATA_SHIFT = "upstream_data_shift"
    DOWNSTREAM_LOGIC_CHANGE = "downstream_logic_change"


@dataclass
class RootCauseHypothesis:
    """
    A single root cause hypothesis with confidence scoring.

    Attributes:
        cause_type: RootCauseType value identifying the category
        confidence_score: Confidence in this hypothesis (0.0 - 1.0)
        evidence: Free-form evidence supporting this hypothesis
        first_seen_at: ISO timestamp when the signal was first observed
        suggested_next_step: Operator-facing recommended action
    """
    cause_type: str
    confidence_score: float
    evidence: Dict[str, Any]
    first_seen_at: Optional[str]
    suggested_next_step: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize hypothesis to a dictionary for JSON storage."""
        return {
            "cause_type": self.cause_type,
            "confidence_score": self.confidence_score,
            "evidence": self.evidence,
            "first_seen_at": self.first_seen_at,
            "suggested_next_step": self.suggested_next_step,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseHypothesis":
        """Deserialize a hypothesis from a dictionary."""
        return cls(
            cause_type=data.get("cause_type", ""),
            confidence_score=float(data.get("confidence_score", 0.0)),
            evidence=data.get("evidence", {}),
            first_seen_at=data.get("first_seen_at"),
            suggested_next_step=data.get("suggested_next_step", ""),
        )


class RootCauseSignal(Base, TenantScopedMixin, TimestampMixin):
    """
    Persisted root cause analysis for a data quality anomaly.

    Stores ranked hypotheses explaining what caused a detected anomaly.
    Hypotheses are stored as a JSON array of serialized RootCauseHypothesis dicts.

    SECURITY: tenant_id is from JWT only.

    Story 4.2 - Data Quality Root Cause Signals
    """
    __tablename__ = "root_cause_signals"

    id = Column(String(255), primary_key=True, default=generate_uuid)

    # Scoping
    dataset = Column(String(255), nullable=False)
    connector_id = Column(String(255), nullable=True)
    correlation_id = Column(String(255), nullable=True)

    # Anomaly context
    anomaly_type = Column(String(100), nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False)

    # Hypotheses (JSON array of RootCauseHypothesis dicts)
    hypotheses = Column(JSON, nullable=False, default=list)

    # Denormalized summary for efficient queries
    top_cause_type = Column(String(50), nullable=True)
    top_confidence = Column(Numeric(4, 3), nullable=True)
    hypothesis_count = Column(Integer, nullable=False, default=0)

    # Lifecycle
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_root_cause_signals_tenant_dataset", "tenant_id", "dataset"),
        Index("ix_root_cause_signals_detected_at", "detected_at"),
        Index("ix_root_cause_signals_correlation", "correlation_id"),
        Index(
            "ix_root_cause_signals_active",
            "tenant_id", "is_active",
        ),
    )
