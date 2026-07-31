"""Shared pagination query resolution for public list endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

from cps.contracts.errors import InvalidRequestError


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """Resolved pagination inputs for repository queries and BMS page metadata."""

    offset: int
    limit: int
    page: int


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
    """
    if offset is not None and page is not None:
        raise InvalidRequestError("Specify either offset or page, not both")
    safe_limit = min(limit, 200)
    if page is not None:
        resolved_offset = (page - 1) * safe_limit
        resolved_page = page
    else:
        resolved_offset = offset or 0
        resolved_page = (resolved_offset // safe_limit) + 1
    return PaginationParams(offset=resolved_offset, limit=safe_limit, page=resolved_page)
