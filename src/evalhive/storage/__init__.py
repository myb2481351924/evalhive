"""SQLite-backed run history (SQLAlchemy 2, swappable to Postgres via DATABASE_URL)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..core.results import RunResult

DEFAULT_DB = Path(os.environ.get("EVALHIVE_DB", ".evalhive/history.sqlite3"))


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    config_hash: Mapped[str] = mapped_column(String(16), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="done")  # running|done|failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    n_cases: Mapped[int] = mapped_column(Integer, default=0)
    n_passed: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_baseline: Mapped[int] = mapped_column(Integer, default=0)


class Store:
    def __init__(self, url: str | None = None):
        self.url = url or f"sqlite:///{DEFAULT_DB}"
        DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.url)
        Base.metadata.create_all(self.engine)

    # -- write path -----------------------------------------------------------

    def save_run(self, result: RunResult, label: str) -> int:
        row_id = self.create_pending(label=label)
        self.finish_run(row_id, result)
        return row_id

    def create_pending(self, label: str) -> int:
        with Session(self.engine) as s:
            row = RunRow(label=label, created_at=datetime.now(timezone.utc), status="running")
            s.add(row)
            s.commit()
            return row.id

    def finish_run(self, run_id: int, result: RunResult) -> None:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            if not row:
                return
            row.status = "done"
            row.config_hash = result.config_hash
            row.n_cases = len(result.results)
            row.n_passed = sum(1 for e in result.results if e.passed)
            row.pass_rate = round(result.overall_pass_rate(), 4)
            row.payload = json.loads(result.model_dump_json())
            s.commit()

    def fail_run(self, run_id: int, error: str) -> None:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            if row:
                row.status = "failed"
                row.error = error[:2000]
                s.commit()

    def set_baseline(self, run_id: int) -> bool:
        with Session(self.engine) as s:
            s.query(RunRow).update({"is_baseline": 0})
            row = s.get(RunRow, run_id)
            if not row:
                return False
            row.is_baseline = 1
            s.commit()
            return True

    # -- read path ------------------------------------------------------------

    def list_runs(self, limit: int = 100) -> list[RunRow]:
        with Session(self.engine) as s:
            return list(s.scalars(select(RunRow).order_by(RunRow.id.desc()).limit(limit)))

    def get_run_row(self, run_id: int) -> RunRow | None:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            s.expunge(row) if row else None
            return row

    def get_run(self, run_id: int) -> RunResult | None:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
            return RunResult.model_validate(row.payload) if row and row.payload else None

    def get_baseline(self) -> RunResult | None:
        row = self.get_baseline_row()
        return self.get_run(row.id) if row else None

    def get_baseline_row(self) -> RunRow | None:
        with Session(self.engine) as s:
            row = s.scalars(select(RunRow).where(RunRow.is_baseline == 1)).first()
            s.expunge(row) if row else None
            return row
