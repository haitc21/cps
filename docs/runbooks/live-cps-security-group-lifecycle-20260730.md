# Live CPS security-group lifecycle — 2026-07-30

## Validation rule

All security-group mutations in this run were performed through CPS API. The
OpenStack CLI was used only for provider read-back and final absence check.
No security group was attached to `dev-cmp1`, so the disposable validation did
not change the instance network policy.

Connection: `019fb108-7ab5-7e0a-9679-9c24f1428275` (`ttcntt`)

## CPS API evidence

### Create

- Operation: `019fb1f5-00bd-7d38-af0c-121ee9e11c70`
- Provider security group: `c5f6f5ac-d641-4f29-95d9-6bb21dee8c01`
- Initial name: `cmp-sg-lifecycle-20260730`
- Result: `SUCCEEDED`

### Update

- Operation: `019fb1f5-2d61-70b4-81a9-993292e2ac79`
- New name: `cmp-sg-lifecycle-updated`
- New description: `CPS lifecycle updated`
- Result: `SUCCEEDED`

### Rule create

- Operation: `019fb1f5-5eeb-738e-9bd4-68f4068d0e27`
- Rule: `d667595a-90e4-4a00-80e7-40475cf5c7c2`
- Ingress TCP/22 from `192.168.0.102/32`
- Result: `SUCCEEDED`

Controller CLI read-back confirmed the updated group and rule, including
project `51006f2625f24f5c891f78839435afe7`, TCP port 22, and the expected
CIDR.

### Rule delete and group delete

- Rule delete operation: `019fb1f5-b2a3-7b1a-a4bd-c96d61ab2c9b` — `SUCCEEDED`
- Group delete operation: `019fb1f5-e490-7968-a74a-0e2cc117290d` — `SUCCEEDED`
- CLI verification: `No SecurityGroup found for c5f6f5ac-d641-4f29-95d9-6bb21dee8c01`

## Conclusion

The disposable security-group and security-group-rule create/update/delete
lifecycle is verified through CPS API with OpenStack CLI read-back. The
default security groups and the instance's existing default group were not
modified.
