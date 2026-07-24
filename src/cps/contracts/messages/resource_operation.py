"""Backward-compatible singular import for scoped resource contracts."""

from cps.contracts.messages.resource_operations import (
    ResourceOperationRequest,
    ResourceOperationResult,
    ResourceOperationState,
    ScopeKind,
)

__all__ = [
    "ResourceOperationRequest",
    "ResourceOperationResult",
    "ResourceOperationState",
    "ScopeKind",
]
