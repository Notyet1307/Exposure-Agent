"""Small authenticated-encryption primitives for model connection Secrets."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_NONCE_BYTES = 12
_MASTER_KEY_BYTES = 32
_SCHEMA = b"exposure-agent:model-connection-secret:v1"


class ModelConnectionSecretError(Exception):
    """A deliberately non-diagnostic Secret boundary failure."""

    code = "model_connection_secret_unavailable"


@dataclass(frozen=True)
class EncryptedModelConnectionSecret:
    nonce: bytes
    ciphertext: bytes


def _master_key(*, key_directory: Path, key_id: str) -> bytes:
    if not _KEY_ID.fullmatch(key_id):
        raise ModelConnectionSecretError()
    try:
        directory = os.open(key_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.fstat(directory).st_mode & 0o022:
                raise ModelConnectionSecretError()
            descriptor = os.open(
                f"{key_id}.key", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory
            )
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                    raise ModelConnectionSecretError()
                key = os.read(descriptor, _MASTER_KEY_BYTES + 1)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
    except OSError, ModelConnectionSecretError:
        raise ModelConnectionSecretError() from None
    if len(key) != _MASTER_KEY_BYTES:
        raise ModelConnectionSecretError()
    return key


def _aad(
    *, tenant_id: uuid.UUID, connection_id: uuid.UUID, secret_id: uuid.UUID
) -> bytes:
    return b"|".join((_SCHEMA, tenant_id.bytes, connection_id.bytes, secret_id.bytes))


def encrypt_model_connection_secret(
    plaintext: bytes,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    secret_id: uuid.UUID,
    key_directory: Path,
    key_id: str,
) -> EncryptedModelConnectionSecret:
    if not isinstance(plaintext, bytes):
        raise ModelConnectionSecretError()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(
        _master_key(key_directory=key_directory, key_id=key_id)
    ).encrypt(
        nonce,
        plaintext,
        _aad(tenant_id=tenant_id, connection_id=connection_id, secret_id=secret_id),
    )
    return EncryptedModelConnectionSecret(nonce=nonce, ciphertext=ciphertext)


def decrypt_model_connection_secret(
    encrypted: EncryptedModelConnectionSecret,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    secret_id: uuid.UUID,
    key_directory: Path,
    key_id: str,
) -> bytes:
    if (
        not isinstance(encrypted.nonce, bytes)
        or len(encrypted.nonce) != _NONCE_BYTES
        or not isinstance(encrypted.ciphertext, bytes)
    ):
        raise ModelConnectionSecretError()
    try:
        return AESGCM(_master_key(key_directory=key_directory, key_id=key_id)).decrypt(
            encrypted.nonce,
            encrypted.ciphertext,
            _aad(
                tenant_id=tenant_id,
                connection_id=connection_id,
                secret_id=secret_id,
            ),
        )
    except InvalidTag, ValueError:
        raise ModelConnectionSecretError() from None


def model_connection_operation_fingerprint(
    payload: bytes,
    *,
    operation: str,
    key_directory: Path,
    key_id: str,
) -> str:
    if not isinstance(payload, bytes) or not _KEY_ID.fullmatch(operation):
        raise ModelConnectionSecretError()
    return hmac.new(
        _master_key(key_directory=key_directory, key_id=key_id),
        b"exposure-agent:model-connection-operation:v1|"
        + operation.encode()
        + b"|"
        + payload,
        hashlib.sha256,
    ).hexdigest()
