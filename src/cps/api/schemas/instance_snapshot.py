"""Public request body for a no-bytes instance image snapshot."""

from pydantic import BaseModel, ConfigDict, Field


class InstanceSnapshotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_provider_resource_id: str = Field(min_length=1, max_length=255)
    project_provider_resource_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=64)
