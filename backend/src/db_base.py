"""
SQLAlchemy declarative base for all models.

This module contains only the Base declarative base and must not import
from models or repositories to avoid circular dependencies.
"""

from sqlalchemy.ext.declarative import declarative_base

# Single source of truth for all SQLAlchemy models
Base = declarative_base()
