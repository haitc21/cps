from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cps.contracts.messages.resource_operations import ScopeKind


class KeypairOperation(StrEnum):
    IMPORT = "import"
    DELETE = "delete"


class KeypairOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    resource_type: str = Field(default="keypair", pattern=r"^keypair$")
    operation: KeypairOperation
    required_scope: ScopeKind = ScopeKind.PROJECT
    provider_connection_id: UUID
    provider_resource_id: str | None = Field(default=None, max_length=255)
    project_provider_resource_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    public_key: str | None = Field(default=None, min_length=32, max_length=16384)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_public_material(self) -> KeypairOperationRequest:
        if self.operation is KeypairOperation.IMPORT:
            if not self.name or not self.public_key:
                raise ValueError("keypair import requires name and public_key")
            lowered = self.public_key.lower()
            if "private key" in lowered or "begin openssh private key" in lowered:
                raise ValueError("PRIVATE_KEY_MATERIAL_REJECTED")
            if not lowered.startswith(("ssh-rsa ", "ssh-ed25519 ", "ecdsa-sha2-", "sk-ssh-")):
                raise ValueError("unsupported public key format")
        elif not self.provider_resource_id:
            raise ValueError("keypair delete requires provider_resource_id")
        return self
