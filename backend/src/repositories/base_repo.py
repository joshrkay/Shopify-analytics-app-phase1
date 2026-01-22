"""
Base repository with strict tenant isolation enforcement.

CRITICAL: All database operations MUST include tenant_id.
No query can access data across tenants.
"""

import logging
from typing import TypeVar, Generic, Optional, List, Any
from abc import ABC, abstractmethod

from sqlalchemy import create_engine, Column, String, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from src.db_base import Base

logger = logging.getLogger(__name__)

# Type variable for repository models
T = TypeVar("T", bound=Base)


class TenantIsolationError(Exception):
    """Raised when tenant isolation is violated."""
    pass


class BaseRepository(Generic[T], ABC):
    """
    Base repository with mandatory tenant_id enforcement.
    
    All methods require tenant_id parameter.
    All queries are automatically scoped by tenant_id.
    """
    
    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize repository with tenant context.
        
        Args:
            db_session: SQLAlchemy database session
            tenant_id: Tenant identifier (from JWT, never from request)
        
        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required and cannot be empty")
        
        self.db_session = db_session
        self.tenant_id = tenant_id
        self._model_class = self._get_model_class()
    
    @abstractmethod
    def _get_model_class(self) -> type[T]:
        """Return the SQLAlchemy model class for this repository."""
        pass
    
    @abstractmethod
    def _get_tenant_column_name(self) -> str:
        """Return the name of the tenant_id column in the model."""
        pass
    
    def _enforce_tenant_scope(self, query):
        """
        Automatically scope query by tenant_id.
        
        This ensures NO query can access cross-tenant data.
        """
        tenant_column = getattr(self._model_class, self._get_tenant_column_name())
        return query.filter(tenant_column == self.tenant_id)
    
    def _validate_tenant_id(self, tenant_id: Optional[str], operation: str):
        """
        Validate that provided tenant_id matches repository tenant_id.
        
        SECURITY: Prevents cross-tenant operations even if tenant_id is passed.
        """
        if tenant_id and tenant_id != self.tenant_id:
            logger.error(
                "Tenant ID mismatch detected",
                extra={
                    "repository_tenant_id": self.tenant_id,
                    "provided_tenant_id": tenant_id,
                    "operation": operation
                }
            )
            raise TenantIsolationError(
                f"Tenant ID mismatch: repository scoped to {self.tenant_id}, "
                f"but operation attempted with {tenant_id}"
            )
    
    def get_by_id(self, entity_id: str, tenant_id: Optional[str] = None) -> Optional[T]:
        """
        Get entity by ID, scoped to tenant.
        
        Args:
            entity_id: Entity identifier
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            Entity if found, None otherwise
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "get_by_id")
        
        query = self.db_session.query(self._model_class)
        query = self._enforce_tenant_scope(query)
        return query.filter(self._model_class.id == entity_id).first()
    
    def get_all(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        tenant_id: Optional[str] = None
    ) -> List[T]:
        """
        Get all entities for tenant.
        
        Args:
            limit: Maximum number of results
            offset: Offset for pagination
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            List of entities
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "get_all")
        
        query = self.db_session.query(self._model_class)
        query = self._enforce_tenant_scope(query)
        
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def create(self, entity_data: dict, tenant_id: Optional[str] = None) -> T:
        """
        Create new entity with tenant_id enforced.
        
        SECURITY: tenant_id from entity_data is IGNORED.
        Repository tenant_id is ALWAYS used.
        
        Args:
            entity_data: Entity data dictionary
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            Created entity
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
            ValueError: If entity_data contains tenant_id (should come from JWT only)
        """
        self._validate_tenant_id(tenant_id, "create")
        
        # CRITICAL: Remove tenant_id from entity_data if present
        # tenant_id MUST come from JWT context, never from request body
        if "tenant_id" in entity_data:
            logger.warning(
                "tenant_id found in entity_data, removing it",
                extra={
                    "repository_tenant_id": self.tenant_id,
                    "removed_tenant_id": entity_data.pop("tenant_id")
                }
            )
        
        # Always set tenant_id from repository context
        entity_data[self._get_tenant_column_name()] = self.tenant_id
        
        entity = self._model_class(**entity_data)
        self.db_session.add(entity)
        
        try:
            self.db_session.commit()
            self.db_session.refresh(entity)
            
            logger.info(
                "Entity created",
                extra={
                    "tenant_id": self.tenant_id,
                    "entity_id": getattr(entity, "id", None),
                    "entity_type": self._model_class.__name__
                }
            )
            
            return entity
        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to create entity",
                extra={
                    "tenant_id": self.tenant_id,
                    "error": str(e)
                }
            )
            raise
    
    def update(
        self,
        entity_id: str,
        entity_data: dict,
        tenant_id: Optional[str] = None
    ) -> Optional[T]:
        """
        Update entity, scoped to tenant.
        
        SECURITY: tenant_id from entity_data is IGNORED.
        Only entities belonging to repository tenant_id can be updated.
        
        Args:
            entity_id: Entity identifier
            entity_data: Update data dictionary
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            Updated entity if found, None otherwise
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "update")
        
        # Remove tenant_id from update data if present
        if "tenant_id" in entity_data or self._get_tenant_column_name() in entity_data:
            logger.warning(
                "tenant_id found in update data, removing it",
                extra={
                    "repository_tenant_id": self.tenant_id,
                    "entity_id": entity_id
                }
            )
            entity_data.pop("tenant_id", None)
            entity_data.pop(self._get_tenant_column_name(), None)
        
        entity = self.get_by_id(entity_id)
        if not entity:
            return None
        
        # Update entity
        for key, value in entity_data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        try:
            self.db_session.commit()
            self.db_session.refresh(entity)
            
            logger.info(
                "Entity updated",
                extra={
                    "tenant_id": self.tenant_id,
                    "entity_id": entity_id,
                    "entity_type": self._model_class.__name__
                }
            )
            
            return entity
        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to update entity",
                extra={
                    "tenant_id": self.tenant_id,
                    "entity_id": entity_id,
                    "error": str(e)
                }
            )
            raise
    
    def delete(self, entity_id: str, tenant_id: Optional[str] = None) -> bool:
        """
        Delete entity, scoped to tenant.
        
        Args:
            entity_id: Entity identifier
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            True if deleted, False if not found
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "delete")
        
        entity = self.get_by_id(entity_id)
        if not entity:
            return False
        
        try:
            self.db_session.delete(entity)
            self.db_session.commit()
            
            logger.info(
                "Entity deleted",
                extra={
                    "tenant_id": self.tenant_id,
                    "entity_id": entity_id,
                    "entity_type": self._model_class.__name__
                }
            )
            
            return True
        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to delete entity",
                extra={
                    "tenant_id": self.tenant_id,
                    "entity_id": entity_id,
                    "error": str(e)
                }
            )
            raise
    
    def count(self, tenant_id: Optional[str] = None) -> int:
        """
        Count entities for tenant.
        
        Args:
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            Count of entities
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "count")
        
        query = self.db_session.query(self._model_class)
        query = self._enforce_tenant_scope(query)
        return query.count()
    
    def exists(self, entity_id: str, tenant_id: Optional[str] = None) -> bool:
        """
        Check if entity exists for tenant.
        
        Args:
            entity_id: Entity identifier
            tenant_id: Optional tenant_id (must match repository tenant_id if provided)
        
        Returns:
            True if exists, False otherwise
        
        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        return self.get_by_id(entity_id, tenant_id) is not None