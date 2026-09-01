"""Alerts and work orders - the two places the product writes, not just reads.

Every state change here lands in `audit_log`, the same way rule deployment
already does. A predictive maintenance product that cannot say who dismissed
the alert about the truck that later failed is not one a fleet will buy.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Customer, Notification, Part, Vehicle, WorkOrder
from app.services.scoping import Scope, limit_by_customer_column

NOTIFICATION_STATUSES = {"pending", "acknowledged", "dismissed", "actioned"}
WORK_ORDER_STATUSES = {"draft", "scheduled", "completed", "cancelled"}


def record_audit(
    session: Session,
    scope: Scope,
    action: str,
    entity: str,
    entity_id: str | int | None,
    payload: dict | None = None,
) -> None:
    """Append one audit row. The caller owns the commit."""
    session.add(
        AuditLog(
            user_id=scope.user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload={
                **(payload or {}),
                "actor_email": scope.email,
                "actor_role": scope.role,
                "actor_customer_id": scope.customer_id,
            },
        )
    )


# --- notifications -----------------------------------------------------------


def _notification_base() -> Select:
    return (
        select(Notification, Part.part_name, Customer.name.label("customer_name"))
        .join(Part, Part.part_code == Notification.part_code)
        .join(Customer, Customer.customer_id == Notification.customer_id)
    )


def _notification_to_dict(row) -> dict:
    notification: Notification = row[0]
    return {
        "id": notification.id,
        "vin": notification.vin,
        "part_code": notification.part_code,
        "part_name": row.part_name,
        "customer_id": notification.customer_id,
        "customer_name": row.customer_name,
        "audience": notification.audience,
        "severity": notification.severity,
        "title": notification.title,
        "message": notification.message,
        "status": notification.status,
        "created_at": notification.created_at,
        "acknowledged_at": notification.acknowledged_at,
    }


def list_notifications(
    session: Session,
    scope: Scope,
    *,
    audiences: list[str] | None = None,
    severities: list[str] | None = None,
    statuses: list[str] | None = None,
    customer_ids: list[int] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = []
    if audiences:
        conditions.append(Notification.audience.in_(audiences))
    if severities:
        conditions.append(Notification.severity.in_(severities))
    if statuses:
        conditions.append(Notification.status.in_(statuses))
    if customer_ids:
        conditions.append(Notification.customer_id.in_(customer_ids))
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(
                Notification.vin.like(needle),
                Notification.title.like(needle),
                Notification.message.like(needle),
            )
        )

    count_stmt = (
        select(func.count())
        .select_from(Notification)
        .join(Part, Part.part_code == Notification.part_code)
        .join(Customer, Customer.customer_id == Notification.customer_id)
        .where(*conditions)
    )
    total = session.execute(
        limit_by_customer_column(count_stmt, scope, Notification.customer_id)
    ).scalar_one()

    stmt = limit_by_customer_column(
        _notification_base().where(*conditions), scope, Notification.customer_id
    )
    # Severity first, then newest: the inbox opens on what matters, not on
    # whatever happened to be written last.
    severity_rank = case(
        (Notification.severity == "critical", 0),
        (Notification.severity == "high", 1),
        (Notification.severity == "medium", 2),
        else_=3,
    )
    stmt = stmt.order_by(severity_rank, Notification.created_at.desc(), Notification.id.desc())
    stmt = stmt.limit(limit).offset(offset)

    return [_notification_to_dict(row) for row in session.execute(stmt).all()], int(total)


def get_notification(session: Session, scope: Scope, notification_id: int) -> dict | None:
    stmt = limit_by_customer_column(
        _notification_base().where(Notification.id == notification_id),
        scope,
        Notification.customer_id,
    )
    row = session.execute(stmt).first()
    return _notification_to_dict(row) if row else None


def update_notification_status(
    session: Session,
    scope: Scope,
    notification_id: int,
    status: str,
) -> dict | None:
    stmt = limit_by_customer_column(
        select(Notification).where(Notification.id == notification_id),
        scope,
        Notification.customer_id,
    )
    notification = session.execute(stmt).scalars().first()
    if notification is None:
        return None

    previous = notification.status
    notification.status = status
    # Acknowledgement is the moment somebody took responsibility, so it is
    # stamped once and not overwritten by a later state change.
    if status == "acknowledged" and notification.acknowledged_at is None:
        notification.acknowledged_at = datetime.now(UTC).replace(tzinfo=None)
    if status == "pending":
        notification.acknowledged_at = None

    record_audit(
        session,
        scope,
        action=f"notification.{status}",
        entity="notification",
        entity_id=notification.id,
        payload={
            "vin": notification.vin,
            "part_code": notification.part_code,
            "from_status": previous,
            "to_status": status,
        },
    )
    session.commit()
    return get_notification(session, scope, notification_id)


# --- work orders -------------------------------------------------------------


def _work_order_base() -> Select:
    return (
        select(WorkOrder, Part.part_name, Customer.name.label("customer_name"))
        .join(Part, Part.part_code == WorkOrder.part_code)
        .join(Customer, Customer.customer_id == WorkOrder.customer_id)
    )


def _work_order_to_dict(row) -> dict:
    order: WorkOrder = row[0]
    return {
        "id": order.id,
        "vin": order.vin,
        "part_code": order.part_code,
        "part_name": row.part_name,
        "customer_id": order.customer_id,
        "customer_name": row.customer_name,
        "status": order.status,
        "scheduled_date": order.scheduled_date,
        "notes": order.notes,
        "created_at": order.created_at,
    }


def list_work_orders(
    session: Session,
    scope: Scope,
    *,
    statuses: list[str] | None = None,
    customer_ids: list[int] | None = None,
    vin: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = []
    if statuses:
        conditions.append(WorkOrder.status.in_(statuses))
    if customer_ids:
        conditions.append(WorkOrder.customer_id.in_(customer_ids))
    if vin:
        conditions.append(WorkOrder.vin == vin)

    count_stmt = (
        select(func.count())
        .select_from(WorkOrder)
        .join(Part, Part.part_code == WorkOrder.part_code)
        .join(Customer, Customer.customer_id == WorkOrder.customer_id)
        .where(*conditions)
    )
    total = session.execute(
        limit_by_customer_column(count_stmt, scope, WorkOrder.customer_id)
    ).scalar_one()

    stmt = limit_by_customer_column(
        _work_order_base().where(*conditions), scope, WorkOrder.customer_id
    )
    stmt = stmt.order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
    stmt = stmt.limit(limit).offset(offset)

    return [_work_order_to_dict(row) for row in session.execute(stmt).all()], int(total)


def get_work_order(session: Session, scope: Scope, work_order_id: int) -> dict | None:
    stmt = limit_by_customer_column(
        _work_order_base().where(WorkOrder.id == work_order_id),
        scope,
        WorkOrder.customer_id,
    )
    row = session.execute(stmt).first()
    return _work_order_to_dict(row) if row else None


class WorkflowError(ValueError):
    """A request that is well-formed but cannot be satisfied by the data."""


def create_work_order(
    session: Session,
    scope: Scope,
    vin: str,
    part_code: str,
    scheduled_date: date | None = None,
    notes: str | None = None,
    status: str = "draft",
) -> dict:
    """Raise a job against a vehicle in the caller's tenant.

    The customer id is taken from the vehicle rather than the request body, so
    a work order can never be filed into another tenant's queue.
    """
    from app.services.scoping import limit_vehicles

    vehicle = session.execute(
        limit_vehicles(select(Vehicle).where(Vehicle.vin == vin), scope)
    ).scalars().first()
    if vehicle is None:
        raise WorkflowError(f"No vehicle {vin} in this view.")

    if session.get(Part, part_code) is None:
        raise WorkflowError(f"No component with code {part_code}.")

    if status not in WORK_ORDER_STATUSES:
        raise WorkflowError(
            f"status must be one of {sorted(WORK_ORDER_STATUSES)}; got {status!r}."
        )

    order = WorkOrder(
        vin=vin,
        part_code=part_code,
        customer_id=vehicle.customer_id,
        status=status,
        scheduled_date=scheduled_date,
        notes=notes,
    )
    session.add(order)
    session.flush()

    record_audit(
        session,
        scope,
        action="work_order.create",
        entity="work_order",
        entity_id=order.id,
        payload={
            "vin": vin,
            "part_code": part_code,
            "status": status,
            "scheduled_date": scheduled_date.isoformat() if scheduled_date else None,
            "notes": notes,
        },
    )
    session.commit()
    return get_work_order(session, scope, order.id)


def update_work_order(
    session: Session,
    scope: Scope,
    work_order_id: int,
    status: str | None = None,
    scheduled_date: date | None = None,
    notes: str | None = None,
) -> dict | None:
    stmt = limit_by_customer_column(
        select(WorkOrder).where(WorkOrder.id == work_order_id),
        scope,
        WorkOrder.customer_id,
    )
    order = session.execute(stmt).scalars().first()
    if order is None:
        return None

    changes: dict[str, object] = {}
    if status is not None:
        if status not in WORK_ORDER_STATUSES:
            raise WorkflowError(
                f"status must be one of {sorted(WORK_ORDER_STATUSES)}; got {status!r}."
            )
        changes["status"] = {"from": order.status, "to": status}
        order.status = status
    if scheduled_date is not None:
        changes["scheduled_date"] = {
            "from": order.scheduled_date.isoformat() if order.scheduled_date else None,
            "to": scheduled_date.isoformat(),
        }
        order.scheduled_date = scheduled_date
    if notes is not None:
        changes["notes"] = {"from": order.notes, "to": notes}
        order.notes = notes

    record_audit(
        session,
        scope,
        action="work_order.update",
        entity="work_order",
        entity_id=order.id,
        payload={"vin": order.vin, "part_code": order.part_code, "changes": changes},
    )
    session.commit()
    return get_work_order(session, scope, work_order_id)
