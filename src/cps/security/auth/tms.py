"""Fail-closed TMS organization/workspace membership adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class TmsAuthorizationUnavailable(RuntimeError):
    """TMS could not produce a trustworthy membership response."""

    def __init__(self) -> None:
        super().__init__("TMS authorization unavailable")


class HttpTmsMembershipAuthorizer:
    """Authorize a verified subject against its TMS organization/workspace roles."""

    def __init__(
        self,
        *,
        base_url: str,
        connect_timeout_seconds: float = 1.0,
        read_timeout_seconds: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._transport = transport

    async def authorize(
        self,
        *,
        bearer_token: str,
        subject: str,
        org_id: str,
        workspace_id: str,
    ) -> bool:
        encoded_org = quote(org_id, safe="")
        encoded_workspace = quote(workspace_id, safe="")
        encoded_subject = quote(subject, safe="")
        headers = {"Authorization": f"Bearer {bearer_token}"}

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            org_roles = await self._get_roles(
                client,
                f"/organizations/{encoded_org}/members/{encoded_subject}/roles",
                headers,
            )
            if org_roles is None:
                return False
            if "org:owner" in org_roles:
                return True

            workspace_roles = await self._get_roles(
                client,
                (
                    f"/organizations/{encoded_org}/workspaces/{encoded_workspace}"
                    f"/members/{encoded_subject}/roles"
                ),
                headers,
            )
            return bool(workspace_roles)

    async def _get_roles(
        self,
        client: httpx.AsyncClient,
        path: str,
        headers: dict[str, str],
    ) -> frozenset[str] | None:
        try:
            response = await client.get(path, headers=headers)
        except httpx.HTTPError as exc:
            raise TmsAuthorizationUnavailable from exc

        if response.status_code in {401, 403, 404}:
            return None
        if response.status_code != 200:
            raise TmsAuthorizationUnavailable

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise TmsAuthorizationUnavailable from exc
        if not isinstance(body, dict):
            raise TmsAuthorizationUnavailable
        roles = body.get("roles")
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise TmsAuthorizationUnavailable
        return frozenset(roles)
