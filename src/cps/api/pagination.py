"""Shared pagination query resolution for public list endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from cps.contracts.errors import InvalidRequestError

# Maximum list offset for catalog queries (page/offset amplification guard).
MAX_CATALOG_OFFSET = 100_000


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """Resolved pagination inputs for repository queries and BMS page metadata."""

    offset: int
    limit: int
    page: int


def _resolve_pagination_inputs(
    *,
    offset: int | None,
    page: int | None,
    limit: int,
    max_offset: int | None,
) -> PaginationParams:
    if offset is not None and page is not None:
        raise InvalidRequestError("Specify either offset or page, not both")
    safe_limit = min(limit, 200)
    if page is not None:
        resolved_offset = (page - 1) * safe_limit
        resolved_page = page
    else:
        resolved_offset = offset or 0
        resolved_page = (resolved_offset // safe_limit) + 1
    if max_offset is not None and resolved_offset > max_offset:
        raise InvalidRequestError(
            f"Pagination offset exceeds maximum allowed value of {max_offset}"
        )
    return PaginationParams(offset=resolved_offset, limit=safe_limit, page=resolved_page)


def resolve_pagination(
    *,
    offset: int | None = Query(default=None, ge=0),  # noqa: B008
    page: int | None = Query(default=None, ge=1),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
) -> PaginationParams:
    """Accept legacy ``offset`` or canonical 1-based ``page``; never both.

    Responses always emit canonical ``page``, ``limit``, ``total``, and
    ``totalPages``. ``offset`` remains accepted for one release cycle and is
    converted with ``page = (offset // limit) + 1``.

    Legacy provider, connection, inventory, and operation list routes keep the
    historical uncapped offset behavior.
    """
    return _resolve_pagination_inputs(
        offset=offset,
        page=page,
        limit=limit,
        max_offset=None,
    )


def resolve_catalog_pagination(
    *,
    offset: int | None = Query(default=None, ge=0),  # noqa: B008
    page: int | None = Query(default=None, ge=1),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
) -> PaginationParams:
    """Catalog-only pagination with ``MAX_CATALOG_OFFSET`` amplification guard."""
    return _resolve_pagination_inputs(
        offset=offset,
        page=page,
        limit=limit,
        max_offset=MAX_CATALOG_OFFSET,
    )
