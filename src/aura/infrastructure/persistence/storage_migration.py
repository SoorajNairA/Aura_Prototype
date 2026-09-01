from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aura.app.config import Settings
from aura.infrastructure.artifacts import GcsArtifactStore, LocalFilesystemArtifactStore
from .postgres_repository import PostgresProjectRepository


@dataclass(frozen=True)
class MigrationSummary:
    projects: int
    revisions: int
    events: int
    artifacts: int
    bytes_copied: int
    dry_run: bool


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()]


def migrate_sqlite_to_postgres(source_db: Path, source_artifacts: Path,
                               target: PostgresProjectRepository, dry_run: bool = False) -> MigrationSummary:
    connection = sqlite3.connect(source_db)
    connection.row_factory = sqlite3.Row
    try:
        data = {table: _rows(connection, table) for table in ("projects", "revisions", "events", "artifacts")}
    finally:
        connection.close()
    project_ids = [row["project_id"] for row in data["projects"]]
    conflicts = [project_id for project_id in project_ids if target.get_project(project_id) is not None]
    if conflicts: raise RuntimeError(f"Target project conflicts: {', '.join(conflicts)}")
    local = LocalFilesystemArtifactStore(source_artifacts)
    payloads: list[tuple[str, bytes, str]] = []
    for artifact in data["artifacts"]:
        if artifact["status"] != "ready" or not artifact["relative_path"]: continue
        content = local.get(artifact["relative_path"])
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact["content_hash"]: raise RuntimeError(f"Source artifact hash mismatch: {artifact['artifact_id']}")
        payloads.append((artifact["relative_path"], content, digest))
    summary = MigrationSummary(len(data["projects"]), len(data["revisions"]), len(data["events"]), len(payloads),
        sum(len(item[1]) for item in payloads), dry_run)
    if dry_run: return summary
    uploaded: list[str] = []
    try:
        for key, content, digest in payloads:
            target.artifact_store.put(key, content, digest); uploaded.append(key)
        from psycopg.types.json import Jsonb
        with target._pool.connection() as postgres, postgres.transaction(), postgres.cursor() as cursor:
            for row in data["projects"]:
                cursor.execute("INSERT INTO projects VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (row["project_id"], row["objective"], row["planning_mode"], row["fallback_reason"], row["status"],
                     Jsonb(json.loads(row["graph_json"])), Jsonb(json.loads(row["representations_json"])), row["created_at"], row["updated_at"]))
            for row in data["revisions"]:
                cursor.execute("INSERT INTO revisions VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (row["project_id"], row["revision_number"], row["revision_id"], row["patch_id"],
                     Jsonb(json.loads(row["graph_json"])), Jsonb(json.loads(row["patch_json"])),
                     Jsonb(json.loads(row["verification_json"])), row["created_at"]))
            for row in data["events"]:
                cursor.execute("""INSERT INTO events(event_id,project_id,revision,type,semantic_ids_json,payload_json,timestamp)
                    OVERRIDING SYSTEM VALUE VALUES(%s,%s,%s,%s,%s,%s,%s)""", (row["event_id"], row["project_id"], row["revision"],
                    row["type"], Jsonb(json.loads(row["semantic_ids_json"])), Jsonb(json.loads(row["payload_json"])), row["timestamp"]))
            for row in data["artifacts"]:
                cursor.execute("INSERT INTO artifacts VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (row["artifact_id"], row["project_id"], row["revision"], Jsonb(json.loads(row["component_ids_json"])),
                     row["representation_type"], row["format"], row["status"], row["content_hash"], row["relative_path"],
                     row["generator"], row["generator_version"], row["created_at"], row["error"]))
            if data["events"]:
                cursor.execute("SELECT setval(pg_get_serial_sequence('events','event_id'), (SELECT MAX(event_id) FROM events), true)")
    except Exception:
        for key in uploaded:
            try: target.artifact_store.delete(key)
            except Exception: pass
        raise
    return summary


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Explicitly migrate AURA Workspace storage")
    parser.add_argument("--from", dest="source", choices=["sqlite"], required=True)
    parser.add_argument("--to", dest="target", choices=["postgres"], required=True)
    parser.add_argument("--sqlite-db", type=Path, default=settings.workspace_db_path)
    parser.add_argument("--sqlite-artifacts", type=Path, default=settings.workspace_artifact_dir)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if settings.artifact_storage_mode == "gcs": store = GcsArtifactStore(settings.gcs_bucket)
    else: store = LocalFilesystemArtifactStore(settings.workspace_artifact_dir)
    dsn = settings.database_url
    if not dsn:
        from psycopg.conninfo import make_conninfo
        dsn = make_conninfo(host=settings.db_host, port=settings.db_port, dbname=settings.db_name,
            user=settings.db_user, password=settings.db_password)
    repository = PostgresProjectRepository(dsn, store, settings.db_pool_size, settings.db_max_overflow, settings.db_pool_timeout)
    try: summary = migrate_sqlite_to_postgres(args.sqlite_db, args.sqlite_artifacts, repository, args.dry_run)
    finally: repository.close()
    print(json.dumps(summary.__dict__, sort_keys=True))


if __name__ == "__main__": main()
