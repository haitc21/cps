"""Pagination query compatibility tests."""

from __future__ import annotations

import pytest

from cps.api.pagination import (
    MAX_CATALOG_OFFSET,
    resolve_catalog_pagination,
    resolve_pagination,
)
from cps.contracts.errors import InvalidRequestError


def test_offset_defaults_to_first_page() -> None:
    params = resolve_pagination(offset=None, page=None, limit=50)
    assert (params.offset, params.limit, params.page) == (0, 50, 1)


def test_legacy_offset_maps_to_page() -> None:
    params = resolve_pagination(offset=100, page=None, limit=25)
    assert params.offset == 100
    assert params.page == 5


def test_page_query_maps_to_offset() -> None:
    params = resolve_pagination(offset=None, page=3, limit=20)
    assert params.offset == 40
    assert params.page == 3


def test_offset_and_page_together_are_rejected() -> None:
    with pytest.raises(InvalidRequestError, match="offset or page"):
        resolve_pagination(offset=10, page=2, limit=50)


@pytest.mark.parametrize(
    "large_offset",
    [MAX_CATALOG_OFFSET + 1, MAX_CATALOG_OFFSET + 50_000],
)
def test_legacy_pagination_accepts_offset_above_catalog_max(large_offset: int) -> None:
    """Provider, connection, inventory, and operation lists keep uncapped legacy behavior."""
    params = resolve_pagination(offset=large_offset, page=None, limit=50)
    assert params.offset == large_offset


def test_catalog_offset_exceeding_maximum_is_rejected() -> None:
    with pytest.raises(InvalidRequestError, match=str(MAX_CATALOG_OFFSET)):
        resolve_catalog_pagination(offset=MAX_CATALOG_OFFSET + 1, page=None, limit=50)


def test_catalog_page_exceeding_maximum_offset_is_rejected() -> None:
    excessive_page = (MAX_CATALOG_OFFSET // 50) + 2
    with pytest.raises(InvalidRequestError, match=str(MAX_CATALOG_OFFSET)):
        resolve_catalog_pagination(offset=None, page=excessive_page, limit=50)
