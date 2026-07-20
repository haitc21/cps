"""service_name must appear in structured log output."""

from __future__ import annotations

import json
import logging
from io import StringIO

from cps.observability.logging import configure_logging


def test_configure_logging_applies_custom_service_name() -> None:
    stream = StringIO()
    configure_logging(level="INFO", service_name="custom-cps")
    root = logging.getLogger()
    assert root.handlers, "configure_logging must install a handler"
    root.handlers[0].setStream(stream)

    logging.getLogger("cps.test").info("hello")

    payload = json.loads(stream.getvalue().strip())
    assert payload["service"] == "custom-cps"
    assert payload["message"] == "hello"
