"""CPS-103 Task 3: UUIDv7 identifier boundary tests."""

from __future__ import annotations

import uuid

import pytest

from cps.identifiers import new_uuid7


def test_new_uuid7_returns_uuid_instance() -> None:
    generated = new_uuid7()
    assert isinstance(generated, uuid.UUID)


def test_new_uuid7_has_version_seven() -> None:
    assert new_uuid7().version == 7


def test_new_uuid7_has_rfc4122_variant() -> None:
    assert new_uuid7().variant == uuid.RFC_4122


def test_new_uuid7_generates_unique_values() -> None:
    values = {new_uuid7() for _ in range(32)}
    assert len(values) == 32


def test_new_uuid7_is_monotonic_without_timing_assertion() -> None:
    first = new_uuid7()
    second = new_uuid7()
    assert int(first) <= int(second)


def test_repository_module_uses_identifier_boundary_only() -> None:
    repository_source = (
        pytest.importorskip("importlib")
        .import_module("cps.infrastructure.db.repositories.providers")
        .__file__
    )
    assert repository_source is not None
    contents = open(repository_source, encoding="utf-8").read()
    assert "uuid6" not in contents
    assert "uuid7(" not in contents.replace("new_uuid7(", "")
