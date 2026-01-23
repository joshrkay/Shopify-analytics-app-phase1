"""
Backfill service for dbt model reprocessing.

This service orchestrates:
- Tenant-scoped dbt backfills with date range filtering
- Audit logging for all backfill executions
- Safe parameterized dbt runs

SECURITY: All backfills are tenant-scoped. Models must filter by tenant_id.

Story 4.8 - Backfills & Reprocessing
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.audit import (
    AuditAction,
    log_system_audit_event,
)

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    """Result of a backfill operation."""
    backfill_id: str
    tenant_id: str
    model_selector: str
    start_date: str
    end_date: str
    status: str
    is_successful: bool
    rows_affected: Optional[int] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    dbt_output: Optional[str] = None
    completed_at: datetime = None


class BackfillServiceError(Exception):
    """Base exception for backfill service errors."""
    pass


class InvalidDateRangeError(BackfillServiceError):
    """Invalid date range provided for backfill."""
    pass


class DbtExecutionError(BackfillServiceError):
    """dbt execution failed."""
    pass


class BackfillService:
    """
    Service for executing tenant-scoped dbt backfills.

    Provides:
    - Date-range parameterized dbt runs
    - Tenant isolation enforcement
    - Audit logging
    - Error handling and validation

    SECURITY: All backfills are scoped to a single tenant_id.
    Models must filter by tenant_id to prevent cross-tenant data access.
    """

    def __init__(self, db_session: Session, tenant_id: str, audit_db: Optional[AsyncSession] = None):
        """
        Initialize backfill service.

        Args:
            db_session: Database session (synchronous, for future use)
            tenant_id: Tenant identifier (from JWT, never from request)
            audit_db: Async database session for audit logging (optional)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required and cannot be empty")

        self.db_session = db_session
        self.tenant_id = tenant_id
        self.audit_db = audit_db

        # Get analytics directory path (assumes backend and analytics are siblings)
        project_root = Path(__file__).parent.parent.parent.parent
        self.analytics_dir = project_root / "analytics"

        if not self.analytics_dir.exists():
            raise BackfillServiceError(
                f"Analytics directory not found: {self.analytics_dir}"
            )

    async def execute_backfill(
        self,
        model_selector: str,
        start_date: str,
        end_date: str,
        backfill_id: Optional[str] = None,
    ) -> BackfillResult:
        """
        Execute a dbt backfill for the specified date range.

        Args:
            model_selector: dbt model selector (e.g., "fact_orders", "facts", "fact_orders+")
            start_date: Start date for backfill (YYYY-MM-DD or YYYY-MM-DD HH:MI:SS)
            end_date: End date for backfill (YYYY-MM-DD or YYYY-MM-DD HH:MI:SS)
            backfill_id: Optional backfill ID for tracking (generated if not provided)

        Returns:
            BackfillResult with execution details

        Raises:
            InvalidDateRangeError: If date range is invalid
            DbtExecutionError: If dbt execution fails
        """
        import uuid

        if not backfill_id:
            backfill_id = str(uuid.uuid4())

        start_time = datetime.now(timezone.utc)

        logger.info(
            "Backfill execution started",
            extra={
                "backfill_id": backfill_id,
                "tenant_id": self.tenant_id,
                "model_selector": model_selector,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

        # Log audit event for backfill start
        if self.audit_db:
            try:
                await log_system_audit_event(
                    db=self.audit_db,
                    tenant_id=self.tenant_id,
                    action=AuditAction.BACKFILL_STARTED,
                    resource_type="backfill",
                    resource_id=backfill_id,
                    metadata={
                        "model_selector": model_selector,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    correlation_id=backfill_id,
                )
            except Exception as e:
                # Don't fail backfill if audit logging fails
                logger.warning(
                    "Failed to log backfill start audit event",
                    extra={"backfill_id": backfill_id, "error": str(e)},
                )

        # Validate date range
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError as e:
            raise InvalidDateRangeError(f"Invalid date format: {e}")

        if start_dt > end_dt:
            raise InvalidDateRangeError(
                f"Start date ({start_date}) must be before end date ({end_date})"
            )

        # Validate date range is not too large (safety limit: 1 year)
        days_diff = (end_dt - start_dt).days
        if days_diff > 365:
            raise InvalidDateRangeError(
                f"Date range too large: {days_diff} days. Maximum allowed: 365 days"
            )

        # Build dbt command with variables
        # CRITICAL: Models must filter by tenant_id - we pass tenant_id as a variable
        # but models are responsible for enforcing tenant isolation
        dbt_vars = {
            "backfill_start_date": start_date,
            "backfill_end_date": end_date,
            "backfill_tenant_id": self.tenant_id,  # Pass tenant_id for model filtering
        }

        # Convert vars dict to dbt format: --vars '{"key": "value"}'
        import json
        vars_json = json.dumps(dbt_vars)

        # Execute dbt run
        cmd = [
            "dbt",
            "run",
            "--select", model_selector,
            "--vars", vars_json,
            "--profiles-dir", str(self.analytics_dir),
            "--project-dir", str(self.analytics_dir),
        ]

        logger.info(
            "Executing dbt command",
            extra={
                "backfill_id": backfill_id,
                "tenant_id": self.tenant_id,
                "command": " ".join(cmd),
            },
        )

        try:
            # Run dbt command asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.analytics_dir),
                env=os.environ.copy(),
            )

            stdout, stderr = await process.communicate()

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            completed_at = datetime.now(timezone.utc)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8") if stderr else "Unknown error"
                logger.error(
                    "dbt execution failed",
                    extra={
                        "backfill_id": backfill_id,
                        "tenant_id": self.tenant_id,
                        "returncode": process.returncode,
                        "error": error_msg[:500],  # Truncate for logging
                    },
                )

                # Log audit event for failed backfill
                if self.audit_db:
                    try:
                        await log_system_audit_event(
                            db=self.audit_db,
                            tenant_id=self.tenant_id,
                            action=AuditAction.BACKFILL_FAILED,
                            resource_type="backfill",
                            resource_id=backfill_id,
                            metadata={
                                "model_selector": model_selector,
                                "start_date": start_date,
                                "end_date": end_date,
                                "duration_seconds": duration,
                                "error": error_msg[:500],
                            },
                            correlation_id=backfill_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to log backfill failure audit event",
                            extra={"backfill_id": backfill_id, "error": str(e)},
                        )

                return BackfillResult(
                    backfill_id=backfill_id,
                    tenant_id=self.tenant_id,
                    model_selector=model_selector,
                    start_date=start_date,
                    end_date=end_date,
                    status="failed",
                    is_successful=False,
                    duration_seconds=duration,
                    error_message=error_msg[:1000],  # Truncate for storage
                    dbt_output=stderr.decode("utf-8")[:5000] if stderr else None,
                    completed_at=completed_at,
                )

            # Parse dbt output to extract row counts (if available)
            output = stdout.decode("utf-8") if stdout else ""
            rows_affected = self._extract_row_count(output)

            logger.info(
                "Backfill execution completed",
                extra={
                    "backfill_id": backfill_id,
                    "tenant_id": self.tenant_id,
                    "status": "success",
                    "duration_seconds": duration,
                    "rows_affected": rows_affected,
                },
            )

            # Log audit event for successful backfill
            if self.audit_db:
                try:
                    await log_system_audit_event(
                        db=self.audit_db,
                        tenant_id=self.tenant_id,
                        action=AuditAction.BACKFILL_COMPLETED,
                        resource_type="backfill",
                        resource_id=backfill_id,
                        metadata={
                            "model_selector": model_selector,
                            "start_date": start_date,
                            "end_date": end_date,
                            "duration_seconds": duration,
                            "rows_affected": rows_affected,
                        },
                        correlation_id=backfill_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to log backfill completion audit event",
                        extra={"backfill_id": backfill_id, "error": str(e)},
                    )

            return BackfillResult(
                backfill_id=backfill_id,
                tenant_id=self.tenant_id,
                model_selector=model_selector,
                start_date=start_date,
                end_date=end_date,
                status="success",
                is_successful=True,
                rows_affected=rows_affected,
                duration_seconds=duration,
                dbt_output=output[:5000] if output else None,
                completed_at=completed_at,
            )

        except Exception as e:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            completed_at = datetime.now(timezone.utc)

            logger.error(
                "Backfill execution error",
                extra={
                    "backfill_id": backfill_id,
                    "tenant_id": self.tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise DbtExecutionError(f"dbt execution failed: {e}") from e

    def _extract_row_count(self, dbt_output: str) -> Optional[int]:
        """
        Extract row count from dbt output if available.

        dbt output format: "Completed successfully\n  Pass=1 Warn=0 Error=0 Skipped=0 Total=1"
        Or: "Completed with X warnings\n  Pass=1 Warn=0 Error=0 Skipped=0 Total=1"
        """
        try:
            # Look for "Total=X" pattern
            import re
            match = re.search(r"Total=(\d+)", dbt_output)
            if match:
                return int(match.group(1))
        except Exception:
            pass

        return None
