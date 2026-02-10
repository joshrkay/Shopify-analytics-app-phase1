"""
Database initialization script.

Creates all tables defined in the SQLAlchemy models.
Run this script to initialize a fresh database or add new tables.

Usage:
    python -m scripts.init_db

Environment variables:
    DATABASE_URL: PostgreSQL connection string
"""

import os
import sys
import logging
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from src.db_base import Base

# Import all models to register them with Base.metadata
# Identity models (Epic 1.1)
from src.models.organization import Organization
from src.models.tenant import Tenant
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole
# Existing models
from src.models.plan import Plan, PlanFeature
from src.models.store import ShopifyStore
from src.models.subscription import Subscription
from src.models.billing_event import BillingEvent
from src.models.usage import UsageRecord, UsageAggregate
# Custom Reports & Dashboard Builder models
from src.models.report_template import ReportTemplate
from src.models.custom_dashboard import CustomDashboard
from src.models.custom_report import CustomReport
from src.models.dashboard_version import DashboardVersion
from src.models.dashboard_share import DashboardShare
from src.models.dashboard_audit import DashboardAudit

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


def init_database(database_url: str) -> None:
    """
    Initialize database tables.

    Creates all tables defined in SQLAlchemy models if they don't exist.
    Existing tables are not modified (use migrations for schema changes).

    Args:
        database_url: PostgreSQL connection string
    """
    logger.info("Connecting to database...")

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true"
    )

    try:
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        logger.info("Database connection successful")
    except SQLAlchemyError as e:
        logger.error(f"Failed to connect to database: {e}")
        raise

    # Get list of tables that will be created
    table_names = sorted(Base.metadata.tables.keys())
    logger.info(f"Tables to create/verify: {', '.join(table_names)}")

    # Create tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("All tables created/verified successfully")
    except SQLAlchemyError as e:
        logger.error(f"Failed to create tables: {e}")
        raise

    # Log table status
    with engine.connect() as conn:
        for table_name in table_names:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :name"),
                {"name": table_name}
            )
            exists = result.fetchone()[0] > 0
            status = "EXISTS" if exists else "MISSING"
            logger.info(f"  {table_name}: {status}")


def seed_default_plans(database_url: str) -> None:
    """
    Seed default pricing plans if they don't exist.

    Creates Free, Growth, Pro, and Enterprise plans with default features.
    """
    from sqlalchemy.orm import sessionmaker
    from src.repositories.plans_repo import PlansRepository, PlanAlreadyExistsError

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    default_plans = [
        {
            "name": "free",
            "display_name": "Free",
            "description": "Perfect for getting started with basic analytics",
            "price_monthly_cents": None,
            "price_yearly_cents": None,
            "is_active": True,
            "features": [
                {"feature_key": "custom_reports", "is_enabled": False},
                {"feature_key": "export_data", "is_enabled": True, "limit_value": 100},
            ]
        },
        {
            "name": "growth",
            "display_name": "Growth",
            "description": "For growing businesses that need more insights",
            "price_monthly_cents": 2900,
            "price_yearly_cents": 29000,
            "is_active": True,
            "features": [
                {"feature_key": "ai_insights", "is_enabled": True, "limit_value": 50},
                {"feature_key": "custom_reports", "is_enabled": True, "limit_value": 10},
                {"feature_key": "export_data", "is_enabled": True},
                {"feature_key": "api_access", "is_enabled": True},
                {"feature_key": "team_members", "is_enabled": True, "limit_value": 5},
            ]
        },
        {
            "name": "pro",
            "display_name": "Professional",
            "description": "Advanced features for professional teams",
            "price_monthly_cents": 7900,
            "price_yearly_cents": 79000,
            "is_active": True,
            "features": [
                {"feature_key": "ai_insights", "is_enabled": True},
                {"feature_key": "custom_reports", "is_enabled": True, "limit_value": 50},
                {"feature_key": "export_data", "is_enabled": True},
                {"feature_key": "api_access", "is_enabled": True},
                {"feature_key": "team_members", "is_enabled": True, "limit_value": 25},
                {"feature_key": "priority_support", "is_enabled": True},
                {"feature_key": "advanced_analytics", "is_enabled": True},
            ]
        },
        {
            "name": "enterprise",
            "display_name": "Enterprise",
            "description": "Custom solutions for large organizations",
            "price_monthly_cents": None,
            "price_yearly_cents": None,
            "is_active": True,
            "features": [
                {"feature_key": "ai_insights", "is_enabled": True},
                {"feature_key": "custom_reports", "is_enabled": True},
                {"feature_key": "export_data", "is_enabled": True},
                {"feature_key": "api_access", "is_enabled": True},
                {"feature_key": "team_members", "is_enabled": True},
                {"feature_key": "priority_support", "is_enabled": True},
                {"feature_key": "custom_branding", "is_enabled": True},
                {"feature_key": "advanced_analytics", "is_enabled": True},
            ]
        },
    ]

    session = SessionLocal()
    try:
        repo = PlansRepository(session)

        for plan_data in default_plans:
            features = plan_data.pop("features")

            try:
                plan = repo.create(**plan_data)

                # Add features
                for feature_data in features:
                    repo.add_feature(plan.id, **feature_data)

                session.commit()
                logger.info(f"Created plan: {plan_data['name']}")
            except PlanAlreadyExistsError:
                logger.info(f"Plan already exists: {plan_data['name']}")
                session.rollback()
    finally:
        session.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Initialize database tables")
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed default pricing plans"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database URL (overrides DATABASE_URL env var)"
    )

    args = parser.parse_args()

    database_url = args.database_url or get_database_url()

    logger.info("Starting database initialization...")
    init_database(database_url)

    if args.seed:
        logger.info("Seeding default plans...")
        seed_default_plans(database_url)

    logger.info("Database initialization complete!")


if __name__ == "__main__":
    main()
