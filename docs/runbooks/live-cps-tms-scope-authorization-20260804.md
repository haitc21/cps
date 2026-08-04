# Live CPS TMS scope authorization — CPS-1203

Date: 2026-08-04 (UTC+7)

## Scope

Ingress-only authorization for CPS public API: Keycloak JWT authentication,
exact client-role route policy, optional `APP_OWNER` bypass, and synchronous
TMS organization/workspace membership checks via `X-Org-ID` / `X-WS-ID`.

No provider resources were created or mutated. Tokens were obtained locally and
were not written to this runbook.

## Environment

Canonical compose for CPS-1203 live verification: repository root
`deploy/docker/docker-compose.yml` (includes Keycloak, TMS, and the shared
`x-cps-environment` block with `APP_OWNER` / `CPS_TMS_BASE_URL`). The CPS-only
stack at `cps/deploy/docker/docker-compose.yml` does not include TMS and must
not be used for TMS outage or scope-header live checks.

| Component | URL |
|---|---|
| CPS public | http://127.0.0.1:8000 |
| CPS internal | http://127.0.0.1:8002 |
| TMS | http://127.0.0.1:3013 |
| Keycloak realm | `vnpost` / client `cmp` |

Scope headers for member-route live checks (environment-specific; obtain from TMS):

```bash
export CPS_TEST_SCOPE_ORG_ID='<org_id>'
export CPS_TEST_SCOPE_WS_ID='<workspace_id>'
```

Unit tests use deterministic synthetic ObjectIds from the authorization design
(`64b000000000000000000001` / `64b000000000000000000101`). Integration tests
require the env vars above and skip when unset.

## Automated gates (2026-08-04 completion)

```text
rtk uv run pytest -q tests/unit/security/auth
  -> 33 passed
rtk uv run pytest -q tests/integration/test_keycloak_auth.py tests/unit/api/test_error_handlers.py
  -> 11 passed, 3 skipped
rtk uv run ruff check .          -> pass
rtk uv run mypy src              -> pass (137 files)
rtk uv run pytest -q             -> 671 passed, 182 skipped
rtk git diff --check             -> pass
deploy/docker compose config -q  -> pass (root `deploy/docker/docker-compose.yml`)
cps/deploy/docker compose config -q -> pass (CPS+OPS-only stack; no TMS)
```

Focused auth suite covers TMS adapter empty-org-role regression, middleware
route/owner/scope policy, and token redaction. OpenAPI contract tests in
`tests/unit/api/test_route_normalization.py` verify member scope headers.

## Live verification

CPS image rebuilt with `docker compose up -d --build --force-recreate cps`.

### Public paths unchanged

| Request | HTTP |
|---|---|
| `GET /health/live` | 200 |
| `GET /metrics` | 200 |
| `GET /api/v1/operations` (no auth) | 401 `UNAUTHORIZED` |
| `GET http://127.0.0.1:8002/health/live` | 200 |

### APP_OWNER bypass (`APP_OWNER=admin@vnpost.vn`)

| Request | HTTP | Notes |
|---|---|---|
| `GET /api/v1/admin/providers` | 200 | no scope headers |
| `GET /api/v1/operations` | 200 | no scope headers, TMS not called |

### Exact role policy (`APP_OWNER` unset)

Local Keycloak JWT client roles for `admin@vnpost.vn`: `admin`, `member`
(not `admin:admin`).

| Request | HTTP | Notes |
|---|---|---|
| `GET /api/v1/admin/providers` | 403 `FORBIDDEN` | legacy `admin` alias does not satisfy admin route policy |
| `GET /api/v1/operations` (no scope) | 403 `FORBIDDEN` | member role present but scope headers required |

### Member scope and TMS (`APP_OWNER` unset)

| Request | HTTP | Notes |
|---|---|---|
| `GET /api/v1/operations` member token, no headers | 403 `FORBIDDEN` |
| `GET /api/v1/operations` + valid `X-Org-ID` / `X-WS-ID` | 200 | TMS membership allow |
| `GET /api/v1/operations` + wrong workspace id | 403 `FORBIDDEN` |

### TMS outage (fail-closed)

TMS container paused (`docker compose pause tms`):

| Request | HTTP | Notes |
|---|---|---|
| Scoped member `GET /api/v1/operations` | 503 | handler not reached; no durable mutation |

TMS unpaused; same request returned 200 again.

## Limitations

- Local Keycloak issues `admin` / `member` client roles, not `admin:admin`.
  Admin-route allow for non-owner principals requires Keycloak role alignment
  or `APP_OWNER` bypass.
- Public API envelope maps `AUTHORIZATION_SERVICE_UNAVAILABLE` to
  `errorCode=INTERNAL_ERROR` while preserving HTTP 503 (no new public error
  code in this slice).
- Persisted authorization decisions and queued-decision expiry remain follow-up
  work (CPS-1203 ingress slice only).

## Review / security

- Independent Luna specification review: **approved 2026-08-04 with no findings**
  (see plan findings closure table)
- Codex Security diff scan: **waived by user for this completion**
- CPS-1906: TMS integration dependency closed by this ingress slice; separate
  OpenStack scope-policy work for CPS-1906 remains open and CPS-1906 is not
  marked Done

## Proposed commit message

`feat(auth): enforce TMS organization workspace scope`
