"""Pagination query compatibility tests."""

from __future__ import annotations

import pytest

from cps.api.pagination import resolve_pagination
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
