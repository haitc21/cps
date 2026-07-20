"""Unit tests for disposable database identifier limits."""

from __future__ import annotations

import pytest

from tests.integration.db.disposable_database import (
    DisposableDatabaseError,
    generate_database_name,
)

MAX_BYTES = 63


def test_long_worker_id_is_rejected() -> None:
    long_worker = "w" * 50
    with pytest.raises(DisposableDatabaseError, match="exceeds PostgreSQL identifier limit"):
        generate_database_name(worker_id=long_worker, suffix="abc123")


def test_long_suffix_is_rejected() -> None:
    long_suffix = "s" * 51
    with pytest.raises(DisposableDatabaseError, match="exceeds PostgreSQL identifier limit"):
        generate_database_name(worker_id="gw0", suffix=long_suffix)


def test_name_at_63_bytes_passes() -> None:
    # cps_test_ (9) + w (1) + _ (1) + 52 suffix chars = 63
    suffix = "a" * 52
    name = generate_database_name(worker_id="w", suffix=suffix)
    assert len(name) == MAX_BYTES


def test_name_at_64_bytes_fails() -> None:
    suffix = "a" * 53
    with pytest.raises(DisposableDatabaseError, match="exceeds PostgreSQL identifier limit"):
        generate_database_name(worker_id="w", suffix=suffix)


def test_different_long_inputs_do_not_collide_after_rejection() -> None:
    first_suffix = "a" * 51
    second_suffix = "b" * 51
    with pytest.raises(DisposableDatabaseError):
        generate_database_name(worker_id="gw0", suffix=first_suffix)
    with pytest.raises(DisposableDatabaseError):
        generate_database_name(worker_id="gw1", suffix=second_suffix)


def test_default_readable_name_stays_under_limit() -> None:
    name = generate_database_name(worker_id="master", suffix="0123456789abcdef")
    assert name == "cps_test_master_0123456789abcdef"
    assert len(name) <= MAX_BYTES
