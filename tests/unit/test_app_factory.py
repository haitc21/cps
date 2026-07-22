"""CPS-001: application factory acceptance tests."""

from __future__ import annotations

import importlib.metadata
import sys

import pytest
from fastapi import FastAPI


def test_runtime_is_cpython_3_12() -> None:
    assert sys.version_info[:2] == (3, 12)


def test_create_app_returns_fastapi_application() -> None:
    from cps.main import create_app

    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.title == "CPS"


def test_internal_resolver_has_a_separate_listener_surface() -> None:
    from cps.main import create_app, create_internal_app

    public_paths = set(create_app().openapi()["paths"])
    internal_paths = {
        route.path
        for included in create_internal_app().routes
        for route in getattr(getattr(included, "original_router", None), "routes", ())
    }

    assert "/internal/v1/credentials/{credential_reference}" not in public_paths
    assert "/internal/v1/credentials/{credential_reference}" in internal_paths
    assert "/api/v1/providers" not in internal_paths


def test_dependencies_exclude_openstacksdk() -> None:
    names = {dist.metadata["Name"].lower() for dist in importlib.metadata.distributions()}
    assert "openstacksdk" not in names
    assert "python-openstacksdk" not in names


def test_cli_main_exposes_help(capsys: pytest.CaptureFixture[str]) -> None:
    from cps.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "cps" in captured.out.lower() or "usage" in captured.out.lower()


def test_cli_supports_private_listener_mode() -> None:
    from cps.cli import build_parser

    args = build_parser().parse_args(["serve", "--internal", "--port", "8001"])

    assert args.internal is True
    assert args.port == 8001
