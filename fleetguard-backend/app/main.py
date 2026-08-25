from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.routers import chat, notifications, overview, parts, predictions, rul, rules
from app.config import CORS_ORIGINS
from app.db import engine
from app.routers import overview, parts, predictions, rul, rules

app = FastAPI(
    title="FleetGuard AI",
    description="Predictive Failure Engine for commercial vehicle fleets",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(rul.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(overview.router)
app.include_router(parts.router)
app.include_router(rules.router)
app.include_router(predictions.router)
app.include_router(rul.router)


@app.get("/api/health", tags=["system"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "degraded", "database": str(exc)}