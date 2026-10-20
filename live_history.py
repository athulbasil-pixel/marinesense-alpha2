"""Persistent, bounded SIMULATION summaries for MarineSense Alpha 2.1.

Adds only three new tables to the existing registry metadata. Raw waveforms are
never stored here. This is a research demonstration, NOT condition certification.
Each stored minute is an observed set of 5-second simulation frames; missing
browser updates are never reconstructed or labelled as collected measurements.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import numpy as np
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

import registry as reg


class LiveSimulationSession(reg.Base):
    __tablename__ = "live_simulation_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="synthetic_browser_demo")
    __table_args__ = (Index("ix_live_session_machine_start", "machine_id", "started_at"),)


class LiveMinuteSummary(reg.Base):
    __tablename__ = "live_simulation_minute"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("live_simulation_session.id"), nullable=False)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"), nullable=False)
    point_id: Mapped[int] = mapped_column(ForeignKey("sensor_point.id"), nullable=False)
    sensor_code: Mapped[str] = mapped_column(String(80), nullable=False)
    minute_index: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stored_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_frames: Mapped[int] = mapped_column(Integer, nullable=False)
    average_rms: Mapped[float] = mapped_column(Float, nullable=False)
    maximum_rms: Mapped[float] = mapped_column(Float, nullable=False)
    last_rms: Mapped[float] = mapped_column(Float, nullable=False)
    rpm_last: Mapped[float] = mapped_column(Float, nullable=False)
    one_x_hz_last: Mapped[float] = mapped_column(Float, nullable=False)
    four_x_hz_last: Mapped[float] = mapped_column(Float, nullable=False)
    one_x_amplitude_last: Mapped[float] = mapped_column(Float, nullable=False)
    four_x_amplitude_last: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="arbitrary")
    partial_window: Mapped[bool] = mapped_column(nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("session_id", "point_id", "minute_index", name="uq_live_session_point_minute"),
        Index("ix_live_minute_machine_time", "machine_id", "window_start_utc"),
    )


class LiveSimulationEvent(reg.Base):
    __tablename__ = "live_simulation_event"
    event_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("live_simulation_session.id"), nullable=False)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"), nullable=False)
    point_id: Mapped[int | None] = mapped_column(ForeignKey("sensor_point.id"), nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (Index("ix_live_event_machine_time", "machine_id", "created_at_utc"),)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_point_belongs_to_machine(s: Session, machine_id: int, point_id: int) -> None:
    owner = s.scalar(select(reg.Component.machine_id)
                     .join(reg.SensorPoint, reg.SensorPoint.component_id == reg.Component.id)
                     .where(reg.SensorPoint.id == point_id))
    if owner != machine_id:
        raise ValueError(f"Sensor point ID {point_id} does not belong to machine ID {machine_id}.")


def _assert_session(s: Session, session_id: str, machine_id: int):
    record = s.get(LiveSimulationSession, session_id)
    if record is None or record.machine_id != machine_id:
        raise ValueError("Simulation session does not belong to the selected machine.")
    return record


def open_session(engine, machine_id: int, point_ids: list[int]) -> str:
    """Create a durable session before activating recorded simulation."""
    if not point_ids or len(set(point_ids)) != len(point_ids):
        raise ValueError("Sensor point selection must be non-empty and unique.")
    identifier = str(uuid.uuid4())
    with Session(engine) as s, s.begin():
        if s.get(reg.Machine, machine_id) is None:
            raise ValueError("Selected machine is not registered.")
        for point_id in point_ids:
            _assert_point_belongs_to_machine(s, machine_id, point_id)
        s.add(LiveSimulationSession(id=identifier, machine_id=machine_id, started_at=utc_now()))
    return identifier


def make_accumulator(minute_index: int) -> dict:
    return {"minute_index": int(minute_index), "points": {}}


def observe(accumulator: dict, point: dict, frame: dict, rpm: float) -> None:
    """Aggregate observed frames only; no assumption about missed Streamlit ticks."""
    pid = int(point["id"])
    last = accumulator["points"].get(pid)
    rms = float(frame["rms"])
    frequency = np.asarray(frame["freq_hz"])
    magnitude = np.asarray(frame["spectrum"])
    freq_1 = float(rpm) / 60.0
    freq_4 = 4.0 * freq_1
    last_values = {
        "point_id": pid,
        "sensor_code": point["sensor_code"] or f"POINT-{pid}",
        "rpm_last": float(rpm),
        "one_x_hz_last": freq_1,
        "four_x_hz_last": freq_4,
        "one_x_amplitude_last": float(magnitude[np.abs(frequency - freq_1).argmin()]),
        "four_x_amplitude_last": float(magnitude[np.abs(frequency - freq_4).argmin()]),
        "unit": "arbitrary",
        "last_rms": rms,
    }
    if last is None:
        last = {**last_values, "observed_frames": 0, "rms_total": 0.0, "maximum_rms": rms}
        accumulator["points"][pid] = last
    last["observed_frames"] += 1
    last["rms_total"] += rms
    last["maximum_rms"] = max(last["maximum_rms"], rms)
    last.update(last_values)


def save_minute(engine, session_id: str, machine_id: int, started_at: datetime,
                accumulator: dict, *, partial: bool = False) -> int:
    """Idempotently insert up to four compact rows for one observed minute."""
    points = accumulator["points"]
    if not points:
        return 0
    index = int(accumulator["minute_index"])
    if index < 0:
        raise ValueError("Minute index must be non-negative")
    if started_at.tzinfo is None:
        raise ValueError("Start timestamp must be UTC-aware")
    window_start = started_at + timedelta(minutes=index)
    stored_time = utc_now()
    with Session(engine) as s, s.begin():
        _assert_session(s, session_id, machine_id)
        for point_id in points:
            _assert_point_belongs_to_machine(s, machine_id, point_id)
        values = []
        for point in points.values():
            record = {k: point[k] for k in (
                "point_id", "sensor_code", "rpm_last", "one_x_hz_last", "four_x_hz_last",
                "one_x_amplitude_last", "four_x_amplitude_last", "unit", "last_rms",
                "maximum_rms", "observed_frames",
            )}
            record.update(session_id=session_id, machine_id=machine_id, minute_index=index,
                          window_start_utc=window_start, stored_at_utc=stored_time,
                          average_rms=point["rms_total"] / point["observed_frames"],
                          partial_window=bool(partial))
            values.append(record)
        if engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
            stmt = insert(LiveMinuteSummary).values(values).on_conflict_do_nothing(
                constraint="uq_live_session_point_minute")
        elif engine.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
            stmt = insert(LiveMinuteSummary).values(values).on_conflict_do_nothing(
                index_elements=["session_id", "point_id", "minute_index"])
        else:
            raise RuntimeError("Live summary persistence supports PostgreSQL and SQLite only")
        result = s.execute(stmt)
        return int(result.rowcount or 0)


def log_event(engine, session_id: str, machine_id: int, kind: str, details: str,
              *, point_id: int | None = None, event_key: str | None = None) -> str:
    if len(details) > 500:
        raise ValueError("Event details exceed 500 characters")
    event_key = event_key or str(uuid.uuid4())
    with Session(engine) as s, s.begin():
        _assert_session(s, session_id, machine_id)
        if point_id is not None:
            _assert_point_belongs_to_machine(s, machine_id, point_id)
        if s.get(LiveSimulationEvent, event_key) is None:
            s.add(LiveSimulationEvent(event_key=event_key, session_id=session_id,
                    machine_id=machine_id, point_id=point_id,
                    created_at_utc=utc_now(), kind=kind, details=details))
    return event_key


def close_session(engine, session_id: str, machine_id: int) -> None:
    with Session(engine) as s, s.begin():
        record = _assert_session(s, session_id, machine_id)
        if record.ended_at is None:
            record.ended_at = utc_now()


def list_sessions(engine, machine_id: int, limit: int = 30) -> list[dict]:
    with Session(engine) as s:
        rows = s.scalars(select(LiveSimulationSession)
                         .where(LiveSimulationSession.machine_id == machine_id)
                         .order_by(LiveSimulationSession.started_at.desc()).limit(min(limit, 100)))
        return [{"id": r.id, "started_utc": r.started_at.isoformat(),
                 "ended_utc": r.ended_at.isoformat() if r.ended_at else "Not formally stopped",
                 "source": r.source} for r in rows]


def list_minutes(engine, session_id: str, limit: int = 1000) -> list[dict]:
    with Session(engine) as s:
        rows = s.scalars(select(LiveMinuteSummary)
                         .where(LiveMinuteSummary.session_id == session_id)
                         .order_by(LiveMinuteSummary.minute_index.desc(), LiveMinuteSummary.point_id)
                         .limit(min(limit, 2000)))
        return [{"time_utc": r.window_start_utc.isoformat(), "minute_index": r.minute_index,
                 "sensor": r.sensor_code, "point_id": r.point_id,
                 "avg_rms": round(r.average_rms, 5), "peak_rms": round(r.maximum_rms, 5),
                 "last_rms": round(r.last_rms, 5), "rpm": r.rpm_last,
                 "1x_hz": r.one_x_hz_last, "4x_hz": r.four_x_hz_last,
                 "1x_amplitude": round(r.one_x_amplitude_last, 5),
                 "4x_amplitude": round(r.four_x_amplitude_last, 5),
                 "observed_frames": r.observed_frames, "partial_window": r.partial_window,
                 "unit": r.unit} for r in rows]


def list_events(engine, session_id: str, limit: int = 150) -> list[dict]:
    with Session(engine) as s:
        rows = s.scalars(select(LiveSimulationEvent)
                         .where(LiveSimulationEvent.session_id == session_id)
                         .order_by(LiveSimulationEvent.created_at_utc.desc())
                         .limit(min(limit, 1000)))
        return [{"time_utc": r.created_at_utc.isoformat(), "point_id": r.point_id,
                 "kind": r.kind, "details": r.details} for r in rows]
