"""REST request bodies for explicit flavor administration operations."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class FlavorCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    provider_resource_id: str | None = Field(default=None, max_length=255)
    vcpus: StrictInt = Field(ge=1, le=4096)
    ram_mib: StrictInt = Field(ge=1, le=16_777_216)
    root_disk_gib: StrictInt = Field(ge=0, le=1_048_576)
    ephemeral_disk_gib: StrictInt = Field(default=0, ge=0, le=1_048_576)
    swap_mib: StrictInt = Field(default=0, ge=0, le=16_777_216)
    is_public: StrictBool
    access_project_ids: list[str] = Field(default_factory=list, max_length=256)
    extra_specs: dict[str, str] = Field(default_factory=dict)


class FlavorAccessReplaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_provider_resource_ids: list[str] = Field(max_length=256)


class FlavorExtraSpecsPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set: dict[str, str] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list, max_length=128)
