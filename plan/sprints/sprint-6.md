# Sprint 6 — Design alignment and fast demo readiness

**Dates:** 2026-07-23 onward

**Sprint Goal:** Make the demo path accurately reflect the approved CPS/OPS
design while closing the highest-risk provider lifecycle and runtime gaps.

**Canonical implementation plan:**
`docs/superpowers/plans/2026-07-23-sprint-6-design-alignment-demo.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Demo blocker | Status |
|---|---:|---|---|---|---|
| OPS-601 Capability/version discovery | 8 | OPS | CPS contract pin | Yes | Done |
| OPS-602 Delete waiter/convergence | 5 | OPS | CPS operation events | Yes | Done |
| CPS-603 Production key-ring fail-fast | 3 | CPS | None | No | Done |
| OPS-603 Recursive mapper sanitization | 5 | OPS | CPS inventory contracts | No | Done |
| CPS-601 Demo runtime configuration | 3 | CPS + OPS | OPS internal URL | Yes | In progress |
| CPS-602/OPS-604 Immutable images | 5 | CPS + OPS | None | No | Done |

## Delivery gates

- [x] P0 tests and implementation complete.
- [x] Local Compose demo passes from the current checkout.
- [x] Capability/version result is persisted without raw catalog data.
- [x] Delete reaches `SUCCEEDED` only after provider disappearance.
- [x] No nested SDK objects cross the OPS contract boundary.
- [x] Production key-ring validation is tested independently from the local demo.
- [x] Image hardening is completed or explicitly carried over after the demo track.

## Current evidence

- OPS capability discovery now uses OpenStackSDK `CloudRegion` version data,
  reports microversion bounds where available, and exposes operation-level
  feature capability checks.
- OPS delete waits for provider `404`/deleted state before publishing the
  terminal deleted result; already-absent resources remain idempotent.
- CPS production settings reject missing or invalid credential key rings;
  development/test settings remain compatible with explicit synthetic keys.
- OPS inventory values are recursively reduced to bounded JSON primitives and
  drop secret-like nested fields.
- CPS and OPS images build from pinned base/uv digests, run as UID 999, and
  pass CLI smoke checks. Compose configuration validates successfully.
- CPS and OPS full suites, Ruff, mypy, contract validation, Docker builds, and
  image smoke checks pass.
- End-to-end local Compose/OpenStack validation reaches the live controller;
  identity mutations emit ordered progress and terminal events and cleanup is
  verified.
