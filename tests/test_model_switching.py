from aura.infrastructure.llm.ollama import OllamaConversationModel
from aura.legacy.assistant.llm import LLMService


def test_ollama_model_can_switch_at_runtime() -> None:
    model = OllamaConversationModel(model="qwen2.5:3b")
    model.is_available = lambda: True
    service = LLMService(conv_model=model)

    active = service.switch_conversation_model("qwen3:8b")
    payload = model._build_payload(
        [{"role": "user", "content": "hello"}],
        system_prompt=None,
        max_tokens=8,
        stream=False,
    )

    assert active == "qwen3:8b"
    assert payload["model"] == "qwen3:8b"
    assert payload["think"] is False
