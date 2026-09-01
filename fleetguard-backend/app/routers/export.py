"""CSV export.

The fleet table's export button hands a fleet manager something they can put
in front of a workshop or a finance team, so it carries the same filters the
table had on screen and streams rather than buffering the whole fleet in
memory.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.deps import CurrentScope, DbSession
from app.services import fleet_queries
from app.services.fleet_queries import PredictionFilters

router = APIRouter(prefix="/api/export", tags=["export"])

COLUMNS = [
    "vin",
    "customer_name",
    "model",
    "variant",
    "region",
    "part_code",
    "part_name",
    "risk_tier",
    "failure_probability",
    "health_index",
    "rul_days",
    "rul_km",
    "window_from_days",
    "window_to_days",
    "model_confidence",
    "top_signal",
    "top_signal_share",
    "escalated",
    "estimated_cost_impact",
    "computed_date",
]

# Rows per database round trip while streaming. Large enough to keep the query
# count sane, small enough that memory stays flat for the whole fleet.
CHUNK = 500


@router.get(
    "/predictions.csv",
    summary="Download the filtered prediction table as CSV",
    response_class=StreamingResponse,
)
def export_predictions(
    db: DbSession,
    scope: CurrentScope,
    tier: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    customer_id: Annotated[list[int] | None, Query(description="Repeatable.")] = None,
    region: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    model: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    part_code: Annotated[list[str] | None, Query(description="Repeatable.")] = None,
    search: Annotated[str | None, Query(description="Free text.")] = None,
    sort: Annotated[str, Query(description="probability | rul | vin | cost | health")] = "probability",
    order: Annotated[str, Query(description="asc | desc")] = "desc",
) -> StreamingResponse:
    filters = PredictionFilters(
        tiers=tier,
        customer_ids=customer_id,
        regions=region,
        models=model,
        part_codes=part_code,
        search=search,
    )

    def rows() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield _drain(buffer)

        offset = 0
        while True:
            batch, _ = fleet_queries.list_predictions(
                db,
                scope,
                filters,
                sort=sort,
                descending=order.lower() != "asc",
                limit=CHUNK,
                offset=offset,
            )
            if not batch:
                break
            for row in batch:
                writer.writerow(row)
            yield _drain(buffer)
            if len(batch) < CHUNK:
                break
            offset += CHUNK

    filename = f"fleetguard-predictions-{date.today().isoformat()}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _drain(buffer: io.StringIO) -> str:
    value = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return value
