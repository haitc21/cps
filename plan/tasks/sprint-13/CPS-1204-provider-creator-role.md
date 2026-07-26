# CPS-1204 — Provider creator role convergence

## Goal

Ensure the OpenStack credential user that creates a domain or project receives
the provider's strongest administrative role at that newly-created scope.

## Scope

- CPS owns the durable binding and operation lifecycle.
- OPS performs the Keystone role assignment after successful creation.
- Assignment is idempotent and uses provider IDs, never display names.
- TMS, LMS and BMS are out of scope.

## Acceptance

- Domain creation converges `admin` (or the strongest supported admin role) on
  the new domain for the provider credential user.
- Project creation converges the same role on the new project.
- Replay does not duplicate assignments.
- Missing administrative role or user fails the operation without reporting a
  false success.
