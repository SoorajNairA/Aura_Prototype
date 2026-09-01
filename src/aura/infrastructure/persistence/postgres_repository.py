from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aura.engineering_graph.patches import GraphPatch
from aura.engineering_graph.serialization import graph_from_dict, graph_to_dict, patch_from_dict, patch_to_dict
from aura.infrastructure.artifacts import ArtifactStore
from .project_repository import (ArtifactMetadata, CorruptProjectData, PersistenceFailure,
    StoredEvent, StoredProject, UnsupportedSchemaVersion)

POSTGRES_SCHEMA_VERSION = 1


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class PostgresProjectRepository:
    """Psycopg-backed Workspace repository with bounded pooling and atomic commits."""

    def __init__(self, dsn: str, artifact_store: ArtifactStore, pool_size: int = 3,
                 max_overflow: int = 1, pool_timeout: float = 5.0) -> None:
        if not dsn:
            raise ValueError("AURA_DATABASE_URL is required for PostgreSQL storage")
        from psycopg_pool import ConnectionPool
        maximum = max(1, pool_size + max_overflow)
        self.artifact_store = artifact_store
        self._pool = ConnectionPool(dsn, min_size=1, max_size=maximum,
            timeout=pool_timeout, kwargs={"autocommit": False}, open=True)
        self._migrate()

    def close(self) -> None:
        self._pool.close()

    def _migration_sql(self) -> str:
        candidates = [Path.cwd() / "migrations/postgres/001_initial.sql",
            Path(__file__).resolve().parents[4] / "migrations/postgres/001_initial.sql"]
        for candidate in candidates:
            if candidate.is_file(): return candidate.read_text(encoding="utf-8")
        raise RuntimeError("PostgreSQL migration 001_initial.sql was not packaged")

    def _migrate(self) -> None:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS aura_schema_version (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                cursor.execute("SELECT COALESCE(MAX(version), 0) FROM aura_schema_version")
                current = int(cursor.fetchone()[0])
                if current > POSTGRES_SCHEMA_VERSION:
                    raise UnsupportedSchemaVersion(f"Workspace schema {current} is newer than supported {POSTGRES_SCHEMA_VERSION}")
                cursor.execute(self._migration_sql())
                if current < 1:
                    cursor.execute("INSERT INTO aura_schema_version(version) VALUES (1) ON CONFLICT DO NOTHING")

    def save_work_item(self, item: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb
        with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("INSERT INTO work_items VALUES(%s,%s,%s,%s) ON CONFLICT(project_id,work_item_id) DO UPDATE SET item_json=EXCLUDED.item_json,updated_at=EXCLUDED.updated_at",
                (item["projectId"],item["id"],Jsonb(item),item["updatedAt"]))

    def get_work_item(self, project_id: str, work_item_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT item_json FROM work_items WHERE project_id=%s AND work_item_id=%s",(project_id,work_item_id)); row=cursor.fetchone()
        return dict(row[0]) if row else None

    def list_work_items(self, project_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT item_json FROM work_items WHERE project_id=%s ORDER BY updated_at,work_item_id",(project_id,)); rows=cursor.fetchall()
        return [dict(row[0]) for row in rows]

    def is_ready(self) -> bool:
        try:
            with self._pool.connection() as connection:
                with connection.cursor() as cursor: cursor.execute("SELECT 1"); cursor.fetchone()
            return self.artifact_store.ready()
        except Exception:
            return False

    def get_project(self, project_id: str) -> StoredProject | None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT project_id,objective,planning_mode,fallback_reason,status,graph_json,representations_json,created_at,updated_at FROM projects WHERE project_id=%s", (project_id,))
            row = cursor.fetchone()
        if row is None: return None
        try:
            return StoredProject(row[0], row[1], row[2], row[3], row[4], graph_from_dict(row[5]), list(row[6]), _iso(row[7]), _iso(row[8]))
        except Exception as exc: raise CorruptProjectData(f"Stored project {project_id} is corrupt") from exc

    def list_projects(self) -> list[StoredProject]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT project_id FROM projects ORDER BY created_at,project_id")
            ids = [row[0] for row in cursor.fetchall()]
        return [project for project_id in ids if (project := self.get_project(project_id)) is not None]

    def _insert_events(self, cursor: Any, project_id: str, revision: int,
                       events: list[dict[str, Any]], now: str) -> list[StoredEvent]:
        from psycopg.types.json import Jsonb
        stored = []
        for event in events:
            timestamp = event.get("timestamp") or now
            cursor.execute("""INSERT INTO events(project_id,revision,type,semantic_ids_json,payload_json,timestamp)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING event_id""",
                (project_id, event.get("revision", revision), event["type"], Jsonb(list(event.get("semantic_ids", []))), Jsonb(dict(event.get("payload", {}))), timestamp))
            stored.append(StoredEvent(int(cursor.fetchone()[0]), project_id, event.get("revision", revision), event["type"],
                list(event.get("semantic_ids", [])), dict(event.get("payload", {})), timestamp))
        return stored

    def save_commit(self, project: StoredProject, patch: GraphPatch,
                    verification: dict[str, Any], events: list[dict[str, Any]]) -> list[StoredEvent]:
        from psycopg.types.json import Jsonb
        revision_number = len(project.graph.revisions)
        if revision_number < 1: raise PersistenceFailure("A committed graph requires a revision")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
                cursor.execute("""INSERT INTO projects VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(project_id) DO UPDATE SET objective=EXCLUDED.objective,planning_mode=EXCLUDED.planning_mode,
                    fallback_reason=EXCLUDED.fallback_reason,status=EXCLUDED.status,graph_json=EXCLUDED.graph_json,
                    representations_json=EXCLUDED.representations_json,updated_at=EXCLUDED.updated_at""",
                    (project.project_id, project.objective, project.planning_mode, project.fallback_reason, project.status,
                     Jsonb(graph_to_dict(project.graph)), Jsonb(project.representations), project.created_at or now, now))
                revision = project.graph.revisions[-1]
                cursor.execute("INSERT INTO revisions VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (project.project_id, revision_number, revision.id, patch.id, Jsonb(graph_to_dict(project.graph)),
                     Jsonb(patch_to_dict(patch)), Jsonb(verification), revision.created_at))
                return self._insert_events(cursor, project.project_id, revision_number, events, now)
        except Exception as exc: raise PersistenceFailure(f"Could not persist project commit: {exc}") from exc

    def list_revisions(self, project_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT revision_number,revision_id,patch_json,verification_json,created_at FROM revisions WHERE project_id=%s ORDER BY revision_number", (project_id,))
            rows = cursor.fetchall()
        return [{"revision": row[0], "revisionId": row[1], "patch": patch_from_dict(row[2]), "verification": row[3], "createdAt": _iso(row[4])} for row in rows]

    def get_events_after(self, project_id: str, event_id: int) -> list[StoredEvent]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT event_id,project_id,revision,type,semantic_ids_json,payload_json,timestamp FROM events WHERE project_id=%s AND event_id>%s ORDER BY event_id", (project_id, event_id))
            rows = cursor.fetchall()
        return [StoredEvent(int(row[0]), row[1], row[2], row[3], list(row[4]), dict(row[5]), _iso(row[6])) for row in rows]

    def update_representations(self, project_id: str, representations: list[dict[str, Any]]) -> None:
        from psycopg.types.json import Jsonb
        with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("UPDATE projects SET representations_json=%s,updated_at=CURRENT_TIMESTAMP WHERE project_id=%s", (Jsonb(representations), project_id))
            if cursor.rowcount != 1: raise KeyError(f"Unknown project: {project_id}")

    def update_project_status(self, project_id: str, status: str) -> None:
        with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("UPDATE projects SET status=%s,updated_at=CURRENT_TIMESTAMP WHERE project_id=%s", (status, project_id))
            if cursor.rowcount != 1: raise KeyError(f"Unknown project: {project_id}")

    def append_events(self, project_id: str, revision: int, events: list[dict[str, Any]]) -> list[StoredEvent]:
        now = datetime.now(timezone.utc).isoformat()
        with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM projects WHERE project_id=%s", (project_id,))
            if cursor.fetchone() is None: raise KeyError(f"Unknown project: {project_id}")
            return self._insert_events(cursor, project_id, revision, events, now)

    def create_artifact(self, project_id: str, revision: int, component_ids: list[str], representation_type: str, format: str) -> ArtifactMetadata:
        from psycopg.types.json import Jsonb
        artifact_id = f"artifact-{uuid4().hex}"
        with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("""INSERT INTO artifacts(artifact_id,project_id,revision,component_ids_json,representation_type,format,status)
                VALUES(%s,%s,%s,%s,%s,%s,'pending')""", (artifact_id, project_id, revision, Jsonb(component_ids), representation_type, format))
        return ArtifactMetadata(artifact_id, project_id, revision, component_ids, representation_type, format)

    def get_artifact(self, artifact_id: str) -> ArtifactMetadata | None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT artifact_id,project_id,revision,component_ids_json,representation_type,format,status,content_hash,relative_path,generator,generator_version,created_at,error FROM artifacts WHERE artifact_id=%s", (artifact_id,))
            row = cursor.fetchone()
        if row is None: return None
        return ArtifactMetadata(row[0], row[1], row[2], list(row[3]), row[4], row[5], row[6], row[7], row[8], row[9], row[10], _iso(row[11]) if row[11] else None, row[12])

    def write_artifact(self, artifact_id: str, content: bytes, generator: str, generator_version: str) -> ArtifactMetadata:
        metadata = self.get_artifact(artifact_id)
        if metadata is None: raise KeyError(f"Unknown artifact: {artifact_id}")
        if not re.fullmatch(r"artifact-[0-9a-f]{32}", artifact_id): raise ValueError("Unsafe artifact id")
        extension = re.sub(r"[^a-z0-9]", "", metadata.format.lower()) or "bin"
        key = f"projects/{metadata.project_id}/revisions/{metadata.revision}/representations/{artifact_id}/artifact.{extension}"
        digest = hashlib.sha256(content).hexdigest()
        self.artifact_store.put(key, content, digest)
        try:
            with self._pool.connection() as connection, connection.transaction(), connection.cursor() as cursor:
                cursor.execute("""UPDATE artifacts SET status='ready',content_hash=%s,relative_path=%s,generator=%s,
                    generator_version=%s,created_at=CURRENT_TIMESTAMP WHERE artifact_id=%s""",
                    (digest, key, generator, generator_version, artifact_id))
        except Exception:
            try: self.artifact_store.delete(key)
            except Exception: pass
            raise
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def read_artifact(self, artifact_id: str) -> bytes:
        metadata = self.get_artifact(artifact_id)
        if metadata is None or metadata.status != "ready" or not metadata.relative_path: raise KeyError(artifact_id)
        content = self.artifact_store.get(metadata.relative_path)
        if hashlib.sha256(content).hexdigest() != metadata.content_hash: raise CorruptProjectData(f"Artifact hash verification failed: {artifact_id}")
        return content
