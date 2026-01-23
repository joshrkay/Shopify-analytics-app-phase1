#!/usr/bin/env python3
"""
Airbyte deployment validation script.

This script validates that the Airbyte Cloud deployment is accessible
and properly configured for the AI Growth Analytics platform.

Usage:
    python backend/scripts/validate_airbyte.py

Prerequisites:
    - AIRBYTE_BASE_URL environment variable (or uses default)
    - AIRBYTE_API_TOKEN environment variable
    - AIRBYTE_WORKSPACE_ID environment variable

Exit codes:
    0 - All validations passed
    1 - One or more validations failed
"""

import asyncio
import os
import sys

# Add backend to path for imports (so src.integrations... imports work)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv


def print_status(passed: bool, message: str) -> None:
    """Print a status message with pass/fail indicator."""
    status = "\u2705" if passed else "\u274c"
    print(f"{status} {message}")


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print(f"{'=' * 60}\n")


async def validate_airbyte_setup() -> bool:
    """
    Validate Airbyte deployment is accessible from worker.

    Returns:
        True if all validations pass, False otherwise
    """
    # Load environment variables from .env if present
    load_dotenv()

    print_header("Airbyte Deployment Validation")

    # Check required environment variables
    required_vars = [
        ("AIRBYTE_API_TOKEN", "API token for authentication"),
        ("AIRBYTE_WORKSPACE_ID", "Workspace ID"),
    ]

    optional_vars = [
        ("AIRBYTE_BASE_URL", "API base URL (optional, has default)"),
    ]

    print("Checking environment variables...")
    all_vars_present = True

    for var_name, description in required_vars:
        value = os.getenv(var_name)
        if value:
            # Redact sensitive values
            if "TOKEN" in var_name or "SECRET" in var_name or "KEY" in var_name:
                display_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            else:
                display_value = value
            print_status(True, f"{var_name}: {display_value}")
        else:
            print_status(False, f"{var_name}: NOT SET - {description}")
            all_vars_present = False

    for var_name, description in optional_vars:
        value = os.getenv(var_name)
        if value:
            print_status(True, f"{var_name}: {value}")
        else:
            print(f"   {var_name}: Using default")

    if not all_vars_present:
        print("\n\u274c Required environment variables missing. Aborting validation.")
        print("\nTo set environment variables, create a .env file with:")
        print("  AIRBYTE_API_TOKEN=<your-api-token>")
        print("  AIRBYTE_WORKSPACE_ID=<your-workspace-id>")
        return False

    # Import here after we know environment is set up
    from src.integrations.airbyte.client import AirbyteClient
    from src.integrations.airbyte.exceptions import (
        AirbyteError,
        AirbyteAuthenticationError,
    )

    validation_passed = True

    # Create client
    print("\nInitializing Airbyte client...")
    try:
        client = AirbyteClient()
        print_status(True, f"Client initialized for workspace: {client.workspace_id}")
        print_status(True, f"Using API base URL: {client.base_url}")
    except ValueError as e:
        print_status(False, f"Failed to initialize client: {e}")
        return False

    async with client:
        # 1. Health check
        print("\n--- Health Check ---")
        try:
            health = await client.check_health()
            if health.available:
                print_status(True, "Airbyte API is available")
                print_status(True, f"Database status: {'OK' if health.db else 'UNAVAILABLE'}")
            else:
                print_status(False, "Airbyte API is not available")
                validation_passed = False
        except AirbyteAuthenticationError as e:
            print_status(False, f"Authentication failed: {e.message}")
            print("    Check that your API token is valid and has not expired.")
            print("    Generate a new token at: Workspace Settings -> API Tokens")
            validation_passed = False
        except AirbyteError as e:
            print_status(False, f"Health check failed: {e.message}")
            validation_passed = False
        except Exception as e:
            print_status(False, f"Unexpected error during health check: {e}")
            validation_passed = False

        # 2. List connections
        print("\n--- Connections ---")
        try:
            connections = await client.list_connections()
            print_status(True, f"Found {len(connections)} connection(s)")

            if connections:
                active_count = sum(1 for c in connections if c.status.value == "active")
                print_status(True, f"Active connections: {active_count}")

                print("\n    Connection details:")
                for conn in connections[:5]:  # Show first 5
                    status_icon = "\u2705" if conn.status.value == "active" else "\u26a0\ufe0f"
                    print(f"    {status_icon} {conn.name}")
                    print(f"       ID: {conn.connection_id}")
                    print(f"       Status: {conn.status.value}")
                    if conn.schedule:
                        print(f"       Schedule: {conn.schedule.schedule_type.value}")

                if len(connections) > 5:
                    print(f"\n    ... and {len(connections) - 5} more connections")

                # Check for at least one active connection
                if active_count == 0:
                    print("\n\u26a0\ufe0f  Warning: No active connections found.")
                    print("    Data syncs won't run until connections are activated.")
            else:
                print("\u26a0\ufe0f  No connections configured yet.")
                print("    Create connections in Airbyte Cloud to start syncing data.")

        except AirbyteAuthenticationError as e:
            print_status(False, f"Authentication failed: {e.message}")
            validation_passed = False
        except AirbyteError as e:
            print_status(False, f"Failed to list connections: {e.message}")
            validation_passed = False
        except Exception as e:
            print_status(False, f"Unexpected error listing connections: {e}")
            validation_passed = False

    # Summary
    print_header("Validation Summary")

    if validation_passed:
        print("\u2705 All validation checks passed!")
        print("\nAirbyte deployment is ready for use.")
        print("\nNext steps:")
        print("  1. Ensure at least one active connection exists")
        print("  2. Test a manual sync via Airbyte Cloud UI")
        print("  3. Verify data appears in destination")
        return True
    else:
        print("\u274c Some validation checks failed.")
        print("\nTroubleshooting:")
        print("  1. Verify API token is valid (regenerate if needed)")
        print("  2. Check workspace ID is correct")
        print("  3. Ensure network access to cloud.airbyte.com")
        print("  4. Review Airbyte Cloud status at status.airbyte.com")
        return False


def main() -> int:
    """Main entry point."""
    try:
        result = asyncio.run(validate_airbyte_setup())
        return 0 if result else 1
    except KeyboardInterrupt:
        print("\n\nValidation cancelled by user.")
        return 1
    except Exception as e:
        print(f"\n\u274c Validation failed with unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
