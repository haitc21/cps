"""CMP/BMS-aligned public HTTP API response envelope and error catalog."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cps.contracts.messages.envelope import assert_utc_datetime

T = TypeVar("T")

SUCCESS_MESSAGE = "Success"


class ErrorCode(StrEnum):
    """Stable CPS public API error codes aligned with the CMP platform taxonomy."""

    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PROVIDER_001 = "PROVIDER_001"
    CONNECTION_001 = "CONNECTION_001"
    OPERATION_001 = "OPERATION_001"
    CAPABILITY_001 = "CAPABILITY_001"


@dataclass(frozen=True, slots=True)
class ErrorCodeMeta:
    default_message: str
    http_status: int


ERROR_CATALOG: dict[ErrorCode, ErrorCodeMeta] = {
    ErrorCode.BAD_REQUEST: ErrorCodeMeta("Bad request", 400),
    ErrorCode.UNAUTHORIZED: ErrorCodeMeta("Unauthorized", 401),
    ErrorCode.FORBIDDEN: ErrorCodeMeta("Forbidden", 403),
    ErrorCode.NOT_FOUND: ErrorCodeMeta("Not found", 404),
    ErrorCode.CONFLICT: ErrorCodeMeta("Conflict", 409),
    ErrorCode.VALIDATION_FAILED: ErrorCodeMeta("Validation failed", 400),
    ErrorCode.EXTERNAL_SERVICE_ERROR: ErrorCodeMeta("External service error", 502),
    ErrorCode.INTERNAL_ERROR: ErrorCodeMeta("Internal error", 500),
    ErrorCode.PROVIDER_001: ErrorCodeMeta("Provider not found", 404),
    ErrorCode.CONNECTION_001: ErrorCodeMeta("Provider connection not found", 404),
    ErrorCode.OPERATION_001: ErrorCodeMeta("Operation not found", 404),
    ErrorCode.CAPABILITY_001: ErrorCodeMeta("Capability not available or unsupported", 422),
}


DOMAIN_CODE_TO_ERROR: dict[str, ErrorCode] = {
    "NOT_FOUND": ErrorCode.NOT_FOUND,
    "INVALID_REQUEST": ErrorCode.VALIDATION_FAILED,
    "CONFLICT": ErrorCode.CONFLICT,
    "VERSION_CONFLICT": ErrorCode.CONFLICT,
    "PROVIDER_NAME_CONFLICT": ErrorCode.CONFLICT,
    "PROVIDER_CONNECTION_CONFLICT": ErrorCode.CONFLICT,
    "IDEMPOTENCY_KEY_REUSED": ErrorCode.CONFLICT,
    "INVALID_RESOURCE_STATE": ErrorCode.CONFLICT,
    "NETWORK_POLICY_VIOLATION": ErrorCode.CONFLICT,
    "NETWORK_QUOTA_EXCEEDED": ErrorCode.BAD_REQUEST,
    "PROVIDER_NOT_FOUND": ErrorCode.PROVIDER_001,
    "PROVIDER_CONNECTION_NOT_FOUND": ErrorCode.CONNECTION_001,
    "OPERATION_NOT_FOUND": ErrorCode.OPERATION_001,
    "CAPABILITIES_NOT_AVAILABLE": ErrorCode.CAPABILITY_001,
    "CAPABILITY_UNSUPPORTED": ErrorCode.CAPABILITY_001,
    "CATALOG_POLICY_VIOLATION": ErrorCode.FORBIDDEN,
    "PROVIDER_ERROR": ErrorCode.EXTERNAL_SERVICE_ERROR,
    "OPERATION_TIMEOUT": ErrorCode.EXTERNAL_SERVICE_ERROR,
    "CREDENTIAL_KEY_UNAVAILABLE": ErrorCode.INTERNAL_ERROR,
    "AUTHENTICATION_FAILED": ErrorCode.UNAUTHORIZED,
    "AUTHORIZATION_FAILED": ErrorCode.FORBIDDEN,
    "INTERNAL_ERROR": ErrorCode.INTERNAL_ERROR,
}


def resolve_error_code(domain_code: str) -> ErrorCode:
    return DOMAIN_CODE_TO_ERROR.get(domain_code, ErrorCode.INTERNAL_ERROR)


class FieldViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    value: Any = None
    params: dict[str, Any] = Field(default_factory=dict)


class PagedData[T](BaseModel):
    """BMS paginated payload with 1-based page numbers."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[T]
    page: int = Field(ge=1, description="Current page number (1-based)")
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    total_pages: int = Field(alias="totalPages", ge=0)

    @classmethod
    def from_offset(
        cls,
        items: list[T],
        *,
        offset: int,
        limit: int,
        total: int,
    ) -> PagedData[T]:
        safe_limit = max(limit, 1)
        page = (offset // safe_limit) + 1
        total_pages = math.ceil(total / safe_limit) if total > 0 else 0
        return cls.model_validate(
            {
                "items": items,
                "page": page,
                "limit": safe_limit,
                "total": total,
                "totalPages": total_pages,
            }
        )


class BaseResponse[T](BaseModel):
    """Uniform JSON envelope shared with BMS/TMS public APIs."""

    model_config = ConfigDict(populate_by_name=True)

    status_code: int = Field(alias="statusCode")
    error_code: str | None = Field(default=None, alias="errorCode")
    message: str
    timestamp: datetime
    path: str | None = None
    data: T | None = None

    @field_serializer("timestamp")
    @classmethod
    def serialize_timestamp(cls, value: datetime) -> str:
        normalized = assert_utc_datetime(value)
        return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def success(
        cls,
        data: T,
        *,
        status_code: int = 200,
        message: str = SUCCESS_MESSAGE,
        path: str | None = None,
    ) -> BaseResponse[T]:
        return cls.model_validate(
            {
                "statusCode": status_code,
                "errorCode": None,
                "message": message,
                "timestamp": datetime.now(UTC),
                "path": path,
                "data": data,
            }
        )

    @classmethod
    def failure(
        cls,
        *,
        message: str,
        error_code: ErrorCode | str,
        status_code: int,
        data: Any | None = None,
        path: str | None = None,
    ) -> BaseResponse[Any]:
        code = error_code.value if isinstance(error_code, ErrorCode) else error_code
        return cls.model_validate(
            {
                "statusCode": status_code,
                "errorCode": code,
                "message": message,
                "timestamp": datetime.now(UTC),
                "path": path,
                "data": data,
            }
        )
