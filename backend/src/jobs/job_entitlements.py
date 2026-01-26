"""
Job Entitlement Enforcement

Checks entitlements before running premium background jobs (syncs, exports, AI actions).
Skips jobs for non-paying users to prevent premium compute consumption.

Story 6.5.3 - Background Job Entitlement Enforcement
"""

import logging
import json
from typing import Optional, Callable
from pathlib import Path
from functools import wraps
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from src.entitlements.policy import EntitlementPolicy, BillingState
from src.models.subscription import Subscription
from src.platform.audit import AuditAction, log_system_audit_event
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class JobType(str, Enum):
    """Types of background jobs that can be premium-gated."""
    SYNC = "sync"
    EXPORT = "export"
    AI_ACTION = "ai_action"
    BACKFILL = "backfill"
    ATTRIBUTION_MODEL = "attribution_model"


@dataclass
class JobEntitlementResult:
    """Result of a job entitlement check."""
    is_allowed: bool
    billing_state: BillingState
    plan_id: Optional[str]
    reason: Optional[str] = None
    job_type: Optional[str] = None


class JobEntitlementError(Exception):
    """Raised when a job is denied due to entitlements."""
    
    def __init__(
        self,
        job_type: str,
        tenant_id: str,
        billing_state: BillingState,
        reason: str,
    ):
        self.job_type = job_type
        self.tenant_id = tenant_id
        self.billing_state = billing_state
        self.reason = reason
        super().__init__(f"Job {job_type} denied for tenant {tenant_id}: {reason}")


class JobEntitlementChecker:
    """
    Checks entitlements for background jobs.
    
    Loads premium job configuration from config/plans.json.
    Enforces gating rules based on billing_state and plan features.
    """
    
    def __init__(self, db_session: Session):
        """
        Initialize job entitlement checker.
        
        Args:
            db_session: Database session for querying subscriptions
        """
        self.db = db_session
        self._config_cache: Optional[dict] = None
    
    def _load_config(self) -> dict:
        """Load premium job configuration from config/plans.json."""
        if self._config_cache is not None:
            return self._config_cache
        
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "plans.json"
        
        if not config_path.exists():
            logger.warning("config/plans.json not found, using default premium job rules")
            self._config_cache = {
                "premium_jobs": {
                    "sync": {"required_feature": "premium_analytics", "skip_on_deny": True},
                    "export": {"required_feature": "data_export", "skip_on_deny": True},
                    "ai_action": {"required_feature": "ai_actions", "skip_on_deny": True},
                    "backfill": {"required_feature": "premium_analytics", "skip_on_deny": True},
                    "attribution_model": {"required_feature": "advanced_analytics", "skip_on_deny": True},
                }
            }
            return self._config_cache
        
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            
            # Ensure premium_jobs section exists
            if "premium_jobs" not in config:
                config["premium_jobs"] = {}
            
            self._config_cache = config
            logger.info("Loaded premium job config from config/plans.json")
            return config
        except Exception as e:
            logger.warning(f"Failed to load config/plans.json: {e}, using defaults")
            self._config_cache = {"premium_jobs": {}}
            return self._config_cache
    
    def check_job_entitlement(
        self,
        tenant_id: str,
        job_type: JobType,
        subscription: Optional[Subscription] = None,
    ) -> JobEntitlementResult:
        """
        Check if a job is allowed to run for a tenant.
        
        Args:
            tenant_id: Tenant ID
            job_type: Type of job to check
            subscription: Optional subscription (will be fetched if not provided)
            
        Returns:
            JobEntitlementResult with entitlement status
        """
        # Load configuration
        config = self._load_config()
        premium_jobs = config.get("premium_jobs", {})
        
        # Check if job type is premium-gated
        job_config = premium_jobs.get(job_type.value)
        if not job_config:
            # Job is not premium-gated - allow
            return JobEntitlementResult(
                is_allowed=True,
                billing_state=BillingState.ACTIVE,
                plan_id=None,
                job_type=job_type.value,
            )
        
        # Fetch subscription if not provided
        if subscription is None:
            subscription = self.db.query(Subscription).filter(
                Subscription.tenant_id == tenant_id
            ).order_by(Subscription.created_at.desc()).first()
        
        # Get billing state
        policy = EntitlementPolicy(self.db)
        billing_state = policy.get_billing_state(subscription)
        
        # Hard block for expired subscriptions
        if billing_state == BillingState.EXPIRED:
            return JobEntitlementResult(
                is_allowed=False,
                billing_state=billing_state,
                plan_id=subscription.plan_id if subscription else None,
                reason="Subscription expired - premium jobs are blocked",
                job_type=job_type.value,
            )
        
        # Check feature entitlement if required
        required_feature = job_config.get("required_feature")
        if required_feature:
            result = policy.check_feature_entitlement(
                tenant_id=tenant_id,
                feature=required_feature,
                subscription=subscription,
            )
            
            if not result.is_entitled:
                return JobEntitlementResult(
                    is_allowed=False,
                    billing_state=billing_state,
                    plan_id=result.plan_id,
                    reason=result.reason or f"Feature '{required_feature}' required for {job_type.value} jobs",
                    job_type=job_type.value,
                )
        
        # Allowed
        return JobEntitlementResult(
            is_allowed=True,
            billing_state=billing_state,
            plan_id=subscription.plan_id if subscription else None,
            job_type=job_type.value,
        )
    
    async def log_job_skipped(
        self,
        tenant_id: str,
        job_type: str,
        reason: str,
        billing_state: BillingState,
        plan_id: Optional[str] = None,
        audit_db: Optional[AsyncSession] = None,
    ) -> None:
        """
        Log that a job was skipped due to entitlements.
        
        Args:
            tenant_id: Tenant ID
            job_type: Type of job that was skipped
            reason: Reason for skipping
            billing_state: Current billing state
            plan_id: Current plan ID
            audit_db: Optional async audit database session
        """
        try:
            if audit_db:
                await log_system_audit_event(
                    db=audit_db,
                    tenant_id=tenant_id,
                    action=AuditAction.JOB_SKIPPED_DUE_TO_ENTITLEMENT,
                    resource_type="job",
                    resource_id=job_type,
                    metadata={
                        "job_type": job_type,
                        "reason": reason,
                        "billing_state": billing_state.value,
                        "plan_id": plan_id,
                    },
                )
            else:
                # Fallback to structured logging if audit DB not available
                logger.warning(
                    "Job skipped due to entitlement",
                    extra={
                        "tenant_id": tenant_id,
                        "job_type": job_type,
                        "reason": reason,
                        "billing_state": billing_state.value,
                        "plan_id": plan_id,
                        "action": "job.skipped_due_to_entitlement",
                    }
                )
        except Exception as e:
            logger.error(
                "Failed to log job skipped event",
                extra={
                    "tenant_id": tenant_id,
                    "job_type": job_type,
                    "error": str(e),
                }
            )
    
    async def log_job_allowed(
        self,
        tenant_id: str,
        job_type: str,
        billing_state: BillingState,
        plan_id: Optional[str] = None,
        audit_db: Optional[AsyncSession] = None,
    ) -> None:
        """
        Log that a job was allowed to run.
        
        Args:
            tenant_id: Tenant ID
            job_type: Type of job that was allowed
            billing_state: Current billing state
            plan_id: Current plan ID
            audit_db: Optional async audit database session
        """
        try:
            if audit_db:
                await log_system_audit_event(
                    db=audit_db,
                    tenant_id=tenant_id,
                    action=AuditAction.JOB_ALLOWED,
                    resource_type="job",
                    resource_id=job_type,
                    metadata={
                        "job_type": job_type,
                        "billing_state": billing_state.value,
                        "plan_id": plan_id,
                    },
                )
        except Exception as e:
            logger.error(
                "Failed to log job allowed event",
                extra={
                    "tenant_id": tenant_id,
                    "job_type": job_type,
                    "error": str(e),
                }
            )


def require_job_entitlement(
    job_type: JobType,
    skip_on_deny: bool = True,
    audit_db: Optional[AsyncSession] = None,
):
    """
    Decorator to check job entitlements before execution.
    
    Usage:
        @require_job_entitlement(JobType.SYNC)
        async def run_sync(tenant_id: str, ...):
            ...
    
    Args:
        job_type: Type of job to check
        skip_on_deny: If True, skip job silently. If False, raise exception.
        audit_db: Optional async audit database session
    
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract tenant_id from function arguments
            tenant_id = None
            
            # Try to find tenant_id in kwargs first
            if "tenant_id" in kwargs:
                tenant_id = kwargs["tenant_id"]
            else:
                # Try to find in args (check first few positional args)
                for arg in args[:3]:
                    if isinstance(arg, str) and arg.startswith("tenant_"):
                        tenant_id = arg
                        break
                    # Also check if it's a service instance with tenant_id attribute
                    if hasattr(arg, "tenant_id"):
                        tenant_id = arg.tenant_id
                        break
            
            if not tenant_id:
                logger.warning(
                    "Could not determine tenant_id for job entitlement check",
                    extra={"job_type": job_type.value, "function": func.__name__}
                )
                # Allow job to proceed if we can't determine tenant (fail-open for availability)
                return await func(*args, **kwargs)
            
            # Get database session from kwargs, args, or service instance
            db_session = kwargs.get("db_session") or kwargs.get("db")
            
            # Try to get from service instance in args
            if not db_session:
                for arg in args:
                    if hasattr(arg, "db") or hasattr(arg, "db_session"):
                        db_session = getattr(arg, "db", None) or getattr(arg, "db_session", None)
                        break
            
            if not db_session:
                logger.warning(
                    "No database session available for entitlement check",
                    extra={"job_type": job_type.value, "tenant_id": tenant_id}
                )
                # Fail-open: allow job if we can't check
                return await func(*args, **kwargs)
            
            # Check entitlement
            checker = JobEntitlementChecker(db_session)
            result = checker.check_job_entitlement(tenant_id, job_type)
            
            if not result.is_allowed:
                # Log skipped job
                await checker.log_job_skipped(
                    tenant_id=tenant_id,
                    job_type=job_type.value,
                    reason=result.reason or "Entitlement check failed",
                    billing_state=result.billing_state,
                    plan_id=result.plan_id,
                    audit_db=audit_db,
                )
                
                if skip_on_deny:
                    logger.info(
                        "Job skipped due to entitlement",
                        extra={
                            "tenant_id": tenant_id,
                            "job_type": job_type.value,
                            "reason": result.reason,
                            "billing_state": result.billing_state.value,
                        }
                    )
                    # Return early without executing job
                    return None
                else:
                    # Raise exception
                    raise JobEntitlementError(
                        job_type=job_type.value,
                        tenant_id=tenant_id,
                        billing_state=result.billing_state,
                        reason=result.reason or "Entitlement check failed",
                    )
            
            # Log allowed job
            await checker.log_job_allowed(
                tenant_id=tenant_id,
                job_type=job_type.value,
                billing_state=result.billing_state,
                plan_id=result.plan_id,
                audit_db=audit_db,
            )
            
            # Execute job
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
