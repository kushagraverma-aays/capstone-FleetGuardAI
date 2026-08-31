"""Alerts and work orders - the write side of the product.

Both resources are scoped by the customer id stored on the row itself rather
than by a join, because a notification belongs to the tenant it was raised
for. Every mutation is audit-logged by the service layer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.deps import CurrentScope, DbSession, PageParams, WriteScope
from app.schemas.common import Page
from app.schemas.workflow import (
    NotificationOut,
    NotificationUpdate,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderUpdate,
)
from app.services import workflow
from app.services.workflow import (
    NOTIFICATION_STATUSES,
    WORK_ORDER_STATUSES,
    WorkflowError,
)

router = APIRouter(prefix="/api", tags=["workflow"])


# --- notifications -----------------------------------------------------------


@router.get(
    "/notifications",
    response_model=Page[NotificationOut],
    summary="Alert inbox, most severe first",
)
def list_notifications(
    db: DbSession,
    scope: CurrentScope,
    page: PageParams,
    audience: Annotated[
        list[str] | None, Query(description="vendor | fleet_owner. Repeatable.")
    ] = None,
    severity: Annotated[
        list[str] | None, Query(description="critical | high | medium | low. Repeatable.")
    ] = None,
    alert_status: Annotated[
        list[str] | None,
        Query(description="pending | acknowledged | dismissed | actioned. Repeatable."),
    ] = None,
    customer_id: Annotated[list[int] | None, Query(description="Repeatable.")] = None,
    search: Annotated[str | None, Query(description="Free text over VIN, title and message.")] = None,
) -> Page[NotificationOut]:
    rows, total = workflow.list_notifications(
        db,
        scope,
        audiences=audience,
        severities=severity,
        statuses=alert_status,
        customer_ids=customer_id,
        search=search,
        limit=page.limit,
        offset=page.offset,
    )
    return Page.of(
        [NotificationOut(**row) for row in rows], total, page.limit, page.offset
    )


@router.patch(
    "/notifications/{notification_id}",
    response_model=NotificationOut,
    summary="Acknowledge, dismiss or action an alert",
)
def update_notification(
    notification_id: int,
    payload: NotificationUpdate,
    db: DbSession,
    scope: WriteScope,
) -> NotificationOut:
    if payload.status not in NOTIFICATION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"status must be one of {sorted(NOTIFICATION_STATUSES)}; "
                f"got {payload.status!r}."
            ),
        )

    row = workflow.update_notification_status(db, scope, notification_id, payload.status)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No alert {notification_id} in this view.",
        )
    return NotificationOut(**row)


# --- work orders -------------------------------------------------------------


@router.get(
    "/work-orders",
    response_model=Page[WorkOrderOut],
    summary="Scheduled and draft workshop jobs",
)
def list_work_orders(
    db: DbSession,
    scope: CurrentScope,
    page: PageParams,
    work_order_status: Annotated[
        list[str] | None,
        Query(description="draft | scheduled | completed | cancelled. Repeatable."),
    ] = None,
    customer_id: Annotated[list[int] | None, Query(description="Repeatable.")] = None,
    vin: Annotated[str | None, Query(description="Restrict to one vehicle.")] = None,
) -> Page[WorkOrderOut]:
    rows, total = workflow.list_work_orders(
        db,
        scope,
        statuses=work_order_status,
        customer_ids=customer_id,
        vin=vin,
        limit=page.limit,
        offset=page.offset,
    )
    return Page.of([WorkOrderOut(**row) for row in rows], total, page.limit, page.offset)


@router.post(
    "/work-orders",
    response_model=WorkOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a workshop job against a vehicle",
)
def create_work_order(
    payload: WorkOrderCreate, db: DbSession, scope: WriteScope
) -> WorkOrderOut:
    try:
        row = workflow.create_work_order(
            db,
            scope,
            vin=payload.vin,
            part_code=payload.part_code,
            scheduled_date=payload.scheduled_date,
            notes=payload.notes,
            status=payload.status,
        )
    except WorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return WorkOrderOut(**row)


@router.patch(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderOut,
    summary="Reschedule, annotate or close a workshop job",
)
def update_work_order(
    work_order_id: int,
    payload: WorkOrderUpdate,
    db: DbSession,
    scope: WriteScope,
) -> WorkOrderOut:
    if payload.status is not None and payload.status not in WORK_ORDER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"status must be one of {sorted(WORK_ORDER_STATUSES)}; "
                f"got {payload.status!r}."
            ),
        )

    try:
        row = workflow.update_work_order(
            db,
            scope,
            work_order_id,
            status=payload.status,
            scheduled_date=payload.scheduled_date,
            notes=payload.notes,
        )
    except WorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No work order {work_order_id} in this view.",
        )
    return WorkOrderOut(**row)
