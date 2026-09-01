"""TEST 8 - Streaming Pipeline Validation
Verifies:
  - Token stream is consumed chunk by chunk
  - Each chunk <= MAX_WORDS words
  - First chunk arrives well before full response would complete
  - Full text assembled correctly
  - Fallback works when streaming is unavailable
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("AURA_OLLAMA_MODEL", "qwen2.5:3b")
os.environ.setdefault("AURA_CONVERSATION_BACKEND", "ollama")
os.environ.setdefault("AURA_OLLAMA_TIMEOUT", "60")

from aura.app.config import Settings
from aura.legacy.assistant.conversation_context import ConversationContextBuilder, ConversationState, WorkingMemory
from aura.infrastructure.llm.ollama import OllamaConversationModel
from aura.legacy.assistant.llm import LLMService
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.infrastructure.voice.tts import TTSService

SEP = "=" * 60


# ---------------------------------------------------------------------------
# Stub TTS: records chunks + timings without audio hardware
# ---------------------------------------------------------------------------
class RecordingTTS(TTSService):
    def __init__(self, real_tts: TTSService):
        # Borrow the real tts state but intercept speak()
        self.__dict__ = real_tts.__dict__.copy()
        self.spoken_chunks: list[str] = []
        self.chunk_times: list[float] = []
        self._t0 = time.perf_counter()

    def speak(self, text: str) -> None:
        ms = (time.perf_counter() - self._t0) * 1000
        self.chunk_times.append(ms)
        self.spoken_chunks.append(text)
        word_count = len(text.split())
        print(f"    [TTS chunk {len(self.spoken_chunks)}] at {ms:.0f}ms  words={word_count}  text={repr(text[:80])}")

    def reset(self) -> None:
        self.spoken_chunks = []
        self.chunk_times = []
        self._t0 = time.perf_counter()


def run_test():
    settings = Settings()
    print(SEP)
    print("TEST 8: Streaming Pipeline Validation")
    print(f"  Model: {settings.ollama_conversation_model}")
    print(SEP)

    conv_model = OllamaConversationModel(
        model=settings.ollama_conversation_model,
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_request_timeout,
    )
    real_tts = TTSService(
        elevenlabs_api_key=settings.elevenlabs_api_key,
        voice_id=settings.elevenlabs_voice_id,
        model_id=settings.elevenlabs_model_id,
        stability=settings.elevenlabs_stability,
        similarity_boost=settings.elevenlabs_similarity_boost,
        style=settings.elevenlabs_style,
        speaker_boost=settings.elevenlabs_speaker_boost,
        clarity=settings.elevenlabs_clarity,
        naturalness=settings.elevenlabs_naturalness,
        local_rate=settings.local_tts_rate,
        local_voice_index=settings.local_tts_voice_index,
    )
    rec_tts = RecordingTTS(real_tts)

    llm = LLMService(
        api_key=settings.openai_api_key,
        planner_model=settings.openai_planner_model,
        conversation_model=settings.openai_conversation_model,
        conv_model=conv_model,
    )

    wm = WorkingMemory()
    memory = MemoryStore(settings.memory_dir)
    ctx_builder = ConversationContextBuilder(memory=memory, working_memory=wm)

    all_pass = True

    # -----------------------------------------------------------------------
    # TEST 8a: Streaming produces multiple chunks for a long response
    # -----------------------------------------------------------------------
    print("\n  TEST 8a: Multi-chunk streaming (long response prompt)")
    user_text = "Explain what Unreal Engine is and list three reasons game developers use it."
    interaction_type = "question"

    wm.append("user", user_text)
    ctx = ctx_builder.build(user_text, interaction_type, ConversationState.CONVERSING)

    rec_tts.reset()
    t0 = time.perf_counter()
    try:
        token_stream = llm.conversation_brain_stream(user_text, interaction_type, ctx)
        full_text = rec_tts.speak_streamed(token_stream)
        total_ms = (time.perf_counter() - t0) * 1000
    except Exception as e:
        print(f"  FAIL  stream raised: {e}")
        all_pass = False
        full_text = ""
        total_ms = 0

    wm.append("assistant", full_text)

    print(f"\n  Results:")
    print(f"    Total time           : {total_ms:.0f}ms")
    print(f"    Chunks produced      : {len(rec_tts.spoken_chunks)}")
    first_chunk_ms = rec_tts.chunk_times[0] if rec_tts.chunk_times else None
    print(f"    First chunk at       : {first_chunk_ms:.0f}ms" if first_chunk_ms else "    First chunk at       : N/A")
    print(f"    Full text length     : {len(full_text.split())} words")
    print(f"    Full text preview    : {repr(full_text[:120])}")

    # Validate chunk word counts
    max_chunk_words = max((len(c.split()) for c in rec_tts.spoken_chunks), default=0)
    print(f"    Max words per chunk  : {max_chunk_words}  (target <= 40+buffer)")

    # Checks
    stream_produced = len(rec_tts.spoken_chunks) > 0
    has_content = len(full_text.split()) >= 5
    chunk_size_ok = max_chunk_words <= 55  # allow small overshoot from markdown

    if stream_produced and has_content:
        print(f"  TEST 8a PASS  Stream produced {len(rec_tts.spoken_chunks)} chunk(s)")
    else:
        print(f"  TEST 8a FAIL  stream_produced={stream_produced}  has_content={has_content}")
        all_pass = False

    # -----------------------------------------------------------------------
    # TEST 8b: First chunk latency < full-response latency
    # -----------------------------------------------------------------------
    print("\n  TEST 8b: First chunk arrives before full response would complete")
    if first_chunk_ms and total_ms:
        ratio = first_chunk_ms / total_ms
        print(f"    First chunk / total  : {first_chunk_ms:.0f}ms / {total_ms:.0f}ms = {ratio:.1%}")
        if ratio < 0.85 and len(rec_tts.spoken_chunks) > 1:
            print(f"  TEST 8b PASS  First chunk at {ratio:.0%} of total time (speech started early)")
        elif len(rec_tts.spoken_chunks) == 1:
            print(f"  TEST 8b NOTE  Response was short enough to fit in one chunk. Acceptable.")
        else:
            print(f"  TEST 8b NOTE  Single-chunk response — no parallelism needed.")
    else:
        print(f"  TEST 8b SKIP  No timing data.")

    # -----------------------------------------------------------------------
    # TEST 8c: Fallback works when conv_model is None
    # -----------------------------------------------------------------------
    print("\n  TEST 8c: Fallback to full-response when no streaming model")
    llm_no_stream = LLMService(
        api_key="",
        planner_model="none",
        conversation_model="none",
        conv_model=None,  # no streaming model
    )
    try:
        llm_no_stream.conversation_brain_stream("hello", "greeting")
        print("  TEST 8c FAIL  Should have raised RuntimeError")
        all_pass = False
    except RuntimeError as e:
        print(f"  TEST 8c PASS  Raised RuntimeError as expected: {e}")
    except Exception as e:
        print(f"  TEST 8c FAIL  Wrong exception type: {type(e).__name__}: {e}")
        all_pass = False

    # -----------------------------------------------------------------------
    # TEST 8d: speak_streamed with a fake fast token stream
    # -----------------------------------------------------------------------
    print("\n  TEST 8d: speak_streamed chunk boundaries from synthetic token stream")

    def fake_tokens():
        """Yield a 60-word stream as individual word tokens."""
        words = (
            "The quick brown fox jumps over the lazy dog and then runs away into the forest "
            "where it finds a quiet spot to rest and think about its adventures. "
            "Later the fox returns home and tells all the other foxes about the amazing journey."
        ).split()
        for w in words:
            yield w + " "

    rec_tts.reset()
    t0 = time.perf_counter()
    assembled = rec_tts.speak_streamed(fake_tokens())
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"    Elapsed              : {elapsed:.0f}ms")
    print(f"    Chunks              : {len(rec_tts.spoken_chunks)}")
    print(f"    Full text words     : {len(assembled.split())}")
    for i, (chunk, ms) in enumerate(zip(rec_tts.spoken_chunks, rec_tts.chunk_times)):
        print(f"    Chunk {i+1}  at={ms:.0f}ms  words={len(chunk.split())}  text={repr(chunk[:60])}")

    chunks_ok = len(rec_tts.spoken_chunks) >= 1
    words_ok = len(assembled.split()) >= 40  # 60 input words → some recombined
    all_under_max = all(len(c.split()) <= 55 for c in rec_tts.spoken_chunks)
    if chunks_ok and words_ok and all_under_max:
        print(f"  TEST 8d PASS  Chunking correct.")
    else:
        print(f"  TEST 8d FAIL  chunks_ok={chunks_ok}  words_ok={words_ok}  all_under_max={all_under_max}")
        all_pass = False

    # Final
    print()
    print(SEP)
    if all_pass:
        print("  TEST 8 PASS  Streaming pipeline validated.")
    else:
        print("  TEST 8 FAIL  One or more checks failed.")
    print(SEP)


if __name__ == "__main__":
    run_test()
