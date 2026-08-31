"""Every Insight Agent tool, against the seeded database (spec section 10).

No LLM is involved here. A tool is a plain function over a session and a
scope, and that is exactly why it can be tested properly: the interesting
behaviour - what a tool returns when the thing does not exist, and what it
returns when the thing exists but belongs to someone else - is decided in
Python, not by the model.

The two properties every tool must hold:

  * it never returns another tenant's data, and
  * when it finds nothing it says so, rather than returning an empty shape the
    model could read as "no problems here".
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from datetime import date

from app.constants import SIGNALS
from app.models import Customer, Notification, Part, Prediction, Vehicle, WorkOrder
from app.services import agent_tools, insights, workflow
from app.services.scoping import MANUFACTURER_SCOPE, customer_scope

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture(scope="module")
def part_name(request) -> str:
    return "Alternator"


# --- registry ----------------------------------------------------------------


def test_every_tool_has_a_schema_and_every_schema_has_a_tool():
    """A schema without a function is a tool call that 500s at demo time."""
    functions = set(agent_tools.TOOL_FUNCTIONS)
    schemas = {s["function"]["name"] for s in agent_tools.TOOL_SCHEMAS}
    assert functions == schemas


def test_every_schema_describes_when_to_use_the_tool():
    for schema in agent_tools.TOOL_SCHEMAS:
        function = schema["function"]
        assert len(function["description"]) > 60, function["name"]
        assert schema["type"] == "function"
        assert "parameters" in function


def test_the_spec_s_nine_tools_are_all_present():
    required = {
        "get_fleet_summary",
        "list_vehicles_by_risk",
        "get_vehicle_risk",
        "explain_prediction",
        "get_rul",
        "compare_parts",
        "get_rule",
        "get_notifications",
        "get_cost_exposure",
    }
    assert required <= set(agent_tools.TOOL_FUNCTIONS)


# --- the tools ---------------------------------------------------------------


def test_get_fleet_summary_counts_the_whole_fleet(db):
    result = agent_tools.get_fleet_summary(db, MANUFACTURER_SCOPE)
    assert result["found"] is True
    assert result["vehicles_monitored"] == 600
    assert result["red_components"] > 0
    assert result["total_cost_exposure"] > 0


def test_fleet_summary_separates_red_components_from_red_vehicles(db):
    """Eight components per vehicle means the two numbers differ a lot."""
    result = agent_tools.get_fleet_summary(db, MANUFACTURER_SCOPE)
    assert result["vehicles_with_at_least_one_red_component"] <= result["vehicles_monitored"]
    assert "red_count" not in result, "the ambiguous key must not come back"


def test_get_fleet_summary_shrinks_under_a_customer_scope(db, customer_a):
    everything = agent_tools.get_fleet_summary(db, MANUFACTURER_SCOPE)
    scoped = agent_tools.get_fleet_summary(db, customer_scope(customer_a))
    assert scoped["vehicles_monitored"] < everything["vehicles_monitored"]
    assert scoped["total_cost_exposure"] < everything["total_cost_exposure"]


def test_list_vehicles_by_risk_ranks_and_filters(db):
    result = agent_tools.list_vehicles_by_risk(db, MANUFACTURER_SCOPE, tier="RED", limit=5)
    assert result["found"] is True
    assert len(result["vehicles"]) == 5
    assert {v["risk_tier"] for v in result["vehicles"]} == {"RED"}
    probabilities = [v["failure_probability_pct"] for v in result["vehicles"]]
    assert probabilities == sorted(probabilities, reverse=True)


def test_list_vehicles_by_risk_caps_the_row_count(db):
    result = agent_tools.list_vehicles_by_risk(db, MANUFACTURER_SCOPE, limit=500)
    assert len(result["vehicles"]) <= agent_tools.MAX_ROWS


def test_list_vehicles_by_risk_is_scoped(db, customer_a):
    scoped = agent_tools.list_vehicles_by_risk(
        db, customer_scope(customer_a), tier="RED", limit=25
    )
    assert {v["customer"] for v in scoped["vehicles"]} == {
        db.execute(
            select(Vehicle).where(Vehicle.customer_id == customer_a).limit(1)
        ).scalars().first().customer.name
    }


def test_get_vehicle_risk_lists_every_component(db, any_prediction):
    result = agent_tools.get_vehicle_risk(db, MANUFACTURER_SCOPE, any_prediction.vin)
    assert result["found"] is True
    assert len(result["components"]) == 8
    assert result["vin"] == any_prediction.vin


def test_get_vehicle_risk_accepts_a_lowercase_vin(db, any_prediction):
    """A user typing a VIN in chat will not shout it."""
    result = agent_tools.get_vehicle_risk(
        db, MANUFACTURER_SCOPE, any_prediction.vin.lower()
    )
    assert result["found"] is True


def test_explain_prediction_resolves_a_component_by_name(db, any_prediction):
    part = db.get(Part, any_prediction.part_code)
    result = agent_tools.explain_prediction(
        db, MANUFACTURER_SCOPE, any_prediction.vin, part.part_name
    )
    assert result["found"] is True
    assert result["component"] == part.part_name
    assert result["drivers"], "the explanation needs its driving signals"
    assert result["rule"]["formula"].startswith("failure_probability =")


def test_explain_prediction_driver_shares_sum_to_one_hundred(db, any_prediction):
    part = db.get(Part, any_prediction.part_code)
    result = agent_tools.explain_prediction(
        db, MANUFACTURER_SCOPE, any_prediction.vin, part.part_name
    )
    total = sum(d["share_of_stress_pct"] for d in result["drivers"])
    assert abs(total - 100.0) < 0.5


def test_get_rul_agrees_with_explain_prediction(db, any_prediction):
    """Both read the same stored prediction, so they cannot disagree."""
    part = db.get(Part, any_prediction.part_code)
    rul = agent_tools.get_rul(db, MANUFACTURER_SCOPE, any_prediction.vin, part.part_name)
    explained = agent_tools.explain_prediction(
        db, MANUFACTURER_SCOPE, any_prediction.vin, part.part_name
    )
    assert rul["failure_probability_pct"] == explained["failure_probability_pct"]
    assert "cross_check" in rul


def test_compare_parts_covers_every_component(db):
    result = agent_tools.compare_parts(db, MANUFACTURER_SCOPE)
    assert result["found"] is True
    assert len(result["components"]) == 8
    failures = [c["failures"] for c in result["components"]]
    assert failures == sorted(failures, reverse=True)
    assert all(c["median_share_of_design_life_pct"] >= 0 for c in result["components"])


def test_compare_parts_accepts_a_named_subset(db):
    result = agent_tools.compare_parts(
        db, MANUFACTURER_SCOPE, parts=["Alternator", "Timing Belt"]
    )
    assert {c["component"] for c in result["components"]} == {"Alternator", "Timing Belt"}


def test_get_rule_returns_the_formula_and_its_metrics(db):
    result = agent_tools.get_rule(db, MANUFACTURER_SCOPE, "Turbocharger")
    assert result["found"] is True
    assert result["formula"].startswith("failure_probability =")
    assert 0 <= result["precision_pct"] <= 100
    assert 0 <= result["coverage_pct"] <= 100
    assert result["signals"]


def test_get_notifications_returns_the_most_severe_first(db):
    result = agent_tools.get_notifications(db, MANUFACTURER_SCOPE, limit=10)
    assert result["found"] is True
    severities = [a["severity"] for a in result["alerts"]]
    assert severities[0] in ("critical", "high")


def test_get_notifications_is_scoped(db, customer_a):
    scoped = agent_tools.get_notifications(db, customer_scope(customer_a), limit=25)
    everything = agent_tools.get_notifications(db, MANUFACTURER_SCOPE, limit=25)
    assert scoped["pending_total"] < everything["pending_total"]


def test_get_cost_exposure_slices_by_dimension(db):
    for dimension in ("customer", "component", "tier", "region"):
        result = agent_tools.get_cost_exposure(db, MANUFACTURER_SCOPE, dimension)
        assert result["found"] is True, dimension
        assert result["breakdown"], dimension


def test_compare_customers_benchmarks_against_the_fleet(db):
    result = agent_tools.compare_customers(db, MANUFACTURER_SCOPE)
    assert result["found"] is True
    assert len(result["customers"]) == 6
    assert result["fleet_mean_health_index"] > 0


def test_compare_customers_hides_rivals_but_keeps_the_benchmark(db, customer_a):
    result = agent_tools.compare_customers(db, customer_scope(customer_a))
    assert len(result["customers"]) == 1
    assert result["fleet_failures_per_100_vehicles"] > 0


# --- grounding: absence is stated, never implied -----------------------------


def test_an_unknown_vin_is_reported_as_not_found(db):
    result = agent_tools.get_vehicle_risk(db, MANUFACTURER_SCOPE, "ZZ9PLURALZALPHA")
    assert result["found"] is False
    assert "not found" in result["message"].lower()


def test_an_unknown_component_lists_the_real_ones(db):
    """The model can correct itself next round if it is told the options."""
    result = agent_tools.get_rule(db, MANUFACTURER_SCOPE, "Flux Capacitor")
    assert result["found"] is False
    assert "Alternator" in result["message"]


def test_an_invalid_cost_dimension_lists_the_valid_ones(db):
    result = agent_tools.get_cost_exposure(db, MANUFACTURER_SCOPE, "colour")
    assert result["found"] is False
    assert "customer" in result["message"]


def test_another_customers_vehicle_is_not_found_through_a_tool(db, customer_a, vehicle_of_b):
    """The agent must be no more able to cross tenants than the REST API is."""
    result = agent_tools.get_vehicle_risk(
        db, customer_scope(customer_a), vehicle_of_b.vin
    )
    assert result["found"] is False
    assert "not found" in result["message"].lower()


def test_another_customers_prediction_is_not_explainable(db, customer_a, prediction_of_b):
    result = agent_tools.explain_prediction(
        db, customer_scope(customer_a), prediction_of_b.vin, prediction_of_b.part_code
    )
    assert result["found"] is False


def test_another_customers_rul_is_not_readable(db, customer_a, prediction_of_b):
    result = agent_tools.get_rul(
        db, customer_scope(customer_a), prediction_of_b.vin, prediction_of_b.part_code
    )
    assert result["found"] is False


def test_a_foreign_vin_and_a_fake_vin_are_indistinguishable(db, customer_a, vehicle_of_b):
    foreign = agent_tools.get_vehicle_risk(db, customer_scope(customer_a), vehicle_of_b.vin)
    fake = agent_tools.get_vehicle_risk(db, customer_scope(customer_a), "NOSUCHVIN00")
    assert foreign["found"] == fake["found"] is False
    # Same wording, so the reply cannot leak that one of them is a real truck.
    assert foreign["message"].replace(vehicle_of_b.vin, "X") == fake["message"].replace(
        "NOSUCHVIN00", "X"
    )


# --- dispatch ----------------------------------------------------------------


def test_run_tool_dispatches_by_name(db):
    result = agent_tools.run_tool(db, MANUFACTURER_SCOPE, "get_fleet_summary", {})
    assert result["found"] is True


def test_run_tool_rejects_an_unknown_tool_and_lists_the_real_ones(db):
    result = agent_tools.run_tool(db, MANUFACTURER_SCOPE, "drop_all_tables", {})
    assert result["found"] is False
    assert "get_fleet_summary" in result["message"]


def test_run_tool_reports_bad_arguments_instead_of_raising(db):
    """A wrong argument is the model's mistake to fix, not a 500."""
    result = agent_tools.run_tool(
        db, MANUFACTURER_SCOPE, "get_vehicle_risk", {"registration": "XYZ"}
    )
    assert result["found"] is False
    assert "arguments" in result["message"].lower()


def test_run_tool_handles_unparseable_arguments(db):
    result = agent_tools.run_tool(
        db, MANUFACTURER_SCOPE, "get_fleet_summary", {"__parse_error__": "{oops"}
    )
    assert result["found"] is False
    assert "json" in result["message"].lower()


def test_scope_cannot_be_passed_as_a_tool_argument(db, customer_a):
    """The model must not be able to widen its own view through an argument."""
    result = agent_tools.run_tool(
        db,
        customer_scope(customer_a),
        "get_fleet_summary",
        {"scope": None, "customer_id": None},
    )
    # Rejected as a bad argument rather than silently honoured.
    assert result["found"] is False


# --- the register and the customer directory ---------------------------------


def test_find_vehicles_counts_one_customer_not_the_whole_fleet(db, customer_a):
    """The defect this tool exists to fix.

    Asked how many vehicles one named customer ran, the assistant used to
    answer with `get_fleet_summary`, which describes the entire view - so a
    manufacturer session confidently reported the fleet-wide count as that
    customer's.
    """
    everyone = agent_tools.find_vehicles(db, MANUFACTURER_SCOPE)
    name = db.get(Customer, customer_a).name
    just_them = agent_tools.find_vehicles(db, MANUFACTURER_SCOPE, customer=name)

    assert just_them["found"] is True
    assert just_them["customer"] == name
    assert 0 < just_them["matching_total"] < everyone["matching_total"]
    assert sum(just_them["vehicles_by_model"].values()) == just_them["matching_total"]


def test_find_vehicles_resolves_a_partial_customer_name(db, customer_a):
    full = db.get(Customer, customer_a).name
    partial = full.split()[0]
    result = agent_tools.find_vehicles(db, MANUFACTURER_SCOPE, customer=partial)
    assert result["found"] is True
    assert result["customer"] == full


def test_find_vehicles_reports_an_unknown_customer_rather_than_guessing(db):
    result = agent_tools.find_vehicles(db, MANUFACTURER_SCOPE, customer="Nonexistent Hauliers")
    assert result["found"] is False
    assert "not found" in result["message"].lower()


def test_find_vehicles_cannot_reach_another_tenant(db, customer_a, customer_b):
    """A customer asking about a rival gets the same nothing a stranger gets."""
    other_name = db.get(Customer, customer_b).name
    result = agent_tools.find_vehicles(db, customer_scope(customer_a), customer=other_name)
    assert result["found"] is False


def test_find_vehicles_breakdown_describes_the_whole_match_not_the_page(db):
    """A breakdown built from the returned rows would describe only the rows."""
    result = agent_tools.find_vehicles(db, MANUFACTURER_SCOPE, limit=3)
    assert result["showing"] == 3
    assert sum(result["vehicles_by_model"].values()) == result["matching_total"]
    assert sum(result["vehicles_by_region"].values()) == result["matching_total"]


def test_list_customers_shows_one_row_to_a_tenant(db, customer_a):
    everyone = agent_tools.list_customers(db, MANUFACTURER_SCOPE)
    theirs = agent_tools.list_customers(db, customer_scope(customer_a))
    assert len(everyone["customers"]) > 1
    assert len(theirs["customers"]) == 1
    assert theirs["customers"][0]["customer"] == db.get(Customer, customer_a).name


# --- one vehicle's record ----------------------------------------------------


def test_get_service_history_returns_the_workshop_record(db, any_prediction):
    result = agent_tools.get_service_history(db, MANUFACTURER_SCOPE, any_prediction.vin)
    assert result["found"] is True
    assert result["vin"] == any_prediction.vin
    if result["events_total"]:
        assert result["failures_total"] + result["preventive_total"] == result["events_total"]
        assert result["events"][0]["type"] in {"failure", "preventive"}


def test_get_service_history_never_lists_a_future_event(db, any_prediction):
    """A timeline whose newest entry has not happened yet reads as a data error."""
    result = agent_tools.get_service_history(db, MANUFACTURER_SCOPE, any_prediction.vin)
    if result["events_total"]:
        assert result["last_service_date"] <= str(date.today())


def test_get_service_history_refuses_an_unknown_vin(db):
    result = agent_tools.get_service_history(db, MANUFACTURER_SCOPE, "NOTAREALVIN00")
    assert result["found"] is False


def test_get_service_history_is_scoped(db, customer_a, vehicle_of_b):
    result = agent_tools.get_service_history(db, customer_scope(customer_a), vehicle_of_b.vin)
    assert result["found"] is False


def test_get_telemetry_trend_summarises_rather_than_dumping_weeks(db, any_prediction):
    result = agent_tools.get_telemetry_trend(db, MANUFACTURER_SCOPE, any_prediction.vin)
    assert result["found"] is True
    assert len(result["signals"]) == len(SIGNALS)
    for row in result["signals"]:
        assert row["direction"] in {"rising", "falling", "steady"}
    # Sorted worst-first so the model reads the deteriorating signal at the top.
    changes = [row["change"] for row in result["signals"]]
    assert changes == sorted(changes, reverse=True)


def test_get_telemetry_trend_is_scoped(db, customer_a, vehicle_of_b):
    result = agent_tools.get_telemetry_trend(db, customer_scope(customer_a), vehicle_of_b.vin)
    assert result["found"] is False


# --- scheduling, trends and booked work --------------------------------------


def test_list_maintenance_due_orders_by_remaining_life(db):
    """The scheduling question, which risk ranking does not answer."""
    result = agent_tools.list_maintenance_due(db, MANUFACTURER_SCOPE, limit=10)
    assert result["found"] is True
    days = [row["rul_days"] for row in result["due"]]
    assert days == sorted(days)
    assert set(result["band_counts"]) >= {"overdue", "within_30_days"}


def test_list_maintenance_due_band_filter_holds(db):
    result = agent_tools.list_maintenance_due(db, MANUFACTURER_SCOPE, band="overdue", limit=5)
    if result["found"]:
        assert all(row["rul_days"] <= 0 for row in result["due"])


def test_list_maintenance_due_rejects_an_invented_band(db):
    result = agent_tools.list_maintenance_due(db, MANUFACTURER_SCOPE, band="quite soon")
    assert result["found"] is False
    assert "overdue" in result["message"]


def test_list_maintenance_due_is_scoped(db, customer_a):
    everyone = agent_tools.list_maintenance_due(db, MANUFACTURER_SCOPE)
    theirs = agent_tools.list_maintenance_due(db, customer_scope(customer_a))
    assert theirs["matching_total"] < everyone["matching_total"]


def test_get_failure_trend_covers_the_recent_months(db):
    result = agent_tools.get_failure_trend(db, MANUFACTURER_SCOPE, months=12)
    assert result["found"] is True
    assert result["months_covered"] >= 1
    assert result["total_failures"] == sum(m["failures"] for m in result["monthly"])
    months = [m["month"] for m in result["monthly"]]
    assert months == sorted(months)


def test_get_failure_trend_is_scoped(db, customer_a):
    everyone = agent_tools.get_failure_trend(db, MANUFACTURER_SCOPE)
    theirs = agent_tools.get_failure_trend(db, customer_scope(customer_a))
    assert theirs["total_failures"] <= everyone["total_failures"]


def test_get_signal_prevalence_labels_weight_and_prevalence_separately(db):
    """They are different measures and are easy to conflate into one ranking."""
    result = agent_tools.get_signal_prevalence(db, MANUFACTURER_SCOPE)
    assert result["found"] is True
    for row in result["signals"]:
        assert "mean_weight_across_rules" in row
        assert "fleet_mean_value" in row


def test_list_work_orders_maps_every_row_it_returns(db, any_prediction):
    """The row-building path has to be exercised, not just the empty one.

    The first version of this tool read `priority` and `estimated_cost` off a
    work order row. Neither key exists. Every test at the time filtered down to
    zero rows, so the mapping never ran and the tool 500ed the first time the
    assistant asked what work had been raised.
    """
    # Raised here rather than relying on the seed, so the mapping is exercised
    # on a fresh database too. Removed again below, because these tests share
    # one seeded database and must not leave rows behind for the next one.
    order = workflow.create_work_order(
        db,
        MANUFACTURER_SCOPE,
        vin=any_prediction.vin,
        part_code=any_prediction.part_code,
        notes="Raised by test_list_work_orders_maps_every_row_it_returns.",
    )
    try:
        result = agent_tools.list_work_orders(db, MANUFACTURER_SCOPE, limit=25)
        assert result["found"] is True
        assert result["work_orders"]

        mine = next(row for row in result["work_orders"] if row["id"] == order["id"])
        assert mine["vin"] == any_prediction.vin
        assert mine["component"] and mine["customer"]
        assert mine["status"] in workflow.WORK_ORDER_STATUSES
        assert mine["raised_on"]
    finally:
        db.delete(db.get(WorkOrder, order["id"]))
        db.commit()


def test_list_work_orders_says_so_when_there_are_none(db):
    result = agent_tools.list_work_orders(db, MANUFACTURER_SCOPE, status="cancelled")
    if not result["found"]:
        assert "no work orders" in result["message"].lower()


def test_list_work_orders_is_scoped(db, customer_a, vehicle_of_b):
    result = agent_tools.list_work_orders(db, customer_scope(customer_a), vin=vehicle_of_b.vin)
    assert result["found"] is False


# --- the schemas must describe the system, not a plausible version of it -----


def test_the_work_order_status_enum_matches_the_real_vocabulary():
    """A schema enum that does not exist in the data is a confident wrong answer.

    The first version of this schema offered "open" and "in_progress", neither
    of which this system uses - the value meant is "draft". Filtering on a
    status that cannot exist returns nothing, and the model reads "nothing
    matched" as "there are none", so asking about open work orders got the
    answer "there are no open work orders" while one sat in the table.
    """
    schema = next(
        s for s in agent_tools.TOOL_SCHEMAS if s["function"]["name"] == "list_work_orders"
    )
    offered = set(schema["function"]["parameters"]["properties"]["status"]["enum"])
    assert offered == workflow.WORK_ORDER_STATUSES


def test_an_unknown_work_order_status_is_reported_not_filtered_on(db):
    result = agent_tools.list_work_orders(db, MANUFACTURER_SCOPE, status="open")
    assert result["found"] is False
    assert "draft" in result["message"]


def _distinct(db, column) -> set[str]:
    return {value for (value,) in db.execute(select(column).distinct()) if value}


def test_every_enum_a_tool_offers_is_a_value_the_data_can_hold(db):
    """Walk the schemas and check each enum against its source of truth.

    Every enum has to be listed here deliberately - an unreviewed one fails the
    test rather than passing by default, because the whole failure mode is a
    value that looks right and does not exist.

    Where there is a named constant, that is the authority. Where the
    vocabulary only lives in the data (notification severity and audience are
    written by the generator and never declared), the seeded rows are, so an
    invented value is still caught.
    """
    tiers = _distinct(db, Prediction.risk_tier)
    known = {
        ("list_vehicles_by_risk", "tier"): tiers,
        ("find_vehicles", "tier"): tiers,
        ("list_work_orders", "status"): workflow.WORK_ORDER_STATUSES,
        ("get_notifications", "audience"): _distinct(db, Notification.audience),
        ("get_notifications", "severity"): _distinct(db, Notification.severity),
        ("get_cost_exposure", "dimension"): set(insights.COST_DIMENSIONS),
        ("list_maintenance_due", "band"): {
            "overdue",
            "within_30_days",
            "within_90_days",
            "healthy",
        },
    }
    checked = 0
    for schema in agent_tools.TOOL_SCHEMAS:
        name = schema["function"]["name"]
        for field, spec in schema["function"]["parameters"].get("properties", {}).items():
            if "enum" not in spec:
                continue
            expected = known.get((name, field))
            assert expected is not None, f"unreviewed enum: {name}.{field}"
            assert set(spec["enum"]) == expected, f"{name}.{field}"
            checked += 1
    assert checked >= 7
