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
| CPS-1701 Instance resize and rebuild | 13 | CPS | OPS-1701 | Needs refinement |
| CPS-1702 Instance console access | 5 | CPS | OPS-1702 | Needs threat review |
| CPS-1703 Admin-curated resource catalog policy | 8 | CPS | OPS-1703 | In progress — tag policy selected |
| CPS-1704 Tenant network guardrails | 8 | CPS | OPS-1704 | Ready |

## Task backlog

| Task | Deliverable | Depends on | Status |
|---|---|---|---|
| [CPS-1701](../tasks/sprint-17/CPS-1701-instance-resize-rebuild.md) | Resize confirm/revert and policy-safe rebuild | CPS-403, CPS-1203 | Needs refinement |
| [CPS-1702](../tasks/sprint-17/CPS-1702-instance-console.md) | Ephemeral capability-gated console access | CPS-403, CPS-1203 | Needs threat review |
| [CPS-1703](../tasks/sprint-17/CPS-1703-curated-catalog-policy.md) | Approved image/flavor/AZ/volume-type/external-network selection | CPS-304, CPS-1203 | In progress |
| [CPS-1704](../tasks/sprint-17/CPS-1704-network-guardrails.md) | CIDR, external-network, rule, quota, and ownership policy | CPS-902..905, CPS-1203 | Ready |

## Execution sequence

1. Approve console secret handling and curated-catalog policy.
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
| Console URL behaves like a bearer secret | CPS/OPS | Non-durable response port, TTL, redaction, threat review | Open |
| Resize needs user confirmation | CPS/OPS | Explicit confirm/revert state machine and timeout policy | Open |
| Admin catalog policy source is undefined | Product/CPS | Approve metadata/tag/DB allow-list source before coding | Open |

## Review evidence

- Policy/design approval: provider metadata/tag convention selected;
  `cmp-catalog-approved=true` is the admin marker.
- Resize/rebuild recovery:
- Console redaction:
- Real-cloud acceptance:
