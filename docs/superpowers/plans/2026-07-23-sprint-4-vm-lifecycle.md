# Sprint 4 executable plan — VM lifecycle

## Planning decisions

- CPS remains the durable source of truth for operation state and normalized VM persistence.
- OPS owns OpenStack SDK mutation, waiters, provider error normalization, and replay observation.
- VM create supports only IMAGE and VOLUME_FROM_IMAGE in this sprint; existing-volume boot remains deferred.
- User data is accepted only as bounded opaque input, redacted before logs, and never copied into result/error payloads.
- Every mutating command carries a deterministic operation marker so redelivery observes provider state before retrying mutation.
- Root-volume removal is controlled by Nova block-device mapping `delete_on_termination`; no independent blind Cinder delete is allowed.

## Task slices

### CPS-401/402 — create contract and operation

- Define canonical create request, boot source, network/port, security-group, key-pair, metadata, config-drive, and result contracts.
- Validate provider-connection ownership for all referenced resources before publishing a command.
- Persist operation request without secrets and publish a reference-only command through outbox.
- Persist normalized instance, instance-port, and instance-volume results atomically after completion.

### OPS-401/406 — create handler and waiter

- Add bounded create mapping for both supported boot modes.
- Add operation marker lookup before provider mutation and deterministic provider result mapping.
- Add waiter with injected clock/sleeper and explicit ACTIVE/SHUTOFF/ERROR/deleted/timeout outcomes.

### CPS-403/404 + OPS-402..405 — lifecycle operations

- Add detail/start/stop/reboot/delete command contracts and idempotent APIs.
- Enforce state and capability preconditions in CPS and repeat safe checks in OPS.
- Refresh normalized instance and related port/volume snapshots for every terminal result.
- Persist root-volume policy and tombstone deleted instances without blind volume deletion.

## Review gates

1. CodeGraph blast-radius query before each slice.
2. Failing contract/acceptance test before implementation.
3. Focused CPS/OPS tests, migration/schema checks, and mocked messaging integration.
4. Ruff, mypy, diff check, secret scan, and contract pin verification.
5. Live acceptance for create in both boot modes, detail, start, stop, reboot, delete, replay, and restart.
