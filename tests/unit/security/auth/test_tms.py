"""Strict TMS organization/workspace membership adapter tests."""

from __future__ import annotations

import httpx
import pytest

from cps.security.auth.tms import HttpTmsMembershipAuthorizer, TmsAuthorizationUnavailable


@pytest.mark.asyncio
async def test_org_owner_is_authorized_without_workspace_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"roles": ["org:owner"]})

    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013",
        transport=httpx.MockTransport(handler),
    )

    allowed = await authorizer.authorize(
        bearer_token="synthetic-token",
        subject="user-1",
        org_id="org-1",
        workspace_id="ws-1",
    )

    assert allowed is True
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer synthetic-token"


@pytest.mark.asyncio
async def test_workspace_member_is_authorized_after_org_membership_lookup() -> None:
    paths: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path)
        if b"/workspaces/" in request.url.raw_path:
            return httpx.Response(200, json={"roles": ["ws:member:read"]})
        return httpx.Response(200, json={"roles": ["org:member:read"]})

    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013/",
        transport=httpx.MockTransport(handler),
    )

    allowed = await authorizer.authorize(
        bearer_token="synthetic-token",
        subject="user/with-path-chars",
        org_id="org/with-path-chars",
        workspace_id="ws/with-path-chars",
    )

    assert allowed is True
    assert len(paths) == 2
    assert b"%2F" in paths[0]
    assert b"%2F" in paths[1]


@pytest.mark.asyncio
async def test_workspace_member_is_authorized_when_org_roles_are_empty() -> None:
    paths: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path)
        if b"/workspaces/" in request.url.raw_path:
            return httpx.Response(200, json={"roles": ["ws:member:read"]})
        return httpx.Response(200, json={"roles": []})

    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013",
        transport=httpx.MockTransport(handler),
    )

    allowed = await authorizer.authorize(
        bearer_token="synthetic-token",
        subject="user-1",
        org_id="org-1",
        workspace_id="ws-1",
    )

    assert allowed is True
    assert len(paths) == 2


@pytest.mark.asyncio
async def test_not_found_or_empty_roles_denies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/workspaces/" in request.url.path:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json={"roles": ["org:member:read"]})

    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013",
        transport=httpx.MockTransport(handler),
    )

    assert (
        await authorizer.authorize(
            bearer_token="synthetic-token",
            subject="user-1",
            org_id="org-1",
            workspace_id="ws-1",
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, json={"roles": "bad"})],
)
async def test_upstream_failure_or_malformed_response_is_unavailable(
    response: httpx.Response,
) -> None:
    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013",
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(TmsAuthorizationUnavailable):
        await authorizer.authorize(
            bearer_token="synthetic-token",
            subject="user-1",
            org_id="org-1",
            workspace_id="ws-1",
        )


@pytest.mark.asyncio
async def test_timeout_is_unavailable_without_exposing_token() -> None:
    secret = "synthetic-secret-token"  # pragma: allowlist secret

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    authorizer = HttpTmsMembershipAuthorizer(
        base_url="http://tms:3013",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TmsAuthorizationUnavailable) as raised:
        await authorizer.authorize(
            bearer_token=secret,
            subject="user-1",
            org_id="org-1",
            workspace_id="ws-1",
        )

    assert secret not in str(raised.value)
