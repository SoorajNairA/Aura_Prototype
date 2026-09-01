"""Narrow interfaces for optional runtime infrastructure."""

from .desktop import DesktopActions
from .llm import ModelProvider
from .persistence import GraphRepository, JsonGraphRepository, ProjectRepository, SQLiteProjectRepository
from .tools import ToolExecutor
from .voice import VoiceInteraction

__all__ = ["DesktopActions", "GraphRepository", "JsonGraphRepository", "ModelProvider",
           "ProjectRepository", "SQLiteProjectRepository", "ToolExecutor", "VoiceInteraction"]
