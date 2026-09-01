from __future__ import annotations

import os
import hashlib
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)


def aura_data_dir() -> Path:
    override = os.getenv("AURA_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "AURA"
    if os.getenv("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]).expanduser() / "aura"
    return Path.home() / ".local" / "share" / "aura"


def _repository_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").is_file() else None


# The example file is documentation, not runtime configuration.
load_dotenv(dotenv_path=".env", override=False)


@dataclass(frozen=True)
class Settings:
    """AURA configuration; the Workspace Planner may use managed Vertex AI."""

    creator_name: str = os.getenv("AURA_CREATOR_NAME", "Sooraj").strip() or "Sooraj"

    # Primary Engineering Workspace server and structured Planner.
    workspace_host: str = os.getenv("AURA_WORKSPACE_HOST", "127.0.0.1").strip()
    workspace_port: int = int(os.getenv("AURA_WORKSPACE_PORT", "8765"))
    workspace_storage_mode: str = os.getenv("AURA_WORKSPACE_STORAGE_MODE", "sqlite").strip().lower()
    workspace_db_path: Path = Path(os.getenv("AURA_WORKSPACE_DB_PATH", str(aura_data_dir() / "workspace" / "aura.db")))
    workspace_artifact_dir: Path = Path(os.getenv("AURA_WORKSPACE_ARTIFACT_DIR", str(aura_data_dir() / "workspace" / "artifacts")))
    artifact_storage_mode: str = os.getenv("AURA_ARTIFACT_STORAGE_MODE", "local").strip().lower()
    gcs_bucket: str = os.getenv("AURA_GCS_BUCKET", "").strip()
    database_url: str = os.getenv("AURA_DATABASE_URL", "").strip()
    db_host: str = os.getenv("AURA_DB_HOST", "").strip()
    db_port: int = int(os.getenv("AURA_DB_PORT", "5432"))
    db_name: str = os.getenv("AURA_DB_NAME", "aura").strip()
    db_user: str = os.getenv("AURA_DB_USER", "aura").strip()
    db_password: str = os.getenv("AURA_DB_PASSWORD", "")
    db_pool_size: int = int(os.getenv("AURA_DB_POOL_SIZE", "3"))
    db_max_overflow: int = int(os.getenv("AURA_DB_MAX_OVERFLOW", "1"))
    db_pool_timeout: float = float(os.getenv("AURA_DB_POOL_TIMEOUT", "5"))
    cloud_mode: bool = os.getenv("AURA_CLOUD_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
    planner_provider: str = os.getenv("AURA_LLM_PROVIDER",os.getenv("AURA_PLANNER_PROVIDER","vertex")).strip().lower()
    planner_model: str = os.getenv("AURA_PLANNER_MODEL", "").strip()
    planner_timeout: float = float(os.getenv("AURA_PLANNER_TIMEOUT", "20"))
    circuit_timeout: float = float(os.getenv("AURA_CIRCUIT_TIMEOUT", "20"))
    cad_timeout: float = float(os.getenv("AURA_CAD_TIMEOUT", "10"))
    artifact_timeout: float = float(os.getenv("AURA_ARTIFACT_TIMEOUT", "10"))
    websocket_reconnect_attempts: int = int(os.getenv("AURA_WEBSOCKET_RECONNECT_ATTEMPTS", "6"))
    gcp_project:str=os.getenv("AURA_GCP_PROJECT",os.getenv("GOOGLE_CLOUD_PROJECT","")).strip()
    gcp_location:str=os.getenv("AURA_GCP_LOCATION","global").strip()
    vertex_model:str=os.getenv("AURA_VERTEX_MODEL","gemini-3.1-flash-lite").strip()
    vertex_timeout:float=float(os.getenv("AURA_VERTEX_TIMEOUT_SECONDS","20"))
    deterministic_fallback: bool = os.getenv(
        "AURA_DETERMINISTIC_FALLBACK", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Local TTS (XTTS-v2 with pyttsx3 and Windows Speech fallbacks)
    voice_persona: str = os.getenv(
        "AURA_VOICE_PERSONA",
        "Warm, confident, emotionally aware executive copilot voice.",
    )
    tts_backend: str = os.getenv("AURA_TTS_BACKEND", "auto").strip().lower()
    voice_reference: Path = Path(
        os.getenv("AURA_VOICE_REFERENCE", str(aura_data_dir() / "voices" / "aura_voice.wav"))
    )
    tts_device: str = os.getenv("AURA_TTS_DEVICE", "cuda").strip().lower()
    tts_cache_dir: Path = Path(os.getenv("AURA_TTS_CACHE_DIR", str(aura_data_dir() / "models" / "xtts")))
    auto_warmup: bool = os.getenv("AURA_AUTO_WARMUP", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    local_tts_rate: int = int(os.getenv("AURA_LOCAL_TTS_RATE", "165"))
    local_tts_voice_index: int = int(os.getenv("AURA_LOCAL_TTS_VOICE_INDEX", "0"))
    max_research_results: int = int(os.getenv("AURA_MAX_RESEARCH_RESULTS", "8"))
    max_execution_steps: int = int(os.getenv("AURA_MAX_EXECUTION_STEPS", "16"))
    auto_reveal_results: bool = os.getenv(
        "AUTO_REVEAL_RESULTS", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}

    # Compatibility fields retained for existing planner, startup, and TTS APIs.
    # Empty defaults keep the normal runtime fully local.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_planner_model: str = os.getenv(
        "OPENAI_PLANNER_MODEL", os.getenv("OPENAI_MODEL", "")
    )
    openai_conversation_model: str = os.getenv(
        "OPENAI_CONVERSATION_MODEL", os.getenv("OPENAI_MODEL", "")
    )
    openai_fallback_models: tuple[str, ...] = tuple(
        model.strip()
        for model in os.getenv("OPENAI_FALLBACK_MODELS", "").split(",")
        if model.strip()
    )
    openai_planner_temperature: float = float(
        os.getenv("OPENAI_PLANNER_TEMPERATURE", "0.2")
    )
    openai_conversation_temperature: float = float(
        os.getenv("OPENAI_CONVERSATION_TEMPERATURE", "0.6")
    )

    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "")
    elevenlabs_model_id: str = os.getenv(
        "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"
    )
    elevenlabs_stability: float = float(os.getenv("ELEVENLABS_STABILITY", "0.22"))
    elevenlabs_similarity_boost: float = float(
        os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.88")
    )
    elevenlabs_style: float = float(os.getenv("ELEVENLABS_STYLE", "0.7"))
    elevenlabs_speaker_boost: bool = os.getenv(
        "ELEVENLABS_SPEAKER_BOOST", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    elevenlabs_clarity: float = float(os.getenv("ELEVENLABS_CLARITY", "0.75"))
    elevenlabs_naturalness: float = float(
        os.getenv("ELEVENLABS_NATURALNESS", "0.90")
    )

    # ------------------------------------------------------------------
    # Legacy compatibility assistant conversation brain (Ollama).
    # ------------------------------------------------------------------
    conversation_backend: str = os.getenv("AURA_CONVERSATION_BACKEND", "ollama")
    ollama_base_url: str = os.getenv("AURA_OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_conversation_model: str = os.getenv("AURA_OLLAMA_MODEL", "auto").strip()
    ollama_primary_model: str = os.getenv(
        "AURA_OLLAMA_PRIMARY_MODEL", "qwen3:8b"
    ).strip()
    ollama_fallback_model: str = os.getenv(
        "AURA_OLLAMA_FALLBACK_MODEL", "qwen2.5:3b"
    ).strip()
    ollama_request_timeout: int = int(os.getenv("AURA_OLLAMA_TIMEOUT", "120"))
    ollama_context_length: int = int(os.getenv("AURA_OLLAMA_CONTEXT_LENGTH", "8192"))

    hardware_profile: str = os.getenv(
        "AURA_HARDWARE_PROFILE", "auto"
    ).strip().lower()
    performance_min_ram_gb: float = float(
        os.getenv("AURA_PERFORMANCE_MIN_RAM_GB", "12")
    )
    performance_min_vram_gb: float = float(
        os.getenv("AURA_PERFORMANCE_MIN_VRAM_GB", "6")
    )
    xtts_min_vram_gb: float = float(
        os.getenv("AURA_XTTS_MIN_VRAM_GB", "3.5")
    )

    stt_model: str = os.getenv("AURA_STT_MODEL", "small")
    stt_device: str = os.getenv("AURA_STT_DEVICE", "cpu")
    stt_compute_type: str = os.getenv("AURA_STT_COMPUTE_TYPE", "int8")

    sample_rate: int = int(os.getenv("AURA_SAMPLE_RATE", "16000"))
    max_record_seconds: int = int(os.getenv("AURA_MAX_RECORD_SECONDS", "12"))
    silence_threshold: float = float(os.getenv("AURA_SILENCE_THRESHOLD", "0.01"))
    silence_hold_seconds: float = float(os.getenv("AURA_SILENCE_HOLD_SECONDS", "1.2"))

    memory_dir: Path = Path(os.getenv("AURA_MEMORY_DIR", str(aura_data_dir() / "memory")))
    log_dir: Path = Path(os.getenv("AURA_LOG_DIR", str(aura_data_dir() / "logs")))

    confirm_words: tuple[str, ...] = tuple(
        w.strip().lower()
        for w in os.getenv("AURA_CONFIRM_WORDS", "yes,confirm,proceed").split(",")
        if w.strip()
    )
    reject_words: tuple[str, ...] = tuple(
        w.strip().lower()
        for w in os.getenv("AURA_REJECT_WORDS", "no,stop,cancel").split(",")
        if w.strip()
    )

    wake_word: str = os.getenv("AURA_WAKE_WORD", "aura").strip().lower()

    demo_mode: bool = os.getenv("AURA_DEMO_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    demo_workspace: Path = Path(os.getenv("AURA_DEMO_WORKSPACE", str(aura_data_dir() / "DemoWorkspace")))


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    if settings.demo_mode:
        settings.demo_workspace.mkdir(parents=True, exist_ok=True)


def migrate_legacy_workspace_data(settings: Settings) -> str:
    """Safely migrate the old repository-local Workspace store once."""
    root = _repository_root()
    if root is None or os.getenv("AURA_WORKSPACE_DB_PATH") or os.getenv("AURA_WORKSPACE_ARTIFACT_DIR"):
        return "not-applicable"
    legacy = root / "runtime" / "workspace"
    legacy_db = legacy / "aura.db"
    if not legacy_db.is_file():
        return "not-found"
    target_db = settings.workspace_db_path.resolve()
    target_artifacts = settings.workspace_artifact_dir.resolve()
    target_root = target_db.parent
    if target_artifacts.parent != target_root:
        LOGGER.warning("Legacy Workspace data retained because default targets do not share a directory")
        return "target-conflict"
    staging = target_root.with_name(f"{target_root.name}.migration")
    if target_root.exists() or staging.exists():
        LOGGER.warning("Legacy Workspace data retained because target storage already exists: %s", target_db.parent)
        return "target-conflict"
    staging.mkdir(parents=True)
    staged_db = staging / target_db.name
    staged_artifacts = staging / target_artifacts.name
    legacy_artifacts = legacy / "artifacts"
    try:
        shutil.copy2(legacy_db, staged_db)
        if legacy_artifacts.is_dir():
            shutil.copytree(legacy_artifacts, staged_artifacts)
        connection = sqlite3.connect(staged_db)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Migrated Workspace database failed SQLite integrity verification")
        finally:
            connection.close()
        for source in legacy_artifacts.rglob("*") if legacy_artifacts.is_dir() else ():
            if source.is_file():
                destination = staged_artifacts / source.relative_to(legacy_artifacts)
                if not destination.is_file() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
                    raise RuntimeError(f"Migrated artifact verification failed: {source}")
        staging.rename(target_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(legacy)
    runtime_root = root / "runtime"
    if runtime_root.is_dir() and not any(runtime_root.iterdir()):
        runtime_root.rmdir()
    LOGGER.info("Migrated Workspace data from %s to %s", legacy, target_db.parent)
    return "migrated"
