"""FastAPI handlers that map exceptions to the CMP/BMS BaseResponse envelope."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from cps.api.response import (
    api_failure,
    envelope_from_domain_error,
    envelope_from_validation_error,
    envelope_json,
)
from cps.contracts.api_response import ERROR_CATALOG, ErrorCode
from cps.contracts.errors import DomainError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> object:
        return envelope_from_validation_error(request, exc)

    @app.exception_handler(ValidationError)
    async def contract_validation_handler(
        request: Request,
        exc: ValidationError,
    ) -> object:
        return envelope_from_validation_error(request, exc)

    @app.exception_handler(DomainError)
    async def domain_handler(request: Request, exc: DomainError) -> object:
        return envelope_from_domain_error(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> object:
        if exc.status_code == 404:
            catalog = ERROR_CATALOG[ErrorCode.NOT_FOUND]
            envelope = api_failure(
                message=catalog.default_message,
                error_code=ErrorCode.NOT_FOUND,
                status_code=catalog.http_status,
                data={},
                path=request.url.path,
            )
            return envelope_json(request, envelope, status_code=catalog.http_status)
        catalog = ERROR_CATALOG[ErrorCode.BAD_REQUEST]
        envelope = api_failure(
            message=exc.detail if isinstance(exc.detail, str) else catalog.default_message,
            error_code=ErrorCode.BAD_REQUEST,
            status_code=exc.status_code,
            data={},
            path=request.url.path,
        )
        return envelope_json(request, envelope, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, _exc: Exception) -> object:
        catalog = ERROR_CATALOG[ErrorCode.INTERNAL_ERROR]
        envelope = api_failure(
            message=catalog.default_message,
            error_code=ErrorCode.INTERNAL_ERROR,
            status_code=catalog.http_status,
            data={},
            path=request.url.path,
        )
        return envelope_json(request, envelope, status_code=catalog.http_status)
