from __future__ import annotations

import glob
import json
import tempfile
import time
from pathlib import Path

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.app.config import Settings
from aura.legacy.assistant.executive_agent import AssumptionEngine, ExecutiveAgent, ExecutionVerifier
from aura.legacy.assistant.llm import LLMService
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest
from aura.legacy.assistant.planner import PlannerAgent
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer
from aura.infrastructure.voice.tts import TTSService
from aura.infrastructure.voice.xtts_backend import XTTSBackend

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "logs" / "xtts_live_results.json"


def build_tts(settings: Settings) -> TTSService:
    return TTSService(
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


def main() -> None:
    settings = Settings()
    results: list[dict[str, object]] = []
    before_temp = set(glob.glob(str(Path(tempfile.gettempdir()) / "aura_xtts_*.wav")))

    startup = time.perf_counter()
    voice = build_tts(settings)
    startup_ms = (time.perf_counter() - startup) * 1000
    ready = voice.wait_until_xtts_ready(timeout=120)
    results.append(
        {
            "test": "startup_warmup",
            "passed": ready and startup_ms < 20_000,
            "startup_return_ms": round(startup_ms, 1),
            "diagnostics": voice.get_diagnostics(),
        }
    )

    started = time.perf_counter()
    voice.speak("Hello.")
    results.append(
        {
            "test": "hello_playback",
            "passed": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "diagnostics": voice.get_diagnostics(),
        }
    )

    executor = ExecutionAgent()
    voice.speak("Opening Visual Studio Code.")
    app_result = executor.run(ActionRequest(action="open_app", args={"app_name": "vscode"}))
    voice.speak("Visual Studio Code is open." if app_result.ok else app_result.message)
    results.append(
        {
            "test": "open_vscode",
            "passed": app_result.ok,
            "actual": app_result.message,
        }
    )

    llm = LLMService()
    executive = ExecutiveAgent(
        planner=PlannerAgent(llm),
        executor=executor,
        verifier=ExecutionVerifier(),
        assumption_engine=AssumptionEngine(ROOT),
        memory=MemoryStore(ROOT / "memory"),
        safety=SafetyLayer(),
        workspace_root=ROOT,
        result_revealer=ResultRevealer(enabled=True),
    )
    project = executive.execute("Build me a snake game.")
    voice.speak(project.message)
    snake_root = ROOT / "Code" / "SnakeGame"
    required = [
        snake_root / "main.py",
        snake_root / "requirements.txt",
        snake_root / "README.md",
        snake_root / "assets",
    ]
    results.append(
        {
            "test": "build_snake_game",
            "passed": project.ok and all(path.exists() for path in required),
            "actual": project.message,
            "artifacts": [str(path) for path in required],
        }
    )

    backend = voice.xtts
    if backend is None:
        results.append({"test": "queue_stress", "passed": False, "actual": "XTTS unavailable"})
    else:
        phrases = [f"Queue response {index}." for index in range(1, 11)]
        started = time.perf_counter()
        jobs = [backend._queue.submit(text, wait=False) for text in phrases]
        for job in jobs:
            job.completed.wait(timeout=120)
        queue_ok = all(job.completed.is_set() and job.error is None for job in jobs)
        results.append(
            {
                "test": "queue_stress",
                "passed": queue_ok,
                "count": len(jobs),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "queue_wait_ms": backend.get_diagnostics()["queue_wait_ms"],
            }
        )

    voice.shutdown()

    cpu = XTTSBackend(
        device="cpu",
        voice_reference=settings.voice_reference,
        cache_dir=settings.tts_cache_dir,
    )
    cpu_started = time.perf_counter()
    cpu_output = None
    try:
        cpu.initialize()
        cpu_output = cpu.speak_to_file("CPU fallback works.")
        results.append(
            {
                "test": "cpu_fallback",
                "passed": cpu.device == "cpu" and cpu_output.is_file(),
                "elapsed_ms": round((time.perf_counter() - cpu_started) * 1000, 1),
                "diagnostics": cpu.get_diagnostics(),
            }
        )
    except Exception as exc:
        results.append(
            {
                "test": "cpu_fallback",
                "passed": False,
                "actual": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        if cpu_output is not None:
            cpu_output.unlink(missing_ok=True)
        cpu.shutdown()

    after_temp = set(glob.glob(str(Path(tempfile.gettempdir()) / "aura_xtts_*.wav")))
    orphaned = sorted(after_temp - before_temp)
    results.append(
        {
            "test": "temporary_file_cleanup",
            "passed": not orphaned,
            "orphaned": orphaned,
        }
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(bool(result["passed"]) for result in results)
    print(f"XTTS LIVE: {passed}/{len(results)} passed")
    print(REPORT)
    for result in results:
        print(f"[{'PASS' if result['passed'] else 'FAIL'}] {result['test']}")


if __name__ == "__main__":
    main()
