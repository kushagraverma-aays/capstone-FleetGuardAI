"""Endpoint contracts: paging, sorting, filtering, and the acceptance criteria.

Two of the checks here are lifted directly from spec section 12 and are worth
naming, because they are the claims the demo makes out loud:

  * toggling a signal re-normalises the weights to exactly 1.00, and
  * the failure probability and the RUL for one component agree, and each
    detail view says so in a sentence.

The rest verify that a list endpoint behaves like a list endpoint: a total
that ignores paging, a sort that actually sorts, and a filter that actually
filters.
"""

from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import select

from app.constants import AMBER_THRESHOLD, RED_THRESHOLD
from app.models import AuditLog, Notification, WorkOrder

pytestmark = pytest.mark.usefixtures("seeded")


# --- health and auth ---------------------------------------------------------


def test_health_is_live(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_readiness_reports_the_database(client):
    body = client.get("/api/health/ready").json()
    assert body["database"] == "ok"


def test_login_issues_a_token_for_a_seeded_user(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@fleetguard.ai", "password": "fleetguard"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["role"] == "manufacturer_admin"
    assert body["customer_id"] is None


def test_login_rejects_a_wrong_password(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@fleetguard.ai", "password": "not-the-password"},
    )
    assert response.status_code == 401


def test_login_does_not_reveal_whether_the_address_exists(client):
    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    wrong = client.post(
        "/api/auth/login", json={"email": "admin@fleetguard.ai", "password": "x"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["message"] == wrong.json()["message"]


# --- list endpoint mechanics -------------------------------------------------


def test_predictions_paginate_with_a_stable_total(client):
    first = client.get("/api/predictions?limit=10&offset=0").json()
    second = client.get("/api/predictions?limit=10&offset=10").json()

    assert first["total"] == second["total"]
    assert first["total"] > 10
    assert len(first["items"]) == 10
    assert first["limit"] == 10 and second["offset"] == 10

    # Paging must not repeat a row, which is what the VIN tie-breaker buys.
    keys = {(r["vin"], r["part_code"]) for r in first["items"]}
    assert not keys & {(r["vin"], r["part_code"]) for r in second["items"]}


def test_predictions_sort_by_probability_descending(client):
    items = client.get("/api/predictions?limit=50&sort=probability&order=desc").json()["items"]
    probabilities = [row["failure_probability"] for row in items]
    assert probabilities == sorted(probabilities, reverse=True)


def test_predictions_sort_by_rul_ascending(client):
    items = client.get("/api/predictions?limit=50&sort=rul&order=asc").json()["items"]
    days = [row["rul_days"] for row in items]
    assert days == sorted(days)


def test_predictions_filter_by_tier(client):
    body = client.get("/api/predictions?tier=RED&limit=100").json()
    assert body["items"]
    assert {row["risk_tier"] for row in body["items"]} == {"RED"}


def test_tier_filter_narrows_the_total(client):
    everything = client.get("/api/predictions?limit=1").json()["total"]
    red = client.get("/api/predictions?tier=RED&limit=1").json()["total"]
    assert 0 < red < everything


def test_max_rul_days_filter(client):
    body = client.get("/api/predictions?max_rul_days=30&limit=100").json()
    assert body["items"]
    assert all(row["rul_days"] <= 30 for row in body["items"])


def test_limit_above_the_cap_is_rejected(client):
    response = client.get("/api/predictions?limit=5000")
    assert response.status_code == 422
    assert response.json()["problems"][0]["field"] == "limit"


# --- risk tiers agree with the thresholds ------------------------------------


def test_risk_tiers_match_their_probability_bands(client):
    """A tier that disagreed with its own probability would undermine every screen."""
    for row in client.get("/api/predictions?limit=200&sort=probability").json()["items"]:
        probability, tier = row["failure_probability"], row["risk_tier"]
        if row["escalated"]:
            # Escalation is allowed to override the band, and must say why.
            assert tier == "RED"
            assert row["escalation_reason"]
        elif probability >= RED_THRESHOLD:
            assert tier == "RED"
        elif probability >= AMBER_THRESHOLD:
            assert tier == "AMBER"
        else:
            assert tier == "GREEN"


# --- the two acceptance criteria ---------------------------------------------


def test_toggling_signals_renormalises_the_weights_to_one(client, any_prediction):
    """Spec section 12: weights must visibly re-normalise to 1.00 on every toggle."""
    part = any_prediction.part_code
    full = client.post("/api/rules/preview", json={"part_code": part}).json()
    assert full["weight_total"] == 1.0

    signals = full["selected_signals"]
    assert len(signals) >= 2

    for count in range(1, len(signals) + 1):
        subset = signals[:count]
        preview = client.post(
            "/api/rules/preview", json={"part_code": part, "signals": subset}
        ).json()
        assert preview["weight_total"] == 1.0, f"weights must sum to 1.00 for {subset}"
        assert round(sum(w["weight"] for w in preview["weights"]), 4) == 1.0
        assert preview["selected_signals"] == subset
        assert preview["formula"].startswith("failure_probability =")


def test_preview_metrics_change_with_the_signal_selection(client, any_prediction):
    """The metric cards must respond to the toggles, or step 3 is theatre."""
    part = any_prediction.part_code
    full = client.post("/api/rules/preview", json={"part_code": part}).json()
    single = client.post(
        "/api/rules/preview",
        json={"part_code": part, "signals": full["selected_signals"][:1]},
    ).json()
    assert full["metrics"] != single["metrics"]


def test_preview_writes_nothing(client, reread, any_prediction):
    latest = select(AuditLog).order_by(AuditLog.id.desc())
    before = reread().execute(latest).scalars().first()
    client.post("/api/rules/preview", json={"part_code": any_prediction.part_code})
    after = reread().execute(latest).scalars().first()
    assert (before.id if before else None) == (after.id if after else None)


def test_probability_and_rul_agree_and_say_so(client, any_prediction):
    """Spec section 12: the two views derive from one health index and must state it."""
    vin, part = any_prediction.vin, any_prediction.part_code
    prediction = client.get(f"/api/predictions/{vin}/{part}").json()
    rul = client.get(f"/api/rul/{vin}/{part}").json()

    assert prediction["rul_days"] == rul["rul_days"]
    assert prediction["rul_km"] == rul["rul_km"]
    assert prediction["health_index"] == rul["health_index"]
    assert prediction["failure_probability"] == rul["failure_probability"]

    # And the derivation itself: probability is 1 - health/100, exactly.
    assert round(1.0 - prediction["health_index"] / 100.0, 4) == round(
        prediction["failure_probability"], 4
    )

    assert prediction["cross_check"] == rul["cross_check"]
    assert f"{prediction['rul_days']:.0f} days" in prediction["cross_check"]


# --- detail payloads ---------------------------------------------------------


def test_prediction_detail_carries_everything_the_screen_needs(client, any_prediction):
    body = client.get(
        f"/api/predictions/{any_prediction.vin}/{any_prediction.part_code}"
    ).json()

    assert body["drivers"], "signal driver bars need drivers"
    assert abs(sum(d["share"] for d in body["drivers"]) - 100.0) < 0.5
    assert body["trend"], "the probability trend chart needs points"
    assert body["curve"], "the degradation chart needs a curve"
    assert body["rule"]["formula"].startswith("failure_probability =")
    assert body["cost"]["unplanned_cost"] > body["cost"]["planned_cost"]
    assert 0 <= body["life_used_pct"]


def test_rul_curve_is_split_into_observed_and_projected(client, db):
    """The chart has to draw the two halves differently, so the flag must be there."""
    from app.models import Prediction

    row = db.execute(
        select(Prediction).where(Prediction.rul_days > 30).limit(1)
    ).scalars().first()
    if row is None:
        pytest.skip("No component with a forward projection to check.")

    curve = client.get(f"/api/rul/{row.vin}/{row.part_code}").json()["curve"]
    assert any(point["projected"] for point in curve)
    assert any(not point["projected"] for point in curve)


def test_vehicle_detail_carries_components_history_and_telemetry(client, any_prediction):
    body = client.get(f"/api/vehicles/{any_prediction.vin}").json()
    assert len(body["components"]) >= 1
    assert body["service_history"], "the timeline needs job cards"
    assert body["telemetry"], "the telemetry chart needs weeks"
    assert set(body["telemetry"][0]["signals"]) >= {"coolant_temp_variance"}
    # The header summary must agree with the component strip below it.
    assert body["worst_probability"] == max(
        c["failure_probability"] for c in body["components"]
    )


def test_rul_bands_sum_to_the_unfiltered_total(client):
    bands = client.get("/api/rul/bands").json()
    total = client.get("/api/rul?limit=1").json()["total"]
    assert sum(bands.values()) == total


def test_rul_band_filter_returns_only_that_band(client):
    body = client.get("/api/rul?band=within_30_days&limit=100").json()
    assert body["items"]
    assert all(0 < row["rul_days"] <= 30 for row in body["items"])
    assert {row["urgency_band"] for row in body["items"]} == {"within_30_days"}


# --- parts and rules ---------------------------------------------------------


def test_parts_catalogue_reports_its_deployed_rule(client):
    parts = client.get("/api/parts").json()
    assert len(parts) == 8
    assert all(part["has_active_rule"] for part in parts)
    assert all(0.0 <= part["rule_precision"] <= 1.0 for part in parts)


def test_correlations_are_ranked_and_floored_at_zero(client, any_prediction):
    body = client.get(f"/api/parts/{any_prediction.part_code}/correlations").json()
    correlations = [c["correlation"] for c in body["correlations"]]
    assert correlations == sorted(correlations, reverse=True)
    assert all(c >= 0.0 for c in correlations)
    assert body["suggested_signals"]
    assert body["sample_failures"] > 0


def test_rule_history_is_newest_first(client, any_prediction):
    history = client.get(f"/api/rules/{any_prediction.part_code}/history").json()
    versions = [rule["version"] for rule in history]
    assert versions == sorted(versions, reverse=True)
    assert sum(1 for rule in history if rule["is_active"]) == 1


def test_unknown_part_is_a_clean_404(client):
    response = client.get("/api/rules/NOT-A-PART")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "NOT-A-PART" in response.json()["message"]


def test_unknown_signal_is_rejected_with_the_valid_list(client, any_prediction):
    response = client.post(
        "/api/rules/preview",
        json={"part_code": any_prediction.part_code, "signals": ["made_up_signal"]},
    )
    assert response.status_code == 422
    assert "made_up_signal" in response.json()["message"]
    assert "coolant_temp_variance" in response.json()["message"]


# --- overview and analytics --------------------------------------------------


def test_overview_tier_counts_match_the_prediction_totals(client):
    body = client.get("/api/overview").json()
    kpis = body["kpis"]
    red = client.get("/api/predictions?tier=RED&limit=1").json()["total"]
    assert kpis["red_count"] == red
    assert sum(slice_["count"] for slice_ in body["tiers"]) == (
        kpis["red_count"] + kpis["amber_count"] + kpis["green_count"]
    )
    assert abs(sum(slice_["share"] for slice_ in body["tiers"]) - 1.0) < 0.01


def test_overview_needs_attention_is_red_and_soonest_first(client):
    rows = client.get("/api/overview").json()["needs_attention"]
    assert rows
    assert {row["risk_tier"] for row in rows} == {"RED"}
    days = [row["rul_days"] for row in rows]
    assert days == sorted(days)


def test_cost_exposure_dimensions_agree_on_the_total(client):
    totals = {
        dimension: client.get(
            f"/api/analytics/cost-exposure?dimension={dimension}"
        ).json()["total_exposure"]
        for dimension in ("customer", "component", "tier", "region")
    }
    # Same money, sliced four ways.
    assert max(totals.values()) - min(totals.values()) < 1.0


def test_failure_trends_cover_the_requested_window(client):
    body = client.get("/api/analytics/failure-trends?months=12").json()
    assert body["months"]
    assert body["by_component"]
    assert body["signal_prevalence"]


# --- alerts and work orders --------------------------------------------------


def test_acknowledging_an_alert_stamps_it_and_writes_an_audit_row(client, db, reread):
    notification = db.execute(
        select(Notification).where(Notification.status == "pending").limit(1)
    ).scalars().first()
    if notification is None:
        pytest.skip("No pending alerts to acknowledge.")

    original = notification.status
    try:
        body = client.patch(
            f"/api/notifications/{notification.id}", json={"status": "acknowledged"}
        ).json()
        assert body["status"] == "acknowledged"
        assert body["acknowledged_at"] is not None

        audit = reread().execute(
            select(AuditLog)
            .where(
                AuditLog.entity == "notification",
                AuditLog.entity_id == str(notification.id),
            )
            .order_by(AuditLog.id.desc())
        ).scalars().first()
        assert audit is not None
        assert audit.action == "notification.acknowledged"
        assert audit.payload["from_status"] == original
    finally:
        client.patch(f"/api/notifications/{notification.id}", json={"status": original})


def test_a_work_order_can_be_raised_updated_and_is_audited(client, db, reread, any_prediction):
    created = client.post(
        "/api/work-orders",
        json={
            "vin": any_prediction.vin,
            "part_code": any_prediction.part_code,
            "status": "draft",
            "notes": "Raised by the endpoint contract test.",
        },
    )
    assert created.status_code == 201
    order = created.json()
    order_id = order["id"]

    try:
        # The tenant comes from the vehicle, never from the request body.
        assert order["customer_id"] is not None
        assert order["part_name"]

        updated = client.patch(
            f"/api/work-orders/{order_id}",
            json={"status": "scheduled", "scheduled_date": "2026-10-01"},
        ).json()
        assert updated["status"] == "scheduled"
        assert updated["scheduled_date"] == "2026-10-01"

        listed = client.get(f"/api/work-orders?vin={any_prediction.vin}").json()
        assert order_id in [row["id"] for row in listed["items"]]

        actions = [
            row.action
            for row in reread().execute(
                select(AuditLog).where(
                    AuditLog.entity == "work_order",
                    AuditLog.entity_id == str(order_id),
                )
            ).scalars()
        ]
        assert "work_order.create" in actions
        assert "work_order.update" in actions
    finally:
        db.execute(
            WorkOrder.__table__.delete().where(WorkOrder.id == order_id)
        )
        db.execute(
            AuditLog.__table__.delete().where(
                AuditLog.entity == "work_order", AuditLog.entity_id == str(order_id)
            )
        )
        db.commit()


def test_a_work_order_against_an_unknown_vehicle_is_refused(client, any_prediction):
    response = client.post(
        "/api/work-orders",
        json={"vin": "NOTAREALVIN", "part_code": any_prediction.part_code},
    )
    assert response.status_code == 422
    assert "NOTAREALVIN" in response.json()["message"]


def test_an_unknown_work_order_is_a_404(client):
    response = client.patch("/api/work-orders/99999999", json={"status": "completed"})
    assert response.status_code == 404


# --- export ------------------------------------------------------------------


def test_csv_export_carries_the_filtered_rows(client):
    response = client.get("/api/export/predictions.csv?tier=RED")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    expected = client.get("/api/predictions?tier=RED&limit=1").json()["total"]
    assert len(rows) == expected
    assert {row["risk_tier"] for row in rows} == {"RED"}
    assert "vin" in rows[0] and "estimated_cost_impact" in rows[0]


# --- documentation -----------------------------------------------------------


def test_openapi_documents_every_endpoint_with_a_summary(client):
    """/docs is part of the demo, so an undescribed endpoint is a defect."""
    schema = client.get("/openapi.json").json()
    missing = [
        f"{method.upper()} {path}"
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if not operation.get("summary")
    ]
    assert not missing, f"endpoints without a summary: {missing}"


# --- read models must not count events that have not happened yet ------------


def test_km_on_part_ignores_a_future_job_card(db, any_prediction, reread):
    """A workshop event dated tomorrow must not reset the part's clock today.

    The generator places events inside Monday-anchored weeks, so the final week
    of the record can carry a date a few days past it. Counting such an event
    made the vehicle drawer read "0 km of 90,000 km" next to "Overdue" - the
    prediction was scored from telemetry that stops at the end of the record,
    while this read model had already jumped forward to a swap that has not
    happened.
    """
    from datetime import date, timedelta

    from app.models import JobCard, Vehicle
    from app.services.fleet_queries import current_km_on_part

    vehicle = db.get(Vehicle, any_prediction.vin)
    before = current_km_on_part(db, any_prediction.vin, any_prediction.part_code)

    future = JobCard(
        vin=any_prediction.vin,
        part_code=any_prediction.part_code,
        event_date=date.today() + timedelta(days=3),
        odometer_reading=vehicle.total_km_driven,
        event_type="preventive",
        cost=1000.0,
        downtime_hours=2.0,
        replaced=True,
    )
    db.add(future)
    db.flush()
    try:
        assert current_km_on_part(db, any_prediction.vin, any_prediction.part_code) == before
    finally:
        db.delete(future)
        db.flush()


def test_cost_exposure_rows_sum_to_the_headline_avoidable(client):
    """The bars and the sentence above them must agree.

    Per-row avoidable used to be a copy of that row's exposure, which made
    every row read as 100% avoidable while the header reported about half.
    Exposure is probability-weighted over every component; avoidable is the
    gross saving on the red ones, so the two totals differ - but the rows must
    add up to their own header.
    """
    body = client.get("/api/analytics/cost-exposure", params={"dimension": "customer"}).json()

    assert body["rows"]
    assert body["total_avoidable"] > 0
    assert body["total_avoidable"] != body["total_exposure"]

    summed = sum(row["avoidable"] for row in body["rows"])
    assert abs(summed - body["total_avoidable"]) < 1.0

    for row in body["rows"]:
        assert row["avoidable"] != row["exposure"]
