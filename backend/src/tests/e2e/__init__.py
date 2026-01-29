"""
End-to-End (E2E) Tests for Shopify Analytics Platform.

This package contains E2E tests that validate the complete data flow
from API ingestion through transformation to analytics output.

Key principles:
- All test data flows through APIs (not direct database seeding)
- External services are mocked with realistic behavior
- Tenant isolation is verified at every layer
- Tests cover the full pipeline: ingestion -> transformation -> analytics -> AI
"""
