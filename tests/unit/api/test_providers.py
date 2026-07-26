"""Provider aggregate public DTO redaction tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cps.api.schemas.providers import ProviderCreate, ProviderPatch, ProviderView
from cps.infrastructure.db.models.enums import ConnectionStatus, ProviderStatus

_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "password",
        "username",
        "ciphertext",
        "nonce",
        "encryption_key_version",
        "key_version",
        "credential_id",
        "connection_id",
        "username_ciphertext",
        "username_nonce",
        "password_ciphertext",
        "password_nonce",
        "ca_cert_pem",
    }
)

_CREATE_BODY = {
    "name": "lab-openstack",
    "provider_type": "OPENSTACK",
    "description": "admin cluster",
    "auth_url": "https://keystone.example/v3",
    "username": "cloud-admin",
    "password": "synthetic-admin-password",  # pragma: allowlist secret
    "user_domain_name": "Default",
    "region_name": "RegionOne",
    "interface": "public",
    "verify_tls": True,
}


def test_provider_create_requires_admin_connection_fields() -> None:
    created = ProviderCreate.model_validate(_CREATE_BODY)
    assert created.username == "cloud-admin"
    assert created.password == "synthetic-admin-password"  # pragma: allowlist secret
    assert created.auth_url == "https://keystone.example/v3"


def test_provider_create_rejects_missing_password() -> None:
    body = dict(_CREATE_BODY)
    del body["password"]
    with pytest.raises(ValidationError):
        ProviderCreate.model_validate(body)


def test_provider_view_never_serializes_secret_fields() -> None:
    now = datetime.now(UTC)
    view = ProviderView.model_validate(
        {
            "id": uuid.uuid4(),
            "name": "lab-openstack",
            "provider_type": "OPENSTACK",
            "description": "admin cluster",
            "status": ProviderStatus.ACTIVE,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "auth_url": "https://keystone.example/v3",
            "user_domain_name": "Default",
            "region_name": "RegionOne",
            "interface": "public",
            "verify_tls": True,
            "has_custom_ca": False,
            "connection_status": ConnectionStatus.PENDING_VALIDATION,
        }
    )
    payload = view.model_dump(mode="json")
    assert _FORBIDDEN_RESPONSE_KEYS.isdisjoint(payload.keys())


def test_provider_patch_accepts_optional_secret_rotation() -> None:
    patch = ProviderPatch.model_validate(
        {
            "expected_version": 1,
            "password": "rotated-password",  # pragma: allowlist secret
            "auth_url": "https://keystone.example/v3",
        }
    )
    assert patch.password == "rotated-password"  # pragma: allowlist secret
    assert patch.auth_url == "https://keystone.example/v3"


def test_provider_patch_forbids_extra_secret_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderPatch.model_validate(
            {
                "expected_version": 1,
                "ciphertext": "never",
            }
        )
