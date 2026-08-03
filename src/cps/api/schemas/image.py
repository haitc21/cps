"""Admin image lifecycle request body; content bytes are deliberately absent."""

from pydantic import BaseModel, ConfigDict, Field

from cps.contracts.messages.image_operations import ImageOperation
from cps.contracts.messages.resource_operations import ScopeKind


class ImageOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: ImageOperation
    required_scope: ScopeKind = ScopeKind.SYSTEM
    provider_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    disk_format: str | None = Field(default=None, max_length=16)
    container_format: str = Field(default="bare", max_length=16)
    architecture: str | None = Field(default=None, max_length=64)
    kernel_id: str | None = Field(default=None, max_length=255)
    ramdisk_id: str | None = Field(default=None, max_length=255)
    min_disk_gib: int = Field(default=0, ge=0, le=65536)
    min_ram_mib: int = Field(default=0, ge=0, le=1048576)
    visibility: str | None = Field(default=None, pattern=r"^(private|shared|community|public)$")
    protected: bool | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=50)
    remove_metadata_keys: list[str] = Field(default_factory=list, max_length=50)
    member_project_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
