import os
import uuid
from pathlib import Path

import pytest

from app.domain.model_connection_secrets import (
    ModelConnectionSecretError,
    decrypt_model_connection_secret,
    encrypt_model_connection_secret,
    model_connection_operation_fingerprint,
)


@pytest.fixture
def key_directory(tmp_path: Path) -> Path:
    path = tmp_path / "keys"
    path.mkdir(mode=0o700)
    key = path / "primary.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    return path


def _ids() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_round_trip_uses_fresh_nonce_and_bound_aad(key_directory: Path) -> None:
    tenant, connection, secret = _ids()
    first = encrypt_model_connection_secret(
        b"secret",
        tenant_id=tenant,
        connection_id=connection,
        secret_id=secret,
        key_directory=key_directory,
        key_id="primary",
    )
    second = encrypt_model_connection_secret(
        b"secret",
        tenant_id=tenant,
        connection_id=connection,
        secret_id=secret,
        key_directory=key_directory,
        key_id="primary",
    )
    assert first.nonce != second.nonce
    assert (
        decrypt_model_connection_secret(
            first,
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="primary",
        )
        == b"secret"
    )


@pytest.mark.parametrize("moved", ["tenant", "connection", "secret"])
def test_aad_rejects_cross_scope_moves(key_directory: Path, moved: str) -> None:
    tenant, connection, secret = _ids()
    plaintext = b"highly-confidential-value"
    encrypted = encrypt_model_connection_secret(
        plaintext,
        tenant_id=tenant,
        connection_id=connection,
        secret_id=secret,
        key_directory=key_directory,
        key_id="primary",
    )
    values = {"tenant": tenant, "connection": connection, "secret": secret}
    values[moved] = uuid.uuid4()
    with pytest.raises(ModelConnectionSecretError):
        decrypt_model_connection_secret(
            encrypted,
            tenant_id=values["tenant"],
            connection_id=values["connection"],
            secret_id=values["secret"],
            key_directory=key_directory,
            key_id="primary",
        )


def test_tamper_and_key_file_fail_without_secret_leakage(key_directory: Path) -> None:
    tenant, connection, secret = _ids()
    plaintext = b"highly-confidential-value"
    encrypted = encrypt_model_connection_secret(
        plaintext,
        tenant_id=tenant,
        connection_id=connection,
        secret_id=secret,
        key_directory=key_directory,
        key_id="primary",
    )
    tampered = encrypted.__class__(
        nonce=encrypted.nonce, ciphertext=encrypted.ciphertext[:-1] + b"x"
    )
    with pytest.raises(ModelConnectionSecretError) as error:
        decrypt_model_connection_secret(
            tampered,
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="primary",
        )
    assert plaintext.decode() not in str(error.value)
    (key_directory / "primary.key").chmod(0o644)
    with pytest.raises(ModelConnectionSecretError):
        encrypt_model_connection_secret(
            b"secret",
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="primary",
        )


def test_missing_invalid_and_symlink_keys_are_rejected(key_directory: Path) -> None:
    tenant, connection, secret = _ids()
    with pytest.raises(ModelConnectionSecretError):
        encrypt_model_connection_secret(
            b"secret",
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="missing",
        )
    (key_directory / "short.key").write_bytes(b"s" * 31)
    (key_directory / "short.key").chmod(0o600)
    with pytest.raises(ModelConnectionSecretError):
        encrypt_model_connection_secret(
            b"secret",
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="short",
        )
    with pytest.raises(ModelConnectionSecretError):
        encrypt_model_connection_secret(
            b"secret",
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="../primary",
        )
    target = key_directory / "target.key"
    target.write_bytes(b"t" * 32)
    target.chmod(0o600)
    os.symlink(target, key_directory / "linked.key")
    with pytest.raises(ModelConnectionSecretError):
        encrypt_model_connection_secret(
            b"secret",
            tenant_id=tenant,
            connection_id=connection,
            secret_id=secret,
            key_directory=key_directory,
            key_id="linked",
        )


def test_operation_fingerprint_is_stable_and_domain_separated(
    key_directory: Path,
) -> None:
    payload = b'{"name":"A"}'
    first = model_connection_operation_fingerprint(
        payload, operation="save", key_directory=key_directory, key_id="primary"
    )
    assert first == model_connection_operation_fingerprint(
        payload, operation="save", key_directory=key_directory, key_id="primary"
    )
    assert first != model_connection_operation_fingerprint(
        payload, operation="enable", key_directory=key_directory, key_id="primary"
    )
