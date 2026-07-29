# Remaining CPS/OPS Completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Sprint 17–18 functional work and Sprint 13 evidence (1201/1202/1204); defer CPS-1203 TMS auth.

**Architecture:** CPS durable operations + OPS stateless OpenStack adapter. Every story Done requires pytest + curl CPS API + OpenStack CLI verification + cleanup.

**Tech Stack:** Python 3.12, FastAPI, Alembic, RabbitMQ, OpenStackSDK (OPS), Compose at `deploy/docker/docker-compose.yml`.

## Global Constraints

- Follow `cps/AGENTS.md` and `ops/AGENTS.md`.
- Done gate: unit/contract tests pass; curl returns expected HTTP + terminal operation state; OpenStack state matches.
- CPS-1203 deferred; CPS-1702 console deferred.
- Disposable prefix: `cmp180-` or `cmp170-`.

## Lab constants (preflight 2026-07-28)

```bash
export CPS=http://127.0.0.1:8000
export PROVIDER_ID=019fa1a6-d0fe-7b64-8e1a-b4508587be86
export CONNECTION_ID=019fa1a6-d0ff-7664-8849-02df2acc55a7
export OS_SSH="sshpass -e ssh -o StrictHostKeyChecking=no devops@192.168.122.253"
export SSHPASS=211203

poll_op() {
  local id=$1
  local deadline=$((SECONDS + 300))
  while [ "$SECONDS" -lt "$deadline" ]; do
    state=$(curl -sS "$CPS/api/v1/operations/$id" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    [ "$state" != "RUNNING" ] && [ "$state" != "QUEUED" ] && [ "$state" != "ACCEPTED" ] && break
    sleep 3
  done
  curl -sS "$CPS/api/v1/operations/$id"
}
```

---

### Task 1: Sprint 13 — CPS-1201/1202 evidence

**Files:**
- `cps/alembic/versions/20260726_0011_provider_owned_credentials.py`
- `cps/alembic/versions/20260726_0012_project_ownership.py`
- `cps/plan/sprints/sprint-13.md`

- [ ] Run migration lifecycle on disposable Postgres
- [ ] curl PATCH provider rotate password — no plaintext in response
- [ ] Inventory sync + GET projects with ownership columns
- [ ] OpenStack project ID matches CPS inventory
- [ ] Update sprint-13 Review evidence

### Task 2: Sprint 13 — CPS-1204 creator role

**Files:**
- `ops/src/ops/application/handlers/resource_operations.py`
- `ops/tests/unit/application/test_creator_role.py` (create if missing)

- [ ] Unit test idempotent role assignment
- [ ] curl identity-project create with test org/workspace IDs
- [ ] OpenStack role assignment verify
- [ ] Replay idempotency
- [ ] Cleanup

### Task 3: CPS-1703 catalog E2E

**Files:**
- `cps/src/cps/api/routers/catalog.py`
- `ops/src/ops/openstack/inventory.py`

- [ ] Tag approved image/flavor on OpenStack
- [ ] Inventory sync via curl
- [ ] GET catalog returns approved only
- [ ] Reject unapproved image on VM create
- [ ] Approved VM create succeeds on OpenStack

### Task 4: CPS-1701 resize/rebuild

**Files:**
- `cps/src/cps/application/operations.py`
- `ops/src/ops/application/handlers/instance_action.py`

- [ ] Contract + integration tests for confirm/revert
- [ ] curl resize → confirm → verify flavor on Nova
- [ ] curl rebuild → verify image on Nova
- [ ] Reject unapproved resize flavor

### Task 5: CPS-1704 network guardrails

**Files:**
- `ops/src/ops/application/handlers/resource_operations.py`

- [ ] Negative curl cases (malformed CIDR, external network)
- [ ] Positive disposable topology E2E
- [ ] Cleanup

### Task 6: CPS-1801 recovery matrix

- [ ] Duplicate idempotency (volume + instance)
- [ ] OPS worker restart mid-operation
- [ ] Direct drift + targeted refresh
- [ ] Evidence table in sprint-18.md

### Task 7: CPS-1802 release scenario

- [ ] Full 9-step runbook scenario
- [ ] Quality gates (ruff, mypy, pytest, checksum)
- [ ] Zero-residual cleanup ledger

### Task 8: Plan hygiene

- [ ] Update sprint-17/18 evidence
- [ ] Create OPS sprint files 15–18
- [ ] Code review request
