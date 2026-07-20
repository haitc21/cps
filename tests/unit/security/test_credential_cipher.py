"""CPS-103 Task 3: credential encryption boundary tests."""

from __future__ import annotations

import logging
import traceback
import uuid

import pytest

from cps.security.credentials import (
    AesGcmCredentialCipher,
    CredentialEncryptionError,
    CredentialKeyProvider,
    EncryptedPassword,
    MappingCredentialKeyProvider,
)

_TEST_KEY = b"a" * 32
_TEST_KEY_V2 = b"c" * 32
_KEY_VERSION = "v1"
_PLAINTEXT = "synthetic-test-password-value"  # pragma: allowlist secret
_SENSITIVE_DIAGNOSTIC = (
    "backend vault lookup failed for version=v99 key=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
_SENSITIVE_KEY_VERSION = "v99"


class _DiagnosticKeyProvider:
    def get_key(self, key_version: str) -> bytes:
        raise RuntimeError(_SENSITIVE_DIAGNOSTIC)


class _InvalidReturnTypeKeyProvider:
    def get_key(self, key_version: str) -> str:
        return "not-bytes"


class _InterruptKeyProvider:
    def get_key(self, key_version: str) -> bytes:
        raise KeyboardInterrupt


def _assert_sanitized_key_failure(
    exc_info: pytest.ExceptionInfo[CredentialEncryptionError],
    *,
    expected_message: str,
    forbidden: tuple[str, ...],
) -> None:
    exc = exc_info.value
    assert str(exc) == expected_message
    assert repr(exc) == f"CredentialEncryptionError('{expected_message}')"
    assert exc.__cause__ is None
    assert exc.__context__ is None

    formatted = "".join(traceback.format_exception_only(type(exc), exc)) + "".join(
        traceback.format_tb(exc.__traceback__)
    )
    for secret in forbidden:
        assert secret not in formatted
    assert "KeyError" not in formatted


@pytest.fixture
def cipher() -> AesGcmCredentialCipher:
    return AesGcmCredentialCipher(
        MappingCredentialKeyProvider(
            {
                _KEY_VERSION: _TEST_KEY,
                "v2": _TEST_KEY_V2,
            }
        )
    )


def test_encrypt_decrypt_round_trip(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    assert cipher.decrypt_password(credential_id=credential_id, encrypted=encrypted) == _PLAINTEXT


def test_encrypt_produces_different_ciphertext_and_nonce(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    first = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    second = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    assert first.ciphertext != second.ciphertext
    assert first.nonce != second.nonce


def test_encrypted_nonce_is_twelve_bytes(cipher: AesGcmCredentialCipher) -> None:
    encrypted = cipher.encrypt_password(
        credential_id=uuid.uuid4(),
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    assert len(encrypted.nonce) == 12


def test_tampered_ciphertext_fails(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    tampered = EncryptedPassword(
        ciphertext=b"\x00" + encrypted.ciphertext[1:],
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
    )
    with pytest.raises(CredentialEncryptionError, match="credential decryption failed"):
        cipher.decrypt_password(credential_id=credential_id, encrypted=tampered)


def test_tampered_nonce_fails(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    tampered = EncryptedPassword(
        ciphertext=encrypted.ciphertext,
        nonce=b"\xff" + encrypted.nonce[1:],
        key_version=encrypted.key_version,
    )
    with pytest.raises(CredentialEncryptionError, match="credential decryption failed"):
        cipher.decrypt_password(credential_id=credential_id, encrypted=tampered)


def test_wrong_credential_id_fails(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    with pytest.raises(CredentialEncryptionError, match="credential decryption failed"):
        cipher.decrypt_password(credential_id=uuid.uuid4(), encrypted=encrypted)


def test_wrong_key_version_fails(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    wrong_version = EncryptedPassword(
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_version="v2",
    )
    with pytest.raises(CredentialEncryptionError, match="credential decryption failed"):
        cipher.decrypt_password(credential_id=credential_id, encrypted=wrong_version)


def test_invalid_key_length_fails_closed() -> None:
    provider = MappingCredentialKeyProvider({_KEY_VERSION: b"short"})
    cipher = AesGcmCredentialCipher(provider)
    with pytest.raises(CredentialEncryptionError, match="credential encryption key unavailable"):
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_KEY_VERSION,
        )


def test_missing_key_provider_version_fails_closed(cipher: AesGcmCredentialCipher) -> None:
    with pytest.raises(CredentialEncryptionError, match="credential encryption key unavailable"):
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version="missing",
        )


def test_encrypted_password_repr_redacts_secrets(cipher: AesGcmCredentialCipher) -> None:
    encrypted = cipher.encrypt_password(
        credential_id=uuid.uuid4(),
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    rendered = repr(encrypted)
    assert _PLAINTEXT not in rendered
    assert encrypted.ciphertext.hex() not in rendered
    assert encrypted.nonce.hex() not in rendered


def test_decrypt_error_message_is_generic(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    tampered = EncryptedPassword(
        ciphertext=b"\x00" + encrypted.ciphertext[1:],
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
    )
    with pytest.raises(CredentialEncryptionError) as exc_info:
        cipher.decrypt_password(credential_id=credential_id, encrypted=tampered)
    assert _PLAINTEXT not in str(exc_info.value)
    assert _TEST_KEY.hex() not in str(exc_info.value)


def test_encrypt_logs_do_not_contain_plaintext(
    cipher: AesGcmCredentialCipher,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    cipher.encrypt_password(
        credential_id=uuid.uuid4(),
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    captured = caplog.text
    assert _PLAINTEXT not in captured
    assert _TEST_KEY.hex() not in captured


def test_encrypt_sanitizes_key_provider_runtime_error() -> None:
    cipher = AesGcmCredentialCipher(_DiagnosticKeyProvider())
    with pytest.raises(
        CredentialEncryptionError, match="credential encryption key unavailable"
    ) as exc_info:
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_SENSITIVE_KEY_VERSION,
        )
    _assert_sanitized_key_failure(
        exc_info,
        expected_message="credential encryption key unavailable",
        forbidden=(_SENSITIVE_DIAGNOSTIC, _SENSITIVE_KEY_VERSION, _TEST_KEY.hex()),
    )


def test_decrypt_sanitizes_key_provider_runtime_error(cipher: AesGcmCredentialCipher) -> None:
    credential_id = uuid.uuid4()
    encrypted = cipher.encrypt_password(
        credential_id=credential_id,
        plaintext=_PLAINTEXT,
        key_version=_KEY_VERSION,
    )
    failing_cipher = AesGcmCredentialCipher(_DiagnosticKeyProvider())
    with pytest.raises(
        CredentialEncryptionError, match="credential encryption key unavailable"
    ) as exc_info:
        failing_cipher.decrypt_password(credential_id=credential_id, encrypted=encrypted)
    _assert_sanitized_key_failure(
        exc_info,
        expected_message="credential encryption key unavailable",
        forbidden=(_SENSITIVE_DIAGNOSTIC, _SENSITIVE_KEY_VERSION, _TEST_KEY.hex()),
    )


def test_missing_mapping_key_has_no_key_error_in_chain() -> None:
    cipher = AesGcmCredentialCipher(MappingCredentialKeyProvider({}))
    with pytest.raises(
        CredentialEncryptionError, match="credential encryption key unavailable"
    ) as exc_info:
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version="missing-version",
        )
    _assert_sanitized_key_failure(
        exc_info,
        expected_message="credential encryption key unavailable",
        forbidden=("missing-version", "KeyError"),
    )


def test_invalid_key_provider_return_type_fails_closed() -> None:
    cipher = AesGcmCredentialCipher(_InvalidReturnTypeKeyProvider())
    with pytest.raises(
        CredentialEncryptionError, match="credential encryption key unavailable"
    ) as exc_info:
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_KEY_VERSION,
        )
    _assert_sanitized_key_failure(
        exc_info,
        expected_message="credential encryption key unavailable",
        forbidden=("not-bytes",),
    )


def test_invalid_key_length_has_sanitized_chain() -> None:
    cipher = AesGcmCredentialCipher(MappingCredentialKeyProvider({_KEY_VERSION: b"short"}))
    with pytest.raises(
        CredentialEncryptionError, match="credential encryption key unavailable"
    ) as exc_info:
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_KEY_VERSION,
        )
    _assert_sanitized_key_failure(
        exc_info,
        expected_message="credential encryption key unavailable",
        forbidden=("short",),
    )


def test_keyboard_interrupt_from_key_provider_is_not_swallowed() -> None:
    cipher = AesGcmCredentialCipher(_InterruptKeyProvider())
    with pytest.raises(KeyboardInterrupt):
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_KEY_VERSION,
        )


def test_system_exit_from_key_provider_is_not_swallowed() -> None:
    class _SystemExitProvider(CredentialKeyProvider):
        def get_key(self, key_version: str) -> bytes:
            raise SystemExit(1)

    cipher = AesGcmCredentialCipher(_SystemExitProvider())
    with pytest.raises(SystemExit):
        cipher.encrypt_password(
            credential_id=uuid.uuid4(),
            plaintext=_PLAINTEXT,
            key_version=_KEY_VERSION,
        )
