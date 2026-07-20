"""Runtime helpers shared by CLI and tests."""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop_policy() -> None:
    """Prefer SelectorEventLoop on Windows for psycopg async compatibility."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
