# Sprint 18 release runbook

## Scope

This runbook covers the CMP user-resource release path: inventory, instance,
network, volume, snapshot, attachment, keypair, catalog policy, and cleanup.
Console access is superseded and TMS is not part of the release gate.
Multi-compute placement and recovery are part of the lab gate when a second
compute is available. Physical-provider-network routing remains observational.

Lab E2E script: `deploy/scripts/sprint-18-openstack-lab-e2e.sh`

## Preflight

1. Confirm the CPS and OPS worktrees are clean and the deployed images identify
   the intended commit.
2. Confirm `GET /health/live` and `GET /health/ready` return success for CPS
   and OPS.
3. Confirm both workers consume their queues and no unexpected DLQ messages
   exist.
4. Record the OpenStack service/capability report before creating resources.

## Quality gates

Run from each worktree (`cps/`, `ops/`):

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
```

Contract checksum parity:

```bash
# CPS and OPS contract fixtures must match pinned checksum in sprint evidence.
uv run pytest tests/contract -q
```

Secret scan and Compose smoke (release environment):

```bash
docker compose -f deploy/docker/docker-compose.yml \
  -f deploy/docker/docker-compose.openstack-lab.yml ps
curl -fsS http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:8001/health/ready
```

## Recovery matrix

For each disposable resource prefix (`cmp180-`), exercise the operation in
these cases:

| Case | Expected |
|---|---|
| Duplicate request before provider mutation | Same operation id; single outbox draft |
| Duplicate request after provider mutation | Same terminal state; no duplicate resource |
| CPS/OPS restart while command in flight | Converges to single terminal state |
| Provider timeout and late terminal result | Deterministic timeout or late success |
| Terminal event redelivery | Idempotent inbox apply |
| Direct provider update/delete + inventory refresh | Drift observed; no unsafe inferred delete |
| Dependency-ordered delete + second idempotent delete | ALREADY_ABSENT or SUCCEEDED |

Automated evidence: `cps/tests/unit/application/test_sprint18_recovery_matrix.py`,
`cps/tests/integration/messaging/test_ack_policy.py`,
`cps/tests/integration/messaging/test_outbox_crash_recovery.py`.

## Migration gate

Run the migration image against a disposable PostgreSQL database. Verify the
empty-schema upgrade, current-head restart, and rollback rehearsal before
touching a release database. Never run migration rollback against production
without an approved backup and change window.

For the local Compose PostgreSQL fixture:

```bash
CPS_RUN_INTEGRATION=1 \
CPS_TEST_DATABASE_URL='postgresql+psycopg://cmp:<password>@127.0.0.1:5432/cps_test' \
uv run pytest tests/integration/db/test_migration_lifecycle.py -q
```

## Release scenario (9 steps)

Use disposable prefix `cmp180-` on OpenStack lab or real cloud:

1. **Capability report** — record Nova/Neutron/Cinder/Keystone versions.
2. **Domain + project** — create or bind tenant scope with correct Keystone domain.
3. **Network topology** — tenant network, subnet, router, external gateway, interface.
4. **Security** — default SG + ingress TCP/22 from operator subnet.
5. **Catalog** — sync inventory; verify approved image/flavor only.
6. **Instance** — create with private network + `floating_network_provider_resource_id`
   (or allocate/associate FIP post-create).
7. **Storage** — volume create, attach, detach; snapshot optional.
8. **Optional network observation** — when the operator network is in scope,
   verify `access.ssh.host` is reachable. SSH transport and physical network
   routing do not block the software release.
9. **Cleanup ledger** — dependency-ordered delete; verify zero residual on OpenStack and CPS inventory.

## Cleanup ledger

Record every provider ID as it is created. Delete in dependency order:

1. floating-IP associations and floating IPs;
2. volume attachments;
3. instances;
4. snapshots and volumes;
5. ports, router interfaces, routers, subnets, and tenant networks;
6. imported keypairs and the disposable project.

Close the scenario only when OpenStack lists and CPS inventory (including
deleted/tombstone checks) show no resource belonging to the disposable prefix.

## Lab recovery (nested compute)

When BUILD hangs at `spawning` or QEMU tcg crashes on compute01:

1. Confirm `[libvirt] virt_type = kvm` and `cpu_mode = host-model` under `[libvirt]`.
2. Purge stale placement allocations if scheduler reports `NoValidHost`.
3. Remove ghost instances from Nova DB and hypervisor (`virsh list --all`).
4. Reset stuck Cinder volumes with `openstack volume set --state available`.
5. Restart `nova-compute` after config changes; prefer durable config over libvirt hook.

See `ops/plan/tasks/sprint-18/OPS-1803-nested-lab-hypervisor-fip-fixes.md`.

## Acceptance sign-off

- [x] All quality gates green
- [x] Recovery matrix evidence recorded in `plan/sprints/sprint-18.md`
- [x] Migration lifecycle rehearsed on disposable DB
- [x] Software portions of the 9-step scenario completed; SSH is observational
- [x] Cleanup ledger closed with zero residual resources
- [x] Multi-compute placement/recovery recorded with `compute02`
