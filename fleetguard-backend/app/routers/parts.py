from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEFAULT_TOP_N_SIGNALS, MIN_CORRELATION
from app.db import engine as db_engine
from app.db import get_db
from app.models import JobCard, Part
from app.schemas import CorrelationsOut, PartHistoryOut, PartOut
from app.services import features
from app.services.agent_tools import part_life_stats
from app.services.correlation import correlate_part

router = APIRouter(prefix="/api/parts", tags=["parts"])


def _get_part(db: Session, part_code: str) -> Part:
    part = db.get(Part, part_code)
    if part is None:
        raise HTTPException(status_code=404, detail=f"unknown part_code '{part_code}'")
    return part


@router.get("", response_model=list[PartOut])
def list_parts(db: Session = Depends(get_db)):
    return db.execute(select(Part).order_by(Part.category, Part.part_name)).scalars().all()


@router.get("/{part_code}/history", response_model=PartHistoryOut)
def part_history(part_code: str, db: Session = Depends(get_db)):
    part = _get_part(db, part_code)

    rows = db.execute(
        select(JobCard).where(
            JobCard.part_code == part_code, JobCard.event_type == "failure"
        )
    ).scalars().all()

    if not rows:
        return {
            "part_code": part.part_code,
            "part_name": part.part_name,
            "historical_failures": 0,
            "affected_vins": 0,
            "avg_mileage_at_failure": 0,
            "monthly_counts": [],
        }

    buckets: dict[str, int] = {}
    for r in rows:
        key = r.failure_date.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0) + 1

    stats = part_life_stats(db, part_code)

    return {
        "part_code": part.part_code,
        "part_name": part.part_name,
        "historical_failures": len(rows),
        "affected_vins": len({r.vin for r in rows}),
        "avg_mileage_at_failure": stats["median_km_on_part_at_failure"],
        "monthly_counts": [
            {"month": m, "count": c} for m, c in sorted(buckets.items())
        ][-12:],
    }


@router.get("/{part_code}/correlations", response_model=CorrelationsOut)
def part_correlations(part_code: str, db: Session = Depends(get_db)):
    _get_part(db, part_code)
    feats = features.build_features(db_engine)
    if feats.empty:
        raise HTTPException(status_code=409, detail="no data; run scripts.generate_data")

    signals = correlate_part(feats, part_code)
    default = [
        c["signal"] for c in signals if c["correlation"] >= MIN_CORRELATION
    ][:DEFAULT_TOP_N_SIGNALS]
    total = sum(c["correlation"] for c in signals if c["signal"] in default) or 1.0

    for c in signals:
        c["included"] = c["signal"] in default
        c["weight"] = round(c["correlation"] / total, 4) if c["included"] else 0.0

    return {
        "part_code": part_code,
        "method": "point-biserial correlation, cross-checked with standardised logistic regression",
        "signals": signals,
    }