# Live CPS API test: `hanoi` / `ttcntt` / `dev-cmp1`

Date: 2026-07-30 (Asia/Bangkok)

## Result

The live test created the requested domain and project through CPS API. Nova
did create an `ACTIVE` instance named `dev-cmp1` with flavor `m1.medium` and
image `ubuntu-24.04`, but CPS marked the corresponding create operation
`FAILED` while reconciling the provider response. This distinction matters:
the server is a provider-side side effect of a failed CPS operation, not a
clean CPS `SUCCEEDED` create result. Host-to-instance SSH was confirmed
successfully through the provider fixed address `192.168.0.246`:

```text
SSH_OK
dev-cmp1
```

The lab's floating-IP topology is not routable: Neutron rejected association
because the external network is not reachable from the provider subnet. The
working host connection therefore uses the fixed provider-network address.

## Environment and protected resources

- CPS API: `http://127.0.0.1:8000`
- Provider: `openstack-hanoi-lab`
- Provider ID: `019fa7a7-9f46-7e71-b6f6-28a7c6632222`
- System/admin connection used for domain/project setup:
  `019fa7a7-9f47-7ff8-87b7-7fdda20f61a0`
- Project connection used for instance/network operations:
  `019fb108-7ab5-7e0a-9679-9c24f1428275`
- External/provider network: `provider`
  (`c50c4ecd-a053-408e-bd45-fa8954f09f4e`)
- Provider subnet: `provider-subnet`
  (`f4fbb9e7-ef68-43cb-9f8e-8950cad760b1`)
- Flavor: `m1.medium` (`3`)
- Image: `ubuntu-24.04`
  (`28a8e975-fb44-4f4e-aefd-09025cf2aa6b`)

No private key or password is recorded in this runbook.

## Step 1 — Create domain `hanoi` through CPS

Request:

```text
POST /api/v1/provider-connections/019fa7a7-9f47-7ff8-87b7-7fdda20f61a0/domains/create
Idempotency-Key: cmp-live-hanoi-domain-20260730
```

Operation: `019fb108-1d23-70c4-a95f-82e125984291`

Result: `SUCCEEDED`; provider domain ID:
`8f3d4e8c763343859c5d5a3c8aa75bc0`; name: `hanoi`.

## Step 2 — Create project `ttcntt` through CPS

Request:

```text
POST /api/v1/provider-connections/019fa7a7-9f47-7ff8-87b7-7fdda20f61a0/projects/create
Idempotency-Key: cmp-live-ttcntt-project-20260730
```

Operation: `019fb108-4bf2-71d7-8e7e-b4ebe67dc585`

Result: `SUCCEEDED`; provider project ID:
`51006f2625f24f5c891f78839435afe7`; name: `ttcntt`; domain: `hanoi`.

## Step 3 — Create and validate project connection

Created through:

```text
POST /api/v1/providers/019fa7a7-9f46-7e71-b6f6-28a7c6632222/connections
```

The connection uses Keystone `http://controller:5000/v3`, project `ttcntt`,
domain `hanoi`, region `RegionOne`, public interface, and TLS verification
disabled for this lab. Credentials were supplied from the existing local
secret configuration and are intentionally omitted here.

Validation request:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/validate
Idempotency-Key: cmp-live-ttcntt-validate-20260730
```

Operation: `019fb108-b792-77bf-9f16-ba6bdf74f0df`; result: `SUCCEEDED`; CPS
connection status: `VALID`.

Inventory sync:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/inventory-syncs
Idempotency-Key: cmp-live-ttcntt-inventory-20260730
Body: {"collections":["flavor","image","network"]}
```

Operation: `019fb109-2979-786b-a3c8-adb474293e35`; result: `SUCCEEDED`.

## Step 4 — Create `dev-cmp1` through CPS

The original live request used:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/instances
Idempotency-Key: cmp-live-dev-cmp1-20260730
```

The request selected flavor `3`, image
`28a8e975-fb44-4f4e-aefd-09025cf2aa6b`, provider network
`c50c4ecd-a053-408e-bd45-fa8954f09f4e`, floating network with the same ID,
SSH username `ubuntu`, and the local public SSH key. The operation was:
`019fb109-6b11-7135-87a6-150d2b081dd3`.

The first CPS operation reported `PROVIDER_RESOURCE_NOT_FOUND`, although Nova
had already created an `ACTIVE` server. A later retry exposed the underlying
capacity race: Nova also left an `ERROR` server with `No valid host was found`.
The orphan `ERROR` servers and their failed-operation keypairs were removed;
the successful `ACTIVE` server was retained.

Final OpenStack server:

- Server ID: `fac1f746-b612-4fd4-ba9f-42567708b9a3`
- Name: `dev-cmp1`
- Status: `ACTIVE`
- Fixed address: `192.168.0.246`
- Port ID: `dbd61885-52da-4e74-9399-8121171d6334`
- Project ID: `51006f2625f24f5c891f78839435afe7`
- Flavor: `m1.medium`
- Image: `ubuntu-24.04`
- Managed keypair: `cmp-019fb113-e09b-76eb-8a3f-92c97c252289`

## Step 5 — Configure SSH ingress through CPS

The instance uses project default security group:
`9801fc4a-5a2d-4591-bfd1-73d3f0965d5e`.

The host source address on `br-home` is `192.168.0.102`. CPS API created a
least-privilege ingress rule:

```text
POST /api/v1/provider-connections/019fb108-7ab5-7e0a-9679-9c24f1428275/network-operations
Idempotency-Key: cmp-live-dev-cmp1-ssh-rule-20260730
Body:
{
  "resource_type": "security-group-rule",
  "operation": "create",
  "parameters": {
    "security_group_id": "9801fc4a-5a2d-4591-bfd1-73d3f0965d5e",
    "direction": "ingress",
    "ethertype": "IPv4",
    "protocol": "tcp",
    "port_range_min": 22,
    "port_range_max": 22,
    "remote_ip_prefix": "192.168.0.102/32"
  }
}
```

Operation: `019fb118-e796-7fb4-b3a9-f84464f60069`; result: `SUCCEEDED`.
Rule ID: `64d0d6e9-d85e-4e26-9772-6226afbfda65`.

## Step 6 — Floating IP check and host connectivity

CPS network association was attempted with operation
`019fb118-06cc-77bb-9792-a862d787d258`, using FIP
`bbcd26f2-ce4f-4b56-b5c4-7de43a4271eb` and port
`dbd61885-52da-4e74-9399-8121171d6334`. CPS correctly reached the project
scoped Neutron resource, but Neutron rejected the association:

```text
External network c50c4ecd-a053-408e-bd45-fa8954f09f4e is not reachable from
subnet f4fbb9e7-ef68-43cb-9f8e-8950cad760b1.
```

The same topology check through OpenStack CLI returned the same 404 policy
error. The unused FIP was removed after verification. The provider network is
directly reachable from the host, so connectivity was verified with:

```text
timeout 20 ssh -o BatchMode=yes -o StrictHostKeyChecking=no \
  -o ConnectTimeout=8 -i ~/.ssh/id_ed25519 ubuntu@192.168.0.246 \
  'echo SSH_OK && hostname'
```

Observed output:

```text
SSH_OK
dev-cmp1
```

## Code/test verification performed

During this live test, OPS was reviewed and fixed through the agreed Cursor
worker flow:

- Instance creation now associates a FIP through Neutron port relationships
  instead of Nova's legacy `add_floating_ip_to_server` path.
- Floating-IP resource operations now fall back to an exact-ID scan of
  `network.ips()` when project-scoped `get_ip()` returns 404.
- Full OPS test suite: `427 passed, 24 skipped`.
- Ruff: passed.
- mypy: passed.
- Rebuilt local images `cmp-ops` and `cmp-ops-worker` and recreated their
  containers.

Changes remain unstaged/uncommitted as required by the working agreement.

## Final state

Successful:

1. Domain `hanoi` created through CPS.
2. Project `ttcntt` created through CPS under `hanoi`.
3. Provider currently has `dev-cmp1` `ACTIVE` with the requested image/flavor;
   the CPS create operation itself remains `FAILED` and needs a convergence
   fix before this can be called a clean CPS success.
4. SSH from the local host to `dev-cmp1` is confirmed through
   `192.168.0.246`.
5. SSH ingress was created through CPS and restricted to the host `/32`.

Known lab limitation:

- Floating IP association is unavailable until a router/path makes the
  external network reachable from the provider subnet. The test does not claim
  floating-IP connectivity; it uses the directly reachable provider fixed IP.
