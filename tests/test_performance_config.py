"""
Tests for Performance Configuration limits.
Verifies that the immutable limits match the project SLAs.
"""

import sys
import os
import pytest

# Add docker/superset to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../docker/superset')))

from performance_config import PERFORMANCE_LIMITS

class TestPerformanceConfig:
    
    def test_query_timeout(self):
        """Verify query timeout is within safety limits."""
        # Requirement says < 3s per chart, but database timeout is distinct.
        # Ensure it's not excessively high (default 20s).
        assert PERFORMANCE_LIMITS.query_timeout_seconds <= 20

    def test_row_limit(self):
        """Verify row limits to prevent browser crashes."""
        assert PERFORMANCE_LIMITS.row_limit == 50_000
        assert PERFORMANCE_LIMITS.samples_row_limit == 1_000

    def test_cache_ttl(self):
        """Verify cache TTL meets the requirement (30 mins)."""
        assert PERFORMANCE_LIMITS.cache_ttl_seconds == 1800
        assert PERFORMANCE_LIMITS.cache_ttl_minutes == 30

    def test_safety_flags(self):
        """Verify critical safety flags are disabled."""
        from performance_config import SAFETY_FEATURE_FLAGS
        assert SAFETY_FEATURE_FLAGS['SQL_QUERIES_ALLOWED'] is False
        assert SAFETY_FEATURE_FLAGS['CSV_EXPORT'] is False
