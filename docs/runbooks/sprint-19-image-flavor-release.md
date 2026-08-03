# Sprint 19 image/flavor release acceptance

## Status matrix (2026-08-03)

| Area | Result | Evidence / limitation |
| --- | --- | --- |
| CPS/OPS-1901 contracts, pinning, catalog live comparison | PASS | CPS `8bcd4bd`, OPS `4a41308`; live inventory IDs/material fields matched; cleanup complete |
| CPS/OPS-1902 flavor CRUD/access/spec/replay | PASS | Project-scoped live create `7e8c097f-2ac3-5c27-8788-a9bde6329efa` returned provider `61789723-813f-4b46-9ae4-7c863afde7f4`; CLI fields matched (1 vCPU/512 MiB/1 GiB), cleanup verified |
| CPS/OPS-1903 image metadata/member/state/delete | PASS | Self-signed HTTPS import `6c4dfe18-c718-55ad-9dad-c0ffad35ba34` returned provider `d31f7c8f-d0ca-496e-a214-a0d80094b683`; CLI showed active qcow2/private/bare, cleanup verified |
| CPS/OPS-1904 snapshot/consumer compatibility | PASS | Instance `d7ea87a6-492e-49f5-8e82-6459116ab60f`, snapshot operation `71b28f7e-13d8-50d0-95b2-100148ff3f7c` → image `5ab875bd-27c8-4c59-9923-18280f7c5e06`; second CPS instance launched from snapshot; all disposable resources absent after cleanup |
| CPS/OPS-1905 release matrix | PASS WITH WAIVER | Replay key `cmp-s19-replay-delete-1905` returned the same operation `d1b44197-a851-50e0-93c0-4d64bd36daaa`; invalid HTTP import returned 400 without provider mutation; cleanup and provider absence verified. Worker restart/failure-injection path explicitly waived for this dev sprint. |

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

## Explicit waiver

The controlled worker-restart, provider-failure, retry, and late-result
scenarios are waived by the sprint owner for this development run. They remain
recommended before production release and are not represented as passing live
evidence.
