from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

if TYPE_CHECKING:
    from aura.app.hardware_profile import HardwareProfile
    from aura.legacy.assistant.orchestrator import AuraSupervisor


_logger = logging.getLogger("aura")


class AuraBridge(QObject):
    """Thread-safe QML adapter over the existing AURA supervisor."""

    stateChanged = Signal()
    statusChanged = Signal()
    transcriptChanged = Signal()
    audioLevelChanged = Signal()
    executionEntriesChanged = Signal()
    projectEntriesChanged = Signal()
    transcriptEntriesChanged = Signal()
    systemStatusChanged = Signal()
    startupEntriesChanged = Signal()
    startupReadyChanged = Signal()
    modelOptionsChanged = Signal()
    currentModelChanged = Signal()
    _requestCompleted = Signal(str, bool)
    _requestFailed = Signal(str)
    _uiEvent = Signal(str, object)
    _startupEvent = Signal(str, str)
    _startupCompleted = Signal(object, object)
    _startupFailed = Signal(str)
    _modelChanged = Signal(str)
    _modelChangeFailed = Signal(str)
    _systemStatusLoaded = Signal(object)
    _modelOptionsLoaded = Signal(object, str)

    def __init__(self, supervisor: Optional["AuraSupervisor"] = None) -> None:
        super().__init__()
        self.supervisor = supervisor
        self._state = "STARTING" if supervisor is None else "IDLE"
        self._status = "Initializing" if supervisor is None else "Ready"
        self._transcript = "AURA is starting." if supervisor is None else "AURA is standing by."
        self._audio_level = 0.0
        self._execution_entries: list[dict[str, str]] = []
        self._project_entries: list[dict[str, str]] = []
        self._transcript_entries: list[dict[str, str]] = []
        self._system_status: list[dict[str, str]] = []
        self._startup_entries: list[dict[str, str]] = []
        self._startup_ready = supervisor is not None
        self._model_options: list[str] = []
        self._current_model = ""
        self._busy = False
        self._refresh_tick = 0
        self._system_status_loading = False
        self._model_options_loading = False
        self._requestCompleted.connect(self._finish_request)
        self._requestFailed.connect(self._fail_request)
        self._uiEvent.connect(self._handle_ui_event)
        self._startupEvent.connect(self._apply_startup_event)
        self._startupCompleted.connect(self._attach_supervisor)
        self._startupFailed.connect(self._fail_startup)
        self._modelChanged.connect(self._finish_model_change)
        self._modelChangeFailed.connect(self._fail_model_change)
        self._systemStatusLoaded.connect(self._apply_system_status)
        self._modelOptionsLoaded.connect(self._apply_model_options)
        if supervisor is not None:
            self._connect_supervisor(supervisor)

        self._state_timer = QTimer(self)
        self._state_timer.setInterval(150)
        self._state_timer.timeout.connect(self._sync_supervisor_state)
        self._state_timer.start()
        if supervisor is not None:
            self._refresh_system_status()
            self._refresh_model_options()

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=transcriptChanged)
    def transcript(self) -> str:
        return self._transcript

    @Property(float, notify=audioLevelChanged)
    def audioLevel(self) -> float:
        return self._audio_level

    @Property("QVariantList", notify=executionEntriesChanged)
    def executionEntries(self) -> list[dict[str, str]]:
        return self._execution_entries

    @Property("QVariantList", notify=projectEntriesChanged)
    def projectEntries(self) -> list[dict[str, str]]:
        return self._project_entries

    @Property("QVariantList", notify=transcriptEntriesChanged)
    def transcriptEntries(self) -> list[dict[str, str]]:
        return self._transcript_entries

    @Property("QVariantList", notify=systemStatusChanged)
    def systemStatus(self) -> list[dict[str, str]]:
        return self._system_status

    @Property("QVariantList", notify=startupEntriesChanged)
    def startupEntries(self) -> list[dict[str, str]]:
        return self._startup_entries

    @Property(bool, notify=startupReadyChanged)
    def startupReady(self) -> bool:
        return self._startup_ready

    @Property("QStringList", notify=modelOptionsChanged)
    def modelOptions(self) -> list[str]:
        return self._model_options

    @Property(str, notify=currentModelChanged)
    def currentModel(self) -> str:
        return self._current_model

    @Slot()
    def listen(self) -> None:
        if self._busy or self.supervisor is None:
            return
        self._busy = True
        self._set_state("LISTENING")
        self._set_status("Listening")
        threading.Thread(
            target=self._capture_and_process,
            daemon=True,
            name="aura-hud-listen",
        ).start()

    @Slot(str)
    def submitText(self, text: str) -> None:
        command = text.strip()
        if self._busy or self.supervisor is None or not command:
            return
        self._busy = True
        self._transcript = f"You: {command}"
        self.transcriptChanged.emit()
        self._set_state("THINKING")
        self._set_status("Processing")
        threading.Thread(
            target=self._process_text,
            args=(command,),
            daemon=True,
            name="aura-hud-command",
        ).start()

    @Slot(str)
    def selectModel(self, model: str) -> None:
        selected = model.strip()
        if self._busy or self.supervisor is None or not selected:
            return
        if selected == self._current_model:
            return
        self._busy = True
        self._set_status(f"Loading {selected}")

        def worker() -> None:
            try:
                active = self.supervisor.switch_conversation_model(selected)
                self._modelChanged.emit(active)
            except Exception as exc:
                self._modelChangeFailed.emit(str(exc))

        threading.Thread(
            target=worker,
            daemon=True,
            name="aura-model-switch",
        ).start()

    def report_startup(self, label: str, status: str = "complete") -> None:
        self._startupEvent.emit(label, status)

    def _capture_and_process(self) -> None:
        try:
            spoken = self.supervisor.listen_once(level_callback=self._set_audio_level)
            if not spoken.strip():
                self._requestFailed.emit("No clear speech detected.")
                return
            self._transcript = f"You: {spoken.strip()}"
            self.transcriptChanged.emit()
            self._set_state("THINKING")
            self._process_text(spoken)
        except Exception as exc:
            self._requestFailed.emit(str(exc))

    def _process_text(self, text: str) -> None:
        try:
            should_continue = self.supervisor.handle_spoken_text(
                text,
                require_wake_word=False,
            )
            self._requestCompleted.emit(text, should_continue)
        except Exception as exc:
            self._requestFailed.emit(str(exc))

    @Slot(str, bool)
    def _finish_request(self, text: str, should_continue: bool) -> None:
        self._busy = False
        self._set_audio_level(0.0)
        self._set_state("IDLE")
        self._set_status("Ready" if should_continue else "Shutting down")
        if should_continue:
            self._transcript = f"AURA completed: {text}"
            self.transcriptChanged.emit()

    @Slot(str)
    def _fail_request(self, message: str) -> None:
        self._busy = False
        self._set_audio_level(0.0)
        self._set_state("IDLE")
        self._set_status(message)

    def _sync_supervisor_state(self) -> None:
        if self.supervisor is None:
            return
        self._refresh_tick += 1
        if self._refresh_tick % 10 == 0:
            self._refresh_execution_feed()
            self._refresh_projects()
            self._refresh_transcript()
        if self._busy and self._state in {"LISTENING", "THINKING"}:
            return
        state = self.supervisor.conversation_state.value.upper()
        mapped = {
            "CONVERSING": "THINKING",
            "PLANNING": "THINKING",
            "EXECUTING": "EXECUTING",
        }.get(state, "IDLE")
        self._set_state(mapped)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.stateChanged.emit()

    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.statusChanged.emit()

    def _set_audio_level(self, level: float) -> None:
        normalized = min(1.0, max(0.0, float(level) * 18.0))
        if abs(normalized - self._audio_level) > 0.01:
            self._audio_level = normalized
            self.audioLevelChanged.emit()

    def _refresh_execution_feed(self) -> None:
        if self.supervisor is None:
            return
        try:
            rows = self.supervisor.memory.read_recent_logs(limit=12)
        except (AttributeError, OSError, ValueError):
            return

        entries: list[dict[str, str]] = []
        for row in rows:
            timestamp = str(row.get("timestamp", ""))
            clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
            result = row.get("result", {})
            message = (
                str(result.get("message", "")).strip()
                if isinstance(result, dict)
                else ""
            )
            if not message:
                message = str(row.get("command", row.get("goal", "Action completed")))
            entries.append({"time": clock, "message": message[:96]})

        if entries != self._execution_entries:
            self._execution_entries = entries
            self.executionEntriesChanged.emit()

    def _refresh_projects(self) -> None:
        if self.supervisor is None:
            return
        try:
            projects = self.supervisor.memory.get_projects()
        except (AttributeError, OSError, ValueError):
            return

        entries: list[dict[str, str]] = []
        for key, project in list(projects.items())[-6:]:
            world_state = (
                project.get("world_state", {})
                if isinstance(project, dict)
                else {}
            )
            completed = len(world_state.get("completed_tasks", []))
            pending = len(world_state.get("pending_tasks", []))
            status = (
                f"{completed} complete / {pending} pending"
                if completed or pending
                else "Available"
            )
            entries.append(
                {
                    "name": str(key).replace("_", " ").title(),
                    "status": status,
                }
            )

        if entries != self._project_entries:
            self._project_entries = entries
            self.projectEntriesChanged.emit()

    def _refresh_transcript(self) -> None:
        if self.supervisor is None:
            return
        try:
            turns = self.supervisor.working_memory.recent(n=12)
        except AttributeError:
            return
        entries = [
            {
                "role": str(turn.get("role", "assistant")),
                "message": str(turn.get("content", "")),
            }
            for turn in turns
            if str(turn.get("content", "")).strip()
        ]
        if entries != self._transcript_entries:
            self._transcript_entries = entries
            self.transcriptEntriesChanged.emit()

    def _refresh_system_status(self) -> None:
        if self.supervisor is None or self._system_status_loading:
            return
        self._system_status_loading = True
        threading.Thread(
            target=self._load_system_status,
            daemon=True,
            name="aura-status-refresh",
        ).start()

    def _load_system_status(self) -> None:
        if self.supervisor is None:
            return
        statuses: list[dict[str, str]] = []
        try:
            stt = self.supervisor.stt.get_diagnostics()
            gpu = (
                "CUDA"
                if stt.get("cuda_available")
                else str(stt.get("device_requested", "CPU")).upper()
            )
            statuses.append({"name": "GPU", "value": gpu, "ok": "true"})
        except (AttributeError, RuntimeError):
            statuses.append({"name": "GPU", "value": "CPU", "ok": "true"})

        statuses.extend(
            [
                {"name": "BRAIN", "value": "READY", "ok": "true"},
                {"name": "VOICE", "value": "READY", "ok": "true"},
                {"name": "MEMORY", "value": "ACTIVE", "ok": "true"},
                {"name": "TOOLS", "value": "ONLINE", "ok": "true"},
                {"name": "AGENT", "value": "EXECUTIVE", "ok": "true"},
            ]
        )
        self._systemStatusLoaded.emit(statuses)

    @Slot(object)
    def _apply_system_status(self, statuses: object) -> None:
        self._system_status_loading = False
        self._system_status = list(statuses) if isinstance(statuses, list) else []
        self.systemStatusChanged.emit()

    def _connect_supervisor(self, supervisor: "AuraSupervisor") -> None:
        if hasattr(supervisor, "add_ui_listener"):
            supervisor.add_ui_listener(self._relay_ui_event)
        if hasattr(supervisor, "tts"):
            supervisor.tts.set_amplitude_callback(self._set_audio_level)

    @Slot(str, str)
    def _apply_startup_event(self, label: str, status: str) -> None:
        if self._startup_entries and self._startup_entries[-1]["status"] == "active":
            self._startup_entries[-1] = {
                **self._startup_entries[-1],
                "status": "complete",
            }
        self._startup_entries = [
            *self._startup_entries,
            {"label": label, "status": status},
        ]
        self._status = label
        self.startupEntriesChanged.emit()
        self.statusChanged.emit()

    @Slot(object, object)
    def _attach_supervisor(
        self,
        supervisor: "AuraSupervisor",
        hardware: "HardwareProfile",
    ) -> None:
        self.supervisor = supervisor
        self._connect_supervisor(supervisor)
        self._refresh_system_status()
        self._refresh_model_options()
        self._startup_entries = [
            *[
                {**entry, "status": "complete"}
                for entry in self._startup_entries
            ],
            {"label": "Ready.", "status": "complete"},
        ]
        self.startupEntriesChanged.emit()
        self._startup_ready = True
        self.startupReadyChanged.emit()
        self._set_state("IDLE")
        self._set_status("Ready")
        self._transcript = "AURA is standing by."
        self.transcriptChanged.emit()

    @Slot(str)
    def _fail_startup(self, message: str) -> None:
        self._startup_entries = [
            *self._startup_entries,
            {"label": message, "status": "error"},
        ]
        self.startupEntriesChanged.emit()
        self._set_state("ERROR")
        self._set_status("Startup failed")

    def _refresh_model_options(self) -> None:
        if self.supervisor is None or self._model_options_loading:
            return
        self._model_options_loading = True
        threading.Thread(
            target=self._load_model_options,
            daemon=True,
            name="aura-model-options",
        ).start()

    def _load_model_options(self) -> None:
        if self.supervisor is None:
            return
        try:
            options = self.supervisor.available_conversation_models()
        except Exception as exc:
            _logger.warning("Could not load model options: %s", exc)
            options = []
        current = str(
            getattr(
                getattr(self.supervisor.llm, "_conv_model", None),
                "model_name",
                "",
            )
        )
        if current and current not in options:
            options.insert(0, current)
        self._modelOptionsLoaded.emit(options, current)

    @Slot(object, str)
    def _apply_model_options(self, options: object, current: str) -> None:
        self._model_options_loading = False
        self._model_options = list(options) if isinstance(options, list) else []
        self._current_model = current
        self.modelOptionsChanged.emit()
        self.currentModelChanged.emit()

    @Slot(str)
    def _finish_model_change(self, model: str) -> None:
        self._busy = False
        self._current_model = model
        self.currentModelChanged.emit()
        self._refresh_system_status()
        self._set_status("Reasoning engine changed.")

    @Slot(str)
    def _fail_model_change(self, message: str) -> None:
        self._busy = False
        self._set_status(message)

    def _relay_ui_event(self, event: str, payload: object) -> None:
        self._uiEvent.emit(event, payload)

    @Slot(str, object)
    def _handle_ui_event(self, event: str, payload: object) -> None:
        if event == "state":
            state = str(payload).upper()
            self._set_state(
                "THINKING" if state in {"CONVERSING", "PLANNING"} else state
            )
        elif event == "status":
            self._set_status(str(payload))
        elif event == "speech_started":
            self._set_state("SPEAKING")
            self._set_status("Speaking")
        elif event == "speech_finished":
            self._set_audio_level(0.0)
            self._set_state("IDLE")
            self._set_status("Ready")


class FutureHUDApp:
    def __init__(
        self,
        bootstrap: Callable[
            [Callable[[str, str], None]],
            tuple["AuraSupervisor", "HardwareProfile"],
        ],
    ) -> None:
        os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        self.supervisor: Optional["AuraSupervisor"] = None
        self.bootstrap = bootstrap
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.app.setApplicationName("AURA")
        self.app.setOrganizationName("AURA")
        self.app.setFont(QFont("Segoe UI", 10))
        icon_path = Path(__file__).resolve().parents[4] / "assets" / "icons" / "aura.ico"
        if icon_path.is_file():
            self.app.setWindowIcon(QIcon(str(icon_path)))

        self.bridge = AuraBridge()
        self.engine = QQmlApplicationEngine()
        self.engine.warnings.connect(self._log_qml_warnings)
        self.engine.rootContext().setContextProperty("auraBridge", self.bridge)
        qml_path = Path(__file__).resolve().parent / "qml" / "FutureHUD.qml"
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        if not self.engine.rootObjects():
            raise RuntimeError(f"Could not load AURA HUD: {qml_path}")
        QTimer.singleShot(0, self._start_bootstrap)
        self.app.aboutToQuit.connect(self._shutdown)
        self.app.aboutToQuit.connect(self._detach_bridge)

    def run(self) -> None:
        exit_code = self.app.exec()
        if exit_code:
            _logger.warning("AURA HUD exited with code %s", exit_code)

    def _detach_bridge(self) -> None:
        if self.supervisor is not None and hasattr(self.supervisor, "remove_ui_listener"):
            self.supervisor.remove_ui_listener(self.bridge._relay_ui_event)

    def _start_bootstrap(self) -> None:
        def worker() -> None:
            try:
                supervisor, hardware = self.bootstrap(self.bridge.report_startup)
                self.supervisor = supervisor
                self.bridge._startupCompleted.emit(supervisor, hardware)
            except Exception as exc:
                _logger.exception("AURA startup failed: %s", exc)
                self.bridge._startupFailed.emit(str(exc))

        threading.Thread(
            target=worker,
            daemon=True,
            name="aura-bootstrap",
        ).start()

    def _shutdown(self) -> None:
        if self.supervisor is not None:
            self.supervisor.shutdown()

    @staticmethod
    def _log_qml_warnings(warnings: list[object]) -> None:
        for warning in warnings:
            _logger.error("QML: %s", warning)
