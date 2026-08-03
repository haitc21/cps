# Sprint 19 image/flavor release acceptance

## Status matrix (2026-08-03)

| Area | Result | Evidence / limitation |
| --- | --- | --- |
| CPS/OPS-1901 contracts, pinning, catalog live comparison | PASS | CPS `8bcd4bd`, OPS `4a41308`; live inventory IDs/material fields matched; cleanup complete |
| CPS/OPS-1902 flavor CRUD/access/spec/replay | BLOCKED | Automated gates pass; live create reached OPS but stored CPS connection returned provider `403`; CLI-only disposable flavor was deleted and proved absent |
| CPS/OPS-1903 image metadata/member/state/delete | BLOCKED | Automated gates pass; import requires deployment-owned HTTPS allowlist and no lab source is configured |
| CPS/OPS-1904 snapshot/consumer compatibility | BLOCKED | Automated gates pass; live flow depends on 1902 auth and 1903 source prerequisites; standalone volume-from-image API is not present in this codebase |
| CPS/OPS-1905 release matrix | BLOCKED | Live mutation, replay, failure-injection, and reverse-dependency cleanup matrix incomplete |

## Pushed task commits

- CPS: `8bcd4bd`, `688fdda`, `f207c0f`, `a40d367`, `85e9282`.
- OPS: `4a41308`, `2f7b427`, `11abe64`, `8d61afc`.

All listed commits were pushed to `main`; worktrees were clean at each push.

## Automated gates

- CPS full counts: 626/182 skipped (1901), 632/182 (1902), 642/182 (1903),
  649/182 (1904); Ruff, mypy, contracts, diff check, and staged secret scan
  passed, with only pre-existing warnings.
- OPS full counts: 459/24 skipped (1901), 464/24 (1902), 468/24 (1903),
  471/24 (1904); same gates passed with the existing Starlette warning.

## Required unblock and live sequence

1. Correct the dev CPS provider connection's stored scope/credential and
   revalidate it; do not print or commit credentials.
2. Configure a non-secret HTTPS image source in the deployment-owned allowlist;
   never bypass SSRF policy or use signed/private URLs.
3. Execute flavor CRUD/access/spec, image lifecycle/import, then disposable
   instance snapshot/consume in dependency order. Poll every CPS operation to a
   terminal state and compare provider IDs/material fields with OpenStack CLI.
4. Delete in reverse dependency order and prove CLI absence plus CPS refresh /
   reconciliation. Record negative/replay/restart/late-result evidence.

No credentials, tokens, authorization headers, signed URLs, raw provider
bodies, image bytes, user data, or private keys are stored here.
