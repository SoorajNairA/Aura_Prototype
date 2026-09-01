"""Isolated structured-model test double for browser integration tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

import uvicorn

from aura.workspace.server import create_app


class BrowserScenarioProvider:
    def generate_structured(self, messages, **_kwargs):
        context = json.loads(messages[0]["content"])
        target = context["target"]
        candidate = context["candidateRequest"]["name"]
        incompatible = target["family"] == "light_sensor" and "servo" in candidate.lower()
        payload = {
            "decision": "INCOMPATIBLE" if incompatible else "COMPATIBLE",
            "candidateName": candidate,
            "candidateFamily": "servo" if incompatible else target["family"],
            "candidateFunctionalRoles": ["controlled_motion"] if incompatible else target["functionalRoles"],
            "interfaceCompatibility": "INCOMPATIBLE" if incompatible else "COMPATIBLE",
            "confidence": "HIGH",
            "rationale": "A servo produces controlled motion and cannot provide ambient-light feedback." if incompatible else "The candidate preserves the target function and interfaces.",
            "missingRequiredRoles": target["functionalRoles"] if incompatible else [],
            "requiredChanges": [],
            "assumptions": [],
        }
        return SimpleNamespace(text=json.dumps(payload), model="browser-scenario-test-model",
            input_tokens=20, output_tokens=30, total_tokens=50)


if __name__ == "__main__":
    uvicorn.run(create_app(provider=BrowserScenarioProvider(), storage_mode="memory"), host="127.0.0.1", port=4184)
