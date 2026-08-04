# CPS-1203 TMS scope authorization integration plan

**Status:** Done — Luna final review approved with no findings (2026-08-04);
user waived Codex Security diff scan for completion
**Story:** CPS-1203 — Fail-closed resource authorization boundary
**Scope:** `cps/` and `deploy/` only. Do not read or modify TMS, LMS, BMS, or CMP Portal sources.

## Outcome

CPS authenticates every protected public request with Keycloak, applies the
shared CMP route rule, and validates member organization/workspace scope through
the deployed TMS API before entering a member handler. The configured
`APP_OWNER` remains authenticated but bypasses route-role and TMS authorization.

## Acceptance criteria

- `/api/v1/admin` and `/api/v1/admin/**` require the exact Keycloak client role
  `admin:admin` (the deployed `admin` alias remains compatible only where
  explicitly covered by the existing authentication contract).
- Other `/api/v1` routes require the Keycloak client role `member`.
- Non-owner member requests require non-empty `X-Org-ID` and `X-WS-ID` headers.
- CPS forwards the original bearer token only to TMS and never logs, persists,
  returns, or publishes it.
- CPS first checks the caller's organization role. `org:owner` authorizes the
  organization and its workspaces; otherwise CPS checks the caller's workspace
  role. A non-empty workspace role list establishes membership.
- Explicit deny/not-found returns `403`. Timeout, network failure, TMS 5xx, or
  malformed response returns `503`. No handler, operation, commit, or outbox
  action occurs after either failure.
- Bare environment variable `APP_OWNER` is matched against verified JWT email
  or preferred username, bypasses route-role and TMS checks, but never bypasses
  JWT authentication. Application code contains no owner identity default; an
  unset variable disables the bypass.
- Public health/metrics and the separate internal listener remain unchanged.

## Contract and compatibility decision

- No CPS public body, OpenAPI response, RabbitMQ, or OPS schema changes.
- Add request headers to the protected member API contract.
- Integrate against existing TMS reads:
  - `GET /organizations/{org_id}/members/{subject}/roles`
  - `GET /organizations/{org_id}/workspaces/{workspace_id}/members/{subject}/roles`
- TMS role responses are strict JSON objects containing `roles: list[str]`.
- This slice proves synchronous ingress authorization. Persisted authorization
  decisions and queued-decision expiry from the older design remain follow-up
  work and are not fabricated without a TMS decision endpoint.

## Exact files and interfaces

- `src/cps/config.py`: `APP_OWNER`, TMS base URL, connect/read timeout settings.
- `src/cps/security/auth/principal.py`: retain verified email and owner predicate.
- `src/cps/security/auth/roles.py`: preserve raw role distinction needed by the
  exact `admin:admin` route contract.
- `src/cps/security/auth/tms.py`: strict async TMS membership client and result.
- `src/cps/security/auth/middleware.py`: route role, scope header, owner bypass,
  and fail-closed TMS sequencing.
- `src/cps/contracts/errors.py`: stable authorization-authority unavailable error.
- `tests/unit/security/auth/`: RED/GREEN route, owner, scope, TMS failure, and
  secret-redaction coverage.
- `.env.example` and repository root `deploy/docker/docker-compose.yml`: local CPS
  configuration for full-stack auth/TMS verification. `cps/deploy/docker/` remains
  the CPS+OPS-only dependency stack without TMS/Keycloak.
- `docs/runbooks/`: redacted live verification evidence.

## Dependency and CodeGraph blast radius

- Existing callers: public `create_app`, every public API router, Keycloak JWT
  verifier, error envelope handler, and auth unit/integration tests.
- No OPS caller or canonical message contract changes.
- `httpx` is already pinned; no dependency or lockfile change.

## Threat/security scope

- Never trust a client-selected subject; use only verified JWT `sub`.
- Reject missing/blank/oversized scope headers before URL construction.
- URL-encode path segments and prevent base-URL/path injection.
- Never expose TMS bodies or bearer tokens in errors/logs.
- Do not allow cache/network/parser failures to become allow.
- Match `APP_OWNER` only after JWT verification using normalized exact identity.
- Do not apply public auth middleware to the internal credential listener.

## RED-GREEN-REFACTOR checklist

- [x] RED: owner with valid JWT and no CMP role reaches admin/member probes;
  observe current `403`.
- [x] RED: `admin:admin` reaches admin but not member; `member` reaches member but
  not admin; observe alias/policy gaps where applicable.
- [x] RED: member request without either scope header fails before handler.
- [x] RED: organization owner, workspace member, non-member, malformed TMS,
  timeout, 5xx, and token-redaction cases fail for the expected reason.
- [x] GREEN: add settings, principal identity fields, strict TMS client, stable
  errors, and middleware sequencing with minimum code.
- [x] REFACTOR: isolate route policy and TMS adapter without framework leakage.

## Verification commands

- [x] Focused: `rtk uv run pytest -q tests/unit/security/auth` → `33 passed`
- [x] Affected: `rtk uv run pytest -q tests/integration/test_keycloak_auth.py tests/unit/api/test_error_handlers.py` → `11 passed, 3 skipped`
- [x] Format/lint/type: `rtk uv run ruff check .` → pass; `rtk uv run mypy src` → pass (`137 files`)
- [x] Full: `rtk uv run pytest -q` → `671 passed, 182 skipped`
- [x] Diff/credential-sensitive: `rtk git diff --check` plus repository credential-sensitive scan.
- [x] Compose: validate config, rebuild/recreate CPS only, verify ready health.

## Live verification and cleanup

- [x] Obtain short-lived local tokens without printing or persisting them.
- [x] Verify APP_OWNER can call admin/member APIs without scope headers.
- [x] Verify `admin:admin` admin route allow and member route deny.
- [x] Verify member request missing headers denies.
- [x] Verify known organization owner and workspace member requests allow with
  `X-Org-ID` and `X-WS-ID`; wrong workspace denies.
- [x] Verify TMS outage path denies without stopping/deleting durable data.
- [x] Remove only task-created temporary files; no provider resource is created.

## Review and proposed commits

- [x] Independent specification/security review of the final diff — Luna
  approved with no findings (2026-08-04).
- [x] Codex Security diff scan waived by user for this completion.
- [x] Fix valid findings and rerun affected/full gates.
- [x] Write redacted runbook with commands, HTTP statuses, IDs, limitations, and
  review closure.
- [x] Proposed CPS commit: `feat(auth): enforce TMS organization workspace scope`
- [x] Proposed deploy commit boundary: include with owning deploy repository only
  if it is versioned and explicitly authorized.
- [x] Do not stage, commit, or push without explicit current-turn authorization.

## Luna review findings closure (2026-08-04)

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | High | `tms.py` returned `False` when org roles were empty instead of checking workspace membership | **Fixed.** Removed early deny; added `test_workspace_member_is_authorized_when_org_roles_are_empty`. |
| 2 | High | `cps/deploy/docker/docker-compose.yml` lacks `APP_OWNER` / `CPS_TMS_BASE_URL`; runbook `pause tms` unusable on CPS-only stack | **Valid, documented.** Canonical path for CPS-1203 is root `deploy/docker/docker-compose.yml` (already wired). CPS-only compose intentionally excludes TMS; README and runbook updated. No TMS service added to CPS-only compose. |
| 3 | Medium | `X-Org-ID` / `X-WS-ID` absent from OpenAPI | **Fixed.** Added reusable `document_member_scope_headers` dependency on all member routers; contract tests assert member paths declare both headers and admin paths do not. Headers remain optional in OpenAPI so APP_OWNER requests without headers are not rejected at the schema layer; middleware enforces fail-closed behavior for non-owner members. |
