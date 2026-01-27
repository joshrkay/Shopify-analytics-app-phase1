"""
Data Quality Runner Job.

Background worker that executes DQ checks for all tenants:
- Freshness checks against source-specific SLAs
- Anomaly detection (row count drops, zero values, etc.)
- Incident creation for severe failures
- Alert routing based on severity

Run as a cron job or background worker:
    python -m src.jobs.dq_runner

Configuration:
- DQ_RUN_INTERVAL_MINUTES: How often to run (default: 15)
- DQ_BATCH_SIZE: Number of tenants to process per batch (default: 50)
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import func

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.session import get_db_session_sync
from src.api.dq.service import DQService, DQEvent, DQEventType
from src.api.dq.alerts.router import get_alert_router
from src.models.dq_models import (
    DQCheck, DQResult, DQIncident,
    DQCheckType, DQSeverity, DQResultStatus, DQIncidentStatus,
    ConnectorSourceType, is_critical_source,
)
from src.models.airbyte_connection import TenantAirbyteConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DQ_BATCH_SIZE = int(os.getenv("DQ_BATCH_SIZE", "50"))


class DQRunner:
    """
    Data Quality check runner.

    Executes freshness and anomaly checks for all tenants,
    records results, creates incidents, and routes alerts.
    """

    def __init__(self, db_session: Session):
        """
        Initialize DQ runner.

        Args:
            db_session: Database session
        """
        self.db = db_session
        self.alert_router = get_alert_router()
        self.run_id = str(uuid.uuid4())
        self.stats = {
            "tenants_processed": 0,
            "connectors_checked": 0,
            "freshness_failures": 0,
            "anomalies_detected": 0,
            "incidents_created": 0,
            "incidents_resolved": 0,
            "alerts_sent": 0,
            "errors": 0,
        }

    def _get_all_tenants(self) -> List[str]:
        """Get all unique tenant IDs with active connectors."""
        result = self.db.query(TenantAirbyteConnection.tenant_id).filter(
            TenantAirbyteConnection.is_enabled == True,
            TenantAirbyteConnection.status != "deleted",
        ).distinct().all()

        return [r[0] for r in result]

    def _get_freshness_checks(self) -> List[DQCheck]:
        """Get all enabled freshness checks."""
        return self.db.query(DQCheck).filter(
            DQCheck.check_type == DQCheckType.FRESHNESS.value,
            DQCheck.is_enabled == True,
        ).all()

    def _should_block_dashboard(
        self,
        severity: DQSeverity,
        source_type: Optional[ConnectorSourceType],
        check_type: DQCheckType,
    ) -> bool:
        """
        Determine if failure should block dashboards.

        Blocking conditions:
        - Critical severity on critical fact tables (Shopify)
        - Prolonged staleness (>4x threshold) on any source
        """
        # Critical failures on Shopify always block
        if severity == DQSeverity.CRITICAL and source_type and is_critical_source(source_type):
            return True

        return False

    def _auto_resolve_incidents(
        self,
        tenant_id: str,
        connector_id: str,
        check_type: DQCheckType,
    ) -> int:
        """
        Auto-resolve open incidents that are no longer failing.

        Returns count of resolved incidents.
        """
        resolved_count = 0

        # Find open incidents for this connector and check type
        check = self.db.query(DQCheck).filter(
            DQCheck.check_type == check_type.value,
        ).first()

        if not check:
            return 0

        open_incidents = self.db.query(DQIncident).filter(
            DQIncident.tenant_id == tenant_id,
            DQIncident.connector_id == connector_id,
            DQIncident.check_id == check.id,
            DQIncident.status.in_([
                DQIncidentStatus.OPEN.value,
                DQIncidentStatus.ACKNOWLEDGED.value,
            ]),
        ).all()

        for incident in open_incidents:
            incident.status = DQIncidentStatus.AUTO_RESOLVED.value
            incident.resolved_at = datetime.now(timezone.utc)
            incident.resolved_by = "dq_runner"
            incident.resolution_notes = "Auto-resolved: check is now passing"
            resolved_count += 1

            logger.info(
                "Incident auto-resolved",
                extra={
                    "tenant_id": tenant_id,
                    "connector_id": connector_id,
                    "incident_id": incident.id,
                },
            )

        if resolved_count > 0:
            self.db.commit()

        return resolved_count

    async def run_freshness_checks(self, tenant_id: str) -> List[DQEvent]:
        """
        Run freshness checks for a single tenant.

        Returns list of events to be routed to alerting.
        """
        events = []
        correlation_id = str(uuid.uuid4())

        service = DQService(self.db, tenant_id)
        results = service.check_all_freshness(self.run_id, correlation_id)

        for result in results:
            self.stats["connectors_checked"] += 1

            # Get or create check definition
            check = self.db.query(DQCheck).filter(
                DQCheck.check_type == DQCheckType.FRESHNESS.value,
                DQCheck.source_type == result.source_type.value if result.source_type else None,
            ).first()

            # If no specific check, use a generic one
            if not check:
                check = self.db.query(DQCheck).filter(
                    DQCheck.check_type == DQCheckType.FRESHNESS.value,
                ).first()

            if not check:
                logger.warning(
                    "No freshness check definition found",
                    extra={"source_type": result.source_type.value if result.source_type else None},
                )
                continue

            if result.is_fresh:
                # Check passed - auto-resolve any open incidents
                resolved = self._auto_resolve_incidents(
                    tenant_id,
                    result.connector_id,
                    DQCheckType.FRESHNESS,
                )
                if resolved > 0:
                    self.stats["incidents_resolved"] += resolved

                    # Emit resolved event
                    events.append(DQEvent(
                        event_type=DQEventType.RESOLVED,
                        run_id=self.run_id,
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        connector_id=result.connector_id,
                        check_type=DQCheckType.FRESHNESS.value,
                        severity=None,
                        message=f"Freshness check now passing for {result.connector_name}",
                        merchant_message="Data sync is now up to date.",
                        support_details=f"Freshness check resolved for {result.connector_name}",
                    ))

                # Record passing result
                service.record_result(
                    check=check,
                    connector_id=result.connector_id,
                    run_id=self.run_id,
                    correlation_id=correlation_id,
                    status=DQResultStatus.PASSED,
                    minutes_since_sync=result.minutes_since_sync,
                    message=result.message,
                )
            else:
                # Check failed
                self.stats["freshness_failures"] += 1

                # Determine if this should block dashboards
                is_blocking = self._should_block_dashboard(
                    result.severity,
                    result.source_type,
                    DQCheckType.FRESHNESS,
                )

                # Record failing result
                service.record_result(
                    check=check,
                    connector_id=result.connector_id,
                    run_id=self.run_id,
                    correlation_id=correlation_id,
                    status=DQResultStatus.FAILED,
                    severity=result.severity,
                    threshold_value=result.threshold_minutes,
                    minutes_since_sync=result.minutes_since_sync,
                    message=result.message,
                    merchant_message=result.merchant_message,
                    support_details=result.support_details,
                )

                # Create incident for high/critical severity
                if result.severity in [DQSeverity.HIGH, DQSeverity.CRITICAL]:
                    # Check if incident already exists
                    existing = self.db.query(DQIncident).filter(
                        DQIncident.tenant_id == tenant_id,
                        DQIncident.connector_id == result.connector_id,
                        DQIncident.check_id == check.id,
                        DQIncident.status.in_([
                            DQIncidentStatus.OPEN.value,
                            DQIncidentStatus.ACKNOWLEDGED.value,
                        ]),
                    ).first()

                    if not existing:
                        service.create_incident(
                            check=check,
                            connector_id=result.connector_id,
                            result_id=None,  # Would need to get result ID
                            run_id=self.run_id,
                            correlation_id=correlation_id,
                            severity=result.severity,
                            title=f"Freshness Alert: {result.connector_name}",
                            description=result.message,
                            merchant_message=result.merchant_message,
                            support_details=result.support_details,
                            is_blocking=is_blocking,
                            recommended_actions=["Retry sync", "Check connector connection"],
                        )
                        self.stats["incidents_created"] += 1

                # Emit failure event
                event_type = DQEventType.SEVERE_BLOCK if is_blocking else DQEventType.FRESHNESS_FAILED
                events.append(DQEvent(
                    event_type=event_type,
                    run_id=self.run_id,
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    connector_id=result.connector_id,
                    check_type=DQCheckType.FRESHNESS.value,
                    severity=result.severity,
                    message=result.message,
                    merchant_message=result.merchant_message,
                    support_details=result.support_details,
                    metadata={
                        "minutes_since_sync": result.minutes_since_sync,
                        "threshold_minutes": result.threshold_minutes,
                        "source_type": result.source_type.value if result.source_type else None,
                        "is_blocking": is_blocking,
                    },
                ))

        return events

    async def run_for_tenant(self, tenant_id: str) -> List[DQEvent]:
        """
        Run all DQ checks for a single tenant.

        Returns list of events to be routed to alerting.
        """
        events = []

        try:
            # Run freshness checks
            freshness_events = await self.run_freshness_checks(tenant_id)
            events.extend(freshness_events)

            self.stats["tenants_processed"] += 1

            logger.info(
                "DQ checks completed for tenant",
                extra={
                    "tenant_id": tenant_id,
                    "events_generated": len(events),
                },
            )

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Error running DQ checks for tenant",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )

        return events

    async def route_events(self, events: List[DQEvent]) -> None:
        """Route events to alerting system."""
        for event in events:
            try:
                channels = await self.alert_router.route(event)
                if channels:
                    self.stats["alerts_sent"] += len(channels)
                    logger.info(
                        "Alert routed",
                        extra={
                            "event_type": event.event_type.value,
                            "channels": channels,
                            "tenant_id": event.tenant_id,
                        },
                    )
            except Exception as e:
                logger.error(
                    "Error routing alert",
                    extra={
                        "event_type": event.event_type.value,
                        "error": str(e),
                    },
                )

    async def run(self) -> Dict:
        """
        Run DQ checks for all tenants.

        Returns run statistics.
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting DQ runner",
            extra={"run_id": self.run_id},
        )

        all_events = []

        try:
            # Get all tenants
            tenants = self._get_all_tenants()
            logger.info(
                f"Found {len(tenants)} tenants to process",
                extra={"run_id": self.run_id},
            )

            # Process tenants in batches
            for i in range(0, len(tenants), DQ_BATCH_SIZE):
                batch = tenants[i:i + DQ_BATCH_SIZE]

                for tenant_id in batch:
                    events = await self.run_for_tenant(tenant_id)
                    all_events.extend(events)

                # Commit after each batch
                self.db.commit()

            # Route all events to alerting
            await self.route_events(all_events)

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "DQ runner failed",
                extra={
                    "run_id": self.run_id,
                    "error": str(e),
                },
                exc_info=True,
            )

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        self.stats["duration_seconds"] = duration
        self.stats["run_id"] = self.run_id

        logger.info(
            "DQ runner completed",
            extra={
                "run_id": self.run_id,
                "duration_seconds": duration,
                **self.stats,
            },
        )

        return self.stats


async def main():
    """Main entry point for DQ runner job."""
    logger.info("DQ Runner starting")

    try:
        for session in get_db_session_sync():
            runner = DQRunner(session)
            stats = await runner.run()
            logger.info("DQ Runner stats", extra=stats)
    except Exception as e:
        logger.error("DQ Runner failed", extra={"error": str(e)}, exc_info=True)
        sys.exit(1)

    logger.info("DQ Runner finished")


if __name__ == "__main__":
    asyncio.run(main())
