# Complete instance provisioning flow

## What the OpenStack-based projects do

The OpenStack SDK models provisioning as a composition of resources: image and
flavor are required, a network or port is attached explicitly, security groups
are applied, a keypair is injected, and user-data/config-drive are optional
bootstrap inputs. A floating IP is a separate network resource that must be
allocated and associated with the server before an external SSH client can
connect. Boot-from-volume is represented as a block-device mapping and has an
explicit delete-on-termination policy.

ManageIQ exposes the same capabilities as provider features and inventory
relationships: keypair creation, security-group creation, floating-IP
creation, cloud networks, and VM provisioning are separate operations. This
allows the UI/workflow to verify capabilities and keep ownership/cleanup
decisions explicit.

## CPS flow

1. Refresh inventory and resolve the image, flavor, tenant network/port,
   security group, and (when public SSH is requested) the external floating
   network IDs. CPS verifies that every referenced resource belongs to the
   provider connection.
2. The caller sends an SSH public key, not a private key. OPS creates a
   keypair named `cmp-{operation_id}` for that instance and injects it into the
   server. Supplying an existing `key_name` remains supported, but it is
   intentionally mutually exclusive with `ssh_public_key`.
3. OPS creates the server with explicit networks/ports, security groups,
   keypair, metadata, user-data, and either image boot or image-to-volume boot.
4. For access from the corporate LAN, the request must either attach the VM to
   a provider network mapped to that LAN or supply
   `floating_network_provider_resource_id`. In the latter case OPS allocates a
   floating IP and associates it with the server. The completed event returns
   `access.ssh.host`/`hosts` with the LAN-reachable address. A tenant-only
   private network is not reachable from a laptop on the physical LAN without
   routing, provider-network mapping, or a floating IP. The private key never
   crosses CPS/OPS and must remain with the caller.
5. Delete removes the server and cleans up floating IPs and keypairs that OPS
   marked as managed for that operation. User-supplied keypairs are not
   deleted.

The operation remains asynchronous. The create response is `202 Accepted`;
the caller follows `status_url` and reads the completed event for the instance
ID and SSH access information.

The current API does not infer a security group or a public network. Those are
tenant policy decisions and must be selected explicitly by the caller or by a
higher-level provisioning profile.
