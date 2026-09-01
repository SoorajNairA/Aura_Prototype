"""
conversation_context.py — Working memory, context building, state, and mood tracking.

Classes:
  ConversationState     — IDLE / CONVERSING / PLANNING / EXECUTING enum
  WorkingMemory         — thread-safe rolling turn buffer (max 30 turns)
  ConversationContext   — snapshot passed to ConversationModel on each request
  ConversationContextBuilder — assembles ConversationContext from memory and state

Design:
  - Working memory is always in RAM; never re-read from disk on every turn.
  - Long-term memory is only queried for memory_recall interaction type.
  - Active project is only loaded when a keyword match exists.
  - Context window hard cap: 20 recent turns, 512 chars per project summary,
    top-6 memory snippets.
  - Mood hint derived from lightweight lexical heuristics — no ML required.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aura.infrastructure.persistence.memory_store import MemoryStore

# ---------------------------------------------------------------------------
# ConversationState
# ---------------------------------------------------------------------------

class ConversationState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    REASONING = "reasoning"
    CONVERSING = "conversing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    SPEAKING = "speaking"
    COMPLETE = "complete"

    def describe(self) -> str:
        return {
            ConversationState.IDLE:       "Standing by.",
            ConversationState.LISTENING:  "Listening.",
            ConversationState.REASONING:  "Analyzing request.",
            ConversationState.CONVERSING: "In conversation.",
            ConversationState.PLANNING:   "Working on a plan.",
            ConversationState.EXECUTING:  "Executing tasks.",
            ConversationState.VERIFYING:  "Verifying results.",
            ConversationState.RECOVERING: "Recovering.",
            ConversationState.SPEAKING:   "Speaking.",
            ConversationState.COMPLETE:   "Completed.",
        }[self]


# ---------------------------------------------------------------------------
# Mood hint heuristics
# ---------------------------------------------------------------------------

_STRESSED_WORDS = {
    "urgent", "asap", "quickly", "hurry", "immediately", "deadline",
    "critical", "crisis", "stuck", "broken", "failing", "fail",
}
_EXCITED_WORDS = {
    "amazing", "awesome", "great", "excellent", "perfect", "love",
    "excited", "fantastic", "brilliant", "incredible", "wow",
}
_FRUSTRATED_WORDS = {
    "again", "still", "ugh", "argh", "why", "broken", "wrong",
    "doesn't work", "not working", "useless", "stupid", "terrible",
}


def _detect_mood(text: str) -> str:
    lowered = text.lower()
    words = set(lowered.split())

    if any(w in lowered for w in _FRUSTRATED_WORDS) or words & _FRUSTRATED_WORDS:
        return "frustrated"
    if _STRESSED_WORDS & words:
        return "stressed"
    if _EXCITED_WORDS & words:
        return "excited"
    return "neutral"


# ---------------------------------------------------------------------------
# WorkingMemory — thread-safe rolling turn buffer
# ---------------------------------------------------------------------------

_MAX_TURNS = 30
_INACTIVITY_THRESHOLD_HOURS = 4.0


class WorkingMemory:
    """Thread-safe rolling window of the last N conversation turns.

    Each turn: {"role": "user"|"assistant", "content": str, "ts": float}
    """

    def __init__(self, max_turns: int = _MAX_TURNS) -> None:
        self._max = max_turns
        self._turns: deque[dict[str, Any]] = deque(maxlen=max_turns)
        self._lock = threading.Lock()

    def append(self, role: str, content: str) -> None:
        content = " ".join(content.split())
        if not content:
            return
        with self._lock:
            self._turns.append({"role": role, "content": content, "ts": time.time()})

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n turns as a list (oldest first)."""
        with self._lock:
            turns = list(self._turns)
        return turns[-n:]

    def as_messages(self, n: int = 20) -> list[dict[str, str]]:
        """Return turns in OpenAI/Ollama messages format."""
        return [{"role": t["role"], "content": t["content"]} for t in self.recent(n)]

    def last_seen_ago(self) -> str | None:
        """Human-readable description of inactivity gap, or None if recent."""
        with self._lock:
            turns = list(self._turns)
        if not turns:
            return None
        gap_seconds = time.time() - turns[-1]["ts"]
        gap_hours = gap_seconds / 3600
        if gap_hours < _INACTIVITY_THRESHOLD_HOURS:
            return None
        if gap_hours < 24:
            h = int(gap_hours)
            return f"{h} hour{'s' if h != 1 else ''} ago"
        days = int(gap_hours / 24)
        return f"{days} day{'s' if days != 1 else ''} ago"

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._turns) == 0

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()


# ---------------------------------------------------------------------------
# ConversationContext
# ---------------------------------------------------------------------------

@dataclass
class ConversationContext:
    recent_messages: list[dict]          # last 20 turns in messages format
    active_project: dict | None          # matched project from MemoryStore, or None
    relevant_memories: list[str]         # top-k strings for memory_recall only
    user_preferences: dict               # from MemoryStore.get_user_profile()
    current_time: str                    # ISO timestamp
    time_of_day: str                     # morning / afternoon / evening
    last_seen_ago: str | None            # None if user was recently active
    mood_hint: str                       # neutral / stressed / excited / frustrated
    state: ConversationState             # IDLE / CONVERSING / PLANNING / EXECUTING
    interaction_type: str                # classification result
    # Truncation metadata (for diagnostics)
    turns_loaded: int = 0
    memory_snippets_loaded: int = 0

    def to_context_block(self) -> str:
        """Render a compact context string to append to model prompts."""
        parts: list[str] = []

        if self.active_project:
            name = self.active_project.get("_key", "current project")
            status = self.active_project.get("world_state", {})
            pending = len(status.get("pending_tasks", []))
            completed = len(status.get("completed_tasks", []))
            summary = f"Active project: {name}. Completed: {completed}, Pending: {pending}."
            parts.append(summary[:512])  # hard cap

        if self.relevant_memories:
            parts.append("Relevant memory:\n" + "\n".join(self.relevant_memories[:6]))

        if self.state != ConversationState.CONVERSING and self.state != ConversationState.IDLE:
            parts.append(f"Current state: {self.state.describe()}")

        if self.mood_hint != "neutral":
            parts.append(f"User mood hint: {self.mood_hint}.")

        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# ConversationContextBuilder
# ---------------------------------------------------------------------------

# Memory retrieval policy per interaction type
_LOAD_MEMORY: dict[str, bool] = {
    "greeting":            False,
    "small_talk":          False,
    "question":            False,
    "discussion":          False,
    "memory_recall":       True,
    "advice_request":      False,
    "goal_request":        True,   # load active project if it exists
    "direct_system_command": False,
}

_TIME_OF_DAY_HOURS: list[tuple[int, str]] = [
    (12, "morning"),
    (17, "afternoon"),
    (24, "evening"),
]


def _time_of_day() -> str:
    h = datetime.now().hour
    for threshold, label in _TIME_OF_DAY_HOURS:
        if h < threshold:
            return label
    return "evening"


class ConversationContextBuilder:
    """Assembles a ConversationContext for each request.

    Memory is only loaded when the interaction type requires it.
    Context window limits are enforced strictly.
    """

    def __init__(self, memory: MemoryStore, working_memory: WorkingMemory) -> None:
        self._memory = memory
        self._wm = working_memory

    def build(
        self,
        user_text: str,
        interaction_type: str,
        state: ConversationState,
    ) -> ConversationContext:
        load_memory = _LOAD_MEMORY.get(interaction_type, False)
        recent_msgs = self._wm.as_messages(n=20)
        turns_loaded = len(recent_msgs)

        active_project: dict | None = None
        relevant_memories: list[str] = []
        snippets_loaded = 0

        if load_memory:
            # Active project — keyword match only
            terms = [t for t in user_text.lower().split() if len(t) > 2]
            active_project = self._memory.get_project_by_keyword(terms)

            # Long-term memory — top-6 snippets only
            relevant_memories = self._retrieve_memory_snippets(user_text, top_k=6)
            snippets_loaded = len(relevant_memories)

        user_prefs: dict = {}
        try:
            user_prefs = self._memory.get_user_profile()
        except Exception:
            pass

        return ConversationContext(
            recent_messages=recent_msgs,
            active_project=active_project,
            relevant_memories=relevant_memories,
            user_preferences=user_prefs,
            current_time=datetime.now().isoformat(timespec="seconds"),
            time_of_day=_time_of_day(),
            last_seen_ago=self._wm.last_seen_ago(),
            mood_hint=_detect_mood(user_text),
            state=state,
            interaction_type=interaction_type,
            turns_loaded=turns_loaded,
            memory_snippets_loaded=snippets_loaded,
        )

    def _retrieve_memory_snippets(self, user_text: str, top_k: int = 6) -> list[str]:
        """Return top-k relevant memory snippets based on keyword overlap."""
        terms = [t for t in user_text.lower().split() if len(t) > 2]
        snippets: list[str] = []

        try:
            projects = self._memory.get_projects()
            for key in projects:
                if terms and not any(t in key.lower() for t in terms):
                    continue
                snippets.append(f"Project: {key}")
                if len(snippets) >= top_k:
                    return snippets
        except Exception:
            pass

        try:
            logs = self._memory.read_recent_logs(limit=80)
            for event in reversed(logs):
                if not isinstance(event, dict):
                    continue
                joined = str(event).lower()
                if terms and not any(t in joined for t in terms):
                    continue
                goal = event.get("goal", "")
                task = (event.get("task") or {}).get("title", "")
                result = (event.get("result") or {}).get("message", "")
                if goal or task:
                    snippets.append(
                        f"Past: goal='{goal}' task='{task}' result='{result}'"
                    )
                if len(snippets) >= top_k:
                    break
        except Exception:
            pass

        return snippets[:top_k]
