"""Request and response models for the two agents (spec section 7)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class ChatTurn(ApiModel):
    role: str = Field(description="user | assistant")
    content: str


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] | None = Field(
        default=None,
        description=(
            "Earlier turns of this conversation. Only the text is replayed; tool "
            "results from previous turns are not, so a figure is never quoted "
            "from a stale lookup."
        ),
    )


class Citation(ApiModel):
    """One tool call, with the raw result the answer was built from.

    The UI's citation chips expand into `result`. That is what makes the
    grounding claim checkable by the reader instead of merely asserted.
    """

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    duration_ms: float


class ChatResponse(ApiModel):
    reply: str
    tools_used: list[str]
    data_cited: list[Citation]
    rounds: int = Field(description="Tool-calling rounds used.")
    truncated: bool = Field(
        description="The model ran out of output tokens before finishing."
    )
    hit_round_limit: bool = Field(
        description="The tool budget was exhausted; the reply was written from what had been gathered."
    )


class ChatCapabilities(ApiModel):
    """What the assistant can do, for the panel's empty state."""

    available: bool = Field(description="False when no LLM key is configured.")
    model: str
    max_tool_rounds: int
    tools: list[dict[str, str]]
    suggested_questions: list[str]
    grounding: str


class DraftRequest(ApiModel):
    vin: str
    part: str = Field(description="Component name or part code.")
    audience: str = Field(description="vendor | fleet_owner")


class DraftResponse(ApiModel):
    message: str
    audience: str
    vin: str
    part: str
    facts: dict[str, Any] = Field(
        description="Every fact the model was given. It had no tools, so it had nothing else."
    )
    truncated: bool
