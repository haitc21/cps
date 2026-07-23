# Sprint 6 implementation plan — design alignment and fast demo readiness

**Dates:** 2026-07-23 onward

**Sprint goal:** Make the demo path accurately reflect the approved CPS/OPS
design while closing the highest-risk provider lifecycle and runtime gaps.

**Canonical design:**
`docs/superpowers/specs/2026-07-16-openstack-cloud-provider-management-design.md`

**Priority rule:** Work follows the original technical priority order. The
demo path is validated after each vertical slice, but no identified item is
dropped or silently deferred.

## Findings carried into this sprint

The current implementation already follows the main boundaries and uses the
intended open-source patterns: CPS owns durable truth, OPS is stateless, OPS
uses supported OpenStackSDK proxies, inventory follows collector/mapper
boundaries, and VM create uses an operation marker plus Nova
`delete_on_termination`.

The remaining gaps are:

1. OPS capability discovery reports service presence but not discovered API
   versions, microversions, or operation-level capability probes.
2. OPS reports delete success immediately after submitting the delete request;
   it does not wait for provider disappearance.
3. Production CPS can start without a credential key ring and fails only when
   credential work is attempted.
4. The mapper accepts nested `list`/`dict` values without recursive primitive
   sanitization, leaving an SDK-object boundary risk.
5. Runtime images use mutable Python/uv installation inputs instead of fully
   immutable image/tool inputs.

## Selected stories

| Story | Priority | Owner | Points | Demo blocker | Status |
|---|---|---|---:|---|---|
| OPS-601 Capability/version discovery | P0 | OPS | 8 | Yes | Ready |
| OPS-602 Delete waiter and provider convergence | P0 | OPS | 5 | Yes | Ready |
| CPS-603 Production key-ring fail-fast | P0 | CPS | 3 | No | Ready |
| OPS-603 Recursive SDK-resource sanitization | P1 | OPS | 5 | No | Ready |
| CPS-601 Demo runtime configuration | P1 | CPS + OPS | 3 | Yes | Ready |
| CPS-602/OPS-604 Immutable runtime images | P1 | CPS + OPS | 5 | No | Ready |

## P0 — original technical priority order

### OPS-601 — Capability and API version discovery

Modify `ops/src/ops/openstack/discovery.py` and the connection factory only
through supported OpenStackSDK APIs.

Acceptance criteria:

- Authenticate through the existing ephemeral connection.
- Record service availability and discovered endpoint/API version data without
  storing raw catalog responses.
- Populate `min_version`/`max_version` where the SDK/provider exposes them.
- Report operation-level features for the delivered paths:
  `instance.create.image`, `instance.create.volume_from_image`,
  `instance.start`, `instance.stop`, `instance.reboot`, and
  `instance.delete`.
- Do not hardcode a named OpenStack release or a fixed maximum microversion.
- Unsupported optional services remain explicit capabilities and do not make
  OPS readiness fail.
- Add mocked SDK tests for missing services, version discovery, malformed
  catalog data, and safe capability output.
- Preserve the CPS/OPS schema checksum unless a CPS contract change is proven
  necessary.

Implementation constraint: inspect the cloned OpenStackSDK proxy/resource
implementation and tests before choosing the version-discovery API. Do not
reimplement SDK HTTP calls in OPS.

### OPS-602 — Delete waiter and convergence-safe result

Modify the instance delete path so `OPERATION_COMPLETED` is emitted only after
the provider confirms deletion, while preserving idempotent behavior when the
server is already absent.

Acceptance criteria:

- Existing `404` before delete remains a successful tombstone.
- Successful `delete_server` is followed by bounded polling until
  `ResourceNotFound` or a documented terminal provider state.
- Timeout maps to the common retry/timeout behavior and does not claim
  `DELETED`.
- Redelivery after a publish failure does not issue a second unsafe mutation;
  it checks provider state and republishes the deterministic result.
- Add unit tests for already absent, normal deletion, timeout, provider error,
  and replay/redelivery.
- Preserve the existing root-volume policy: Nova owns
  `delete_on_termination`; OPS must not blindly delete the Cinder volume.

### CPS-603 — Fail fast when production credential encryption is unavailable

Make `CPS_CREDENTIAL_KEY_RING` mandatory for `CPS_ENVIRONMENT=production` and
ensure the application cannot expose credential-bearing routes with a null
cipher.

Acceptance criteria:

- Production settings fail validation when the key ring is missing, malformed,
  or missing the active key version.
- Development/test behavior remains usable with explicit synthetic test keys.
- No credential plaintext appears in startup errors, logs, health payloads, or
  diagnostics.
- Add startup/config tests and verify migrations plus credential lifecycle
  tests remain green.
- Update deployment documentation and secret injection examples.

### OPS-603 — Recursive primitive boundary for mapped resources

Add one shared, bounded sanitizer in the OPS mapper boundary.

Acceptance criteria:

- Output contains only JSON primitives, lists, and dictionaries with string
  keys.
- Nested OpenStackSDK resources are converted to stable IDs or safe scalar
  fields; they are never serialized by `str(resource)` as an opaque object.
- Secret-like fields remain redacted or excluded.
- Collection and targeted-refresh mappings use the same sanitizer.
- Add regression tests for nested SDK resources in image/flavor, addresses,
  attachments, fixed IPs, and metadata.
- Existing golden fixtures remain byte-compatible where their values are
  already primitive.

### CPS-601 — Fast local demo runtime

Keep the local Compose path easy to start without weakening production
requirements.

Acceptance criteria:

- `cps/deploy/docker/docker-compose.yml` starts public CPS, internal CPS,
  CPS worker, OPS API, and OPS worker with the correct Docker DNS URL:
  `http://cps-internal:8002`.
- Documentation distinguishes host-process development URL
  `http://127.0.0.1:8002` from container-to-container URL.
- Demo instructions provide a synthetic development credential key-ring input
  through `.env.example` or an explicit shell command; no real secret is
  committed.
- A clean local stack can demonstrate credential creation, validation,
  capability retrieval, inventory, and VM delete convergence.
- This slice does not require production key-ring fail-fast; that is CPS-603.

## P1 — remaining design hardening

### CPS-602 / OPS-604 — Immutable runtime images

Harden both Dockerfiles without changing service behavior.

Acceptance criteria:

- Python base image is pinned to an immutable patch tag or digest.
- uv installation is version-pinned and reproducible, or uses a pinned uv
  image/binary source with checksum verification.
- Runtime dependencies continue to install only from the committed lockfile.
- Images run as a non-root user unless a documented dependency proves that
  root is required.
- CPS public/internal modes and OPS API/worker overrides continue to work.
- Docker build, Compose config, and container health checks pass.

This is not a demo blocker if the existing development images build and the
demo uses a controlled local environment.

## P2 — none

All five identified gaps are selected in this sprint. The demo runtime remains
available as a validation track and is not a reason to remove production
hardening from the sprint.

## Delivery order

1. Write failing tests for OPS-601, OPS-602, and OPS-603.
2. Implement capability discovery and delete convergence.
3. Implement recursive mapper sanitization.
4. Make the local Compose demo reproducible with synthetic, externally supplied
   development key material.
5. Run the end-to-end demo acceptance against the local OpenStack environment.
6. Harden images as capacity permits.
7. Re-run the complete demo acceptance after all five technical slices.

## Demo acceptance scenario

From a clean checkout:

1. Start the Compose dependencies and services.
2. Create a provider, connection, and credential in CPS.
3. Submit safe connection validation and verify persisted capabilities include
   service/version information and operation features.
4. Run full inventory and a targeted refresh; verify no SDK object or secret is
   persisted.
5. Create a disposable VM, execute delete, and verify CPS reaches `SUCCEEDED`
   only after provider disappearance.
6. Redeliver/retry the delete completion path and verify no duplicate provider
   mutation occurs.

## Definition of Done

- P0 focused tests, affected CPS/OPS suites, contract validation, and Compose
  validation pass.
- No CPS OpenStackSDK dependency and no OPS persistence dependency are added.
- No direct OpenStack service HTTP clients or SDK internals are introduced.
- Provider request IDs, normalized errors, timeout behavior, replay safety, and
  redaction remain covered.
- Demo evidence records the OpenStack capability/version result, inventory
  result, delete convergence, and known provider limitations.
- Production key-ring validation is tested independently from the local demo.

## Risks and mitigations

| Risk | Mitigation | Owner | Status |
|---|---|---|---|
| SDK version API differs across providers | Use OpenStackSDK public APIs and mocked provider variants | OPS | Open |
| Delete completion is eventually consistent | Bounded waiter plus deterministic replay path | OPS | Open |
| Demo key material is mishandled | Synthetic key only, injected externally, never committed | CPS | Open |
| Image hardening delays demo | Run the demo track after the first three slices and retain image work in this sprint | CPS/OPS | Open |
| Production key validation blocks local work | Keep explicit synthetic development keys separate from production validation | CPS | Accepted |

## Review evidence

- Demo command/results:
- OPS capability/version fixture:
- Delete waiter/replay tests:
- Mapper sanitizer tests:
- Compose/Docker validation:
- Production key-ring result:
- P1 image hardening result:
- Known limitations:
