"""Object storage backends for the immutable raw vault.

Keys are content hashes, so a backend never overwrites different bytes under
the same key. Bytes may be encrypted at rest with AES-GCM; the checksum stored
in the database is always of the plaintext.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultBackend(Protocol):
    scheme: str

    def put(self, key: str, data: bytes) -> str: ...
    def get(self, uri: str) -> bytes: ...
    def exists(self, uri: str) -> bool: ...
    def delete(self, uri: str) -> None: ...


class LocalBackend:
    scheme = "file"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / key[2:4] / key

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return f"file://{path}"

    def get(self, uri: str) -> bytes:
        return Path(uri.removeprefix("file://")).read_bytes()

    def exists(self, uri: str) -> bool:
        return Path(uri.removeprefix("file://")).exists()

    def delete(self, uri: str) -> None:
        p = Path(uri.removeprefix("file://"))
        if p.exists():
            p.unlink()


class S3Backend:
    """S3 / MinIO backend. Requires the optional ``boto3`` dependency."""

    scheme = "s3"

    def __init__(self, bucket: str, endpoint: str, access_key: str, secret_key: str) -> None:
        try:
            import boto3
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError("S3Backend requires `pip install cie[s3]`") from e
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception:
            self.client.create_bucket(Bucket=bucket)

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def get(self, uri: str) -> bytes:
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def exists(self, uri: str) -> bool:
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, uri: str) -> None:
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        self.client.delete_object(Bucket=bucket, Key=key)


class Cipher:
    """AES-256-GCM envelope. ``None`` key means bytes are stored in the clear."""

    def __init__(self, key_b64: str | None) -> None:
        self.aead = AESGCM(base64.b64decode(key_b64)) if key_b64 else None

    @property
    def enabled(self) -> bool:
        return self.aead is not None

    def encrypt(self, data: bytes) -> bytes:
        if self.aead is None:
            return data
        nonce = os.urandom(12)
        return nonce + self.aead.encrypt(nonce, data, None)

    def decrypt(self, data: bytes) -> bytes:
        if self.aead is None:
            return data
        return self.aead.decrypt(data[:12], data[12:], None)

    @staticmethod
    def generate_key() -> str:
        return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
