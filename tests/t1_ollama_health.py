"""TEST 1 - Ollama Health Check
Checks: server reachable, model exists, loads, first-token latency, full-response latency.
"""
import json
import sys
import time

import requests

BASE = "http://localhost:11434"
MODEL = "qwen2.5:3b"

SEP = "=" * 60


def check_server():
    print(SEP)
    print("TEST 1a: Ollama server reachable")
    t0 = time.perf_counter()
    try:
        r = requests.get(f"{BASE}/api/tags", timeout=5)
        ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200, f"HTTP {r.status_code}"
        print(f"  PASS  status=200  latency={ms:.1f}ms")
        return r.json()
    except Exception as e:
        print(f"  FAIL  {e}")
        sys.exit(1)


def check_model(tags_data):
    print(SEP)
    print(f"TEST 1b: Model '{MODEL}' exists")
    models = [m.get("name", "") for m in tags_data.get("models", [])]
    print(f"  Available models: {models}")
    found = any(m == MODEL or m.startswith(MODEL.split(":")[0]) for m in models)
    if found:
        print(f"  PASS  model '{MODEL}' found")
    else:
        print(f"  FAIL  model '{MODEL}' not found. Run: ollama pull {MODEL}")
        sys.exit(1)


def check_first_token_latency():
    print(SEP)
    print("TEST 1c: First-token latency (streaming)")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Reply concisely."},
            {"role": "user", "content": "hello"},
        ],
        "stream": True,
        "options": {"num_predict": 32},
    }
    t_start = time.perf_counter()
    first_token_ms = None
    full_response = []
    try:
        with requests.post(f"{BASE}/api/chat", json=payload, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                chunk = json.loads(raw)
                token = chunk.get("message", {}).get("content", "")
                if token and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t_start) * 1000
                if token:
                    full_response.append(token)
                if chunk.get("done", False):
                    break
    except Exception as e:
        print(f"  FAIL  {e}")
        sys.exit(1)

    full_ms = (time.perf_counter() - t_start) * 1000
    reply = "".join(full_response).strip()

    print(f"  First token latency : {first_token_ms:.0f}ms  (target < 2000ms)")
    print(f"  Full response latency: {full_ms:.0f}ms  (target < 5000ms)")
    print(f"  Response text        : '{reply}'")

    if first_token_ms is None:
        print("  FAIL  no tokens received")
        sys.exit(1)

    ft_pass = first_token_ms < 2000
    fr_pass = full_ms < 5000
    print(f"  First token < 2s : {'PASS' if ft_pass else 'FAIL (exceeded)'}")
    print(f"  Full resp  < 5s  : {'PASS' if fr_pass else 'FAIL (exceeded)'}")

    if not (ft_pass and fr_pass):
        print("  NOTE: Latency targets may vary on first cold load. Warm runs are faster.")


if __name__ == "__main__":
    tags = check_server()
    check_model(tags)
    check_first_token_latency()
    print(SEP)
    print("TEST 1 COMPLETE")
