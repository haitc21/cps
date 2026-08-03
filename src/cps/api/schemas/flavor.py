"""Admin flavor lifecycle request body."""

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.messages.flavor_operations import FlavorOperation
from cps.contracts.messages.resource_operations import ScopeKind


class FlavorOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: FlavorOperation
    required_scope: ScopeKind = ScopeKind.SYSTEM
    provider_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    vcpus: int | None = Field(default=None, ge=1, le=256)
    ram_mib: int | None = Field(default=None, ge=1, le=1048576)
    disk_gib: int | None = Field(default=None, ge=0, le=65536)
    ephemeral_gib: int = Field(default=0, ge=0, le=65536)
    swap_mib: int = Field(default=0, ge=0, le=1048576)
    is_public: bool | None = None
    access_project_ids: list[str] = Field(default_factory=list, max_length=1000)
    extra_specs: dict[str, str] = Field(default_factory=dict)
    remove_extra_spec_keys: list[str] = Field(default_factory=list, max_length=1000)
