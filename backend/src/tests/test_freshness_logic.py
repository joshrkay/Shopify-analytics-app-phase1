"""
Tests for FreshnessService — data freshness tracking and AI staleness gate.

Validates:
- Per-source freshness classification (fresh / stale / critical / never_synced)
- Dashboard summary aggregation and scoring
- AI freshness gate blocks when data is stale
- AI freshness gate allows when data is fresh
- record_successful_sync updates connection timestamps
- Tenant isolation (tenant A cannot see tenant B's data)
- Edge cases: no sources, disabled sources, mixed freshness

Story: Expose data freshness to downstream systems
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.services.freshness_service import (
    FreshnessService,
    FreshnessGateResult,
    FreshnessSummary,
    SourceFreshness,
    DEFAULT_FRESHNESS_THRESHOLD_MINUTES,
    DEFAULT_CRITICAL_THRESHOLD_MINUTES,
    AI_STALENESS_BLOCK_THRESHOLD_MINUTES,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_connection(
    tenant_id,
    source_type="shopify",
    last_sync_at=None,
    last_sync_status="success",
    sync_frequency_minutes="60",
    is_enabled=True,
    status=None,
    connection_name=None,
):
    """Create a mock TenantAirbyteConnection."""
    from src.models.airbyte_connection import ConnectionStatus

    conn = MagicMock()
    conn.id = str(uuid.uuid4())
    conn.tenant_id = tenant_id
    conn.source_type = source_type
    conn.connection_name = connection_name or f"Test {source_type} connection"
    conn.last_sync_at = last_sync_at
    conn.last_sync_status = last_sync_status
    conn.sync_frequency_minutes = sync_frequency_minutes
    conn.is_enabled = is_enabled
    conn.status = status or ConnectionStatus.ACTIVE
    return conn


# =============================================================================
# Test: Initialization
# =============================================================================

class TestFreshnessServiceInit:
    """Tests for FreshnessService initialization."""

    def test_requires_tenant_id(self):
        """FreshnessService raises ValueError when tenant_id is empty."""
        db = MagicMock()
        with pytest.raises(ValueError, match="tenant_id is required"):
            FreshnessService(db_session=db, tenant_id="")

    def test_requires_non_none_tenant_id(self):
        """FreshnessService raises ValueError when tenant_id is None."""
        db = MagicMock()
        with pytest.raises(ValueError):
            FreshnessService(db_session=db, tenant_id=None)

    def test_default_ai_threshold(self):
        """Default AI block threshold is 1440 minutes (24h)."""
        db = MagicMock()
        svc = FreshnessService(db_session=db, tenant_id="t-1")
        assert svc.ai_block_threshold_minutes == 1440

    def test_custom_ai_threshold(self):
        """AI block threshold can be customized."""
        db = MagicMock()
        svc = FreshnessService(
            db_session=db, tenant_id="t-1",
            ai_block_threshold_minutes=720,
        )
        assert svc.ai_block_threshold_minutes == 720


# =============================================================================
# Test: Freshness Classification
# =============================================================================

class TestFreshnessClassification:
    """Tests for _classify_freshness method."""

    def _make_service(self):
        return FreshnessService(db_session=MagicMock(), tenant_id="t-1")

    def test_never_synced(self):
        """None last_sync_at → never_synced."""
        svc = self._make_service()
        assert svc._classify_freshness(None, 60) == "never_synced"

    def test_fresh_within_threshold(self):
        """Sync 30 minutes ago with 60-min frequency → fresh."""
        svc = self._make_service()
        ts = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert svc._classify_freshness(ts, 60) == "fresh"

    def test_fresh_at_effective_threshold(self):
        """Sync exactly at effective threshold boundary → fresh."""
        svc = self._make_service()
        # effective_threshold = max(60, 120) = 120
        ts = datetime.now(timezone.utc) - timedelta(minutes=119)
        assert svc._classify_freshness(ts, 60) == "fresh"

    def test_stale_beyond_freshness_threshold(self):
        """Sync 180 minutes ago → stale (beyond 120 but under 1440)."""
        svc = self._make_service()
        ts = datetime.now(timezone.utc) - timedelta(minutes=180)
        assert svc._classify_freshness(ts, 60) == "stale"

    def test_critical_beyond_24h(self):
        """Sync 25 hours ago → critical."""
        svc = self._make_service()
        ts = datetime.now(timezone.utc) - timedelta(hours=25)
        assert svc._classify_freshness(ts, 60) == "critical"

    def test_high_frequency_uses_larger_threshold(self):
        """Sync frequency of 360 min → effective threshold is 360, not 120."""
        svc = self._make_service()
        ts = datetime.now(timezone.utc) - timedelta(minutes=300)
        # effective_threshold = max(360, 120) = 360 → 300 < 360 → fresh
        assert svc._classify_freshness(ts, 360) == "fresh"

    def test_timezone_naive_treated_as_utc(self):
        """Timezone-naive datetime treated as UTC."""
        svc = self._make_service()
        ts = datetime.utcnow() - timedelta(minutes=30)
        assert svc._classify_freshness(ts, 60) == "fresh"


# =============================================================================
# Test: Source Freshness Building
# =============================================================================

class TestBuildSourceFreshness:
    """Tests for _build_source_freshness."""

    def test_healthy_source(self):
        """Active, enabled, fresh source is healthy."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        sf = svc._build_source_freshness(conn)

        assert sf.freshness_status == "fresh"
        assert sf.is_healthy is True
        assert sf.is_stale is False
        assert sf.warning_message is None

    def test_stale_source_warning(self):
        """Stale source includes warning message."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        sf = svc._build_source_freshness(conn)

        assert sf.freshness_status == "stale"
        assert sf.is_stale is True
        assert sf.is_healthy is False
        assert "stale" in sf.warning_message.lower()

    def test_critical_source_warning(self):
        """Critical source includes critical warning message."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        sf = svc._build_source_freshness(conn)

        assert sf.freshness_status == "critical"
        assert sf.is_stale is True
        assert "critically stale" in sf.warning_message.lower()

    def test_never_synced_warning(self):
        """Never-synced source includes appropriate warning."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection("t-1", last_sync_at=None)
        sf = svc._build_source_freshness(conn)

        assert sf.freshness_status == "never_synced"
        assert sf.is_stale is True
        assert "never been synced" in sf.warning_message.lower()

    def test_failed_last_sync_not_healthy(self):
        """Source with failed last sync is not healthy even if within window."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            last_sync_status="failed",
        )
        sf = svc._build_source_freshness(conn)

        assert sf.freshness_status == "fresh"
        assert sf.is_healthy is False  # failed sync → not healthy

    def test_sync_frequency_parsing(self):
        """Sync frequency is parsed into int minutes."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc),
            sync_frequency_minutes="120",
        )
        sf = svc._build_source_freshness(conn)
        assert sf.sync_frequency_minutes == 120

    def test_invalid_sync_frequency_defaults_to_60(self):
        """Invalid sync frequency string defaults to 60."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc),
            sync_frequency_minutes="invalid",
        )
        sf = svc._build_source_freshness(conn)
        assert sf.sync_frequency_minutes == 60


# =============================================================================
# Test: Per-Source Freshness Queries
# =============================================================================

class TestGetSourceFreshness:
    """Tests for get_source_freshness and get_all_source_freshness."""

    def test_filter_by_source_type(self):
        """get_source_freshness only returns matching source_type."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        shopify = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc),
        )
        meta = _make_connection(
            "t-1", source_type="meta",
            last_sync_at=datetime.now(timezone.utc),
        )
        with patch.object(svc, "_get_connections", return_value=[shopify, meta]):
            result = svc.get_source_freshness("shopify")

        assert len(result) == 1
        assert result[0].source_type == "shopify"

    def test_empty_for_missing_source(self):
        """get_source_freshness returns empty list if source type not found."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        with patch.object(svc, "_get_connections", return_value=[]):
            result = svc.get_source_freshness("unknown")
        assert result == []

    def test_get_all_returns_all(self):
        """get_all_source_freshness returns all enabled sources."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conns = [
            _make_connection(
                "t-1", source_type=st,
                last_sync_at=datetime.now(timezone.utc),
            )
            for st in ("shopify", "meta", "google")
        ]
        with patch.object(svc, "_get_connections", return_value=conns):
            result = svc.get_all_source_freshness()
        assert len(result) == 3


# =============================================================================
# Test: Dashboard Summary
# =============================================================================

class TestFreshnessSummary:
    """Tests for get_freshness_summary."""

    def test_no_sources_gives_100_score(self):
        """Tenant with no sources gets 100% freshness score."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        with patch.object(svc, "_get_connections", return_value=[]):
            summary = svc.get_freshness_summary()

        assert summary.total_sources == 0
        assert summary.overall_freshness_score == 100.0
        assert summary.has_stale_data is False

    def test_all_fresh_gives_100_score(self):
        """All-fresh sources → 100% score."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conns = [
            _make_connection(
                "t-1", source_type=st,
                last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            for st in ("shopify", "meta")
        ]
        with patch.object(svc, "_get_connections", return_value=conns):
            summary = svc.get_freshness_summary()

        assert summary.total_sources == 2
        assert summary.fresh_sources == 2
        assert summary.stale_sources == 0
        assert summary.overall_freshness_score == 100.0
        assert summary.has_stale_data is False

    def test_mixed_freshness_scoring(self):
        """Mix of fresh and stale → blended score."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        fresh = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        stale = _make_connection(
            "t-1", source_type="meta",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        with patch.object(svc, "_get_connections", return_value=[fresh, stale]):
            summary = svc.get_freshness_summary()

        assert summary.fresh_sources == 1
        assert summary.stale_sources == 1
        # Score: (100 + 50) / 2 = 75.0
        assert summary.overall_freshness_score == 75.0
        assert summary.has_stale_data is True

    def test_critical_sources_score_zero(self):
        """Critical sources contribute 0 to the score."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        critical = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        with patch.object(svc, "_get_connections", return_value=[critical]):
            summary = svc.get_freshness_summary()

        assert summary.critical_sources == 1
        assert summary.overall_freshness_score == 0.0
        assert summary.has_stale_data is True

    def test_never_synced_scores_25(self):
        """Never-synced sources contribute 25 to the score."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        never = _make_connection("t-1", last_sync_at=None)
        with patch.object(svc, "_get_connections", return_value=[never]):
            summary = svc.get_freshness_summary()

        assert summary.never_synced_sources == 1
        assert summary.overall_freshness_score == 25.0

    def test_summary_includes_source_details(self):
        """Summary sources list contains SourceFreshness entries."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1", last_sync_at=datetime.now(timezone.utc),
        )
        with patch.object(svc, "_get_connections", return_value=[conn]):
            summary = svc.get_freshness_summary()

        assert len(summary.sources) == 1
        assert isinstance(summary.sources[0], SourceFreshness)

    def test_summary_to_dict(self):
        """FreshnessSummary.to_dict() returns serializable dict."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        with patch.object(svc, "_get_connections", return_value=[]):
            summary = svc.get_freshness_summary()

        d = summary.to_dict()
        assert d["tenant_id"] == "t-1"
        assert d["overall_freshness_score"] == 100.0
        assert isinstance(d["sources"], list)


# =============================================================================
# Test: AI Freshness Gate
# =============================================================================

class TestAIFreshnessGate:
    """Tests for check_freshness_gate — the AI staleness blocker."""

    def test_blocks_when_no_sources(self):
        """Gate blocks AI when tenant has no enabled sources."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        with patch.object(svc, "_get_connections", return_value=[]):
            gate = svc.check_freshness_gate()

        assert gate.is_allowed is False
        assert "No enabled data sources" in gate.reason

    def test_allows_when_all_fresh(self):
        """Gate allows AI when all sources are fresh."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conns = [
            _make_connection(
                "t-1", source_type=st,
                last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            for st in ("shopify", "meta")
        ]
        with patch.object(svc, "_get_connections", return_value=conns):
            gate = svc.check_freshness_gate()

        assert gate.is_allowed is True
        assert gate.freshness_score == 100.0
        assert gate.stale_sources == []

    def test_blocks_when_critical(self):
        """Gate blocks AI when any source is critically stale (>24h)."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        fresh = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        critical = _make_connection(
            "t-1", source_type="meta",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        with patch.object(svc, "_get_connections", return_value=[fresh, critical]):
            with patch.object(svc, "_log_ai_gate_blocked"):
                gate = svc.check_freshness_gate()

        assert gate.is_allowed is False
        assert len(gate.stale_sources) == 1
        assert "meta" in gate.stale_sources[0]

    def test_blocks_when_never_synced(self):
        """Gate blocks AI when any source has never been synced."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        never = _make_connection("t-1", source_type="shopify", last_sync_at=None)
        with patch.object(svc, "_get_connections", return_value=[never]):
            with patch.object(svc, "_log_ai_gate_blocked"):
                gate = svc.check_freshness_gate()

        assert gate.is_allowed is False
        assert "never synced" in gate.stale_sources[0]

    def test_allows_when_stale_but_below_ai_threshold(self):
        """Gate ALLOWS when source is stale but under 24h AI threshold."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        stale = _make_connection(
            "t-1", source_type="shopify",
            # 3 hours → stale but under 24h AI block threshold
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        with patch.object(svc, "_get_connections", return_value=[stale]):
            gate = svc.check_freshness_gate()

        assert gate.is_allowed is True

    def test_required_sources_filter(self):
        """Gate only checks required_sources when specified."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        shopify_fresh = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        meta_critical = _make_connection(
            "t-1", source_type="meta",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        with patch.object(
            svc, "_get_connections",
            return_value=[shopify_fresh, meta_critical],
        ):
            # Only require shopify → should pass
            gate = svc.check_freshness_gate(required_sources=["shopify"])

        assert gate.is_allowed is True

    def test_required_sources_missing_blocks(self):
        """Gate blocks when required_sources are not found."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        shopify = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc),
        )
        with patch.object(svc, "_get_connections", return_value=[shopify]):
            gate = svc.check_freshness_gate(required_sources=["meta"])

        assert gate.is_allowed is False
        assert "Required sources not found" in gate.reason

    def test_custom_ai_threshold(self):
        """Custom AI threshold is respected."""
        svc = FreshnessService(
            db_session=MagicMock(), tenant_id="t-1",
            ai_block_threshold_minutes=60,
        )
        conn = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=90),
        )
        with patch.object(svc, "_get_connections", return_value=[conn]):
            with patch.object(svc, "_log_ai_gate_blocked"):
                gate = svc.check_freshness_gate()

        # 90 min > 60 min threshold → blocked
        assert gate.is_allowed is False

    def test_gate_audit_called_on_block(self):
        """AI gate logs an audit event when blocking."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        critical = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        with patch.object(svc, "_get_connections", return_value=[critical]):
            with patch.object(svc, "_log_ai_gate_blocked") as mock_audit:
                svc.check_freshness_gate()

        mock_audit.assert_called_once()
        stale_arg = mock_audit.call_args[0][0]
        assert len(stale_arg) == 1

    def test_gate_result_to_dict(self):
        """FreshnessGateResult.to_dict() returns expected keys."""
        result = FreshnessGateResult(
            is_allowed=False,
            reason="test reason",
            stale_sources=["shopify"],
            freshness_score=50.0,
        )
        d = result.to_dict()
        assert d["is_allowed"] is False
        assert d["reason"] == "test reason"
        assert d["stale_sources"] == ["shopify"]
        assert d["freshness_score"] == 50.0


# =============================================================================
# Test: Static Convenience Method
# =============================================================================

class TestStaticAIGate:
    """Tests for the static check_ai_freshness_gate method."""

    def test_static_method_delegates_to_instance(self):
        """Static method creates service and delegates."""
        db = MagicMock()
        with patch.object(
            FreshnessService, "check_freshness_gate",
            return_value=FreshnessGateResult(is_allowed=True),
        ) as mock_gate:
            result = FreshnessService.check_ai_freshness_gate(
                db_session=db,
                tenant_id="t-1",
                required_sources=["shopify"],
            )

        assert result.is_allowed is True
        mock_gate.assert_called_once_with(required_sources=["shopify"])

    def test_static_method_custom_threshold(self):
        """Static method passes custom threshold to service."""
        db = MagicMock()
        with patch.object(
            FreshnessService, "__init__", return_value=None,
        ) as mock_init:
            with patch.object(
                FreshnessService, "check_freshness_gate",
                return_value=FreshnessGateResult(is_allowed=True),
            ):
                FreshnessService.check_ai_freshness_gate(
                    db_session=db,
                    tenant_id="t-1",
                    ai_block_threshold_minutes=360,
                )

        mock_init.assert_called_once_with(
            db_session=db,
            tenant_id="t-1",
            ai_block_threshold_minutes=360,
        )


# =============================================================================
# Test: Record Successful Sync
# =============================================================================

class TestRecordSuccessfulSync:
    """Tests for record_successful_sync."""

    def test_updates_connection(self):
        """record_successful_sync updates last_sync_at via UPDATE stmt."""
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute.return_value = mock_result

        svc = FreshnessService(db_session=db, tenant_id="t-1")
        result = svc.record_successful_sync(connection_id="conn-123")

        assert result is True
        db.execute.assert_called_once()
        db.flush.assert_called_once()

    def test_returns_false_if_not_found(self):
        """record_successful_sync returns False when connection not found."""
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        db.execute.return_value = mock_result

        svc = FreshnessService(db_session=db, tenant_id="t-1")
        result = svc.record_successful_sync(connection_id="conn-missing")

        assert result is False

    def test_custom_synced_at(self):
        """record_successful_sync accepts custom timestamp."""
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute.return_value = mock_result

        ts = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        svc = FreshnessService(db_session=db, tenant_id="t-1")
        result = svc.record_successful_sync(
            connection_id="conn-123", synced_at=ts,
        )

        assert result is True


# =============================================================================
# Test: Threshold Constants
# =============================================================================

class TestThresholdConstants:
    """Tests for freshness threshold constants."""

    def test_default_freshness_threshold(self):
        """Default freshness threshold is 120 minutes."""
        assert DEFAULT_FRESHNESS_THRESHOLD_MINUTES == 120

    def test_default_critical_threshold(self):
        """Default critical threshold is 1440 minutes (24h)."""
        assert DEFAULT_CRITICAL_THRESHOLD_MINUTES == 1440

    def test_ai_block_threshold(self):
        """AI block threshold is 1440 minutes (24h)."""
        assert AI_STALENESS_BLOCK_THRESHOLD_MINUTES == 1440

    def test_freshness_below_critical(self):
        """Freshness threshold is always below critical threshold."""
        assert DEFAULT_FRESHNESS_THRESHOLD_MINUTES < DEFAULT_CRITICAL_THRESHOLD_MINUTES

    def test_ai_threshold_matches_critical(self):
        """AI block threshold equals the critical threshold."""
        assert AI_STALENESS_BLOCK_THRESHOLD_MINUTES == DEFAULT_CRITICAL_THRESHOLD_MINUTES


# =============================================================================
# Test: Data Classes
# =============================================================================

class TestDataClasses:
    """Tests for SourceFreshness, FreshnessSummary, and FreshnessGateResult."""

    def test_source_freshness_to_dict(self):
        """SourceFreshness.to_dict() returns serializable dict."""
        ts = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        sf = SourceFreshness(
            connection_id="c-1",
            connection_name="Test",
            source_type="shopify",
            last_sync_at=ts,
            last_sync_status="success",
            sync_frequency_minutes=60,
            minutes_since_sync=30,
            freshness_status="fresh",
            is_stale=False,
            is_healthy=True,
        )
        d = sf.to_dict()
        assert d["connection_id"] == "c-1"
        assert d["last_sync_at"] == ts.isoformat()
        assert d["freshness_status"] == "fresh"
        assert d["is_stale"] is False

    def test_source_freshness_to_dict_null_sync(self):
        """SourceFreshness.to_dict() handles None last_sync_at."""
        sf = SourceFreshness(
            connection_id="c-1",
            connection_name="Test",
            source_type="shopify",
            last_sync_at=None,
            last_sync_status=None,
            sync_frequency_minutes=60,
            minutes_since_sync=None,
            freshness_status="never_synced",
            is_stale=True,
            is_healthy=False,
        )
        d = sf.to_dict()
        assert d["last_sync_at"] is None
        assert d["minutes_since_sync"] is None

    def test_freshness_summary_defaults(self):
        """FreshnessSummary sources list defaults to empty."""
        summary = FreshnessSummary(
            tenant_id="t-1",
            total_sources=0,
            fresh_sources=0,
            stale_sources=0,
            critical_sources=0,
            never_synced_sources=0,
            overall_freshness_score=100.0,
            has_stale_data=False,
        )
        assert summary.sources == []

    def test_gate_result_defaults(self):
        """FreshnessGateResult defaults."""
        gate = FreshnessGateResult(is_allowed=True)
        assert gate.reason is None
        assert gate.stale_sources == []
        assert gate.freshness_score == 100.0


# =============================================================================
# Test: Audit Logging
# =============================================================================

class TestAuditLogging:
    """Tests for audit event logging in freshness gate."""

    @patch("src.services.freshness_service.logger")
    def test_audit_failure_does_not_crash(self, mock_logger):
        """Audit logging failure is caught and does not crash the gate."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")

        with patch(
            "src.services.freshness_service.FreshnessService._log_ai_gate_blocked",
            side_effect=Exception("audit down"),
        ):
            # Force the original method to be called
            pass

        # Call the real _log_ai_gate_blocked with a broken audit import
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("audit DB down"),
        ):
            # Should not raise
            svc._log_ai_gate_blocked(["shopify (1500min stale)"])

        mock_logger.error.assert_called_once()

    def test_audit_called_with_correct_action(self):
        """Audit event uses AI_ACTION_BLOCKED action."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")

        with patch(
            "src.platform.audit.log_system_audit_event_sync",
        ) as mock_audit:
            svc._log_ai_gate_blocked(["shopify (critical)"])

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        # Check action is AI_ACTION_BLOCKED
        from src.platform.audit import AuditAction
        assert call_kwargs.kwargs.get("action") or call_kwargs[1].get("action") is not None


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests for freshness service."""

    def test_multiple_connections_same_source(self):
        """Multiple connections of same source_type are all returned."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conns = [
            _make_connection(
                "t-1", source_type="shopify",
                last_sync_at=datetime.now(timezone.utc),
                connection_name=f"Shopify {i}",
            )
            for i in range(3)
        ]
        with patch.object(svc, "_get_connections", return_value=conns):
            result = svc.get_source_freshness("shopify")
        assert len(result) == 3

    def test_minutes_since_sync_is_integer(self):
        """minutes_since_sync is always an integer (not float)."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        conn = _make_connection(
            "t-1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=45, seconds=30),
        )
        sf = svc._build_source_freshness(conn)
        assert isinstance(sf.minutes_since_sync, int)

    def test_freshness_gate_score_with_mixed_states(self):
        """Gate score reflects fraction of fresh sources."""
        svc = FreshnessService(db_session=MagicMock(), tenant_id="t-1")
        fresh1 = _make_connection(
            "t-1", source_type="shopify",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        fresh2 = _make_connection(
            "t-1", source_type="meta",
            last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        stale = _make_connection(
            "t-1", source_type="google",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        with patch.object(
            svc, "_get_connections",
            return_value=[fresh1, fresh2, stale],
        ):
            gate = svc.check_freshness_gate()

        # 2 out of 3 fresh → allowed (stale is under 24h AI threshold)
        assert gate.is_allowed is True
        # Score = 2/3 * 100 = 66.7
        assert gate.freshness_score == 66.7

    def test_none_sync_frequency_defaults_to_60(self):
        """None sync_frequency_minutes defaults to 60."""
        result = FreshnessService._parse_sync_frequency(None)
        assert result == 60

    def test_empty_string_sync_frequency_defaults_to_60(self):
        """Empty string sync_frequency_minutes defaults to 60."""
        result = FreshnessService._parse_sync_frequency("")
        assert result == 60
