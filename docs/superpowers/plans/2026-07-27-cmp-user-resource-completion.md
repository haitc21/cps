# CMP User Resource Completion — Implementation Plan

**Status:** Proposed for Sprint Planning
**Date:** 2026-07-27
**Repositories:** CPS and OPS
**Backlog:** CPS-E15..E18

## Objective

Complete the resource lifecycle a CMP workspace user needs after the existing
instance and Neutron workflows: block storage, snapshots, SSH keypairs,
advanced VM actions, and governed selection of administrator-curated catalogs.

CPS remains the durable provider-neutral control plane. OPS remains the
stateless OpenStackSDK adapter. Every mutation is authorized from persisted
ownership, represented by an idempotent operation, and reconciled into typed
inventory.

## Product policy

### CMP user-managed

- instances, including selected advanced lifecycle actions;
- tenant networks, subnets, routers, ports, security groups, and floating IPs;
- volumes and volume snapshots;
- imported SSH public keypairs.

### OpenStack administrator-managed

- public/shared Glance images;
- Nova flavors, host aggregates, and availability zones;
- Cinder volume types and storage backends;
- external/provider networks and floating-IP pools;
- domains, roles, global quotas, and provider policy.

CMP exposes administrator-managed resources as an allow-listed selection
catalog. It does not hardcode provider UUIDs and does not expose user mutation
APIs for those catalogs.

## Explicitly deferred

- user image upload/import and image binary transfer;
- flavor, availability-zone, volume-type, or external-network mutation by a
  workspace user;
- load balancer, DNS, VPN, Kubernetes, database, object storage, and file share;
- private-key custody;
- implicit cascading deletes or a composite “delete workspace” workflow.

## Delivery sequence

1. Sprint 15 establishes project-owned volume inventory and lifecycle.
2. Sprint 16 adds snapshots and project-owned public keypairs.
3. Sprint 17 adds resize/rebuild/console, catalog policy, and network guardrails.
4. Sprint 18 proves recovery, migrations, authorization, real-cloud behavior,
   and cleanup across the complete user workflow.

Each sprint is a vertical CPS/OPS slice. Contract/schema changes start in CPS,
the exact artifacts are pinned in OPS, and provider mutation is not enabled
until contract, authorization, replay, and redaction tests pass.

## Cross-cutting acceptance

- CPS never imports OpenStackSDK or performs provider I/O.
- OPS never persists business state or credentials.
- Workspace ownership is derived from canonical project inventory and cannot
  be overridden by request fields.
- Operation and outbox commit atomically; result ingestion is inbox-idempotent.
- Provider IDs are returned by inventory/results, not configured as constants.
- Secrets, private keys, tokens, console URLs, and raw SDK objects never enter
  durable messages, logs, fixtures, or error details.
- Every real-cloud resource uses a disposable prefix and has verified cleanup.

## Release scenario

Using one authorized workspace:

1. select an approved image, flavor, volume type, and external network;
2. import an SSH public key;
3. create a tenant network topology and security policy;
4. create a VM and a data volume;
5. attach, detach, extend, snapshot, and clone the data volume;
6. resize and rebuild the VM within approved catalog policy;
7. allocate and release a floating IP;
8. delete all user resources and prove inventory convergence;
9. repeat critical transitions across OPS/CPS restart and message redelivery.

## Quality gates

- Pydantic, JSON Schema, golden fixture, and checksum parity in CPS and OPS.
- Unit, contract, integration, migration, redelivery, and authorization tests.
- Ruff, mypy, secret scan, Docker/Compose smoke, and `git diff --check`.
- Real OpenStack capability report and verified resource cleanup.
