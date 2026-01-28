"""
AI Insight Generation Service.

Generates insights from aggregated dbt mart data using configurable
threshold-based detection. All outputs are deterministic.

SECURITY:
- Tenant isolation via tenant_id in all queries
- No raw data access - only aggregated marts
- No PII access
- No external API calls

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.ai_insight import AIInsight, InsightType, InsightSeverity
from src.services.insight_thresholds import InsightThresholds, DEFAULT_THRESHOLDS


logger = logging.getLogger(__name__)


@dataclass
class MetricChange:
    """Represents a metric change for analysis."""

    metric_name: str
    current_value: Decimal
    prior_value: Decimal
    delta: Decimal
    delta_pct: float
    timeframe: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "metric": self.metric_name,
            "current_value": float(self.current_value),
            "prior_value": float(self.prior_value),
            "delta": float(self.delta),
            "delta_pct": self.delta_pct,
            "timeframe": self.timeframe,
        }


@dataclass
class DetectedInsight:
    """Intermediate representation of a detected insight."""

    insight_type: InsightType
    severity: InsightSeverity
    metrics: list[MetricChange]
    period_type: str
    period_start: datetime
    period_end: datetime
    comparison_type: str
    platform: str | None = None
    campaign_id: str | None = None
    currency: str | None = None
    confidence_score: float = 0.0


class InsightGenerationService:
    """
    Service for generating AI insights from dbt mart data.

    SECURITY: All operations are tenant-scoped. tenant_id from JWT only.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        thresholds: InsightThresholds | None = None,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.thresholds = thresholds or DEFAULT_THRESHOLDS

    def generate_insights(
        self,
        job_id: str,
        period_types: list[str] | None = None,
    ) -> list[AIInsight]:
        """
        Generate all insights for the tenant.

        Args:
            job_id: ID of the InsightJob triggering generation
            period_types: Period types to analyze (default: weekly, last_30_days)

        Returns:
            List of generated AIInsight objects
        """
        if period_types is None:
            period_types = ["weekly", "last_30_days"]

        all_detected: list[DetectedInsight] = []

        for period_type in period_types:
            # Fetch data from marts
            marketing_data = self._fetch_marketing_metrics(period_type)
            revenue_data = self._fetch_revenue_metrics(period_type)

            # Detect insights
            all_detected.extend(
                self._detect_spend_anomalies(marketing_data, period_type)
            )
            all_detected.extend(
                self._detect_roas_changes(marketing_data, period_type)
            )
            all_detected.extend(
                self._detect_revenue_spend_divergence(
                    marketing_data, revenue_data, period_type
                )
            )
            all_detected.extend(
                self._detect_cac_anomalies(marketing_data, period_type)
            )
            all_detected.extend(
                self._detect_aov_changes(revenue_data, period_type)
            )

        # Persist insights
        persisted = []
        for detected in all_detected:
            insight = self._persist_insight(detected, job_id)
            if insight:
                persisted.append(insight)

        logger.info(
            "Insights generated",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job_id,
                "detected": len(all_detected),
                "persisted": len(persisted),
            },
        )

        return persisted

    def _fetch_marketing_metrics(self, period_type: str) -> list[dict[str, Any]]:
        """Fetch marketing metrics from mart_marketing_metrics."""
        query = text("""
            SELECT
                platform,
                currency,
                campaign_id,
                period_type,
                period_start,
                period_end,
                comparison_type,
                spend,
                prior_spend,
                spend_change,
                spend_change_pct,
                gross_roas,
                prior_gross_roas,
                gross_roas_change,
                gross_roas_change_pct,
                net_roas,
                prior_net_roas,
                net_roas_change_pct,
                cac,
                prior_cac,
                cac_change,
                cac_change_pct,
                new_customers,
                prior_new_customers,
                orders,
                prior_orders
            FROM marts.mart_marketing_metrics
            WHERE tenant_id = :tenant_id
              AND period_type = :period_type
              AND period_end = (
                  SELECT MAX(period_end)
                  FROM marts.mart_marketing_metrics
                  WHERE tenant_id = :tenant_id
                    AND period_type = :period_type
              )
        """)

        result = self.db.execute(
            query, {"tenant_id": self.tenant_id, "period_type": period_type}
        )

        return [dict(row._mapping) for row in result.fetchall()]

    def _fetch_revenue_metrics(self, period_type: str) -> list[dict[str, Any]]:
        """Fetch revenue metrics from mart_revenue_metrics."""
        query = text("""
            SELECT
                currency,
                period_type,
                period_start,
                period_end,
                comparison_type,
                gross_revenue,
                prior_gross_revenue,
                gross_revenue_change,
                gross_revenue_change_pct,
                net_revenue,
                prior_net_revenue,
                net_revenue_change,
                net_revenue_change_pct,
                order_count,
                prior_order_count,
                order_count_change_pct,
                aov,
                prior_aov,
                aov_change,
                aov_change_pct
            FROM marts.mart_revenue_metrics
            WHERE tenant_id = :tenant_id
              AND period_type = :period_type
              AND period_end = (
                  SELECT MAX(period_end)
                  FROM marts.mart_revenue_metrics
                  WHERE tenant_id = :tenant_id
                    AND period_type = :period_type
              )
        """)

        result = self.db.execute(
            query, {"tenant_id": self.tenant_id, "period_type": period_type}
        )

        return [dict(row._mapping) for row in result.fetchall()]

    def _detect_spend_anomalies(
        self,
        marketing_data: list[dict],
        period_type: str,
    ) -> list[DetectedInsight]:
        """Detect significant spend changes."""
        insights = []

        for row in marketing_data:
            spend = float(row.get("spend") or 0)
            prior_spend = float(row.get("prior_spend") or 0)
            change_pct = float(row.get("spend_change_pct") or 0)

            # Skip if below minimum threshold
            if spend < self.thresholds.min_spend_for_analysis and \
               prior_spend < self.thresholds.min_spend_for_analysis:
                continue

            if abs(change_pct) >= self.thresholds.spend_anomaly_pct:
                severity = self._calculate_severity(
                    abs(change_pct),
                    self.thresholds.spend_anomaly_pct,
                    self.thresholds.spend_critical_pct,
                )

                metrics = [
                    MetricChange(
                        metric_name="spend",
                        current_value=Decimal(str(spend)),
                        prior_value=Decimal(str(prior_spend)),
                        delta=Decimal(str(row.get("spend_change") or 0)),
                        delta_pct=change_pct,
                        timeframe=row.get("comparison_type") or "period_over_period",
                    )
                ]

                insights.append(
                    DetectedInsight(
                        insight_type=InsightType.SPEND_ANOMALY,
                        severity=severity,
                        metrics=metrics,
                        period_type=period_type,
                        period_start=row["period_start"],
                        period_end=row["period_end"],
                        comparison_type=row.get("comparison_type") or "",
                        platform=row.get("platform"),
                        campaign_id=row.get("campaign_id"),
                        currency=row.get("currency"),
                        confidence_score=self._calculate_confidence(
                            change_pct, spend, prior_spend
                        ),
                    )
                )

        return insights

    def _detect_roas_changes(
        self,
        marketing_data: list[dict],
        period_type: str,
    ) -> list[DetectedInsight]:
        """Detect significant ROAS changes."""
        insights = []

        for row in marketing_data:
            roas = float(row.get("gross_roas") or 0)
            prior_roas = float(row.get("prior_gross_roas") or 0)
            change_pct = float(row.get("gross_roas_change_pct") or 0)

            # Skip if no meaningful ROAS data
            if roas == 0 and prior_roas == 0:
                continue

            if abs(change_pct) >= self.thresholds.roas_change_pct:
                severity = self._calculate_severity(
                    abs(change_pct),
                    self.thresholds.roas_change_pct,
                    self.thresholds.roas_critical_pct,
                )

                metrics = [
                    MetricChange(
                        metric_name="gross_roas",
                        current_value=Decimal(str(roas)),
                        prior_value=Decimal(str(prior_roas)),
                        delta=Decimal(str(row.get("gross_roas_change") or 0)),
                        delta_pct=change_pct,
                        timeframe=row.get("comparison_type") or "period_over_period",
                    )
                ]

                insights.append(
                    DetectedInsight(
                        insight_type=InsightType.ROAS_CHANGE,
                        severity=severity,
                        metrics=metrics,
                        period_type=period_type,
                        period_start=row["period_start"],
                        period_end=row["period_end"],
                        comparison_type=row.get("comparison_type") or "",
                        platform=row.get("platform"),
                        campaign_id=row.get("campaign_id"),
                        currency=row.get("currency"),
                        confidence_score=self._calculate_confidence(
                            change_pct, roas, prior_roas
                        ),
                    )
                )

        return insights

    def _detect_revenue_spend_divergence(
        self,
        marketing_data: list[dict],
        revenue_data: list[dict],
        period_type: str,
    ) -> list[DetectedInsight]:
        """Detect when revenue and spend move in opposite directions."""
        insights = []

        # Aggregate marketing spend by currency
        spend_by_currency: dict[str, dict] = {}
        for row in marketing_data:
            currency = row.get("currency") or "USD"
            if currency not in spend_by_currency:
                spend_by_currency[currency] = {
                    "spend": 0,
                    "prior_spend": 0,
                    "spend_change_pct": 0,
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "comparison_type": row.get("comparison_type") or "",
                }
            spend_by_currency[currency]["spend"] += float(row.get("spend") or 0)
            spend_by_currency[currency]["prior_spend"] += float(
                row.get("prior_spend") or 0
            )

        # Recalculate percentage after aggregation
        for currency, data in spend_by_currency.items():
            if data["prior_spend"] > 0:
                data["spend_change_pct"] = (
                    (data["spend"] - data["prior_spend"]) / data["prior_spend"] * 100
                )

        for rev_row in revenue_data:
            currency = rev_row.get("currency") or "USD"
            revenue_change_pct = float(rev_row.get("net_revenue_change_pct") or 0)
            net_revenue = float(rev_row.get("net_revenue") or 0)
            prior_net_revenue = float(rev_row.get("prior_net_revenue") or 0)

            if currency not in spend_by_currency:
                continue

            spend_data = spend_by_currency[currency]
            spend_change_pct = spend_data["spend_change_pct"]

            # Check for divergence: opposite directions with significant magnitude
            threshold = self.thresholds.divergence_pct
            is_divergent = (
                (revenue_change_pct < -threshold and spend_change_pct > threshold)
                or (revenue_change_pct > threshold and spend_change_pct < -threshold)
            )

            if not is_divergent:
                continue

            # Skip if values are too small
            if (
                net_revenue < self.thresholds.min_revenue_for_analysis
                and prior_net_revenue < self.thresholds.min_revenue_for_analysis
            ):
                continue

            metrics = [
                MetricChange(
                    metric_name="net_revenue",
                    current_value=Decimal(str(net_revenue)),
                    prior_value=Decimal(str(prior_net_revenue)),
                    delta=Decimal(str(rev_row.get("net_revenue_change") or 0)),
                    delta_pct=revenue_change_pct,
                    timeframe=rev_row.get("comparison_type") or "period_over_period",
                ),
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal(str(spend_data["spend"])),
                    prior_value=Decimal(str(spend_data["prior_spend"])),
                    delta=Decimal(
                        str(spend_data["spend"] - spend_data["prior_spend"])
                    ),
                    delta_pct=spend_change_pct,
                    timeframe=spend_data["comparison_type"],
                ),
            ]

            # Divergence is always at least WARNING severity
            severity = InsightSeverity.WARNING
            if abs(revenue_change_pct) > 25 or abs(spend_change_pct) > 25:
                severity = InsightSeverity.CRITICAL

            insights.append(
                DetectedInsight(
                    insight_type=InsightType.REVENUE_VS_SPEND_DIVERGENCE,
                    severity=severity,
                    metrics=metrics,
                    period_type=period_type,
                    period_start=rev_row["period_start"],
                    period_end=rev_row["period_end"],
                    comparison_type=rev_row.get("comparison_type") or "",
                    currency=currency,
                    confidence_score=0.85,
                )
            )

        return insights

    def _detect_cac_anomalies(
        self,
        marketing_data: list[dict],
        period_type: str,
    ) -> list[DetectedInsight]:
        """Detect significant CAC changes."""
        insights = []

        for row in marketing_data:
            cac = float(row.get("cac") or 0)
            prior_cac = float(row.get("prior_cac") or 0)
            change_pct = float(row.get("cac_change_pct") or 0)

            # Skip if no CAC data
            if cac == 0 and prior_cac == 0:
                continue

            if abs(change_pct) >= self.thresholds.cac_anomaly_pct:
                severity = self._calculate_severity(
                    abs(change_pct),
                    self.thresholds.cac_anomaly_pct,
                    self.thresholds.cac_critical_pct,
                )

                metrics = [
                    MetricChange(
                        metric_name="cac",
                        current_value=Decimal(str(cac)),
                        prior_value=Decimal(str(prior_cac)),
                        delta=Decimal(str(row.get("cac_change") or 0)),
                        delta_pct=change_pct,
                        timeframe=row.get("comparison_type") or "period_over_period",
                    )
                ]

                insights.append(
                    DetectedInsight(
                        insight_type=InsightType.CAC_ANOMALY,
                        severity=severity,
                        metrics=metrics,
                        period_type=period_type,
                        period_start=row["period_start"],
                        period_end=row["period_end"],
                        comparison_type=row.get("comparison_type") or "",
                        platform=row.get("platform"),
                        campaign_id=row.get("campaign_id"),
                        currency=row.get("currency"),
                        confidence_score=self._calculate_confidence(
                            change_pct, cac, prior_cac
                        ),
                    )
                )

        return insights

    def _detect_aov_changes(
        self,
        revenue_data: list[dict],
        period_type: str,
    ) -> list[DetectedInsight]:
        """Detect significant AOV changes."""
        insights = []

        for row in revenue_data:
            aov = float(row.get("aov") or 0)
            prior_aov = float(row.get("prior_aov") or 0)
            change_pct = float(row.get("aov_change_pct") or 0)

            # Skip if no AOV data
            if aov == 0 and prior_aov == 0:
                continue

            if abs(change_pct) >= self.thresholds.aov_change_pct:
                # AOV changes are typically INFO unless very large
                severity = InsightSeverity.INFO
                if abs(change_pct) >= 25:
                    severity = InsightSeverity.WARNING
                if abs(change_pct) >= 40:
                    severity = InsightSeverity.CRITICAL

                metrics = [
                    MetricChange(
                        metric_name="aov",
                        current_value=Decimal(str(aov)),
                        prior_value=Decimal(str(prior_aov)),
                        delta=Decimal(str(row.get("aov_change") or 0)),
                        delta_pct=change_pct,
                        timeframe=row.get("comparison_type") or "period_over_period",
                    )
                ]

                insights.append(
                    DetectedInsight(
                        insight_type=InsightType.AOV_CHANGE,
                        severity=severity,
                        metrics=metrics,
                        period_type=period_type,
                        period_start=row["period_start"],
                        period_end=row["period_end"],
                        comparison_type=row.get("comparison_type") or "",
                        currency=row.get("currency"),
                        confidence_score=self._calculate_confidence(
                            change_pct, aov, prior_aov
                        ),
                    )
                )

        return insights

    def _calculate_severity(
        self,
        change_pct: float,
        warning_threshold: float,
        critical_threshold: float,
    ) -> InsightSeverity:
        """Calculate severity based on change magnitude."""
        if change_pct >= critical_threshold:
            return InsightSeverity.CRITICAL
        if change_pct >= warning_threshold:
            return InsightSeverity.WARNING
        return InsightSeverity.INFO

    def _calculate_confidence(
        self,
        change_pct: float,
        current_value: float,
        prior_value: float,
    ) -> float:
        """
        Calculate confidence score based on statistical significance.

        Higher confidence when:
        - Both values are non-trivial (not near zero)
        - Change is larger than threshold
        """
        # Low confidence if values are too small
        if current_value < 100 and prior_value < 100:
            return 0.5

        # Higher confidence for larger relative changes
        abs_change = abs(change_pct)
        if abs_change > 50:
            return 0.95
        if abs_change > 30:
            return 0.85
        if abs_change > 15:
            return 0.75
        return 0.65

    def _generate_content_hash(self, detected: DetectedInsight) -> str:
        """Generate deterministic hash for deduplication."""
        parts = [
            self.tenant_id,
            detected.insight_type.value,
            detected.period_type,
            detected.period_end.isoformat() if detected.period_end else "",
            detected.platform or "",
            detected.campaign_id or "",
        ]
        for m in detected.metrics:
            parts.append(f"{m.metric_name}:{m.delta_pct:.2f}")

        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()

    def _persist_insight(
        self,
        detected: DetectedInsight,
        job_id: str,
    ) -> AIInsight | None:
        """Persist insight to database, handling deduplication."""
        from src.services.insight_templates import render_insight_summary, render_why_it_matters

        content_hash = self._generate_content_hash(detected)
        summary = render_insight_summary(detected)
        why_it_matters = render_why_it_matters(detected)

        insight = AIInsight(
            tenant_id=self.tenant_id,
            insight_type=detected.insight_type,
            severity=detected.severity,
            summary=summary,
            why_it_matters=why_it_matters,
            supporting_metrics=[m.to_dict() for m in detected.metrics],
            confidence_score=detected.confidence_score,
            period_type=detected.period_type,
            period_start=detected.period_start,
            period_end=detected.period_end,
            comparison_type=detected.comparison_type,
            platform=detected.platform,
            campaign_id=detected.campaign_id,
            currency=detected.currency,
            generated_at=datetime.now(timezone.utc),
            job_id=job_id,
            content_hash=content_hash,
            is_read=0,
            is_dismissed=0,
        )

        try:
            self.db.add(insight)
            self.db.flush()
            return insight
        except IntegrityError:
            # Duplicate constraint violation - insight already exists
            self.db.rollback()
            logger.debug(
                "Insight deduplicated",
                extra={
                    "tenant_id": self.tenant_id,
                    "content_hash": content_hash,
                },
            )
            return None
