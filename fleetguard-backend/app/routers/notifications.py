from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Notification
from app.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    audience: str | None = Query(None, pattern="^(vendor|fleet_owner)$"),
    vin: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).order_by(Notification.id.desc())
    if audience:
        stmt = stmt.where(Notification.audience == audience)
    if vin:
        stmt = stmt.where(Notification.vin == vin.upper())
    return db.execute(stmt.limit(limit).offset(offset)).scalars().all()