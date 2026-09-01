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
import re
import time
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


class LLMBudgetExceeded(UpstreamLLMError):
    """The provider's per-minute token budget is spent.

    A subclass rather than a flag because this is the one upstream failure that
    is *expected* on a small plan and that the person asking can act on - wait
    a moment and ask again. The API turns it into a 429 with its own slug so
    the assistant panel can say "busy" instead of "unavailable", which are very
    different sentences to read.
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
    reasoning_effort: str | None = None,
) -> Completion:
    """One round trip to the provider, retried once if the budget resets soon.

    Temperature defaults to zero: this assistant reports numbers that came out
    of a database, and creative variation in that is a defect, not a feature.

    `max_tokens` is not only a cap on the answer - providers charge it against
    the per-minute token allowance the moment the request is made, whether or
    not it is used. Asking for 2,500 tokens to emit a two-line tool call spends
    2,500 tokens of budget, so the agent loop passes a small figure for
    tool-selection rounds and the full figure only when prose is expected.

    `reasoning_effort` is honoured by reasoning models (Groq's gpt-oss family
    among them) and ignored by the rest. Choosing which tool to call is not
    hard reasoning; writing the final answer sometimes is.
    """
    client = get_client()
    request: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.AGENT_MAX_TOKENS,
    }
    if reasoning_effort:
        request["reasoning_effort"] = reasoning_effort
    if tools:
        request["tools"] = tools
        request["tool_choice"] = "auto"

    response = _create_with_backoff(client, request)

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


# How long we are willing to hold a request open waiting for the provider's
# token bucket to refill. A per-minute allowance refills continuously, so the
# wait is usually a second or two; anything longer is better reported than
# waited out, because the browser is holding a spinner the whole time.
_MAX_BACKOFF_SECONDS = 8.0
_RETRY_HINT = re.compile(r"try again in ([0-9.]+)\s*(ms|s)\b", re.IGNORECASE)


def _create_with_backoff(client: OpenAI, request: dict[str, Any]):
    """Issue the request, waiting out one short rate-limit window if offered.

    The SDK's own retries do not help here: it backs off on a fixed schedule
    that ignores the provider's stated reset time, so it either waits far
    longer than needed or gives up just before the bucket refills. The provider
    tells us exactly how long to wait, so we use that.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return client.chat.completions.create(**request)
        except APITimeoutError as exc:
            raise UpstreamLLMError(
                f"The language model did not respond within "
                f"{settings.LLM_TIMEOUT_SECONDS:.0f} seconds."
            ) from exc
        except APIConnectionError as exc:
            raise UpstreamLLMError(
                f"Could not reach the language model provider at "
                f"{settings.LLM_BASE_URL}."
            ) from exc
        except APIStatusError as exc:
            detail = _provider_message(exc)
            if exc.status_code != 429:
                # Pass the provider's own message through: "model decommissioned"
                # is exactly what the operator needs to see.
                raise UpstreamLLMError(
                    f"The language model provider returned {exc.status_code}: {detail}"
                ) from exc

            wait = _retry_after_seconds(exc, detail)
            if attempt == 1 and wait is not None and wait <= _MAX_BACKOFF_SECONDS:
                log.info("llm_rate_limited_retrying", extra={"wait_seconds": wait})
                time.sleep(wait)
                continue
            raise LLMBudgetExceeded(detail) from exc
        except Exception as exc:  # noqa: BLE001 - any SDK failure is upstream
            raise UpstreamLLMError(f"The language model call failed: {exc}") from exc


def _retry_after_seconds(exc: APIStatusError, detail: str) -> float | None:
    """How long the provider says to wait, from the header or its own message."""
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_HINT.search(detail)
    if match:
        value = float(match.group(1))
        return value / 1000 if match.group(2).lower() == "ms" else value
    return None


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
