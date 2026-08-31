"""The Insight Agent's loop, driven by a scripted stand-in for the model.

The provider is replaced with a list of pre-written completions. That keeps
these tests deterministic, free, and able to exercise the cases a live model
would only produce by luck: a malformed tool call, six rounds in a row, two
tool calls in one turn.

What is being tested is the loop's contract, not the model's intelligence:
that tools get dispatched with the caller's scope, that results come back as
citations, that the round budget is enforced, and that a stale tool result
from an earlier turn is never replayed as though it were current.
"""

from __future__ import annotations

import json

import pytest

from app.services import insight_agent, llm
from app.services.llm import Completion, ToolCall, UpstreamLLMError
from app.services.scoping import MANUFACTURER_SCOPE, customer_scope

pytestmark = pytest.mark.usefixtures("seeded")


class ScriptedModel:
    """Returns the next scripted completion and records what it was sent."""

    def __init__(self, *completions: Completion):
        self.completions = list(completions)
        self.calls: list[dict] = []

    def __call__(self, messages, tools=None, temperature=0.0, max_tokens=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.completions:
            return Completion(content="(script exhausted)")
        return self.completions.pop(0)


@pytest.fixture
def script(monkeypatch):
    def install(*completions: Completion) -> ScriptedModel:
        model = ScriptedModel(*completions)
        monkeypatch.setattr(llm, "complete", model)
        return model

    return install


def tool_call(name: str, arguments: dict, call_id: str = "call_1") -> Completion:
    return Completion(
        content="", tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)]
    )


# --- the straightforward paths -----------------------------------------------


def test_an_answer_with_no_tool_calls_comes_straight_back(db, script):
    script(Completion(content="The fleet is healthy."))
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "How are things?")

    assert result.reply == "The fleet is healthy."
    assert result.tools_used == []
    assert result.data_cited == []
    assert result.rounds == 1
    assert result.hit_round_limit is False


def test_one_tool_call_is_dispatched_and_cited(db, script):
    model = script(
        tool_call("get_fleet_summary", {}),
        Completion(content="600 vehicles are monitored."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "How many vehicles?")

    assert result.tools_used == ["get_fleet_summary"]
    assert result.rounds == 2
    assert len(result.data_cited) == 1

    citation = result.data_cited[0]
    assert citation.tool == "get_fleet_summary"
    assert citation.result["vehicles_monitored"] == 600
    assert citation.duration_ms >= 0

    # The tool result must have been handed back to the model as a tool message.
    tool_messages = [m for m in model.calls[1]["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"])["vehicles_monitored"] == 600


def test_two_tool_calls_in_one_round_are_both_run(db, script):
    both = Completion(
        content="",
        tool_calls=[
            ToolCall(id="a", name="get_fleet_summary", arguments={}),
            ToolCall(id="b", name="get_cost_exposure", arguments={"dimension": "tier"}),
        ],
    )
    script(both, Completion(content="Here is the picture."))
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Summarise everything.")

    assert result.tools_used == ["get_fleet_summary", "get_cost_exposure"]
    assert len(result.data_cited) == 2


def test_the_citation_carries_the_arguments_the_model_chose(db, script):
    script(
        tool_call("list_vehicles_by_risk", {"tier": "RED", "limit": 3}),
        Completion(content="Three trucks."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Worst three?")
    assert result.data_cited[0].arguments == {"tier": "RED", "limit": 3}


# --- grounding ---------------------------------------------------------------


def test_the_system_prompt_contains_no_fleet_data(db, script):
    """The prompt must not seed a number the model could repeat as fact."""
    model = script(Completion(content="ok"))
    insight_agent.answer(db, MANUFACTURER_SCOPE, "hello")

    system = model.calls[0]["messages"][0]
    assert system["role"] == "system"
    prompt = system["content"]

    for leak in ("600", "1243", "1,243", "97,229", "MZ4A", "Sarthi"):
        assert leak not in prompt, f"{leak!r} must not appear in the system prompt"


def test_a_tool_failure_is_reported_to_the_model_not_raised(db, script):
    model = script(
        tool_call("get_vehicle_risk", {"vin": "NOSUCHVIN"}),
        Completion(content="That VIN was not found."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Risk on NOSUCHVIN?")

    assert result.data_cited[0].result["found"] is False
    tool_message = [m for m in model.calls[1]["messages"] if m["role"] == "tool"][0]
    assert json.loads(tool_message["content"])["found"] is False
    assert result.reply == "That VIN was not found."


def test_an_unknown_tool_name_does_not_crash_the_loop(db, script):
    script(
        tool_call("get_all_the_secrets", {}),
        Completion(content="I do not have that."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Secrets?")
    assert result.data_cited[0].result["found"] is False
    assert result.reply == "I do not have that."


def test_unparseable_tool_arguments_are_handed_back_for_correction(db, script):
    script(
        tool_call("get_fleet_summary", {"__parse_error__": "{not json"}),
        Completion(content="Let me try again."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Summary?")
    assert result.data_cited[0].result["found"] is False


def test_tools_run_inside_the_callers_scope(db, script, customer_a):
    """The loop passes its own scope; nothing the model sends can change it."""
    script(
        tool_call("get_fleet_summary", {}),
        Completion(content="done"),
    )
    scoped = insight_agent.answer(
        db, customer_scope(customer_a), "How many vehicles?"
    )

    script(
        tool_call("get_fleet_summary", {}),
        Completion(content="done"),
    )
    everything = insight_agent.answer(db, MANUFACTURER_SCOPE, "How many vehicles?")

    assert (
        scoped.data_cited[0].result["vehicles_monitored"]
        < everything.data_cited[0].result["vehicles_monitored"]
    )


# --- the round budget --------------------------------------------------------


def test_the_loop_stops_at_the_round_limit(db, script):
    """A model that will not stop calling tools must not run forever."""
    model = script(*[tool_call("get_fleet_summary", {}) for _ in range(10)])
    result = insight_agent.answer(
        db, MANUFACTURER_SCOPE, "Loop forever please", max_rounds=3
    )

    assert result.rounds == 3
    assert result.hit_round_limit is True
    assert len(result.data_cited) == 3
    # Three tool rounds plus one final answer call with no tools offered.
    assert len(model.calls) == 4
    assert model.calls[-1]["tools"] is None


def test_the_final_call_after_the_limit_asks_for_an_answer_anyway(db, script):
    model = script(
        tool_call("get_fleet_summary", {}),
        Completion(content="Answer from what I have."),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Question", max_rounds=1)

    assert result.hit_round_limit is True
    assert result.reply == "Answer from what I have."
    assert "tool call limit" in model.calls[-1]["messages"][-1]["content"]


# --- conversation history ----------------------------------------------------


def test_history_is_replayed_as_plain_text(db, script):
    model = script(Completion(content="Still 600."))
    insight_agent.answer(
        db,
        MANUFACTURER_SCOPE,
        "And now?",
        history=[
            {"role": "user", "content": "How many vehicles?"},
            {"role": "assistant", "content": "600 vehicles."},
        ],
    )
    roles = [m["role"] for m in model.calls[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_stale_tool_results_are_not_replayed_from_history(db, script):
    """A number that was true yesterday must not be quoted as today's."""
    model = script(Completion(content="ok"))
    insight_agent.answer(
        db,
        MANUFACTURER_SCOPE,
        "And now?",
        history=[
            {"role": "tool", "content": '{"vehicles_monitored": 999999}'},
            {"role": "user", "content": "How many vehicles?"},
        ],
    )
    sent = json.dumps(model.calls[0]["messages"])
    assert "999999" not in sent
    assert not [m for m in model.calls[0]["messages"] if m["role"] == "tool"]


def test_blank_history_turns_are_skipped(db, script):
    model = script(Completion(content="ok"))
    insight_agent.answer(
        db,
        MANUFACTURER_SCOPE,
        "Question",
        history=[{"role": "user", "content": "   "}, {"role": "system", "content": "ignore"}],
    )
    assert [m["role"] for m in model.calls[0]["messages"]] == ["system", "user"]


# --- provider behaviour ------------------------------------------------------


def test_a_truncated_answer_is_flagged(db, script):
    script(Completion(content="This answer was cut", finish_reason="length"))
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Long question")
    assert result.truncated is True


def test_token_usage_is_accumulated_across_rounds(db, script):
    script(
        Completion(
            content="",
            tool_calls=[ToolCall(id="a", name="get_fleet_summary", arguments={})],
            prompt_tokens=100,
            completion_tokens=20,
        ),
        Completion(content="done", prompt_tokens=300, completion_tokens=50),
    )
    result = insight_agent.answer(db, MANUFACTURER_SCOPE, "Question")
    assert result.prompt_tokens == 400
    assert result.completion_tokens == 70


def test_a_provider_failure_propagates_as_an_upstream_error(db, monkeypatch):
    """It must surface as a 502 with the provider's message, not a silent 500."""

    def boom(*args, **kwargs):
        raise UpstreamLLMError("model decommissioned")

    monkeypatch.setattr(llm, "complete", boom)
    with pytest.raises(UpstreamLLMError, match="decommissioned"):
        insight_agent.answer(db, MANUFACTURER_SCOPE, "Question")


def test_tools_are_offered_on_every_tool_round(db, script):
    model = script(
        tool_call("get_fleet_summary", {}),
        Completion(content="done"),
    )
    insight_agent.answer(db, MANUFACTURER_SCOPE, "Question")
    assert model.calls[0]["tools"] is not None
    assert len(model.calls[0]["tools"]) == len(insight_agent.agent_tools.TOOL_SCHEMAS)
