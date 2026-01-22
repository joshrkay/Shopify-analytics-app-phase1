"""
Billing Plans Seed Script
Creates 7 pricing tiers: Free + 3 tiers (Starter, Professional, Enterprise)
with Monthly and Annual billing options for paid tiers.

Usage:
    python -m scripts.seed_billing_plans
    python -m scripts.seed_billing_plans --dry-run (to preview without saving)

Environment variables:
    DATABASE_URL: PostgreSQL connection string (required)
"""

import os
import sys
import logging
from pathlib import Path
import uuid

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from src.models.plan import Plan, PlanFeature
from src.db_base import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://user:password@localhost:5432/dbname"
        )

    # Handle Render's postgres:// URL format
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def generate_plan_id(name: str) -> str:
    """Generate a unique plan ID."""
    return f"plan_{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"


def generate_feature_id() -> str:
    """Generate a unique feature ID."""
    return f"feat_{uuid.uuid4().hex[:12]}"


BILLING_PLANS = [
    {
        "name": "free",
        "display_name": "Free",
        "description": "Perfect for getting started with analytics",
        "price_monthly_cents": None,  # Free tier
        "price_yearly_cents": None,
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": 10},
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": 3},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": 50},
            {"feature_key": "api_access", "is_enabled": False},
            {"feature_key": "team_members", "is_enabled": False, "limit_value": 1},
            {"feature_key": "priority_support", "is_enabled": False},
        ]
    },
    {
        "name": "starter_monthly",
        "display_name": "Starter - Monthly",
        "description": "Growing businesses - Monthly billing",
        "price_monthly_cents": 999,  # $9.99/month
        "price_yearly_cents": None,
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": 25},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": 500},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": 1000},
            {"feature_key": "team_members", "is_enabled": True, "limit_value": 3},
            {"feature_key": "priority_support", "is_enabled": False},
        ]
    },
    {
        "name": "starter_annual",
        "display_name": "Starter - Annual",
        "description": "Growing businesses - Annual billing (save 17%)",
        "price_monthly_cents": None,
        "price_yearly_cents": 9990,  # $99.90/year ($8.32/month equivalent)
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": 25},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": 500},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": 1000},
            {"feature_key": "team_members", "is_enabled": True, "limit_value": 3},
            {"feature_key": "priority_support", "is_enabled": False},
        ]
    },
    {
        "name": "professional_monthly",
        "display_name": "Professional - Monthly",
        "description": "Professional teams - Monthly billing",
        "price_monthly_cents": 2999,  # $29.99/month
        "price_yearly_cents": None,
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": None},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": None},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": 5000},
            {"feature_key": "team_members", "is_enabled": True, "limit_value": 10},
            {"feature_key": "priority_support", "is_enabled": True},
        ]
    },
    {
        "name": "professional_annual",
        "display_name": "Professional - Annual",
        "description": "Professional teams - Annual billing (save 17%)",
        "price_monthly_cents": None,
        "price_yearly_cents": 29990,  # $299.90/year ($24.99/month equivalent)
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": None},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": None},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": 5000},
            {"feature_key": "team_members", "is_enabled": True, "limit_value": 10},
            {"feature_key": "priority_support", "is_enabled": True},
        ]
    },
    {
        "name": "enterprise_monthly",
        "display_name": "Enterprise - Monthly",
        "description": "Large organizations - Monthly billing",
        "price_monthly_cents": 9999,  # $99.99/month
        "price_yearly_cents": None,
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": None},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": None},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "team_members", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "priority_support", "is_enabled": True},
            {"feature_key": "custom_branding", "is_enabled": True},
            {"feature_key": "sso", "is_enabled": True},
        ]
    },
    {
        "name": "enterprise_annual",
        "display_name": "Enterprise - Annual",
        "description": "Large organizations - Annual billing (save 17%)",
        "price_monthly_cents": None,
        "price_yearly_cents": 99990,  # $999.90/year ($83.32/month equivalent)
        "is_active": True,
        "features": [
            {"feature_key": "basic_analytics", "is_enabled": True, "limit_value": None},
            {"feature_key": "custom_reports", "is_enabled": True, "limit_value": None},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": None},
            {"feature_key": "api_access", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "team_members", "is_enabled": True, "limit_value": None},  # Unlimited
            {"feature_key": "priority_support", "is_enabled": True},
            {"feature_key": "custom_branding", "is_enabled": True},
            {"feature_key": "sso", "is_enabled": True},
        ]
    },
]


def format_price(cents: int | None) -> str:
    """Format price in cents to display string."""
    if cents is None:
        return "N/A"
    return f"${cents / 100:.2f}"


def seed_billing_plans(database_url: str, dry_run: bool = False) -> None:
    """
    Seed billing plans into the database.

    Args:
        database_url: PostgreSQL connection string
        dry_run: If True, preview changes without saving
    """
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        logger.info("=" * 60)
        logger.info("BILLING PLANS SEED SCRIPT")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'EXECUTION'}")
        logger.info(f"Total plans to create: {len(BILLING_PLANS)}")
        logger.info("")

        # Check existing plans
        existing_plans = session.query(Plan).all()
        existing_names = {p.name for p in existing_plans}

        plans_to_create = []
        plans_already_exist = []

        for plan_data in BILLING_PLANS:
            if plan_data["name"] in existing_names:
                plans_already_exist.append(plan_data["name"])
            else:
                plans_to_create.append(plan_data)

        # Display summary
        if plans_already_exist:
            logger.info(f"Plans already exist ({len(plans_already_exist)}):")
            for name in plans_already_exist:
                logger.info(f"   - {name}")
            logger.info("")

        logger.info(f"Plans to create ({len(plans_to_create)}):")
        for plan_data in plans_to_create:
            if plan_data["price_monthly_cents"]:
                price_str = f"{format_price(plan_data['price_monthly_cents'])}/month"
            elif plan_data["price_yearly_cents"]:
                price_str = f"{format_price(plan_data['price_yearly_cents'])}/year"
            else:
                price_str = "FREE"

            feature_count = len(plan_data["features"])
            logger.info(f"   - {plan_data['display_name']}: {price_str} ({feature_count} features)")

        logger.info("")

        if dry_run:
            logger.info("DRY RUN - No changes will be made")
            logger.info("")

            # Show detailed plan info
            for plan_data in plans_to_create:
                logger.info(f"Plan: {plan_data['display_name']}")
                logger.info(f"  Name: {plan_data['name']}")
                logger.info(f"  Description: {plan_data['description']}")
                logger.info(f"  Monthly: {format_price(plan_data['price_monthly_cents'])}")
                logger.info(f"  Yearly: {format_price(plan_data['price_yearly_cents'])}")
                logger.info("  Features:")
                for feature in plan_data["features"]:
                    enabled = "enabled" if feature["is_enabled"] else "disabled"
                    limit = feature.get("limit_value")
                    limit_str = f" (limit: {limit})" if limit is not None else " (unlimited)" if feature["is_enabled"] else ""
                    logger.info(f"    - {feature['feature_key']}: {enabled}{limit_str}")
                logger.info("")

            return

        # Create plans
        created_count = 0
        for plan_data in plans_to_create:
            try:
                # Generate unique plan ID
                plan_id = generate_plan_id(plan_data["name"])

                # Create plan
                plan = Plan(
                    id=plan_id,
                    name=plan_data["name"],
                    display_name=plan_data["display_name"],
                    description=plan_data["description"],
                    price_monthly_cents=plan_data["price_monthly_cents"],
                    price_yearly_cents=plan_data["price_yearly_cents"],
                    is_active=plan_data["is_active"],
                )
                session.add(plan)
                session.flush()  # Get the plan ID

                # Create features
                for feature_data in plan_data["features"]:
                    feature = PlanFeature(
                        id=generate_feature_id(),
                        plan_id=plan.id,
                        feature_key=feature_data["feature_key"],
                        is_enabled=feature_data["is_enabled"],
                        limit_value=feature_data.get("limit_value"),
                    )
                    session.add(feature)

                session.commit()
                created_count += 1
                logger.info(f"Created: {plan_data['display_name']} (ID: {plan_id})")

            except SQLAlchemyError as e:
                session.rollback()
                logger.error(f"Failed to create {plan_data['name']}: {e}")

        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Plans created: {created_count}")
        logger.info(f"Plans already existed: {len(plans_already_exist)}")
        logger.info(f"Total plans in database: {len(existing_names) + created_count}")

    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def delete_billing_plans(database_url: str, dry_run: bool = False) -> None:
    """
    Delete all billing plans created by this script.

    Args:
        database_url: PostgreSQL connection string
        dry_run: If True, preview changes without saving
    """
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    plan_names = [p["name"] for p in BILLING_PLANS]

    try:
        logger.info("=" * 60)
        logger.info("DELETE BILLING PLANS")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'EXECUTION'}")
        logger.info("")

        plans_to_delete = session.query(Plan).filter(Plan.name.in_(plan_names)).all()

        if not plans_to_delete:
            logger.info("No plans to delete.")
            return

        logger.info(f"Plans to delete ({len(plans_to_delete)}):")
        for plan in plans_to_delete:
            logger.info(f"   - {plan.display_name} (ID: {plan.id})")

        if dry_run:
            logger.info("")
            logger.info("DRY RUN - No changes will be made")
            return

        for plan in plans_to_delete:
            session.delete(plan)

        session.commit()
        logger.info("")
        logger.info(f"Deleted {len(plans_to_delete)} plans and their associated features.")

    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed billing plans into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.seed_billing_plans              # Create plans
  python -m scripts.seed_billing_plans --dry-run    # Preview without saving
  python -m scripts.seed_billing_plans --delete     # Delete seeded plans
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without saving to database"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete all plans created by this script"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database URL (overrides DATABASE_URL env var)"
    )

    args = parser.parse_args()

    try:
        database_url = args.database_url or get_database_url()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    try:
        if args.delete:
            delete_billing_plans(database_url, args.dry_run)
        else:
            seed_billing_plans(database_url, args.dry_run)
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)

    logger.info("Done!")


if __name__ == "__main__":
    main()
