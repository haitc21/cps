# CPS-1603 — Snapshot and keypair acceptance

**Status:** Blocked by CPS-1601..1602
**Points:** 5

## Scenario

Import a public key, create and snapshot a data volume, create a second volume
from the snapshot, boot a VM with the imported key, verify SSH, then delete all
resources in dependency order.

## Gates

- Cross-project variants fail before publication.
- Restart/redelivery variants converge.
- Secret/private-key scan passes.
- Snapshot, volume, keypair, and VM cleanup is verified in OpenStack and CPS
  inventory.

