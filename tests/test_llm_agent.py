import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import numpy as np
import pytest

from gamepilot.llm_agent.controller import AgentDecisionError, GameAction, TaskAgent, observation_summary
from gamepilot.llm_agent.evaluator import evaluate_episode, evaluate_task_agent
from gamepilot.llm_agent.provider import ChatProvider, ChatResult, ProviderError, ProviderSettings
from gamepilot.tasks import TASK_DIR, load_task


class ResponseHandler(BaseHTTPRequestHandler):
    envelope = {}
    seen = None
    status = 200
    delay_seconds = 0.0

    def do_POST(self):
        time.sleep(type(self).delay_seconds)
        type(self).seen = {"path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))}
        encoded = json.dumps(type(self).envelope).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        pass


@pytest.fixture
def fake_http():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ResponseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()
    server.server_close()


def test_ollama_provider_uses_json_schema_and_parses_action_and_usage(fake_http):
    ResponseHandler.envelope = {"message": {"role": "assistant",
        "content": '{"move":1,"shoot":8,"repeat":5}'}, "prompt_eval_count": 12,
        "eval_count": 4}
    provider = ChatProvider(ProviderSettings("ollama", "test-model", fake_http))
    result = provider.call_tool([{"role": "user", "content": "test"}], max_repeat=20)
    assert result.tool_name == "step_game"
    assert result.arguments == {"move": 1, "shoot": 8, "repeat": 5}
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 4}
    assert ResponseHandler.seen["path"] == "/api/chat"
    assert ResponseHandler.seen["body"]["options"]["num_predict"] == 768
    assert ResponseHandler.seen["body"]["think"] is False
    assert ResponseHandler.seen["body"]["stream"] is False
    assert ResponseHandler.seen["body"]["format"]["additionalProperties"] is False
    assert ResponseHandler.seen["body"]["format"]["properties"]["repeat"]["maximum"] == 20


def test_ollama_provider_supports_api_base_url(fake_http):
    ResponseHandler.envelope = {"message": {"role": "assistant", "content":
        '{"move":0,"shoot":0,"repeat":1}'}}
    provider = ChatProvider(ProviderSettings("ollama", "model", fake_http + "/api"))
    provider.call_tool([], max_repeat=5)
    assert ResponseHandler.seen["path"] == "/api/chat"


def test_ollama_provider_returns_invalid_json_for_bounded_repair():
    provider = ChatProvider(ProviderSettings("ollama", "model", "http://127.0.0.1"))
    result = provider._parse({"message": {"role": "assistant", "content": "not json"},
                              "prompt_eval_count": 4, "eval_count": 2})
    assert result.tool_name == "step_game"
    assert result.arguments == "not json"
    assert result.assistant_message == {"role": "assistant", "content": "not json"}
    assert result.usage == {"prompt_tokens": 4, "completion_tokens": 2}


def test_openai_compatible_provider_sends_auth_and_parses_response(fake_http):
    ResponseHandler.envelope = {"choices": [{"message": {"role": "assistant", "tool_calls": [{
        "id": "call_1", "type": "function", "function": {"name": "step_game",
        "arguments": '{"move":0,"shoot":2,"repeat":3}'}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    provider = ChatProvider(ProviderSettings("openai_compatible", "model", fake_http,
                                              "secret-value"))
    result = provider.call_tool([], max_repeat=5)
    assert result.arguments == {"move": 0, "shoot": 2, "repeat": 3}
    assert result.usage["prompt_tokens"] == 10
    assert ResponseHandler.seen["path"] == "/v1/chat/completions"
    assert ResponseHandler.seen["headers"]["Authorization"] == "Bearer secret-value"


def test_openai_compatible_base_url_with_v1_is_not_duplicated(fake_http):
    ResponseHandler.envelope = {"choices": [{"message": {"role": "assistant", "tool_calls": [{
        "id": "call_1", "type": "function", "function": {"name": "step_game",
        "arguments": '{"move":0,"shoot":2,"repeat":3}'}}]}}]}
    settings = ProviderSettings("openai_compatible", "model", fake_http + "/v1")
    ChatProvider(settings).call_tool([], max_repeat=5)
    assert ResponseHandler.seen["path"] == "/v1/chat/completions"


def test_provider_http_failure_does_not_leak_response_body(fake_http):
    ResponseHandler.status = 429
    ResponseHandler.envelope = {"error": "secret response body"}
    provider = ChatProvider(ProviderSettings("ollama", "model", fake_http))
    try:
        with pytest.raises(ProviderError) as raised:
            provider.call_tool([], max_repeat=4)
        assert raised.value.category == "http_error"
        assert "secret" not in str(raised.value)
    finally:
        ResponseHandler.status = 200


def test_provider_timeout_is_classified(fake_http):
    ResponseHandler.delay_seconds = 0.2
    provider = ChatProvider(ProviderSettings("ollama", "model", fake_http,
                                              timeout_seconds=0.05))
    try:
        with pytest.raises(ProviderError) as raised:
            provider.call_tool([], max_repeat=4)
        assert raised.value.category == "transport_error"
    finally:
        ResponseHandler.delay_seconds = 0.0


def test_ollama_provider_rejects_non_string_action_content():
    provider = ChatProvider(ProviderSettings("ollama", "model", "http://127.0.0.1"))
    with pytest.raises(ProviderError, match="invalid_message_content"):
        provider._parse({"message": {"content": {"move": 0}}})


def test_task_agent_repairs_invalid_arguments_once():
    class SequenceProvider:
        def __init__(self):
            self.responses = [
                ChatResult("step_game", {"move": 9, "shoot": 0, "repeat": 2},
                           {"role": "assistant", "content": ""}, {"prompt_tokens": 2, "completion_tokens": 1}),
                ChatResult("step_game", {"move": 2, "shoot": 5, "repeat": 1},
                           {"role": "assistant", "content": ""}, {"prompt_tokens": 3, "completion_tokens": 1}),
            ]
            self.messages = []

        def call_tool(self, messages, *, max_repeat):
            self.messages.append(messages)
            return self.responses.pop(0)

    provider = SequenceProvider()
    task = load_task(TASK_DIR / "kill_target.json")
    action, usage = TaskAgent(provider, max_repeat=10).decide(
        task, np.zeros(76, dtype=np.float32), {"seconds": 0}, decision_index=0)
    assert action == GameAction(2, 5, 1)
    assert usage["repair_attempts"] == 1
    assert usage["prompt_tokens"] == 5 and usage["completion_tokens"] == 2
    assert "rejected" in provider.messages[1][-1]["content"]


@pytest.mark.parametrize("arguments, category", [
    ({"move": True, "shoot": 0, "repeat": 1}, "tool_arguments_must_be_integers"),
    ({"move": 0, "shoot": 0, "repeat": 11}, "tool_argument_out_of_range"),
    ({"move": 0, "shoot": 0}, "invalid_tool_arguments"),
])
def test_task_agent_rejects_invalid_arguments(arguments, category):
    class InvalidProvider:
        def call_tool(self, *_args, **_kwargs):
            return ChatResult("step_game", arguments, {"role": "assistant", "content": ""},
                              {"prompt_tokens": 0, "completion_tokens": 0})

    task = load_task(TASK_DIR / "kill_target.json")
    with pytest.raises(AgentDecisionError) as raised:
        TaskAgent(InvalidProvider(), max_repeat=10, repair_attempts=0).decide(
            task, np.zeros(76, dtype=np.float32), {}, decision_index=0)
    assert raised.value.category == category


def test_provider_settings_require_model_and_never_default_api_key(monkeypatch):
    monkeypatch.setenv("GAMEPILOT_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GAMEPILOT_LLM_MODEL", raising=False)
    monkeypatch.delenv("GAMEPILOT_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MODEL"):
        ProviderSettings.from_env()
    monkeypatch.setenv("GAMEPILOT_LLM_MODEL", "qwen3:4b")
    settings = ProviderSettings.from_env()
    assert settings.base_url == "http://127.0.0.1:11434"
    assert settings.api_key is None
    monkeypatch.setenv("GAMEPILOT_LLM_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(ValueError, match="must be a number"):
        ProviderSettings.from_env()
    monkeypatch.setenv("GAMEPILOT_LLM_TIMEOUT_SECONDS", "5")
    assert ProviderSettings.from_env().timeout_seconds == 5
    monkeypatch.setenv("GAMEPILOT_LLM_MAX_COMPLETION_TOKENS", "1024")
    assert ProviderSettings.from_env().max_completion_tokens == 1024
    monkeypatch.setenv("GAMEPILOT_LLM_MAX_COMPLETION_TOKENS", "12")
    with pytest.raises(ValueError, match="between 64 and 8192"):
        ProviderSettings.from_env()


def test_provider_safe_url_drops_userinfo_and_query_secrets():
    settings = ProviderSettings("openai_compatible", "model",
        "https://user:password@example.test:9443/v1?token=private#fragment")
    assert settings.safe_base_url == "https://example.test:9443/v1"
    assert "password" not in settings.safe_base_url
    assert "private" not in settings.safe_base_url


def test_observation_summary_decodes_game_enemy_and_pickup_types():
    obs = np.zeros(76, dtype=np.float32)
    obs[12 + 5] = 1 / 3
    obs[12 + 6] = 1
    obs[60 + 2] = 0.5
    obs[60 + 3] = 1
    summary = observation_summary(obs, {})
    assert summary["nearest_enemies"][0]["type"] == "shelled"
    assert summary["nearest_pickups"][0]["type"] == "rapid_fire"


def test_environment_start_failure_is_recorded_as_invalid_episode(tmp_path, monkeypatch):
    class BrokenEnv:
        def __init__(self, **_kwargs):
            raise ConnectionError("Godot is unavailable")

    class UnusedProvider:
        def call_tool(self, *_args, **_kwargs):
            raise AssertionError("provider must not be called")

    monkeypatch.setattr("gamepilot.llm_agent.evaluator.PilotEnv", BrokenEnv)
    task = load_task(TASK_DIR / "kill_target.json")
    row = evaluate_episode(TaskAgent(UnusedProvider()), task, seed=2000,
                           trace_path=tmp_path / "startup-error.json")
    assert row["task_status"] == "invalid"
    assert row["task_reason"] == "execution_ConnectionError"
    trace = json.loads((tmp_path / "startup-error.json").read_text(encoding="utf-8"))
    assert trace["execution_error"] == "execution_ConnectionError"
    summary = evaluate_task_agent(TaskAgent(UnusedProvider()), task, seeds=[2000])
    assert summary["invalid_reasons"] == {"execution_ConnectionError": 1}


def test_agent_enforces_per_episode_request_and_token_budgets():
    class CountingProvider:
        def __init__(self):
            self.calls = 0

        def call_tool(self, *_args, **_kwargs):
            self.calls += 1
            return ChatResult("step_game", {"move": 0, "shoot": 0, "repeat": 1},
                {"role": "assistant", "content": ""},
                {"prompt_tokens": 3, "completion_tokens": 2})

    task = load_task(TASK_DIR / "kill_target.json")
    provider = CountingProvider()
    agent = TaskAgent(provider, max_requests_per_episode=2, max_tokens_per_episode=10)
    for index in range(2):
        agent.decide(task, np.zeros(76), {}, decision_index=index)
    with pytest.raises(AgentDecisionError, match="request_budget_exhausted"):
        agent.decide(task, np.zeros(76), {}, decision_index=2)
    assert provider.calls == 2
    assert agent.usage["model_requests"] == 2
    assert agent.usage["prompt_tokens"] == 6

    agent.reset_episode()
    agent = TaskAgent(provider, max_requests_per_episode=5, max_tokens_per_episode=4)
    with pytest.raises(AgentDecisionError, match="token_budget_exhausted"):
        agent.decide(task, np.zeros(76), {}, decision_index=0)
    assert provider.calls == 3
    assert agent.usage["model_requests"] == 1


def test_recent_action_memory_is_bounded_structured_and_cleared_between_episodes():
    class MemoryProvider:
        def __init__(self):
            self.payloads = []

        def call_tool(self, messages, *, max_repeat):
            self.payloads.append(json.loads(messages[-1]["content"]))
            return ChatResult("step_game", {"move": 1, "shoot": 3, "repeat": 1},
                {"role": "assistant", "content": ""},
                {"prompt_tokens": 2, "completion_tokens": 1})

    provider = MemoryProvider()
    task = load_task(TASK_DIR / "kill_target.json")
    agent = TaskAgent(provider, history_window=2)
    obs_before = np.zeros(76, dtype=np.float32)
    action = None
    before_info = {"seconds": 0.0, "health": 5, "damage": 0, "kills": 0,
                   "pickups_collected": 0}
    for index in range(3):
        action, _ = agent.decide(task, obs_before, before_info, decision_index=index)
        after_info = {"seconds": index + 1.0, "health": 5, "damage": 0,
                      "kills": index + 1, "pickups_collected": 0}
        agent.record_transition(before_obs=obs_before, before_info=before_info,
            action=action, after_obs=obs_before, after_info=after_info,
            grade={"status": "running", "reason": None}, executed_repeat=1)
        before_info = after_info

    history = provider.payloads[-1]["recent_history"]
    assert len(history) == 2
    assert history[-1]["delta"]["kills"] == 1
    assert history[-1]["action"] == {"move": 1, "shoot": 3,
                                      "requested_repeat": 1, "executed_repeat": 1}
    assert "reasoning" not in json.dumps(history).lower()
    agent.reset_episode()
    assert agent.history == []
    agent.history_window = 0
    agent.record_transition(before_obs=obs_before, before_info=before_info,
        action=action, after_obs=obs_before, after_info=before_info,
        grade={"status": "running", "reason": None}, executed_repeat=1)
    assert agent.history == []


def test_provider_failure_counts_the_attempt_in_agent_usage():
    class FailedProvider:
        def call_tool(self, *_args, **_kwargs):
            raise ProviderError("transport_error")

    task = load_task(TASK_DIR / "kill_target.json")
    agent = TaskAgent(FailedProvider())
    with pytest.raises(ProviderError):
        agent.decide(task, np.zeros(76), {}, decision_index=0)
    assert agent.usage["model_requests"] == 1
    assert agent.usage["model_latency_seconds"] >= 0
