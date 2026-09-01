from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class WorkspaceEvent:
    type: str
    project_id: str
    revision_id: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.type.strip() or not self.project_id.strip():
            raise ValueError("Workspace event type and project_id are required")
