"""Fast API contract tests that avoid loading Geoq's optional AI stack."""

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient


_MISSING = object()


def _noop(*_args, **_kwargs):
    """Accept logging and persistence calls that are irrelevant to API contracts."""


def _install_runtime_stubs():
    """Install lightweight modules required to import ``api.app`` in CI."""
    module_names = (
        "api.utils",
        "api.graph",
        "api.config",
        "langchain_core",
        "langchain_core.messages",
        "uvicorn",
    )
    previous_modules = {name: sys.modules.get(name, _MISSING) for name in module_names}

    # The endpoint contracts only need normalization and logging; model, Redis,
    # Chroma, and LangGraph setup must remain outside this dependency-light suite.
    utils_module = ModuleType("api.utils")
    utils_module.logger = SimpleNamespace(
        debug=_noop,
        info=_noop,
        warning=_noop,
        error=_noop,
        critical=_noop,
        exception=_noop,
    )
    utils_module.normalize_farsi = lambda value: value
    utils_module.chain_with_history = None
    utils_module.get_session_history = _noop
    utils_module.save_session_history = _noop
    utils_module.llm = None
    utils_module.runtime_error = None

    graph_module = ModuleType("api.graph")
    graph_module.conversation_graph = SimpleNamespace()
    graph_module.ConversationState = dict

    config_module = ModuleType("api.config")
    config_module.GEOQ_NAME = "Geoq"
    config_module.PORT = 8001
    config_module.CORS_ORIGINS = []

    langchain_module = ModuleType("langchain_core")
    langchain_module.__path__ = []
    messages_module = ModuleType("langchain_core.messages")
    messages_module.AIMessage = SimpleNamespace
    langchain_module.messages = messages_module

    uvicorn_module = ModuleType("uvicorn")
    uvicorn_module.run = _noop

    sys.modules.update(
        {
            "api.utils": utils_module,
            "api.graph": graph_module,
            "api.config": config_module,
            "langchain_core": langchain_module,
            "langchain_core.messages": messages_module,
            "uvicorn": uvicorn_module,
        }
    )
    return previous_modules


def _restore_runtime_modules(previous_modules):
    """Restore modules replaced by the dependency-light contract fixture."""
    for name, previous in previous_modules.items():
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


@pytest.fixture(scope="module")
def api_runtime():
    """Provide the real FastAPI routes with external runtime dependencies stubbed."""
    previous_modules = _install_runtime_stubs()
    previous_app = sys.modules.pop("api.app", _MISSING)

    try:
        app_module = importlib.import_module("api.app")
        with TestClient(app_module.app) as client:
            yield client, app_module
    finally:
        sys.modules.pop("api.app", None)
        if previous_app is not _MISSING:
            sys.modules["api.app"] = previous_app
        _restore_runtime_modules(previous_modules)


def test_health_contract_reports_ready_runtime(api_runtime):
    """Document the public health response without initializing AI resources."""
    client, _ = api_runtime

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": "geoq-0",
        "orchestration": "LangGraph",
        "ai_resources": "ready",
    }


def test_health_contract_reports_degraded_runtime(api_runtime, monkeypatch):
    """Expose dependency initialization failures through the health contract."""
    client, _ = api_runtime
    monkeypatch.setattr(sys.modules["api.utils"], "runtime_error", RuntimeError("model unavailable"))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "model": "geoq-0",
        "orchestration": "LangGraph",
        "ai_resources": "not_ready",
    }


def test_models_contract_is_openai_compatible(api_runtime):
    """Document the model-list shape consumed by OpenAI-compatible clients."""
    client, _ = api_runtime

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "geoq-0",
                "object": "model",
                "created": 1677610602,
                "owned_by": "geoq",
            }
        ],
    }


def test_chat_contract_rejects_empty_messages(api_runtime):
    """Reject requests that omit the conversation required by the API model."""
    client, _ = api_runtime

    response = client.post("/v1/chat/completions", json={"messages": [], "stream": False})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "messages"]


def test_chat_contract_requires_user_as_final_message(api_runtime):
    """Reject a conversation whose final message cannot drive a user turn."""
    client, _ = api_runtime

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "assistant", "content": "Done"}], "stream": False},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "The last message must be from the user"}


def test_non_streaming_chat_contract_uses_openai_response_shape(api_runtime, monkeypatch):
    """Return the documented response envelope while the graph is mocked."""
    client, app_module = api_runtime

    def fake_run_graph(session_id, messages, user_input):
        """Return a deterministic graph result for the non-streaming route."""
        assert session_id == "contract-test"
        assert messages[-1].content == "Where should I go?"
        assert user_input == "Where should I go?"
        return {"llm_output": "Visit Hormuz Castle.", "route": "local"}

    monkeypatch.setattr(app_module, "run_graph_blocking", fake_run_graph)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "geoq-0",
            "messages": [{"role": "user", "content": "Where should I go?"}],
            "stream": False,
            "session_id": "contract-test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("chatcmpl-")
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "Geoq"
    assert payload["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Visit Hormuz Castle."},
            "finish_reason": "stop",
        }
    ]
    assert payload["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
