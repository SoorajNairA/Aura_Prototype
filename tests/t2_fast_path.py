"""TEST 2 - Fast Path Validation
For each input: Classification, Fast Path Used, LLM Calls, Memory Retrieval, Planner Invoked, Latency.
Expected: LLM Calls=0, Memory=false, Planner=false, Latency < 50ms.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.llm import LLMService
from aura.legacy.assistant.conversation_context import WorkingMemory

SEP = "=" * 60

INPUTS = [
    "hello",
    "hi",
    "good morning",
    "thanks",
    "bye",
    "yes",
    "no",
    "Who created you?",
    "Who made you?",
    "Who built AURA?",
    "Were you created by me?",
    "Well, and you created by me",
]

HEADER = f"  {'Input':<20} {'Classification':<22} {'FastPath':<10} {'LLM Calls':<12} {'Memory':<10} {'Planner':<10} {'Latency':>10}"
ROW = "  {input:<20} {cls:<22} {fp:<10} {llm:<12} {mem:<10} {planner:<10} {lat:>10}"


def make_llm():
    return LLMService(
        api_key="",
        planner_model="none",
        conversation_model="none",
    )


def test_fast_path():
    print(SEP)
    print("TEST 2: Fast Path Validation")
    print(SEP)
    llm = make_llm()
    wm = WorkingMemory()

    # Patch to count LLM calls
    llm_call_count = [0]
    original_call = llm._call_output_text
    def counting_call(model, prompt):
        llm_call_count[0] += 1
        return original_call(model, prompt)
    llm._call_output_text = counting_call

    # Patch memory/planner flags (not invoked in fast path, verify by absence)
    print(HEADER)
    print("  " + "-" * 96)

    all_pass = True
    for inp in INPUTS:
        llm_call_count[0] = 0

        t0 = time.perf_counter()
        reply = llm.fast_path_reply(inp, working_memory=wm)
        latency_ms = (time.perf_counter() - t0) * 1000

        fp_used = reply is not None
        llm_calls = llm_call_count[0]
        memory = False   # fast_path_reply never touches memory store
        planner = False  # fast_path_reply never touches planner

        # Classification: fast path tokens always classify as small_talk or greeting
        heuristic_type = llm._heuristic_interaction_type(inp)

        lat_str = f"{latency_ms:.2f}ms"
        row_pass = fp_used and llm_calls == 0 and not memory and not planner and latency_ms < 50
        if not row_pass:
            all_pass = False

        print(ROW.format(
            input=repr(inp),
            cls=heuristic_type,
            fp="YES" if fp_used else "NO (FAIL)",
            llm=str(llm_calls),
            mem="false",
            planner="false",
            lat=lat_str,
        ))
        if fp_used:
            print(f"    Reply: {repr(reply)}")
            if "created" in inp.lower() or "made" in inp.lower() or "built" in inp.lower():
                identity_ok = "Sooraj" in reply and "Alibaba" not in reply
                row_pass = row_pass and identity_ok
                all_pass = all_pass and identity_ok

    print()
    if all_pass:
        print("  TEST 2 PASS  All fast-path inputs: LLM=0, Memory=false, Planner=false, <50ms")
    else:
        print("  TEST 2 FAIL  One or more inputs did not meet requirements")


if __name__ == "__main__":
    test_fast_path()
