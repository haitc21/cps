"""Contracts for safe OpenStack connection validation messages."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.contracts.errors import CommonError
from cps.contracts.messages.envelope import MessageEnvelope

MAX_VALIDATION_DOCUMENT_BYTES = 64 * 1024
_FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "token",
        "authorization",
        "user_data",
        "private_key",
        "raw_catalog",
        "raw_response",
    }
)
_REQUIRED_SERVICES = frozenset({"identity", "compute", "network", "image", "block_storage"})
_REQUIRED_FEATURES = frozenset(
    {
        "connection.authenticate",
        "service.identity",
        "service.compute",
        "service.network",
        "service.image",
        "service.block_storage",
    }
)


def _assert_safe_tree(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS or any(
                token in str(key).lower()
                for token in ("password", "token", "authorization", "private_key")
            ):
                raise ValueError(f"forbidden validation field: {key}")
            _assert_safe_tree(child)
    elif isinstance(value, list):
        for child in value:
            _assert_safe_tree(child)


class _VersionedContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str
    supported_major: ClassVar[int] = 1
    allow_sensitive_fields: ClassVar[bool] = False

    @model_validator(mode="after")
    def validate_version_and_size(self) -> _VersionedContract:
        parts = self.schema_version.split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("invalid schema version")
        if int(parts[0]) != self.supported_major:
            raise ValueError("unsupported major schema version")
        if not self.allow_sensitive_fields:
            _assert_safe_tree(self.model_dump(mode="json"))
        if (
            len(json.dumps(self.model_dump(mode="json"), separators=(",", ":")).encode())
            > MAX_VALIDATION_DOCUMENT_BYTES
        ):
            raise ValueError("validation document exceeds maximum size")
        return self


class ServiceCapability(BaseModel):
    model_config = ConfigDict(extra="allow")
    available: bool
    min_version: str | None = None
    max_version: str | None = None
    reason: str | None = Field(default=None, max_length=256)


class FeatureCapability(BaseModel):
    model_config = ConfigDict(extra="allow")
    supported: bool
    reason: str | None = Field(default=None, max_length=256)


class CapabilityDocument(_VersionedContract):
    """Provider-neutral, bounded, secret-free capability result."""

    services: dict[str, ServiceCapability]
    features: dict[str, FeatureCapability]

    @model_validator(mode="after")
    def validate_required_capabilities(self) -> CapabilityDocument:
        if not _REQUIRED_SERVICES.issubset(self.services):
            raise ValueError("capability document is missing required services")
        if not _REQUIRED_FEATURES.issubset(self.features):
            raise ValueError("capability document is missing required features")
        return self


class CredentialResolution(_VersionedContract):
    """Internal-only cleartext resolution; never accepted as an event payload."""

    allow_sensitive_fields: ClassVar[bool] = True

    auth_url: str = Field(min_length=1, max_length=2048)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=4096)
    user_domain_name: str = Field(min_length=1, max_length=255)
    project_name: str = Field(min_length=1, max_length=255)
    project_domain_name: str = Field(min_length=1, max_length=255)
    region_name: str = Field(min_length=1, max_length=255)
    interface: str = Field(pattern="^(public|internal|admin)$")
    verify_tls: bool
    ca_cert_pem: str | None = Field(default=None, max_length=32768)


class ValidationProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    progress: int = Field(ge=0, le=100)
    state: str = Field(pattern="^(RUNNING|WAITING_PROVIDER)$")
    message: str = Field(min_length=1, max_length=256)


class ValidationCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^VALID$")
    capabilities: CapabilityDocument


def validate_validation_event(value: dict[str, Any]) -> dict[str, Any]:
    """Validate an event envelope and its allow-listed validation payload."""
    if "credential_reference" in value:
        raise ValueError("validation events must omit credential_reference")
    envelope = MessageEnvelope.model_validate(value)
    if envelope.message_type.endswith(".progress"):
        ValidationProgress.model_validate(envelope.payload)
    elif envelope.message_type.endswith(".completed"):
        result = envelope.payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("completed validation result is invalid")
        ValidationCompleted.model_validate(result)
    elif envelope.message_type.endswith(".failed"):
        error = envelope.payload.get("error")
        if not isinstance(error, dict):
            raise ValueError("failed validation error is invalid")
        CommonError.model_validate(error)
    else:
        raise ValueError("unsupported validation event type")
    return value
