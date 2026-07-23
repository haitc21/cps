# Sprint 5 recovery runbook

## Principles

- CPS operation state and the provider are authoritative; do not edit terminal rows to force success.
- Replay only messages whose payload hash, correlation ID, operation ID, and provider connection match the target operation.
- Inspect the DLQ before replaying. Poison messages remain rejected after the bounded retry budget.
- Never print or copy credentials, tokens, user data, or complete message payloads into tickets.

## Safe replay checklist

1. Record queue, message ID, operation ID, correlation ID, retry count, and a SHA-256 payload hash.
2. Query CPS operation state and event history; check provider state for provider-backed operations.
3. Verify the message belongs to the same provider connection and operation fingerprint.
4. Replay through the retry exchange with the canonical original routing key, or re-drive the normal CPS workflow with a fresh idempotency key.
5. Confirm one terminal CPS state and inspect the late-result event if the operation was already terminal.
6. Verify no duplicate provider resource exists and archive the outcome.

## Operational metrics

- CPS: `GET /metrics` exposes process-safe counters.
- OPS: `GET /metrics` exposes worker success/retry/DLQ counters.
- Health endpoints remain `/health/live` and `/health/ready`; readiness must be green before replay.

## Development deployment check

The OPS worker must resolve credentials through the private CPS listener. In the
development environment use `OPS_CPS_BASE_URL=http://127.0.0.1:8002`; the public
CPS API listener does not expose the resolver route.

After a restart, verify both consumers and their bounded QoS:

```text
rabbitmqctl -p cmp list_consumers
```

Expected queues are `ops.command.v1` and `cps.cloud.event.v1`, both active with
prefetch 10. Readiness must report database and RabbitMQ as `up`.
