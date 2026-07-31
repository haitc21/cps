# CPS-1704 — Tenant network guardrails

**Status:** Done
**Active backlog:** no
**Points:** 8
**Depends on:** CPS-902..905, CPS-1202, CPS-1203
**Paired task:** OPS-1704

## Outcome

Tenant network mutations stay within approved address, security, quota,
external-network, and project boundaries.

## Change set

- Validate CIDR overlap, allocation pools, gateway, DNS, project quotas, and
  allowed external networks.
- Add configurable security-rule policy for public CIDRs, protocols, and port
  ranges with explicit administrative exceptions.
- Recheck ownership and provider state in OPS immediately before mutation.

Guardrails now fail closed for administrator-only external network mutation,
malformed subnet CIDRs/gateways/allocation pools, public ingress security
rules, overlapping tenant subnets, exhausted network quotas, unapproved
external networks, and foreign relationship references. OPS independently
rechecks effective project ownership, parent-resource ownership, provider
network type, and current Neutron quota immediately before mutation.

## Required tests

- CIDR overlap and malformed allocation pool.
- Foreign network/subnet/port/router/security-group references.
- Unapproved external network and quota exhaustion.
- Public ingress policy allow/deny and bypass attempts.
- Duplicate relationship operations and direct provider drift.

## Done when

Unsafe requests publish no command and valid disposable topology still passes
end-to-end cleanup.

## Review evidence

- CPS contract tests cover CIDR, gateway, allocation pool, external-network
  mutation, public ingress, and port range bounds.
- CPS application tests cover overlap, cross-provider relationship,
  unapproved external-network, and exhausted-quota rejection before outbox
  publication.
- OPS tests cover provider-side ownership drift, quota recheck, public
  ingress/egress policy, malformed topology, and replay-safe relationships.
- Reviewer closed bypasses for noncanonical `/0` ingress CIDRs, mixed-family
  overlap checks, and provider-owned external-network references.
- Final quality gates: CPS 568 passed/181 skipped; OPS 453 passed/24 skipped;
  Ruff and MyPy pass in both repositories.
- Live negative requests for malformed CIDR, external-network mutation, and
  noncanonical public ingress each returned HTTP 422 without publishing.
- Live positive operations created network `de079b61-2d07-4612-9247-bddd6c3a84c9`,
  subnet `ec19fe56-27ed-487a-b39a-f4782928cbab`, and router
  `735ff018-1cbe-41ca-a1ff-39b6dc972c53` in the acceptance project.
  All three disposable resources were removed and OpenStack list verification
  returned zero residuals.
