"""TEST 5 - Planner Isolation
Verifies planner is NOT invoked for conversational inputs,
and IS invoked for goal_request inputs.
Only verifies classification routing - does not run the actual planner.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.llm import LLMService

SEP = "=" * 60

CASES = [
    # (input_text, expect_planner)
    ("hello",                          False),
    ("what is recursion",              False),
    ("let's discuss game ideas",       False),
    ("organize a college festival",    True),
    ("help me plan a product launch",  True),
]


def run_test():
    print(SEP)
    print("TEST 5: Planner Isolation")
    print(SEP)

    llm = LLMService(api_key="", planner_model="none", conversation_model="none")

    planner_call_count = [0]
    original_pipeline = None  # planner not wired here; verify via classification only

    print(f"  {'Input':<40} {'Type':<25} {'Planner?':<12} {'Expected':<12} {'Result'}")
    print("  " + "-" * 106)

    all_pass = True
    for user_text, expect_planner in CASES:
        t0 = time.perf_counter()
        cls = llm.classify_interaction(user_text)
        latency_ms = (time.perf_counter() - t0) * 1000

        interaction_type = cls["interaction_type"]
        requires_planning = bool(cls.get("requires_planning", False))
        method = cls.get("classification_method", "?")

        planner_would_fire = requires_planning or interaction_type == "goal_request"

        match = planner_would_fire == expect_planner
        if not match:
            all_pass = False

        result_str = "PASS" if match else "FAIL"
        print(
            f"  {repr(user_text):<40} {interaction_type:<25} "
            f"{'YES' if planner_would_fire else 'NO':<12} "
            f"{'YES' if expect_planner else 'NO':<12} "
            f"{result_str}  [{method}  {latency_ms:.1f}ms]"
        )

    print()
    if all_pass:
        print("  TEST 5 PASS  Planner isolation correct for all inputs")
    else:
        print("  TEST 5 FAIL  One or more misclassifications")


if __name__ == "__main__":
    run_test()
