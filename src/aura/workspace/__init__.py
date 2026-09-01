"""GUI-independent workspace state and event bridge."""

from .bridge import WorkspaceBridge
from .events import WorkspaceEvent

__all__ = ["WorkspaceBridge", "WorkspaceEvent"]
