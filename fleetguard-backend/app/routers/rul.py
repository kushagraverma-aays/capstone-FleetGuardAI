from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import FAILURE_THRESHOLD_INDEX
from app.db import get_db
from app.models import Part, Prediction, Vehicle
from app.routers.predictions import vehicle_rows
from app.schemas import RulDetailOut, VehicleRiskOut

router = APIRouter(prefix="/api/rul", tags=["rul"])


@router.get("", response_model=list[VehicleRiskOut])
def list_rul(
    status: str | None = Query(None, pattern="^(RED|AMBER|GREEN)$"),
    search: str | None = None,
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = vehicle_rows(db)
    if status:
        rows = [r for r in rows if r["risk_tier"] == status]
    if search:
        term = search.lower()
        rows = [r for r in rows if term in r["vin"].lower() or term in r["model"].lower()]
    rows.sort(key=lambda r: r["min_rul_days"])
    return rows[offset : offset + limit]


@router.get("/{vin}/{part_code}", response_model=RulDetailOut)
def rul_detail(vin: str, part_code: str, db: Session = Depends(get_db)):
    pred = db.execute(
        select(Prediction).where(Prediction.vin == vin, Prediction.part_code == part_code)
    ).scalar_one_or_none()
    if pred is None:
        raise HTTPException(status_code=404, detail=f"no RUL estimate for {vin} / {part_code}")

    veh = db.get(Vehicle, vin)
    part = db.get(Part, part_code)

    crosscheck = (
        f"Cross-checked against Failure Probability for the same VIN and part: "
        f"{pred.failure_probability:.0%} probability, window {pred.window_from_days}-"
        f"{pred.window_to_days} days. The {pred.health_index:.0f}% health index here is "
        f"exactly what that probability is derived from."
    )

    return {
        "vin": vin,
        "model": veh.model if veh else "",
        "part_code": part_code,
        "part_name": part.part_name if part else part_code,
        "rul_km": pred.rul_km,
        "rul_days": pred.rul_days,
        "design_life_km": part.design_life_km if part else 0,
        "model_confidence": pred.model_confidence,
        "degradation_trend": pred.degradation_trend,
        "health_index": pred.health_index,
        "failure_threshold": FAILURE_THRESHOLD_INDEX,
        "curve": pred.curve,
        "crosscheck": crosscheck,
    }