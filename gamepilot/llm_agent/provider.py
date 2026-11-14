"""Ollama and OpenAI-compatible chat-completions transport."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from urllib.parse import urlsplit, urlunsplit
import urllib.error
import urllib.request


class ProviderError(RuntimeError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    model: str
    base_url: str
    api_key: str | None = None
    timeout_seconds: float = 90.0
    max_completion_tokens: int = 768

    @property
    def safe_base_url(self) -> str:
        parts = urlsplit(self.base_url)
        hostname = parts.hostname or ""
        if ":" in hostname:
            hostname = f"[{hostname}]"
        host = hostname
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))

    @classmethod
    def from_env(cls) -> "ProviderSettings":
        provider = os.getenv("GAMEPILOT_LLM_PROVIDER", "ollama").strip().lower()
        if provider not in {"ollama", "openai_compatible"}:
            raise ValueError("GAMEPILOT_LLM_PROVIDER must be ollama or openai_compatible")
        model = os.getenv("GAMEPILOT_LLM_MODEL", "").strip()
        if not model:
            raise ValueError("Set GAMEPILOT_LLM_MODEL to the installed or hosted model name")
        default_url = "http://127.0.0.1:11434" if provider == "ollama" else ""
        base_url = os.getenv("GAMEPILOT_LLM_BASE_URL", default_url).strip().rstrip("/")
        if not base_url:
            raise ValueError("Set GAMEPILOT_LLM_BASE_URL for openai_compatible")
        api_key = os.getenv("GAMEPILOT_LLM_API_KEY") or None
        try:
            timeout_seconds = float(os.getenv("GAMEPILOT_LLM_TIMEOUT_SECONDS", "90"))
        except ValueError:
            raise ValueError("GAMEPILOT_LLM_TIMEOUT_SECONDS must be a number") from None
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 600:
            raise ValueError("GAMEPILOT_LLM_TIMEOUT_SECONDS must be between 1 and 600")
        try:
            max_completion_tokens = int(os.getenv("GAMEPILOT_LLM_MAX_COMPLETION_TOKENS", "768"))
        except ValueError:
            raise ValueError("GAMEPILOT_LLM_MAX_COMPLETION_TOKENS must be an integer") from None
        if not 64 <= max_completion_tokens <= 8192:
            raise ValueError("GAMEPILOT_LLM_MAX_COMPLETION_TOKENS must be between 64 and 8192")
        return cls(provider, model, base_url, api_key, timeout_seconds, max_completion_tokens)


@dataclass(frozen=True)
class ChatResult:
    tool_name: str | None
    arguments: object
    assistant_message: dict
    usage: dict[str, int]


class ChatProvider:
    def __init__(self, settings: ProviderSettings):
        self.settings = settings

    def call_tool(self, messages: list[dict], *, max_repeat: int) -> ChatResult:
        if self.settings.provider == "ollama":
            url = self.settings.base_url
            url += "/chat" if url.endswith("/api") else "/api/chat"
            payload = {"model": self.settings.model, "messages": messages,
                       "stream": False, "think": False,
                       "format": self._action_schema(max_repeat),
                       "options": {"num_predict": self.settings.max_completion_tokens}}
        else:
            tool = {"type": "function", "function": {
                "name": "step_game",
                "description": "Apply one bounded batch of movement and firing in the current game state.",
                "parameters": self._action_schema(max_repeat)}}
            url = self.settings.base_url
            if url.endswith("/v1"):
                url += "/chat/completions"
            elif not url.endswith("/chat/completions"):
                url += "/v1/chat/completions"
            tool_choice = {"type": "function", "function": {"name": "step_game"}}
            payload = {"model": self.settings.model, "messages": messages, "tools": [tool],
                       "tool_choice": tool_choice,
                       "max_tokens": self.settings.max_completion_tokens, "stream": False}
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = "Bearer " + self.settings.api_key
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            error.close()
            raise ProviderError("http_error") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError("transport_error") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError("invalid_response_json") from None
        return self._parse(envelope)

    def _parse(self, envelope: object) -> ChatResult:
        if not isinstance(envelope, dict):
            raise ProviderError("invalid_response_shape")
        if self.settings.provider == "ollama":
            message = envelope.get("message")
            if not isinstance(message, dict):
                raise ProviderError("missing_message")
            content = message.get("content", "")
            if not isinstance(content, str):
                raise ProviderError("invalid_message_content")
            usage = self._usage(envelope.get("prompt_eval_count", 0), envelope.get("eval_count", 0))
            normalized = {"role": "assistant", "content": content}
            try:
                arguments = json.loads(content)
            except json.JSONDecodeError:
                # Let TaskAgent apply its single bounded repair attempt.
                arguments = content
            return ChatResult("step_game", arguments, normalized, usage)
        else:
            choices = envelope.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ProviderError("missing_choices")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ProviderError("missing_message")
            normalized = message
            usage_data = envelope.get("usage") or {}
            usage = self._usage(usage_data.get("prompt_tokens", 0), usage_data.get("completion_tokens", 0))
        calls = normalized.get("tool_calls") or []
        if not isinstance(calls, list):
            raise ProviderError("invalid_tool_calls")
        if len(calls) != 1:
            return ChatResult(None, None, normalized, usage)
        if not isinstance(calls[0], dict) or not isinstance(calls[0].get("function"), dict):
            raise ProviderError("invalid_tool_call_shape")
        function = calls[0]["function"]
        name = function.get("name")
        raw_args = function.get("arguments")
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            arguments = raw_args
        return ChatResult(name if isinstance(name, str) else None, arguments, normalized, usage)

    @staticmethod
    def _usage(prompt, completion):
        try:
            values = {"prompt_tokens": int(prompt or 0), "completion_tokens": int(completion or 0)}
        except (TypeError, ValueError, OverflowError):
            raise ProviderError("invalid_usage") from None
        if any(value < 0 for value in values.values()):
            raise ProviderError("invalid_usage")
        return values

    @staticmethod
    def _action_schema(max_repeat: int) -> dict:
        return {"type": "object", "additionalProperties": False,
                "properties": {
                    "move": {"type": "integer", "minimum": 0, "maximum": 8},
                    "shoot": {"type": "integer", "minimum": 0, "maximum": 8},
                    "repeat": {"type": "integer", "minimum": 1, "maximum": max_repeat}},
                "required": ["move", "shoot", "repeat"]}
