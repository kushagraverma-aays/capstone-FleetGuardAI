from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import AGENT_MAX_TOOL_ROUNDS, GROQ_API_KEY, GROQ_MODEL
from app.services.agent_tools import TOOL_SCHEMAS, run_tool

INSIGHT_MAX_TOKENS = 4000
ACTION_MAX_TOKENS = 2500

INSIGHT_SYSTEM_PROMPT = """You are FleetGuard AI, the assistant for a commercial vehicle fleet's predictive maintenance platform. You help fleet managers and dealer service staff understand which trucks need attention and why.

GROUNDING RULES - these are absolute:
1. You have NO knowledge of this fleet. Every vehicle, part, probability, day count and signal name must come from a tool result in this conversation.
2. Never state, estimate, round or infer a number that a tool did not return. If you need a figure, call a tool.
3. If a tool returns an error or an empty result, say plainly that the data is not available. Never fill the gap with a plausible guess.
4. If a question cannot be answered by any available tool, say so and describe what the platform does cover.
5. Never invent VINs or part names. If the user's VIN or part does not resolve, report that.

HOW TO ANSWER:
- Lead with the direct answer, then the supporting numbers.
- Always name the VIN and component you are talking about, so the user can cross-check on the dashboard.
- When explaining a prediction, give the contributing signals and their percentage shares.
- Failure probability is the chance of failure within the predicted window. RUL is how long until the component crosses its failure threshold. Both derive from the same health index, so they always agree - say so if the user seems to think they are separate opinions.
- A rule's precision is the share of flagged cases that were genuine; coverage is the share of real failures it caught. Quote both when discussing rule quality, and be honest that precision near 50% is normal and still valuable given the lead time.
- Keep answers short. Two or three sentences plus a compact list where useful.
- Plain language. The reader is a fleet manager, not a data scientist."""

ACTION_SYSTEM_PROMPT = """You draft short, professional maintenance outreach messages for a commercial vehicle fleet.

Use ONLY the facts supplied to you. Do not invent costs, dates, contact names, part prices or workshop availability.

Write 4-6 sentences: what was detected, the evidence, the recommended action and its timing, and the consequence of waiting. Direct and courteous. No greeting placeholders like [Name], no marketing language, no emoji. Output only the message body, and always finish your final sentence."""


class AgentUnavailable(RuntimeError):
    pass


def _client():
    if not GROQ_API_KEY:
        raise AgentUnavailable(
            "GROQ_API_KEY is not set. Add it to your .env file to enable the agent."
        )
    try:
        from groq import Groq
    except ImportError as exc:
        raise AgentUnavailable("the 'groq' package is not installed") from exc
    return Groq(api_key=GROQ_API_KEY)


def _serialise_tool_calls(tool_calls) -> list[dict]:
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in tool_calls
    ]


def run_insight_agent(db: Session, message: str, history: list[dict] | None = None) -> dict:
    client = _client()

    messages: list[dict[str, Any]] = [{"role": "system", "content": INSIGHT_SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    tools_used: list[dict] = []
    data_cited: list[dict] = []

    for _ in range(AGENT_MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=INSIGHT_MAX_TOKENS,
        )
        choice = response.choices[0]
        reply = choice.message

        if not getattr(reply, "tool_calls", None):
            return {
                "reply": (reply.content or "").strip() or "I could not produce an answer.",
                "tools_used": tools_used,
                "data_cited": data_cited,
                "grounded": bool(tools_used),
                "truncated": choice.finish_reason == "length",
                "model": GROQ_MODEL,
            }

        messages.append(
            {
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": _serialise_tool_calls(reply.tool_calls),
            }
        )

        for tc in reply.tool_calls:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            result = run_tool(db, tc.function.name, arguments)
            tools_used.append({"tool": tc.function.name, "arguments": arguments})
            data_cited.append({"tool": tc.function.name, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(result, default=str),
                }
            )

    return {
        "reply": (
            "I could not finish that request within the allowed number of data lookups. "
            "Try asking about one vehicle or one component at a time."
        ),
        "tools_used": tools_used,
        "data_cited": data_cited,
        "grounded": bool(tools_used),
        "truncated": False,
        "model": GROQ_MODEL,
    }


def run_action_agent(db: Session, vin: str, part: str, audience: str = "fleet_owner") -> dict:
    facts = run_tool(db, "explain_prediction", {"vin": vin, "part": part})
    if "error" in facts:
        return {"error": facts["error"]}
    rul = run_tool(db, "get_rul", {"vin": vin, "part": part})

    client = _client()
    audience_line = (
        "The reader is the parts vendor. Focus on pre-positioning the replacement part."
        if audience == "vendor"
        else "The reader is the fleet owner. Focus on booking a workshop slot."
    )
    prompt = (
        f"{audience_line}\n\nVerified data:\n"
        f"{json.dumps({'prediction': facts, 'rul': rul}, indent=2, default=str)}"
    )

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": ACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=ACTION_MAX_TOKENS,
    )
    choice = response.choices[0]

    return {
        "vin": facts["vin"],
        "part": facts["part"],
        "audience": audience,
        "message": (choice.message.content or "").strip(),
        "truncated": choice.finish_reason == "length",
        "model": GROQ_MODEL,
        "based_on": {
            "failure_probability": facts["failure_probability"],
            "risk_tier": facts["risk_tier"],
            "rul_days": rul.get("rul_days"),
            "top_signal": facts["top_signal"],
        },
    }


SUGGESTED_QUESTIONS = [
    "Which vehicles are red-tier this week?",
    "Why is this VIN's alternator at high risk?",
    "How many days before the transmission fluid needs replacing?",
    "Compare durability of the alternator and the radiator fan.",
    "Which signal causes the most failures across the fleet?",
]