from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aura.infrastructure.artifacts import LocalFilesystemArtifactStore, validate_object_key


@pytest.mark.unit
def test_artifact_store_immutable_hash_and_path_guards(tmp_path: Path) -> None:
    store = LocalFilesystemArtifactStore(tmp_path)
    content = b"artifact"
    digest = hashlib.sha256(content).hexdigest()
    key = "projects/project/revisions/1/representations/repr/artifact.json"
    store.put(key, content, digest)
    assert store.get(key) == content
    with pytest.raises(ValueError): store.put(key, content, "0" * 64)
    for unsafe in ("../secret", "/absolute", "a\\b", "projects/x/../../secret"):
        with pytest.raises(ValueError): validate_object_key(unsafe)


@pytest.mark.unit
def test_health_endpoints_use_repository_readiness() -> None:
    from fastapi.testclient import TestClient
    from aura.workspace.server import create_app
    app = create_app(storage_mode="memory")
    with TestClient(app) as client:
        live=client.get("/health/live").json()
        assert live["status"] == "ok"
        assert set(live) == {"status","version","commit","environment"}
        assert client.get("/health/ready").json() == {"status": "ready"}
    app.state.workspace.repository.close()


@pytest.mark.unit
def test_sqlite_to_postgres_empty_dry_run_has_no_target_writes(tmp_path: Path) -> None:
    from aura.infrastructure.persistence.project_repository import SQLiteProjectRepository
    from aura.infrastructure.persistence.storage_migration import migrate_sqlite_to_postgres
    source_db = tmp_path / "source.db"; artifacts = tmp_path / "artifacts"
    source = SQLiteProjectRepository(source_db, artifacts); source.close()
    class DryTarget:
        def get_project(self, project_id: str): raise AssertionError("empty source must not query target projects")
    summary = migrate_sqlite_to_postgres(source_db, artifacts, DryTarget(), dry_run=True)  # type: ignore[arg-type]
    assert summary.dry_run and summary.projects == summary.revisions == summary.events == summary.artifacts == 0
