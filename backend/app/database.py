"""SQLAlchemy models. Works with SQLite (default) and PostgreSQL / TimescaleDB (DATABASE_URL)."""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Station(Base):
    __tablename__ = "stations"
    id = Column(String(32), primary_key=True)
    name = Column(String(200), nullable=False)
    monitoring_type = Column(String(32), nullable=False)  # air_quality | water_quality | noise
    location = Column(String(200))
    latitude = Column(Float)
    longitude = Column(Float)
    zone_category = Column(String(32))  # industrial | residential | commercial | silence | water_body
    water_class = Column(String(4), nullable=True)
    jurisdiction = Column(String(8), default="IN")
    parameters = Column(JSON, default=list)
    sensors = Column(JSON, default=list)
    operational_status = Column(String(32), default="active")  # active | maintenance | offline
    last_communication = Column(DateTime, nullable=True)
    notes = Column(Text, default="")


class Measurement(Base):
    __tablename__ = "measurements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(String(32), ForeignKey("stations.id"), index=True)
    timestamp = Column(DateTime, index=True)
    parameter = Column(String(32), index=True)
    value = Column(Float, nullable=True)
    unit = Column(String(16))
    quality_flag = Column(String(24), default="valid")  # valid | suspect | invalid | missing
    flag_reason = Column(Text, default="")
    source = Column(String(32), default="dataset")


Index("ix_meas_station_param_ts", Measurement.station_id, Measurement.parameter, Measurement.timestamp)


class WeatherObservation(Base):
    __tablename__ = "weather"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, index=True)
    location = Column(String(100))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    temperature = Column(Float)
    humidity = Column(Float)
    wind_speed = Column(Float)
    wind_direction = Column(Float)
    rainfall = Column(Float)
    source = Column(String(64))
    retrieved_at = Column(DateTime, default=datetime.now)


class RegisteredSource(Base):
    __tablename__ = "registered_sources"
    id = Column(String(32), primary_key=True)
    name = Column(String(200))
    category = Column(String(64))
    latitude = Column(Float)
    longitude = Column(Float)


class StandardRecord(Base):
    __tablename__ = "standards"
    id = Column(String(64), primary_key=True)
    data = Column(JSON)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.now)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String(32), primary_key=True)
    station_id = Column(String(32), index=True)
    parameter = Column(String(32))
    category = Column(String(48))  # Normal ... Critical Review Required | Sensor Verification Required
    alert_type = Column(String(48))  # threshold_exceedance | spike | persistent | sensor_failure | ...
    priority_rank = Column(Integer, default=0)
    title = Column(String(300))
    evidence = Column(JSON)
    ai_interpretation = Column(Text, default="")
    standard_ref = Column(JSON, nullable=True)
    status = Column(String(24), default="open")  # open | acknowledged | confirmed | rejected | closed
    occurrences = Column(Integer, default=1)
    first_seen = Column(DateTime, default=datetime.now)
    last_seen = Column(DateTime, default=datetime.now)
    run_id = Column(String(32))
    incident_id = Column(String(32), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String(32), primary_key=True)
    station_id = Column(String(32), index=True)
    parameter = Column(String(32))
    title = Column(String(300))
    start_time = Column(DateTime)
    status = Column(String(32), default="open")  # open | under_review | field_inspection_requested | investigating | escalated | closed
    investigation_status = Column(String(48), default="not_started")
    priority = Column(String(48))
    measurement = Column(JSON)
    applicable_reference = Column(JSON)
    evidence = Column(JSON)
    recommendation = Column(JSON)
    assigned_to = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)


class IncidentAction(Base):
    __tablename__ = "incident_actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String(32), index=True)
    action = Column(String(48))
    actor = Column(String(100))
    note = Column(Text, default="")
    data = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.now)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String(32), primary_key=True)
    scope = Column(String(32))  # station id or NETWORK
    trigger = Column(String(64))
    status = Column(String(32))  # running | awaiting_human_review | approved | rejected | reassessment_requested | failed
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    result = Column(JSON)
    trace = Column(JSON)
    events = Column(JSON)
    risk = Column(JSON)
    human_decision = Column(JSON, nullable=True)
    parent_run = Column(String(32), nullable=True)


class Report(Base):
    __tablename__ = "reports"
    id = Column(String(32), primary_key=True)
    created_at = Column(DateTime, default=datetime.now)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    station_ids = Column(JSON)
    content = Column(JSON)
    status = Column(String(24), default="draft")  # draft | approved
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)


class BanditArm(Base):
    __tablename__ = "bandit_arms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    context = Column(String(64), index=True)
    arm = Column(String(200))
    pulls = Column(Integer, default=0)
    reward_sum = Column(Float, default=0.0)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
