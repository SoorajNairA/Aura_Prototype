CREATE TABLE IF NOT EXISTS aura_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY, objective TEXT NOT NULL, planning_mode TEXT NOT NULL,
    fallback_reason TEXT, status TEXT NOT NULL, graph_json JSONB NOT NULL,
    representations_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL, revision_id TEXT NOT NULL, patch_id TEXT NOT NULL,
    graph_json JSONB NOT NULL, patch_json JSONB NOT NULL, verification_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(project_id, revision_number)
);
CREATE TABLE IF NOT EXISTS events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL, type TEXT NOT NULL, semantic_ids_json JSONB NOT NULL,
    payload_json JSONB NOT NULL, timestamp TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project_replay ON events(project_id, event_id);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL, component_ids_json JSONB NOT NULL, representation_type TEXT NOT NULL,
    format TEXT NOT NULL, status TEXT NOT NULL, content_hash TEXT, relative_path TEXT,
    generator TEXT, generator_version TEXT, created_at TIMESTAMPTZ, error TEXT
);
CREATE TABLE IF NOT EXISTS work_items (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    work_item_id TEXT NOT NULL, item_json JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(project_id, work_item_id)
);
