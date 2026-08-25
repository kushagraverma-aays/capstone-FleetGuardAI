from __future__ import annotations

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import (
    BACKTEST_EPISODE_DAYS,
    BACKTEST_LOOKBACK_DAYS,
    DEFAULT_TOP_N_SIGNALS,
    MIN_CORRELATION,
    RED_THRESHOLD,
    SIGNAL_LABELS,
)
from app.models import Rule, RuleSignal
from app.services import engine as scoring
from app.services.correlation import correlate_part


def normalise_weights(correlations: list[dict], selected: list[str]) -> list[dict]:
    chosen = [c for c in correlations if c["signal"] in selected]
    total = sum(c["correlation"] for c in chosen)
    if total <= 0:
        share = 1.0 / max(len(chosen), 1)
        return [{**c, "weight": round(share, 4)} for c in chosen]
    return [{**c, "weight": round(c["correlation"] / total, 4)} for c in chosen]


def build_formula(weighted: list[dict]) -> str:
    terms = " + ".join(f"{w['weight']:.2f} {w['signal']}" for w in weighted)
    return f"failure_probability = {terms}"


def backtest(features: pd.DataFrame, part_code: str, weights: dict[str, float]) -> dict:
    part_df = features[features["part_code"] == part_code]
    if part_df.empty:
        return {"precision": 0.0, "coverage": 0.0, "days_to_alert": 0, "sample_failures": 0}

    scored = scoring.score_frame(part_df, weights)
    scored = scored.sort_values(["vin", "week_start_date"])

    failures = scored.dropna(subset=["next_failure_date"])[["vin", "next_failure_date"]]
    failures = failures.drop_duplicates()
    total_failures = len(failures)

    flagged = scored[scored["failure_probability"] >= RED_THRESHOLD].copy()
    if flagged.empty or total_failures == 0:
        return {
            "precision": 0.0,
            "coverage": 0.0,
            "days_to_alert": 0,
            "sample_failures": total_failures,
        }

    episodes = []
    for vin, group in flagged.groupby("vin"):
        last_kept = None
        for row in group.sort_values("week_start_date").itertuples():
            if last_kept is None or (row.week_start_date - last_kept).days > BACKTEST_EPISODE_DAYS:
                episodes.append(row)
                last_kept = row.week_start_date

    true_positives = 0
    caught = set()
    lead_times = []
    for ep in episodes:
        if pd.isna(ep.next_failure_date):
            continue
        gap = (ep.next_failure_date - ep.week_start_date).days
        if 0 <= gap <= BACKTEST_LOOKBACK_DAYS:
            true_positives += 1
            key = (ep.vin, ep.next_failure_date)
            if key not in caught:
                caught.add(key)
                lead_times.append(gap)

    precision = true_positives / len(episodes) if episodes else 0.0
    coverage = len(caught) / total_failures if total_failures else 0.0
    days_to_alert = int(pd.Series(lead_times).median()) if lead_times else 0

    return {
        "precision": round(precision, 4),
        "coverage": round(coverage, 4),
        "days_to_alert": days_to_alert,
        "sample_failures": total_failures,
    }


def preview_rule(
    features: pd.DataFrame, part_code: str, selected: list[str] | None = None
) -> dict:
    correlations = correlate_part(features, part_code)

    if selected is None:
        selected = [
            c["signal"] for c in correlations if c["correlation"] >= MIN_CORRELATION
        ][:DEFAULT_TOP_N_SIGNALS]
    if not selected:
        selected = [correlations[0]["signal"]]

    weighted = normalise_weights(correlations, selected)
    weights = {w["signal"]: w["weight"] for w in weighted}
    metrics = backtest(features, part_code, weights)

    return {
        "part_code": part_code,
        "formula": build_formula(weighted),
        "signals": [
            {
                "signal": w["signal"],
                "label": SIGNAL_LABELS.get(w["signal"], w["signal"]),
                "correlation": w["correlation"],
                "correlation_pct": w["correlation_pct"],
                "weight": w["weight"],
                "included": True,
            }
            for w in weighted
        ],
        "excluded": [
            {
                "signal": c["signal"],
                "label": c["label"],
                "correlation": c["correlation"],
                "correlation_pct": c["correlation_pct"],
                "weight": 0.0,
                "included": False,
            }
            for c in correlations
            if c["signal"] not in selected
        ],
        **metrics,
    }


def save_rule(db: Session, preview: dict) -> Rule:
    db.execute(
        update(Rule)
        .where(Rule.part_code == preview["part_code"], Rule.is_active == True)  # noqa: E712
        .values(is_active=False)
    )

    rule = Rule(
        part_code=preview["part_code"],
        formula=preview["formula"],
        precision=preview["precision"],
        coverage=preview["coverage"],
        days_to_alert=preview["days_to_alert"],
        sample_failures=preview["sample_failures"],
        is_active=True,
    )
    db.add(rule)
    db.flush()

    for s in preview["signals"]:
        db.add(
            RuleSignal(
                rule_id=rule.rule_id,
                signal=s["signal"],
                correlation=s["correlation"],
                weight=s["weight"],
                included=True,
            )
        )
    db.commit()
    db.refresh(rule)
    return rule


def active_rule(db: Session, part_code: str) -> Rule | None:
    return db.execute(
        select(Rule).where(Rule.part_code == part_code, Rule.is_active == True)  # noqa: E712
    ).scalar_one_or_none()


def rule_weights(db: Session, rule: Rule) -> dict[str, float]:
    rows = db.execute(
        select(RuleSignal).where(RuleSignal.rule_id == rule.rule_id, RuleSignal.included == True)  # noqa: E712
    ).scalars().all()
    return {r.signal: r.weight for r in rows}


def rule_to_dict(db: Session, rule: Rule) -> dict:
    rows = db.execute(select(RuleSignal).where(RuleSignal.rule_id == rule.rule_id)).scalars().all()
    return {
        "rule_id": rule.rule_id,
        "part_code": rule.part_code,
        "formula": rule.formula,
        "precision": rule.precision,
        "coverage": rule.coverage,
        "days_to_alert": rule.days_to_alert,
        "sample_failures": rule.sample_failures,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "signals": [
            {
                "signal": r.signal,
                "label": SIGNAL_LABELS.get(r.signal, r.signal),
                "correlation": r.correlation,
                "correlation_pct": round(r.correlation * 100, 1),
                "weight": r.weight,
                "included": r.included,
            }
            for r in rows
        ],
    }