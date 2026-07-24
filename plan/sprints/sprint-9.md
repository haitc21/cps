# Sprint 9 — Internal network topology control

**Status:** Implementation complete; internal connectivity acceptance covered by tests  
**Dates:** 2026-07-24 to 2026-08-07  
**Capacity:** 58 combined points  
**Sprint Goal:** Create, reconcile, and remove an OpenStack network topology
that lets computers on the corporate LAN reach a VM.

**Canonical design:**
`docs/superpowers/specs/2026-07-24-openstack-resource-control-plane-expansion-design.md`

## Selected stories

| Story | Points | Owner | OPS dependency | Status |
|---|---:|---|---|---|
| CPS-901 Network inventory expansion | 13 | CPS | OPS-901 | Done |
| CPS-902 Network/subnet lifecycle | 8 | CPS | OPS-902 | Done |
| CPS-903 Router/interface lifecycle | 8 | CPS | OPS-903 | Done |
| CPS-904 Port/security lifecycle | 13 | CPS | OPS-904 | Done |
| CPS-905 Floating-IP lifecycle | 8 | CPS | OPS-905 | Done |
| CPS-906 Internal topology acceptance | 8 | CPS/OPS | OPS-901..905 | Accepted by automated tests; live pending |

## Delivery tasks

- [x] Confirm corporate-LAN connectivity as the primary acceptance target.
- [x] Define network operation contracts and ownership relationships.
- [x] Add typed network/security/floating-IP inventory and migrations.
- [x] Implement idempotent network/subnet/router/interface operations.
- [x] Implement port, security-group/rule, and floating-IP lifecycle.
- [x] Pin CPS contracts in OPS and validate checksums.
- [x] Add dependency, replay, partial-success, and cleanup tests.
- [ ] Run internal topology connectivity acceptance.
- [x] Run Definition of Done quality gates and update evidence.

## Acceptance

- A project-scoped connection can create a private network, subnet, port, security rules, and the required external/provider-network path.
- A VM returns a floating IP or provider-network IP reachable from a laptop on the corporate LAN.
- Router/interface operations preserve topology and recover from replay or partial relationship failure.
- External/shared/floating-IP operations are capability-gated and required for corporate-LAN access unless a provider network directly assigns a LAN address.
- Cleanup removes topology resources without deleting user-owned resources.

## Risks and impediments

| Risk/impediment | Owner | Mitigation | Status |
|---|---|---|---|
| Provider catalog endpoints are not routable from Compose | OPS | Internal acceptance uses reachable network endpoints; record public-IP limitation | Open |
| Existing tenant network policy differs by cloud | OPS | Use explicit network/security inputs and normalize policy errors | Open |
| Neutron relationship operations are eventually consistent | CPS/OPS | Idempotent ensure/remove and bounded retries | Open |

## Review evidence

- Demo scenario: create network/subnet/port/security resources, attach a VM, allocate/associate a floating or provider-network address, and connect from the corporate LAN.
- Test/migration commands and results: CPS `485 passed, 193 skipped`; OPS `358 passed, 24 skipped`; CPS DB integration `146 passed`; migration `20260724_0008` verified.
- Contract checksum: network requests map to the pinned generic resource-operation envelope.
- Internal connectivity result: private topology path is implemented; corporate-LAN reachability requires live floating/provider-network acceptance.
- Known limitations: the current live environment still needs a routable external network and security-group ingress validation.

## Retrospective actions

- Keep: explicit project ownership and idempotent relationship operations.
- Improve: live Neutron acceptance from the deployment network.
- One measurable action for next sprint: add a private-IP SSH smoke test after instance provisioning.
