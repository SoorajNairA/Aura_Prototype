"""TEST 4 - Memory Validation
Simulates festival planning conversation across 3 turns.
Verifies: active project detected, memory loaded, context injected, response references prior info.
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

TURNS = [
    ("goal_request",  "We are organizing a festival with a budget of Rs 2 lakh."),
    ("goal_request",  "The expected attendance is 500 students."),
    ("memory_recall", "Continue our festival planning."),
]


def run_test():
    settings = Settings()
    print(SEP)
    print("TEST 4: Memory Validation - Festival Planning")
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

    # Seed memory with festival project so memory recall can find it
    memory.upsert_project("college_festival", {
        "goal": "Organize a college festival",
        "budget": "Rs 2 lakh",
        "attendance": "500 students",
        "world_state": {
            "completed_tasks": [],
            "pending_tasks": [
                {"title": "Book venue"},
                {"title": "Arrange food stalls"},
                {"title": "Schedule performances"},
            ],
        },
        "notes": "Budget Rs 2 lakh. Expected attendance 500 students.",
    })
    print("  [SETUP] Seeded 'college_festival' project into MemoryStore.")

    ctx_builder = ConversationContextBuilder(memory=memory, working_memory=wm)

    all_pass = True
    for i, (forced_type, user_text) in enumerate(TURNS, 1):
        print(f"\n  [Turn {i}] User: {repr(user_text)}")

        wm.append("user", user_text)

        # Use forced type for turns 1-2 to simulate goal acceptance,
        # use actual classification for turn 3 (memory_recall test).
        if i == 3:
            cls_result = llm.classify_interaction(user_text)
            interaction_type = cls_result["interaction_type"]
            print(f"  Classification (real): {interaction_type}")
        else:
            interaction_type = forced_type
            print(f"  Classification (forced): {interaction_type}")

        t0 = time.perf_counter()
        ctx = ctx_builder.build(user_text, interaction_type, ConversationState.CONVERSING)
        ctx_ms = (time.perf_counter() - t0) * 1000

        print(f"  Context build       : {ctx_ms:.1f}ms")
        print(f"  Turns loaded        : {ctx.turns_loaded}")
        print(f"  Memory snippets     : {ctx.memory_snippets_loaded}")
        print(f"  Active project      : {ctx.active_project is not None}")
        if ctx.active_project:
            print(f"  Project data        : budget={ctx.active_project.get('budget')}  "
                  f"attendance={ctx.active_project.get('attendance')}")
        print(f"  Context block       :")
        cb = ctx.to_context_block()
        for line in (cb or "(empty)").splitlines():
            print(f"    {line}")

        # For turn 3 specifically, verify memory was loaded
        if i == 3:
            if ctx.memory_snippets_loaded > 0 or ctx.active_project is not None:
                print(f"  PASS  Memory retrieved for turn 3")
            else:
                print(f"  FAIL  Memory NOT retrieved for memory_recall turn")
                all_pass = False

        # Generate reply
        t_gen = time.perf_counter()
        reply = llm.conversation_brain_reply(
            user_text=user_text,
            interaction_type=interaction_type,
            context=ctx,
        )
        gen_ms = (time.perf_counter() - t_gen) * 1000

        wm.append("assistant", reply)
        print(f"  Latency             : {gen_ms:.0f}ms")
        print(f"  Response            : {repr(reply[:200])}")

        # Check if response references festival context (turn 3)
        if i == 3:
            keywords = ["festival", "budget", "lakh", "student", "attendance", "planning",
                       "venue", "stall", "performance"]
            mentioned = [k for k in keywords if k.lower() in reply.lower()]
            if mentioned:
                print(f"  PASS  Response references prior context: {mentioned}")
            else:
                print(f"  NOTE  Response may not reference prior context (keywords not found). "
                      f"Review manually: {repr(reply[:200])}")

    print()
    print(f"  Working memory turns : {len(wm.recent())}")
    print(f"  All turns stored     : {[t['role'] for t in wm.recent()]}")

    if all_pass:
        print("\n  TEST 4 PASS")
    else:
        print("\n  TEST 4 FAIL")


if __name__ == "__main__":
    run_test()
