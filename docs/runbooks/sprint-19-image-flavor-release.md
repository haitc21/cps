# Sprint 19 image/flavor release acceptance

## Status matrix (2026-08-03)

| Area | Result | Evidence / limitation |
| --- | --- | --- |
| CPS/OPS-1901 contracts, pinning, catalog live comparison | PASS | CPS `8bcd4bd`, OPS `4a41308`; live inventory IDs/material fields matched; cleanup complete |
| CPS/OPS-1902 flavor CRUD/access/spec/replay | PASS | Project-scoped live create `7e8c097f-2ac3-5c27-8788-a9bde6329efa` returned provider `61789723-813f-4b46-9ae4-7c863afde7f4`; CLI fields matched (1 vCPU/512 MiB/1 GiB), cleanup verified |
| CPS/OPS-1903 image metadata/member/state/delete | PASS | Self-signed HTTPS import `6c4dfe18-c718-55ad-9dad-c0ffad35ba34` returned provider `d31f7c8f-d0ca-496e-a214-a0d80094b683`; CLI showed active qcow2/private/bare, cleanup verified |
| CPS/OPS-1904 snapshot/consumer compatibility | BLOCKED | Automated gates pass; live flow depends on 1902 auth and 1903 source prerequisites; standalone volume-from-image API is not present in this codebase |
| CPS/OPS-1905 release matrix | BLOCKED | 1904 snapshot/consumer and full replay/failure-injection matrix remain incomplete |

## Pushed task commits

- CPS: `8bcd4bd`, `688fdda`, `f207c0f`, `a40d367`, `85e9282`.
- OPS: `4a41308`, `2f7b427`, `11abe64`, `8d61afc`.
- OPS live-lab SSRF exception: `204dc26` (explicit, allowlisted private HTTPS fixture only in development).

All listed commits were pushed to `main`; worktrees were clean at each push.

## Automated gates

- CPS full counts: 626/182 skipped (1901), 632/182 (1902), 642/182 (1903),
  649/182 (1904); Ruff, mypy, contracts, diff check, and staged secret scan
  passed, with only pre-existing warnings.
- OPS full counts: 459/24 skipped (1901), 464/24 (1902), 468/24 (1903),
  471/24 (1904); same gates passed with the existing Starlette warning.

## Required unblock and live sequence

1. Keep the project-scoped `admin` connection validated for image/flavor
   mutations; the system-scoped connection remains unsuitable for Glance
   flavor/image policy in this lab.
2. The deployment-owned allowlist now uses `controller-test` with a two-day
   self-signed certificate. `OPS_IMAGE_IMPORT_ALLOW_PRIVATE_HOSTS=true` is a
   development-only exception gated by that allowlist; production remains
   public-address/CA enforced.
3. Execute flavor CRUD/access/spec, image lifecycle/import, then disposable
   instance snapshot/consume in dependency order. Poll every CPS operation to a
   terminal state and compare provider IDs/material fields with OpenStack CLI.
4. Delete in reverse dependency order and prove CLI absence plus CPS refresh /
   reconciliation. Record negative/replay/restart/late-result evidence.

No credentials, tokens, authorization headers, signed URLs, raw provider
bodies, image bytes, user data, or private keys are stored here.
