"""TEST 6 - Thread Safety
Spawns 10 concurrent threads all calling WorkingMemory.append simultaneously.
Verifies no race conditions, no crashes, correct turn count, consistent state.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.conversation_context import WorkingMemory

SEP = "=" * 60

NUM_THREADS = 10
TURNS_PER_THREAD = 20
EXPECTED_TOTAL = NUM_THREADS * TURNS_PER_THREAD  # may be capped by maxlen=30


def writer_thread(wm: WorkingMemory, thread_id: int, errors: list, results: list):
    try:
        for i in range(TURNS_PER_THREAD):
            role = "user" if i % 2 == 0 else "assistant"
            wm.append(role, f"Thread {thread_id} message {i}")
            time.sleep(0)  # yield
        results.append(thread_id)
    except Exception as e:
        errors.append(f"Thread {thread_id} error: {e}")


def run_test():
    print(SEP)
    print("TEST 6: Thread Safety - WorkingMemory")
    print(f"  Threads: {NUM_THREADS}  Turns/thread: {TURNS_PER_THREAD}")
    print(f"  Total writes attempted: {EXPECTED_TOTAL}  (maxlen=30, so final count <= 30)")
    print(SEP)

    wm = WorkingMemory(max_turns=30)
    errors = []
    results = []
    threads = []

    t0 = time.perf_counter()
    for tid in range(NUM_THREADS):
        t = threading.Thread(
            target=writer_thread,
            args=(wm, tid, errors, results),
            daemon=True,
        )
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"  Elapsed              : {elapsed_ms:.0f}ms")
    print(f"  Threads completed    : {len(results)}/{NUM_THREADS}")
    print(f"  Errors               : {len(errors)}")
    if errors:
        for e in errors:
            print(f"    {e}")

    final_turns = wm.recent(n=30)
    print(f"  Final turn count     : {len(final_turns)}  (maxlen=30)")
    print(f"  All turns have role  : {all('role' in t for t in final_turns)}")
    print(f"  All turns have content: {all('content' in t for t in final_turns)}")
    print(f"  All turns have ts    : {all('ts' in t for t in final_turns)}")

    # Verify content is coherent (no half-written strings)
    for turn in final_turns:
        content = turn.get("content", "")
        role = turn.get("role", "")
        assert isinstance(content, str) and len(content) > 0, f"Empty/corrupt content: {turn}"
        assert role in ("user", "assistant"), f"Invalid role: {role}"

    # as_messages correctness
    msgs = wm.as_messages()
    assert all("role" in m and "content" in m for m in msgs), "as_messages() returned corrupt entries"

    no_crashes = len(errors) == 0
    all_done = len(results) == NUM_THREADS
    data_ok = len(final_turns) == 30 and all(
        isinstance(t.get("content"), str) for t in final_turns
    )

    print()
    if no_crashes and all_done and data_ok:
        print("  TEST 6 PASS  No race conditions, no crashes, WorkingMemory consistent")
    else:
        print("  TEST 6 FAIL")
        if not no_crashes:
            print("  FAIL: exceptions occurred")
        if not all_done:
            print(f"  FAIL: only {len(results)}/{NUM_THREADS} threads completed")
        if not data_ok:
            print("  FAIL: data corruption detected")


if __name__ == "__main__":
    run_test()
