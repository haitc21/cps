# CPS-1803 — OpenStack lab instance access follow-ups (E2E / SSH)

**Status:** Open — deferred after lab E2E session 2026-07-28
**Points:** TBD
**Paired task:** OPS-1803
**Lab context:** `deploy/docker/docker-compose.openstack-lab.yml`, domain `hanoi`,
project `ttcntt-cloud`, instance `dev-cmp`, provider external net `192.168.0.0/24`,
laptop on `br-home` (`192.168.0.102`)

## Outcome

A CMP operator can create `dev-cmp` end-to-end and SSH from the physical laptop
to the instance floating IP without manual OpenStack CLI recovery on controller
or compute.

Reference flow: `cps/docs/instance-provisioning.md` (router + FIP or
`floating_network_provider_resource_id` at create time).

## Issues to fix

### CPS / API

| ID | Issue | Evidence | Owner | Priority |
|---|---|---|---|---|
| L1 | **Floating IP associate fails** via CPS network op — `PROVIDER_INTERNAL_ERROR`, `provider_service: identity` | Associate after allocate succeeded on OpenStack only with `openstack floating ip set --port` | CPS/OPS | P0 |
| L2 | **E2E script incomplete** — create instance without router/FIP reports success but laptop cannot SSH | User expectation: usable VM, not just Nova ACTIVE | CPS | P0 |
| L3 | **Project connection domain** — must use `project_domain_name=hanoi`; `Default` → Keystone 401, downstream network/volume fail | E2E log; connection `019fa7a7-dc82-796d-949f-f5c862f64e30` | CPS | P1 |
| L4 | **Instance create + FIP in one request** — document and E2E-test `floating_network_provider_resource_id` so OPS allocates+associates at create (avoid separate associate op) | `instance-provisioning.md` § CPS flow step 4 | CPS | P1 |
| L5 | **Glance sync scope** — SYSTEM connection gets 403; image inventory sync works on PROJECT connection only | E2E catalog/inventory session | CPS/OPS | P2 |

### OPS (uncommitted code + handler bugs)

| ID | Issue | Evidence | Owner | Priority |
|---|---|---|---|---|
| O1 | **Inventory flavor `catalog_approved`** — `flavor.extra_specs.cmp-catalog-approved` not mapped until fix in `inventory.py` | CPS-1703; fix local, not committed | OPS | P1 |
| O2 | **Instance create SG format** — Nova expects `[{"name": "..."}]`, not raw UUID; fix in `instance_create.py` | E2E create failed before fix | OPS | P1 |
| O3 | **FIP associate error service mapping** — `normalize_openstack_exception` may label network failures as `identity` when resource_type is not volume | Failed associate event showed `provider_service: identity` | OPS | P1 |
| O4 | **Verify associate payload** — CPS sends `port_provider_resource_id` → OPS `port_id`; confirm end-to-end against Neutron for post-create associate | Associate handler in `resource_operations.py` | OPS | P0 |

### OpenStack lab / hypervisor (compute01)

| ID | Issue | Evidence | Owner | Priority |
|---|---|---|---|---|
| H1 | **Nova creates `domain type=qemu` + `-accel tcg`** despite `[libvirt] virt_type=kvm` — VM crashes immediately (`qemu_mutex_lock_iothread_impl`) on nested compute01 | QEMU logs `instance-0000003d.log`; manual `type=kvm` + `virsh start` worked | Lab/OPS | P0 |
| H2 | **`nova.conf` libvirt options misplaced** — `cpu_mode`/`cpu_model` were under `[DEFAULT]`, ignored; must live under `[libvirt]` on compute | compute01 `/etc/nova/nova.conf` inspection | Lab | P1 |
| H3 | **Placement / nova desync** — ghost instances, `vcpus_used` > capacity, `DELETE FROM allocations` needed; BUILD stuck at `spawning` / `Creating image(s)` | Scheduler `NoValidHost`; hypervisor stats stale | Lab | P1 |
| H4 | **Power state desync** — OpenStack ACTIVE/SHUTOFF vs libvirt shut off / crashed; manual `virsh start` triggers nova stop loop | nova-compute logs during debug | Lab | P1 |
| H5 | **Cinder volume stuck `detaching`** — blocks rebuild; needed `openstack volume set --state available` | rebuild dev-cmp session | Lab | P2 |
| H6 | **Temporary libvirt hook** — `/etc/libvirt/hooks/qemu` forces `qemu`→`kvm` on prepare; not a durable product fix | Installed on compute01 during debug | Lab/OPS | P1 |

### Network / acceptance criteria

| ID | Issue | Evidence | Owner | Priority |
|---|---|---|---|---|
| N1 | **L2 path laptop → FIP is OK** when VM runs — `ping 192.168.0.241` (router) succeeds from laptop; FIP `192.168.0.249` fails only when VM/port down | `provider-net` → `br-home` | — | Verified |
| N2 | **SG ingress** — TCP/22 from `192.168.0.0/24` on `ttcntt-default-sg` required for laptop SSH | Rule added manually in E2E | CPS E2E | P1 |
| N3 | **Acceptance definition** — “instance ACTIVE” is insufficient; release check must include **reachable SSH** (or explicit `access.ssh.host` from CPS) | User feedback in E2E session | CPS | P0 |

## Temporary workarounds applied in lab (do not treat as done)

- Router `ttcntt-router` + external gateway + subnet interface — OpenStack CLI/API
- FIP `6fecb693-b686-4cb8-b396-28d6944e1335` / `192.168.0.249` — associate via CLI
- `[libvirt]` block + `vnc_enabled=false` on compute01 nova.conf
- Libvirt hook `/etc/libvirt/hooks/qemu` on compute01
- Placement `DELETE FROM allocations` when scheduler blocked

## Follow-up tasks

1. **OPS:** Commit and test inventory + instance_create fixes; add unit tests already written.
2. **OPS:** Debug and fix FIP associate command path (O3, O4); add integration test.
3. **OPS/Lab:** Root-cause why Nova/libvirt selects `tcg` on nested compute; permanent fix (H1, H2) — prefer config over hook.
4. **CPS:** Extend E2E script: domain → project → net → **router** → SG rule :22 → instance (with `floating_network_provider_resource_id`) → verify `access.ssh.host` → curl/SSH check.
5. **CPS:** Fix or document project connection template for multi-domain Keystone (`hanoi`).
6. **Lab runbook:** Cleanup procedure for ghost instances, placement allocations, and compute01 nova-compute restart (H3, H4).
7. **CPS-1802 gate:** Add “laptop SSH to FIP” (or documented jump-less equivalent) to disposable real-cloud / lab acceptance checklist (N3).

## Done when

- [ ] CPS API associate FIP to existing instance port succeeds without CLI.
- [ ] E2E lab script completes with router + FIP (or create-time FIP) and SSH from laptop succeeds.
- [ ] No manual libvirt hook required on compute after fresh instance create.
- [ ] OPS fixes for catalog SG/inventory committed with tests green.
- [ ] Runbook documents lab recovery for BUILD hang, placement desync, and volume detaching.

## References

- E2E log: `/tmp/cmp-ec2-e2e-20260728143640.log`
- Instance IDs observed during debug: multiple `dev-cmp` recreates; last in-flight `6fe007c0-af4d-4d11-852d-e6fda81c8a97` (BUILD)
- FIP: `6fecb693-b686-4cb8-b396-28d6944e1335` → `192.168.0.249`
- Catalog policy: `cps/plan/tasks/sprint-17/CPS-1703-curated-catalog-policy.md`
