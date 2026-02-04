#!/usr/bin/env python3
"""
Standalone Script for Creating Dashboard Sample Data.

This script creates comprehensive sample data for the Shopify Analytics dashboard
by hitting all ad platform endpoints and creating Shopify operations.

Usage:
    # Local testing with mocks (recommended)
    python create_dashboard_sample_data.py --local

    # Against deployed service
    python create_dashboard_sample_data.py \
        --api-url https://shopify-analytics-app-pmsl.onrender.com \
        --operations-per-platform 30

    # Dry-run mode (preview without executing)
    python create_dashboard_sample_data.py --dry-run

    # With detailed logging
    python create_dashboard_sample_data.py --local --verbose

    # Custom output format
    python create_dashboard_sample_data.py --local --output-format json > results.json
"""

import os
import sys
import argparse
import asyncio
import logging
import json
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(backend_dir))

# Set environment before imports
os.environ.setdefault("ENV", "test")
os.environ.setdefault("SHOPIFY_API_SECRET", "test-webhook-secret-for-hmac")
os.environ.setdefault("FRONTEGG_CLIENT_ID", "test-client-id")
os.environ.setdefault("FRONTEGG_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcw==")
os.environ.setdefault("AIRBYTE_API_TOKEN", "test-airbyte-token")
os.environ.setdefault("AIRBYTE_WORKSPACE_ID", "test-workspace-id")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def setup_test_environment():
    """Set up test environment with mock services."""
    # Import test fixtures
    from src.tests.e2e.mocks import MockFronteggServer

    # Initialize mock Frontegg server
    mock_frontegg = MockFronteggServer()

    return mock_frontegg


async def create_sample_data_local(
    operations_per_platform: int = 20,
    verbose: bool = False,
):
    """
    Create sample data using local TestClient with mocks.

    Args:
        operations_per_platform: Number of operations per platform
        verbose: Enable verbose logging

    Returns:
        TestSummary with results
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Setting up local test environment with mocks")

    # Import dependencies
    from fastapi.testclient import TestClient
    from httpx import AsyncClient
    from src.tests.e2e.conftest import _get_async_database_url
    from src.tests.e2e.sample_data_generator import SampleDataGenerator
    from src.tests.e2e.mocks import MockFronteggServer
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    # Set up mock Frontegg
    mock_frontegg = MockFronteggServer()

    # Generate unique tenant
    tenant_id = f"e2e-test-{int(time.time())}-{uuid.uuid4().hex[:8]}"

    # Create JWT token
    test_token = mock_frontegg.create_test_token(
        tenant_id=tenant_id,
        entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS", "AI_ACTIONS"],
    )

    auth_headers = {"Authorization": f"Bearer {test_token}"}

    logger.info(f"Generated test tenant: {tenant_id}")
    logger.info(f"Generated JWT token: {test_token[:20]}...")

    # Set up database session
    database_url = _get_async_database_url()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Import and configure app
    from main import app
    from src.database.session import get_db_session

    # Override database dependency
    async def override_get_db():
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    # Create async client using ASGITransport (httpx 0.23.0+ pattern)
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Get database session for verification
        async with async_session_maker() as db_session:
            # Create sample data generator
            generator = SampleDataGenerator(
                client=client,
                auth_headers=auth_headers,
                tenant_id=tenant_id,
                db_session=db_session,
            )

            # Run full test suite
            logger.info("Starting sample data generation...")
            summary = await generator.run_full_test_suite()

            # Commit database changes
            await db_session.commit()

            logger.info("Sample data generation completed")

            return summary


async def create_sample_data_remote(
    api_url: str,
    jwt_token: str,
    operations_per_platform: int = 20,
    verbose: bool = False,
):
    """
    Create sample data against deployed service.

    Args:
        api_url: Base URL of deployed service
        jwt_token: Valid JWT token for authentication
        operations_per_platform: Number of operations per platform
        verbose: Enable verbose logging

    Returns:
        TestSummary with results
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Creating sample data against: {api_url}")

    # Import dependencies
    import httpx
    from src.tests.e2e.sample_data_generator import SampleDataGenerator

    # Extract tenant_id from JWT
    import jwt
    decoded = jwt.decode(jwt_token, options={"verify_signature": False})
    tenant_id = decoded.get("org_id", "unknown")

    auth_headers = {"Authorization": f"Bearer {jwt_token}"}

    logger.info(f"Using tenant: {tenant_id}")

    # Create HTTP client
    async with httpx.AsyncClient(base_url=api_url, timeout=30.0) as client:
        # Create sample data generator (no db_session for remote)
        generator = SampleDataGenerator(
            client=client,
            auth_headers=auth_headers,
            tenant_id=tenant_id,
            db_session=None,
        )

        # Run full test suite
        logger.info("Starting sample data generation...")
        summary = await generator.run_full_test_suite()

        logger.info("Sample data generation completed")

        return summary


def print_summary_text(summary):
    """Print summary in human-readable text format."""
    from src.tests.e2e.sample_data_generator import SampleDataGenerator

    # Create a temporary generator just for report generation
    generator = SampleDataGenerator(
        client=None,
        auth_headers={},
        tenant_id=summary.tenant_id,
    )
    generator.summary = summary

    report = generator.generate_report()
    print(report)


def print_summary_json(summary):
    """Print summary in JSON format."""
    summary_dict = {
        "tenant_id": summary.tenant_id,
        "start_time": summary.start_time.isoformat(),
        "end_time": summary.end_time.isoformat() if summary.end_time else None,
        "platforms_tested": summary.platforms_tested,
        "total_operations": summary.total_operations,
        "successful_operations": summary.successful_operations,
        "failed_operations": summary.failed_operations,
        "platform_results": {
            platform: {
                "success_count": result.success_count,
                "error_count": result.error_count,
                "total_duration_ms": result.total_duration_ms,
                "connection_id": result.connection_id,
            }
            for platform, result in summary.platform_results.items()
        },
        "db_verification": summary.db_verification,
    }

    print(json.dumps(summary_dict, indent=2))


async def main():
    """Main entry point for standalone script."""
    parser = argparse.ArgumentParser(
        description="Create comprehensive sample data for Shopify Analytics dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local testing with mocks
  %(prog)s --local

  # Against deployed service
  %(prog)s --api-url https://shopify-analytics-app-pmsl.onrender.com --jwt-token YOUR_TOKEN

  # Dry-run to preview
  %(prog)s --dry-run

  # JSON output
  %(prog)s --local --output-format json > results.json
        """,
    )

    # Execution mode
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--local",
        action="store_true",
        help="Run locally with TestClient and mocks",
    )
    mode_group.add_argument(
        "--api-url",
        type=str,
        help="Base URL of deployed service",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview configuration without executing",
    )

    # Authentication
    parser.add_argument(
        "--jwt-token",
        type=str,
        help="JWT token for authentication (required for --api-url)",
    )

    # Configuration
    parser.add_argument(
        "--operations-per-platform",
        type=int,
        default=20,
        help="Number of operations per platform (default: 20)",
    )

    # Output
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.api_url and not args.jwt_token:
        parser.error("--jwt-token is required when using --api-url")

    # Dry-run mode
    if args.dry_run:
        print("=== DRY-RUN MODE ===")
        print(f"Operations per platform: {args.operations_per_platform}")
        print(f"Output format: {args.output_format}")
        print("\nConfiguration validated successfully!")
        print("Remove --dry-run to execute.")
        return

    # Execute
    try:
        if args.local:
            summary = await create_sample_data_local(
                operations_per_platform=args.operations_per_platform,
                verbose=args.verbose,
            )
        else:
            summary = await create_sample_data_remote(
                api_url=args.api_url,
                jwt_token=args.jwt_token,
                operations_per_platform=args.operations_per_platform,
                verbose=args.verbose,
            )

        # Print results
        if args.output_format == "json":
            print_summary_json(summary)
        else:
            print_summary_text(summary)

        # Exit code based on success
        if summary.failed_operations == 0 and summary.successful_operations > 0:
            sys.exit(0)
        else:
            logger.warning(f"Some operations failed: {summary.failed_operations}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
