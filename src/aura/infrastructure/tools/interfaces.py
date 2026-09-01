from __future__ import annotations

from typing import Any, Protocol


class ToolExecutor(Protocol):
    """Execute only pre-registered operations; arbitrary shell is not supported."""

    def catalog(self) -> list[dict[str, Any]]: ...
    def execute(self, tool_call: dict[str, Any]) -> Any: ...


class RegisteredToolAdapter:
    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def catalog(self) -> list[dict[str, Any]]:
        return list(self._registry.catalog())

    def execute(self, tool_call: dict[str, Any]) -> Any:
        if not isinstance(tool_call, dict) or not isinstance(tool_call.get("name"), str):
            raise ValueError("A registered tool name is required")
        return self._registry.execute(tool_call)
