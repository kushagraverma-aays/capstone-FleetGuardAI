"""The Action Agent: drafts outreach, and cannot look anything up.

Spec section 7 is specific about the shape of this one. The facts are gathered
in Python **first**, and the model is then handed those facts and asked to
write prose. It gets no tools, so there is no mechanism by which it could
query a VIN it was not given - the grounding guarantee here is structural
rather than a matter of the prompt being persuasive.

It never sends anything. A draft goes back to the human who asked for it, and
what happens next is their decision. That is a deliberate product stance, not
an unfinished feature: an LLM that emails a customer's vendor unattended is a
liability, and every buyer for this product will ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import SIGNAL_LABELS
from app.models import Part
from app.services import agent_tools, fleet_queries, llm
from app.services.scoping import Scope

AUDIENCES = ("vendor", "fleet_owner")

SYSTEM_PROMPT = """\
You write short, professional maintenance outreach messages for FleetGuard AI, \
a predictive maintenance service for commercial vehicle fleets.

You will be given a set of verified facts. Write 4 to 6 sentences using only \
those facts.

RULES

- Use only the facts provided. Do not invent part numbers, prices, dates, \
names, phone numbers or reference codes.
- Do not add a fact that is not in the list, even if it would sound helpful.
- Do not include a subject line, a signature block, or placeholders such as \
[Name] or [Company].
- Write plain prose. No bullet points, no Markdown headings.
- Be direct and specific. Quote the numbers you were given exactly as written, including their thousands separators.
- Costs are in the fleet's local currency. Write the figure without inventing a currency symbol or code.
- State clearly what you are asking the reader to do.
"""

VENDOR_BRIEF = """\
Audience: the parts vendor who supplies this fleet.
They need to commit stock against a lead time. Emphasise the component, the \
quantity of one, the lead time against the remaining life, and the date \
pressure. They do not care about the driver or the route.
"""

OWNER_BRIEF = """\
Audience: the fleet owner or operations manager who runs this truck.
They need to book a workshop slot and plan around the vehicle being off the \
road. Emphasise the risk to the vehicle, the remaining life, and the money \
saved by replacing on plan rather than after a roadside failure.
"""


@dataclass
class DraftResult:
    message: str
    audience: str
    vin: str
    part: str
    facts: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DraftError(ValueError):
    """The draft cannot be produced from the data available."""


def gather_facts(session: Session, scope: Scope, vin: str, part: str) -> dict[str, Any]:
    """Everything the message is allowed to contain, fetched in Python.

    This is the security boundary. Whatever this function returns is the
    complete universe of facts available to the model for this draft.
    """
    part_row = agent_tools.resolve_part(session, part)
    if part_row is None:
        raise DraftError(
            f"No component matches {part!r}. "
            + agent_tools.known_components_message(session)
        )

    vin = vin.strip().upper()
    prediction = fleet_queries.get_prediction(session, scope, vin, part_row.part_code)
    if prediction is None:
        raise DraftError(
            f"No prediction exists for {part_row.part_name} on {vin} in this view. "
            "Either the VIN is unknown or it belongs to another customer."
        )

    context = fleet_queries.prediction_context(session, vin, part_row.part_code)
    cost = fleet_queries.cost_breakdown(
        session, context["part"], prediction["failure_probability"]
    )
    stored_part: Part = context["part"]

    # Figures are pre-formatted here rather than left raw. The model copies
    # what it is given, so "49,810" is what appears in the message and
    # "49810.3" is what appears if nobody bothered. Currency is left unsymbolled
    # deliberately: the analytics constants are documented as currency-neutral,
    # and the frontend renders the symbol for the customer's locale.
    return {
        "vin": prediction["vin"],
        "customer": prediction["customer_name"],
        "vehicle_model": prediction["model"],
        "vehicle_variant": prediction["variant"],
        "region": prediction["region"],
        "component": prediction["part_name"],
        "part_code": prediction["part_code"],
        "risk_tier": prediction["risk_tier"],
        "failure_probability_pct": round(prediction["failure_probability"] * 100),
        "remaining_life_days": round(prediction["rul_days"]),
        "remaining_life_km": f"{round(prediction['rul_km']):,}",
        "earliest_expected_days": prediction["window_from_days"],
        "latest_expected_days": prediction["window_to_days"],
        "part_lead_time_days": stored_part.lead_time_days,
        "km_on_part": f"{round(context['km_on_part']):,}",
        "design_life_km": f"{stored_part.design_life_km:,}",
        "share_of_design_life_used_pct": context["life_used_pct"],
        "strongest_warning_signal": SIGNAL_LABELS.get(
            prediction["top_signal"], prediction["top_signal"]
        ),
        "unplanned_failure_cost": f"{cost['unplanned_cost']:,.0f}",
        "planned_replacement_cost": f"{cost['planned_cost']:,.0f}",
        "saving_if_replaced_on_plan": f"{cost['avoidable_cost']:,.0f}",
        "escalated": prediction["escalated"],
        "escalation_reason": prediction["escalation_reason"],
    }


def draft(
    session: Session,
    scope: Scope,
    vin: str,
    part: str,
    audience: str,
) -> DraftResult:
    if audience not in AUDIENCES:
        raise DraftError(
            f"audience must be one of {', '.join(AUDIENCES)}; got {audience!r}."
        )

    facts = gather_facts(session, scope, vin, part)
    brief = VENDOR_BRIEF if audience == "vendor" else OWNER_BRIEF

    fact_lines = "\n".join(
        f"- {key.replace('_', ' ')}: {value}"
        for key, value in facts.items()
        if value is not None and value != ""
    )

    completion = llm.complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{brief}\nVerified facts:\n{fact_lines}\n\nWrite the message.",
            },
        ],
        # No tools argument at all: the model has nothing to call.
        max_tokens=settings.AGENT_MAX_TOKENS,
    )

    return DraftResult(
        message=completion.content.strip(),
        audience=audience,
        vin=facts["vin"],
        part=facts["component"],
        facts=facts,
        truncated=completion.truncated,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )
