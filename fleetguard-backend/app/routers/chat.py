from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import GROQ_API_KEY, GROQ_MODEL
from app.db import get_db
from app.services.agent import (
    SUGGESTED_QUESTIONS,
    AgentUnavailable,
    run_action_agent,
    run_insight_agent,
)
from app.services.agent_tools import TOOL_SCHEMAS

router = APIRouter(prefix="/api/chat", tags=["agent"])


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)


class DraftRequest(BaseModel):
    vin: str
    part: str
    audience: str = "fleet_owner"


@router.get("")
def chat_info():
    return {
        "agent_enabled": bool(GROQ_API_KEY),
        "model": GROQ_MODEL,
        "tools": [
            {"name": t["function"]["name"], "description": t["function"]["description"]}
            for t in TOOL_SCHEMAS
        ],
        "suggested_questions": SUGGESTED_QUESTIONS,
    }


@router.post("")
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    try:
        return run_insight_agent(
            db, payload.message, [t.model_dump() for t in payload.history]
        )
    except AgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{type(exc).__name__}: {exc}",
        )


@router.post("/draft")
def draft(payload: DraftRequest, db: Session = Depends(get_db)):
    try:
        result = run_action_agent(db, payload.vin, payload.part, payload.audience)
    except AgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{type(exc).__name__}: {exc}",
        )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result