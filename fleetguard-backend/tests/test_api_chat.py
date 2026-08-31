"""The assistant endpoints.

The provider is stubbed throughout. These tests are about the HTTP contract -
scope, validation, rate limiting, error mapping and the shape of the citation
payload the UI depends on - not about whether the model writes good English.

`limiter.reset()` runs around every test in this module. slowapi keeps its
counters in process memory, so without that a test that deliberately trips the
limit would leave every later test rate limited.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.rate_limit import limiter
from app.services import llm
from app.services.llm import Completion, ToolCall, UpstreamLLMError

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture(autouse=True)
def clean_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def stub_llm(monkeypatch):
    """A model that calls one tool, then answers from its result.

    The decision keys off whether a tool result is already in the transcript
    rather than off a call counter, so the stub behaves the same on the second
    request of a test as on the first.
    """
    state = {"calls": 0}

    def fake(messages, tools=None, temperature=0.0, max_tokens=None):
        state["calls"] += 1
        already_ran = any(m.get("role") == "tool" for m in messages)
        if tools and not already_ran:
            return Completion(
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="get_fleet_summary", arguments={})
                ],
            )
        return Completion(content="600 vehicles are monitored, 1,243 components are red.")

    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    return state


@pytest.fixture
def stub_draft(monkeypatch):
    def fake(messages, tools=None, temperature=0.0, max_tokens=None):
        assert tools is None, "the Action Agent must never be given tools"
        return Completion(content="Please stock one Radiator Fan for VIN X within 5 days.")

    monkeypatch.setattr(llm, "complete", fake)
    monkeypatch.setattr(llm, "is_configured", lambda: True)


# --- capabilities ------------------------------------------------------------


def test_capabilities_lists_every_tool(client):
    body = client.get("/api/chat").json()
    assert body["model"] == settings.LLM_MODEL
    assert body["max_tool_rounds"] == settings.AGENT_MAX_TOOL_ROUNDS
    assert len(body["tools"]) >= 9
    assert body["suggested_questions"]
    assert all(t["name"] and t["description"] for t in body["tools"])


def test_capabilities_needs_no_llm_key(client, monkeypatch):
    """The panel must still render its empty state on an unconfigured install."""
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    body = client.get("/api/chat").json()
    assert body["available"] is False
    assert body["tools"]


# --- chat --------------------------------------------------------------------


def test_chat_returns_a_reply_with_citations(client, stub_llm):
    body = client.post("/api/chat", json={"message": "How many vehicles?"}).json()

    assert body["reply"]
    assert body["tools_used"] == ["get_fleet_summary"]
    assert body["rounds"] == 2
    assert body["truncated"] is False
    assert body["hit_round_limit"] is False

    citation = body["data_cited"][0]
    assert citation["tool"] == "get_fleet_summary"
    assert citation["result"]["vehicles_monitored"] == 600
    assert "duration_ms" in citation


def test_chat_citations_carry_the_raw_tool_result(client, stub_llm):
    """The UI expands a citation chip into this - it has to be the real JSON."""
    body = client.post("/api/chat", json={"message": "Summary"}).json()
    result = body["data_cited"][0]["result"]
    assert result["found"] is True
    assert "total_cost_exposure" in result


def test_chat_is_scoped(client, stub_llm, as_customer):
    scoped = client.post(
        "/api/chat", json={"message": "How many?"}, headers=as_customer
    ).json()
    everything = client.post("/api/chat", json={"message": "How many?"}).json()

    assert (
        scoped["data_cited"][0]["result"]["vehicles_monitored"]
        < everything["data_cited"][0]["result"]["vehicles_monitored"]
    )


def test_chat_rejects_an_empty_message(client, stub_llm):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_chat_rejects_an_overlong_message(client, stub_llm):
    assert client.post("/api/chat", json={"message": "x" * 5000}).status_code == 422


def test_chat_accepts_history(client, stub_llm):
    response = client.post(
        "/api/chat",
        json={
            "message": "And now?",
            "history": [
                {"role": "user", "content": "How many vehicles?"},
                {"role": "assistant", "content": "600."},
            ],
        },
    )
    assert response.status_code == 200


def test_chat_reports_an_unconfigured_provider_as_503(client, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["message"]


def test_a_provider_failure_becomes_a_502_carrying_its_message(client, monkeypatch):
    def boom(*args, **kwargs):
        raise UpstreamLLMError("rate limit exceeded on the provider")

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "complete", boom)

    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "llm_unavailable"
    assert "rate limit exceeded" in body["provider_message"]


# --- draft -------------------------------------------------------------------


def test_draft_writes_a_message_from_verified_facts(client, stub_draft, any_prediction):
    body = client.post(
        "/api/chat/draft",
        json={
            "vin": any_prediction.vin,
            "part": any_prediction.part_code,
            "audience": "vendor",
        },
    ).json()

    assert body["message"]
    assert body["audience"] == "vendor"
    assert body["vin"] == any_prediction.vin
    # The facts are returned so a reviewer can check the message against them.
    assert body["facts"]["vin"] == any_prediction.vin
    assert "unplanned_failure_cost" in body["facts"]


def test_draft_facts_are_the_models_entire_universe(client, stub_draft, any_prediction):
    """Whatever is in `facts` is all the model had; it has no tools."""
    body = client.post(
        "/api/chat/draft",
        json={"vin": any_prediction.vin, "part": any_prediction.part_code, "audience": "fleet_owner"},
    ).json()
    facts = body["facts"]
    for required in ("component", "risk_tier", "remaining_life_days", "saving_if_replaced_on_plan"):
        assert required in facts


def test_draft_rejects_an_unknown_audience(client, stub_draft, any_prediction):
    response = client.post(
        "/api/chat/draft",
        json={"vin": any_prediction.vin, "part": any_prediction.part_code, "audience": "regulator"},
    )
    assert response.status_code == 422
    assert "vendor" in response.json()["message"]


def test_draft_refuses_an_unknown_vin(client, stub_draft, any_prediction):
    response = client.post(
        "/api/chat/draft",
        json={"vin": "NOSUCHVIN", "part": any_prediction.part_code, "audience": "vendor"},
    )
    assert response.status_code == 422
    assert "NOSUCHVIN" in response.json()["message"]


def test_draft_refuses_an_unknown_component(client, stub_draft, any_prediction):
    response = client.post(
        "/api/chat/draft",
        json={"vin": any_prediction.vin, "part": "Flux Capacitor", "audience": "vendor"},
    )
    assert response.status_code == 422
    assert "Alternator" in response.json()["message"]


def test_draft_cannot_reach_another_customers_vehicle(
    client, stub_draft, as_customer, prediction_of_b
):
    response = client.post(
        "/api/chat/draft",
        json={
            "vin": prediction_of_b.vin,
            "part": prediction_of_b.part_code,
            "audience": "vendor",
        },
        headers=as_customer,
    )
    assert response.status_code == 422
    assert "another customer" in response.json()["message"]


def test_draft_accepts_a_component_name_not_just_a_code(client, stub_draft, any_prediction, db):
    from app.models import Part

    part = db.get(Part, any_prediction.part_code)
    response = client.post(
        "/api/chat/draft",
        json={"vin": any_prediction.vin, "part": part.part_name, "audience": "vendor"},
    )
    assert response.status_code == 200
    assert response.json()["part"] == part.part_name


# --- rate limiting -----------------------------------------------------------


def test_the_chat_endpoint_is_rate_limited(client, stub_llm):
    """Spec section 10. These are the only endpoints that cost money per call."""
    allowed = int(settings.CHAT_RATE_LIMIT.split("/")[0])

    statuses = [
        client.post("/api/chat", json={"message": "ping"}).status_code
        for _ in range(allowed + 2)
    ]

    assert statuses[0] == 200
    assert 429 in statuses, f"expected a 429 within {allowed + 2} calls, got {set(statuses)}"
    assert statuses.count(200) <= allowed


def test_the_rate_limit_response_uses_the_standard_error_envelope(client, stub_llm):
    allowed = int(settings.CHAT_RATE_LIMIT.split("/")[0])
    response = None
    for _ in range(allowed + 2):
        response = client.post("/api/chat", json={"message": "ping"})
        if response.status_code == 429:
            break

    assert response.status_code == 429
    body = response.json()
    assert body["error"] == "rate_limited"
    assert settings.CHAT_RATE_LIMIT in body["message"]


def test_the_draft_endpoint_is_rate_limited(client, stub_draft, any_prediction):
    allowed = int(settings.CHAT_RATE_LIMIT.split("/")[0])
    payload = {
        "vin": any_prediction.vin,
        "part": any_prediction.part_code,
        "audience": "vendor",
    }
    statuses = [
        client.post("/api/chat/draft", json=payload).status_code
        for _ in range(allowed + 2)
    ]
    assert 429 in statuses


def test_reading_endpoints_are_not_rate_limited(client):
    """Only the endpoints that call the provider are limited."""
    statuses = {client.get("/api/overview").status_code for _ in range(30)}
    assert statuses == {200}
