"""Public HTTP API envelope contract tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cps.api.response import api_success
from cps.config import Settings
from cps.contracts.api_response import BaseResponse, ErrorCode, PagedData
from cps.contracts.errors import ResourceNotFoundError
from cps.main import create_app


def test_success_envelope_serializes_bms_field_order() -> None:
    envelope = api_success({"id": "demo"})
    payload = json.loads(envelope.model_dump_json(by_alias=True, exclude_none=True))
    assert list(payload.keys()) == ["statusCode", "message", "timestamp", "data"]
    assert payload["statusCode"] == 200
    assert payload["message"] == "Success"
    assert payload["data"] == {"id": "demo"}


def test_paged_data_emits_canonical_metadata() -> None:
    page = PagedData.from_offset(["a", "b"], offset=50, limit=25, total=120)
    payload = page.model_dump(mode="json", by_alias=True)
    assert payload == {
        "items": ["a", "b"],
        "page": 3,
        "limit": 25,
        "total": 120,
        "totalPages": 5,
    }


def test_error_envelope_omits_null_success_fields() -> None:
    envelope = BaseResponse.failure(
        message="Not found",
        error_code=ErrorCode.NOT_FOUND,
        status_code=404,
        data={},
        path="/api/v1/missing",
    )
    payload = json.loads(envelope.model_dump_json(by_alias=True, exclude_none=True))
    assert payload["statusCode"] == 404
    assert payload["errorCode"] == "NOT_FOUND"
    assert payload["path"] == "/api/v1/missing"
    assert "error" not in payload


def test_validation_error_includes_field_violations() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_contract/validation")
    async def validation(value: int) -> dict[str, int]:
        return {"value": value}

    response = TestClient(app, raise_server_exceptions=False).get("/_contract/validation")
    body = response.json()
    assert response.status_code == 400
    assert body["errorCode"] == "VALIDATION_FAILED"
    fields = body["data"]["fields"]
    assert "value" in fields
    violation = fields["value"][0]
    assert {"code", "value", "params"} <= set(violation)


def test_domain_error_maps_to_catalog_code() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/_contract/not-found")
    async def not_found() -> None:
        raise ResourceNotFoundError("missing provider")

    response = TestClient(app, raise_server_exceptions=False).get("/_contract/not-found")
    body = response.json()
    assert response.status_code == 404
    assert body["statusCode"] == 404
    assert body["errorCode"] == "NOT_FOUND"
    assert body["message"] == "missing provider"


@pytest.mark.parametrize(
    ("offset", "limit", "expected_page"),
    (
        (0, 50, 1),
        (50, 25, 3),
        (100, 100, 2),
    ),
)
def test_offset_maps_to_one_based_page(offset: int, limit: int, expected_page: int) -> None:
    page = PagedData.from_offset([], offset=offset, limit=limit, total=0)
    assert page.page == expected_page


def test_openapi_declares_base_response_for_provider_list() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    schema = app.openapi()
    list_op = schema["paths"]["/api/v1/admin/providers"]["get"]
    response_schema = list_op["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in response_schema
    component_name = response_schema["$ref"].rsplit("/", 1)[-1]
    component = schema["components"]["schemas"][component_name]
    assert "statusCode" in component["properties"]
    assert "data" in component["properties"]
