"""Credential encryption boundaries for CPS persistence."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LENGTH_BYTES = 32
NONCE_LENGTH_BYTES = 12


class CredentialEncryptionError(RuntimeError):
    """Raised when credential encryption or decryption fails."""


class CredentialKeyProvider(Protocol):
    def get_key(self, key_version: str) -> bytes:
        """Return the 32-byte AES key for the given version."""


class CredentialCipher(Protocol):
    def encrypt_password(
        self,
        *,
        credential_id: uuid.UUID,
        plaintext: str,
        key_version: str,
    ) -> EncryptedPassword:
        """Encrypt a credential password for persistence."""

    def decrypt_password(
        self,
        *,
        credential_id: uuid.UUID,
        encrypted: EncryptedPassword,
    ) -> str:
        """Decrypt a persisted credential password."""


@dataclass(frozen=True, slots=True)
class EncryptedPassword:
    ciphertext: bytes
    nonce: bytes
    key_version: str

    def __repr__(self) -> str:
        return "EncryptedPassword(redacted)"


class MappingCredentialKeyProvider:
    """In-memory key provider for tests and explicit wiring."""

    def __init__(self, keys: dict[str, bytes]) -> None:
        self._keys = keys

    def get_key(self, key_version: str) -> bytes:
        return _validate_key_bytes(self._keys[key_version])


class AesGcmCredentialCipher:
    """AES-256-GCM credential cipher with deterministic AAD."""

    def __init__(self, key_provider: CredentialKeyProvider) -> None:
        self._key_provider = key_provider

    def encrypt_password(
        self,
        *,
        credential_id: uuid.UUID,
        plaintext: str,
        key_version: str,
    ) -> EncryptedPassword:
        key = self._resolve_key(key_version)
        nonce = _generate_nonce()
        aad = _build_aad(credential_id, key_version)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return EncryptedPassword(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=key_version,
        )

    def decrypt_password(
        self,
        *,
        credential_id: uuid.UUID,
        encrypted: EncryptedPassword,
    ) -> str:
        key = self._resolve_key(encrypted.key_version)
        aad = _build_aad(credential_id, encrypted.key_version)
        try:
            plaintext = AESGCM(key).decrypt(encrypted.nonce, encrypted.ciphertext, aad)
        except Exception:
            msg = "credential decryption failed"
            raise CredentialEncryptionError(msg) from None
        return plaintext.decode("utf-8")

    def _resolve_key(self, key_version: str) -> bytes:
        provider_error: BaseException | None = None
        try:
            key = self._key_provider.get_key(key_version)
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exc:
            provider_error = exc

        if provider_error is not None:
            msg = "credential encryption key unavailable"
            raise CredentialEncryptionError(msg)

        return _validate_key_bytes(key)


def _build_aad(credential_id: uuid.UUID, key_version: str) -> bytes:
    return f"{credential_id}:{key_version}".encode()


def _generate_nonce() -> bytes:
    return os.urandom(NONCE_LENGTH_BYTES)


def _validate_key_bytes(key: object) -> bytes:
    if not isinstance(key, bytes):
        msg = "credential encryption key unavailable"
        raise CredentialEncryptionError(msg)
    if len(key) != KEY_LENGTH_BYTES:
        msg = "credential encryption key unavailable"
        raise CredentialEncryptionError(msg)
    return key
