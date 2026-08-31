"""The only module in the codebase that knows which LLM provider is in use.

Spec section 7 requires the provider to be isolated so it can be swapped by
changing an environment variable. Groq speaks the OpenAI wire protocol, so the
official OpenAI SDK pointed at `LLM_BASE_URL` is the whole integration —
moving to OpenAI, Together or a local vLLM is a change to two env vars and
nothing else.

Everything above this module deals in plain dictionaries and the small
`Completion` record below. Nothing else imports `openai`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.config import settings
from app.logging_config import get_logger

log = get_logger("fleetguard.llm")


class UpstreamLLMError(RuntimeError):
    """The provider failed. Surfaces as a 502 carrying the provider's message.

    Defined here rather than in `main` so that services never import the web
    layer; `main` imports it from here to register the handler.
    """


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Completion:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def truncated(self) -> bool:
        """Whether the model ran out of room mid-answer.

        Reasoning models spend tokens internally before emitting anything, so
        this is a real possibility rather than a theoretical one, and the UI
        needs to be able to say so instead of showing a sentence that stops.
        """
        return self.finish_reason == "length"


_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.LLM_API_KEY:
            raise UpstreamLLMError(
                "No LLM_API_KEY is configured, so the assistant is unavailable. "
                "Set it in .env and restart."
            )
        _client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=2,
        )
    return _client


def is_configured() -> bool:
    return bool(settings.LLM_API_KEY)


def complete(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Completion:
    """One round trip to the provider.

    Temperature defaults to zero: this assistant reports numbers that came out
    of a database, and creative variation in that is a defect, not a feature.
    """
    client = get_client()
    request: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.AGENT_MAX_TOKENS,
    }
    if tools:
        request["tools"] = tools
        request["tool_choice"] = "auto"

    try:
        response = client.chat.completions.create(**request)
    except APITimeoutError as exc:
        raise UpstreamLLMError(
            f"The language model did not respond within "
            f"{settings.LLM_TIMEOUT_SECONDS:.0f} seconds."
        ) from exc
    except APIConnectionError as exc:
        raise UpstreamLLMError(
            f"Could not reach the language model provider at {settings.LLM_BASE_URL}."
        ) from exc
    except APIStatusError as exc:
        # Pass the provider's own message through: "model decommissioned" or
        # "rate limit exceeded" is exactly what the operator needs to see.
        raise UpstreamLLMError(
            f"The language model provider returned {exc.status_code}: "
            f"{_provider_message(exc)}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any SDK failure is an upstream failure
        raise UpstreamLLMError(f"The language model call failed: {exc}") from exc

    choice = response.choices[0]
    message = choice.message

    calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        calls.append(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments, call.function.name),
            )
        )

    usage = response.usage
    return Completion(
        content=message.content or "",
        tool_calls=calls,
        finish_reason=choice.finish_reason or "stop",
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


def _parse_arguments(raw: str | None, tool_name: str) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string and are not always valid JSON.

    A malformed argument blob must not take the request down: the loop reports
    it back to the model as a tool error, which it can then correct on the next
    round.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("tool_arguments_unparseable", extra={"tool": tool_name})
        return {"__parse_error__": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _provider_message(exc: APIStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
        return str(body)
    except Exception:  # noqa: BLE001 - a non-JSON error body is still worth showing
        return exc.message or "no message supplied"


def reset_client() -> None:
    """Drop the cached client. Used by tests that change configuration."""
    global _client
    _client = None
