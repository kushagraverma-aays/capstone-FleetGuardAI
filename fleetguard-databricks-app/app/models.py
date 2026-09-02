"""SQLAlchemy declarative models - the schema in spec section 4.

Conventions used throughout:
  * Natural business keys (vin, part_code) stay as the primary key where the
    business already has a stable identifier; everything else gets a surrogate.
  * Money is DECIMAL(12,2). Floats are fine for signals and probabilities,
    but currency compared across a fleet must not drift.
  * Every table carries created_at so an audit question is always answerable.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- tenancy -----------------------------------------------------------------


class Customer(Base):
    """A fleet operator. The tenant boundary for every scoped query."""

    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(160), nullable=False)
    contract_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="basic")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer")
    users: Mapped[list["User"]] = relationship(back_populates="customer")


class User(Base):
    """A login. customer_id NULL means manufacturer scope (sees everything)."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer | None"] = relationship(back_populates="users")


# --- master data -------------------------------------------------------------


class Vehicle(Base):
    __tablename__ = "vehicle_master"

    vin: Mapped[str] = mapped_column(String(24), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    variant: Mapped[str] = mapped_column(String(60), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    registration_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_km_driven: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_km_per_day: Mapped[float] = mapped_column(nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    customer: Mapped["Customer"] = relationship(back_populates="vehicles")

    __table_args__ = (
        Index("ix_vehicle_customer_status", "customer_id", "status"),
        Index("ix_vehicle_model", "model"),
    )


class Part(Base):
    __tablename__ = "part_master"

    part_code: Mapped[str] = mapped_column(String(24), primary_key=True)
    part_name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    design_life_km: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    labour_hours: Mapped[float] = mapped_column(nullable=False)


# --- telemetry and service history -------------------------------------------


class TelematicsWeekly(Base):
    """One row per vehicle per week. Signals are normalised 0-1."""

    __tablename__ = "telematics_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_km: Mapped[float] = mapped_column(nullable=False, default=0.0)
    odometer_km: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    coolant_temp_variance: Mapped[float] = mapped_column(nullable=False, default=0.0)
    oil_pressure_dips: Mapped[float] = mapped_column(nullable=False, default=0.0)
    battery_voltage_sag: Mapped[float] = mapped_column(nullable=False, default=0.0)
    dtc_recurrence_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    harsh_braking_frequency: Mapped[float] = mapped_column(nullable=False, default=0.0)
    overload_duty_share: Mapped[float] = mapped_column(nullable=False, default=0.0)
    high_rpm_dwell_time: Mapped[float] = mapped_column(nullable=False, default=0.0)
    short_trip_ratio: Mapped[float] = mapped_column(nullable=False, default=0.0)
    idle_time_pct: Mapped[float] = mapped_column(nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("vin", "week_start_date", name="uq_telematics_vin_week"),
        Index("ix_telematics_week", "week_start_date"),
    )


class JobCard(Base):
    """A workshop event. event_type is fitment, failure or preventive.

    Only failure rows are labels for the model. Fitment rows are what make
    km-on-part computable - without them RUL is meaningless.
    """

    __tablename__ = "job_cards"

    job_card_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    odometer_reading: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    replaced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    downtime_hours: Mapped[float] = mapped_column(nullable=False, default=0.0)

    __table_args__ = (
        Index("ix_jobcard_vin_part_date", "vin", "part_code", "event_date"),
        Index("ix_jobcard_type_date", "event_type", "event_date"),
    )


class WarrantyClaim(Base):
    __tablename__ = "warranty_claims"

    claim_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_card_id: Mapped[int] = mapped_column(ForeignKey("job_cards.job_card_id"), nullable=False)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    claim_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


# --- rules -------------------------------------------------------------------


class Rule(Base):
    """A deployed scoring rule for one component.

    Deploying a new version deactivates the previous one rather than
    overwriting it, so the full history stays queryable.
    """

    __tablename__ = "rules"

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    precision: Mapped[float] = mapped_column(nullable=False, default=0.0)
    coverage: Mapped[float] = mapped_column(nullable=False, default=0.0)
    days_to_alert: Mapped[float] = mapped_column(nullable=False, default=0.0)
    sample_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    signals: Mapped[list["RuleSignal"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_rules_part_active", "part_code", "is_active"),
        UniqueConstraint("part_code", "version", name="uq_rule_part_version"),
    )


class RuleSignal(Base):
    """One signal contribution to a rule.

    The `included` flag records signals that were offered to the user but
    toggled off, so the modelling choice stays auditable after the fact.
    """

    __tablename__ = "rule_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.rule_id"), nullable=False)
    signal: Mapped[str] = mapped_column(String(48), nullable=False)
    correlation: Mapped[float] = mapped_column(nullable=False, default=0.0)
    weight: Mapped[float] = mapped_column(nullable=False, default=0.0)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    rule: Mapped["Rule"] = relationship(back_populates="signals")

    __table_args__ = (UniqueConstraint("rule_id", "signal", name="uq_rulesignal"),)


# --- scoring output ----------------------------------------------------------


class Prediction(Base):
    """Current risk for one (vehicle, component). Recomputed by the scoring CLI.

    health_index is the single source of truth: failure_probability is derived
    from it, and RUL projects the same quantity forward. That is why the
    probability screen and the RUL screen can never contradict each other.
    """

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.rule_id"), nullable=True)

    failure_probability: Mapped[float] = mapped_column(nullable=False, default=0.0)
    risk_tier: Mapped[str] = mapped_column(String(8), nullable=False, default="GREEN")
    health_index: Mapped[float] = mapped_column(nullable=False, default=100.0)

    window_from_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_to_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    rul_km: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rul_days: Mapped[float] = mapped_column(nullable=False, default=0.0)
    model_confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    degradation_trend: Mapped[float] = mapped_column(nullable=False, default=0.0)

    top_signal: Mapped[str | None] = mapped_column(String(48), nullable=True)
    top_signal_share: Mapped[float] = mapped_column(nullable=False, default=0.0)

    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    drivers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trend: Mapped[list | None] = mapped_column(JSON, nullable=True)
    curve: Mapped[list | None] = mapped_column(JSON, nullable=True)

    estimated_cost_impact: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    computed_date: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        UniqueConstraint("vin", "part_code", name="uq_prediction_vin_part"),
        Index("ix_prediction_tier", "risk_tier"),
        Index("ix_prediction_part", "part_code"),
        Index("ix_prediction_rul", "rul_days"),
    )


# --- workflow ----------------------------------------------------------------


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=False, index=True
    )
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_notification_status_audience", "status", "audience"),)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(ForeignKey("vehicle_master.vin"), nullable=False)
    part_code: Mapped[str] = mapped_column(ForeignKey("part_master.part_code"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.customer_id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Every rule deployment and work order change lands here."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)
