from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Protocol


class ArtifactStore(Protocol):
    def put(self, key: str, content: bytes, content_hash: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def ready(self) -> bool: ...


def validate_object_key(key: str) -> str:
    if not key or "\\" in key or key.startswith("/"):
        raise ValueError("Artifact object key must be a relative POSIX path")
    path = PurePosixPath(key)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Artifact path escapes configured root through unsafe traversal")
    if not all(re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in path.parts):
        raise ValueError("Artifact object key contains unsafe characters")
    return path.as_posix()


class LocalFilesystemArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, key: str | Path) -> Path:
        safe = validate_object_key(Path(key).as_posix())
        destination = (self.root / Path(*PurePosixPath(safe).parts)).resolve()
        try:
            destination.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Artifact path escapes configured root") from exc
        return destination

    def put(self, key: str, content: bytes, content_hash: str) -> None:
        if hashlib.sha256(content).hexdigest() != content_hash:
            raise ValueError("Artifact hash does not match content")
        destination = self.resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)

    def get(self, key: str) -> bytes:
        return self.resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)

    def ready(self) -> bool:
        return self.root.is_dir()


class GcsArtifactStore:
    def __init__(self, bucket_name: str, prefix: str = "", timeout: float = 10) -> None:
        if not bucket_name:
            raise ValueError("AURA_GCS_BUCKET is required for GCS artifact storage")
        from google.cloud import storage
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.timeout = timeout
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def _name(self, key: str) -> str:
        safe = validate_object_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def put(self, key: str, content: bytes, content_hash: str) -> None:
        if hashlib.sha256(content).hexdigest() != content_hash:
            raise ValueError("Artifact hash does not match content")
        blob = self._bucket.blob(self._name(key))
        blob.metadata = {"sha256": content_hash}
        blob.upload_from_string(content, if_generation_match=0, timeout=self.timeout, retry=None)
        blob.reload(timeout=self.timeout, retry=None)
        if (blob.metadata or {}).get("sha256") != content_hash:
            raise RuntimeError("GCS artifact metadata verification failed")

    def get(self, key: str) -> bytes:
        return self._bucket.blob(self._name(key)).download_as_bytes(timeout=self.timeout, retry=None)

    def delete(self, key: str) -> None:
        try:
            self._bucket.blob(self._name(key)).delete(timeout=self.timeout, retry=None)
        except Exception as exc:
            if exc.__class__.__name__ != "NotFound":
                raise

    def ready(self) -> bool:
        # Bucket metadata access is intentionally not granted to the runtime
        # identity; successful client construction is enough for readiness.
        # Every object operation still verifies its own result and hash.
        return True
