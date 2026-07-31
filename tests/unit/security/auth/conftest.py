"""Shared helpers for Keycloak auth unit tests."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@dataclass(frozen=True)
class TestSigningMaterial:
    private_pem: bytes
    public_pem: bytes
    kid: str


def generate_signing_material() -> TestSigningMaterial:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return TestSigningMaterial(private_pem=private_pem, public_pem=public_pem, kid="test-key")


def build_token(
    material: TestSigningMaterial,
    *,
    issuer: str,
    client_id: str = "cmp",
    roles: list[str] | None = None,
    subject: str | None = None,
    audience: str | list[str] | None = "cmp",
    expired: bool = False,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject or str(uuid.uuid4()),
        "iss": issuer,
        "iat": now,
        "exp": now - 60 if expired else now + 3600,
        "preferred_username": "test-user@example.com",
        "resource_access": {client_id: {"roles": roles or ["admin"]}},
    }
    if audience is not None:
        payload["aud"] = audience
    return jwt.encode(
        payload,
        material.private_pem,
        algorithm="RS256",
        headers={"kid": material.kid},
    )
