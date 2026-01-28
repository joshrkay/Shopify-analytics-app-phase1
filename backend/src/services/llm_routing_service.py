"""
LLM Routing Service for Story 8.8 - Model Routing & Prompt Governance.

Provides:
- Model selection based on org configuration
- Automatic fallback on primary model failure
- Versioned prompt template rendering
- Usage logging for audit and cost tracking

SECURITY:
- Tenant isolation enforced via tenant_id
- No hardcoded models - all from registry
- Complete audit trail for all LLM calls
- API keys never logged

NO AUTO-EXECUTION:
- All LLM calls are explicit
- Results require interpretation
- No autonomous actions
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from src.models.llm_routing import (
    LLMModelRegistry,
    LLMOrgConfig,
    LLMPromptTemplate,
    LLMUsageLog,
    LLMResponseStatus,
)
from src.integrations.openrouter import (
    OpenRouterClient,
    get_openrouter_client,
    ChatMessage,
    ChatCompletionResponse,
    OpenRouterError,
    OpenRouterRateLimitError,
    OpenRouterTimeoutError,
    OpenRouterModelUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMCompletionResult:
    """Result of an LLM completion request."""
    content: str
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: Decimal
    was_fallback: bool
    fallback_reason: Optional[str] = None


class LLMRoutingError(Exception):
    """Raised when LLM routing fails."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.tenant_id = tenant_id


class LLMRoutingService:
    """
    Service for routing LLM requests with fallback support.

    Handles:
    - Org-level model configuration
    - Primary and fallback model selection
    - Prompt template rendering
    - Usage logging

    SECURITY: tenant_id is required and enforced on all operations.
    """

    # Default model if org has no config
    DEFAULT_MODEL_ID = "anthropic/claude-3-haiku"

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        client: Optional[OpenRouterClient] = None,
    ):
        """
        Initialize LLM routing service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT
            client: Optional OpenRouter client (created if not provided)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._client = client
        self._org_config: Optional[LLMOrgConfig] = None

    def _get_client(self) -> OpenRouterClient:
        """Get or create OpenRouter client."""
        if self._client is None:
            self._client = get_openrouter_client()
        return self._client

    def _get_org_config(self) -> Optional[LLMOrgConfig]:
        """Get cached org configuration."""
        if self._org_config is None:
            self._org_config = self.db.query(LLMOrgConfig).filter(
                LLMOrgConfig.tenant_id == self.tenant_id
            ).first()
        return self._org_config

    def _get_model_registry(self, model_id: str) -> Optional[LLMModelRegistry]:
        """Get model from registry by ID."""
        return self.db.query(LLMModelRegistry).filter(
            LLMModelRegistry.model_id == model_id,
            LLMModelRegistry.is_enabled == True,
        ).first()

    def _get_default_model(self) -> Optional[LLMModelRegistry]:
        """Get default model from registry."""
        return self._get_model_registry(self.DEFAULT_MODEL_ID)

    def get_primary_model(self) -> LLMModelRegistry:
        """
        Get the primary model for this tenant.

        Falls back to default model if org has no config.

        Returns:
            LLMModelRegistry for the primary model

        Raises:
            LLMRoutingError: If no model is available
        """
        org_config = self._get_org_config()

        if org_config:
            model = self._get_model_registry(org_config.primary_model_id)
            if model:
                return model

        # Fall back to default
        model = self._get_default_model()
        if model:
            return model

        raise LLMRoutingError(
            message="No LLM model available",
            code="no_model_available",
            tenant_id=self.tenant_id,
        )

    def get_fallback_model(self) -> Optional[LLMModelRegistry]:
        """
        Get the fallback model for this tenant.

        Returns:
            LLMModelRegistry for fallback model, or None if not configured
        """
        org_config = self._get_org_config()

        if org_config and org_config.fallback_model_id:
            return self._get_model_registry(org_config.fallback_model_id)

        return None

    def get_prompt_template(
        self,
        template_key: str,
        version: Optional[int] = None,
    ) -> Optional[LLMPromptTemplate]:
        """
        Get a prompt template by key.

        Priority:
        1. Tenant-specific active template
        2. System template (tenant_id=NULL)

        Args:
            template_key: Template identifier
            version: Specific version (default: active version)

        Returns:
            LLMPromptTemplate or None if not found
        """
        # Try tenant-specific template first
        query = self.db.query(LLMPromptTemplate).filter(
            LLMPromptTemplate.template_key == template_key,
            LLMPromptTemplate.tenant_id == self.tenant_id,
            LLMPromptTemplate.is_active == True,
        )
        if version is not None:
            query = query.filter(LLMPromptTemplate.version == version)

        template = query.order_by(LLMPromptTemplate.version.desc()).first()

        if template:
            return template

        # Fall back to system template
        query = self.db.query(LLMPromptTemplate).filter(
            LLMPromptTemplate.template_key == template_key,
            LLMPromptTemplate.tenant_id.is_(None),
            LLMPromptTemplate.is_system == True,
            LLMPromptTemplate.is_active == True,
        )
        if version is not None:
            query = query.filter(LLMPromptTemplate.version == version)

        return query.order_by(LLMPromptTemplate.version.desc()).first()

    def render_template(
        self,
        template_key: str,
        variables: Dict[str, Any],
        version: Optional[int] = None,
    ) -> Optional[str]:
        """
        Render a prompt template with variables.

        Args:
            template_key: Template identifier
            variables: Variables to substitute
            version: Specific version (default: active version)

        Returns:
            Rendered template string, or None if template not found
        """
        template = self.get_prompt_template(template_key, version)
        if template:
            return template.render(variables)
        return None

    def _log_usage(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_usd: Decimal,
        status: str,
        was_fallback: bool = False,
        fallback_reason: Optional[str] = None,
        error_message: Optional[str] = None,
        template_key: Optional[str] = None,
        template_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMUsageLog:
        """
        Log LLM usage for audit and cost tracking.

        Args:
            model_id: Model used
            input_tokens: Input token count
            output_tokens: Output token count
            latency_ms: Request latency in milliseconds
            cost_usd: Calculated cost in USD
            status: Response status
            was_fallback: Whether fallback model was used
            fallback_reason: Reason for fallback
            error_message: Error message if applicable
            template_key: Prompt template key used
            template_version: Prompt template version used
            metadata: Additional request metadata

        Returns:
            Created LLMUsageLog entry
        """
        log_entry = LLMUsageLog(
            tenant_id=self.tenant_id,
            model_id=model_id,
            prompt_template_key=template_key,
            prompt_template_version=template_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            was_fallback=was_fallback,
            fallback_reason=fallback_reason,
            request_metadata=metadata or {},
            response_status=status,
            error_message=error_message,
        )

        self.db.add(log_entry)
        self.db.commit()

        logger.info(
            "LLM usage logged",
            extra={
                "tenant_id": self.tenant_id,
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": str(cost_usd),
                "status": status,
                "was_fallback": was_fallback,
            },
        )

        return log_entry

    async def complete(
        self,
        messages: List[ChatMessage],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        template_key: Optional[str] = None,
        template_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletionResult:
        """
        Complete a chat request with automatic fallback.

        Tries primary model first, falls back on certain errors.

        Args:
            messages: Chat messages to send
            max_tokens: Override max tokens (default: from org config)
            temperature: Override temperature (default: from org config)
            template_key: Template key for logging
            template_version: Template version for logging
            metadata: Additional request metadata

        Returns:
            LLMCompletionResult with response content and metrics

        Raises:
            LLMRoutingError: If all models fail
        """
        org_config = self._get_org_config()
        primary_model = self.get_primary_model()
        fallback_model = self.get_fallback_model()

        # Determine parameters
        effective_max_tokens = max_tokens
        if effective_max_tokens is None and org_config:
            effective_max_tokens = org_config.max_tokens_per_request

        effective_temperature = temperature
        if effective_temperature is None:
            effective_temperature = float(org_config.temperature) if org_config else 0.7

        client = self._get_client()
        start_time = time.time()

        # Try primary model
        try:
            response = await client.chat_completion(
                messages=messages,
                model=primary_model.model_id,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            cost = primary_model.calculate_cost(
                response.input_tokens,
                response.output_tokens,
            )

            # Log success
            self._log_usage(
                model_id=primary_model.model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                status=LLMResponseStatus.SUCCESS.value,
                template_key=template_key,
                template_version=template_version,
                metadata=metadata,
            )

            return LLMCompletionResult(
                content=response.content,
                model_id=primary_model.model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.input_tokens + response.output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost,
                was_fallback=False,
            )

        except (OpenRouterRateLimitError, OpenRouterTimeoutError, OpenRouterModelUnavailableError) as e:
            primary_error = e
            fallback_reason = type(e).__name__

            logger.warning(
                "Primary model failed, attempting fallback",
                extra={
                    "tenant_id": self.tenant_id,
                    "primary_model": primary_model.model_id,
                    "error": str(e),
                    "fallback_reason": fallback_reason,
                },
            )

            # Log primary failure
            latency_ms = int((time.time() - start_time) * 1000)
            status = LLMResponseStatus.TIMEOUT.value if isinstance(e, OpenRouterTimeoutError) else LLMResponseStatus.RATE_LIMITED.value if isinstance(e, OpenRouterRateLimitError) else LLMResponseStatus.ERROR.value

            self._log_usage(
                model_id=primary_model.model_id,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                cost_usd=Decimal("0"),
                status=status,
                error_message=str(e),
                template_key=template_key,
                template_version=template_version,
                metadata=metadata,
            )

            # Try fallback if available
            if fallback_model:
                try:
                    start_time = time.time()
                    response = await client.chat_completion(
                        messages=messages,
                        model=fallback_model.model_id,
                        max_tokens=effective_max_tokens,
                        temperature=effective_temperature,
                    )

                    latency_ms = int((time.time() - start_time) * 1000)
                    cost = fallback_model.calculate_cost(
                        response.input_tokens,
                        response.output_tokens,
                    )

                    # Log fallback success
                    self._log_usage(
                        model_id=fallback_model.model_id,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        latency_ms=latency_ms,
                        cost_usd=cost,
                        status=LLMResponseStatus.SUCCESS.value,
                        was_fallback=True,
                        fallback_reason=fallback_reason,
                        template_key=template_key,
                        template_version=template_version,
                        metadata=metadata,
                    )

                    return LLMCompletionResult(
                        content=response.content,
                        model_id=fallback_model.model_id,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.input_tokens + response.output_tokens,
                        latency_ms=latency_ms,
                        cost_usd=cost,
                        was_fallback=True,
                        fallback_reason=fallback_reason,
                    )

                except OpenRouterError as fallback_error:
                    logger.error(
                        "Fallback model also failed",
                        extra={
                            "tenant_id": self.tenant_id,
                            "fallback_model": fallback_model.model_id,
                            "error": str(fallback_error),
                        },
                    )
                    raise LLMRoutingError(
                        message=f"Both primary and fallback models failed: {fallback_error}",
                        code="all_models_failed",
                        tenant_id=self.tenant_id,
                    )

            # No fallback available
            raise LLMRoutingError(
                message=f"Primary model failed and no fallback configured: {primary_error}",
                code="no_fallback",
                tenant_id=self.tenant_id,
            )

        except OpenRouterError as e:
            # Non-retryable error (auth, content filter, etc.)
            latency_ms = int((time.time() - start_time) * 1000)

            self._log_usage(
                model_id=primary_model.model_id,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                cost_usd=Decimal("0"),
                status=LLMResponseStatus.ERROR.value,
                error_message=str(e),
                template_key=template_key,
                template_version=template_version,
                metadata=metadata,
            )

            raise LLMRoutingError(
                message=f"LLM request failed: {e}",
                code="llm_error",
                tenant_id=self.tenant_id,
            )

    async def complete_with_template(
        self,
        template_key: str,
        variables: Dict[str, Any],
        system_message: Optional[str] = None,
        version: Optional[int] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletionResult:
        """
        Complete using a prompt template.

        Args:
            template_key: Template identifier
            variables: Variables to substitute in template
            system_message: Optional system message prefix
            version: Specific template version
            max_tokens: Override max tokens
            temperature: Override temperature
            metadata: Additional request metadata

        Returns:
            LLMCompletionResult with response content and metrics

        Raises:
            LLMRoutingError: If template not found or completion fails
        """
        template = self.get_prompt_template(template_key, version)

        if not template:
            raise LLMRoutingError(
                message=f"Prompt template not found: {template_key}",
                code="template_not_found",
                tenant_id=self.tenant_id,
            )

        rendered_content = template.render(variables)

        messages = []
        if system_message:
            messages.append(ChatMessage(role="system", content=system_message))
        messages.append(ChatMessage(role="user", content=rendered_content))

        return await self.complete(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            template_key=template_key,
            template_version=template.version,
            metadata=metadata,
        )

    def get_usage_stats(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get usage statistics for the tenant.

        Args:
            days: Number of days to include (default: 30)

        Returns:
            Dict with usage stats: total_tokens, total_cost, request_count, etc.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = self.db.query(
            func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
            func.sum(LLMUsageLog.cost_usd).label("total_cost"),
            func.count(LLMUsageLog.id).label("request_count"),
            func.count(LLMUsageLog.id).filter(
                LLMUsageLog.response_status == LLMResponseStatus.SUCCESS.value
            ).label("success_count"),
            func.count(LLMUsageLog.id).filter(
                LLMUsageLog.was_fallback == True
            ).label("fallback_count"),
        ).filter(
            LLMUsageLog.tenant_id == self.tenant_id,
            LLMUsageLog.created_at >= cutoff,
        ).first()

        return {
            "total_tokens": result.total_tokens or 0,
            "total_cost_usd": float(result.total_cost or 0),
            "request_count": result.request_count or 0,
            "success_count": result.success_count or 0,
            "fallback_count": result.fallback_count or 0,
            "period_days": days,
        }
