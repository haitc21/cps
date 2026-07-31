# Sprint 17 — Advanced VM lifecycle and governed catalogs

**Status:** In progress
**Dates:** TBD at Sprint Planning
**Capacity:** 34 CPS points
**Sprint Goal:** CMP users can operate VMs beyond basic power actions while
selecting only administrator-approved catalog and external-network resources.

**Plan:** `../../docs/superpowers/plans/2026-07-27-cmp-user-resource-completion.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-1701 Instance resize and rebuild | 13 | CPS | OPS-1701 | Done |
| CPS-1702 Instance console access | 5 | CPS | OPS-1702 | Deferred — chưa ưu tiên |
| CPS-1703 Admin-curated resource catalog policy | 8 | CPS | OPS-1703 | Done |
| CPS-1704 Tenant network guardrails | 8 | CPS | OPS-1704 | Done |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1701](../tasks/sprint-17/CPS-1701-instance-resize-rebuild.md) | Resize confirm/revert and policy-safe rebuild | CPS-403, CPS-1203 | Done |
| [CPS-1702](../tasks/sprint-17/CPS-1702-instance-console.md) | Ephemeral capability-gated console access | CPS-403, CPS-1203 | Deferred — chưa ưu tiên |
| [CPS-1703](../tasks/sprint-17/CPS-1703-curated-catalog-policy.md) | Approved image/flavor/AZ/volume-type/external-network selection | CPS-304, CPS-1203 | Done |
| [CPS-1704](../tasks/sprint-17/CPS-1704-network-guardrails.md) | CIDR, external-network, rule, quota, and ownership policy | CPS-902..905, CPS-1203 | Done |

## Execution sequence

1. Record console access as deferred and approve curated-catalog policy.
2. Deliver catalog filtering and reference validation before VM changes.
3. Implement resize with confirm/revert recovery.
4. Implement rebuild using approved images and existing storage/network policy.
5. Add ephemeral console response boundary and network guardrails.
6. Run cross-workspace and real-cloud scenarios.

## Acceptance

- No CMP user endpoint mutates Glance public images, flavors, AZs, volume
  types, or external/provider networks.
- CPS stores provider IDs from inventory and never hardcodes cloud UUIDs.
- Resize/rebuild publish no command until ownership/catalog policy allows it.
- Console URLs/tokens are short-lived and absent from durable operation data.
- Unsafe CIDR, security rules, quotas, and cross-project references fail closed.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Console URL behaves like a bearer secret | CPS/OPS | Deferred; require non-durable response port, TTL, redaction, and threat review before activation | Deferred |
| Resize needs user confirmation | CPS/OPS | Explicit confirm/revert state machine and timeout policy | Resolved |
| Admin catalog policy source is undefined | Product/CPS | Provider metadata/tag convention implemented; Nova AZ approval maps host-aggregate metadata | Resolved |

## Review evidence

- Policy/design approval: provider metadata/tag convention selected;
  `cmp-catalog-approved=true` is the admin marker.
- Curated catalogs: typed image, flavor, network, volume-type, and
  availability-zone inventory and fail-closed consumer validation pass full
  CPS/OPS quality gates.
- Network guardrails: deterministic CPS/OPS tests and live negative/positive
  topology acceptance cover malformed and overlapping CIDRs, external-network
  policy, security bounds, quota exhaustion, ownership/provider drift, and
  zero-residual cleanup.
- Resize/rebuild recovery: CPS/OPS full tests plus live resize, revert, rebuild,
  final confirm, SSH verification, and zero-residual disposable-flavor cleanup.
- Console redaction:
- Real-cloud acceptance:
