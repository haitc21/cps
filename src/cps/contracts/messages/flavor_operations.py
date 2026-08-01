"""Strict provider-neutral contracts for Nova flavor administration."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.safe_metadata import is_secret_key, is_secret_value

_PROVIDER_ID = re.compile(r"^[A-Za-z0-9. _-]+$")
_MAX_SPECS = 128
_MAX_PROJECTS = 256


def _safe_string(value: str, *, label: str) -> str:
    if not value or len(value) > 255:
        raise ValueError(f"{label} must contain 1..255 characters")
    if is_secret_value(value) or value.casefold().startswith(("bearer ", "basic ", "token ")):
        raise ValueError(f"{label} contains secret-bearing data")
    return value


def _safe_specs(value: dict[str, str]) -> dict[str, str]:
    if len(value) > _MAX_SPECS:
        raise ValueError("extra_specs exceeds 128 entries")
    for key, item in value.items():
        _safe_string(key, label="extra spec key")
        _safe_string(item, label="extra spec value")
        if is_secret_key(key):
            raise ValueError("extra spec key is credential-like")
    return dict(sorted(value.items()))


def _validate_project_ids(value: list[str]) -> list[str]:
    checked = [_safe_string(item, label="project provider ID") for item in value]
    if len(set(checked)) != len(checked):
        raise ValueError("project provider IDs must be unique")
    return sorted(checked)


def _validate_provider_id(value: str) -> str:
    if not _PROVIDER_ID.fullmatch(value):
        raise ValueError("provider_resource_id contains invalid characters")
    return _safe_string(value, label="provider_resource_id")


class _FlavorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    operation_id: UUID
    provider_connection_id: UUID
    required_scope: Literal[ScopeKind.SYSTEM] = ScopeKind.SYSTEM


class FlavorCreateRequest(_FlavorRequest):
    resource_type: Literal["flavor"] = "flavor"
    operation: Literal["create"] = "create"
    name: str = Field(min_length=1, max_length=255)
    provider_resource_id: str | None = Field(default=None, max_length=255)
    vcpus: Annotated[StrictInt, Field(ge=1, le=4096)]
    ram_mib: Annotated[StrictInt, Field(ge=1, le=16_777_216)]
    root_disk_gib: Annotated[StrictInt, Field(ge=0, le=1_048_576)]
    ephemeral_disk_gib: Annotated[StrictInt, Field(ge=0, le=1_048_576)] = 0
    swap_mib: Annotated[StrictInt, Field(ge=0, le=16_777_216)] = 0
    is_public: StrictBool
    access_project_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROJECTS)
    extra_specs: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _safe_string(value.strip(), label="name")

    @field_validator("provider_resource_id", mode="before")
    @classmethod
    def normalize_provider_id(cls, value: object) -> object:
        if value is None or value == "auto":
            return None
        if type(value) is not str or not _PROVIDER_ID.fullmatch(value):
            raise ValueError("provider_resource_id contains invalid characters")
        return _safe_string(value, label="provider_resource_id")

    @field_validator("access_project_ids")
    @classmethod
    def validate_access(cls, value: list[str]) -> list[str]:
        return _validate_project_ids(value)

    @field_validator("extra_specs")
    @classmethod
    def validate_specs(cls, value: dict[str, str]) -> dict[str, str]:
        return _safe_specs(value)

    @model_validator(mode="after")
    def validate_visibility(self) -> FlavorCreateRequest:
        if self.is_public and self.access_project_ids:
            raise ValueError("public flavors cannot have restricted project access")
        return self


class FlavorDeleteRequest(_FlavorRequest):
    resource_type: Literal["flavor"] = "flavor"
    operation: Literal["delete"] = "delete"
    provider_resource_id: str = Field(min_length=1, max_length=255)

    @field_validator("provider_resource_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _validate_provider_id(value)


class FlavorAccessReplaceRequest(_FlavorRequest):
    resource_type: Literal["flavor"] = "flavor"
    operation: Literal["access.replace"] = "access.replace"
    provider_resource_id: str = Field(min_length=1, max_length=255)
    project_provider_resource_ids: list[str] = Field(max_length=_MAX_PROJECTS)

    @field_validator("provider_resource_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _validate_provider_id(value)

    @field_validator("project_provider_resource_ids")
    @classmethod
    def validate_projects(cls, value: list[str]) -> list[str]:
        return _validate_project_ids(value)


class FlavorExtraSpecsPatchRequest(_FlavorRequest):
    resource_type: Literal["flavor"] = "flavor"
    operation: Literal["extra_specs.patch"] = "extra_specs.patch"
    provider_resource_id: str = Field(min_length=1, max_length=255)
    set: dict[str, str] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list, max_length=_MAX_SPECS)

    @field_validator("provider_resource_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _validate_provider_id(value)

    @field_validator("set")
    @classmethod
    def validate_set(cls, value: dict[str, str]) -> dict[str, str]:
        return _safe_specs(value)

    @field_validator("unset")
    @classmethod
    def validate_unset(cls, value: list[str]) -> list[str]:
        checked = [_safe_string(item, label="extra spec key") for item in value]
        if any(is_secret_key(item) for item in checked):
            raise ValueError("extra spec key is credential-like")
        if len(set(checked)) != len(checked):
            raise ValueError("unset keys must be unique")
        return sorted(checked)

    @model_validator(mode="after")
    def validate_patch(self) -> FlavorExtraSpecsPatchRequest:
        if not self.set and not self.unset:
            raise ValueError("extra-spec patch cannot be empty")
        if set(self.set).intersection(self.unset):
            raise ValueError("set and unset keys must be disjoint")
        return self


class FlavorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_resource_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    vcpus: Annotated[StrictInt, Field(ge=1, le=4096)]
    ram_mib: Annotated[StrictInt, Field(ge=1, le=16_777_216)]
    root_disk_gib: Annotated[StrictInt, Field(ge=0, le=1_048_576)]
    ephemeral_disk_gib: Annotated[StrictInt, Field(ge=0, le=1_048_576)] = 0
    swap_mib: Annotated[StrictInt, Field(ge=0, le=16_777_216)] = 0
    is_public: StrictBool
    access_project_ids: list[str] = Field(default_factory=list, max_length=_MAX_PROJECTS)
    extra_specs: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider_resource_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        return _validate_provider_id(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        return _safe_string(normalized, label="name")

    @field_validator("access_project_ids")
    @classmethod
    def validate_access(cls, value: list[str]) -> list[str]:
        return _validate_project_ids(value)

    @field_validator("extra_specs")
    @classmethod
    def validate_specs(cls, value: dict[str, str]) -> dict[str, str]:
        return _safe_specs(value)


class FlavorOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    operation_id: UUID
    resource_type: Literal["flavor"] = "flavor"
    operation: Literal["create", "delete", "access.replace", "extra_specs.patch"]
    state: Literal["SUCCEEDED", "FAILED"]
    provider_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    resource: FlavorSnapshot | None = None
    error: dict[str, str] | None = None

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if not value or len(value) > 16:
            raise ValueError("error must contain 1..16 entries")
        return _safe_specs(value)

    @model_validator(mode="after")
    def validate_terminal_result(self) -> FlavorOperationResult:
        if self.state == "SUCCEEDED" and self.operation != "delete" and self.resource is None:
            raise ValueError("successful flavor mutation requires a complete snapshot")
        if (
            self.state == "SUCCEEDED"
            and self.operation == "delete"
            and not self.provider_resource_id
        ):
            raise ValueError("successful flavor delete requires provider identity")
        if self.state == "FAILED" and not self.error:
            raise ValueError("failed flavor mutation requires an error")
        if self.state == "FAILED" and self.resource is not None:
            raise ValueError("failed flavor mutation cannot include a resource")
        if self.state == "SUCCEEDED" and self.error is not None:
            raise ValueError("successful flavor mutation cannot include an error")
        return self
