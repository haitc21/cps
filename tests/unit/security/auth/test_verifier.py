"""JWT verifier unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest
from tests.unit.security.auth.conftest import (
    TestSigningMaterial,
    build_token,
    generate_signing_material,
)

from cps.security.auth.jwks import JwksSigningKeyProvider, OidcDiscoveryClient
from cps.security.auth.verifier import JwtVerificationError, KeycloakJwtVerifier

ISSUER = "http://127.0.0.1:8080/realms/vnpost"


class _FakeSigningKey:
    def __init__(self, key: bytes) -> None:
        self.key = key


@pytest.fixture
def signing_material() -> TestSigningMaterial:
    return generate_signing_material()


def _verifier(
    signing_material: TestSigningMaterial,
    *,
    audience: str | None = "cmp",
) -> KeycloakJwtVerifier:
    discovery = OidcDiscoveryClient(issuer=ISSUER, cache_ttl_seconds=60.0)
    signing_keys = JwksSigningKeyProvider(discovery=discovery, cache_ttl_seconds=60)
    signing_keys.get_signing_key = AsyncMock(  # type: ignore[method-assign]
        return_value=_FakeSigningKey(signing_material.public_pem)
    )
    return KeycloakJwtVerifier(
        issuer=ISSUER,
        client_id="cmp",
        audience=audience,
        discovery=discovery,
        signing_keys=signing_keys,
    )


@pytest.mark.asyncio
async def test_verify_accepts_valid_admin_token(signing_material: TestSigningMaterial) -> None:
    token = build_token(signing_material, issuer=ISSUER, roles=["admin"])
    principal = await _verifier(signing_material).verify(token)
    assert principal.subject
    assert principal.roles == frozenset({"admin"})


@pytest.mark.asyncio
async def test_verify_accepts_deployed_admin_alias(signing_material: TestSigningMaterial) -> None:
    token = build_token(signing_material, issuer=ISSUER, roles=["admin:admin"])
    principal = await _verifier(signing_material).verify(token)
    assert principal.roles == frozenset({"admin"})


@pytest.mark.asyncio
async def test_verify_rejects_expired_token(signing_material: TestSigningMaterial) -> None:
    token = build_token(signing_material, issuer=ISSUER, expired=True)
    with pytest.raises(JwtVerificationError):
        await _verifier(signing_material).verify(token)


@pytest.mark.asyncio
async def test_verify_rejects_wrong_issuer(signing_material: TestSigningMaterial) -> None:
    token = build_token(
        signing_material,
        issuer="http://evil.example/realms/vnpost",
        roles=["admin"],
    )
    with pytest.raises(JwtVerificationError):
        await _verifier(signing_material).verify(token)


@pytest.mark.asyncio
async def test_verify_rejects_wrong_audience_without_matching_azp(
    signing_material: TestSigningMaterial,
) -> None:
    token = build_token(
        signing_material,
        issuer=ISSUER,
        roles=["admin"],
        audience="other-client",
    )
    with pytest.raises(JwtVerificationError):
        await _verifier(signing_material, audience="cmp").verify(token)


@pytest.mark.asyncio
async def test_verify_accepts_account_audience_when_azp_matches_client(
    signing_material: TestSigningMaterial,
) -> None:
    token = build_token(
        signing_material,
        issuer=ISSUER,
        roles=["member"],
        audience="account",
    )
    payload = pyjwt.decode(token, options={"verify_signature": False})
    payload["azp"] = "cmp"
    resigned = pyjwt.encode(
        payload,
        signing_material.private_pem,
        algorithm="RS256",
        headers={"kid": signing_material.kid},
    )
    principal = await _verifier(signing_material, audience="cmp").verify(resigned)
    assert principal.roles == frozenset({"member"})
