"""TEST 3 - Conversation Validation
Inputs: "How are you?", "What do you think about Unreal Engine?", "Let's discuss game ideas."
For each: Classification, Memory Retrieval, LLM Backend Used, Latency, Response.
Expected: No planner invocation.
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

SEP = "=" * 60

INPUTS = [
    "How are you?",
    "What do you think about Unreal Engine?",
    "Let's discuss game ideas.",
]


def run_test():
    settings = Settings()
    print(SEP)
    print("TEST 3: Conversation Validation")
    print(f"  Backend: {settings.conversation_backend}  Model: {settings.ollama_conversation_model}")
    print(SEP)

    conv_model = OllamaConversationModel(
        model=settings.ollama_conversation_model,
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_request_timeout,
    )

    llm = LLMService(
        api_key=settings.openai_api_key,
        planner_model=settings.openai_planner_model,
        conversation_model=settings.openai_conversation_model,
        conv_model=conv_model,
    )

    wm = WorkingMemory()
    memory = MemoryStore(settings.memory_dir)
    ctx_builder = ConversationContextBuilder(memory=memory, working_memory=wm)

    planner_invoked = [False]

    all_pass = True
    for i, user_text in enumerate(INPUTS, 1):
        print(f"\n  [{i}] Input: {repr(user_text)}")

        planner_invoked[0] = False

        # Classify
        t_cls = time.perf_counter()
        classification = llm.classify_interaction(user_text)
        cls_ms = (time.perf_counter() - t_cls) * 1000
        interaction_type = classification["interaction_type"]
        cls_method = classification.get("classification_method", "?")

        print(f"      Classification : {interaction_type}  method={cls_method}  ({cls_ms:.0f}ms)")

        # Check if memory would be retrieved
        mem_types = {"memory_recall", "goal_request"}
        memory_retrieved = interaction_type in mem_types
        print(f"      Memory Retrieval: {memory_retrieved}")

        # Check planner
        planner_would_fire = interaction_type in {"goal_request", "direct_system_command"}
        print(f"      Planner Invoked: {planner_would_fire}")

        if planner_would_fire:
            all_pass = False
            print("      FAIL  Planner should NOT be invoked for this input")
            continue

        # Build context
        ctx = ctx_builder.build(user_text, interaction_type, ConversationState.CONVERSING)
        wm.append("user", user_text)

        # Generate reply
        t_gen = time.perf_counter()
        reply = llm.conversation_brain_reply(
            user_text=user_text,
            interaction_type=interaction_type,
            context=ctx,
        )
        gen_ms = (time.perf_counter() - t_gen) * 1000
        wm.append("assistant", reply)

        # Determine actual backend used
        backend_used = "ollama" if conv_model.is_available() else "local_fallback"

        print(f"      LLM Backend    : {backend_used}")
        print(f"      Latency        : {gen_ms:.0f}ms")
        print(f"      Response       : {repr(reply[:120])}")

        if planner_would_fire:
            all_pass = False
        else:
            print(f"      Result         : PASS")

    print()
    if all_pass:
        print("  TEST 3 PASS  No planner invocations. All responses generated.")
    else:
        print("  TEST 3 FAIL")


if __name__ == "__main__":
    run_test()
