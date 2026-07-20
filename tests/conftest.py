"""Shared pytest configuration for CPS."""

from __future__ import annotations

from cps.runtime import configure_event_loop_policy

configure_event_loop_policy()
