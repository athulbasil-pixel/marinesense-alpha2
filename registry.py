"""MarineSense Alpha 2.0 database models and explicit registry operations.

Demo software, NOT a production multi-tenant authorisation solution.
Compatible with SQLite (ephemeral in Community Cloud) and Postgres.
"""
from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from sqlalchemy import (
    create_engine, ForeignKey, String, Text, Float, Integer, DateTime,
    UniqueConstraint, select, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

UTC = dt.timezone.utc


def now_utc():
    return dt.datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Fleet(Base):
    __tablename__ = "fleet"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    operator: Mapped[str] = mapped_column(String(150), default="")


class Vessel(Base):
    __tablename__ = "vessel"
    id: Mapped[int] = mapped_column(primary_key=True)
    fleet_id: Mapped[int] = mapped_column(ForeignKey("fleet.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    imo: Mapped[str] = mapped_column(String(20), default="")
    __table_args__ = (UniqueConstraint("fleet_id", "name"),)


class Machine(Base):
    __tablename__ = "machine"
    id: Mapped[int] = mapped_column(primary_key=True)
    vessel_id: Mapped[int] = mapped_column(ForeignKey("vessel.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    serial: Mapped[str] = mapped_column(String(120), default="")
    rated_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rated_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (UniqueConstraint("vessel_id", "tag"),)

    @property
    def ms_number(self):
        return f"MS-{self.id:06d}"


class Component(Base):
    __tablename__ = "component"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    bearing_model: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class SensorPoint(Base):
    __tablename__ = "sensor_point"
    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("component.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sensor_code: Mapped[str] = mapped_column(String(80), default="")
    oem: Mapped[str] = mapped_column(String(100), default="")
    sensor_model: Mapped[str] = mapped_column(String(100), default="")
    sensor_type: Mapped[str] = mapped_column(String(80), default="Accelerometer")
    unit: Mapped[str] = mapped_column(String(40), default="arbitrary")
    __table_args__ = (UniqueConstraint("component_id", "name", "direction"),)


class Measurement(Base):
    __tablename__ = "measurement"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"), nullable=False)
    point_id: Mapped[int] = mapped_column(ForeignKey("sensor_point.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    sample_rate_hz: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count_baseline: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count_test: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_load: Mapped[str] = mapped_column(String(120), default="")
    baseline_rms: Mapped[float] = mapped_column(Float, nullable=False)
    test_rms: Mapped[float] = mapped_column(Float, nullable=False)
    rms_change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    peaks_baseline_json: Mapped[str] = mapped_column(Text, nullable=False)
    peaks_test_json: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    test_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class Report(Base):
    __tablename__ = "engineering_report"
    id: Mapped[int] = mapped_column(primary_key=True)
    measurement_id: Mapped[int] = mapped_column(ForeignKey("measurement.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


@lru_cache(maxsize=4)
def get_engine(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, connection_record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    Base.metadata.create_all(engine)
    return engine


def create_fleet(engine, name: str, operator: str = "") -> int:
    with Session(engine) as s, s.begin():
        row = Fleet(name=name.strip(), operator=operator.strip())
        s.add(row)
        s.flush()
        return row.id


def create_vessel(engine, fleet_id: int, name: str, imo: str = "") -> int:
    with Session(engine) as s, s.begin():
        row = Vessel(fleet_id=fleet_id, name=name.strip(), imo=imo.strip())
        s.add(row)
        s.flush()
        return row.id


def create_machine(engine, **fields) -> str:
    if not fields.get("name", "").strip() or not fields.get("tag", "").strip():
        raise ValueError("Machinery name and unique vessel equipment tag are required.")
    with Session(engine) as s, s.begin():
        row = Machine(**fields)
        s.add(row)
        s.flush()
        return row.ms_number


def create_component(engine, **fields) -> int:
    with Session(engine) as s, s.begin():
        row = Component(**fields)
        s.add(row)
        s.flush()
        return row.id


def create_sensor_point(engine, **fields) -> int:
    with Session(engine) as s, s.begin():
        row = SensorPoint(**fields)
        s.add(row)
        s.flush()
        return row.id


def create_measurement(engine, **fields) -> int:
    with Session(engine) as s, s.begin():
        linked_machine = s.scalar(
            select(Component.machine_id).join(SensorPoint, SensorPoint.component_id == Component.id)
            .where(SensorPoint.id == fields["point_id"])
        )
        if linked_machine != fields["machine_id"]:
            raise ValueError("Sensor point does not belong to the selected machinery assembly")
        row = Measurement(**fields)
        s.add(row)
        s.flush()
        return row.id


def create_report(engine, measurement_id: int, model_name: str, markdown: str) -> int:
    with Session(engine) as s, s.begin():
        row = Report(measurement_id=measurement_id, model_name=model_name, report_markdown=markdown)
        s.add(row)
        s.flush()
        return row.id


def list_fleets(engine):
    with Session(engine) as s:
        return [{"id": o.id, "name": o.name, "operator": o.operator} for o in s.scalars(select(Fleet).order_by(Fleet.id))]


def list_vessels(engine, fleet_id=None):
    with Session(engine) as s:
        stmt = select(Vessel).order_by(Vessel.id)
        if fleet_id is not None:
            stmt = stmt.where(Vessel.fleet_id == fleet_id)
        return [{"id": o.id, "fleet_id": o.fleet_id, "name": o.name, "imo": o.imo} for o in s.scalars(stmt)]


def list_machines(engine, vessel_id=None):
    with Session(engine) as s:
        stmt = select(Machine).order_by(Machine.id)
        if vessel_id is not None:
            stmt = stmt.where(Machine.vessel_id == vessel_id)
        return [machine_dict(o) for o in s.scalars(stmt)]


def machine_dict(o):
    return {"id": o.id, "ms_number": o.ms_number, "vessel_id": o.vessel_id,
            "name": o.name, "tag": o.tag, "equipment_type": o.equipment_type,
            "manufacturer": o.manufacturer, "model": o.model, "serial": o.serial,
            "rated_rpm": o.rated_rpm, "rated_power_kw": o.rated_power_kw,
            "description": o.description}


def get_machine_by_number(engine, public_number: str):
    value = public_number.strip().upper()
    if not value.startswith("MS-") or not value[3:].isdigit():
        return None
    with Session(engine) as s:
        o = s.get(Machine, int(value[3:]))
        return machine_dict(o) if o else None


def list_components(engine, machine_id: int):
    with Session(engine) as s:
        return [{"id": o.id, "machine_id": o.machine_id, "name": o.name,
                 "category": o.category, "manufacturer": o.manufacturer,
                 "model": o.model, "bearing_model": o.bearing_model,
                 "notes": o.notes} for o in s.scalars(select(Component).where(Component.machine_id == machine_id).order_by(Component.id))]


def list_sensor_points(engine, component_ids: list[int]):
    if not component_ids:
        return []
    with Session(engine) as s:
        return [{"id": o.id, "component_id": o.component_id, "name": o.name,
                 "direction": o.direction, "sensor_code": o.sensor_code,
                 "oem": o.oem, "sensor_model": o.sensor_model, "sensor_type": o.sensor_type,
                 "unit": o.unit} for o in s.scalars(select(SensorPoint).where(SensorPoint.component_id.in_(component_ids)).order_by(SensorPoint.id))]


def get_recent_measurements(engine, machine_id: int):
    with Session(engine) as s:
        rows = s.scalars(select(Measurement).where(Measurement.machine_id == machine_id)
                         .order_by(Measurement.created_at.desc(), Measurement.id.desc()).limit(30))
        return [{"id": o.id, "created_at": o.created_at.isoformat(), "point_id": o.point_id,
                 "baseline_rms": o.baseline_rms, "test_rms": o.test_rms,
                 "rms_change_pct": o.rms_change_pct, "unit": o.unit,
                 "actual_rpm": o.actual_rpm, "source": o.source} for o in rows]


def get_reports_for_machine(engine, machine_id: int):
    with Session(engine) as s:
        stmt = (select(Report, Measurement).join(Measurement, Report.measurement_id == Measurement.id)
                .where(Measurement.machine_id == machine_id).order_by(Report.id.desc()).limit(20))
        return [{"id": r.id, "measurement_id": m.id, "model_name": r.model_name,
                 "created_at": r.created_at.isoformat(), "text": r.report_markdown}
                for r, m in s.execute(stmt)]


def make_example_registry(engine):
    """Seed an illustrative fleet only when the registry is empty."""
    if list_fleets(engine):
        return False
    fid = create_fleet(engine, "Demonstration Fleet", "MarineSense prototype")
    vid = create_vessel(engine, fid, "Demo Vessel 01", "")
    num = create_machine(engine, vessel_id=vid, name="Auxiliary Cooling Water Pump No. 1",
                         tag="ACWP-01", equipment_type="Centrifugal Pump Assembly",
                         manufacturer="", model="", serial="", rated_rpm=1800.0,
                         rated_power_kw=None, description="Synthetic demonstration; not a real vessel or pump")
    machine = get_machine_by_number(engine, num)
    cid = create_component(engine, machine_id=machine["id"], name="Electric Motor",
                           category="Motor", manufacturer="", model="", bearing_model="", notes="")
    create_sensor_point(engine, component_id=cid, name="Motor drive-end bearing",
                        direction="Horizontal", sensor_code="SEN-DEMO-01", oem="Virtual",
                        sensor_model="Demo node", sensor_type="Virtual accelerometer", unit="arbitrary")
    return True
