"""Operation projections and validation-command creation."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime

from cps.api.schemas.operations import (
    OperationEventPage,
    OperationEventView,
    OperationPage,
    OperationPageInfo,
    OperationView,
)
from cps.application.audit import project_operation_audit
from cps.contracts.errors import (
    CapabilityUnsupportedError,
    CatalogPolicyViolationError,
    DomainConflictError,
    IdempotencyKeyReusedError,
    InstanceStateConflictError,
    NetworkPolicyViolationError,
    NetworkQuotaExceededError,
    OperationNotFoundPublicError,
    ProviderConnectionNotFoundError,
)
from cps.contracts.messages.envelope import MessageEnvelope
from cps.contracts.messages.flavor_operations import (
    FlavorAccessReplaceRequest,
    FlavorCreateRequest,
    FlavorDeleteRequest,
    FlavorExtraSpecsPatchRequest,
)
from cps.contracts.messages.identity import (
    IdentityOperation,
    IdentityResourceRequest,
    QuotaRequest,
    RoleAssignmentRequest,
)
from cps.contracts.messages.instance import InstanceAction, InstanceCreateRequest
from cps.contracts.messages.keypair_operations import KeypairOperationRequest
from cps.contracts.messages.network_operations import NetworkOperationRequest
from cps.contracts.messages.resource_operations import ScopeKind
from cps.contracts.messages.types import (
    CONNECTION_VALIDATE,
    FLAVOR_ACCESS_REPLACE,
    FLAVOR_CREATE,
    FLAVOR_DELETE,
    FLAVOR_EXTRA_SPECS_PATCH,
    FLOATING_IP_ALLOCATE,
    FLOATING_IP_ASSOCIATE,
    FLOATING_IP_DISASSOCIATE,
    FLOATING_IP_RELEASE,
    IDENTITY_DOMAIN_CREATE,
    IDENTITY_DOMAIN_DELETE,
    IDENTITY_DOMAIN_UPDATE,
    IDENTITY_PROJECT_CREATE,
    IDENTITY_PROJECT_DELETE,
    IDENTITY_PROJECT_UPDATE,
    IDENTITY_QUOTA_READ,
    IDENTITY_QUOTA_UPDATE,
    IDENTITY_ROLE_ENSURE,
    IDENTITY_ROLE_REVOKE,
    INSTANCE_CONFIRM_RESIZE,
    INSTANCE_CREATE,
    INSTANCE_DELETE,
    INSTANCE_GET,
    INSTANCE_REBOOT,
    INSTANCE_REBUILD,
    INSTANCE_RESIZE,
    INSTANCE_REVERT_RESIZE,
    INSTANCE_START,
    INSTANCE_STOP,
    INVENTORY_COLLECT,
    INVENTORY_REFRESH,
    KEYPAIR_DELETE,
    KEYPAIR_IMPORT,
    NETWORK_CREATE,
    NETWORK_DELETE,
    NETWORK_UPDATE,
    PORT_CREATE,
    PORT_DELETE,
    PORT_UPDATE,
    ROUTER_CREATE,
    ROUTER_DELETE,
    ROUTER_INTERFACE_ENSURE,
    ROUTER_INTERFACE_REMOVE,
    ROUTER_UPDATE,
    SECURITY_GROUP_CREATE,
    SECURITY_GROUP_DELETE,
    SECURITY_GROUP_RULE_CREATE,
    SECURITY_GROUP_RULE_DELETE,
    SECURITY_GROUP_UPDATE,
    SUBNET_CREATE,
    SUBNET_DELETE,
    SUBNET_UPDATE,
    VOLUME_ATTACH,
    VOLUME_CREATE,
    VOLUME_DELETE,
    VOLUME_DETACH,
    VOLUME_RESIZE,
    VOLUME_SNAPSHOT_CREATE,
    VOLUME_SNAPSHOT_DELETE,
    VOLUME_SNAPSHOT_UPDATE,
)
from cps.contracts.messages.volume_operations import (
    VolumeAttachmentOperationRequest,
    VolumeOperationRequest,
)
from cps.contracts.messages.volume_snapshot_operations import VolumeSnapshotOperationRequest
from cps.domain.messaging.outbox import OutboxDraft
from cps.domain.operations.create import create_operation_idempotent
from cps.domain.operations.errors import IdempotencyConflictError
from cps.domain.operations.service import OperationService
from cps.infrastructure.db.models.enums import ConnectionScopeKind, ConnectionStatus, OperationState
from cps.infrastructure.db.repositories.inventory import InventoryRepository
from cps.infrastructure.db.repositories.operations import OperationRepository
from cps.infrastructure.db.repositories.outbox import OutboxRepository
from cps.observability.metrics import metrics


def to_view(operation: object) -> OperationView:
    return OperationView.model_validate(operation, from_attributes=True)


class OperationApplicationService:
    def __init__(
        self,
        repository: OperationRepository,
        outbox: OutboxRepository,
        inventory: InventoryRepository | None = None,
    ) -> None:
        self._repository = repository
        self._outbox = outbox
        self._inventory = inventory

    async def create_flavor_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: FlavorCreateRequest
        | FlavorDeleteRequest
        | FlavorAccessReplaceRequest
        | FlavorExtraSpecsPatchRequest,
    ) -> OperationView:
        """Validate and enqueue one explicit system-scoped flavor mutation."""
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        if (
            connection.status is not ConnectionStatus.VALID
            or connection.scope_kind is not ConnectionScopeKind.SYSTEM
        ):
            raise CapabilityUnsupportedError(
                "flavor administration requires a validated SYSTEM connection"
            )

        message_type = {
            FlavorCreateRequest: FLAVOR_CREATE,
            FlavorDeleteRequest: FLAVOR_DELETE,
            FlavorAccessReplaceRequest: FLAVOR_ACCESS_REPLACE,
            FlavorExtraSpecsPatchRequest: FLAVOR_EXTRA_SPECS_PATCH,
        }[type(request)]
        await self._repository.lock_connection_idempotency_key(
            provider_connection_id=connection.id, idempotency_key=idempotency_key
        )
        existing_key = await self._repository.get_by_connection_idempotency_key(
            provider_connection_id=connection.id, idempotency_key=idempotency_key
        )
        if existing_key is not None and existing_key.operation_type != message_type:
            raise IdempotencyKeyReusedError
        feature = {
            FLAVOR_CREATE: "flavor.create",
            FLAVOR_DELETE: "flavor.delete",
            FLAVOR_ACCESS_REPLACE: "flavor.access",
            FLAVOR_EXTRA_SPECS_PATCH: "flavor.extra_specs",
        }[message_type]
        raw_features = (connection.capabilities or {}).get("features", {})
        capability = raw_features.get(feature) if isinstance(raw_features, dict) else None
        if not isinstance(capability, dict) or capability.get("supported") is not True:
            raise CapabilityUnsupportedError
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        if isinstance(request, FlavorCreateRequest):
            if await self._inventory.live_flavor_name_exists_case_insensitive(
                connection.id, request.name
            ):
                raise DomainConflictError("A live flavor already uses this name")
            if (
                request.provider_resource_id
                and await self._inventory.resource_belongs_to_connection(
                    "flavor", connection.id, request.provider_resource_id
                )
            ):
                raise DomainConflictError("A live flavor already uses this provider ID")
            if not await self._inventory.project_provider_ids_belong_to_provider(
                connection.provider_id, request.access_project_ids
            ):
                raise ProviderConnectionNotFoundError
        else:
            flavor_state = await self._inventory.flavor_mutation_state(
                connection.id, request.provider_resource_id
            )
            if flavor_state is None:
                raise ProviderConnectionNotFoundError
            is_public, catalog_approved = flavor_state
            if isinstance(request, FlavorAccessReplaceRequest):
                if is_public:
                    raise DomainConflictError("Public flavor access cannot be replaced")
                if not await self._inventory.project_provider_ids_belong_to_provider(
                    connection.provider_id, request.project_provider_resource_ids
                ):
                    raise ProviderConnectionNotFoundError
            if isinstance(request, FlavorDeleteRequest):
                if catalog_approved:
                    raise DomainConflictError("Approved flavor cannot be deleted")
                if await self._inventory.flavor_is_used_on_provider(
                    connection.provider_id, request.provider_resource_id
                ):
                    raise DomainConflictError("Flavor is referenced by a live instance")

        operation_id = uuid.uuid5(connection.id, f"flavor:{idempotency_key}")
        message_id = uuid.uuid5(operation_id, "flavor-command")
        payload = request.model_dump(
            mode="json", exclude={"schema_version", "operation_id"}
        )
        payload["operation_id"] = str(operation_id)
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": datetime.now(UTC),
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=envelope.occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_validation(
        self, connection_id: uuid.UUID, *, idempotency_key: str, correlation_id: uuid.UUID
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        operation_id = _uuid7()
        message_id = _uuid7()
        occurred_at = datetime.now(UTC)
        request_payload = {"validation_mode": "SAFE_READ_ONLY"}
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": CONNECTION_VALIDATE,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "causation_id": None,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "trace_context": {},
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=CONNECTION_VALIDATE,
            routing_key=CONNECTION_VALIDATE,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=CONNECTION_VALIDATE,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_inventory_sync(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        collections: list[str],
        batch_size: int = 100,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        operation_id = _uuid7()
        sync_id = uuid.uuid5(connection.id, f"inventory-sync:{idempotency_key}")
        message_id = uuid.uuid5(sync_id, "inventory-command")
        occurred_at = datetime.now(UTC)
        request_payload = {
            "sync_id": str(sync_id),
            "collections": collections,
            "batch_size": batch_size,
        }
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": INVENTORY_COLLECT,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=INVENTORY_COLLECT,
            routing_key=INVENTORY_COLLECT,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=INVENTORY_COLLECT,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        existing_sync = await self._inventory.get_sync(
            uuid.UUID(operation.request_payload["sync_id"])
        )
        if existing_sync is None:
            await self._inventory.create_sync(
                sync_id=uuid.UUID(operation.request_payload["sync_id"]),
                operation_id=operation.id,
                provider_connection_id=connection.id,
                sync_type="FULL",
                expected_collections=list(operation.request_payload["collections"]),
            )
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_inventory_refresh(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        resource_type: str,
        provider_resource_id: str,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        operation_id = _uuid7()
        sync_id = uuid.uuid5(
            connection.id,
            f"inventory-refresh:{idempotency_key}:{resource_type}:{provider_resource_id}",
        )
        message_id = uuid.uuid5(sync_id, "inventory-refresh-command")
        occurred_at = datetime.now(UTC)
        request_payload = {
            "sync_id": str(sync_id),
            "resource_type": resource_type,
            "provider_resource_id": provider_resource_id,
        }
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": INVENTORY_REFRESH,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=INVENTORY_REFRESH,
            routing_key=INVENTORY_REFRESH,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=INVENTORY_REFRESH,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        existing_sync = await self._inventory.get_sync(sync_id)
        if existing_sync is None:
            await self._inventory.create_sync(
                sync_id=sync_id,
                operation_id=operation.id,
                provider_connection_id=connection.id,
                sync_type="TARGETED",
                expected_collections=[resource_type],
                target_resource_type=resource_type,
                target_provider_resource_id=provider_resource_id,
            )
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_instance(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: InstanceCreateRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        references: list[tuple[str, str]] = [
            ("flavor", request.flavor_provider_resource_id),
            ("image", request.image_provider_resource_id),
        ]
        references.extend(("network", value) for value in request.network_provider_resource_ids)
        if request.floating_network_provider_resource_id:
            references.append(("network", request.floating_network_provider_resource_id))
        references.extend(("port", value) for value in request.port_provider_resource_ids)
        references.extend(
            ("security_group", value) for value in request.security_group_provider_resource_ids
        )
        if request.key_name and not await self._inventory_resource_name_belongs(
            "keypair", connection.id, request.key_name
        ):
            raise ProviderConnectionNotFoundError
        for resource_type, provider_resource_id in references:
            if resource_type == "security_group":
                continue
            if not await self._inventory_resource_belongs(
                resource_type, connection.id, provider_resource_id
            ):
                raise ProviderConnectionNotFoundError
        for resource_type, provider_resource_id in (
            ("flavor", request.flavor_provider_resource_id),
            ("image", request.image_provider_resource_id),
        ):
            if not await self._inventory_resource_is_catalog_approved(
                resource_type, connection.id, provider_resource_id
            ):
                raise CatalogPolicyViolationError
        if request.availability_zone and not await self._inventory_resource_is_catalog_approved(
            "availability-zone", connection.id, request.availability_zone
        ):
            raise CatalogPolicyViolationError
        operation_id = _uuid7()
        message_id = _uuid7()
        occurred_at = datetime.now(UTC)
        request_payload = {"action": "CREATE", "create": request.model_dump(mode="json")}
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": INSTANCE_CREATE,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=INSTANCE_CREATE,
            routing_key=INSTANCE_CREATE,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=INSTANCE_CREATE,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def _inventory_resource_belongs(
        self, resource_type: str, connection_id: uuid.UUID, provider_resource_id: str
    ) -> bool:
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        return await self._inventory.resource_belongs_to_connection(
            resource_type, connection_id, provider_resource_id
        )

    async def _inventory_resource_name_belongs(
        self, resource_type: str, connection_id: uuid.UUID, name: str
    ) -> bool:
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        return await self._inventory.resource_name_belongs_to_connection(
            resource_type, connection_id, name
        )

    async def _inventory_resource_is_catalog_approved(
        self, resource_type: str, connection_id: uuid.UUID, provider_resource_id: str
    ) -> bool:
        if self._inventory is None:
            raise RuntimeError("inventory repository is required")
        return await self._inventory.catalog_resource_is_approved(
            resource_type, connection_id, provider_resource_id
        )

    async def _volume_snapshot_lifecycle_allowed(
        self,
        connection_id: uuid.UUID,
        provider_resource_id: str,
        *,
        project_provider_resource_id: str | None = None,
    ) -> bool:
        if self._inventory is None:
            return False
        if await self._inventory.resource_belongs_to_connection(
            "volume-snapshot", connection_id, provider_resource_id
        ):
            if project_provider_resource_id is not None:
                rows, _ = await self._inventory.list_resources(
                    "volume-snapshot",
                    provider_connection_id=connection_id,
                    provider_resource_id=provider_resource_id,
                    limit=1,
                    offset=0,
                )
                if rows:
                    row_project = rows[0].project_provider_resource_id
                    if row_project is not None and row_project != project_provider_resource_id:
                        return False
            return True
        return await self._repository.cps_created_volume_snapshot_exists(
            provider_connection_id=connection_id,
            provider_resource_id=provider_resource_id,
            project_provider_resource_id=project_provider_resource_id,
        )

    async def create_instance_action(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        action: InstanceAction,
        instance_provider_resource_id: str,
        reboot_type: str | None = None,
        resize_flavor_provider_resource_id: str | None = None,
        rebuild_image_provider_resource_id: str | None = None,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        if self._inventory is None or not await self._inventory.resource_belongs_to_connection(
            "instance", connection.id, instance_provider_resource_id
        ):
            raise ProviderConnectionNotFoundError
        state_requirements = {
            InstanceAction.RESIZE: {"ACTIVE", "SHUTOFF"},
            InstanceAction.CONFIRM_RESIZE: {"VERIFY_RESIZE"},
            InstanceAction.REVERT_RESIZE: {"VERIFY_RESIZE"},
            InstanceAction.REBUILD: {"ACTIVE", "SHUTOFF"},
        }
        allowed_states = state_requirements.get(action)
        if allowed_states is not None:
            rows, _ = await self._inventory.list_resources(
                "instance",
                provider_connection_id=connection.id,
                provider_resource_id=instance_provider_resource_id,
                limit=1,
                offset=0,
            )
            provider_status = str(rows[0].provider_status or "").upper() if rows else ""
            if provider_status not in allowed_states:
                raise InstanceStateConflictError
        if action is InstanceAction.RESIZE:
            if (
                not resize_flavor_provider_resource_id
                or not await self._inventory_resource_is_catalog_approved(
                    "flavor", connection.id, resize_flavor_provider_resource_id
                )
            ):
                raise CatalogPolicyViolationError
        if action is InstanceAction.REBUILD:
            if (
                not rebuild_image_provider_resource_id
                or not await self._inventory_resource_is_catalog_approved(
                    "image", connection.id, rebuild_image_provider_resource_id
                )
            ):
                raise CatalogPolicyViolationError
        message_types = {
            InstanceAction.GET: INSTANCE_GET,
            InstanceAction.START: INSTANCE_START,
            InstanceAction.STOP: INSTANCE_STOP,
            InstanceAction.REBOOT: INSTANCE_REBOOT,
            InstanceAction.DELETE: INSTANCE_DELETE,
            InstanceAction.RESIZE: INSTANCE_RESIZE,
            InstanceAction.CONFIRM_RESIZE: INSTANCE_CONFIRM_RESIZE,
            InstanceAction.REVERT_RESIZE: INSTANCE_REVERT_RESIZE,
            InstanceAction.REBUILD: INSTANCE_REBUILD,
        }
        message_type = message_types.get(action)
        if message_type is None:
            raise ValueError("unsupported instance action")
        operation_id = _uuid7()
        message_id = _uuid7()
        occurred_at = datetime.now(UTC)
        request_payload = {
            "action": action.value,
            "instance_provider_resource_id": instance_provider_resource_id,
            "reboot_type": reboot_type,
            "resize_flavor_provider_resource_id": resize_flavor_provider_resource_id,
            "rebuild_image_provider_resource_id": rebuild_image_provider_resource_id,
        }
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": request_payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=request_payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_identity_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: IdentityResourceRequest | RoleAssignmentRequest | QuotaRequest,
    ) -> OperationView:
        """Create a typed identity operation with one durable outbox command."""
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None:
            raise ProviderConnectionNotFoundError
        if request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        message_type: str
        payload = request.model_dump(
            mode="json", exclude={"operation_id", "provider_connection_id"}
        )
        if isinstance(request, IdentityResourceRequest) and request.operation.value == "disable":
            payload["enabled"] = False
        if isinstance(request, IdentityResourceRequest):
            prefix = "domain" if request.resource_type == "domain" else "project"
            message_type = {
                ("domain", "create"): IDENTITY_DOMAIN_CREATE,
                ("domain", "update"): IDENTITY_DOMAIN_UPDATE,
                ("domain", "disable"): IDENTITY_DOMAIN_UPDATE,
                ("domain", "delete"): IDENTITY_DOMAIN_DELETE,
                ("project", "create"): IDENTITY_PROJECT_CREATE,
                ("project", "update"): IDENTITY_PROJECT_UPDATE,
                ("project", "disable"): IDENTITY_PROJECT_UPDATE,
                ("project", "delete"): IDENTITY_PROJECT_DELETE,
            }[(prefix, request.operation.value)]
            parameters = {
                key: value
                for key, value in {
                    "name": request.name,
                    "description": request.description,
                    "enabled": request.enabled,
                    "domain_id": request.domain_provider_resource_id,
                }.items()
                if value is not None
            }
            if request.operation is IdentityOperation.DISABLE:
                parameters["enabled"] = False
            payload = {
                "operation_id": str(request.operation_id),
                "resource_type": request.resource_type,
                "operation": "update"
                if request.operation is IdentityOperation.DISABLE
                else request.operation.value,
                "required_scope": request.required_scope.value,
                "provider_connection_id": str(connection.id),
                "provider_resource_id": request.provider_resource_id,
                "parameters": parameters,
            }
            if request.binding_id is not None:
                parameters["binding_id"] = str(request.binding_id)
                if request.org_id is not None:
                    parameters["org_id"] = request.org_id
                if request.workspace_id is not None:
                    parameters["workspace_id"] = request.workspace_id
        elif isinstance(request, RoleAssignmentRequest):
            message_type = (
                IDENTITY_ROLE_ENSURE if request.operation == "ensure" else IDENTITY_ROLE_REVOKE
            )
            payload = {
                "operation_id": str(request.operation_id),
                "resource_type": "role_assignment",
                "operation": request.operation,
                "required_scope": request.required_scope.value,
                "provider_connection_id": str(connection.id),
                "provider_resource_id": None,
                "parameters": {
                    "role": request.role_provider_resource_id,
                    "user": request.principal_provider_resource_id
                    if request.principal_type == "user"
                    else None,
                    "group": request.principal_provider_resource_id
                    if request.principal_type == "group"
                    else None,
                    "project": request.scope_provider_resource_id
                    if request.required_scope is ScopeKind.PROJECT
                    else None,
                    "domain": request.scope_provider_resource_id
                    if request.required_scope is ScopeKind.DOMAIN
                    else None,
                },
            }
        else:
            message_type = (
                IDENTITY_QUOTA_READ if request.operation == "read" else IDENTITY_QUOTA_UPDATE
            )
            quota_parameters: dict[str, object] = {
                "service": request.service.replace("-", "_"),
                "project_id": request.project_provider_resource_id,
            }
            quota_parameters.update({item.resource_name: item.limit for item in request.quotas})
            payload = {
                "operation_id": str(request.operation_id),
                "resource_type": "quota",
                "operation": request.operation,
                "required_scope": request.required_scope.value,
                "provider_connection_id": str(connection.id),
                "provider_resource_id": request.project_provider_resource_id,
                "parameters": quota_parameters,
            }
        operation_id = request.operation_id
        message_id = _uuid7()
        occurred_at = datetime.now(UTC)
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        metrics.increment("cps_operations_created_total")
        return to_view(operation)

    async def create_network_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: NetworkOperationRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        await self._validate_network_operation_policy(connection.id, request)
        table = {
            ("network", "create"): NETWORK_CREATE,
            ("network", "update"): NETWORK_UPDATE,
            ("network", "delete"): NETWORK_DELETE,
            ("subnet", "create"): SUBNET_CREATE,
            ("subnet", "update"): SUBNET_UPDATE,
            ("subnet", "delete"): SUBNET_DELETE,
            ("router", "create"): ROUTER_CREATE,
            ("router", "update"): ROUTER_UPDATE,
            ("router", "delete"): ROUTER_DELETE,
            ("router-interface", "ensure"): ROUTER_INTERFACE_ENSURE,
            ("router-interface", "remove"): ROUTER_INTERFACE_REMOVE,
            ("port", "create"): PORT_CREATE,
            ("port", "update"): PORT_UPDATE,
            ("port", "delete"): PORT_DELETE,
            ("security-group", "create"): SECURITY_GROUP_CREATE,
            ("security-group", "update"): SECURITY_GROUP_UPDATE,
            ("security-group", "delete"): SECURITY_GROUP_DELETE,
            ("security-group-rule", "create"): SECURITY_GROUP_RULE_CREATE,
            ("security-group-rule", "delete"): SECURITY_GROUP_RULE_DELETE,
            ("floating-ip", "allocate"): FLOATING_IP_ALLOCATE,
            ("floating-ip", "associate"): FLOATING_IP_ASSOCIATE,
            ("floating-ip", "disassociate"): FLOATING_IP_DISASSOCIATE,
            ("floating-ip", "release"): FLOATING_IP_RELEASE,
        }
        message_type = table.get((request.resource_type.value, request.operation.value))
        if message_type is None:
            raise ValueError("unsupported network resource/action")
        parameters = dict(request.parameters)
        relationship_parameters = {
            "network_id": request.network_provider_resource_id,
            "subnet_id": request.subnet_provider_resource_id,
            "project_id": request.project_provider_resource_id,
            "port_id": request.port_provider_resource_id,
        }
        parameters.update({key: value for key, value in relationship_parameters.items() if value})
        operation_id = request.operation_id
        message_id = _uuid7()
        payload = {
            "operation_id": str(operation_id),
            "resource_type": request.resource_type.value,
            "operation": request.operation.value,
            "required_scope": request.required_scope.value,
            "provider_connection_id": str(connection.id),
            "provider_resource_id": request.provider_resource_id,
            "parameters": parameters,
        }
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": datetime.now(UTC),
                "correlation_id": correlation_id,
                "causation_id": None,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=datetime.now(UTC),
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def _validate_network_operation_policy(
        self,
        connection_id: uuid.UUID,
        request: NetworkOperationRequest,
    ) -> None:
        if self._inventory is None:
            raise NetworkPolicyViolationError
        resource_type = request.resource_type.value
        inventory_type = resource_type.replace("router-interface", "router")
        if (
            request.operation.value in {"create", "allocate"}
            and not request.project_provider_resource_id
        ):
            raise NetworkPolicyViolationError
        if request.provider_resource_id and resource_type != "router-interface":
            if not await self._inventory.resource_belongs_to_connection(
                inventory_type, connection_id, request.provider_resource_id
            ):
                raise ProviderConnectionNotFoundError
        if (
            request.provider_resource_id
            and resource_type == "router-interface"
            and not await self._inventory.resource_belongs_to_connection(
                "router", connection_id, request.provider_resource_id
            )
        ):
            raise ProviderConnectionNotFoundError
        references = (
            ("network", request.network_provider_resource_id),
            ("subnet", request.subnet_provider_resource_id),
            ("port", request.port_provider_resource_id),
        )
        for reference_type, provider_resource_id in references:
            if provider_resource_id and not await self._inventory.resource_belongs_to_connection(
                reference_type, connection_id, provider_resource_id
            ):
                raise ProviderConnectionNotFoundError
            if (
                provider_resource_id
                and request.project_provider_resource_id
                and not (
                    resource_type == "floating-ip"
                    and request.operation.value == "allocate"
                    and reference_type == "network"
                )
            ):
                rows, _ = await self._inventory.list_resources(
                    reference_type,
                    provider_connection_id=connection_id,
                    provider_resource_id=provider_resource_id,
                    offset=0,
                    limit=1,
                )
                owner = getattr(rows[0], "project_provider_resource_id", None) if rows else None
                if owner and owner != request.project_provider_resource_id:
                    raise ProviderConnectionNotFoundError
        if (
            resource_type == "floating-ip"
            and request.operation.value == "allocate"
            and request.network_provider_resource_id
            and not await self._inventory.catalog_resource_is_approved(
                "network", connection_id, request.network_provider_resource_id
            )
        ):
            raise CatalogPolicyViolationError
        if resource_type == "subnet" and request.operation.value == "create":
            requested = ipaddress.ip_network(str(request.parameters["cidr"]), strict=True)
            rows, _ = await self._inventory.list_resources(
                "subnet",
                provider_connection_id=connection_id,
                project_provider_resource_id=request.project_provider_resource_id,
                offset=0,
                limit=1000,
            )
            for row in rows:
                existing_cidr = (row.provider_attributes or {}).get("cidr")
                if isinstance(existing_cidr, str):
                    try:
                        existing = ipaddress.ip_network(existing_cidr, strict=False)
                    except ValueError:
                        continue
                    if requested.version == existing.version and requested.overlaps(existing):
                        raise NetworkPolicyViolationError
        quota_resource = {
            "network": "networks",
            "subnet": "subnets",
            "router": "routers",
            "port": "ports",
            "security-group": "security_groups",
            "security-group-rule": "security_group_rules",
            "floating-ip": "floating_ips",
        }.get(resource_type)
        if request.operation.value in {"create", "allocate"} and quota_resource:
            rows, _ = await self._inventory.list_resources(
                "quota",
                provider_connection_id=connection_id,
                project_provider_resource_id=request.project_provider_resource_id,
                offset=0,
                limit=1000,
            )
            for row in rows:
                if (
                    row.service == "network"
                    and row.resource_name.replace("-", "_") == quota_resource
                    and not row.unlimited
                    and row.limit_value is not None
                    and (row.in_use or 0) >= row.limit_value
                ):
                    raise NetworkQuotaExceededError

    async def create_volume_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: VolumeOperationRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError

        message_type = {
            "create": VOLUME_CREATE,
            "resize": VOLUME_RESIZE,
            "delete": VOLUME_DELETE,
        }.get(request.operation.value)
        if message_type is None:
            raise ValueError("unsupported volume operation")
        if request.operation.value == "create":
            catalog_references = (
                ("volume-type", request.volume_type_provider_resource_id),
                ("availability-zone", request.availability_zone),
            )
            for resource_type, provider_resource_id in catalog_references:
                if provider_resource_id and not await self._inventory_resource_is_catalog_approved(
                    resource_type, connection.id, provider_resource_id
                ):
                    raise CatalogPolicyViolationError

        parameters = dict(request.parameters)
        for field in (
            "name",
            "size_gib",
            "volume_type_provider_resource_id",
            "availability_zone",
            "metadata",
            "project_provider_resource_id",
            "source_snapshot_provider_resource_id",
        ):
            value = getattr(request, field)
            if value is not None:
                parameters[field] = value
        if request.project_provider_resource_id:
            parameters["ownership"] = {
                "project_provider_resource_id": request.project_provider_resource_id
            }

        operation_id = uuid.uuid5(connection.id, f"volume-operation:{idempotency_key}")
        message_id = uuid.uuid5(operation_id, "volume-command")

        payload = {
            "operation_id": str(operation_id),
            "resource_type": "volume",
            "operation": request.operation.value,
            "required_scope": request.required_scope.value,
            "provider_connection_id": str(connection.id),
            "provider_resource_id": request.provider_resource_id,
            "parameters": parameters,
        }
        occurred_at = datetime.now(UTC)
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "causation_id": None,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def create_volume_attachment_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: VolumeAttachmentOperationRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        message_type = VOLUME_ATTACH if request.operation.value == "attach" else VOLUME_DETACH
        operation_id = uuid.uuid5(connection.id, f"volume-attachment:{idempotency_key}")
        message_id = uuid.uuid5(operation_id, "volume-attachment-command")
        parameters = {
            "server_id": request.instance_provider_resource_id,
            "volume_id": request.volume_provider_resource_id,
        }
        if request.project_provider_resource_id:
            parameters["project_provider_resource_id"] = request.project_provider_resource_id
        payload = {
            "operation_id": str(operation_id),
            "resource_type": "volume-attachment",
            "operation": request.operation.value,
            "required_scope": request.required_scope.value,
            "provider_connection_id": str(connection.id),
            "parameters": parameters,
        }
        occurred_at = datetime.now(UTC)
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": occurred_at,
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def create_volume_snapshot_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: VolumeSnapshotOperationRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        if request.operation.value in {"update", "delete"}:
            if not request.provider_resource_id:
                raise ProviderConnectionNotFoundError
            if not await self._volume_snapshot_lifecycle_allowed(
                connection.id,
                request.provider_resource_id,
                project_provider_resource_id=request.project_provider_resource_id,
            ):
                raise ProviderConnectionNotFoundError
        message_type = {
            "create": VOLUME_SNAPSHOT_CREATE,
            "update": VOLUME_SNAPSHOT_UPDATE,
            "delete": VOLUME_SNAPSHOT_DELETE,
        }[request.operation.value]
        operation_id = uuid.uuid5(connection.id, f"volume-snapshot:{idempotency_key}")
        message_id = uuid.uuid5(operation_id, "volume-snapshot-command")
        parameters = dict(request.parameters)
        if request.volume_provider_resource_id:
            parameters["volume_id"] = request.volume_provider_resource_id
        if request.project_provider_resource_id:
            parameters["project_provider_resource_id"] = request.project_provider_resource_id
        payload_parameters = parameters
        payload = {
            "operation_id": str(operation_id),
            "resource_type": "snapshot",
            "operation": request.operation.value,
            "required_scope": request.required_scope.value,
            "provider_connection_id": str(connection.id),
            "provider_resource_id": request.provider_resource_id,
            "parameters": payload_parameters,
        }
        if request.operation.value == "create":
            payload_parameters["name"] = request.name
        elif request.name:
            payload_parameters["name"] = request.name
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": datetime.now(UTC),
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=envelope.occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def create_keypair_operation(
        self,
        connection_id: uuid.UUID,
        *,
        idempotency_key: str,
        correlation_id: uuid.UUID,
        request: KeypairOperationRequest,
    ) -> OperationView:
        connection = await self._repository.get_provider_connection(connection_id)
        if connection is None or request.provider_connection_id != connection.id:
            raise ProviderConnectionNotFoundError
        if request.operation.value == "delete":
            if self._inventory is None or not request.provider_resource_id:
                raise ProviderConnectionNotFoundError
            if not await self._inventory.resource_belongs_to_connection(
                "keypair", connection.id, request.provider_resource_id
            ):
                raise ProviderConnectionNotFoundError
        message_type = KEYPAIR_IMPORT if request.operation.value == "import" else KEYPAIR_DELETE
        operation_id = uuid.uuid5(connection.id, f"keypair:{idempotency_key}")
        message_id = uuid.uuid5(operation_id, "keypair-command")
        parameters = dict(request.parameters)
        if request.project_provider_resource_id:
            parameters["project_provider_resource_id"] = request.project_provider_resource_id
        if request.name:
            parameters["name"] = request.name
        if request.public_key:
            parameters["public_key"] = request.public_key
        payload = {
            "operation_id": str(operation_id),
            "resource_type": "keypair",
            "operation": "create" if request.operation.value == "import" else "delete",
            "required_scope": request.required_scope.value,
            "provider_connection_id": str(connection.id),
            "provider_resource_id": request.provider_resource_id,
            "parameters": parameters,
        }
        envelope = MessageEnvelope.model_validate(
            {
                "message_id": message_id,
                "message_type": message_type,
                "schema_version": "1.0",
                "occurred_at": datetime.now(UTC),
                "correlation_id": correlation_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "provider_id": connection.provider_id,
                "provider_connection_id": connection.id,
                "payload": payload,
            }
        )
        draft = OutboxDraft(
            aggregate_type="operation",
            aggregate_id=operation_id,
            message_id=message_id,
            message_type=message_type,
            routing_key=message_type,
            payload=envelope.model_dump(mode="json"),
            correlation_id=correlation_id,
            occurred_at=envelope.occurred_at,
        )
        try:
            operation = await create_operation_idempotent(
                self._repository,
                provider_connection_id=connection.id,
                operation_type=message_type,
                request_payload=payload,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                outbox_repository=self._outbox,
                outbox_draft=draft,
            )
        except IdempotencyConflictError as exc:
            raise IdempotencyKeyReusedError from exc
        if operation.state == OperationState.ACCEPTED:
            operation = await OperationService(self._repository).transition_operation(
                operation_id=operation.id,
                expected_version=operation.version,
                to_state=OperationState.QUEUED,
                details={"status": "QUEUED"},
                message_id=message_id,
            )
        return to_view(operation)

    async def get(self, operation_id: uuid.UUID) -> OperationView:
        operation = await self._repository.get_operation(operation_id)
        if operation is None:
            raise OperationNotFoundPublicError
        return to_view(operation)

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        connection_id: uuid.UUID | None = None,
        operation_type: str | None = None,
        state: OperationState | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> OperationPage:
        rows, total = await self._repository.list_operations(
            offset=offset,
            limit=limit,
            provider_connection_id=connection_id,
            operation_type=operation_type,
            state=state,
            created_from=created_from,
            created_to=created_to,
        )
        return OperationPage(
            items=[to_view(row) for row in rows],
            page=OperationPageInfo(offset=offset, limit=limit, total=total),
        )

    async def events(
        self, operation_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> OperationEventPage:
        if await self._repository.get_operation(operation_id) is None:
            raise OperationNotFoundPublicError
        rows = await self._repository.get_events(operation_id)
        items = [
            OperationEventView.model_validate(
                {
                    "id": event.id,
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "from_state": event.from_state,
                    "to_state": event.to_state,
                    "message_id": event.message_id,
                    "details": event.details,
                    "occurred_at": event.occurred_at,
                }
            )
            for event in rows[offset : offset + limit]
        ]
        return OperationEventPage(
            items=items,
            page=OperationPageInfo(offset=offset, limit=limit, total=len(rows)),
        )

    async def audit(self, operation_id: uuid.UUID) -> dict[str, object]:
        operation = await self._repository.get_operation(operation_id)
        if operation is None:
            raise OperationNotFoundPublicError
        events = await self._repository.get_events(operation_id)
        return project_operation_audit(operation, events)


def _uuid7() -> uuid.UUID:
    from cps.identifiers import new_uuid7

    return new_uuid7()
