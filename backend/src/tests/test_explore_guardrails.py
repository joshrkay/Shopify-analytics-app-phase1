"""Tests for Explore guardrail bypass service and validation engine."""

from datetime import datetime, timedelta, timezone

import pytest

from src.models.explore_guardrail_exception import GuardrailExceptionStatus
from src.services.explore_guardrail_service import ExploreGuardrailService
from src.superset_explore_guardrails import (
    DatasetRules,
    ExploreGuardrailEngine,
    GuardrailLimits,
)


def _roles(*values: str):
    return list(values)


def test_request_requires_super_admin(db_session):
    service = ExploreGuardrailService(db_session=db_session, tenant_id="tenant-1")

    with pytest.raises(PermissionError):
        service.request_exception(
            requestor_id="actor-1",
            requestor_roles=_roles("editor"),
            user_id="user-1",
            dataset_names=["fact_orders"],
            reason="investigation",
            duration_minutes=15,
        )


def test_approve_requires_valid_role(db_session):
    service = ExploreGuardrailService(db_session=db_session, tenant_id="tenant-1")

    exception = service.request_exception(
        requestor_id="actor-1",
        requestor_roles=_roles("super_admin"),
        user_id="user-1",
        dataset_names=["fact_orders"],
        reason="investigation",
        duration_minutes=15,
    )

    with pytest.raises(PermissionError):
        service.approve_exception(
            approver_id="actor-2",
            approver_roles=_roles("editor"),
            exception_id=exception.id,
        )


def test_bypass_active_within_scope(db_session):
    service = ExploreGuardrailService(db_session=db_session, tenant_id="tenant-1")

    exception = service.request_exception(
        requestor_id="actor-1",
        requestor_roles=_roles("super_admin"),
        user_id="user-1",
        dataset_names=["fact_orders"],
        reason="investigation",
        duration_minutes=15,
    )
    service.approve_exception(
        approver_id="actor-2",
        approver_roles=_roles("analytics_tech_lead"),
        exception_id=exception.id,
    )

    active = service.get_active_exception_for_dataset(
        user_id="user-1",
        dataset_name="fact_orders",
    )
    assert active is not None
    assert active.status == GuardrailExceptionStatus.APPROVED

    missing = service.get_active_exception_for_dataset(
        user_id="user-1",
        dataset_name="other_dataset",
    )
    assert missing is None


def test_expired_bypass_rejected(db_session):
    service = ExploreGuardrailService(db_session=db_session, tenant_id="tenant-1")

    exception = service.request_exception(
        requestor_id="actor-1",
        requestor_roles=_roles("super_admin"),
        user_id="user-1",
        dataset_names=["fact_orders"],
        reason="investigation",
        duration_minutes=1,
    )
    exception.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    exception.status = GuardrailExceptionStatus.APPROVED
    db_session.flush()

    active = service.list_active_exceptions(user_id="user-1")
    assert active == []
    assert exception.status == GuardrailExceptionStatus.EXPIRED


def test_guardrail_engine_validation():
    limits = GuardrailLimits(
        max_date_range_days=30,
        max_group_by_dimensions=2,
        max_metrics_per_query=2,
        max_filters=2,
        row_limit=1000,
        query_timeout_seconds=20,
    )
    rules = {
        "fact_orders": DatasetRules(
            allowed_dimensions=["order_date"],
            allowed_metrics=["SUM(revenue)"],
            allowed_visualizations=["line"],
            restricted_columns=[],
        )
    }
    engine = ExploreGuardrailEngine(limits=limits, dataset_rules=rules)

    query_params = {
        "dimensions": ["order_date"],
        "metrics": ["SUM(revenue)"],
        "group_by": ["order_date"],
        "start_date": datetime.now(timezone.utc) - timedelta(days=45),
        "end_date": datetime.now(timezone.utc),
        "filters": [],
        "viz_type": "line",
    }

    decision = engine.validate_query(dataset_name="fact_orders", query_params=query_params)
    assert decision.allowed is False
    assert decision.error_code == "DATE_RANGE_EXCEEDED"

    bypassed = engine.validate_query(
        dataset_name="fact_orders",
        query_params=query_params,
        bypass_active=True,
    )
    assert bypassed.allowed is True
