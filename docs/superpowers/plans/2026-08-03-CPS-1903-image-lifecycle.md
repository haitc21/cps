# CPS-1903 / OPS-1903 image lifecycle

Story: CPS-1903 / OPS-1903.  Outcome: privileged, durable Glance metadata and
access operations without image bytes or source credentials.

Contract decision: additive `1.0` resource-operation payloads; the canonical
image request is pinned verbatim into OPS.  CPS accepts only HTTPS URLs whose
host is explicitly allowlisted per request, has no userinfo/query/fragment, and
is not an IP literal or private/reserved target.  Metadata is string-only and
bounded.  No request accepts byte/base64 fields.

- [ ] RED: contract tests reject SSRF, secret metadata and bytes; service test
  proves durable/idempotent import command; OPS tests prove replay-safe Glance
  deltas and no URL reaches a provider before validation.
- [ ] Observe each test fail against the absent image contract/handler.
- [ ] GREEN: add canonical/pinned image models, message types, admin API and
  atomic CPS outbox operation; add OPS dispatch and Glance-only converger.
- [ ] Refactor validation into a shared, side-effect-free policy; keep provider
  SDK objects at the OPS boundary.
- [ ] Review: inspect URL parsing, DNS/IP literal ambiguity, metadata redaction,
  protected deletion, capability gates, idempotency and publish-before-ack.
- [ ] Security scan, focused/affected/full checks, diff check and secret scan.
- [ ] Live: capability-gated HTTPS import plus CLI comparison; cleanup only the
  operation-created disposable image.  Record redacted evidence in runbook.
- [ ] Proposed commits: `feat(cps): add safe image lifecycle commands` and
  `feat(ops): handle safe Glance image lifecycle commands`.

Out of scope: image upload/download bytes, private/signed URLs, DNS resolution
or SSRF fetching by CPS/OPS, migrations, user-facing catalog policy changes.
