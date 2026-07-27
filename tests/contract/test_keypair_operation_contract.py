from uuid import uuid4

import pytest
from pydantic import ValidationError

from cps.contracts.messages.keypair_operations import KeypairOperationRequest


def test_keypair_import_accepts_public_material_only() -> None:
    request = KeypairOperationRequest(
        operation_id=uuid4(),
        provider_connection_id=uuid4(),
        operation="import",
        name="cmp-key",
        public_key="ssh-ed25519 " + "A" * 64,
    )
    assert request.operation.value == "import"


def test_keypair_contract_rejects_private_key_markers() -> None:
    with pytest.raises(ValidationError, match="PRIVATE_KEY_MATERIAL_REJECTED"):
        KeypairOperationRequest(
            operation_id=uuid4(),
            provider_connection_id=uuid4(),
            operation="import",
            name="cmp-key",
            public_key="-----BEGIN OPENSSH PRIVATE KEY-----"  # pragma: allowlist secret
            + "A" * 64,
        )


def test_keypair_delete_requires_provider_id() -> None:
    with pytest.raises(ValidationError):
        KeypairOperationRequest(
            operation_id=uuid4(), provider_connection_id=uuid4(), operation="delete"
        )
