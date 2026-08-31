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

from app.models import Part, Prediction, Vehicle
from app.services import agent_tools
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
