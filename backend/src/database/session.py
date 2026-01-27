"""
Database session management with connection pooling.

Provides a shared FastAPI dependency for database sessions across all routes.
Uses SQLAlchemy with connection pooling for production workloads.

Usage:
    from src.database.session import get_db_session

    @router.get("/items")
    async def get_items(db: Session = Depends(get_db_session)):
        return db.query(Item).all()
"""

import os
import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Module-level engine singleton
_engine = None
_SessionLocal = None


def _get_database_url() -> str:
    """
    Get and normalize the database URL from environment.

    Handles Render's postgres:// URL format by converting to postgresql://.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")

    # Handle Render's postgres:// URL format (SQLAlchemy requires postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def get_engine():
    """
    Get or create the database engine singleton.

    Uses connection pooling with sensible defaults for production:
    - pool_size: 5 connections
    - max_overflow: 10 additional connections under load
    - pool_pre_ping: Verify connections before use
    """
    global _engine
    if _engine is None:
        try:
            database_url = _get_database_url()
            _engine = create_engine(
                database_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,  # Verify connection health
                pool_recycle=1800,   # Recycle connections after 30 minutes
            )
            logger.info("Database engine created with connection pooling")
        except ValueError as e:
            logger.error("Failed to create database engine", extra={"error": str(e)})
            raise
    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the session factory singleton."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
    return _SessionLocal


async def get_db_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.

    Creates a new session for each request and ensures proper cleanup.
    Raises HTTP 503 if database is not configured.

    Usage:
        @router.get("/items")
        async def get_items(db: Session = Depends(get_db_session)):
            return db.query(Item).all()
    """
    try:
        SessionLocal = get_session_factory()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured"
        )

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db_session_sync() -> Generator[Session, None, None]:
    """
    Synchronous version of get_db_session for non-async contexts.

    Usage:
        for session in get_db_session_sync():
            # use session
    """
    try:
        SessionLocal = get_session_factory()
    except ValueError as e:
        raise RuntimeError(f"Database not configured: {e}")

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
