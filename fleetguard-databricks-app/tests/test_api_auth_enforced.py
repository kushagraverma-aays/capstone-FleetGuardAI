"""The same API with `AUTH_ENABLED=true`.

Spec section 3 promises that turning authentication on changes the dependency
and nothing else - the route code, the response shapes and the scoping rules
are identical. That promise is only worth something if the enforced path is
actually exercised, so these tests flip the flag and re-run the same
assertions against tokens instead of the scope header.

The one behaviour that *is* different is deliberate and is the security
property: with a token bound to a tenant, the `X-Customer-Scope` header can no
longer widen the view. It is refused outright rather than quietly ignored.
"""

from __future__ import annotations

import pytest

from app.config import settings

DEMO_PASSWORD = "fleetguard"
MANUFACTURER = "admin@fleetguard.ai"
CUSTOMER_ADMIN = "fleet@sarthilogistics.in"
VIEWER = "viewer@bluelinecarriers.in"

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture
def auth_on(monkeypatch):
    """Turn enforcement on for one test.

    The dependency reads `settings.AUTH_ENABLED` per request, so flipping the
    attribute is enough - no app rebuild, which is itself evidence that the
    routes do not care which mode they are in.
    """
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


def token_for(client, email: str) -> str:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- enforcement -------------------------------------------------------------


def test_without_a_token_every_endpoint_is_401(client, auth_on):
    for path in ("/api/overview", "/api/predictions", "/api/vehicles", "/api/auth/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"] == "unauthenticated"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_garbage_token_is_401(client, auth_on):
    response = client.get("/api/overview", headers=bearer("not.a.jwt"))
    assert response.status_code == 401


def test_health_stays_open(client, auth_on):
    """A liveness probe that needs a token is a liveness probe that fails."""
    assert client.get("/api/health").status_code == 200


def test_login_still_works_with_enforcement_on(client, auth_on):
    assert token_for(client, MANUFACTURER)


# --- the manufacturer token --------------------------------------------------


def test_a_manufacturer_token_sees_the_whole_fleet(client, auth_on):
    headers = bearer(token_for(client, MANUFACTURER))
    body = client.get("/api/auth/me", headers=headers).json()
    assert body["is_manufacturer"] is True
    assert body["email"] == MANUFACTURER
    assert body["auth_enabled"] is True

    customers = client.get("/api/customers", headers=headers).json()
    assert len(customers) > 1


def test_a_manufacturer_token_can_narrow_with_the_scope_header(client, auth_on, customer_a):
    headers = {**bearer(token_for(client, MANUFACTURER)), "X-Customer-Scope": str(customer_a)}
    body = client.get("/api/predictions?limit=100", headers=headers).json()
    assert body["items"]
    assert {row["customer_id"] for row in body["items"]} == {customer_a}


# --- the customer token ------------------------------------------------------


def test_a_customer_token_is_bound_to_its_own_tenant(client, auth_on):
    headers = bearer(token_for(client, CUSTOMER_ADMIN))
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["is_manufacturer"] is False
    own = me["customer_id"]

    body = client.get("/api/predictions?limit=200", headers=headers).json()
    assert body["items"]
    assert {row["customer_id"] for row in body["items"]} == {own}


def test_a_customer_token_cannot_widen_with_the_scope_header(client, auth_on):
    """The header is refused, not ignored - a broken client must learn it failed."""
    token = token_for(client, CUSTOMER_ADMIN)
    me = client.get("/api/auth/me", headers=bearer(token)).json()
    other = me["customer_id"] + 1

    # "all" is manufacturer scope, which this token does not have. It is
    # refused rather than quietly narrowed back: no other customer's rows were
    # ever reachable either way, but a client that asked to widen and got a 200
    # has been told it succeeded.
    widened = client.get(
        "/api/predictions", headers={**bearer(token), "X-Customer-Scope": "all"}
    )
    assert widened.status_code == 403
    assert widened.json()["error"] == "forbidden"

    switched = client.get(
        "/api/predictions", headers={**bearer(token), "X-Customer-Scope": str(other)}
    )
    assert switched.status_code == 403
    assert switched.json()["error"] == "forbidden"


def test_a_customer_token_cannot_read_another_tenants_vehicle(client, auth_on, db):
    from sqlalchemy import select

    from app.models import Vehicle

    token = token_for(client, CUSTOMER_ADMIN)
    me = client.get("/api/auth/me", headers=bearer(token)).json()

    foreign = db.execute(
        select(Vehicle).where(Vehicle.customer_id != me["customer_id"]).limit(1)
    ).scalars().first()

    response = client.get(f"/api/vehicles/{foreign.vin}", headers=bearer(token))
    assert response.status_code == 404


def test_a_customer_token_cannot_deploy_a_rule(client, auth_on, any_prediction):
    response = client.post(
        "/api/rules",
        json={"part_code": any_prediction.part_code},
        headers=bearer(token_for(client, CUSTOMER_ADMIN)),
    )
    assert response.status_code == 403


# --- the viewer token --------------------------------------------------------


def test_a_viewer_can_read(client, auth_on):
    headers = bearer(token_for(client, VIEWER))
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["role"] == "viewer"
    assert me["can_write"] is False

    assert client.get("/api/overview", headers=headers).status_code == 200
    assert client.get("/api/predictions?limit=5", headers=headers).status_code == 200


def test_a_viewer_cannot_acknowledge_an_alert(client, auth_on, db):
    from sqlalchemy import select

    from app.models import Notification

    headers = bearer(token_for(client, VIEWER))
    me = client.get("/api/auth/me", headers=headers).json()

    notification = db.execute(
        select(Notification).where(Notification.customer_id == me["customer_id"]).limit(1)
    ).scalars().first()
    if notification is None:
        pytest.skip("The viewer's tenant has no alerts to attempt.")

    response = client.patch(
        f"/api/notifications/{notification.id}",
        json={"status": "acknowledged"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_a_viewer_cannot_raise_a_work_order(client, auth_on, any_prediction):
    response = client.post(
        "/api/work-orders",
        json={"vin": any_prediction.vin, "part_code": any_prediction.part_code},
        headers=bearer(token_for(client, VIEWER)),
    )
    assert response.status_code == 403


# --- the flag really is the only difference ----------------------------------


def test_the_same_route_serves_both_modes_identically(client, auth_on, customer_a, monkeypatch):
    """Same URL, same shape, whether scope came from a header or a token."""
    with_token = client.get(
        "/api/predictions?limit=5&sort=probability",
        headers={
            **bearer(token_for(client, MANUFACTURER)),
            "X-Customer-Scope": str(customer_a),
        },
    ).json()

    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    with_header = client.get(
        "/api/predictions?limit=5&sort=probability",
        headers={"X-Customer-Scope": str(customer_a)},
    ).json()

    assert with_token["total"] == with_header["total"]
    assert [r["vin"] for r in with_token["items"]] == [
        r["vin"] for r in with_header["items"]
    ]
    assert with_token["items"][0].keys() == with_header["items"][0].keys()


# --- a token is honoured whether or not it is required -----------------------
#
# `AUTH_ENABLED` decides what happens when there is *no* token. A token that is
# presented always drives role and tenant. That is what makes the sign-in
# screen mean something during the demo - signing in as the viewer genuinely
# removes write actions - and it is why turning the flag on later changes
# nothing anybody can see.


def test_a_token_drives_scope_even_with_enforcement_off(client):
    assert settings.AUTH_ENABLED is False
    token = token_for(client, CUSTOMER_ADMIN)

    me = client.get("/api/auth/me", headers=bearer(token)).json()
    assert me["email"] == CUSTOMER_ADMIN
    assert me["is_manufacturer"] is False
    assert me["customer_id"] is not None

    # And the data follows the token, not the default manufacturer view.
    scoped = client.get("/api/vehicles?limit=5", headers=bearer(token)).json()
    assert {row["customer_id"] for row in scoped["items"]} == {me["customer_id"]}


def test_a_viewer_token_is_read_only_with_enforcement_off(client):
    """The role picked at sign-in has to have teeth, or it is theatre."""
    assert settings.AUTH_ENABLED is False
    token = token_for(client, VIEWER)

    me = client.get("/api/auth/me", headers=bearer(token)).json()
    assert me["role"] == "viewer"
    assert me["can_write"] is False

    response = client.post(
        "/api/work-orders",
        headers=bearer(token),
        json={"vin": "IRRELEVANT", "part_code": "IRRELEVANT", "priority": "high"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_a_customer_token_still_cannot_be_widened_by_the_header(client):
    """The header may narrow a manufacturer session, never widen a tenant one."""
    assert settings.AUTH_ENABLED is False
    token = token_for(client, CUSTOMER_ADMIN)
    response = client.get(
        "/api/vehicles", headers={**bearer(token), "X-Customer-Scope": "all"}
    )
    assert response.status_code == 403


def test_no_token_still_falls_back_to_the_scope_header(client, as_customer):
    """The existing demo path is untouched: no token, header decides."""
    assert settings.AUTH_ENABLED is False
    me = client.get("/api/auth/me", headers=as_customer).json()
    assert me["is_manufacturer"] is False
    assert client.get("/api/auth/me").json()["is_manufacturer"] is True


# --- the demo accounts the login screen offers -------------------------------


def test_demo_accounts_lists_one_sign_in_per_role(client):
    payload = client.get("/api/auth/demo-accounts").json()
    roles = {account["role"] for account in payload["accounts"]}
    assert roles == {"manufacturer_admin", "customer_admin", "viewer"}
    for account in payload["accounts"]:
        assert account["role_label"]
        assert account["description"]


def test_every_demo_account_actually_signs_in(client):
    """A login screen offering a credential that does not work is worse than none."""
    for account in client.get("/api/auth/demo-accounts").json()["accounts"]:
        response = client.post(
            "/api/auth/login",
            json={"email": account["email"], "password": account["password"]},
        )
        assert response.status_code == 200, account["email"]
        assert response.json()["role"] == account["role"]


def test_demo_accounts_disappear_once_authentication_is_enforced(client, auth_on):
    """Handing out working credentials is only defensible while nothing is protected."""
    assert client.get("/api/auth/demo-accounts").status_code == 404
