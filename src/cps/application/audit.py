"""LMS-independent, safe audit projection for cloud operations."""

from __future__ import annotations

from typing import Any


def project_operation_audit(operation: Any, events: list[Any]) -> dict[str, Any]:
    request = operation.request_payload if isinstance(operation.request_payload, dict) else {}
    action = request.get("action") or operation.operation_type
    target = request.get("instance_provider_resource_id")
    if target is None:
        target = request.get("resource_type") or request.get("sync_id")
    return {
        "operation_id": str(operation.id),
        "provider_connection_id": str(operation.provider_connection_id),
        "correlation_id": str(operation.correlation_id),
        "operation_type": operation.operation_type,
        "action": action,
        "target": target,
        "state": operation.state,
        "outcome": "error" if operation.error_payload else operation.state,
        "provider_request_id": operation.provider_request_id,
        "event_count": len(events),
        "updated_at": operation.updated_at,
    }
