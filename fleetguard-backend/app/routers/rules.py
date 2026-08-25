from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import engine as db_engine
from app.db import get_db
from app.models import Part
from app.schemas import RuleOut, RuleRequest
from app.services import features
from app.services.rules_engine import active_rule, preview_rule, rule_to_dict, save_rule

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _feats():
    feats = features.build_features(db_engine)
    if feats.empty:
        raise HTTPException(status_code=409, detail="no data; run scripts.generate_data")
    return feats


def _check_part(db: Session, part_code: str) -> None:
    if db.get(Part, part_code) is None:
        raise HTTPException(status_code=404, detail=f"unknown part_code '{part_code}'")


@router.get("/{part_code}", response_model=RuleOut)
def get_active_rule(part_code: str, db: Session = Depends(get_db)):
    _check_part(db, part_code)
    rule = active_rule(db, part_code)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no active rule for '{part_code}'")
    return rule_to_dict(db, rule)


@router.post("/preview", response_model=RuleOut)
def preview(payload: RuleRequest, db: Session = Depends(get_db)):
    _check_part(db, payload.part_code)
    selected = payload.signals or None
    return preview_rule(_feats(), payload.part_code, selected)


@router.post("", response_model=RuleOut)
def deploy(payload: RuleRequest, db: Session = Depends(get_db)):
    _check_part(db, payload.part_code)
    selected = payload.signals or None
    preview = preview_rule(_feats(), payload.part_code, selected)
    rule = save_rule(db, preview)
    return rule_to_dict(db, rule)