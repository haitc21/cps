"""SQLAlchemy ORM models for CPS persistence."""

from __future__ import annotations

from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.inventory import (
    Flavor,
    IdentityDomain,
    Image,
    Instance,
    InstancePort,
    InstanceVolume,
    Network,
    Port,
    Project,
    Quota,
    Region,
    RoleAssignment,
    Subnet,
    Volume,
)
from cps.infrastructure.db.models.inventory_sync import InventoryBatch, InventorySync
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.outbox_messages import OutboxMessage
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider

__all__ = [
    "Credential",
    "InboxMessage",
    "Region",
    "IdentityDomain",
    "Project",
    "RoleAssignment",
    "Quota",
    "Flavor",
    "Image",
    "Instance",
    "Network",
    "Subnet",
    "Port",
    "Volume",
    "InstancePort",
    "InstanceVolume",
    "InventorySync",
    "InventoryBatch",
    "Operation",
    "OperationEvent",
    "OutboxMessage",
    "Provider",
    "ProviderConnection",
]
