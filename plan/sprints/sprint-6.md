# Sprint 6 — Design alignment and fast demo readiness

**Dates:** 2026-07-23 onward

**Sprint Goal:** Make the demo path accurately reflect the approved CPS/OPS
design while closing the highest-risk provider lifecycle and runtime gaps.

**Canonical implementation plan:**
`docs/superpowers/plans/2026-07-23-sprint-6-design-alignment-demo.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Demo blocker | Status |
|---|---:|---|---|---|---|
| OPS-601 Capability/version discovery | 8 | OPS | CPS contract pin | Yes | Ready |
| OPS-602 Delete waiter/convergence | 5 | OPS | CPS operation events | Yes | Ready |
| CPS-603 Production key-ring fail-fast | 3 | CPS | None | No | Ready |
| OPS-603 Recursive mapper sanitization | 5 | OPS | CPS inventory contracts | No | Ready |
| CPS-601 Demo runtime configuration | 3 | CPS + OPS | OPS internal URL | Yes | Ready |
| CPS-602/OPS-604 Immutable images | 5 | CPS + OPS | None | No | Ready |

## Delivery gates

- [ ] P0 tests and implementation complete.
- [ ] Local Compose demo passes from a clean checkout.
- [ ] Capability/version result is persisted without raw catalog data.
- [ ] Delete reaches `SUCCEEDED` only after provider disappearance.
- [ ] No nested SDK objects cross the OPS contract boundary.
- [ ] Production key-ring validation is tested independently from the local demo.
- [ ] Image hardening is completed or explicitly carried over after the demo track.
