# Sprint 19 flavor lifecycle — evidence

## Scope

CPS-1902/OPS-1902 add typed, idempotent flavor create, delete, access
replacement, and extra-spec patch operations. Core sizing is immutable; OPS
uses Nova compute SDK methods and never replaces a flavor to apply a patch.

## Automated verification

- CPS: 632 passed, 182 skipped; focused flavor contract/API/idempotency tests
  passed (9 tests); Ruff, mypy, contract validation, diff check, and staged
  secret scan passed.
- OPS: 464 passed, 24 skipped; focused flavor contract/dispatch/handler tests
  passed (21 tests); Ruff, mypy, contract validation, diff check, and staged
  secret scan passed.
- RED tests were observed for the missing typed contract and unsupported
  provider dispatch before implementation.

## Live verification and cleanup ledger

The live CRUD/access/extra-spec flow is pending the next disposable OpenStack
window. It must use a unique `cmp-s19-flavor-*` name, poll CPS operations to a
terminal state, compare provider IDs and fields with `openstack flavor show`,
`flavor access list`, and `flavor extra spec list`, then delete and prove
absence. No live resource was created by the automated gates; cleanup required
for this task is therefore none.

Credentials, tokens, raw provider bodies, and private endpoint details are
intentionally omitted.
