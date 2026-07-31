"""Helpers for building CMP/BMS-aligned HTTP API envelopes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cps.contracts.api_response import (
    ERROR_CATALOG,
    SUCCESS_MESSAGE,
    BaseResponse,
    ErrorCode,
    FieldViolation,
    PagedData,
    resolve_error_code,
)
from cps.contracts.errors import DomainError

_SENSITIVE_FIELD_MARKERS = frozenset(
    {
        "password",
        "token",
        "authorization",
        "secret",
        "credential",
        "user_data",
        "private_key",
    }
)


def correlation_id_for(request: Request) -> str:
    return getattr(request.state, "correlation_id", str(uuid4()))


def envelope_json(
    request: Request,
    envelope: BaseResponse[Any],
    *,
    status_code: int | None = None,
) -> JSONResponse:
    correlation_id = correlation_id_for(request)
    resolved_status = status_code if status_code is not None else envelope.status_code
    payload = envelope.model_dump(mode="json", by_alias=True, exclude_none=False)
    if payload.get("errorCode") is None:
        payload.pop("errorCode", None)
    if payload.get("path") is None:
        payload.pop("path", None)
    return JSONResponse(
        status_code=resolved_status,
        content=jsonable_encoder(payload),
        headers={"x-correlation-id": correlation_id},
    )


def api_success(
    data: Any,
    *,
    status_code: int = 200,
    message: str = SUCCESS_MESSAGE,
    path: str | None = None,
) -> BaseResponse[Any]:
    return BaseResponse.success(data, status_code=status_code, message=message, path=path)


def api_failure(
    *,
    message: str,
    error_code: ErrorCode | str,
    status_code: int,
    data: Any | None = None,
    path: str | None = None,
) -> BaseResponse[Any]:
    return BaseResponse.failure(
        message=message,
        error_code=error_code,
        status_code=status_code,
        data=data,
        path=path,
    )


def paged_from_offset(
    items: list[Any],
    *,
    offset: int,
    limit: int,
    total: int,
) -> PagedData[Any]:
    return PagedData.from_offset(items, offset=offset, limit=limit, total=total)


def envelope_from_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    error_code = resolve_error_code(exc.code)
    catalog = ERROR_CATALOG[error_code]
    message = exc.public_message or catalog.default_message
    status_code = exc.status_code
    if error_code in {ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND}:
        status_code = catalog.http_status
    elif error_code == ErrorCode.VALIDATION_FAILED:
        status_code = catalog.http_status
    elif error_code == ErrorCode.CAPABILITY_001:
        status_code = exc.status_code
    elif error_code == ErrorCode.EXTERNAL_SERVICE_ERROR and exc.status_code in {502, 504}:
        status_code = exc.status_code
    elif error_code == ErrorCode.INTERNAL_ERROR and exc.status_code == 503:
        status_code = exc.status_code
    envelope = api_failure(
        message=message,
        error_code=error_code,
        status_code=status_code,
        data={},
        path=request.url.path,
    )
    return envelope_json(request, envelope, status_code=status_code)


def _is_sensitive_field(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(marker in lowered for marker in _SENSITIVE_FIELD_MARKERS)


def _safe_validation_value(field_name: str, value: Any) -> Any:
    if _is_sensitive_field(field_name):
        return None
    return value


def _validation_params(error: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    context = error.get("ctx")
    if isinstance(context, dict):
        for key, raw in context.items():
            if isinstance(raw, str | int | float | bool):
                params[key] = raw
            elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
                params[key] = raw
    return params


def build_validation_fields(
    exc: RequestValidationError | ValidationError,
) -> dict[str, list[FieldViolation]]:
    fields: dict[str, list[FieldViolation]] = {}
    for error in exc.errors():
        location = error.get("loc", ())
        parts = [str(part) for part in location if part not in {"body", "query", "path"}]
        field_name = ".".join(parts) if parts else "request"
        violation = FieldViolation(
            code=str(error.get("type", "invalid")),
            value=_safe_validation_value(field_name, error.get("input")),
            params=_validation_params(dict(error)),
        )
        fields.setdefault(field_name, []).append(violation)
    return fields


def envelope_from_validation_error(
    request: Request,
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    catalog = ERROR_CATALOG[ErrorCode.VALIDATION_FAILED]
    envelope = api_failure(
        message=catalog.default_message,
        error_code=ErrorCode.VALIDATION_FAILED,
        status_code=catalog.http_status,
        data={"fields": build_validation_fields(exc)},
        path=request.url.path,
    )
    return envelope_json(request, envelope, status_code=catalog.http_status)
