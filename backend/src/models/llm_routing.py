"""
LLM Routing models for Story 8.8 - Model Routing & Prompt Governance.

Provides:
- LLMModelRegistry: Available models from OpenRouter (no hardcoding)
- LLMOrgConfig: Organization-level model selection and preferences
- LLMPromptTemplate: Versioned prompt templates with governance
- LLMUsageLog: Audit trail for all LLM calls

SECURITY:
- tenant_id from TenantScopedMixin ensures isolation
- tenant_id is ONLY extracted from JWT, never from client input
- No hardcoded model names - all models configured via registry
- Usage logs provide complete audit trail

NO AUTO-EXECUTION:
- Model selection is advisory
- Prompts require explicit invocation
- All calls are logged
"""

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    Text,
    DateTime,
    Numeric,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class LLMResponseStatus(str, enum.Enum):
    """Status of LLM API response."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class LLMModelRegistry(Base, TimestampMixin):
    """
    Registry of available LLM models via OpenRouter.

    KEY DESIGN: No hardcoded models. All model configurations are stored here,
    allowing runtime updates without code changes.

    Capabilities array may include: 'chat', 'function_calling', 'vision'
    tier_restriction: NULL=all tiers, 'growth'=Growth+, 'enterprise'=Enterprise only
    """

    __tablename__ = "llm_model_registry"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique registry entry ID (UUID)"
    )

    model_id = Column(
        String(255),
        unique=True,
        nullable=False,
        comment="OpenRouter model ID (e.g., 'openai/gpt-4-turbo')"
    )

    display_name = Column(
        String(255),
        nullable=False,
        comment="Human-readable model name"
    )

    provider = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Model provider: openai, anthropic, meta, etc."
    )

    context_window = Column(
        Integer,
        nullable=False,
        default=4096,
        comment="Maximum context length in tokens"
    )

    max_output_tokens = Column(
        Integer,
        nullable=False,
        default=4096,
        comment="Maximum output tokens per request"
    )

    cost_per_input_token = Column(
        Numeric(12, 10),
        nullable=False,
        default=Decimal("0"),
        comment="Cost per input token in USD"
    )

    cost_per_output_token = Column(
        Numeric(12, 10),
        nullable=False,
        default=Decimal("0"),
        comment="Cost per output token in USD"
    )

    capabilities = Column(
        JSONB,
        nullable=False,
        default=list,
        comment="Model capabilities: ['chat', 'function_calling', 'vision']"
    )

    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether model is available for selection"
    )

    tier_restriction = Column(
        String(50),
        nullable=True,
        comment="Billing tier restriction: NULL=all, 'growth', 'enterprise'"
    )

    def __repr__(self) -> str:
        return f"<LLMModelRegistry(model_id={self.model_id}, provider={self.provider})>"

    def has_capability(self, capability: str) -> bool:
        """Check if model has a specific capability."""
        return capability in (self.capabilities or [])

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Calculate cost for a request with given token counts."""
        input_cost = Decimal(str(input_tokens)) * self.cost_per_input_token
        output_cost = Decimal(str(output_tokens)) * self.cost_per_output_token
        return input_cost + output_cost


class LLMOrgConfig(Base, TimestampMixin):
    """
    Organization-level LLM configuration.

    Each tenant can configure:
    - Primary model for LLM calls
    - Fallback model if primary fails
    - Token limits and temperature
    - Monthly budget constraints

    SECURITY: tenant_id is ONLY extracted from JWT, never from client input.
    """

    __tablename__ = "llm_org_config"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Configuration ID (UUID)"
    )

    tenant_id = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Tenant identifier from JWT org_id. NEVER from client input."
    )

    primary_model_id = Column(
        String(255),
        ForeignKey("llm_model_registry.model_id"),
        nullable=False,
        comment="Primary model for LLM calls"
    )

    fallback_model_id = Column(
        String(255),
        ForeignKey("llm_model_registry.model_id"),
        nullable=True,
        comment="Fallback model if primary fails"
    )

    max_tokens_per_request = Column(
        Integer,
        nullable=False,
        default=2048,
        comment="Maximum output tokens per request"
    )

    temperature = Column(
        Numeric(3, 2),
        nullable=False,
        default=Decimal("0.7"),
        comment="Temperature for LLM sampling (0.0-2.0)"
    )

    monthly_token_budget = Column(
        Integer,
        nullable=True,
        comment="Monthly token budget, NULL=unlimited based on tier"
    )

    preferences = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Additional configuration preferences"
    )

    def __repr__(self) -> str:
        return f"<LLMOrgConfig(tenant_id={self.tenant_id}, primary_model={self.primary_model_id})>"


class LLMPromptTemplate(Base, TimestampMixin):
    """
    Versioned prompt templates for LLM governance.

    Templates can be:
    - System templates (tenant_id=NULL, is_system=True): Default templates
    - Custom templates (tenant_id=<id>): Tenant-specific overrides

    VERSION CONTROL: Each template_key can have multiple versions.
    Only one version can be active per tenant/key combination.

    SECURITY:
    - System templates cannot be modified by users
    - Custom templates require appropriate entitlements
    """

    __tablename__ = "llm_prompt_template"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Template ID (UUID)"
    )

    tenant_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="NULL=system template, otherwise tenant-specific"
    )

    template_key = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Template identifier: 'insight_analysis', 'recommendation_generation'"
    )

    version = Column(
        Integer,
        nullable=False,
        default=1,
        comment="Template version number"
    )

    template_content = Column(
        Text,
        nullable=False,
        comment="Template content with {{variable}} placeholders"
    )

    variables = Column(
        JSONB,
        nullable=False,
        default=list,
        comment="Expected variables for this template"
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this version is active"
    )

    is_system = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="System templates cannot be modified by users"
    )

    created_by = Column(
        String(255),
        nullable=True,
        comment="User ID who created the template"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "template_key",
            "version",
            name="uq_llm_prompt_template_key_version"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMPromptTemplate("
            f"key={self.template_key}, "
            f"version={self.version}, "
            f"tenant_id={self.tenant_id}"
            f")>"
        )

    def render(self, variables: Dict[str, Any]) -> str:
        """
        Render template with provided variables.

        Uses simple {{variable}} replacement pattern.
        Missing variables are left as-is (fail-safe).
        """
        content = self.template_content
        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            content = content.replace(placeholder, str(value))
        return content


class LLMUsageLog(Base):
    """
    Audit log for all LLM API calls.

    Every LLM call is logged with:
    - Token usage and cost
    - Latency metrics
    - Fallback information
    - Error details if applicable

    SECURITY:
    - Complete audit trail for compliance
    - No PII in request_metadata
    - Tenant-scoped queries only
    """

    __tablename__ = "llm_usage_log"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Log entry ID (UUID)"
    )

    tenant_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Tenant identifier from JWT org_id"
    )

    model_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Model used for this request"
    )

    prompt_template_key = Column(
        String(100),
        nullable=True,
        comment="Template key used, if any"
    )

    prompt_template_version = Column(
        Integer,
        nullable=True,
        comment="Template version used, if any"
    )

    input_tokens = Column(
        Integer,
        nullable=False,
        comment="Number of input tokens"
    )

    output_tokens = Column(
        Integer,
        nullable=False,
        comment="Number of output tokens"
    )

    total_tokens = Column(
        Integer,
        nullable=False,
        comment="Total tokens (input + output)"
    )

    latency_ms = Column(
        Integer,
        nullable=False,
        comment="Request latency in milliseconds"
    )

    cost_usd = Column(
        Numeric(10, 6),
        nullable=False,
        comment="Calculated cost in USD"
    )

    was_fallback = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether fallback model was used"
    )

    fallback_reason = Column(
        String(255),
        nullable=True,
        comment="Reason for fallback, if applicable"
    )

    request_metadata = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Request context: correlation_id, feature, etc."
    )

    response_status = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Response status: success, error, timeout, rate_limited"
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if status is not success"
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Timestamp of LLM call"
    )

    __table_args__ = (
        Index(
            "ix_llm_usage_log_tenant_created",
            "tenant_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMUsageLog("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"model={self.model_id}, "
            f"status={self.response_status}"
            f")>"
        )
