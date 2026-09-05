"""Load evaluation configs and compute reproducible config hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Case, EvalConfig

class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> tuple[EvalConfig, Path]:
    """Parse a YAML config file; returns (config, config_dir) for path resolution."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {p}: {e}") from e
    try:
        cfg = EvalConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config in {p}:\n{e}") from e
    if not cfg.providers:
        raise ConfigError(f"{p}: at least one target provider is required")
    if not cfg.datasets:
        raise ConfigError(f"{p}: at least one dataset is required")
    ids = [pr.id for pr in cfg.providers] + [pr.id for pr in cfg.judge_providers]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{p}: duplicate provider ids")
    judge_ids = {pr.id for pr in cfg.judge_providers}
    if cfg.judge_provider and cfg.judge_provider not in judge_ids:
        raise ConfigError(f"{p}: judge_provider {cfg.judge_provider!r} not declared in judge_providers")
    return cfg, p.parent


def load_cases(cfg: EvalConfig, config_dir: Path) -> list[Case]:
    """Load every dataset referenced by the config; case ids must be unique."""
    cases: list[Case] = []
    seen: set[str] = set()
    for ds in cfg.datasets:
        ds_path = (config_dir / ds.path).resolve()
        if not ds_path.exists():
            raise ConfigError(f"dataset file not found: {ds_path}")
        for lineno, line in enumerate(ds_path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                case = Case.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                raise ConfigError(f"{ds_path}:{lineno}: bad case row: {e}") from e
            # dataset-level vars are defaults; case vars override them
            merged = {**ds.vars, **case.vars}
            case.vars = merged
            if case.id in seen:
                raise ConfigError(f"{ds_path}:{lineno}: duplicate case id {case.id!r}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise ConfigError("no cases found in datasets")
    _validate_judge_refs(cfg, cases, str(config_dir))
    return cases


def _validate_judge_refs(cfg: EvalConfig, cases: list[Case], where: str) -> None:
    judge_ids = {pr.id for pr in cfg.judge_providers}
    for a in cfg.defaults.assert_:
        if a.provider and a.provider not in judge_ids:
            raise ConfigError(f"{where}: default assertion provider {a.provider!r} "
                              "is not a judge_providers id")
    for c in cases:
        for a in c.assert_:
            if a.provider and a.provider not in judge_ids:
                raise ConfigError(f"{where}: case {c.id!r} assertion provider {a.provider!r} "
                                  "is not a judge_providers id")


def config_hash(cfg: EvalConfig, cases: list[Case], config_dir: Path | None = None) -> str:
    """Stable sha256 over config + dataset content (+ mock fixture contents when
    ``config_dir`` is given). Same hash => same inputs => reproducible rerun.

    Mock response files are part of the *inputs* in offline mode: editing a
    fixture changes the hash exactly like editing the dataset would.
    """
    fixtures: dict[str, str] = {}
    if config_dir is not None:
        for pr in [*cfg.providers, *cfg.judge_providers]:
            if pr.type == "mock" and pr.responses_file:
                p = Path(pr.responses_file)
                if not p.is_absolute():
                    p = config_dir / p
                if p.exists():
                    fixtures[pr.id] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    payload = {
        "config": cfg.model_dump(mode="json", by_alias=True),
        "cases": [c.model_dump(mode="json", by_alias=True) for c in cases],
        "fixtures": fixtures,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
