from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicle_master"

    vin: Mapped[str] = mapped_column(String(20), primary_key=True)
    model: Mapped[str] = mapped_column(String(60))
    region: Mapped[str] = mapped_column(String(20), index=True)
    registration_date: Mapped[date] = mapped_column(Date)
    total_km_driven: Mapped[int] = mapped_column(Integer)
    avg_km_per_day: Mapped[float] = mapped_column(Float)
    fleet_operator: Mapped[str] = mapped_column(String(60), default="")


class Part(Base):
    __tablename__ = "part_master"

    part_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    part_name: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(40), index=True)
    design_life_km: Mapped[int] = mapped_column(Integer)


class JobCard(Base):
    __tablename__ = "job_cards"

    job_card_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    vin: Mapped[str] = mapped_column(String(20), ForeignKey("vehicle_master.vin"), index=True)
    part_code: Mapped[str] = mapped_column(String(20), ForeignKey("part_master.part_code"), index=True)
    failure_date: Mapped[date] = mapped_column(Date, index=True)
    odometer_at_failure: Mapped[int] = mapped_column(Integer)
    replaced: Mapped[bool] = mapped_column(Boolean, default=True)
    event_type: Mapped[str] = mapped_column(String(20), default="failure", index=True)

    __table_args__ = (Index("ix_jobcard_vin_part", "vin", "part_code"),)


class TelematicsWeekly(Base):
    __tablename__ = "telematics_weekly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(20), ForeignKey("vehicle_master.vin"), index=True)
    week_start_date: Mapped[date] = mapped_column(Date, index=True)

    week_km: Mapped[float] = mapped_column(Float, default=0.0)
    odometer_km: Mapped[float] = mapped_column(Float, default=0.0)

    coolant_temp_variance: Mapped[float] = mapped_column(Float, default=0.0)
    oil_pressure_dips: Mapped[float] = mapped_column(Float, default=0.0)
    battery_voltage_sag: Mapped[float] = mapped_column(Float, default=0.0)
    dtc_recurrence_rate: Mapped[float] = mapped_column(Float, default=0.0)
    harsh_braking_frequency: Mapped[float] = mapped_column(Float, default=0.0)
    overload_duty_share: Mapped[float] = mapped_column(Float, default=0.0)
    high_rpm_dwell_time: Mapped[float] = mapped_column(Float, default=0.0)
    short_trip_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    idle_time_pct: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("vin", "week_start_date", name="uq_vin_week"),)


class Rule(Base):
    __tablename__ = "rules"

    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_code: Mapped[str] = mapped_column(String(20), ForeignKey("part_master.part_code"), index=True)
    formula: Mapped[str] = mapped_column(String(1000))
    precision: Mapped[float] = mapped_column(Float, default=0.0)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    days_to_alert: Mapped[int] = mapped_column(Integer, default=0)
    sample_failures: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuleSignal(Base):
    __tablename__ = "rule_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("rules.rule_id"), index=True)
    signal: Mapped[str] = mapped_column(String(50))
    correlation: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    included: Mapped[bool] = mapped_column(Boolean, default=True)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(20), index=True)
    part_code: Mapped[str] = mapped_column(String(20), index=True)
    rule_id: Mapped[int] = mapped_column(Integer, nullable=True)

    failure_probability: Mapped[float] = mapped_column(Float, index=True)
    risk_tier: Mapped[str] = mapped_column(String(10), index=True)
    health_index: Mapped[float] = mapped_column(Float)
    window_from_days: Mapped[int] = mapped_column(Integer)
    window_to_days: Mapped[int] = mapped_column(Integer)

    rul_km: Mapped[float] = mapped_column(Float)
    rul_days: Mapped[int] = mapped_column(Integer, index=True)
    model_confidence: Mapped[float] = mapped_column(Float)
    degradation_trend: Mapped[float] = mapped_column(Float)

    top_signal: Mapped[str] = mapped_column(String(50))
    top_signal_share: Mapped[float] = mapped_column(Float)

    drivers: Mapped[list] = mapped_column(JSON)
    trend: Mapped[list] = mapped_column(JSON)
    curve: Mapped[list] = mapped_column(JSON)

    computed_date: Mapped[date] = mapped_column(Date)

    __table_args__ = (UniqueConstraint("vin", "part_code", name="uq_pred_vin_part"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(20), index=True)
    part_code: Mapped[str] = mapped_column(String(20))
    audience: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)