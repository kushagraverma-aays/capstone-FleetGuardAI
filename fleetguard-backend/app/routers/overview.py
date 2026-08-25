from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import RED_THRESHOLD
from app.db import engine as db_engine
from app.db import get_db
from app.models import Prediction, RuleSignal
from app.schemas import OverviewOut
from app.services import features
from app.services.correlation import fleet_precursors

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview", response_model=OverviewOut)
def get_overview(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Prediction)) or 0
    high = db.scalar(
        select(func.count()).select_from(Prediction).where(
            Prediction.failure_probability >= RED_THRESHOLD
        )
    ) or 0
    urgent = db.scalar(
        select(func.count()).select_from(Prediction).where(Prediction.rul_days <= 30)
    ) or 0
    validated = db.scalar(select(func.count()).select_from(RuleSignal)) or 0
    latest = db.scalar(select(func.max(Prediction.computed_date)))

    feats = features.build_features(db_engine)
    precursors = fleet_precursors(feats) if not feats.empty else []

    return {
        "components_under_watch": total,
        "high_failure_probability": high,
        "inside_30day_rul": urgent,
        "precursor_patterns_validated": validated,
        "action_threshold": RED_THRESHOLD,
        "top_precursor_signals": precursors,
        "computed_date": latest.isoformat() if latest else None,
    }