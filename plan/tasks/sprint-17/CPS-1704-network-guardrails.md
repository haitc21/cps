# CPS-1704 — Tenant network guardrails

**Status:** Ready
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

## Required tests

- CIDR overlap and malformed allocation pool.
- Foreign network/subnet/port/router/security-group references.
- Unapproved external network and quota exhaustion.
- Public ingress policy allow/deny and bypass attempts.
- Duplicate relationship operations and direct provider drift.

## Done when

Unsafe requests publish no command and valid disposable topology still passes
end-to-end cleanup.

