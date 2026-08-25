from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SIGNAL_LABELS, URGENT_RUL_DAYS
from app.db import get_db
from app.models import Part, Prediction, Rule, Vehicle
from app.services import engine
from app.schemas import PredictionDetailOut, VehicleRiskOut

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


def vehicle_rows(db: Session) -> list[dict]:
    preds = db.execute(select(Prediction)).scalars().all()
    parts = {p.part_code: p.part_name for p in db.execute(select(Part)).scalars().all()}
    vehicles = {v.vin: v for v in db.execute(select(Vehicle)).scalars().all()}

    grouped: dict[str, list] = {}
    for p in preds:
        grouped.setdefault(p.vin, []).append(p)

    out = []
    for vin, rows in grouped.items():
        veh = vehicles.get(vin)
        tier_rank = {"RED": 0, "AMBER": 1, "GREEN": 2}
        rows.sort(key=lambda r: (tier_rank.get(r.risk_tier, 3), -r.failure_probability))
        top = rows[0]
        out.append(
            {
                "vin": vin,
                "model": veh.model if veh else "",
                "region": veh.region if veh else "",
                "fleet_operator": veh.fleet_operator if veh else "",
                "parts_tracked": len(rows),
                "top_probability": round(top.failure_probability, 4),
                "top_part": parts.get(top.part_code, top.part_code),
                "min_rul_days": min(r.rul_days for r in rows),
                "risk_tier": top.risk_tier,
                "parts": [
                    {
                        "part_code": r.part_code,
                        "part_name": parts.get(r.part_code, r.part_code),
                        "failure_probability": round(r.failure_probability, 4),
                        "rul_days": r.rul_days,
                        "risk_tier": r.risk_tier,
                    }
                    for r in rows
                ],
            }
        )
    return out


@router.get("", response_model=list[VehicleRiskOut])
def list_predictions(
    status: str | None = Query(None, pattern="^(RED|AMBER|GREEN)$"),
    search: str | None = None,
    sort: str = Query("probability", pattern="^(probability|rul|vin)$"),
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

    if sort == "probability":
        rows.sort(key=lambda r: r["top_probability"], reverse=True)
    elif sort == "rul":
        rows.sort(key=lambda r: r["min_rul_days"])
    else:
        rows.sort(key=lambda r: r["vin"])

    return rows[offset : offset + limit]


@router.get("/{vin}/{part_code}", response_model=PredictionDetailOut)
def prediction_detail(vin: str, part_code: str, db: Session = Depends(get_db)):
    pred = db.execute(
        select(Prediction).where(Prediction.vin == vin, Prediction.part_code == part_code)
    ).scalar_one_or_none()
    if pred is None:
        raise HTTPException(status_code=404, detail=f"no prediction for {vin} / {part_code}")

    veh = db.get(Vehicle, vin)
    part = db.get(Part, part_code)
    rule = db.get(Rule, pred.rule_id) if pred.rule_id else None

    escalated = engine.is_escalated(pred.failure_probability, pred.rul_days)
    crosscheck = (
        f"Cross-checked against RUL for the same VIN and part: {pred.health_index:.0f}% "
        f"component health, {pred.rul_days} days remaining. Same signals, same vehicle "
        f"- this probability is derived from that health index, not a second opinion."
    )

    return {
        "vin": vin,
        "model": veh.model if veh else "",
        "region": veh.region if veh else "",
        "part_code": part_code,
        "part_name": part.part_name if part else part_code,
        "failure_probability": round(pred.failure_probability, 4),
        "risk_tier": pred.risk_tier,
        "escalated": escalated,
        "escalation_reason": (
            f"Escalated to RED: {pred.rul_days} days of useful life remaining, "
            f"inside the {URGENT_RUL_DAYS}-day intervention window."
            if escalated
            else None
        ),
        "health_index": pred.health_index,
        "window_from_days": pred.window_from_days,
        "window_to_days": pred.window_to_days,
        "top_signal": pred.top_signal,
        "top_signal_label": SIGNAL_LABELS.get(pred.top_signal, pred.top_signal),
        "top_signal_share": round(pred.top_signal_share, 4),
        "drivers": pred.drivers,
        "trend": pred.trend,
        "rule_id": pred.rule_id,
        "formula": rule.formula if rule else None,
        "crosscheck": crosscheck,
    }