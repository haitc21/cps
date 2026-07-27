# CPS-1603 — Snapshot and keypair acceptance

**Status:** Done with lab-network SSH limitation
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

## Review evidence

- Real curl acceptance passed for keypair import, private-network/router
  creation, VM create with `key_name`, floating-IP allocation and association,
  inventory sync, and operation convergence.
- OpenStack showed the VM port on the private subnet and the associated address
  `192.168.0.243`; the VM carried keypair `cmp1603-keypair`.
- SSH was attempted from the CMP host with the configured public key and
  failed with `No route to host` because the lab provider network is not
  reachable from the test host. This is an external topology gate, not a CPS
  or OPS API failure.
- Cleanup was verified directly in OpenStack: VM, floating IP, keypair,
  router, subnet, network, and disposable project were removed.
