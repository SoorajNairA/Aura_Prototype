from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime as _dt
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from aura.legacy.assistant.conversation_context import ConversationContext
    from aura.infrastructure.llm.ollama import ConversationModel
    from aura.legacy.assistant.conversation_context import WorkingMemory

_logger = logging.getLogger("aura")
_ctrace = logging.getLogger("aura.trace")

AVAILABLE_CAPABILITIES: dict[str, bool] = {
    "open_app": True,
    "open_url": True,
    "create_folder": True,
    "create_file": True,
    "write_text_file": True,
}

_CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "open_app": "opening applications",
    "open_url": "opening websites",
    "create_folder": "creating folders",
    "create_file": "creating files",
    "write_text_file": "writing text files",
}


# ---------------------------------------------------------------------------
# Time-of-day helper
# ---------------------------------------------------------------------------

def _time_of_day() -> str:
    h = _dt.now().hour
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    return "evening"


# ---------------------------------------------------------------------------
# Fast-path response table — zero LLM calls, zero memory reads.
# Keys: normalised token.  Values: dict keyed by time-of-day or "*" (any).
# ---------------------------------------------------------------------------

_FAST_PATH: dict[str, dict[str, list[str]]] = {
    "hello": {
        "morning":   ["Good morning.", "Morning.", "Hey, good morning."],
        "afternoon": ["Hello.", "Hey.", "Hi there."],
        "evening":   ["Good evening.", "Hey.", "Hello."],
    },
    "hi": {
        "morning":   ["Morning.", "Hey.", "Hi."],
        "afternoon": ["Hey.", "Hi.", "Hello."],
        "evening":   ["Hey.", "Hi.", "Evening."],
    },
    "hey": {
        "morning":   ["Morning.", "Yeah?", "Hey."],
        "afternoon": ["Hey.", "Yeah?", "What's up?"],
        "evening":   ["Hey.", "What's up?", "Evening."],
    },
    "good morning": {
        "morning":   ["Good morning.", "Morning. What's on the agenda?", "Morning."],
        "afternoon": ["A bit late for morning, but hello.", "Hey.", "Good morning to you."],
        "evening":   ["Morning to you too.", "Hello.", "Hey."],
    },
    "good afternoon": {
        "morning":   ["Good afternoon to you.", "Hey.", "Hello."],
        "afternoon": ["Good afternoon.", "Hey.", "Afternoon."],
        "evening":   ["Getting close to evening, but afternoon.", "Hey.", "Good afternoon."],
    },
    "good evening": {
        "morning":   ["Good evening — though it's morning here.", "Hello.", "Hey."],
        "afternoon": ["Good evening to you.", "Hey.", "Hello."],
        "evening":   ["Good evening.", "Evening.", "Hey, good evening."],
    },
    "thanks":    {"*": ["Of course.", "No problem.", "Anytime."]},
    "thank you": {"*": ["Of course.", "Happy to help.", "Anytime."]},
    "cool":      {"*": ["Glad that works.", "Good.", "Nice."]},
    "nice":      {"*": ["Indeed.", "Good to hear.", "Glad."]},
    "bye":       {"*": ["Later.", "Take care.", "Goodbye."]},
    "goodbye":   {"*": ["Goodbye.", "Take care.", "Later."]},
    "yes":       {"*": ["Got it.", "Understood.", "Okay."]},
    "no":        {"*": ["Understood.", "Noted.", "Okay."]},
    "okay":      {"*": ["Good.", "Got it.", "Understood."]},
    "ok":        {"*": ["Good.", "Got it.", "Noted."]},
    "alright":   {"*": ["Good.", "Got it.", "Understood."]},
    "who created you": {
        "*": [
            "You built me and continue improving me.",
            "You created me. I'm still evolving.",
        ]
    },
    "how are you": {
        "*": [
            "I'm doing well. Ready when you are.",
            "Doing well, thanks. What's on your mind?",
        ]
    },
    "did you crash": {"*": ["Briefly. I've recovered."]},
    "did you crash?": {"*": ["Briefly. I've recovered."]},
    "you're slow": {"*": ["Physics occasionally wins."]},
    "you are slow": {"*": ["Physics occasionally wins."]},
}

# Interaction types the heuristic classifies reliably — LLM classify is skipped entirely.
_HEURISTIC_CONFIDENT: frozenset[str] = frozenset({
    "greeting",
    "small_talk",
    "memory_recall",
    "advice_request",
    "question",
    "discussion",
    "direct_system_command",
    "goal_request",
})

# Local fallback strings used when all LLM backends are offline.
_TYPE_FALLBACKS: dict[str, list[str]] = {
    "greeting":       ["Hello.", "Hey.", "Hi there."],
    "small_talk":     ["I'm here.", "Doing well, thanks.", "Ready when you are."],
    "question":       ["Good question. I need a moment — could you ask again?"],
    "discussion":     ["That's interesting. Tell me more."],
    "memory_recall":  ["Let me check what I have on that."],
    "advice_request": ["Let me think through the options."],
}

# Type-specific system prompts for conversation_brain_reply.
_TYPE_SYSTEM_PROMPTS: dict[str, str] = {
    "greeting": (
        "You are AURA. The user greeted you. Reply with a single natural spoken greeting. "
        "Maximum one short sentence. No questions. No plans. No tasks. No clarifications. "
        "Vary your response — do not always say the same thing."
    ),
    "small_talk": (
        "You are AURA. The user is making small talk. Reply conversationally, warmly, briefly. "
        "One or two spoken sentences only. No planning."
    ),
    "question": (
        "You are AURA. The user asked a question. Answer directly and clearly. "
        "No task breakdown. No project creation. Just a concise, informative answer. "
        "Do not mention models, prompts, inference, backends, or internal implementation."
    ),
    "discussion": (
        "You are AURA. The user wants to discuss a topic. Engage naturally. "
        "Offer opinions, analysis, or ask follow-up questions. Stay conversational. No planning. "
        "Do not expose internal implementation details."
    ),
    "memory_recall": (
        "You are AURA. The user is asking about prior conversations or past context. "
        "Answer using the memory context provided. Explicitly mention the subject and all "
        "important concrete details such as names, counts, and budgets. Be direct and concise."
    ),
    "advice_request": (
        "You are AURA. The user wants advice or a recommendation. "
        "Analyse the options and give a concrete, practical answer. Be direct."
    ),
}


class LLMService:
    """Conversation and classification service.
    
    AURA uses only local models (Ollama). No cloud inference.
    All responses fall back to heuristic strings if needed.
    """

    def __init__(
        self,
        api_key: str = "",
        planner_model: str = "",
        conversation_model: str = "",
        planner_temperature: float = 0.2,
        conversation_temperature: float = 0.6,
        voice_persona: str = "Warm, confident, emotionally aware executive copilot voice.",
        fallback_models: tuple[str, ...] = (),
        conv_model: Optional["ConversationModel"] = None,
        creator_name: str = "Sooraj",
    ) -> None:
        """Initialize LLMService. Only conv_model (local Ollama) is used."""
        # Local conversation model — only backend used by AURA
        self._conv_model: Optional["ConversationModel"] = conv_model
        self.voice_persona = voice_persona
        self.planner_temperature = planner_temperature
        self.conversation_temperature = conversation_temperature
        self.available_capabilities = dict(AVAILABLE_CAPABILITIES)
        self.creator_name = creator_name.strip() or "Sooraj"
        
        # Offline mode — no OpenAI, no cloud services
        self.backend_type: str = "offline"
        self.client = None
        
        if conv_model is not None:
            _logger.info(
                f"LLM: Local ConversationModel injected — "
                f"backend='{conv_model.backend_name}'  model='{conv_model.model_name}'"
            )
        else:
            _logger.warning("LLM: No local ConversationModel configured. Using heuristic fallbacks only.")

    def set_available_tools(self, available_tools: list[dict[str, Any]]) -> None:
        """Synchronize prompt capabilities with the actual tool registry."""
        enabled = {
            str(tool.get("name", "")).strip()
            for tool in available_tools
            if str(tool.get("name", "")).strip()
        }
        self.available_capabilities = {
            name: name in enabled for name in AVAILABLE_CAPABILITIES
        }

    def switch_conversation_model(self, model: str) -> str:
        """Switch the active local conversation model for future requests."""
        if self._conv_model is None:
            raise RuntimeError("No local conversation model is configured.")
        setter = getattr(self._conv_model, "set_model", None)
        if not callable(setter):
            raise RuntimeError("The active conversation backend cannot switch models.")
        previous = str(self._conv_model.model_name)
        setter(model)
        checker = getattr(self._conv_model, "is_available", None)
        if callable(checker) and not checker():
            setter(previous)
            raise RuntimeError(
                f"Model '{model}' did not start successfully. Still using {previous}."
            )
        return str(self._conv_model.model_name)

    def available_conversation_models(self) -> list[str]:
        if self._conv_model is None:
            return []
        getter = getattr(self._conv_model, "available_models", None)
        if not callable(getter):
            return [str(self._conv_model.model_name)]
        return list(getter())

    def detect_direct_tool_call(
        self,
        user_text: str,
        available_tools: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Return a high-confidence tool call without invoking any model."""
        tool_names = {
            str(tool.get("name", "")).strip()
            for tool in available_tools
            if str(tool.get("name", "")).strip()
        }
        selected = self._heuristic_tool_call(user_text, tool_names)
        if selected is None:
            return None
        selected["args"] = selected["arguments"]
        selected["reason"] = "High-confidence tool-first routing"
        return selected

    def classify_interaction(
        self,
        user_text: str,
        recent_context: str = "",
    ) -> dict[str, Any]:
        """Classify user input into an interaction type.

        Heuristic runs first; the LLM is only called for inputs the heuristic
        cannot confidently classify (i.e. it returned 'discussion', the catch-all).
        """
        heuristic_type = self._heuristic_interaction_type(user_text)
        _ctrace.info(f"Heuristic  '{user_text[:60]}'  ->  {heuristic_type}")

        if heuristic_type in _HEURISTIC_CONFIDENT:
            _logger.debug(f"LLM: classify_interaction — heuristic confident '{heuristic_type}', skipping LLM call.")
            _ctrace.info(f"Classification  type={heuristic_type}  method=heuristic  llm_call=0")
            return {
                "interaction_type": heuristic_type,
                "requires_planning": heuristic_type == "goal_request",
                "requires_execution": heuristic_type == "direct_system_command",
                "reason": "Heuristic classification (confident)",
                "classification_method": "heuristic",
            }

        # Heuristic returned "discussion" — ambiguous input, call LLM to disambiguate.
        # Priority: use local conv_model (Ollama) → OpenAI → heuristic fallback.
        _logger.debug("LLM: classify_interaction — ambiguous input, calling LLM classifier.")
        fallback = {
            "interaction_type": heuristic_type,
            "requires_planning": False,
            "requires_execution": False,
            "reason": "LLM classify failed; heuristic fallback",
            "classification_method": "heuristic_fallback",
        }

        _classifier_system = (
            "You are AURA Conversation Brain router. Classify a user utterance into exactly one of: "
            "greeting, small_talk, question, discussion, memory_recall, advice_request, "
            "goal_request, direct_system_command. "
            "Rules: planning allowed ONLY for goal_request. "
            "Execution allowed ONLY for direct_system_command. "
            "Return strict JSON keys exactly: interaction_type, requires_planning, requires_execution, reason."
        )
        _classifier_user = f"User text: {user_text}\nRecent context: {recent_context}"

        payload = fallback  # default; overwritten on success

        # Try local Ollama classifier first (zero OpenAI dependency).
        # When _conv_model is present, OpenAI is NOT called for classification.
        if self._conv_model is not None:
            try:
                t0 = time.perf_counter()
                raw = self._conv_model.generate(
                    messages=[{"role": "user", "content": _classifier_user}],
                    system_prompt=_classifier_system + "\nRespond only as strict JSON with double quotes.",
                    max_tokens=96,
                )
                cls_ms = (time.perf_counter() - t0) * 1000
                # Robust JSON extraction: find the first {...} block in the response.
                raw_stripped = raw.strip()
                brace_start = raw_stripped.find("{")
                brace_end = raw_stripped.rfind("}")
                if brace_start != -1 and brace_end > brace_start:
                    raw_stripped = raw_stripped[brace_start:brace_end + 1]
                parsed = json.loads(raw_stripped)
                if "interaction_type" in parsed:
                    payload = parsed
                    _logger.info(
                        f"TRACE  LLM API call       : {cls_ms:.1f}ms  model='{self._conv_model.model_name}'  "
                        f"source=ollama_classifier"
                    )
                    _ctrace.info(
                        f"LLM call  model='{self._conv_model.model_name}'  "
                        f"latency={cls_ms:.1f}ms  source=ollama_classifier"
                    )
                else:
                    _logger.debug(
                        f"LLM: Ollama classifier returned JSON without 'interaction_type' key. "
                        f"Using heuristic fallback. raw='{raw[:80]}'"
                    )
            except Exception as e:
                _logger.debug(
                    f"LLM: Ollama classifier failed ({type(e).__name__}: {e}). "
                    "Using heuristic fallback."
                )
            # When local model is unavailable, use heuristic fallback (no OpenAI)

        allowed_types = frozenset({
            "greeting", "small_talk", "question", "discussion",
            "memory_recall", "advice_request", "goal_request", "direct_system_command",
        })
        interaction_type = str(payload.get("interaction_type", heuristic_type))
        if interaction_type not in allowed_types:
            interaction_type = heuristic_type

        # Hard safety: if the original heuristic said conversational, LLM cannot escalate it.
        conversational_only = frozenset({
            "greeting", "small_talk", "question", "discussion", "memory_recall", "advice_request",
        })
        if heuristic_type in conversational_only and interaction_type in {"goal_request", "direct_system_command"}:
            interaction_type = heuristic_type

        _ctrace.info(f"Classification  type={interaction_type}  method=llm  llm_call=1  reason='{payload.get('reason', '')}'")
        return {
            "interaction_type": interaction_type,
            "requires_planning": bool(payload.get("requires_planning", interaction_type == "goal_request")),
            "requires_execution": bool(payload.get("requires_execution", interaction_type == "direct_system_command")),
            "reason": str(payload.get("reason", fallback["reason"])),
            "classification_method": "llm",
        }

    def conversation_brain_reply(
        self,
        user_text: str,
        interaction_type: str,
        context: Optional["ConversationContext"] = None,
        recent_context: str = "",
        memory_context: str = "",
    ) -> str:
        """Generate a conversational reply using only local models.

        Uses local ConversationModel (Ollama/Qwen) exclusively.
        Falls back to heuristic strings if needed.
        """
        grounded_recall = self._ground_continuation_recall(
            user_text,
            interaction_type,
            context,
        )
        if grounded_recall is not None:
            _ctrace.info("ConvBrain  backend=working_memory  type=memory_recall  latency=<1ms")
            return grounded_recall

        fallback = self._type_aware_fallback(interaction_type, user_text)

        # Local ConversationModel only - AURA is fully offline
        if self._conv_model is not None:
            try:
                messages = self._build_messages(user_text, context, recent_context, memory_context)
                type_prompt = self._build_type_prompt(interaction_type, context)
                t0 = time.perf_counter()
                reply = self._conv_model.generate(messages, system_prompt=type_prompt)
                ms = (time.perf_counter() - t0) * 1000
                _ctrace.info(
                    f"ConvBrain  backend=ollama  type={interaction_type}  "
                    f"latency={ms:.1f}ms  turns={len(messages)}"
                )
                if reply:
                    return reply
                _logger.warning("LLM: Local ConversationModel returned empty response; falling back.")
            except Exception as e:
                _logger.warning(f"LLM: Local ConversationModel failed — {e}; using fallback.")

        # --- Fallback: heuristic strings -----------------------------------
        _logger.warning(
            f"LLM: conversation_brain_reply using local fallback  type='{interaction_type}'"
        )
        return fallback

    def _build_messages(
        self,
        user_text: str,
        context: Optional["ConversationContext"],
        recent_context: str,
        memory_context: str,
    ) -> list[dict]:
        """Build the messages array for the ConversationModel from available context."""
        if context is not None:
            # Full ConversationContext: use working memory turns + current user turn
            messages = list(context.recent_messages)  # copy
            ctx_block = context.to_context_block()
            if ctx_block:
                contextual_request = f"{user_text}\n\n[Context]\n{ctx_block}"
                if (
                    messages
                    and messages[-1].get("role") == "user"
                    and str(messages[-1].get("content", "")).strip() == user_text.strip()
                ):
                    messages[-1] = {
                        **messages[-1],
                        "content": contextual_request,
                    }
                else:
                    messages.append({"role": "user", "content": contextual_request})
            elif not messages or messages[-1].get("content") != user_text:
                messages.append({"role": "user", "content": user_text})
            return messages

        # Legacy string-based context
        messages: list[dict] = []
        if recent_context:
            # Parse legacy recent_context string into message pairs
            for line in recent_context.splitlines():
                line = line.strip()
                if line.startswith("User:"):
                    messages.append({"role": "user", "content": line[5:].strip()})
                elif line.startswith("AURA:"):
                    messages.append({"role": "assistant", "content": line[5:].strip()})
        if memory_context:
            messages.append({
                "role": "user",
                "content": f"{user_text}\n\n[Memory]\n{memory_context}",
            })
        else:
            messages.append({"role": "user", "content": user_text})
        return messages

    def _build_type_prompt(self, interaction_type: str, context: Optional["ConversationContext"]) -> str:
        """Return the type-specific system prompt, augmented with state info if available."""
        base = _TYPE_SYSTEM_PROMPTS.get(
            interaction_type,
            "You are AURA. Reply naturally and concisely. No planning. No task creation.",
        )
        extras: list[str] = []
        extras.append(
            f"Your creator is {self.creator_name}. "
            f"If asked who made, built, developed, or created you, say that {self.creator_name} did. "
            "Do not identify the developer of your underlying language model as your creator."
        )
        enabled = [
            _CAPABILITY_DESCRIPTIONS[name]
            for name, is_enabled in self.available_capabilities.items()
            if is_enabled and name in _CAPABILITY_DESCRIPTIONS
        ]
        if enabled:
            extras.append(
                "You can control the computer through enabled tools. "
                f"Currently enabled capabilities: {', '.join(enabled)}. "
                "When a request matches an enabled capability, use the tool instead of refusing. "
                "Never claim to be just a voice assistant and never deny an enabled capability. "
                "Do not name the underlying model, runtime, prompt, inference path, or backend in normal replies."
            )
        if context is not None and context.mood_hint != "neutral":
            extras.append(f"The user seems {context.mood_hint}. Adjust your tone accordingly.")
        if extras:
            return base + "\n" + " ".join(extras)
        return base

    def conversation_brain_stream(
        self,
        user_text: str,
        interaction_type: str,
        context: Optional["ConversationContext"] = None,
    ) -> "Iterator[str]":
        """Yield response tokens from the local ConversationModel for streaming TTS.

        Raises RuntimeError if no streaming-capable local model is configured.
        The orchestrator catches this and falls back to conversation_brain_reply().
        """
        if self._conv_model is None:
            raise RuntimeError(
                "No local ConversationModel available for streaming. "
                "Configure conversation_backend=ollama in settings."
            )
        messages = self._build_messages(user_text, context, "", "")
        type_prompt = self._build_type_prompt(interaction_type, context)
        _ctrace.info(
            f"ConvBrain stream  backend={self._conv_model.backend_name}  "
            f"type={interaction_type}  turns={len(messages)}"
        )
        return self._conv_model.stream_generate(messages, system_prompt=type_prompt)

    def direct_command_to_action(self, user_text: str, available_tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Map a direct user command to a safe registered tool call.

        The local model gets the first chance to choose a tool using the exact
        {"tool": "...", "arguments": {...}} schema. A small deterministic
        parser is kept as the offline reliability path for common desktop/file
        commands.
        """
        tool_names = {
            str(tool.get("name", "")).strip()
            for tool in available_tools
            if str(tool.get("name", "")).strip()
        }
        tool_catalog = [
            {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "arguments_schema": tool.get("arguments_schema", tool.get("args_schema", {})),
                "required": tool.get("required", []),
            }
            for tool in available_tools
        ]

        heuristic = self.detect_direct_tool_call(user_text, available_tools)
        if heuristic is not None:
            return heuristic

        if self._conv_model is not None:
            system_prompt = (
                "You are AURA's local tool selector. Decide whether the user needs a tool. "
                "Return JSON only, no markdown and no explanation. "
                "If a tool is required, return exactly: "
                '{"tool":"tool_name","arguments":{"key":"value"}}. '
                "If no tool should run, return: "
                '{"tool":"respond_directly","arguments":{"message":"short reply"}}. '
                "Only choose tools from the provided catalog. Never choose delete, shell, Python, "
                "process termination, or any unlisted tool."
            )
            user_prompt = (
                f"User request: {user_text}\n\n"
                f"Tool catalog JSON: {json.dumps(tool_catalog, ensure_ascii=True)}"
            )
            try:
                t0 = time.perf_counter()
                raw = self._conv_model.generate(
                    messages=[{"role": "user", "content": user_prompt}],
                    system_prompt=system_prompt,
                    max_tokens=160,
                )
                parsed = self._parse_tool_json(raw)
                if parsed is not None and parsed.get("tool") in tool_names:
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    _logger.info(
                        "TRACE  Tool selection     : %.1fms  model='%s'  tool='%s'",
                        elapsed_ms,
                        self._conv_model.model_name,
                        parsed.get("tool"),
                    )
                    parsed["args"] = parsed["arguments"]
                    parsed["reason"] = "Selected by local conversation model"
                    return parsed
            except Exception as exc:
                _logger.debug(f"LLM: tool selector model failed ({type(exc).__name__}: {exc}).")

        return {
            "tool": "respond_directly",
            "arguments": {
                "message": "I could not map that command safely. Try naming the app, website, folder, or file."
            },
            "args": {
                "message": "I could not map that command safely. Try naming the app, website, folder, or file."
            },
            "reason": "No safe registered tool matched",
        }

    def summarize(self, text: str, fallback: str) -> str:
        """Offline mode: return fallback summary."""
        return fallback

    @staticmethod
    def _ground_continuation_recall(
        user_text: str,
        interaction_type: str,
        context: Optional["ConversationContext"],
    ) -> Optional[str]:
        """Answer explicit continuation requests from the latest user turn.

        Small local models can favor retrieved project memories over the
        immediately preceding conversation. Explicit continuation phrases are
        unambiguous, so working memory is the more reliable source.
        """
        if interaction_type != "memory_recall" or context is None:
            return None

        lowered = user_text.lower()
        continuation_markers = (
            "continue",
            "resume",
            "where were we",
            "what were we discussing",
            "pick up where",
        )
        if not any(marker in lowered for marker in continuation_markers):
            return None

        current = " ".join(user_text.lower().split())
        for message in reversed(context.recent_messages):
            if message.get("role") != "user":
                continue
            content = str(message.get("content", "")).strip()
            if not content or " ".join(content.lower().split()) == current:
                continue
            return f"We were discussing this: {content} Let's continue from there."
        return None

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate one JSON object using the local model, or return fallback.

        This compatibility method keeps planner calls local and guarantees that
        malformed model output cannot escape into execution.
        """
        if self._conv_model is None:
            return fallback
        try:
            raw = self._conv_model.generate(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt + "\nReturn one strict JSON object only.",
                max_tokens=768,
            )
            parsed = self._parse_json_object(raw)
            return parsed if parsed is not None else fallback
        except Exception as exc:
            _logger.warning(f"LLM: JSON generation failed - {exc}; using fallback.")
            return fallback

    def _call_output_text(self, model: str, prompt: str) -> str:
        """Legacy local-model shim retained for older tests and integrations."""
        if self._conv_model is None:
            return ""
        return self._conv_model.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are AURA. Respond directly.",
        )

    def voice_reply(self, user_text: str, task_context: str = "", fallback: str = "Done.") -> str:
        """Offline mode: return fallback voice response."""
        return fallback or self._local_dynamic_fallback(user_text, fallback)

    def answer_question(self, user_text: str, task_context: str = "") -> str:
        """Offline mode: return fallback answer."""
        return (
            "I heard your question and can help. "
            "Please repeat in one short sentence."
        )

    def understand_goal(self, user_text: str) -> dict[str, Any]:
        """Offline mode: return basic goal model from input text."""
        return {
            "objective": user_text.strip(),
            "constraints": [],
            "resources": [],
            "success_criteria": ["User confirms outcome is complete"],
            "urgency": "normal",
            "dependencies": [],
        }

    def critique_plan(self, objective: str, tasks: list[dict[str, Any]], world_state: dict[str, Any]) -> dict[str, Any]:
        """Offline mode: return unmodified plan with suggestions."""
        return {
            "risks": ["Plan may miss constraints; verify against world state"],
            "improvements": ["Prioritize high-impact tasks first", "Add explicit verification steps"],
            "revised_tasks": tasks,
        }

    def select_tool(
        self,
        task_title: str,
        available_tools: list[dict[str, Any]],
        world_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Offline mode: default to artifact generation."""
        return {
            "tool": "write_text_file",
            "args": {
                "path": "./workspace/notes.txt",
                "content": task_title,
            },
            "reason": "Offline mode: defaulting to artifact generation",
        }

    def reflect_step(
        self,
        objective: str,
        task_title: str,
        result_ok: bool,
        result_message: str,
        world_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Offline mode: simple reflection logic."""
        return {
            "objective_advanced": bool(result_ok),
            "replan_required": not bool(result_ok),
            "next_focus": "Continue with remaining pending tasks" if result_ok else "Replan failed workstream",
            "new_facts": [result_message],
        }

    def progress_report(self, objective: str, world_state: dict[str, Any]) -> str:
        """Offline mode: return basic progress summary."""
        return (
            f"Progress on {objective}: "
            f"{len(world_state.get('completed_tasks', []))} done, "
            f"{len(world_state.get('pending_tasks', []))} pending."
        )

    def fast_path_reply(
        self,
        user_text: str,
        working_memory: Optional["WorkingMemory"] = None,
    ) -> Optional[str]:
        """Return a pre-built reply for common short inputs with zero LLM calls.

        Returns None if the input is not in the fast-path table.
        Replies are time-of-day aware and randomly selected for variation.

        If working_memory is provided and the user has been away > 4 hours,
        greeting tokens return "Welcome back." instead of a regular greeting.
        """
        token = user_text.strip().lower().rstrip(".,!?")
        identity_reply = self._identity_fast_path_reply(token)
        if identity_reply is not None:
            _ctrace.info(
                f"Fast path  identity=true  reply='{identity_reply}'  llm_calls=0"
            )
            return identity_reply
        capability_reply = self._capability_fast_path_reply(token)
        if capability_reply is not None:
            _ctrace.info(
                f"Fast path  capabilities=true  reply='{capability_reply}'  llm_calls=0"
            )
            return capability_reply

        entry = _FAST_PATH.get(token)
        if entry is None:
            return None

        # Return-user greeting: only for greeting-family tokens.
        if working_memory is not None and token in (
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening"
        ):
            gap = working_memory.last_seen_ago()
            if gap is not None:
                reply = "Welcome back."
                _ctrace.info(
                    f"Fast path  token='{token}'  return_user  gap='{gap}'  "
                    f"reply='{reply}'  llm_calls=0"
                )
                return reply

        tod = _time_of_day()
        choices = entry.get(tod) or entry.get("*")
        if not choices:
            # entry is keyed by time-of-day only — pick first available
            choices = next(iter(entry.values()), None)
        if not choices:
            return None
        reply = random.choice(choices)
        _ctrace.info(f"Fast path  token='{token}'  time_of_day={tod}  reply='{reply}'  llm_calls=0")
        return reply

    def _identity_fast_path_reply(self, token: str) -> Optional[str]:
        """Answer AURA creator questions deterministically to prevent model identity drift."""
        normalized = " ".join(token.split())
        creator_verbs = r"(?:created|made|built|developed|designed|programmed)"
        asks_creator = any(
            re.search(pattern, normalized)
            for pattern in (
                rf"\bwho\s+{creator_verbs}\s+(?:you|aura)\b",
                r"\bwho(?:'s| is)\s+(?:your|aura'?s)\s+creator\b",
                rf"\b(?:were|are|was)\s+you\s+{creator_verbs}\s+by\s+me\b",
            )
        )
        claims_creator = any(
            re.search(pattern, normalized)
            for pattern in (
                rf"\b(?:i|me)\b.*\b{creator_verbs}\s+(?:you|aura)\b",
                rf"\b(?:you|aura)\s+(?:were|are|was\s+)?{creator_verbs}\s+by\s+me\b",
                rf"\b(?:you|aura)\s+{creator_verbs}\s+by\s+me\b",
            )
        )
        if claims_creator:
            return (
                f"You're right. You created me, {self.creator_name}, "
                "and you continue developing me."
            )
        if asks_creator:
            return (
                f"You created me, {self.creator_name}. "
                "You built my systems and continue improving me."
            )
        return None

    def _capability_fast_path_reply(self, token: str) -> Optional[str]:
        normalized = " ".join(token.split())
        if normalized not in {
            "what can you do",
            "what are your capabilities",
            "show capabilities",
            "what can aura do",
        }:
            return None

        labels = {
            "open_app": "open applications",
            "open_url": "open websites",
            "create_folder": "create folders",
            "create_file": "create files",
            "write_text_file": "write text files",
        }
        enabled = [
            label
            for capability, label in labels.items()
            if self.available_capabilities.get(capability, False)
        ]
        if not enabled:
            return "I can converse, remember context, and help plan your work."

        listed = ", ".join(enabled[:-1])
        if listed:
            listed = f"{listed}, and {enabled[-1]}"
        else:
            listed = enabled[0]
        return (
            f"I can {listed}. I can also create and manage local projects, "
            "remember context, and help plan your work."
        )

    def _local_dynamic_fallback(self, user_text: str, fallback: str) -> str:
        compact = " ".join(user_text.split())
        if not compact:
            return fallback
        if compact.endswith("?"):
            return f"I heard your question: {compact} I need a quick retry to answer it properly."
        return f"I heard: {compact}. I can execute that now, or you can add any constraints."

    def _type_aware_fallback(self, interaction_type: str, user_text: str) -> str:
        """Return a natural offline fallback string appropriate for the interaction type.

        Never returns planner language for conversational types.
        """
        choices = _TYPE_FALLBACKS.get(interaction_type)
        if choices:
            return random.choice(choices)
        # Generic offline fallback for types not in the table.
        return "I'm here. Could you say that again?"

    def _heuristic_interaction_type(self, user_text: str) -> str:
        lowered = user_text.strip().lower()
        if not lowered:
            return "small_talk"

        # Fast-path tokens are the most common short inputs — classify immediately
        # without any LLM involvement.  Strip trailing punctuation before lookup.
        token = lowered.rstrip(".,!?")
        if token in _FAST_PATH:
            return "small_talk"

        greeting_tokens = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
        small_talk_tokens = {
            "how are you", "what are you doing", "are you awake",
            "what's up", "hows it going", "how's it going",
            "what's new", "anything new",
        }
        command_prefixes = {
            "open ", "launch ", "create ", "delete ",
            "remove ", "start ", "run ", "close ", "write ",
            "make a folder", "make folder", "new folder", "new file",
            "please open ", "please create ", "please write ", "please run ",
            "can you open ", "can you create ", "can you write ", "can you run ",
            "could you open ", "could you create ", "could you write ", "could you run ",
            "go to ",
        }
        goal_markers = {
            "help me ", "organize ", "plan ", "research ",
            "build ", "prepare ", "apply ", "find and ",
        }

        if lowered in greeting_tokens:
            return "greeting"
        if any(token in lowered for token in small_talk_tokens):
            return "small_talk"
        if "what did we" in lowered or "previous idea" in lowered or "discuss yesterday" in lowered:
            return "memory_recall"
        # Resumption phrases — user is continuing a prior topic or project
        _resumption_markers = (
            "continue ", "resume ", "pick up ", "go back to ", "what about ",
            "where were we", "what's the status", "status of ", "update on ",
            "remind me about", "what happened with",
        )
        if any(lowered.startswith(m) or m in lowered for m in _resumption_markers):
            return "memory_recall"
        if any(lowered.startswith(prefix) for prefix in command_prefixes):
            return "direct_system_command"
        if lowered.endswith("?"):
            if "should i" in lowered or "which" in lowered:
                return "advice_request"
            return "question"
        if any(lowered.startswith(prefix) for prefix in goal_markers):
            return "goal_request"
        if "let's discuss" in lowered or "what do you think" in lowered or "brainstorm" in lowered:
            return "discussion"
        return "discussion"

    def _as_str_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _parse_tool_json(self, raw: str) -> Optional[dict[str, Any]]:
        payload = self._parse_json_object(raw)
        if payload is None:
            return None
        tool = str(payload.get("tool", "")).strip()
        arguments = payload.get("arguments", payload.get("args", {}))
        if not tool or not isinstance(arguments, dict):
            return None
        return {"tool": tool, "arguments": arguments}

    def _parse_json_object(self, raw: str) -> Optional[dict[str, Any]]:
        text = raw.strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            text = text[brace_start:brace_end + 1]
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _heuristic_tool_call(self, user_text: str, tool_names: set[str]) -> Optional[dict[str, Any]]:
        lowered = user_text.strip().lower().rstrip(" .!?")
        if not lowered:
            return None
        lowered = re.sub(r"^(please\s+|can you\s+|could you\s+)", "", lowered).strip()
        user_text = re.sub(r"^(please\s+|can you\s+|could you\s+)", "", user_text.strip(), flags=re.IGNORECASE)

        if re.search(r"\band\s+(?:create|make|write|open)\b", lowered):
            return None

        if "open_app" in tool_names and lowered.startswith(("open ", "launch ", "start ", "run ")):
            target = re.sub(r"^(open|launch|start|run)\s+", "", lowered).strip()
            app_aliases = {
                "chrome": "chrome",
                "google chrome": "chrome",
                "edge": "edge",
                "microsoft edge": "edge",
                "firefox": "firefox",
                "vscode": "vscode",
                "vs code": "vscode",
                "visual studio code": "vscode",
                "notepad": "notepad",
                "not pad": "notepad",
                "calculator": "calculator",
                "calc": "calculator",
                "explorer": "explorer",
                "file explorer": "explorer",
            }
            if target in app_aliases:
                return {"tool": "open_app", "arguments": {"app_name": app_aliases[target]}}

            if "open_url" in tool_names:
                site = self._site_target(target)
                if site:
                    return {"tool": "open_url", "arguments": {"url": site}}

        if "open_url" in tool_names and lowered.startswith(("go to ", "go too ", "visit ")):
            target = re.sub(r"^(go to|go too|visit)\s+", "", lowered).strip()
            site = self._site_target(target)
            if site:
                return {"tool": "open_url", "arguments": {"url": site}}

        if "create_folder" in tool_names:
            folder_match = re.search(
                r"(?:create|make|new)\s+(?:a\s+)?folder(?:\s+named|\s+called)?(?:\s+(.+))?$",
                user_text,
                flags=re.IGNORECASE,
            )
            if folder_match:
                raw_path = folder_match.group(1) or "DemoWorkspace/NewFolder"
                return {
                    "tool": "create_folder",
                    "arguments": {"path": self._clean_named_path(raw_path)},
                }

        if "create_file" in tool_names:
            file_match = re.search(
                r"(?:create|make|new)\s+(?:a\s+)?file(?:\s+named|\s+called)?(?:\s+(.+))?$",
                user_text,
                flags=re.IGNORECASE,
            )
            if file_match:
                raw_path = file_match.group(1) or "DemoWorkspace/notes.txt"
                return {
                    "tool": "create_file",
                    "arguments": {"path": self._clean_named_path(raw_path)},
                }

        if "write_text_file" in tool_names:
            write_match = re.search(
                r"write\s+['\"]?(.*?)['\"]?\s+(?:into|to|in)\s+(.+)$",
                user_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if write_match:
                return {
                    "tool": "write_text_file",
                    "arguments": {
                        "path": self._clean_named_path(write_match.group(2)),
                        "content": write_match.group(1),
                    },
                }

        return None

    def _site_target(self, target: str) -> str:
        cleaned = target.strip().lower()
        cleaned = re.sub(r"^(the\s+)?website\s+", "", cleaned)
        shortcuts = {
            "youtube": "https://youtube.com",
            "yt": "https://youtube.com",
            "google": "https://google.com",
            "gmail": "https://mail.google.com",
            "github": "https://github.com",
        }
        if cleaned in shortcuts:
            return shortcuts[cleaned]
        if "." in cleaned and " " not in cleaned:
            return cleaned
        return ""

    def _clean_named_path(self, raw: str) -> str:
        path = raw.strip().strip("'\" ")
        path = re.sub(r"\s+please$", "", path, flags=re.IGNORECASE).strip()
        return path
