"""SQLite-backed run history (SQLAlchemy 2, swappable to Postgres via DATABASE_URL)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from ..core.results import RunResult

DEFAULT_DB = Path(".evalhive") / "history.sqlite3"


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    config_hash: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    n_cases: Mapped[int] = mapped_column(Integer)
    n_passed: Mapped[int] = mapped_column(Integer)
    pass_rate: Mapped[float] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    is_baseline: Mapped[int] = mapped_column(Integer, default=0)


class Store:
    def __init__(self, url: str | None = None):
        self.engine = create_engine(url or f"sqlite:///{DEFAULT_DB}")
        DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    def save_run(self, result: RunResult, label: str) -> int:
        with Session(self.engine) as s:
            row = RunRow(
                label=label,
                config_hash=result.config_hash,
                created_at=datetime.now(timezone.utc),
                n_cases=len(result.results),
                n_passed=sum(1 for e in result.results if e.passed),
                pass_rate=round(result.overall_pass_rate(), 4),
                payload=json.loads(result.model_dump_json()),
            )
            s.add(row)
            s.commit()
            return row.id

    def list_runs(self, limit: int = 100) -> list[RunRow]:
        with Session(self.engine) as s:
            return list(s.scalars(select(RunRow).order_by(RunRow.id.desc()).limit(limit)))

    def get_run(self, run_id: int) -> RunResult | None:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            return RunResult.model_validate(row.payload) if row else None

    def set_baseline(self, run_id: int) -> bool:
        with Session(self.engine) as s:
            s.query(RunRow).update({"is_baseline": 0})
            row = s.get(RunRow, run_id)
            if not row:
                return False
            row.is_baseline = 1
            s.commit()
            return True

    def get_baseline(self) -> RunResult | None:
        with Session(self.engine) as s:
            row = s.scalars(select(RunRow).where(RunRow.is_baseline == 1)).first()
            return RunResult.model_validate(row.payload) if row else None
