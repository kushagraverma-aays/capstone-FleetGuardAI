"""The Insight Agent: a bounded, grounded tool-calling loop (spec section 7).

The design constraint that matters is grounding. **The system prompt contains
no fleet data at all** - not a vehicle count, not an example VIN, not a
plausible-looking number. Everything the assistant says about the fleet has to
arrive through a tool result during this conversation, which means a wrong
answer is traceable to a tool result rather than to something the model
remembered from training.

The loop is bounded at `AGENT_MAX_TOOL_ROUNDS` (6). Hitting the bound is not
an error: the model is asked to answer from what it has, and the response says
the limit was reached.

`tools_used` and `data_cited` come back with every reply. `data_cited` carries
the raw tool results, so the UI's citation chips can expand into exactly the
JSON the answer was built from - which is what makes the grounding claim
checkable by the person reading it rather than something they take on trust.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.logging_config import get_logger
from app.models import Customer
from app.services import agent_tools, llm
from app.services.scoping import Scope

log = get_logger("fleetguard.agent")

SYSTEM_PROMPT = """\
You are FleetGuard AI's fleet analyst. You help fleet managers and parts \
vendors understand which vehicle components are about to fail, when, and what \
it will cost.

HOW YOU WORK

You have tools that read this customer's live maintenance database. You have \
no other source of information about their fleet.

- Every figure you state about vehicles, components, risk, remaining life or \
cost must come from a tool result in this conversation. You have no prior \
knowledge of this fleet.
- If a tool returns found: false, say plainly that the thing was not found. \
Never substitute a plausible value, and never guess at a VIN.
- If a tool returns an error, say what failed. Do not retry more than once.
- You may add, subtract and take percentages of figures a tool returned, and \
should when it answers the question - but show which returned figures you \
used. Never estimate a figure no tool gave you.
- If you need data you have no tool for, say so.

CHOOSING TOOLS

Call several tools in one turn when a question needs several - it is faster \
than one per turn, and you have a limited number of turns.

- get_fleet_summary describes the whole of the current view and cannot be \
narrowed. For anything about one named customer, one model or one region - \
including how many vehicles they run - use find_vehicles.
- list_vehicles_by_risk ranks by failure probability: use it for "worst" and \
"highest risk". list_maintenance_due ranks by remaining life: use it for \
"next", "overdue", "due this month" and parts ordering.
- get_notifications returns warnings that have been raised. list_work_orders \
returns workshop jobs that have been booked. They are different things.
- When a question is about one vehicle, get_vehicle_risk gives every component \
at once; reach for explain_prediction, get_rul, get_service_history or \
get_telemetry_trend when asked why, when, what was done, or what changed.

WHAT THE NUMBERS MEAN

- Risk tiers: GREEN below 40% failure probability, AMBER 40-70%, RED at or \
above 70%. Anything with 7 days or less of useful life is escalated to RED \
regardless of probability.
- Failure probability and remaining useful life both derive from one health \
index, so they always agree. If asked, say so.
- A rule's precision is the share of its alerts followed by a real failure; \
coverage is the share of real failures it caught; days of warning is the \
median lead time.
- Cost exposure is probability-weighted: the expected cost, not a worst case.
- Costs are in the fleet's own local currency. Write figures with thousands \
separators and no currency symbol or code - do not write $ or USD, because \
you have not been told which currency this is.
- Telematics signals run 0 to 1, where higher is more stressful.

HOW YOU ANSWER

- Lead with the answer in the first sentence, then the figures that support it.
- Match the length to the question. A count deserves a sentence. "Why is this \
truck red", "what should we do this week" or a comparison deserves the \
supporting detail, in short paragraphs or a Markdown table.
- Use a Markdown table when comparing three or more things, and bold the \
figure that is the answer.
- Never pad. No preamble, no restating the question, no closing offer of \
further help.
- Use the units the tools give you: days, kilometres, percentages, currency.
- When the data supports an action - order a part with a long lead time, book \
a vehicle in before a trip - say it in one line at the end. When it does not, \
do not invent one. If the fleet is healthy, say it is healthy.
"""

SCOPE_NOTE_ALL = (
    "You are answering for the manufacturer view: every customer's vehicles are "
    "in scope. When a question names one customer, filter to them with a tool "
    "argument rather than quoting a fleet-wide number."
)

SCOPE_NOTE_CUSTOMER = (
    "You are answering for a single customer's view. Every tool result is "
    "already limited to their vehicles, so a fleet total here is their total, "
    "not the manufacturer's. You cannot see any other customer's data and must "
    "not speculate about it."
)

SUGGESTED_QUESTIONS = [
    "Which vehicles need attention today?",
    "What is overdue right now, and what should we book in first?",
    "What is our total cost exposure, and where is it concentrated?",
    "Which component fails most often across the fleet?",
    "Are failures trending up or down over the last 12 months?",
    "Show me the ten highest-risk trucks.",
    "What is driving the risk on our worst vehicle?",
    "Which parts should we order now, given their lead times?",
    "How accurate is the alternator rule?",
    "Which telematics signals most often come before a failure?",
    "How many vehicles are inside a 30-day remaining life?",
    "Which customer has the worst failure rate?",
]


@dataclass
class ToolInvocation:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    duration_ms: float


@dataclass
class AgentReply:
    reply: str
    tools_used: list[str] = field(default_factory=list)
    data_cited: list[ToolInvocation] = field(default_factory=list)
    rounds: int = 0
    truncated: bool = False
    hit_round_limit: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _scope_messages(session: Session, scope: Scope) -> list[dict[str, Any]]:
    """The system prompt plus one line saying whose data this is.

    Naming the current view is not a grounding leak - it is the caller's own
    identity, not a fact about the fleet - and leaving it out was a real
    defect: asked how many vehicles one named customer ran, the model answered
    with the count from `get_fleet_summary`, because nothing had told it that
    the summary covered every customer.
    """
    note = insight_scope_note(session, scope)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": note},
    ]


def insight_scope_note(session: Session, scope: Scope) -> str:
    if scope.is_manufacturer:
        return SCOPE_NOTE_ALL
    name = None
    if scope.customer_id is not None:
        customer = session.get(Customer, scope.customer_id)
        name = customer.name if customer else None
    subject = f"{name}'s fleet" if name else "one customer's fleet"
    return f"{SCOPE_NOTE_CUSTOMER} The customer is {subject}."


def answer(
    session: Session,
    scope: Scope,
    question: str,
    history: list[dict[str, str]] | None = None,
    max_rounds: int | None = None,
) -> AgentReply:
    """Run the loop until the model stops calling tools or the bound is hit."""
    limit = max_rounds or settings.AGENT_MAX_TOOL_ROUNDS

    messages: list[dict[str, Any]] = _scope_messages(session, scope)
    # Prior turns are replayed as plain text. Tool results from earlier turns
    # are deliberately not replayed: they may be stale, and a number that was
    # true yesterday being quoted as today's is exactly the failure this design
    # exists to prevent.
    for turn in history or []:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    invocations: list[ToolInvocation] = []
    prompt_tokens = completion_tokens = 0
    rounds = 0

    while rounds < limit:
        rounds += 1
        # A round that only has to pick a tool is given a small budget and low
        # reasoning effort. Providers bill `max_tokens` against the per-minute
        # allowance whether or not it is spent, so asking for the full answer
        # budget on every round is what exhausts a small plan mid-question.
        completion = llm.complete(
            messages,
            tools=agent_tools.TOOL_SCHEMAS,
            max_tokens=settings.AGENT_TOOL_ROUND_TOKENS,
            reasoning_effort=settings.AGENT_TOOL_ROUND_EFFORT,
        )
        prompt_tokens += completion.prompt_tokens
        completion_tokens += completion.completion_tokens

        if not completion.tool_calls:
            # The model chose to answer rather than call a tool. If it ran out
            # of room doing so, the small budget was the wrong call for this
            # question - ask again with the full one rather than showing a
            # sentence that stops mid-word.
            if completion.truncated:
                completion = llm.complete(
                    messages,
                    max_tokens=settings.AGENT_MAX_TOKENS,
                    reasoning_effort=settings.AGENT_ANSWER_EFFORT,
                )
                prompt_tokens += completion.prompt_tokens
                completion_tokens += completion.completion_tokens

            return AgentReply(
                reply=completion.content.strip(),
                tools_used=[i.tool for i in invocations],
                data_cited=invocations,
                rounds=rounds,
                truncated=completion.truncated,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        messages.append(
            {
                "role": "assistant",
                "content": completion.content or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in completion.tool_calls
                ],
            }
        )

        for call in completion.tool_calls:
            started = time.perf_counter()
            result = agent_tools.run_tool(session, scope, call.name, call.arguments)
            elapsed = round((time.perf_counter() - started) * 1000, 1)

            invocations.append(
                ToolInvocation(
                    tool=call.name,
                    arguments=call.arguments,
                    result=result,
                    duration_ms=elapsed,
                )
            )
            log.info(
                "agent_tool_call",
                extra={
                    "tool": call.name,
                    "found": result.get("found"),
                    "duration_ms": elapsed,
                    "customer_id": scope.customer_id,
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    # The bound was reached. Ask for an answer from what is already gathered,
    # with tools withheld so this call cannot start another round.
    messages.append(
        {
            "role": "user",
            "content": (
                "You have reached the tool call limit for this question. Answer "
                "using only what the tools have already returned, and say plainly "
                "if that is not enough to answer fully."
            ),
        }
    )
    final = llm.complete(
        messages,
        max_tokens=settings.AGENT_MAX_TOKENS,
        reasoning_effort=settings.AGENT_ANSWER_EFFORT,
    )
    prompt_tokens += final.prompt_tokens
    completion_tokens += final.completion_tokens

    return AgentReply(
        reply=final.content.strip(),
        tools_used=[i.tool for i in invocations],
        data_cited=invocations,
        rounds=rounds,
        truncated=final.truncated,
        hit_round_limit=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
