"""CPS-002: secret redaction in structured logs."""

from __future__ import annotations

from cps.observability.redaction import redact_mapping, redact_text


def test_redact_mapping_masks_secret_fields() -> None:
    payload = {
        "password": "super-secret",
        "token": "tok-123",
        "Authorization": "Bearer abc",
        "user_data": "#!/bin/bash\necho hi",
        "safe": "ok",
        "nested": {"password": "nested-secret", "name": "vm-1"},
    }

    redacted = redact_mapping(payload)

    assert redacted["password"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["user_data"] == "[REDACTED]"
    assert redacted["safe"] == "ok"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["name"] == "vm-1"


def test_redact_text_masks_authorization_header_values() -> None:
    text = 'Authorization: Bearer secret-token password="p@ss"'
    assert "secret-token" not in redact_text(text)
    assert "p@ss" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)
