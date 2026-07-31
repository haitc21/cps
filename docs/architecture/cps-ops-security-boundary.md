# CPS/OPS security and provider boundary

## Purpose

CPS is an independently exposed CMP API service. It does not depend on BMS for
request authentication or authorization. BMS and TMS may be separate platform
services, but they are not in the CPS authentication path.

## Request flow

```text
Client
  -> CPS /api/v1 or /api/v1/admin
  -> Keycloak JWT validation in CPS
  -> resource_access["cmp"].roles mapping
  -> organization/workspace policy in CPS
  -> OPS internal command
  -> OpenStack SDK with one provider-admin credential
```

## Roles and API surfaces

- CPS validates the Bearer token directly against the configured Keycloak
  issuer, audience, and signing keys.
- CPS reads roles from the Keycloak client `cmp`; the supported roles are
  `admin` and `member`.
- `/api/v1/**` is the member-facing surface. A member is restricted by the
  organization/workspace context and policy attached to the request.
- `/api/v1/admin/**` is the CMP administration surface and requires the
  `admin` role. It manages provider resources and policy such as flavors,
  images, availability zones, volume types, networks, quotas, and catalog
  approval.
- BMS does not authenticate CPS requests or forward a replacement security
  context. CPS must not infer admin/member from BMS headers.

## Provider execution

- OpenStack has one configured provider credential with administrator rights.
- Both CMP admins and CMP members ultimately use that provider credential;
  OpenStack does not distinguish CMP users.
- CPS is responsible for authentication, role checks, organization/workspace
  ownership, catalog policy, idempotency, and durable workflow state.
- OPS is an internal OpenStack SDK adapter. It executes CPS commands, handles
  provider waiters/retries/error normalization, and does not authenticate the
  end user or decide CMP roles.

## Audit and secrets

BMS business audit is not a CPS/OPS dependency. CPS operation history and
events are technical workflow state for idempotency, recovery, and provider
convergence; they are not a substitute for business audit. JWTs, authorization
headers, provider credentials, and bearer console URLs must never be persisted
in commands, operation results, events, or logs.

## Horizon relationship

Horizon is a behavioral/provider reference for OpenStack SDK calls, resource
mapping, pagination, waiters, and exception handling. Its session/auth/UI
assumptions must not be copied into CPS. Provider behavior can be ported under
the Apache-2.0 license while preserving the CPS policy and durable-operation
boundaries.

## Required security tests

The CPS security contract must cover missing/expired/wrong-issuer tokens,
missing client `cmp`, unsupported roles, member access to admin routes,
organization/workspace ownership violations, and correct `admin`/`member`
mapping from `resource_access.cmp.roles`.

> Current implementation note: CPS currently has redaction rules for
> authorization material, but the direct Keycloak JWT converter and route
> authorization described here must be implemented and tested before claiming
> the security boundary is complete.
