"""Scope isolation - the requirement spec section 3 calls the most important one.

The claim being tested is narrow and absolute: with the scope switcher set to
customer A, there is no request that returns customer B's data. Not a filtered
list that happens to look right, and not a detail endpoint that leaks by
direct VIN lookup.

Every list endpoint is checked for foreign rows, every detail endpoint is
checked for a 404 on a known-good VIN belonging to the other tenant, and the
aggregates are checked for the arithmetic that would give a leak away - a
customer view whose vehicle count matches the whole fleet is not scoped, it is
merely filtered somewhere cosmetic.
"""

from __future__ import annotations

import csv
import io

from app.services.scoping import (
    MANUFACTURER_SCOPE,
    Scope,
    customer_scope,
    viewer_scope,
)

# --- the Scope object itself -------------------------------------------------


def test_manufacturer_scope_sees_everything():
    assert MANUFACTURER_SCOPE.is_manufacturer is True
    assert MANUFACTURER_SCOPE.customer_id is None
    assert MANUFACTURER_SCOPE.can_manage_rules is True
    assert MANUFACTURER_SCOPE.can_write is True


def test_customer_scope_is_bounded_and_cannot_author_rules():
    scope = customer_scope(4)
    assert scope.is_manufacturer is False
    assert scope.customer_id == 4
    assert scope.can_write is True
    assert scope.can_manage_rules is False


def test_viewer_cannot_write():
    scope = viewer_scope(4)
    assert scope.can_write is False
    assert scope.can_manage_rules is False


def test_scope_is_immutable():
    """A scope that could be reassigned mid-request is a scope that will be."""
    scope = Scope(customer_id=2, role="customer_admin")
    try:
        scope.customer_id = None
    except Exception as exc:  # frozen dataclass raises FrozenInstanceError
        assert "customer_id" in str(exc) or "frozen" in str(exc).lower()
    else:
        raise AssertionError("Scope must be immutable once resolved.")


# --- list endpoints do not leak rows ----------------------------------------


def test_predictions_are_limited_to_the_scoped_customer(client, as_customer, customer_a):
    body = client.get("/api/predictions?limit=200", headers=as_customer).json()
    assert body["items"], "expected the scoped customer to own some predictions"
    assert {row["customer_id"] for row in body["items"]} == {customer_a}


def test_vehicles_are_limited_to_the_scoped_customer(client, as_customer, customer_a):
    body = client.get("/api/vehicles?limit=200", headers=as_customer).json()
    assert body["items"]
    assert {row["customer_id"] for row in body["items"]} == {customer_a}


def test_rul_is_limited_to_the_scoped_customer(client, as_customer, customer_a):
    body = client.get("/api/rul?limit=200", headers=as_customer).json()
    assert body["items"]
    assert {row["customer_id"] for row in body["items"]} == {customer_a}


def test_notifications_are_limited_to_the_scoped_customer(client, as_customer, customer_a):
    body = client.get("/api/notifications?limit=200", headers=as_customer).json()
    assert body["items"]
    assert {row["customer_id"] for row in body["items"]} == {customer_a}


def test_customers_list_shows_only_the_caller(client, as_customer, customer_a):
    body = client.get("/api/customers", headers=as_customer).json()
    assert [row["customer_id"] for row in body] == [customer_a]


def test_csv_export_is_scoped(client, as_customer, customer_names, customer_a):
    response = client.get("/api/export/predictions.csv", headers=as_customer)
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows
    assert {row["customer_name"] for row in rows} == {customer_names[customer_a]}


# --- detail endpoints do not leak by direct lookup ---------------------------


def test_another_customers_vehicle_is_not_found(client, as_customer, vehicle_of_b):
    response = client.get(f"/api/vehicles/{vehicle_of_b.vin}", headers=as_customer)
    assert response.status_code == 404


def test_another_customers_prediction_is_not_found(client, as_customer, prediction_of_b):
    response = client.get(
        f"/api/predictions/{prediction_of_b.vin}/{prediction_of_b.part_code}",
        headers=as_customer,
    )
    assert response.status_code == 404


def test_another_customers_rul_is_not_found(client, as_customer, prediction_of_b):
    response = client.get(
        f"/api/rul/{prediction_of_b.vin}/{prediction_of_b.part_code}",
        headers=as_customer,
    )
    assert response.status_code == 404


def test_the_same_vehicle_is_visible_to_its_own_customer(client, vehicle_of_b, customer_b):
    """The 404s above must be about scope, not about a broken lookup."""
    response = client.get(
        f"/api/vehicles/{vehicle_of_b.vin}",
        headers={"X-Customer-Scope": str(customer_b)},
    )
    assert response.status_code == 200
    assert response.json()["customer_id"] == customer_b


def test_a_missing_vin_and_a_foreign_vin_answer_identically(
    client, as_customer, vehicle_of_b
):
    """Probing must not distinguish "not yours" from "does not exist"."""
    foreign = client.get(f"/api/vehicles/{vehicle_of_b.vin}", headers=as_customer)
    missing = client.get("/api/vehicles/DEFINITELYNOTAVIN", headers=as_customer)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"]


# --- filters cannot be used to widen the scope -------------------------------


def test_customer_filter_cannot_reach_another_tenant(client, as_customer, customer_b):
    """Asking for customer B's rows while scoped to A returns nothing, not B."""
    body = client.get(
        f"/api/predictions?customer_id={customer_b}&limit=200", headers=as_customer
    ).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_cannot_reach_another_tenant(client, as_customer, vehicle_of_b):
    body = client.get(
        f"/api/predictions?search={vehicle_of_b.vin}&limit=50", headers=as_customer
    ).json()
    assert body["total"] == 0


def test_work_order_filter_cannot_reach_another_tenant(client, as_customer, customer_b):
    body = client.get(
        f"/api/work-orders?customer_id={customer_b}&limit=50", headers=as_customer
    ).json()
    assert body["total"] == 0


# --- aggregates are scoped, not merely filtered ------------------------------


def test_overview_totals_shrink_under_a_customer_scope(client, as_customer):
    everything = client.get("/api/overview").json()["kpis"]
    scoped = client.get("/api/overview", headers=as_customer).json()["kpis"]

    assert scoped["vehicles_monitored"] < everything["vehicles_monitored"]
    assert scoped["total_cost_exposure"] < everything["total_cost_exposure"]
    assert scoped["red_count"] <= everything["red_count"]


def test_overview_cost_by_customer_has_one_row_when_scoped(
    client, as_customer, customer_a
):
    rows = client.get("/api/overview", headers=as_customer).json()["cost_by_customer"]
    assert [row["customer_id"] for row in rows] == [customer_a]


def test_fleet_comparison_shows_only_the_caller_but_keeps_the_benchmark(
    client, as_customer, customer_a
):
    """A customer should see where they stand without seeing a rival's numbers."""
    body = client.get("/api/analytics/fleet-comparison", headers=as_customer).json()
    assert [row["customer_id"] for row in body["rows"]] == [customer_a]
    # The fleet mean is computed over everyone - that is the point of a benchmark.
    assert body["fleet_mean_health_index"] > 0


def test_cost_exposure_by_customer_is_scoped(client, as_customer):
    everything = client.get("/api/analytics/cost-exposure?dimension=customer").json()
    scoped = client.get(
        "/api/analytics/cost-exposure?dimension=customer", headers=as_customer
    ).json()
    assert len(scoped["rows"]) == 1
    assert len(everything["rows"]) > 1
    assert scoped["total_exposure"] < everything["total_exposure"]


def test_part_history_counts_shrink_under_a_customer_scope(client, as_customer, any_prediction):
    part = any_prediction.part_code
    everything = client.get(f"/api/parts/{part}/history").json()
    scoped = client.get(f"/api/parts/{part}/history", headers=as_customer).json()
    assert scoped["total_failures"] < everything["total_failures"]


# --- role capability -----------------------------------------------------------


def test_a_customer_scope_cannot_deploy_a_rule(client, as_customer, any_prediction):
    response = client.post(
        "/api/rules",
        json={"part_code": any_prediction.part_code},
        headers=as_customer,
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_a_customer_scope_can_still_read_the_rule(client, as_customer, any_prediction):
    """Read-only on rules, not blind to them - the customer must see why they were alerted."""
    response = client.get(f"/api/rules/{any_prediction.part_code}", headers=as_customer)
    assert response.status_code == 200
    assert response.json()["formula"].startswith("failure_probability =")


def test_auth_me_reports_the_scope_switcher_state(client, as_customer, customer_a):
    body = client.get("/api/auth/me", headers=as_customer).json()
    assert body["customer_id"] == customer_a
    assert body["is_manufacturer"] is False
    assert body["can_manage_rules"] is False

    manufacturer = client.get("/api/auth/me").json()
    assert manufacturer["customer_id"] is None
    assert manufacturer["is_manufacturer"] is True
    assert manufacturer["can_manage_rules"] is True


# --- the header itself ---------------------------------------------------------


def test_an_unparseable_scope_header_is_rejected(client):
    response = client.get("/api/overview", headers={"X-Customer-Scope": "banana"})
    assert response.status_code == 400


def test_an_unknown_customer_scope_is_rejected(client):
    response = client.get("/api/overview", headers={"X-Customer-Scope": "999999"})
    assert response.status_code == 404


def test_all_is_the_manufacturer_view(client):
    body = client.get("/api/auth/me", headers={"X-Customer-Scope": "all"}).json()
    assert body["is_manufacturer"] is True
