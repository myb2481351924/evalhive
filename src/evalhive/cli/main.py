"""EvalHive CLI: run / diff / gate."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from .. import __version__
from ..config.loader import ConfigError, load_cases, load_config
from ..core.compare import diff_runs, gate_decision, load_run_result
from ..core.results import RunResult
from ..core.runner import run_evaluation
from ..report import to_junit_xml, to_markdown
from ..report.html import to_html
from ..storage import Store

app = typer.Typer(help="EvalHive — CI-style LLM evaluation & regression gate", no_args_is_help=True)


def _print_summary(result: RunResult) -> None:
    typer.echo(
        f"\n{'provider':<16}{'cases':>6}{'pass':>6}{'fail':>6}{'err':>6}"
        f"{'pass_rate':>11}{'avg_lat':>10}{'cost_usd':>10}{'avg_score':>10}"
    )
    for pid, s in sorted(result.summary().items()):
        typer.echo(
            f"{pid:<16}{s.total:>6}{s.passed:>6}{s.failed:>6}{s.errored:>6}"
            f"{s.pass_rate * 100:>10.1f}%{s.avg_latency_ms:>9.0f}ms{s.total_cost_usd:>10.4f}"
            f"{s.avg_score:>10.2f}"
        )


def _print_failures(result: RunResult, verbose: bool) -> int:
    fails = [e for e in result.results if not e.passed]
    for e in fails[: 20 if verbose else 10]:
        who = e.provider_id if e.prompt_id == "default" else f"{e.provider_id}/{e.prompt_id}"
        if e.error:
            typer.secho(f"  ✗ {who}/{e.case_id} ERROR {e.error}", fg=typer.colors.RED)
        else:
            bad = [m for m in e.metrics if not m.passed]
            typer.secho(
                f"  ✗ {who}/{e.case_id} " + "; ".join(f"{m.metric}={m.score:.2f}" for m in bad),
                fg=typer.colors.RED,
            )
            if verbose:
                for m in bad:
                    typer.echo(f"      {m.metric}: {m.detail[:200]}")
    if len(fails) > (20 if verbose else 10):
        typer.echo(f"  … {len(fails) - (20 if verbose else 10)} more failures")
    return len(fails)


@app.command()
def version() -> None:
    """Print the EvalHive version."""
    typer.echo(__version__)


@app.command()
def run(
    config: Path = typer.Argument(..., exists=True, help="Path to eval YAML"),
    gate: bool = typer.Option(False, "--gate", help="Exit 1 when gate thresholds are not met"),
    json_out: Path | None = typer.Option(None, "--json", help="Write the full RunResult as JSON"),
    junit_out: Path | None = typer.Option(None, "--junit", help="Write JUnit XML (CI artifact)"),
    md_out: Path | None = typer.Option(None, "--md", help="Write a Markdown summary (PR comment)"),
    html_out: Path | None = typer.Option(None, "--html", help="Write a self-contained HTML report"),
    baseline: Path | None = typer.Option(
        None, "--baseline", help="RunResult JSON to compare against"
    ),
    save: bool = typer.Option(False, "--save/--no-save", help="Persist the run to local history"),
    label: str | None = typer.Option(None, "--label", help="History label for this run"),
    concurrency: int = typer.Option(5, min=1, max=50, help="Parallel provider calls"),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Reuse cached provider responses"),
    verbose: bool = typer.Option(False, "-v", help="Show every failed metric with detail"),
) -> None:
    """Run the evaluation declared in a YAML config."""
    try:
        cfg, config_dir = load_config(config)
        cases = load_cases(cfg, config_dir)
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from e

    typer.echo(f"EvalHive v{__version__} — {cfg.description or str(config)}")
    judges = ", ".join(p.id for p in cfg.judge_providers) or "none"
    targets = ", ".join(p.id for p in cfg.providers)
    typer.echo(f"providers: {targets} | judges: {judges} | cases: {len(cases)}")

    def progress(done: int, total: int) -> None:
        typer.echo(f"\r  progress {done}/{total}", nl=False)

    result = asyncio.run(
        run_evaluation(
            cfg, cases, config_dir, concurrency=concurrency, use_cache=cache, progress=progress
        )
    )
    typer.echo(
        f"\nconfig_hash: {result.config_hash} (same hash => same inputs => reproducible rerun)"
    )
    _print_summary(result)
    _print_failures(result, verbose)

    decision = None
    base_run: RunResult | None = None
    if gate or baseline:
        if baseline:
            base_run = load_run_result(baseline)
        elif gate:
            base_run = Store().get_baseline()  # fall back to the run pinned via `set-baseline`
        decision = gate_decision(result, cfg.gate, base_run)
        typer.echo("\n── gate " + ("PASSED ✓" if decision.passed else "FAILED ✗"))
        for r in decision.reasons:
            typer.secho(f"  ! {r}", fg=typer.colors.YELLOW)
        if decision.diff:
            d = decision.diff
            typer.echo(
                f"  drift {d.drift:+.2%} (95% CI [{d.ci_low:+.2%}, {d.ci_high:+.2%}], "
                f"{'significant' if d.significant else 'not significant'}) "
                f"baseline={d.baseline_pass_rate:.2%} current={d.current_pass_rate:.2%}"
            )

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"wrote {json_out}")
    if junit_out:
        junit_out.parent.mkdir(parents=True, exist_ok=True)
        junit_out.write_text(to_junit_xml(result), encoding="utf-8")
        typer.echo(f"wrote {junit_out}")
    if md_out:
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(to_markdown(result, decision), encoding="utf-8")
        typer.echo(f"wrote {md_out}")
    if html_out:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(to_html(result, decision), encoding="utf-8")
        typer.echo(f"wrote {html_out}")
    if save:
        run_id = Store().save_run(result, label or str(config))
        typer.echo(f"saved as run #{run_id} (use `evalhive set-baseline {run_id}` to pin it)")

    if gate and decision and not decision.passed:
        raise typer.Exit(1)


@app.command()
def diff(
    baseline: Path = typer.Argument(..., exists=True, help="Baseline RunResult JSON"),
    current: Path = typer.Argument(..., exists=True, help="Current RunResult JSON"),
    only_changes: bool = typer.Option(True, "--all/--only-changes"),
) -> None:
    """Compare two RunResult JSON files with a paired bootstrap on the drift."""
    report = diff_runs(load_run_result(baseline), load_run_result(current))
    typer.echo(
        f"baseline {report.baseline_hash}: {report.baseline_pass_rate:.2%}  "
        f"current  {report.current_hash}: {report.current_pass_rate:.2%}"
    )
    typer.echo(
        f"drift {report.drift:+.2%}  95% CI [{report.ci_low:+.2%}, {report.ci_high:+.2%}]  "
        f"{'STATISTICALLY SIGNIFICANT' if report.significant else 'not significant (likely noise)'}"
    )
    changed = [
        c for c in report.cases if c.change in ("newly_failed", "newly_passed", "added", "removed")
    ]
    if not changed:
        typer.echo("no case-level changes")
    for c in changed:
        color = {
            "newly_failed": "RED",
            "newly_passed": "GREEN",
            "added": "CYAN",
            "removed": "YELLOW",
        }[c.change]
        if only_changes or c.change in ("newly_failed", "newly_passed"):
            typer.secho(f"  {c.change:<14} {c.label}", fg=getattr(typer.colors, color))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Start the EvalHive API + dashboard (http://{host}:{port})."""
    import uvicorn

    from ..api import create_app

    typer.echo(f"EvalHive dashboard on http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="How many recent runs to show"),
) -> None:
    """List recent runs from local history."""
    rows = Store().list_runs(limit=limit)
    if not rows:
        typer.echo("no saved runs yet (use `evalhive run ... --save`)")
        return
    typer.echo(f"{'id':>4}  {'baseline':<9}{'hash':<18}{'pass_rate':<10}{'cases':<7}label")
    for r in rows:
        typer.echo(
            f"{r.id:>4}  {'★' if r.is_baseline else ' ':<9}{r.config_hash:<18}"
            f"{r.pass_rate:<10.2%}{r.n_cases:<7}{r.label}"
        )


@app.command("set-baseline")
def set_baseline(
    run_id: int = typer.Argument(..., help="Run id from `evalhive history`"),
) -> None:
    """Pin a saved run as the baseline for `--gate` regression checks."""
    if Store().set_baseline(run_id):
        typer.echo(f"run #{run_id} is now the baseline")
    else:
        typer.secho(f"run #{run_id} not found", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
