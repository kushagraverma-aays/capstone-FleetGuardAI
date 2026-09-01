"""Components and rules - everything behind Rule Studio.

`POST /api/rules/preview` is the endpoint the wizard calls on every signal
toggle, so it must recompute weights and back-test metrics without writing
anything and return fast enough to feel instant. The feature table it needs is
memoised in `services/feature_cache`.

Rule *authoring* is a manufacturer capability (spec section 3): a customer-
scoped session can read the deployed formula and its metrics, but the deploy
endpoint refuses. The read endpoints stay open to both because a customer
being able to see exactly why they were alerted is the point of the product.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.constants import SIGNALS
from app.deps import CurrentScope, DbSession, RuleAuthorScope
from app.models import Part, Rule
from app.schemas.fleet import (
    PartCorrelations,
    PartHistory,
    PartOut,
    RuleDeployRequest,
    RuleOut,
    RulePreview,
    RulePreviewRequest,
)
from app.services import correlation, feature_cache, fleet_queries, rules_engine
from app.services.workflow import record_audit

router = APIRouter(prefix="/api", tags=["rules"])


def _require_part(db, part_code: str) -> Part:
    part = db.get(Part, part_code)
    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No component with code {part_code}.",
        )
    return part


def _validate_signals(signals: list[str] | None) -> None:
    if not signals:
        return
    unknown = [s for s in signals if s not in SIGNALS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown signals: {', '.join(unknown)}. Valid signals: {', '.join(SIGNALS)}.",
        )


# --- parts -------------------------------------------------------------------


@router.get("/parts", response_model=list[PartOut], summary="Component catalogue")
def list_parts(db: DbSession, scope: CurrentScope) -> list[PartOut]:
    return [PartOut(**row) for row in fleet_queries.list_parts(db, scope)]


@router.get(
    "/parts/{part_code}/history",
    response_model=PartHistory,
    summary="Twelve months of failures and preventive swaps for one component",
)
def part_history(part_code: str, db: DbSession, scope: CurrentScope) -> PartHistory:
    row = fleet_queries.part_history(db, scope, part_code)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No component with code {part_code}.",
        )
    return PartHistory(**row)


@router.get(
    "/parts/{part_code}/correlations",
    response_model=PartCorrelations,
    summary="Signals ranked by how strongly they precede this component's failures",
)
def part_correlations(
    part_code: str, db: DbSession, scope: CurrentScope
) -> PartCorrelations:
    part = _require_part(db, part_code)
    features = feature_cache.features_for_part(db, part_code)
    correlations = correlation.rank_signals(features)

    return PartCorrelations(
        part_code=part.part_code,
        part_name=part.part_name,
        sample_rows=int(len(features)),
        sample_failures=int(features["failed_within_horizon"].sum())
        if not features.empty
        else 0,
        correlations=[c.to_dict() for c in correlations],
        suggested_signals=rules_engine.default_selection(correlations),
    )


# --- rules -------------------------------------------------------------------


@router.get(
    "/rules/{part_code}",
    response_model=RuleOut,
    summary="The rule currently scoring this component",
)
def get_rule(part_code: str, db: DbSession, scope: CurrentScope) -> RuleOut:
    part = _require_part(db, part_code)
    rule = rules_engine.active_rule(db, part_code)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No rule is deployed for {part.part_name}. Preview one in Rule "
                "Studio and deploy it, or run the scoring CLI."
            ),
        )
    return RuleOut(**fleet_queries.rule_to_dict(db, rule, part.part_name))


@router.get(
    "/rules/{part_code}/history",
    response_model=list[RuleOut],
    summary="Every deployed version of this component's rule, newest first",
)
def rule_history(part_code: str, db: DbSession, scope: CurrentScope) -> list[RuleOut]:
    part = _require_part(db, part_code)
    return [
        RuleOut(**fleet_queries.rule_to_dict(db, rule, part.part_name))
        for rule in rules_engine.rule_history(db, part_code)
    ]


@router.post(
    "/rules/preview",
    response_model=RulePreview,
    summary="Recompute weights and back-test metrics without deploying",
)
def preview_rule(
    payload: RulePreviewRequest, db: DbSession, scope: CurrentScope
) -> RulePreview:
    part = _require_part(db, payload.part_code)
    _validate_signals(payload.signals)

    features = feature_cache.features_for_part(db, payload.part_code)
    failures = feature_cache.failures_for_part(db, payload.part_code)
    preview = rules_engine.preview_rule(features, failures, payload.part_code, payload.signals)

    return RulePreview(
        part_code=part.part_code,
        part_name=part.part_name,
        formula=preview["formula"],
        selected_signals=preview["selected_signals"],
        weights=[
            {**weight, "included": True, "share": weight["share"]}
            for weight in preview["weights"]
        ],
        correlations=preview["correlations"],
        metrics=preview["metrics"],
        weight_total=round(sum(w["weight"] for w in preview["weights"]), 4),
    )


@router.post(
    "/rules",
    response_model=RuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Deploy a rule version, retiring the previous one",
)
def deploy_rule(
    payload: RuleDeployRequest, db: DbSession, scope: RuleAuthorScope
) -> RuleOut:
    part = _require_part(db, payload.part_code)
    _validate_signals(payload.signals)

    features = feature_cache.features_for_part(db, payload.part_code)
    failures = feature_cache.failures_for_part(db, payload.part_code)

    rule = rules_engine.deploy_rule(
        db,
        features,
        failures,
        payload.part_code,
        payload.signals,
        created_by=scope.email or "manufacturer",
        user_id=scope.user_id,
    )

    if payload.note:
        record_audit(
            db,
            scope,
            action="rule.note",
            entity="rule",
            entity_id=rule.rule_id,
            payload={"note": payload.note, "part_code": payload.part_code},
        )
        db.commit()

    return RuleOut(**fleet_queries.rule_to_dict(db, rule, part.part_name))


@router.get(
    "/rules",
    response_model=list[RuleOut],
    summary="The active rule for every component",
)
def list_active_rules(db: DbSession, scope: CurrentScope) -> list[RuleOut]:
    rules = db.execute(
        select(Rule).where(Rule.is_active.is_(True)).order_by(Rule.part_code)
    ).scalars().all()
    return [RuleOut(**fleet_queries.rule_to_dict(db, rule)) for rule in rules]
