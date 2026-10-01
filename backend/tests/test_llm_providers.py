from types import SimpleNamespace

import pytest

from app.services import llm_service as llm_module
from app.services.llm_service import (
    GeminiProvider,
    LLMService,
    LLMServiceError,
    OpenAICompatibleProvider,
)


class FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, system_prompt, user_prompt, *, json_schema=None):
        self.calls.append((system_prompt, user_prompt, json_schema))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_gemini_provider_uses_sdk_client_and_json_schema():
    calls = []

    class FakeInteractions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text='{"operation":"sum"}')

    provider = GeminiProvider("test-key", "gemini-test", client=SimpleNamespace(interactions=FakeInteractions()))
    output = provider.generate("system", "user", json_schema={"type": "object"})

    assert output == '{"operation":"sum"}'
    assert calls[0]["model"] == "gemini-test"
    assert calls[0]["system_instruction"] == "system"
    assert calls[0]["response_format"]["mime_type"] == "application/json"


@pytest.mark.parametrize(
    ("name", "base_url"),
    [
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("groq", "https://api.groq.com/openai/v1"),
    ],
)
def test_openai_compatible_providers_use_configured_endpoint(monkeypatch, name, base_url):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_module, "OpenAI", FakeClient)
    provider = OpenAICompatibleProvider(name, "test-key", "test-model")

    assert provider.generate("system", "user", json_schema={"type": "object"}) == "ok"
    assert captured["client"]["base_url"] == base_url
    assert captured["request"]["model"] == "test-model"
    assert captured["request"]["response_format"] == {"type": "json_object"}


def test_service_retries_invalid_json_then_validates_structured_plan():
    adapter = FakeAdapter([
        "not json",
        '{"intent":"aggregation","metric":"Sales Amount","group_by":"Region","operation":"sum","sort":"descending","limit":1}',
    ])
    service = LLMService({"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, {"groq": adapter})

    plan = service.analyze_question("Which region has the highest sales?", ["Region", "Sales Amount"])

    assert plan["metric"] == "Sales Amount"
    assert plan["group_by"] == "Region"
    assert plan["operation"] == "sum"
    assert len(adapter.calls) == 2


def test_provider_error_is_clear_when_key_is_missing():
    service = LLMService({"LLM_PROVIDER": "gemini"})

    with pytest.raises(LLMServiceError, match="GEMINI_API_KEY"):
        service.generate("system", "user")


def test_configured_fallback_provider_is_used_when_enabled():
    failing = FakeAdapter([LLMServiceError("primary down")])
    fallback = FakeAdapter(["grounded response"])
    service = LLMService(
        {
            "LLM_PROVIDER": "gemini",
            "LLM_FALLBACK_ENABLED": "true",
            "GEMINI_API_KEY": "test-gemini-key",
            "GROQ_API_KEY": "test-groq-key",
        },
        {"gemini": failing, "groq": fallback},
    )

    assert service.generate("system", "user") == "grounded response"


def test_provider_status_never_returns_credentials():
    service = LLMService({"LLM_PROVIDER": "groq", "GROQ_API_KEY": "secret-test-value"})

    status = service.provider_status()

    assert status["active_provider"] == "groq"
    assert status["active_configured"] is True
    assert "secret-test-value" not in str(status)
    assert service.set_provider("openrouter")["active_provider"] == "openrouter"
    with pytest.raises(ValueError):
        service.set_provider("unsupported")