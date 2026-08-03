# Sprint 19 image lifecycle — CPS-1903 / OPS-1903

## Security boundary

The command contract carries metadata and a provider-side HTTPS reference only:
no image bytes, encoded data, credentials, query strings, fragments, or raw
provider bodies.  Import hosts are deployment-owned; the worker revalidates the
contract and rejects DNS answers that are private, link-local, loopback, or
reserved before credential resolution and before invoking OpenStackSDK.

## Automated evidence

- CPS focused image contract/durable-outbox tests: pending final suite.
- OPS focused Glance replay/security tests: pending final suite.
- Required live import: pending a non-secret HTTPS lab host configured in the
  deployment allowlist.  Do not use signed URLs or source images with private
  credentials.

## Cleanup ledger

No provider image was created by this implementation pass.  Before live test,
record the disposable image ID, verify fields/members with `openstack image
show` and `openstack image member list`, then unprotect/delete it and verify
not-found plus CPS tombstone.  Never include URLs containing signatures,
credentials, tokens, image bytes, or raw provider payloads here.
