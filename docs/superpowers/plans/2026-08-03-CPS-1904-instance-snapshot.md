# CPS/OPS-1904 instance snapshot

- [x] RED: add no-bytes CPS/OPS contract tests; observed missing module failures.
- [x] GREEN: add pinned `InstanceSnapshotRequest`, route, durable CPS operation and OPS handler.
- [x] Validate source ownership/ACTIVE state/capability before Nova mutation; use deterministic operation marker for replay.
- [x] Apply the central catalog evaluator to launch, rebuild, and resize without provider I/O.
- [x] Project terminal snapshot output as image inventory with `image_type=snapshot` and source-instance metadata.
- [x] Run focused contract/handler/regression tests, formatter, lint, type checks, full suites, and diff check.
- [ ] Live: create disposable instance through CPS, snapshot and poll operation, compare with OpenStack CLI, consume snapshot, cleanup.
- [x] Security: metadata bounds and secret-key rejection; no image bytes in API, AMQP payload, result, or fixture.
- [ ] Commit boundary: CPS-1904 and OPS-1904 only after paired live evidence and review.
