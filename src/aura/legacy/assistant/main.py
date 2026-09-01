from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from aura.app.config import Settings, ensure_runtime_dirs
from aura.infrastructure.llm.ollama import OllamaConversationModel
from aura.app.hardware_profile import HardwareProfile, resolve_runtime_settings
from aura.legacy.assistant.orchestrator import AuraSupervisor


def _build_conversation_model(settings: Settings) -> OllamaConversationModel | None:
    """Construct the local ConversationModel from settings.

    Returns None if conversation_backend is not 'ollama' (reserved for future
    backends).  The caller handles None gracefully — OpenAI falls back.
    """
    if settings.conversation_backend != "ollama":
        logging.getLogger("aura").warning(
            f"main: conversation_backend='{settings.conversation_backend}' "
            "is not 'ollama'. Local conversation model will not be loaded."
        )
        return None
    return OllamaConversationModel(
        model=settings.ollama_conversation_model,
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_request_timeout,
        context_length=settings.ollama_context_length,
    )


def _setup_logging(settings: Settings) -> None:
    root = logging.getLogger("aura")
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)

    fmt_console = logging.Formatter("[AURA] %(levelname)-8s %(message)s")
    fmt_file = logging.Formatter("%(asctime)s [AURA] %(levelname)-8s %(message)s")
    fmt_trace = logging.Formatter("%(asctime)s  %(message)s")

    console_stream = sys.stdout
    if console_stream is not None:
        try:
            console_stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError):
            pass
        sh = logging.StreamHandler(console_stream)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt_console)
        root.addHandler(sh)

    try:
        log_path = Path(settings.log_dir) / "aura.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt_file)
        root.addHandler(fh)
    except Exception as e:
        root.warning(f"Could not open log file: {e}")

    # Dedicated conversation trace logger — every classification, LLM call,
    # fast-path hit, memory lookup, and planner activation is recorded here.
    trace_logger = logging.getLogger("aura.trace")
    trace_logger.setLevel(logging.DEBUG)
    trace_logger.propagate = False  # keep trace out of the main aura log

    if console_stream is not None:
        trace_sh = logging.StreamHandler(console_stream)
        trace_sh.setLevel(logging.INFO)
        trace_sh.setFormatter(logging.Formatter("[TRACE] %(message)s"))
        trace_logger.addHandler(trace_sh)

    try:
        trace_path = Path(settings.log_dir) / "conversation_trace.log"
        trace_fh = logging.FileHandler(trace_path, encoding="utf-8")
        trace_fh.setLevel(logging.DEBUG)
        trace_fh.setFormatter(fmt_trace)
        trace_logger.addHandler(trace_fh)
    except Exception as e:
        root.warning(f"Could not open trace log file: {e}")


def _print_capability_report(
    settings: Settings,
    supervisor: AuraSupervisor,
    hardware: HardwareProfile,
) -> None:
    logger = logging.getLogger("aura")
    openai_loaded = bool(settings.openai_api_key)
    elevenlabs_loaded = bool(settings.elevenlabs_api_key)

    stt_diag = supervisor.stt.get_diagnostics()
    stt_backend = (
        f"Faster-Whisper  model={stt_diag['model']}  "
        f"device={stt_diag['device_requested']}  "
        f"compute={stt_diag['compute_type']}"
    )
    tts_diag = supervisor.tts.get_diagnostics()
    tts_backend = str(tts_diag["backend"])
    cuda_info = (
        f"{stt_diag['cuda_device_count']} device(s) available"
        if stt_diag["cuda_available"]
        else "not available"
    )

    lines = [
        "=" * 60,
        "  AURA Capability Report",
        "=" * 60,
        f"  Hardware Profile     : {hardware.tier.upper()}",
        f"  System RAM           : {hardware.total_ram_gb:.1f} GB",
        f"  GPU                  : {hardware.gpu_name}",
        f"  GPU VRAM             : {hardware.vram_gb:.1f} GB",
        f"  Profile Decision     : {hardware.reason}",
        f"  DEMO MODE            : {'ENABLED' if settings.demo_mode else 'DISABLED'}",
        f"  Demo Workspace       : {settings.demo_workspace}",
        f"  STT Backend          : {stt_backend}",
        f"  STT Model Load Time  : {stt_diag['load_time_s']}s",
        f"  STT Avg Latency      : {stt_diag['avg_transcription_ms']}ms  (no samples yet)",
        f"  GPU / CUDA           : {cuda_info}",
        f"  OpenAI STT           : Not supported (Faster-Whisper only)",
        f"  STT Backend Switch   : Not supported",
        f"  TTS Backend          : {tts_backend}",
        f"  TTS Device           : {tts_diag['device']}",
        f"  TTS Voice            : {tts_diag['voice']}",
        f"  TTS Warmup           : {'Complete' if tts_diag['warmup'] else 'Not run'}",
        f"  TTS Fallback         : {tts_diag['fallback']}",
        "-" * 60,
        "  Conversation Brain",
        "-" * 60,
        f"  Conv Backend         : {settings.conversation_backend}",
        f"  Conv Model           : {settings.ollama_conversation_model}",
        f"  Ollama URL           : {settings.ollama_base_url}",
        f"  Context Length       : {settings.ollama_context_length}",
        f"  Streaming Enabled    : True",
        f"  Memory Enabled       : True",
        "-" * 60,
        "  Optional compatibility services",
        "-" * 60,
        f"  Planner Model        : {settings.openai_planner_model}",
        f"  Fallback Models      : {', '.join(settings.openai_fallback_models) or 'none'}",
        f"  OpenAI Key Loaded    : {openai_loaded}",
        f"  ElevenLabs Loaded    : {elevenlabs_loaded}",
        "=" * 60,
    ]
    report = "\n".join(lines)
    if sys.stdout is not None:
        print(report)
    logger.debug("Capability report logged.")

    if not openai_loaded:
        logger.info("OpenAI is disabled. Local Ollama handles LLM features.")
    if not elevenlabs_loaded:
        logger.info("ElevenLabs is disabled. Local XTTS/fallback speech is active.")


def main() -> None:
    initial_settings = Settings()
    ensure_runtime_dirs(initial_settings)
    _setup_logging(initial_settings)

    def bootstrap(
        report: Callable[[str, str], None],
    ) -> tuple[AuraSupervisor, HardwareProfile]:
        report(f"Python {sys.version.split()[0]} detected", "complete")
        report("Detecting hardware profile", "active")
        settings, hardware = resolve_runtime_settings(initial_settings)
        ensure_runtime_dirs(settings)
        report(
            f"Hardware: {hardware.tier.upper()} / {hardware.gpu_name}",
            "complete",
        )
        report(f"Selected model: {settings.ollama_conversation_model}", "active")
        conv_model = _build_conversation_model(settings)
        if conv_model is not None:
            if conv_model.is_available():
                report("Ollama connected and model warmed", "complete")
            else:
                report(
                    "Ollama model unavailable; conversation fallback active",
                    "warning",
                )
        report("Loading speech recognition", "active")
        supervisor = AuraSupervisor(
            settings,
            conversation_model=conv_model,
        )
        report("Speech recognition ready", "complete")
        if settings.tts_backend == "xtts":
            report("Warming XTTS voice", "active")
            supervisor.tts.wait_until_initialization_done(timeout=120)
            if supervisor.tts.wait_until_xtts_ready(timeout=0):
                report("XTTS voice ready", "complete")
            else:
                report("XTTS unavailable; local voice fallback active", "warning")
        tts_diag = supervisor.tts.get_diagnostics()
        report(
            f"Voice backend: {tts_diag.get('backend', settings.tts_backend)}",
            "complete",
        )
        report("Memory and tools online", "complete")
        _print_capability_report(settings, supervisor, hardware)
        return supervisor, hardware

    try:
        from aura.legacy.ui.future_gui import FutureHUDApp

        FutureHUDApp(bootstrap).run()
    except Exception as e:
        logging.getLogger("aura").exception(
            f"Future HUD unavailable, falling back to classic GUI: {e}"
        )
        supervisor, _hardware = bootstrap(
            lambda label, status: logging.getLogger("aura").info(
                "Startup [%s]: %s", status, label
            )
        )
        try:
            from aura.legacy.ui.gui import AuraAppUI

            AuraAppUI(supervisor).run()
        except Exception as classic_error:
            logging.getLogger("aura").exception(
                f"Classic GUI unavailable, falling back to voice loop: {classic_error}"
            )
            supervisor.run()


if __name__ == "__main__":
    main()
