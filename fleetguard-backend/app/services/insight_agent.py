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
- Do not calculate new figures from tool results beyond simple totals you can \
show your working for. Prefer quoting the number the tool gave you.
- If you need data you have no tool for, say so.

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
- Costs are in the fleet's own local currency. Write figures with thousands separators and no currency symbol or code - do not write $ or USD, because you have not been told which currency this is.

HOW YOU ANSWER

- Lead with the answer, then the supporting figures.
- Use Markdown tables when comparing three or more things.
- Keep it short. A fleet manager reading on a phone between calls.
- Use the units the tools give you: days, kilometres, percentages, currency.
- Never invent a recommendation the data does not support. If the fleet is \
healthy, say it is healthy.
"""

SUGGESTED_QUESTIONS = [
    "Which vehicles need attention today?",
    "What is our total cost exposure, and where is it concentrated?",
    "Which component fails most often across the fleet?",
    "How accurate is the alternator rule?",
    "Show me the ten highest-risk trucks.",
    "What is driving the risk on our worst vehicle?",
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


def answer(
    session: Session,
    scope: Scope,
    question: str,
    history: list[dict[str, str]] | None = None,
    max_rounds: int | None = None,
) -> AgentReply:
    """Run the loop until the model stops calling tools or the bound is hit."""
    limit = max_rounds or settings.AGENT_MAX_TOOL_ROUNDS

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
        completion = llm.complete(messages, tools=agent_tools.TOOL_SCHEMAS)
        prompt_tokens += completion.prompt_tokens
        completion_tokens += completion.completion_tokens

        if not completion.tool_calls:
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
    final = llm.complete(messages)
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
