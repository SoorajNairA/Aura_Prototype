from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.verification.adapters.architecture_analysis import ArchitectureIntelligenceEngine
from aura.infrastructure.voice.audio_io import AudioIO
from aura.app.config import Settings
from aura.legacy.assistant.conversation_context import (
    ConversationContextBuilder,
    ConversationState,
    WorkingMemory,
)
from aura.infrastructure.llm.ollama import ConversationModel
from aura.legacy.assistant.executive_behavior import ExecutiveBehavior
from aura.legacy.assistant.executive_agent import AssumptionEngine, ExecutiveAgent, ExecutionVerifier
from aura.legacy.assistant.llm import LLMService
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest, GoalState
from aura.legacy.assistant.planner import PlannerAgent
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer
from aura.infrastructure.voice.stt import STTService
from aura.infrastructure.voice.tts import TTSService

_logger = logging.getLogger("aura")
_ctrace = logging.getLogger("aura.trace")


class AuraSupervisor:
    def __init__(
        self,
        settings: Settings,
        conversation_model: Optional[ConversationModel] = None,
    ) -> None:
        self.settings = settings

        self.audio = AudioIO(
            sample_rate=settings.sample_rate,
            max_record_seconds=settings.max_record_seconds,
            silence_threshold=settings.silence_threshold,
            silence_hold_seconds=settings.silence_hold_seconds,
        )
        self.stt = STTService(settings.stt_model, settings.stt_device, settings.stt_compute_type)
        self.tts = TTSService(
            settings.elevenlabs_api_key,
            settings.elevenlabs_voice_id,
            settings.elevenlabs_model_id,
            settings.elevenlabs_stability,
            settings.elevenlabs_similarity_boost,
            settings.elevenlabs_style,
            settings.elevenlabs_speaker_boost,
            settings.elevenlabs_clarity,
            settings.elevenlabs_naturalness,
            settings.local_tts_rate,
            settings.local_tts_voice_index,
            backend=settings.tts_backend,
            voice_reference=str(settings.voice_reference),
            device=settings.tts_device,
            auto_warmup=settings.auto_warmup,
            cache_dir=str(settings.tts_cache_dir),
        )
        self.llm = LLMService(
            api_key=settings.openai_api_key,
            planner_model=settings.openai_planner_model,
            conversation_model=settings.openai_conversation_model,
            planner_temperature=settings.openai_planner_temperature,
            conversation_temperature=settings.openai_conversation_temperature,
            voice_persona=settings.voice_persona,
            fallback_models=settings.openai_fallback_models,
            conv_model=conversation_model,
            creator_name=settings.creator_name,
        )

        self.memory = MemoryStore(settings.memory_dir)
        self.architecture = ArchitectureIntelligenceEngine(
            project_root=Path(__file__).resolve().parents[2],
            memory=self.memory,
        )
        self.planner = PlannerAgent(self.llm)
        self.safety = SafetyLayer()
        self.executor = ExecutionAgent(max_research_results=settings.max_research_results)
        self.llm.set_available_tools(self.executor.tool_catalog())
        self.result_revealer = ResultRevealer(enabled=settings.auto_reveal_results)

        # In Demo Mode, use an isolated workspace to prevent cluttering judge PCs.
        if settings.demo_mode:
            workspace_root = settings.demo_workspace.resolve()
            _logger.info(f"DEMO MODE ACTIVE: Workspace redirected to {workspace_root}")
        else:
            workspace_root = Path.cwd()
        self.executor.workspace_root = workspace_root.resolve()

        self.executive = ExecutiveAgent(
            planner=self.planner,
            executor=self.executor,
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(workspace_root),
            memory=self.memory,
            safety=self.safety,
            workspace_root=workspace_root,
            confirmation_callback=self._confirm,
            result_revealer=self.result_revealer,
            status_callback=self._report_status,
        )

        # v2: Working memory replaces flat conversation_history list.
        self.working_memory: WorkingMemory = WorkingMemory(max_turns=30)
        # Legacy alias — keeps any code still referencing conversation_history working.
        self.conversation_history = self.working_memory

        # Conversation state machine.
        self.conversation_state: ConversationState = ConversationState.IDLE

        # Context builder — assembles ConversationContext per request.
        self.context_builder = ConversationContextBuilder(
            memory=self.memory,
            working_memory=self.working_memory,
        )

        self._first_run_completed = False
        self._ui_listeners: list[Callable[[str, Any], None]] = []

    def listen_once(self, level_callback: Optional[Callable[[float], None]] = None) -> str:
        self._notify_ui("state", "LISTENING")
        wav_path = self.audio.record_until_silence(level_callback=level_callback)
        self._notify_ui("state", "THINKING")
        return self.stt.transcribe(wav_path)

    def _speak(self, text: str) -> None:
        self._notify_ui("speech_started", text)
        try:
            self.tts.speak(text)
        finally:
            self._notify_ui("speech_finished", "")

    def add_ui_listener(self, listener: Callable[[str, Any], None]) -> None:
        if listener not in self._ui_listeners:
            self._ui_listeners.append(listener)

    def remove_ui_listener(self, listener: Callable[[str, Any], None]) -> None:
        if listener in self._ui_listeners:
            self._ui_listeners.remove(listener)

    def _notify_ui(self, event: str, payload: Any) -> None:
        for listener in list(getattr(self, "_ui_listeners", [])):
            try:
                listener(event, payload)
            except Exception:
                _logger.debug("HUD listener failed.", exc_info=True)

    def _report_status(self, message: str) -> None:
        self._notify_ui("status", message)
        _logger.info("STATUS: %s", message)

    def _set_conversation_state(self, state: ConversationState) -> None:
        self.conversation_state = state
        self._notify_ui("state", state.value.upper())

    def _confirm(self, spoken_prompt: str) -> bool:
        self._speak(spoken_prompt)
        heard = self.listen_once().lower()
        if any(word in heard for word in self.settings.confirm_words):
            return True
        if any(word in heard for word in self.settings.reject_words):
            return False
        return False

    def _announce_plan(self, goal_state: GoalState) -> None:
        top = "; ".join(item.title for item in goal_state.plan[:3])
        summary = self.llm.summarize(
            text=(
                f"Goal: {goal_state.goal}\n"
                f"Constraints: {goal_state.constraints}\n"
                f"Top tasks: {top}"
            ),
            fallback=f"I created a plan. Top tasks are: {top}",
        )
        self._speak(summary)

    def _build_world_state(self, goal_info: dict[str, Any], goal_state: GoalState) -> dict[str, Any]:
        return {
            "active_goal": goal_info.get("objective", goal_state.goal),
            "known_facts": [],
            "constraints": goal_info.get("constraints", []),
            "resources": goal_info.get("resources", []),
            "success_criteria": goal_info.get("success_criteria", []),
            "urgency": goal_info.get("urgency", "normal"),
            "dependencies": goal_info.get("dependencies", []),
            "completed_tasks": [],
            "failed_tasks": [],
            "pending_tasks": [item.model_dump() for item in goal_state.plan if item.status == "pending"],
            "generated_artifacts": [],
            "observations": [],
        }

    def _update_world_after_step(
        self,
        world_state: dict[str, Any],
        task: dict[str, Any],
        request: ActionRequest,
        result_message: str,
        result_ok: bool,
        output: dict[str, Any],
    ) -> None:
        pending = world_state.get("pending_tasks", [])
        world_state["pending_tasks"] = [
            p for p in pending if p.get("id") != task.get("id")
        ]
        if result_ok:
            world_state.setdefault("completed_tasks", []).append(task)
        else:
            world_state.setdefault("failed_tasks", []).append(task)

        observation = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": task,
            "request": request.model_dump(),
            "result_ok": result_ok,
            "result_message": result_message,
            "output": output,
        }
        world_state.setdefault("observations", []).append(observation)

        report_path = output.get("report_path")
        if isinstance(report_path, str) and report_path:
            world_state.setdefault("generated_artifacts", []).append(report_path)

    def _execute_goal_pipeline(self, goal_text: str) -> None:
        self._set_conversation_state(ConversationState.PLANNING)
        goal_info = self.llm.understand_goal(goal_text)
        objective = goal_info.get("objective", goal_text)

        self._speak(
            self.llm.voice_reply(
                user_text=goal_text,
                task_context=(
                    f"Understood objective: {objective}. "
                    "Acknowledge and announce that execution loop is starting."
                ),
                fallback="Understood. I am starting goal analysis and execution now.",
            )
        )

        goal_state = self.planner.create_plan(objective, known_constraints={"constraints": goal_info.get("constraints", [])})
        world_state = self._build_world_state(goal_info, goal_state)
        goal_state = self.planner.critique_and_revise(goal_state, world_state)
        world_state["pending_tasks"] = [item.model_dump() for item in goal_state.plan if item.status == "pending"]

        self._announce_plan(goal_state)
        self._set_conversation_state(ConversationState.EXECUTING)

        step = 0
        while step < self.settings.max_execution_steps and world_state.get("pending_tasks"):
            step += 1
            task = world_state["pending_tasks"][0]
            task_title = task.get("title", "Unnamed task")

            selection = self.llm.select_tool(task_title, self.executor.tool_catalog(), world_state)
            valid_tool_names = {tool["name"] for tool in self.executor.tool_catalog()}
            if selection["tool"] not in valid_tool_names:
                selection = {
                    "tool": "write_text_file",
                    "args": {
                        "path": "./workspace/notes.txt",
                        "content": f"{task_title}\n\nTool selection fallback triggered.",
                    },
                    "reason": "Selected tool unavailable; falling back to artifact generation.",
                }

            if selection["tool"] == "respond_directly" and not str(selection["args"].get("message", "")).strip():
                selection["args"]["message"] = self.llm.answer_question(
                    user_text=goal_text,
                    task_context=(
                        f"Task: {task_title}. "
                        "Answer conversationally and concretely with no generic filler."
                    ),
                )

            request = ActionRequest(action=selection["tool"], args=selection["args"])
            request.risk = self.safety.classify(request.action)

            if self.safety.requires_confirmation(request):
                approved = self._confirm(
                    f"High risk action {request.action} is next. Do you approve?"
                )
                if not approved:
                    self._update_world_after_step(
                        world_state,
                        task,
                        request,
                        "Rejected by user",
                        False,
                        {},
                    )
                    continue

            result = self.executor.run(request)
            if result.ok:
                self._reveal_action_result(request, result)
            self._update_world_after_step(
                world_state,
                task,
                request,
                result.message,
                result.ok,
                result.output,
            )

            self.memory.append_log(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "goal": objective,
                    "world_state": world_state,
                    "task": task,
                    "request": request.model_dump(),
                    "result": result.model_dump(),
                    "selection_reason": selection.get("reason", ""),
                }
            )

            reflection = self.llm.reflect_step(
                objective=objective,
                task_title=task_title,
                result_ok=result.ok,
                result_message=result.message,
                world_state=world_state,
            )
            world_state["known_facts"].extend(reflection.get("new_facts", []))

            if reflection.get("replan_required", False):
                goal_state = self.planner.replan_after_failure(goal_state, task.get("id", "UNKNOWN"), result.message)
                goal_state = self.planner.critique_and_revise(goal_state, world_state)
                world_state["pending_tasks"] = [
                    item.model_dump() for item in goal_state.plan if item.status == "pending"
                ]

            spoken_response = result.output.get("spoken_response")
            if isinstance(spoken_response, str) and spoken_response.strip():
                self._speak(spoken_response.strip())

            self._speak(self.llm.progress_report(objective, world_state))

        project_data = {
            "goal_state": goal_state.model_dump(),
            "world_state": world_state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.memory.upsert_project(key=objective, project_data=project_data)
        self._speak(self.llm.progress_report(objective, world_state))
        self._set_conversation_state(ConversationState.CONVERSING)

    def _recent_conversation_context(self, limit: int = 6) -> str:
        turns = self.working_memory.recent(n=limit)
        if not turns:
            return ""
        return "\n".join(
            f"{t['role'].capitalize()}: {t['content']}" for t in turns
        )

    def _append_conversation_turn(self, role: str, text: str) -> None:
        self.working_memory.append(role, text)

    def _handle_demo_commands(self, text: str) -> bool:
        settings = getattr(self, "settings", None)
        if settings is None or not getattr(settings, "demo_mode", False):
            return False

        lowered = text.lower()
        if "show capabilities" in lowered:
            capabilities = (
                "I'm AURA, your local executive assistant. I can:\n"
                "- Conversation and Memory: I remember our past interactions.\n"
                "- Desktop Automation: I can open applications and websites.\n"
                "- Project Generation: I can build games, websites, and scripts from scratch.\n"
                "- Task Planning: I decompose complex goals into executable steps.\n"
                "- Voice Interaction: I can listen and respond naturally.\n"
                "- Offline Operation: I run on this computer."
            )
            self._speak(capabilities)
            self._append_conversation_turn("assistant", capabilities)
            return True

        if "run demo" in lowered or "execute demo" in lowered:
            self._speak("Starting the showcase demo. I will now demonstrate my core capabilities.")
            demo_steps = [
                "Open VS Code",
                "Create a Snake Game in Python",
                "Draft a Sponsor Email",
                "Show capabilities"
            ]
            for step in demo_steps:
                self._speak(f"Step: {step}")
                time.sleep(1)  # Brief pause for effect.
                self.handle_spoken_text(step, require_wake_word=False)

            self._speak("Demo sequence completed. I am ready for your next objective.")
            return True

        return False

    def _memory_recall_context(self, spoken_query: str) -> str:
        projects = self.memory.get_projects()
        logs = self.memory.read_recent_logs(limit=80)
        terms = [t for t in spoken_query.lower().split() if len(t) > 2]

        snippets: list[str] = []
        for key, project in projects.items():
            joined = f"{key} {project}".lower()
            if terms and not any(t in joined for t in terms):
                continue
            snippets.append(f"Project: {key}")
            if len(snippets) >= 3:
                break

        for event in reversed(logs):
            joined = str(event).lower()
            if terms and not any(t in joined for t in terms):
                continue
            goal = event.get("goal", "")
            task = event.get("task", {}).get("title", "")
            result = event.get("result", {}).get("message", "")
            if goal or task or result:
                snippets.append(f"Log: goal={goal}; task={task}; result={result}")
            if len(snippets) >= 6:
                break

        if not snippets:
            return "No relevant memory found."
        return "\n".join(snippets)

    def _execute_direct_command(
        self,
        command_text: str,
        selection: Optional[dict[str, Any]] = None,
    ) -> None:
        selection = selection or self.llm.direct_command_to_action(
            command_text,
            self.executor.tool_catalog(),
        )
        valid_tool_names = {tool["name"] for tool in self.executor.tool_catalog()}
        selected_tool = selection.get("tool", "")
        if selected_tool not in valid_tool_names:
            selected_tool = "respond_directly"
            selection = {
                "tool": "respond_directly",
                "args": {
                    "message": (
                        "I could not safely map that system command yet. "
                        "Please specify the exact app name or full file path."
                    )
                },
                "reason": "Invalid tool from direct command parser",
            }

        request = ActionRequest(action=selected_tool, args=selection.get("args", {}))
        request.risk = self.safety.classify(request.action)
        if self.safety.requires_confirmation(request):
            approved = self._confirm(f"High risk action {request.action} is requested. Do you approve?")
            if not approved:
                self._speak("Understood. I cancelled that command.")
                return
        path = str(request.args.get("path", "")).strip()
        if path:
            path_decision = self.safety.assess_path(
                request.action,
                path,
                self.executor.workspace_root,
                self.executor.approved_roots,
            )
        else:
            path_decision = None
        if path_decision is not None and path_decision.denied:
            self._speak(f"I blocked that file operation. {path_decision.reason}")
            return
        if path_decision is not None and path_decision.requires_confirmation:
            approved = self._confirm(f"{path_decision.reason} Approve access to {path_decision.target}?")
            if not approved:
                self._speak("Understood. I kept the file operation inside the approved scope.")
                return
            if "existing" in path_decision.reason.lower():
                request.args["overwrite"] = True
            if "outside approved workspace" in path_decision.reason:
                request.args["allow_external_write"] = True

        status_message = self._direct_command_status_message(request)
        if status_message:
            self._report_status(status_message)
        pre_message = self._direct_command_pre_message(request)
        if pre_message:
            self._speak(pre_message)

        result = self.executor.run(request)
        if not result.ok:
            recovered = self._recover_direct_command(request, result)
            if recovered is not None:
                request, result = recovered
        self._report_status("Verifying results...")
        revealed = self._reveal_action_result(request, result) if result.ok else False
        self.memory.append_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "direct_command",
                "command": command_text,
                "request": request.model_dump(),
                "result": result.model_dump(),
                "selection_reason": selection.get("reason", ""),
            }
        )

        spoken_response = result.output.get("spoken_response")
        if isinstance(spoken_response, str) and spoken_response.strip():
            self._speak(spoken_response.strip())
            return
        if result.ok:
            final_message = self._direct_command_result_message(request, result, revealed)
            self._report_status("Completed.")
            self._speak(self.llm.voice_reply(command_text, task_context=f"Command completed: {final_message}", fallback=final_message))
            return
        self._report_status("Trying another route.")
        self._speak(self.llm.voice_reply(
            command_text,
            task_context=f"Command failed: {result.message}",
            fallback=ExecutiveBehavior.sanitize_for_user(result.message),
        ))

    def _direct_command_pre_message(self, request: ActionRequest) -> str:
        if request.action == "open_app":
            app = str(request.args.get("app_name", request.args.get("app", "that app"))).strip()
            return f"Opening {_friendly_app_name(app)}."
        if request.action == "open_url":
            url = str(request.args.get("url", "that site")).strip()
            return f"Opening {_friendly_url_name(url)}."
        return ""

    def _direct_command_status_message(self, request: ActionRequest) -> str:
        if request.action in {"open_app", "open_url"}:
            return "Launching..."
        if request.action == "create_folder":
            return "Creating folders..."
        if request.action in {"create_file", "write_text_file"}:
            return "Generating files..."
        return "Executing..."

    def _direct_command_result_message(
        self,
        request: ActionRequest,
        result: Any,
        revealed: bool = False,
    ) -> str:
        if result.output.get("fallback_used"):
            return result.message
        if request.action == "open_app":
            app = str(result.output.get("app_name") or request.args.get("app_name", "That app")).strip()
            return f"{app} is open."
        if request.action == "open_url":
            return f"{_friendly_url_name(str(request.args.get('url', 'that site')))} is open."
        if request.action == "create_folder" and revealed:
            path = Path(str(request.args.get("path", "folder")))
            return f"Done. Created {path.name} and opened it."
        if request.action in {"create_file", "write_text_file"} and revealed:
            path = Path(str(request.args.get("path", "file")))
            return f"Done. Saved and opened {path.name}."
        return result.message

    def _recover_direct_command(
        self,
        request: ActionRequest,
        result: Any,
    ) -> tuple[ActionRequest, Any] | None:
        self._report_status("Trying another route.")
        if request.action == "open_app":
            app = str(request.args.get("app_name", "")).strip().lower().replace(" ", "")
            if app in {"vscode", "visualstudiocode"}:
                fallback = ActionRequest(action="open_app", args={"app_name": "explorer"})
                fallback.risk = self.safety.classify(fallback.action)
                fallback_result = self.executor.run(fallback)
                if fallback_result.ok:
                    fallback_result.message = "VS Code wasn't available, so I opened Explorer instead."
                    fallback_result.output["fallback_used"] = True
                    fallback_result.output["fallback_reason"] = "vscode_unavailable"
                    return fallback, fallback_result
            if app in {"chrome", "googlechrome", "edge", "microsoftedge", "firefox"}:
                fallback = ActionRequest(action="open_url", args={"url": "https://google.com"})
                fallback.risk = self.safety.classify(fallback.action)
                fallback_result = self.executor.run(fallback)
                if fallback_result.ok:
                    fallback_result.message = "The requested browser wasn't available, so I opened the default browser."
                    fallback_result.output["fallback_used"] = True
                    fallback_result.output["fallback_reason"] = "browser_unavailable"
                    return fallback, fallback_result
        return None

    def _reveal_action_result(self, request: ActionRequest, result: Any) -> bool:
        revealer = getattr(self, "result_revealer", None)
        if revealer is None or not revealer.enabled:
            return False
        if request.action == "open_app":
            return revealer.reveal_application(result.output)
        if request.action == "open_url":
            return revealer.reveal_url(str(result.output.get("url", "")))
        if request.action == "create_folder":
            return revealer.reveal_folder(str(request.args.get("path", "")))
        if request.action in {"create_file", "write_text_file"}:
            return revealer.reveal_file(str(request.args.get("path", "")))
        report_path = result.output.get("report_path")
        if isinstance(report_path, str) and report_path:
            return revealer.reveal_file(report_path)
        return False

    def _handle_conversation(self, user_text: str, interaction_type: str) -> None:
        # ------------------------------------------------------------------
        # Fast path: exact token match — zero LLM calls, zero memory reads.
        # ------------------------------------------------------------------
        contextual_greeting = self._contextual_greeting_reply(user_text)
        if contextual_greeting is not None:
            self._append_conversation_turn("assistant", contextual_greeting)
            self._speak(contextual_greeting)
            return

        fast_reply = self.llm.fast_path_reply(user_text, working_memory=self.working_memory)
        if fast_reply is not None:
            _ctrace.info("" + "-" * 46)
            _ctrace.info(f"Request        : '{user_text}'")
            _ctrace.info(f"Classification : {interaction_type}  (heuristic)")
            _ctrace.info("Fast Path      : YES")
            _ctrace.info("LLM Calls      : 0")
            _ctrace.info("Memory Lookup  : 0")
            _ctrace.info("Planner        : SKIPPED")
            _ctrace.info("Safety Check   : SKIPPED")
            _ctrace.info(f"Response       : '{fast_reply}'")
            _logger.info(f"TRACE  Fast Path          : <1ms  (no LLM call) → '{fast_reply}'")
            self._append_conversation_turn("assistant", fast_reply)
            t0 = time.perf_counter()
            self._speak(fast_reply)
            _logger.info(f"TRACE  TTS Total          : {(time.perf_counter() - t0) * 1000:.1f}ms")
            return

        # ------------------------------------------------------------------
        # Normal conversation path.
        # ------------------------------------------------------------------
        _ctrace.info("-" * 46)
        _ctrace.info(f"Request        : '{user_text}'")
        _ctrace.info(f"Classification : {interaction_type}")
        _ctrace.info("Fast Path      : NO")
        _logger.info("TRACE  [Safety Check]     : skipped — conversation mode, no risk assessment needed")
        _logger.info("TRACE  [Planner]          : skipped — conversation mode, no goal decomposition")
        _ctrace.info("Planner        : SKIPPED")
        _ctrace.info("Safety Check   : SKIPPED")

        memory_context = ""
        if interaction_type == "memory_recall":
            t0 = time.perf_counter()
            memory_context = self._memory_recall_context(user_text)
            mem_ms = (time.perf_counter() - t0) * 1000
            _logger.info(f"TRACE  Memory Retrieval   : {mem_ms:.1f}ms")
            _ctrace.info(f"Memory Lookup  : {mem_ms:.1f}ms")
        else:
            _logger.info(f"TRACE  Memory Retrieval   : skipped — type='{interaction_type}' does not require lookup")
            _ctrace.info("Memory Lookup  : SKIPPED")

        t0 = time.perf_counter()
        ctx = self.context_builder.build(
            user_text=user_text,
            interaction_type=interaction_type,
            state=self.conversation_state,
        )

        # ------------------------------------------------------------------
        # Streaming path (default): pipe tokens directly to TTS as chunks.
        # First spoken words arrive after the first chunk (~20 words) rather
        # than after the full response, significantly reducing perceived latency.
        # Falls back to full-response mode if streaming is unavailable.
        # ------------------------------------------------------------------
        reply = ""
        streamed = False
        try:
            if interaction_type == "memory_recall":
                raise RuntimeError("Memory recall uses grounded full-response mode.")
            token_stream = self.llm.conversation_brain_stream(
                user_text=user_text,
                interaction_type=interaction_type,
                context=ctx,
            )
            self._notify_ui("speech_started", "")
            try:
                assembled = self.tts.speak_streamed(token_stream)
            finally:
                self._notify_ui("speech_finished", "")
            if assembled:
                # At least one chunk was spoken — streaming succeeded.
                reply = assembled
                streamed = True
            else:
                # speak_streamed returned empty: stream produced 0 chunks.
                # Treat as "stream never started" and fall through to full-response.
                raise RuntimeError("Stream produced empty reply.")
        except Exception as stream_err:
            if streamed:
                # Some chunks were spoken but stream failed mid-way.
                # Use what we have — don't re-speak.
                _logger.warning(f"TRACE  Stream partial     : mid-stream error — {stream_err!r}")
            else:
                # Stream never started — full fallback.
                _logger.info(f"TRACE  Stream fallback     : {stream_err!r}  (full-response mode)")
                reply = self.llm.conversation_brain_reply(
                    user_text=user_text,
                    interaction_type=interaction_type,
                    context=ctx,
                )
                t_speak = time.perf_counter()
                self._speak(reply)
                _logger.info(f"TRACE  TTS Total          : {(time.perf_counter() - t_speak) * 1000:.1f}ms")

        conv_ms = (time.perf_counter() - t0) * 1000
        mode = "streaming" if streamed else "full-response"
        _logger.info(f"TRACE  Conversation total : {conv_ms:.0f}ms  mode={mode}")
        _ctrace.info(f"Conversation Model : {conv_ms:.0f}ms  mode={mode}")
        _ctrace.info(f"Response       : '{reply[:120]}'")

        self._append_conversation_turn("assistant", reply)

    def _contextual_greeting_reply(self, user_text: str) -> str | None:
        token = user_text.strip().lower().rstrip(".,!?")
        if token not in {"hello", "hi", "hey", "good morning", "good afternoon", "good evening"}:
            return None
        try:
            projects = self.memory.get_projects()
        except Exception:
            projects = {}
        if projects:
            name = str(next(reversed(projects))).replace("_", " ").title()
            return f"Welcome back. We still have {name} open."
        try:
            logs = self.memory.read_recent_logs(limit=1)
        except Exception:
            logs = []
        if logs:
            latest = logs[-1]
            goal = str(latest.get("goal") or latest.get("command") or "").strip()
            if goal:
                return f"Welcome back. Last time, we were working on {goal}."
        return None

    def handle_spoken_text(self, spoken: str, require_wake_word: bool = True) -> bool:
        spoken = spoken.strip()
        if not spoken:
            return True

        lowered = spoken.lower()
        if _is_shutdown_command(lowered):
            self._speak("Shutting down. Goodbye.")
            return False

        goal_text = spoken
        if require_wake_word:
            extracted = _extract_wake_request(spoken, self.settings.wake_word)
            if extracted is None:
                return True
            goal_text = extracted

        if not goal_text:
            self._speak("I heard the wake word but not the message. Please repeat.")
            return True

        req_start = time.perf_counter()
        _logger.info("TRACE " + "=" * 50)
        _logger.info(f"TRACE  New request        : '{goal_text}'")
        _logger.info("TRACE  Audio Capture      : bypassed (text already transcribed by STTService)")

        self._append_conversation_turn("user", goal_text)

        # Demo Commands
        if self._handle_demo_commands(goal_text):
            _logger.info(f"Router: Demo command handled: '{goal_text}'")
            return True

        architecture = getattr(self, "architecture", None)
        if architecture is not None and architecture.can_handle(goal_text):
            answer = architecture.answer(goal_text)
            response = answer.answer
            if answer.diagram:
                response = f"{response}\n\n{answer.diagram}"
            self._speak(response)
            self._append_conversation_turn("assistant", response)
            _logger.info(
                "Router: ArchitectureIntelligence handled request confidence=%.2f",
                answer.confidence,
            )
            _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
            _logger.info("TRACE " + "=" * 50)
            return True

        tool_selection = self.llm.detect_direct_tool_call(
            goal_text,
            self.executor.tool_catalog(),
        )
        if tool_selection is not None:
            _logger.info(
                "Router: Tool-first match tool='%s' args=%s",
                tool_selection.get("tool"),
                tool_selection.get("arguments", {}),
            )
            _ctrace.info(
                f"Tool First     : YES  tool={tool_selection.get('tool')}  "
                f"args={tool_selection.get('arguments', {})}"
            )
            self._execute_direct_command(goal_text, selection=tool_selection)
            self._append_conversation_turn("assistant", "Direct command handled.")
            _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
            _logger.info("TRACE " + "=" * 50)
            return True

        if self.executive.can_handle(goal_text):
            _logger.info(f"Router: Activating ExecutiveAgent for: '{goal_text[:80]}'")
            self._set_conversation_state(ConversationState.EXECUTING)
            outcome = self.executive.execute(goal_text)
            response = ExecutiveBehavior.sanitize_for_user(outcome.message)
            self._speak(response)
            self._append_conversation_turn("assistant", response)
            self._set_conversation_state(ConversationState.CONVERSING)
            _logger.info(
                "ExecutiveAgent: success=%s actions=%d artifacts=%d",
                outcome.ok,
                len(outcome.actions),
                len(outcome.artifacts),
            )
            _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
            _logger.info("TRACE " + "=" * 50)
            return True

        t0 = time.perf_counter()
        classification = self.llm.classify_interaction(
            user_text=goal_text,
            recent_context=self._recent_conversation_context(),
        )
        interaction_type = classification.get("interaction_type", "discussion")
        _logger.info(
            f"TRACE  Intent Routing     : {(time.perf_counter() - t0) * 1000:.1f}ms  "
            f"→ type='{interaction_type}'  "
            f"method='{classification.get('classification_method', '?')}'  "
            f"reason='{classification.get('reason', '')}'"
        )
        _logger.info(
            f"Router: interaction_type='{interaction_type}' "
            f"requires_planning={classification.get('requires_planning')} "
            f"requires_execution={classification.get('requires_execution')} "
            f"— reason: {classification.get('reason', '')}"
        )

        if interaction_type == "goal_request":
            _logger.info(f"Router: Activating planning pipeline for goal: '{goal_text[:80]}'")
            self._execute_goal_pipeline(goal_text)
            self._append_conversation_turn("assistant", "Execution pipeline completed or progressed.")
            _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
            _logger.info("TRACE " + "=" * 50)
            return True

        if interaction_type == "direct_system_command":
            _logger.info(f"Router: Activating direct command execution for: '{goal_text[:80]}'")
            self._execute_direct_command(goal_text)
            self._append_conversation_turn("assistant", "Direct command handled.")
            _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
            _logger.info("TRACE " + "=" * 50)
            return True

        _logger.info(f"Router: Handling as conversation ({interaction_type}).")
        self._set_conversation_state(ConversationState.CONVERSING)
        self._handle_conversation(goal_text, interaction_type)
        _logger.info(f"TRACE  Total              : {(time.perf_counter() - req_start) * 1000:.1f}ms")
        _logger.info("TRACE " + "=" * 50)
        return True

    def run(self) -> None:
        try:
            if self.settings.demo_mode and not self._first_run_completed:
                intro = (
                    f"Hello. I'm AURA, a local AI executive assistant built by {self.settings.creator_name}. "
                    "I run entirely on this machine with no cloud dependencies. "
                    "You can ask me to open apps, build projects, or just chat. "
                    "To see what I can do, say 'show capabilities'."
                )
                self._speak(intro)
                self._append_conversation_turn("assistant", intro)
                self._first_run_completed = True
            else:
                self._speak("AURA is online. I am here.")

            while True:
                spoken = self.listen_once()
                should_continue = self.handle_spoken_text(spoken, require_wake_word=True)
                if not should_continue:
                    break
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.tts.shutdown()

    def available_conversation_models(self) -> list[str]:
        """Return installed Ollama models suitable for the GUI selector."""
        installed = self.llm.available_conversation_models()
        preferred = {
            self.settings.ollama_primary_model,
            self.settings.ollama_fallback_model,
        }
        return sorted(
            model
            for model in installed
            if model in preferred or model.startswith(("qwen", "llama", "mistral", "phi"))
        )

    def switch_conversation_model(self, model: str) -> str:
        """Switch models while preserving the rest of the running supervisor."""
        selected = model.strip()
        installed = self.available_conversation_models()
        normalized = {name.removesuffix(":latest"): name for name in installed}
        resolved = normalized.get(selected.removesuffix(":latest"))
        if resolved is None:
            raise ValueError(
                f"Model '{selected}' is not installed. Run: ollama pull {selected}"
            )
        active = self.llm.switch_conversation_model(resolved)
        _logger.info("Runtime model selection changed to %s", active)
        return active


def _friendly_app_name(app: str) -> str:
    key = app.strip().lower().replace(" ", "")
    names = {
        "chrome": "Chrome",
        "googlechrome": "Chrome",
        "edge": "Edge",
        "microsoftedge": "Edge",
        "firefox": "Firefox",
        "vscode": "VS Code",
        "visualstudiocode": "VS Code",
        "notepad": "Notepad",
        "calculator": "Calculator",
        "calc": "Calculator",
        "explorer": "Explorer",
        "fileexplorer": "Explorer",
    }
    return names.get(key, app.strip() or "that app")


def _is_shutdown_command(text: str) -> bool:
    return text.strip().lower().strip(" .!?") in {
        "exit",
        "quit",
        "shutdown",
        "shut down",
        "exit aura",
        "quit aura",
        "shutdown aura",
        "shut down aura",
    }


def _extract_wake_request(spoken: str, wake_word: str) -> str | None:
    match = re.search(rf"\b{re.escape(wake_word.lower())}\b", spoken.lower())
    if match is None:
        return None
    return spoken[match.end():].strip(" ,:.-")


def _friendly_url_name(url: str) -> str:
    lowered = url.strip().lower()
    if "youtube" in lowered:
        return "YouTube"
    if "google" in lowered:
        return "Google"
    if "github" in lowered:
        return "GitHub"
    return url.strip() or "that site"
