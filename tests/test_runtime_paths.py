from pathlib import Path
from types import SimpleNamespace
import sqlite3

from aura.app import config


def test_legacy_workspace_migration_is_verified_and_atomic(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    legacy = root / "runtime" / "workspace"
    artifacts = legacy / "artifacts" / "project-1"
    artifacts.mkdir(parents=True)
    database = legacy / "aura.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker VALUES('preserved')")
        connection.commit()
    finally:
        connection.close()
    (artifacts / "artifact.bin").write_bytes(b"preserved artifact")

    target = tmp_path / "user-data" / "workspace"
    settings = SimpleNamespace(
        workspace_db_path=target / "aura.db",
        workspace_artifact_dir=target / "artifacts",
    )
    monkeypatch.setattr(config, "_repository_root", lambda: root)
    monkeypatch.delenv("AURA_WORKSPACE_DB_PATH", raising=False)
    monkeypatch.delenv("AURA_WORKSPACE_ARTIFACT_DIR", raising=False)

    assert config.migrate_legacy_workspace_data(settings) == "migrated"
    assert not legacy.exists()
    with sqlite3.connect(settings.workspace_db_path) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "preserved"
    assert (settings.workspace_artifact_dir / "project-1" / "artifact.bin").read_bytes() == b"preserved artifact"
