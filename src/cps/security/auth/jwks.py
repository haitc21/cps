"""OIDC discovery and JWKS retrieval with bounded caching."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from jwt import PyJWKClient

_DEFAULT_HTTP_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class OidcDiscoveryClient:
    """Fetch and cache OpenID Provider metadata."""

    def __init__(
        self,
        *,
        issuer: str,
        cache_ttl_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._discovery_url = f"{self._issuer}/.well-known/openid-configuration"
        self._cache_ttl_seconds = cache_ttl_seconds
        self._http_client = http_client
        self._metadata: dict[str, Any] | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_metadata(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._metadata is not None and now < self._expires_at:
            return self._metadata

        async with self._lock:
            now = time.monotonic()
            if self._metadata is not None and now < self._expires_at:
                return self._metadata
            metadata = await self._fetch_metadata()
            self._metadata = metadata
            self._expires_at = time.monotonic() + self._cache_ttl_seconds
            return metadata

    async def get_jwks_uri(self) -> str:
        metadata = await self.get_metadata()
        jwks_uri = metadata.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            msg = "OIDC metadata is missing jwks_uri"
            raise RuntimeError(msg)
        return jwks_uri

    async def _fetch_metadata(self) -> dict[str, Any]:
        if self._http_client is not None:
            response = await self._http_client.get(self._discovery_url)
            response.raise_for_status()
            payload = response.json()
        else:
            payload = await asyncio.to_thread(self._fetch_metadata_sync)
        if not isinstance(payload, dict):
            msg = "OIDC discovery response is not a JSON object"
            raise RuntimeError(msg)
        return payload

    def _fetch_metadata_sync(self) -> dict[str, Any]:
        with httpx.Client(timeout=_DEFAULT_HTTP_TIMEOUT) as client:
            response = client.get(self._discovery_url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                msg = "OIDC discovery response is not a JSON object"
                raise RuntimeError(msg)
            return payload


class JwksSigningKeyProvider:
    """Resolve JWT signing keys via JWKS with refresh on unknown ``kid``."""

    def __init__(
        self,
        *,
        discovery: OidcDiscoveryClient,
        cache_ttl_seconds: int,
    ) -> None:
        self._discovery = discovery
        self._cache_ttl_seconds = cache_ttl_seconds
        self._client: PyJWKClient | None = None
        self._jwks_uri: str | None = None
        self._lock = asyncio.Lock()

    async def get_signing_key(self, token: str) -> Any:
        client = await self._get_client()
        try:
            return await asyncio.to_thread(client.get_signing_key_from_jwt, token)
        except Exception:
            await self._refresh_client()
            client = await self._get_client(force=True)
            return await asyncio.to_thread(client.get_signing_key_from_jwt, token)

    async def _get_client(self, *, force: bool = False) -> PyJWKClient:
        if not force and self._client is not None:
            return self._client
        async with self._lock:
            if not force and self._client is not None:
                return self._client
            jwks_uri = await self._discovery.get_jwks_uri()
            self._jwks_uri = jwks_uri
            self._client = PyJWKClient(
                jwks_uri,
                cache_keys=True,
                max_cached_keys=16,
                lifespan=self._cache_ttl_seconds,
            )
            return self._client

    async def _refresh_client(self) -> None:
        async with self._lock:
            if self._jwks_uri is None:
                self._client = None
                return
            self._client = PyJWKClient(
                self._jwks_uri,
                cache_keys=True,
                max_cached_keys=16,
                lifespan=0,
            )
