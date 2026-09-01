"""The assistant endpoints.

Rate limited, because these are the only endpoints that cost money per call
and the only ones where a runaway client in a demo would be noticed on an
invoice. The limit comes from `CHAT_RATE_LIMIT` and is applied per client
address.
"""

# No `from __future__ import annotations` in this module, deliberately.
# slowapi's rate-limit decorator wraps each endpoint, and the wrapper carries
# slowapi's module globals rather than this one's. With postponed annotations
# the parameter types arrive at FastAPI as strings it cannot resolve in those
# globals, so the request body and both dependencies get misread as required
# query parameters and every call 422s. Real annotation objects sidestep it.
from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.deps import CurrentScope, DbSession
from app.rate_limit import limiter
from app.schemas.chat import (
    ChatCapabilities,
    ChatRequest,
    ChatResponse,
    DraftRequest,
    DraftResponse,
)
from app.services import action_agent, agent_tools, insight_agent, llm
from app.services.action_agent import DraftError

router = APIRouter(prefix="/api/chat", tags=["assistant"])


def _require_llm() -> None:
    if not llm.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The assistant is not configured. Set LLM_API_KEY in the "
                "environment and restart the API."
            ),
        )


@router.get(
    "",
    response_model=ChatCapabilities,
    summary="What the assistant can do, and what to ask it",
)
def capabilities() -> ChatCapabilities:
    """Drives the assistant panel's empty state and its suggestion chips."""
    return ChatCapabilities(
        available=llm.is_configured(),
        model=settings.LLM_MODEL,
        max_tool_rounds=settings.AGENT_MAX_TOOL_ROUNDS,
        tools=[
            {
                "name": schema["function"]["name"],
                "description": schema["function"]["description"],
            }
            for schema in agent_tools.TOOL_SCHEMAS
        ],
        suggested_questions=insight_agent.SUGGESTED_QUESTIONS,
        grounding=(
            "Every figure in a reply comes from a tool call against your live "
            "data, listed under the answer. The assistant has no fleet data in "
            "its prompt and will say so rather than guess."
        ),
    )


@router.post(
    "",
    response_model=ChatResponse,
    summary="Ask the Insight Agent a question about the fleet",
)
@limiter.limit(settings.CHAT_RATE_LIMIT)
def chat(
    request: Request,
    payload: ChatRequest,
    db: DbSession,
    scope: CurrentScope,
) -> ChatResponse:
    """Answers using tools only, inside the caller's customer scope."""
    _require_llm()

    result = insight_agent.answer(
        db,
        scope,
        question=payload.message,
        history=[turn.model_dump() for turn in payload.history or []],
    )

    return ChatResponse(
        reply=result.reply,
        tools_used=result.tools_used,
        data_cited=[
            {
                "tool": call.tool,
                "arguments": call.arguments,
                "result": call.result,
                "duration_ms": call.duration_ms,
            }
            for call in result.data_cited
        ],
        rounds=result.rounds,
        truncated=result.truncated,
        hit_round_limit=result.hit_round_limit,
    )


@router.post(
    "/draft",
    response_model=DraftResponse,
    summary="Draft vendor or fleet-owner outreach for one component",
)
@limiter.limit(settings.CHAT_RATE_LIMIT)
def draft(
    request: Request,
    payload: DraftRequest,
    db: DbSession,
    scope: CurrentScope,
) -> DraftResponse:
    """Facts are gathered in Python first; the model only writes the prose.

    Nothing is sent anywhere. The draft comes back for a human to review, edit
    and send.
    """
    _require_llm()

    try:
        result = action_agent.draft(
            db, scope, vin=payload.vin, part=payload.part, audience=payload.audience
        )
    except DraftError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return DraftResponse(
        message=result.message,
        audience=result.audience,
        vin=result.vin,
        part=result.part,
        facts=result.facts,
        truncated=result.truncated,
    )
