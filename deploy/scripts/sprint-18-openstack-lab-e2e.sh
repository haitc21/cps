#!/usr/bin/env bash
# Sprint 18 OpenStack lab smoke: router + FIP + optional SSH gate.
set -euo pipefail

CPS="${CPS:-http://127.0.0.1:8000}"
PREFIX="${PREFIX:-cmp180-e2e}"
SSH_USER="${SSH_USER:-cirros}"
SSH_PASS="${SSH_PASS:-gocubsgo}"

poll_op() {
  local id=$1
  local deadline=$((SECONDS + "${POLL_TIMEOUT:-300}"))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local response state
    response=$(curl -fsS "$CPS/api/v1/operations/$id")
    state=$(jq -r '.state // empty' <<<"$response")
    if [[ "$state" != "RUNNING" && "$state" != "QUEUED" && "$state" != "ACCEPTED" ]]; then
      jq . <<<"$response"
      [[ "$state" == "SUCCEEDED" ]] && return 0
      echo "operation $id reached non-success terminal state: $state" >&2
      return 1
    fi
    sleep 3
  done
  echo "timeout waiting for operation $id" >&2
  curl -sS "$CPS/api/v1/operations/$id"
  return 1
}

require_env() {
  local name=$1
  if [ -z "${!name:-}" ]; then
    echo "Set $name before running" >&2
    exit 1
  fi
}

for name in PROVIDER_ID CONNECTION_ID EXTERNAL_NETWORK_ID SUBNET_ID \
  SECURITY_GROUP_ID IMAGE_ID FLAVOR_ID; do
  require_env "$name"
done

echo "== preflight =="
curl -fsS "$CPS/health/ready" | jq .

echo "== router create =="
router_resp=$(curl -sS -X POST "$CPS/api/v1/providers/$PROVIDER_ID/network/routers" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-router-$(date +%s)" \
  -d "{\"provider_connection_id\":\"$CONNECTION_ID\",\"name\":\"$PREFIX-router\",\"external_network_provider_resource_id\":\"$EXTERNAL_NETWORK_ID\"}")
router_op=$(jq -r '.operation.id' <<<"$router_resp")
poll_op "$router_op" | jq '{state, provider_resource_id: .result_payload.provider_resource_id}'
ROUTER_ID=$(curl -sS "$CPS/api/v1/operations/$router_op" |
  jq -r '.result_payload.provider_resource_id // .result_payload.resource.id // empty')

echo "== router interface =="
iface_resp=$(curl -sS -X POST "$CPS/api/v1/providers/$PROVIDER_ID/network/router-interfaces" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-iface-$(date +%s)" \
  -d "{\"provider_connection_id\":\"$CONNECTION_ID\",\"router_provider_resource_id\":\"$ROUTER_ID\",\"subnet_provider_resource_id\":\"$SUBNET_ID\"}")
poll_op "$(jq -r '.operation.id' <<<"$iface_resp")" | jq '{state}'

echo "== SG rule TCP/22 from provider net =="
rule_resp=$(curl -sS -X POST "$CPS/api/v1/providers/$PROVIDER_ID/network/security-group-rules" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-sg22-$(date +%s)" \
  -d "{\"provider_connection_id\":\"$CONNECTION_ID\",\"security_group_provider_resource_id\":\"$SECURITY_GROUP_ID\",\"direction\":\"ingress\",\"protocol\":\"tcp\",\"port_range_min\":22,\"port_range_max\":22,\"remote_ip_prefix\":\"192.168.0.0/24\"}")
poll_op "$(jq -r '.operation.id' <<<"$rule_resp")" | jq '{state}'

if [ -z "${NETWORK_ID:-}" ]; then
  if [ "${ALLOW_PARTIAL:-0}" = "1" ]; then
    echo "NETWORK_ID absent; partial router-only smoke explicitly allowed" >&2
    exit 0
  fi
  echo "Set NETWORK_ID, or ALLOW_PARTIAL=1 for an explicit router-only smoke" >&2
  exit 1
fi

echo "== instance create with floating network =="
inst_resp=$(curl -sS -X POST "$CPS/api/v1/providers/$PROVIDER_ID/instances" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $PREFIX-vm-$(date +%s)" \
  -d "{\"provider_connection_id\":\"$CONNECTION_ID\",\"name\":\"$PREFIX-vm\",\"image_provider_resource_id\":\"$IMAGE_ID\",\"flavor_provider_resource_id\":\"$FLAVOR_ID\",\"network_provider_resource_ids\":[\"$NETWORK_ID\"],\"security_group_provider_resource_ids\":[\"$SECURITY_GROUP_ID\"],\"floating_network_provider_resource_id\":\"$EXTERNAL_NETWORK_ID\"}")
inst_op=$(jq -r '.operation.id' <<<"$inst_resp")
poll_op "$inst_op" | jq '{state, error: .error_payload.code, access: .result_payload.access}'
SSH_TARGET=$(curl -sS "$CPS/api/v1/operations/$inst_op" |
  jq -r '.result_payload.access.ssh.host // empty')

if [ -n "$SSH_TARGET" ] && command -v sshpass >/dev/null 2>&1; then
  echo "== SSH gate to $SSH_TARGET =="
  SSHPASS="$SSH_PASS" sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
    "$SSH_USER@$SSH_TARGET" 'echo ok && hostname'
else
  echo "SSH gate skipped (set NETWORK_ID + sshpass for full gate)"
fi

echo "Record provider IDs and run the dependency-ordered cleanup ledger."
