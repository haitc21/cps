"""FastAPI handlers that map exceptions to the common error envelope."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cps.contracts.errors import CommonError, DomainError, ErrorCategory


def _response(request: Request, error: CommonError, status_code: int) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={"error": error.model_dump(mode="json"), "correlation_id": correlation_id},
        headers={"x-correlation-id": correlation_id},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, _exc: RequestValidationError) -> JSONResponse:
        error = CommonError(
            code="INVALID_REQUEST",
            message="Request validation failed",
            category=ErrorCategory.VALIDATION,
            retryable=False,
        )
        return _response(request, error, 422)

    @app.exception_handler(DomainError)
    async def domain_handler(request: Request, exc: DomainError) -> JSONResponse:
        error = CommonError(
            code=exc.code,
            message=exc.public_message,
            category=exc.category,
            retryable=exc.retryable,
        )
        return _response(request, error, exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, _exc: Exception) -> JSONResponse:
        error = CommonError(
            code="INTERNAL_ERROR",
            message="Internal service error",
            category=ErrorCategory.INTERNAL,
            retryable=False,
        )
        return _response(request, error, 500)
