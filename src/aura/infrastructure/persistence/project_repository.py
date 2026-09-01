from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from aura.engineering_graph.model import EngineeringGraph
from aura.infrastructure.artifacts import ArtifactStore, LocalFilesystemArtifactStore
from aura.engineering_graph.patches import GraphPatch
from aura.engineering_graph.serialization import graph_from_dict, graph_to_dict, patch_from_dict, patch_to_dict

SCHEMA_VERSION = 1


class UnsupportedSchemaVersion(RuntimeError): pass
class CorruptProjectData(RuntimeError): pass
class PersistenceFailure(RuntimeError): pass


@dataclass
class StoredProject:
    project_id: str
    objective: str
    planning_mode: str
    fallback_reason: str | None
    status: str
    graph: EngineeringGraph
    representations: list[dict[str, Any]]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredEvent:
    event_id: int
    project_id: str
    revision: int
    type: str
    semantic_ids: list[str]
    payload: dict[str, Any]
    timestamp: str


@dataclass
class ArtifactMetadata:
    artifact_id: str
    project_id: str
    revision: int
    component_ids: list[str]
    representation_type: str
    format: str
    status: str = "pending"
    content_hash: str | None = None
    relative_path: str | None = None
    generator: str | None = None
    generator_version: str | None = None
    created_at: str | None = None
    error: str | None = None


class ProjectRepository(Protocol):
    def get_project(self, project_id: str) -> StoredProject | None: ...
    def list_projects(self) -> list[StoredProject]: ...
    def save_commit(self, project: StoredProject, patch: GraphPatch,
                    verification: dict[str, Any], events: list[dict[str, Any]]) -> list[StoredEvent]: ...
    def list_revisions(self, project_id: str) -> list[dict[str, Any]]: ...
    def get_events_after(self, project_id: str, event_id: int) -> list[StoredEvent]: ...
    def get_artifact(self, artifact_id: str) -> ArtifactMetadata | None: ...
    def update_representations(self, project_id: str, representations: list[dict[str, Any]]) -> None: ...
    def update_project_status(self, project_id: str, status: str) -> None: ...
    def append_events(self, project_id: str, revision: int, events: list[dict[str, Any]]) -> list[StoredEvent]: ...
    def create_artifact(self, project_id: str, revision: int, component_ids: list[str], representation_type: str, format: str) -> ArtifactMetadata: ...
    def write_artifact(self, artifact_id: str, content: bytes, generator: str, generator_version: str) -> ArtifactMetadata: ...
    def read_artifact(self, artifact_id: str) -> bytes: ...
    def is_ready(self) -> bool: ...
    def close(self) -> None: ...
    def save_work_item(self, item: dict[str, Any]) -> None: ...
    def get_work_item(self, project_id: str, work_item_id: str) -> dict[str, Any] | None: ...
    def list_work_items(self, project_id: str) -> list[dict[str, Any]]: ...


class SQLiteProjectRepository:
    def __init__(self, database: str | Path, artifact_root: Path, artifact_store: ArtifactStore | None = None) -> None:
        self.database = str(database)
        self.artifact_root = artifact_root.resolve()
        self.artifact_store = artifact_store or LocalFilesystemArtifactStore(self.artifact_root)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def close(self) -> None:
        with self._lock: self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            current = self._connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_info'").fetchone()
            if current:
                version = self._connection.execute("SELECT version FROM schema_info").fetchone()[0]
                if version != SCHEMA_VERSION:
                    raise UnsupportedSchemaVersion(f"Workspace schema {version} is unsupported; expected {SCHEMA_VERSION}")
                self._connection.execute("CREATE TABLE IF NOT EXISTS work_items(project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, work_item_id TEXT NOT NULL, item_json TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(project_id, work_item_id))")
                self._connection.commit()
                return
            with self._connection:
                self._connection.executescript("""
                CREATE TABLE schema_info(version INTEGER NOT NULL);
                INSERT INTO schema_info VALUES (1);
                CREATE TABLE projects(project_id TEXT PRIMARY KEY, objective TEXT NOT NULL, planning_mode TEXT NOT NULL,
                    fallback_reason TEXT, status TEXT NOT NULL, graph_json TEXT NOT NULL, representations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE revisions(project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    revision_number INTEGER NOT NULL, revision_id TEXT NOT NULL, patch_id TEXT NOT NULL,
                    graph_json TEXT NOT NULL, patch_json TEXT NOT NULL, verification_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(project_id, revision_number));
                CREATE TABLE events(project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL, revision INTEGER NOT NULL, type TEXT NOT NULL,
                    semantic_ids_json TEXT NOT NULL, payload_json TEXT NOT NULL, timestamp TEXT NOT NULL,
                    PRIMARY KEY(project_id, event_id));
                CREATE TABLE artifacts(artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, component_ids_json TEXT NOT NULL, representation_type TEXT NOT NULL,
                    format TEXT NOT NULL, status TEXT NOT NULL, content_hash TEXT, relative_path TEXT,
                    generator TEXT, generator_version TEXT, created_at TEXT, error TEXT);
                CREATE TABLE work_items(project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                    work_item_id TEXT NOT NULL, item_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, work_item_id));
                """)

    def save_work_item(self, item: dict[str, Any]) -> None:
        with self._lock, self._connection:
            if self._connection.execute("SELECT 1 FROM projects WHERE project_id=?",(item["projectId"],)).fetchone() is None: raise KeyError(item["projectId"])
            self._connection.execute("INSERT INTO work_items VALUES(?,?,?,?) ON CONFLICT(project_id,work_item_id) DO UPDATE SET item_json=excluded.item_json,updated_at=excluded.updated_at",
                (item["projectId"],item["id"],json.dumps(item,separators=(",",":")),item["updatedAt"]))

    def get_work_item(self, project_id: str, work_item_id: str) -> dict[str, Any] | None:
        with self._lock: row=self._connection.execute("SELECT item_json FROM work_items WHERE project_id=? AND work_item_id=?",(project_id,work_item_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list_work_items(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock: rows=self._connection.execute("SELECT item_json FROM work_items WHERE project_id=? ORDER BY updated_at,work_item_id",(project_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_project(self, project_id: str) -> StoredProject | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None: return None
        try:
            return StoredProject(row["project_id"], row["objective"], row["planning_mode"], row["fallback_reason"],
                row["status"], graph_from_dict(json.loads(row["graph_json"])), json.loads(row["representations_json"]),
                row["created_at"], row["updated_at"])
        except Exception as exc:
            raise CorruptProjectData(f"Stored project {project_id} is corrupt") from exc

    def list_projects(self) -> list[StoredProject]:
        with self._lock:
            ids = [row[0] for row in self._connection.execute("SELECT project_id FROM projects ORDER BY created_at, project_id")]
        return [project for project_id in ids if (project := self.get_project(project_id)) is not None]

    def save_commit(self, project: StoredProject, patch: GraphPatch,
                    verification: dict[str, Any], events: list[dict[str, Any]]) -> list[StoredEvent]:
        revision_number = len(project.graph.revisions)
        if revision_number < 1: raise PersistenceFailure("A committed graph requires a revision")
        now = datetime.now(timezone.utc).isoformat()
        stored_events: list[StoredEvent] = []
        with self._lock:
            try:
                with self._connection:
                    existing = self._connection.execute("SELECT created_at FROM projects WHERE project_id=?", (project.project_id,)).fetchone()
                    created = existing[0] if existing else project.created_at or now
                    self._connection.execute("""INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(project_id) DO UPDATE SET objective=excluded.objective,planning_mode=excluded.planning_mode,
                        fallback_reason=excluded.fallback_reason,status=excluded.status,graph_json=excluded.graph_json,
                        representations_json=excluded.representations_json,updated_at=excluded.updated_at""",
                        (project.project_id, project.objective, project.planning_mode, project.fallback_reason, project.status,
                         json.dumps(graph_to_dict(project.graph)), json.dumps(project.representations), created, now))
                    revision = project.graph.revisions[-1]
                    self._connection.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?)",
                        (project.project_id, revision_number, revision.id, patch.id, json.dumps(graph_to_dict(project.graph)),
                         json.dumps(patch_to_dict(patch)), json.dumps(verification), revision.created_at))
                    next_id = self._connection.execute("SELECT COALESCE(MAX(event_id),0)+1 FROM events WHERE project_id=?", (project.project_id,)).fetchone()[0]
                    for offset, event in enumerate(events):
                        item = StoredEvent(next_id + offset, project.project_id, event.get("revision", revision_number),
                            event["type"], list(event.get("semantic_ids", [])), dict(event.get("payload", {})),
                            event.get("timestamp") or now)
                        self._connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                            (item.project_id, item.event_id, item.revision, item.type, json.dumps(item.semantic_ids),
                             json.dumps(item.payload), item.timestamp))
                        stored_events.append(item)
            except Exception as exc:
                raise PersistenceFailure(f"Could not persist project commit: {exc}") from exc
        return stored_events

    def list_revisions(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM revisions WHERE project_id=? ORDER BY revision_number", (project_id,)).fetchall()
        return [{"revision": row["revision_number"], "revisionId": row["revision_id"], "patch": patch_from_dict(json.loads(row["patch_json"])),
                 "verification": json.loads(row["verification_json"]), "createdAt": row["created_at"]} for row in rows]

    def get_events_after(self, project_id: str, event_id: int) -> list[StoredEvent]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM events WHERE project_id=? AND event_id>? ORDER BY event_id", (project_id, event_id)).fetchall()
        return [StoredEvent(row["event_id"], row["project_id"], row["revision"], row["type"],
            json.loads(row["semantic_ids_json"]), json.loads(row["payload_json"]), row["timestamp"]) for row in rows]

    def update_representations(self, project_id: str, representations: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute("UPDATE projects SET representations_json=?,updated_at=? WHERE project_id=?",
                (json.dumps(representations), now, project_id))
            if cursor.rowcount != 1: raise KeyError(f"Unknown project: {project_id}")

    def update_project_status(self, project_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute("UPDATE projects SET status=?,updated_at=? WHERE project_id=?", (status, now, project_id))
            if cursor.rowcount != 1: raise KeyError(f"Unknown project: {project_id}")

    def append_events(self, project_id: str, revision: int, events: list[dict[str, Any]]) -> list[StoredEvent]:
        now = datetime.now(timezone.utc).isoformat(); stored: list[StoredEvent] = []
        with self._lock, self._connection:
            if self._connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is None:
                raise KeyError(f"Unknown project: {project_id}")
            next_id = self._connection.execute("SELECT COALESCE(MAX(event_id),0)+1 FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            for offset, event in enumerate(events):
                item = StoredEvent(next_id + offset, project_id, revision, event["type"], list(event.get("semantic_ids", [])),
                    dict(event.get("payload", {})), event.get("timestamp") or now)
                self._connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)", (item.project_id, item.event_id,
                    item.revision, item.type, json.dumps(item.semantic_ids), json.dumps(item.payload), item.timestamp))
                stored.append(item)
        return stored

    def create_artifact(self, project_id: str, revision: int, component_ids: list[str],
                        representation_type: str, format: str) -> ArtifactMetadata:
        artifact_id = f"artifact-{uuid4().hex}"
        metadata = ArtifactMetadata(artifact_id, project_id, revision, component_ids, representation_type, format)
        with self._lock, self._connection:
            self._connection.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, project_id, revision, json.dumps(component_ids), representation_type, format, "pending",
                 None, None, None, None, None, None))
        return metadata

    def get_artifact(self, artifact_id: str) -> ArtifactMetadata | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if row is None: return None
        return ArtifactMetadata(row["artifact_id"], row["project_id"], row["revision"], json.loads(row["component_ids_json"]),
            row["representation_type"], row["format"], row["status"], row["content_hash"], row["relative_path"],
            row["generator"], row["generator_version"], row["created_at"], row["error"])

    def write_artifact(self, artifact_id: str, content: bytes, generator: str, generator_version: str) -> ArtifactMetadata:
        metadata = self.get_artifact(artifact_id)
        if metadata is None: raise KeyError(f"Unknown artifact: {artifact_id}")
        if not re.fullmatch(r"artifact-[0-9a-f]{32}", artifact_id): raise ValueError("Unsafe artifact id")
        extension = re.sub(r"[^a-z0-9]", "", metadata.format.lower()) or "bin"
        relative = Path("projects") / metadata.project_id / "revisions" / str(metadata.revision) / "representations" / artifact_id / f"artifact.{extension}"
        digest = hashlib.sha256(content).hexdigest(); now = datetime.now(timezone.utc).isoformat()
        self.artifact_store.put(relative.as_posix(), content, digest)
        try:
            with self._lock, self._connection:
                self._connection.execute("UPDATE artifacts SET status='ready',content_hash=?,relative_path=?,generator=?,generator_version=?,created_at=? WHERE artifact_id=?",
                    (digest, relative.as_posix(), generator, generator_version, now, artifact_id))
        except Exception:
            try: self.artifact_store.delete(relative.as_posix())
            except Exception: pass
            raise
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def read_artifact(self, artifact_id: str) -> bytes:
        metadata = self.get_artifact(artifact_id)
        if metadata is None or metadata.status != "ready" or not metadata.relative_path:
            raise KeyError(f"Artifact content is unavailable: {artifact_id}")
        content = self.artifact_store.get(metadata.relative_path)
        if hashlib.sha256(content).hexdigest() != metadata.content_hash:
            raise CorruptProjectData(f"Artifact hash verification failed: {artifact_id}")
        return content

    def is_ready(self) -> bool:
        try:
            self._connection.execute("SELECT 1").fetchone()
            return self.artifact_store.ready()
        except Exception:
            return False

    def resolve_artifact_path(self, relative_path: str | Path) -> Path:
        if not isinstance(self.artifact_store, LocalFilesystemArtifactStore):
            raise RuntimeError("Cloud artifacts do not have local filesystem paths")
        return self.artifact_store.resolve(relative_path)
