"""Canonical common error contract and domain exception types."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cps.contracts.messages.envelope import assert_utc_datetime


class ErrorCategory(StrEnum):
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    CAPABILITY = "CAPABILITY"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    QUOTA = "QUOTA"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    PROVIDER = "PROVIDER"
    INTERNAL = "INTERNAL"


class CommonError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    category: ErrorCategory
    retryable: bool
    provider: str | None = None
    provider_service: str | None = None
    provider_request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at_utc(cls, value: datetime) -> datetime:
        return assert_utc_datetime(value)


class DomainError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    category = ErrorCategory.INTERNAL
    retryable = False
    default_public_message = "Internal service error"

    def __init__(
        self,
        public_message: str | None = None,
        *,
        cause: object | None = None,
    ) -> None:
        self.public_message = public_message or type(self).default_public_message
        self.cause = cause
        super().__init__(self.public_message)


class ResourceNotFoundError(DomainError):
    status_code = 404
    code = "NOT_FOUND"
    category = ErrorCategory.NOT_FOUND
    default_public_message = "Resource not found"


class InvalidRequestError(DomainError):
    status_code = 422
    code = "INVALID_REQUEST"
    category = ErrorCategory.VALIDATION
    default_public_message = "Request validation failed"


class DomainConflictError(DomainError):
    status_code = 409
    code = "CONFLICT"
    category = ErrorCategory.CONFLICT
    default_public_message = "Conflict"


class ProviderNotFoundError(ResourceNotFoundError):
    code = "PROVIDER_NOT_FOUND"
    default_public_message = "Provider not found"


class CredentialNotFoundError(ResourceNotFoundError):
    code = "CREDENTIAL_NOT_FOUND"
    default_public_message = "Credential not found"


class VersionConflictError(DomainConflictError):
    code = "VERSION_CONFLICT"
    default_public_message = "Provider version conflict"


class ProviderNameConflictError(DomainConflictError):
    code = "PROVIDER_NAME_CONFLICT"
    default_public_message = "Provider name already exists"


class CredentialInUseError(DomainConflictError):
    code = "RESOURCE_IN_USE"
    default_public_message = "Credential is referenced by a provider connection"


class CredentialKeyUnavailableError(DomainError):
    status_code = 503
    code = "CREDENTIAL_KEY_UNAVAILABLE"
    category = ErrorCategory.INTERNAL
    retryable = True
    default_public_message = "Credential encryption key unavailable"


class ProviderConnectionNotFoundError(ResourceNotFoundError):
    code = "PROVIDER_CONNECTION_NOT_FOUND"
    default_public_message = "Provider connection not found"


class ProviderConnectionConflictError(DomainConflictError):
    code = "PROVIDER_CONNECTION_CONFLICT"
    default_public_message = "Provider connection already exists"


class IdempotencyKeyReusedError(DomainConflictError):
    code = "IDEMPOTENCY_KEY_REUSED"
    default_public_message = "Idempotency key was reused with different input"


class OperationNotFoundPublicError(ResourceNotFoundError):
    code = "OPERATION_NOT_FOUND"
    default_public_message = "Operation not found"


class CapabilitiesNotAvailableError(ResourceNotFoundError):
    code = "CAPABILITIES_NOT_AVAILABLE"
    default_public_message = "Connection capabilities are not available"


class CapabilityUnsupportedError(DomainError):
    status_code = 422
    code = "CAPABILITY_UNSUPPORTED"
    category = ErrorCategory.CAPABILITY
    default_public_message = "Capability unsupported"


class ProviderOperationError(DomainError):
    status_code = 502
    code = "PROVIDER_ERROR"
    category = ErrorCategory.PROVIDER
    default_public_message = "Provider operation failed"

    def __init__(self, cause: object | None = None) -> None:
        """Public message is fixed; diagnostic detail belongs only in ``cause``."""
        super().__init__(type(self).default_public_message, cause=cause)


class OperationTimeoutError(DomainError):
    status_code = 504
    code = "OPERATION_TIMEOUT"
    category = ErrorCategory.TIMEOUT
    retryable = True
    default_public_message = "Operation timed out"
