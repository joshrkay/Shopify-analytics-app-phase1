"""
Report Templates Seed Script.

Seeds system-defined report templates for the template gallery.
Templates use abstract chart types (line, bar, etc.) that get mapped
to Superset viz_type plugins at instantiation time.

Usage:
    python -m scripts.seed_report_templates
    python -m scripts.seed_report_templates --dry-run
    python -m scripts.seed_report_templates --delete

Environment variables:
    DATABASE_URL: PostgreSQL connection string (required)

Phase 2C - Template System Backend
"""

import os
import sys
import logging
from pathlib import Path
import uuid

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from src.models.report_template import ReportTemplate, TemplateCategory
from src.db_base import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required.")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


REPORT_TEMPLATES = [
    {
        "name": "Revenue Overview",
        "description": "Track gross revenue, net revenue, and order trends over time. Includes daily revenue line chart, revenue by product category, and top products table.",
        "category": "sales",
        "min_billing_tier": "free",
        "config_json": {
            "reports": [
                {
                    "title": "Daily Revenue Trend",
                    "chart_type": "line",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Gross Revenue", "column": "total_revenue_gross", "aggregate": "SUM", "expressionType": "SIMPLE"},
                        {"label": "Net Revenue", "column": "total_revenue_net", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "time_column": "order_date",
                    "time_grain": "P1D",
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Revenue by Category",
                    "chart_type": "bar",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Revenue", "column": "total_revenue_gross", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["product_type"],
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Top Products",
                    "chart_type": "table",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Revenue", "column": "total_revenue_gross", "aggregate": "SUM", "expressionType": "SIMPLE"},
                        {"label": "Orders", "column": "order_count", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["product_title"],
                    "time_range": "Last 30 days",
                },
            ],
        },
    },
    {
        "name": "Marketing Performance",
        "description": "Monitor ad spend, ROAS, CPC, and CTR across marketing channels. Helps identify which campaigns are driving the best return.",
        "category": "marketing",
        "min_billing_tier": "starter",
        "config_json": {
            "reports": [
                {
                    "title": "Ad Spend Over Time",
                    "chart_type": "line",
                    "dataset_name": "sem_ad_performance_v1",
                    "metrics": [
                        {"label": "Spend", "column": "spend", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "time_column": "date",
                    "time_grain": "P1D",
                    "time_range": "Last 30 days",
                },
                {
                    "title": "ROAS by Channel",
                    "chart_type": "bar",
                    "dataset_name": "sem_ad_performance_v1",
                    "metrics": [
                        {"label": "ROAS", "column": "roas", "aggregate": "AVG", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["platform"],
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Campaign Performance Table",
                    "chart_type": "table",
                    "dataset_name": "sem_ad_performance_v1",
                    "metrics": [
                        {"label": "Spend", "column": "spend", "aggregate": "SUM", "expressionType": "SIMPLE"},
                        {"label": "Revenue", "column": "revenue", "aggregate": "SUM", "expressionType": "SIMPLE"},
                        {"label": "ROAS", "column": "roas", "aggregate": "AVG", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["campaign_name"],
                    "time_range": "Last 30 days",
                },
            ],
        },
    },
    {
        "name": "Customer Analytics",
        "description": "Understand customer acquisition, retention, and lifetime value. Track new vs returning customers and cohort behavior.",
        "category": "customer",
        "min_billing_tier": "growth",
        "config_json": {
            "reports": [
                {
                    "title": "New vs Returning Customers",
                    "chart_type": "line",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "New Customers", "column": "new_customer_count", "aggregate": "SUM", "expressionType": "SIMPLE"},
                        {"label": "Returning Customers", "column": "returning_customer_count", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "time_column": "order_date",
                    "time_grain": "P1D",
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Average Order Value",
                    "chart_type": "kpi",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "AOV", "column": "average_order_value", "aggregate": "AVG", "expressionType": "SIMPLE"},
                    ],
                    "time_range": "Last 30 days",
                },
            ],
        },
    },
    {
        "name": "Product Performance",
        "description": "Analyze product sales velocity, inventory turns, and margin by product. Identify bestsellers and underperformers.",
        "category": "product",
        "min_billing_tier": "starter",
        "config_json": {
            "reports": [
                {
                    "title": "Sales by Product",
                    "chart_type": "bar",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Units Sold", "column": "quantity_sold", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["product_title"],
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Product Revenue Trend",
                    "chart_type": "line",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Revenue", "column": "total_revenue_gross", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "dimensions": ["product_type"],
                    "time_column": "order_date",
                    "time_grain": "P1W",
                    "time_range": "Last 90 days",
                },
            ],
        },
    },
    {
        "name": "Operations Dashboard",
        "description": "Monitor fulfillment rates, shipping times, and refund metrics. Keep operations running smoothly.",
        "category": "operations",
        "min_billing_tier": "growth",
        "config_json": {
            "reports": [
                {
                    "title": "Order Fulfillment Rate",
                    "chart_type": "line",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Fulfillment Rate", "column": "fulfillment_rate", "aggregate": "AVG", "expressionType": "SIMPLE"},
                    ],
                    "time_column": "order_date",
                    "time_grain": "P1D",
                    "time_range": "Last 30 days",
                },
                {
                    "title": "Refund Summary",
                    "chart_type": "kpi",
                    "dataset_name": "fact_orders_current",
                    "metrics": [
                        {"label": "Refund Amount", "column": "total_refunds", "aggregate": "SUM", "expressionType": "SIMPLE"},
                    ],
                    "time_range": "Last 30 days",
                },
            ],
        },
    },
]


def seed_report_templates(database_url: str, dry_run: bool = False) -> None:
    """Seed report templates into the database."""
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine, tables=[ReportTemplate.__table__], checkfirst=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        logger.info("=" * 60)
        logger.info("REPORT TEMPLATES SEED SCRIPT")
        logger.info("=" * 60)
        logger.info("Mode: %s", "DRY RUN" if dry_run else "EXECUTION")
        logger.info("Total templates to seed: %d", len(REPORT_TEMPLATES))
        logger.info("")

        existing = session.query(ReportTemplate).all()
        existing_names = {t.name for t in existing}

        to_create = [t for t in REPORT_TEMPLATES if t["name"] not in existing_names]
        already_exist = [t["name"] for t in REPORT_TEMPLATES if t["name"] in existing_names]

        if already_exist:
            logger.info("Templates already exist (%d):", len(already_exist))
            for name in already_exist:
                logger.info("   - %s", name)
            logger.info("")

        logger.info("Templates to create (%d):", len(to_create))
        for t in to_create:
            report_count = len(t["config_json"].get("reports", []))
            logger.info(
                "   - %s [%s] (%d reports, tier: %s)",
                t["name"], t["category"], report_count, t["min_billing_tier"],
            )

        if dry_run:
            logger.info("")
            logger.info("DRY RUN - No changes will be made")
            return

        created_count = 0
        for t in to_create:
            try:
                template = ReportTemplate(
                    id=str(uuid.uuid4()),
                    name=t["name"],
                    description=t["description"],
                    category=TemplateCategory(t["category"]),
                    min_billing_tier=t["min_billing_tier"],
                    config_json=t["config_json"],
                    is_active=True,
                    version=1,
                )
                session.add(template)
                session.commit()
                created_count += 1
                logger.info("Created: %s (ID: %s)", t["name"], template.id)
            except SQLAlchemyError as e:
                session.rollback()
                logger.error("Failed to create %s: %s", t["name"], e)

        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY: Created %d, Already existed %d", created_count, len(already_exist))
        logger.info("=" * 60)

    finally:
        session.close()


def delete_report_templates(database_url: str, dry_run: bool = False) -> None:
    """Delete all seeded report templates."""
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    template_names = [t["name"] for t in REPORT_TEMPLATES]

    try:
        to_delete = session.query(ReportTemplate).filter(
            ReportTemplate.name.in_(template_names)
        ).all()

        if not to_delete:
            logger.info("No templates to delete.")
            return

        logger.info("Templates to delete (%d):", len(to_delete))
        for t in to_delete:
            logger.info("   - %s (ID: %s)", t.name, t.id)

        if dry_run:
            logger.info("DRY RUN - No changes will be made")
            return

        for t in to_delete:
            session.delete(t)
        session.commit()
        logger.info("Deleted %d templates.", len(to_delete))

    except SQLAlchemyError as e:
        logger.error("Database error: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed report templates into the database",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--delete", action="store_true", help="Delete seeded templates")
    parser.add_argument("--database-url", type=str, help="Database URL override")

    args = parser.parse_args()

    try:
        database_url = args.database_url or get_database_url()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    try:
        if args.delete:
            delete_report_templates(database_url, args.dry_run)
        else:
            seed_report_templates(database_url, args.dry_run)
    except Exception as e:
        logger.error("Script failed: %s", e)
        sys.exit(1)

    logger.info("Done!")


if __name__ == "__main__":
    main()
