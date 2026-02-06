"""
Middleware package for data availability and quality enforcement.

Provides:
- DataAvailabilityGuard: Decorator-based and DI-based guards for API endpoints
- SupersetAvailabilityHook: Query access control for Superset dashboards
- AIAvailabilityCheck: AI feature gating based on data availability state
- DataQualityGuard: Guards that block consumers based on DQ state (PASS/WARN/FAIL)
- SupersetQualityHook: Superset query access control based on data quality state
"""
