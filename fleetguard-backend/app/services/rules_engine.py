"""Rule builder, versioning and deployment (spec section 6.3).

A rule is just a normalised set of signal weights for one component:

    weight_i = correlation_i / sum(selected correlations)

so the weights always sum to 1.00 and the resulting stress term stays on a
0-1 scale, which is what lets the health index treat it as a percentage.

Deploying a new rule deactivates the previous one rather than overwriting it.
Keeping the history means a prediction made last month can still be explained
by the rule that actually produced it.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import DEFAULT_TOP_N_SIGNALS, MIN_CORRELATION, SIGNAL_LABELS
from app.models import AuditLog, JobCard, Rule, RuleSignal
from app.services.backtest import BacktestResult, backtest_rule
from app.services.correlation import SignalCorrelation, rank_signals


def default_selection(correlations: list[SignalCorrelation]) -> list[str]:
    """The signals the wizard pre-ticks: the strongest few that clear the floor."""
    usable = [c for c in correlations if c.correlation >= MIN_CORRELATION]
    return [c.signal for c in usable[:DEFAULT_TOP_N_SIGNALS]]


def normalise_weights(
    correlations: list[SignalCorrelation],
    selected: list[str],
) -> dict[str, float]:
    """Turn correlations for the selected signals into weights summing to 1.00.

    Rounding is done deliberately: the residual is folded into the largest
    weight so the total is exactly 1.0 rather than 0.9999, because the UI
    displays the sum and a user who sees 0.9999 stops trusting the number.
    """
    by_signal = {c.signal: c.correlation for c in correlations}
    chosen = [s for s in selected if by_signal.get(s, 0.0) > 0.0]
    if not chosen:
        return {}

    total = sum(by_signal[s] for s in chosen)
    if total <= 0:
        return {}

    weights = {s: round(by_signal[s] / total, 4) for s in chosen}
    residual = round(1.0 - sum(weights.values()), 4)
    if residual:
        heaviest = max(weights, key=lambda s: weights[s])
        weights[heaviest] = round(weights[heaviest] + residual, 4)
    return dict(sorted(weights.items(), key=lambda kv: kv[1], reverse=True))


def format_formula(weights: dict[str, float]) -> str:
    """Human-readable formula, e.g.

    failure_probability = 0.28 coolant_temp_variance + 0.27 overload_duty_share
    """
    if not weights:
        return "failure_probability = 0"
    terms = [f"{weight:.2f} {signal}" for signal, weight in weights.items()]
    return "failure_probability = " + " + ".join(terms)


def describe_weights(
    weights: dict[str, float],
    correlations: list[SignalCorrelation],
) -> list[dict]:
    """Weights plus their provenance, for the API and the Rule Studio."""
    by_signal = {c.signal: c for c in correlations}
    return [
        {
            "signal": signal,
            "label": SIGNAL_LABELS.get(signal, signal),
            "weight": weight,
            "share": round(weight * 100, 1),
            "correlation": by_signal[signal].correlation if signal in by_signal else 0.0,
        }
        for signal, weight in weights.items()
    ]


def preview_rule(
    features: pd.DataFrame,
    failures: pd.DataFrame,
    part_code: str,
    selected: list[str] | None = None,
) -> dict:
    """Recompute weights and back-test metrics without writing anything.

    This is what the Rule Studio calls on every signal toggle, so it must stay
    a pure computation over frames the caller already has.
    """
    part_features = features[features["part_code"] == part_code]
    part_failures = failures[failures["part_code"] == part_code]

    correlations = rank_signals(part_features)
    if selected is None:
        selected = default_selection(correlations)

    weights = normalise_weights(correlations, selected)
    metrics = (
        backtest_rule(part_features, part_failures, weights)
        if weights
        else BacktestResult(0.0, 0.0, 0.0, 0, 0, 0, 0, 0.0)
    )

    return {
        "part_code": part_code,
        "selected_signals": list(weights.keys()),
        "weights": describe_weights(weights, correlations),
        "formula": format_formula(weights),
        "correlations": [c.to_dict() for c in correlations],
        "metrics": metrics.to_dict(),
    }


def active_rule(session: Session, part_code: str) -> Rule | None:
    return session.execute(
        select(Rule)
        .where(Rule.part_code == part_code, Rule.is_active.is_(True))
        .order_by(Rule.version.desc())
    ).scalars().first()


def rule_history(session: Session, part_code: str) -> list[Rule]:
    return list(
        session.execute(
            select(Rule).where(Rule.part_code == part_code).order_by(Rule.version.desc())
        ).scalars()
    )


def rule_weights(session: Session, rule: Rule) -> dict[str, float]:
    """The included signal weights of a persisted rule."""
    rows = session.execute(
        select(RuleSignal.signal, RuleSignal.weight).where(
            RuleSignal.rule_id == rule.rule_id, RuleSignal.included.is_(True)
        )
    ).all()
    return {signal: float(weight) for signal, weight in rows}


def deploy_rule(
    session: Session,
    features: pd.DataFrame,
    failures: pd.DataFrame,
    part_code: str,
    selected: list[str] | None = None,
    created_by: str = "system",
    user_id: int | None = None,
) -> Rule:
    """Persist a new rule version and retire the previous one."""
    preview = preview_rule(features, failures, part_code, selected)
    weights = {w["signal"]: w["weight"] for w in preview["weights"]}
    correlations = {c["signal"]: c["correlation"] for c in preview["correlations"]}
    metrics = preview["metrics"]

    previous = active_rule(session, part_code)
    if previous is not None:
        previous.is_active = False

    next_version = 1 + (
        session.execute(
            select(Rule.version)
            .where(Rule.part_code == part_code)
            .order_by(Rule.version.desc())
        ).scalars().first()
        or 0
    )

    rule = Rule(
        part_code=part_code,
        version=next_version,
        formula=preview["formula"],
        precision=metrics["precision"],
        coverage=metrics["coverage"],
        days_to_alert=metrics["days_to_alert"],
        sample_failures=metrics["sample_failures"],
        is_active=True,
        created_by=created_by,
    )
    session.add(rule)
    session.flush()

    # Signals the user turned off are recorded too, with included=False, so the
    # modelling choice remains auditable after the fact.
    for signal, correlation in correlations.items():
        session.add(
            RuleSignal(
                rule_id=rule.rule_id,
                signal=signal,
                correlation=correlation,
                weight=weights.get(signal, 0.0),
                included=signal in weights,
            )
        )

    session.add(
        AuditLog(
            user_id=user_id,
            action="rule.deploy",
            entity="rule",
            entity_id=str(rule.rule_id),
            payload={
                "part_code": part_code,
                "version": next_version,
                "formula": preview["formula"],
                "weights": weights,
                "metrics": metrics,
                "replaced_rule_id": previous.rule_id if previous else None,
            },
        )
    )
    session.commit()
    return rule


def load_failures(session: Session) -> pd.DataFrame:
    """Failure events only - the ground truth the back-test scores against."""
    frame = pd.DataFrame(
        session.execute(
            select(JobCard.vin, JobCard.part_code, JobCard.event_date).where(
                JobCard.event_type == "failure"
            )
        ).all(),
        columns=["vin", "part_code", "event_date"],
    )
    if not frame.empty:
        frame["event_date"] = pd.to_datetime(frame["event_date"])
    return frame
