"""Keycloak JWT bearer verification."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt
from jwt.exceptions import InvalidTokenError

from cps.security.auth.jwks import JwksSigningKeyProvider, OidcDiscoveryClient
from cps.security.auth.principal import AuthenticatedPrincipal

if TYPE_CHECKING:
    import httpx


class JwtVerificationError(Exception):
    """Raised when a bearer token cannot be verified."""


def _audience_is_valid(
    claims: dict[str, Any],
    *,
    audience: str | None,
    client_id: str,
) -> bool:
    if audience is None:
        return True
    aud = claims.get("aud")
    if isinstance(aud, str):
        audiences = {aud}
    elif isinstance(aud, list):
        audiences = {item for item in aud if isinstance(item, str)}
    else:
        audiences = set()
    if audience in audiences:
        return True
    azp = claims.get("azp")
    return isinstance(azp, str) and azp == client_id


class KeycloakJwtVerifier:
    """Verify bearer JWTs against Keycloak OIDC discovery and JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        audience: str | None,
        discovery: OidcDiscoveryClient,
        signing_keys: JwksSigningKeyProvider,
    ) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._audience = audience
        self._signing_keys = signing_keys

    @classmethod
    def from_settings(
        cls,
        *,
        issuer: str,
        client_id: str,
        audience: str | None,
        jwks_cache_ttl_seconds: int,
        http_client: httpx.AsyncClient | None = None,
    ) -> KeycloakJwtVerifier:
        discovery = OidcDiscoveryClient(
            issuer=issuer,
            cache_ttl_seconds=float(jwks_cache_ttl_seconds),
            http_client=http_client,
        )
        signing_keys = JwksSigningKeyProvider(
            discovery=discovery,
            cache_ttl_seconds=jwks_cache_ttl_seconds,
        )
        return cls(
            issuer=issuer,
            client_id=client_id,
            audience=audience,
            discovery=discovery,
            signing_keys=signing_keys,
        )

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        try:
            signing_key = await self._signing_keys.get_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                issuer=self._issuer,
                options={
                    "verify_aud": False,
                    "require": ["exp", "iat", "sub"],
                },
            )
        except InvalidTokenError as exc:
            raise JwtVerificationError("invalid token") from exc
        except Exception as exc:
            raise JwtVerificationError("token verification failed") from exc

        if not _audience_is_valid(
            claims,
            audience=self._audience,
            client_id=self._client_id,
        ):
            raise JwtVerificationError("invalid audience")

        try:
            return AuthenticatedPrincipal.from_claims(claims, client_id=self._client_id)
        except ValueError as exc:
            raise JwtVerificationError("invalid token claims") from exc
