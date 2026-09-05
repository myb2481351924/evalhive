# 🐝 EvalHive

**CI-style LLM evaluation & regression gating — built by a test engineer, for LLM quality.**

[![MIT license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![CI](https://github.com/myb2481351924/evalhive/actions/workflows/ci.yml/badge.svg)](https://github.com/myb2481351924/evalhive/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-green)

LLM apps ship fast and regress silently: a prompt tweak, a model version bump, a
retrieval change — none of it fails your unit tests. EvalHive brings the test
engineer's discipline to model quality: declarative eval suites, layered metrics,
run-to-run regression detection with statistical significance, and a hard CI gate
that fails the build when quality drops.

> 中文文档见 [README.zh-CN.md](README.zh-CN.md)；**保姆级使用教程（中文）：[docs/TUTORIAL.zh-CN.md](docs/TUTORIAL.zh-CN.md)**。

## Features

- **Declarative evals** — one YAML: `providers × datasets × asserts`, versioned with your code
- **Layered metrics** — free deterministic assertions (regex, JSON schema, latency, cost,
  similarity) → LLM-as-judge (correctness, relevance, toxicity) → simplified RAGAS-style
  `faithfulness` / `answer-relevance`
- **Regression intelligence** — per-case diff vs a pinned baseline + **paired bootstrap
  95% CI** on pass-rate drift, so a 2-case flip on a 20-case suite is labeled *noise*,
  not a green checkmark
- **CI gate** — `--gate` exits non-zero on breach; ships JUnit XML, Markdown PR comments,
  and self-contained HTML reports
- **Auditable judges** — every verdict keeps the raw judge output; unparseable = fail, never pass
- **Reproducible & cheap** — response cache keyed by `(config_hash, provider, prompt)`;
  provider implementation salted so editing a model param or mock fixture invalidates
  stale cache. Same hash ⇒ same inputs ⇒ same rerun
- **Offline demo mode** — `mock://` providers run the *entire* pipeline (judges included)
  with zero API keys
- **API + dashboard** — FastAPI service, background eval runs, ECharts trend of
  pass-rate / cost / latency over runs

## Quickstart

```bash
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate on unix
pip install -e .

# 1) run an offline demo eval (mock providers, no keys needed)
evalhive run examples/rag-chat/config.yaml --gate -v --html out/report.html

# 2) compare against a previous run — drift with bootstrap CI
evalhive run examples/rag-chat/config.yaml --save
evalhive history            # pick an id
evalhive set-baseline 1
evalhive run examples/codegen/config.yaml --gate   # fails => exit 1

# 3) dashboard
evalhive serve              # http://127.0.0.1:8000
```

Or with Docker: `docker compose -f docker/docker-compose.yml up`.

### Dashboard

![EvalHive dashboard — pass-rate trend with baseline, cost & latency per run, run history](docs/dashboard.png)

### Self-contained HTML report

![EvalHive HTML report — provider summary, metric averages and per-case results](docs/report.png)

## How it works

```
                evals/*.yaml + dataset.jsonl
                         │
              ┌──────────▼──────────┐   deterministic: equals/regex/json-schema/…
   config →   │  runner (asyncio)   │──▶ metric registry
              └──────────┬──────────┘   LLM-judge: correctness/relevance/toxicity
                         │               RAG: faithfulness/answer-relevance
        provider matrix: target models   (judge = any provider, cached too)
                         │
                   CaseResult[] ──▶ RunResult (config_hash pinned)
                         │
        ┌────────────────┼────────────────┬───────────────┐
     JSON / JUnit /   HTML /        SQLite history    FastAPI+dashboard
       Markdown      report     baseline & runs       trend & control
                         │
                 gate: min_pass_rate + max_regression (bootstrap CI) ──▶ exit 1
```

## Config in 30 seconds

```yaml
description: Customer-support RAG chat — regression suite
judge_provider: judge                      # default judge for LLM metrics

providers:                                 # evaluated in the matrix
  - id: support-bot
    type: mock                             # or: openai (any OpenAI-compatible endpoint)
    model: mock://support-bot-v1
    responses_file: bot_responses.jsonl    # recorded fixtures => offline reruns

judge_providers:                           # services, never scored themselves
  - id: judge
    type: openai
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY

datasets:
  - path: dataset.jsonl                    # {"id","prompt","context","expected","assert":[…]}

defaults:
  assert:
    - {type: latency, threshold: 500}

gate:
  min_pass_rate: 0.8
  max_regression: 0.05                     # vs `set-baseline` run, in CI
```

## CI gate

Drop [`templates/github-actions/eval-gate.yml`](templates/github-actions/eval-gate.yml)
into your repo: run suite → fail the check on breach → comment a Markdown summary on the PR.

## Design decisions (and why)

| Decision | Why |
|---|---|
| **Mock providers as first-class** | The whole pipeline (runner → judge metrics → gate → reports) is demonstrable and testable offline. CI wiring can land before you buy tokens. |
| **Bootstrap CI on drift, not raw deltas** | Eval suites are small and LLM output is stochastic. Reporting `drift -20% [CI -60%, 0%] not significant` stops teams from chasing noise; a significant drop stops merges. |
| **Provider `cache_salt`** | A cache keyed only by prompt would return stale answers after you edit a model param or a mock fixture. The salt folds the provider implementation identity into the key. |
| **Judge protocol: `VERDICT` + `SCORE`, unparseable = fail** | LLM judges fail in style, not in logic. Strict machine parsing plus keeping the raw judge output makes verdicts auditable — and biases failure toward the safe side. |
| **Judge providers can't be targets** | Early design let judges sit in the same matrix as targets, which silently "evaluated" the judge against every case. Two namespaces (`providers` vs `judge_providers`) made the data flow obvious. |
| **Untrusted content is tag-fenced** | The model under test could try to manipulate its own grade. Judge prompts wrap `QUESTION`/`ANSWER` in `<untrusted>` tags with an explicit ignore-instructions directive — a first-line defense, with canonicalization on the roadmap. |

## Development

```bash
pip install -e ".[dev]"
pytest -q        # 33 tests: metrics, loader, bootstrap, e2e runner, cache salt, storage, API
```

CI (`.github/workflows/ci.yml`) runs the suite and then eats its own dog food:
`--gate` must pass on the healthy example and must **fail** on the regressed one —
proving the exit-code contract on every push.

## Roadmap

- More RAGAS-style metrics (context precision/recall), embedding similarity
- Stronger judge-injection defenses (canonicalization, constrained decoding of verdicts)
- Eval-suite auto-expansion from production traces (dataset flywheel)
- Cost budget enforcement per run; per-provider rate-limit profiles
- Postgres first-class support; multi-user auth for team servers
- `pipx install evalhive` distribution
