"""
Action execution service for Story 8.5.

Core service for executing approved actions on external platforms.

EXECUTION FLOW:
1. Validate action is approved and ready
2. Get platform executor with credentials
3. Generate idempotency key
4. Capture before_state from platform
5. Execute via platform executor
6. Capture after_state from platform
7. Generate rollback instructions
8. Update action status based on outcome
9. Log all events for audit

PRINCIPLES:
- External platform is source of truth
- No blind retries on failure
- Full before/after state capture
- Rollback support for all executed actions

SECURITY:
- tenant_id from JWT only
- Credentials decrypted only when needed
- All API calls logged for audit

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.models.ai_action import AIAction, ActionStatus
from src.models.action_execution_log import ActionExecutionLog
from src.services.platform_credentials_service import (
    PlatformCredentialsService,
    Platform,
)
from src.services.platform_executors import (
    BasePlatformExecutor,
    ExecutionResult,
    StateCapture,
    RetryConfig,
)


logger = logging.getLogger(__name__)


@dataclass
class ActionExecutionResult:
    """Result of executing an action."""
    success: bool
    action_id: str
    status: ActionStatus
    message: str
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    rollback_instructions: Optional[dict] = None
    error_code: Optional[str] = None
    error_details: Optional[dict] = None


class ActionExecutionError(Exception):
    """Error during action execution."""

    def __init__(self, message: str, code: str, action_id: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.action_id = action_id


class ActionExecutionService:
    """
    Core service for executing approved actions.

    SECURITY:
    - Tenant isolation via tenant_id from JWT only
    - Entitlement checking before execution
    - All external calls logged for audit

    PRINCIPLES:
    - External platform is source of truth
    - No blind retries on failure
    - Full before/after state capture
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        credentials_service: Optional[PlatformCredentialsService] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        """
        Initialize execution service.

        Args:
            db_session: Database session
            tenant_id: Tenant identifier (from JWT only)
            credentials_service: Optional credentials service (created if not provided)
            retry_config: Optional retry configuration for executors
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.retry_config = retry_config or RetryConfig()

        # Credentials service (lazy or provided)
        self._credentials_service = credentials_service

    @property
    def credentials_service(self) -> PlatformCredentialsService:
        """Get or create credentials service."""
        if self._credentials_service is None:
            self._credentials_service = PlatformCredentialsService(self.db)
        return self._credentials_service

    # =========================================================================
    # Main Execution Method
    # =========================================================================

    async def execute_action(self, action_id: str) -> ActionExecutionResult:
        """
        Execute a single approved action.

        This is the main entry point for action execution.

        Flow:
        1. Validate action is approved and ready
        2. Generate idempotency key
        3. Get platform executor
        4. Capture before_state from platform
        5. Execute via platform executor
        6. Capture after_state from platform
        7. Generate rollback_instructions
        8. Update action status
        9. Log all events

        Args:
            action_id: ID of the action to execute

        Returns:
            ActionExecutionResult with outcome details
        """
        # 1. Get and validate action
        action = self._get_action(action_id)
        self._validate_action_ready(action)

        # 2. Mark as executing
        idempotency_key = self._generate_idempotency_key(action)
        action.mark_executing(idempotency_key)
        self.db.flush()

        # Log execution start
        self._log_event(action, ActionExecutionLog.log_execution_started(
            tenant_id=self.tenant_id,
            action_id=action.id,
            job_id=action.job_id,
        ))

        try:
            # 3. Get platform executor
            executor = await self._get_executor(action)

            # 4. Capture before state
            before_state = await self._capture_before_state(action, executor)
            self._log_event(action, ActionExecutionLog.log_state_captured(
                tenant_id=self.tenant_id,
                action_id=action.id,
                state_snapshot=before_state.to_dict(),
                is_before=True,
            ))

            # 5. Execute the action
            result = await self._execute_on_platform(action, executor, idempotency_key)

            if result.success:
                # 6. Capture after state
                after_state = await self._capture_after_state(action, executor)
                self._log_event(action, ActionExecutionLog.log_state_captured(
                    tenant_id=self.tenant_id,
                    action_id=action.id,
                    state_snapshot=after_state.to_dict(),
                    is_before=False,
                ))

                # 7. Generate rollback instructions
                rollback_instructions = executor.generate_rollback_instructions(
                    action_type=action.action_type.value,
                    before_state=before_state,
                    entity_id=action.target_entity_id,
                    entity_type=action.target_entity_type.value,
                )

                # 8. Mark as succeeded
                action.mark_succeeded(
                    before_state=before_state.to_dict(),
                    after_state=after_state.to_dict(),
                    rollback_instructions=rollback_instructions,
                )

                self._log_event(action, ActionExecutionLog.log_execution_succeeded(
                    tenant_id=self.tenant_id,
                    action_id=action.id,
                    state_snapshot=result.confirmed_state,
                ))

                logger.info(
                    "Action executed successfully",
                    extra={
                        "tenant_id": self.tenant_id,
                        "action_id": action.id,
                        "platform": action.platform,
                    }
                )

                return ActionExecutionResult(
                    success=True,
                    action_id=action.id,
                    status=action.status,
                    message=result.message,
                    before_state=before_state.to_dict(),
                    after_state=after_state.to_dict(),
                    rollback_instructions=rollback_instructions,
                )

            else:
                # Execution failed
                action.mark_failed(
                    error_message=result.message,
                    error_code=result.error_code,
                    before_state=before_state.to_dict() if before_state else None,
                )

                self._log_event(action, ActionExecutionLog.log_execution_failed(
                    tenant_id=self.tenant_id,
                    action_id=action.id,
                    error_details={
                        "message": result.message,
                        "code": result.error_code,
                        "details": result.error_details,
                    },
                    http_status_code=result.http_status_code,
                ))

                logger.warning(
                    "Action execution failed",
                    extra={
                        "tenant_id": self.tenant_id,
                        "action_id": action.id,
                        "error": result.message,
                        "error_code": result.error_code,
                    }
                )

                return ActionExecutionResult(
                    success=False,
                    action_id=action.id,
                    status=action.status,
                    message=result.message,
                    before_state=before_state.to_dict() if before_state else None,
                    error_code=result.error_code,
                    error_details=result.error_details,
                )

        except Exception as e:
            # Unexpected error
            error_message = str(e)
            action.mark_failed(
                error_message=error_message,
                error_code="UNEXPECTED_ERROR",
            )

            self._log_event(action, ActionExecutionLog.log_execution_failed(
                tenant_id=self.tenant_id,
                action_id=action.id,
                error_details={
                    "message": error_message,
                    "type": type(e).__name__,
                },
            ))

            logger.exception(
                "Unexpected error during action execution",
                extra={
                    "tenant_id": self.tenant_id,
                    "action_id": action.id,
                }
            )

            return ActionExecutionResult(
                success=False,
                action_id=action.id,
                status=action.status,
                message=error_message,
                error_code="UNEXPECTED_ERROR",
                error_details={"type": type(e).__name__},
            )

        finally:
            # Always commit changes
            self.db.commit()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_action(self, action_id: str) -> AIAction:
        """Get action by ID with tenant isolation."""
        action = (
            self.db.query(AIAction)
            .filter(
                AIAction.id == action_id,
                AIAction.tenant_id == self.tenant_id,
            )
            .first()
        )

        if not action:
            raise ActionExecutionError(
                message="Action not found",
                code="NOT_FOUND",
                action_id=action_id,
            )

        return action

    def _validate_action_ready(self, action: AIAction) -> None:
        """Validate that action can be executed."""
        if not action.can_be_executed:
            raise ActionExecutionError(
                message=f"Action cannot be executed in status {action.status.value}",
                code="INVALID_STATUS",
                action_id=action.id,
            )

    def _generate_idempotency_key(self, action: AIAction) -> str:
        """Generate idempotency key for action."""
        return BasePlatformExecutor.generate_idempotency_key(
            tenant_id=self.tenant_id,
            action_id=action.id,
        )

    async def _get_executor(self, action: AIAction) -> BasePlatformExecutor:
        """Get platform executor for action."""
        platform = Platform(action.platform.lower())

        executor = self.credentials_service.get_executor_for_platform(
            tenant_id=self.tenant_id,
            platform=platform,
            retry_config=self.retry_config,
        )

        if not executor:
            raise ActionExecutionError(
                message=f"No credentials available for platform {action.platform}",
                code="NO_CREDENTIALS",
                action_id=action.id,
            )

        if not executor.validate_credentials():
            raise ActionExecutionError(
                message=f"Invalid credentials for platform {action.platform}",
                code="INVALID_CREDENTIALS",
                action_id=action.id,
            )

        return executor

    async def _capture_before_state(
        self,
        action: AIAction,
        executor: BasePlatformExecutor,
    ) -> StateCapture:
        """Capture entity state before execution."""
        return await executor.capture_before_state(
            entity_id=action.target_entity_id,
            entity_type=action.target_entity_type.value,
        )

    async def _capture_after_state(
        self,
        action: AIAction,
        executor: BasePlatformExecutor,
    ) -> StateCapture:
        """Capture entity state after execution."""
        return await executor.capture_after_state(
            entity_id=action.target_entity_id,
            entity_type=action.target_entity_type.value,
        )

    async def _execute_on_platform(
        self,
        action: AIAction,
        executor: BasePlatformExecutor,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Execute action on platform via executor."""
        # Log the request
        self._log_event(action, ActionExecutionLog.log_api_request(
            tenant_id=self.tenant_id,
            action_id=action.id,
            request_payload={
                "action_type": action.action_type.value,
                "entity_id": action.target_entity_id,
                "entity_type": action.target_entity_type.value,
                "params": action.action_params,
                "idempotency_key": idempotency_key,
            },
        ))

        # Execute
        result = await executor.execute_action(
            action_type=action.action_type.value,
            entity_id=action.target_entity_id,
            entity_type=action.target_entity_type.value,
            params=action.action_params,
            idempotency_key=idempotency_key,
        )

        # Log the response
        self._log_event(action, ActionExecutionLog.log_api_response(
            tenant_id=self.tenant_id,
            action_id=action.id,
            response_payload=result.response_data or {},
            http_status_code=result.http_status_code or 0,
        ))

        return result

    def _log_event(self, action: AIAction, log_entry: ActionExecutionLog) -> None:
        """Add log entry to database."""
        self.db.add(log_entry)
        self.db.flush()

    # =========================================================================
    # Batch Execution
    # =========================================================================

    async def execute_batch(
        self,
        action_ids: list[str],
    ) -> list[ActionExecutionResult]:
        """
        Execute multiple actions.

        Actions are executed sequentially (not in parallel) to avoid
        rate limiting issues with external platforms.

        Args:
            action_ids: List of action IDs to execute

        Returns:
            List of execution results
        """
        results = []

        for action_id in action_ids:
            try:
                result = await self.execute_action(action_id)
                results.append(result)
            except ActionExecutionError as e:
                results.append(ActionExecutionResult(
                    success=False,
                    action_id=action_id,
                    status=ActionStatus.FAILED,
                    message=str(e),
                    error_code=e.code,
                ))
            except Exception as e:
                results.append(ActionExecutionResult(
                    success=False,
                    action_id=action_id,
                    status=ActionStatus.FAILED,
                    message=str(e),
                    error_code="UNEXPECTED_ERROR",
                ))

        return results

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_actions_ready_for_execution(self, limit: int = 10) -> list[AIAction]:
        """Get actions that are ready for execution."""
        return (
            self.db.query(AIAction)
            .filter(
                AIAction.tenant_id == self.tenant_id,
                AIAction.status.in_([ActionStatus.APPROVED, ActionStatus.QUEUED]),
            )
            .order_by(AIAction.created_at.asc())
            .limit(limit)
            .all()
        )

    def get_execution_logs(self, action_id: str) -> list[ActionExecutionLog]:
        """Get execution logs for an action."""
        return (
            self.db.query(ActionExecutionLog)
            .filter(
                ActionExecutionLog.action_id == action_id,
                ActionExecutionLog.tenant_id == self.tenant_id,
            )
            .order_by(ActionExecutionLog.event_timestamp.asc())
            .all()
        )
