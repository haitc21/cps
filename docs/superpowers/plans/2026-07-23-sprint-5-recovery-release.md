# Sprint 5 implementation plan — recovery and release readiness

## Design constraints

- CPS owns durable scheduling, timeout, audit, and operation truth.
- OPS remains stateless between deliveries; provider state and CPS operation state are authoritative.
- Scheduler code creates normal CPS workflows and never imports provider SDKs.
- Retry/DLQ controls remain bounded and preserve correlation/message IDs.
- Metrics and audit payloads contain identifiers and outcomes only; never credentials, tokens, user data, or provider SDK objects.

## Delivery slices

1. CPS timeout service, scheduler primitives, late-result event projection, and operational read models.
2. CPS metrics/audit endpoints and bounded replay documentation.
3. OPS bounded consumer lifecycle, replay instrumentation, provider metrics, and mocked recovery matrix.
4. Full regression, restart/redelivery tests, and real OpenStack eight-scenario acceptance.
