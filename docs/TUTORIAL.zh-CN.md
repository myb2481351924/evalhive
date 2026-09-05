# EvalHive 使用教程（中文）

> 10 分钟内跑通第一个评测；30 分钟接入自己的模型和 CI 门禁。

## 0. 这是什么

EvalHive 用「回归测试 + CI 门禁」的思路管理 LLM 应用质量：写一份 YAML 评测配置，
跑一批用例（提示词 + 期望），用三层指标打分（确定性断言 / LLM 评委 / RAG 指标），
和历史基线对比，质量退化就让 CI 红灯。

## 1. 环境要求

- Python **3.11+**（开发环境为 3.13）
- git（可选：Docker Desktop、任意 OpenAI 兼容模型的 API Key）

## 2. 安装（2 分钟）

```bash
git clone https://github.com/myb2481351924/evalhive.git
cd evalhive

python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows Git Bash:
source .venv/Scripts/activate
# macOS / Linux:
source .venv/bin/activate

pip install -e ".[dev]"
evalhive version        # 输出 0.1.0 即安装成功
```

## 3. 第一次跑评测（零配置、零 API Key）

仓库自带三个离线示例（mock provider，不需要任何 Key）：

```bash
# RAG 客服问答：含 LLM 评委 + faithfulness 指标
evalhive run examples/rag-chat/config.yaml --gate -v

# 模型对比矩阵：model-a vs model-b（model-b 有意退化，gate 会失败、退出码 1）
evalhive run examples/codegen/config.yaml --gate

# function-calling：JSON schema 校验 + 相关性评委
evalhive run examples/function-calling/config.yaml --gate
```

`--gate` 表示按配置里的 `gate:` 阈值判定，不达标退出码 1（CI 拦截用）。
第一条命令的预期输出：5 个用例 4 过 1 挂（c3 是故意写错答案的演示用例），80% ≥ 80% 门禁通过。

生成离线报告：

```bash
evalhive run examples/rag-chat/config.yaml --html out/report.html --junit out/junit.xml --md out/summary.md
start out/report.html   # 浏览器打开自包含 HTML 报告
```

## 4. 看板（Web Dashboard）

```bash
evalhive serve          # 默认 http://127.0.0.1:8000
```

- 顶部下拉框选择示例套件，点 **▶ Run eval** 在后台触发评测，看板每 4 秒自动刷新
- 图表：通过率趋势（含基线虚线）、每轮成本/延迟、run 历史表
- 每行 **view** 打开用例明细弹窗，**set baseline** 把该轮设为回归基线
- 换端口：`evalhive serve --port 8017`

## 5. 接入真实模型（OpenAI 兼容接口均可）

任何实现 `/v1/chat/completions` 的服务都能接：OpenAI、DeepSeek、通义、Kimi、本地 vLLM/Ollama 等。

```bash
# 1) 设置 Key（provider 里 api_key_env 指定的环境变量名）
set OPENAI_API_KEY=sk-xxxx          # Windows cmd
export OPENAI_API_KEY=sk-xxxx       # Git Bash / macOS / Linux
```

把配置里的 mock provider 换成 openai 类型（新建 `my-eval/config.yaml`）：

```yaml
description: 我的第一份真实评测
judge_provider: judge

providers:                      # 被测对象（会进评分矩阵）
  - id: gpt4o-mini
    type: openai
    model: gpt-4o-mini
    # base_url: https://api.deepseek.com/v1     # 换厂商只改这一行
    # api_key_env: DEEPSEEK_API_KEY             # 默认读 OPENAI_API_KEY
    temperature: 0.0

judge_providers:                # 评委（只服务评分，自身不进矩阵）
  - id: judge
    type: openai
    model: gpt-4o-mini          # 评委建议用便宜快的模型

datasets:
  - path: dataset.jsonl

defaults:
  assert:
    - type: latency
      threshold: 8000           # 毫秒，按网络情况放宽

gate:
  min_pass_rate: 0.8
```

`my-eval/dataset.jsonl`（每行一个 JSON 用例）：

```json
{"id": "q1", "prompt": "1+1等于几？只回答数字", "expected": "2", "assert": [{"type": "equals", "value": "2"}]}
{"id": "q2", "prompt": "中国的首都是哪里？", "expected": "北京", "assert": [{"type": "icontains", "value": "北京"}, {"type": "llm-correctness"}]}
```

跑起来：

```bash
evalhive run my-eval/config.yaml --gate -v --save
```

说明：
- 费用按公开牌价估算（内置 gpt/claude/deepseek/qwen 常见型号，未知型号用保守默认），显示在 cost 列
- 响应缓存写在 `.evalhive/cache/`：同 prompt 重复跑不重复计费；`--no-cache` 强制真调
- 评委指标（`llm-*`、`faithfulness`、`answer-relevance`）每次会多一次评委模型调用，成本计入 total cost

## 6. 配置详解

### 6.1 指标（assert 的 type）速查

| 类型 | 用途 | 关键参数 |
|---|---|---|
| `equals` | 归一化后精确相等 | `value` |
| `icontains` | 包含（大小写不敏感，可传数组按比例计分） | `value` |
| `regex` | 正则命中 | `value` |
| `json-valid` | 输出是合法 JSON（容忍 markdown 代码块） | — |
| `json-schema` | 按 JSON Schema 校验 | `value` = schema |
| `similarity` | 词级 Jaccard 相似度 | `value`、`threshold`（默认 0.8） |
| `latency` | 延迟阈值 | `threshold`（毫秒） |
| `cost` | 单次调用成本阈值 | `threshold`（美元） |
| `llm-correctness` | 评委判断答案与 expected/context 是否相符 | 可加 `rubric` |
| `llm-relevance` | 评委判断是否切题 | 同上 |
| `llm-toxicity` | 有害性（0 清洁~5 严重，≤1 过） | `threshold` 反向 |
| `faithfulness` | 答案是否被 context 支撑（RAG 防幻觉） | `threshold`（默认 0.8），要求 case 有 `context` |
| `answer-relevance` | 答案是否完整回应问题 | 同上 |

断言写在两个地方，**case 级覆盖同级默认**（按 type 去重合并）：
配置里 `defaults.assert`（全部用例生效）+ 数据集行内 `assert`（仅该用例）。

### 6.2 provider 字段

| 字段 | 说明 |
|---|---|
| `id` | 唯一标识；`providers` 与 `judge_providers` 命名空间分离，不允许重名 |
| `type` | `openai`（任何兼容端点）或 `mock`（离线录制回放） |
| `model` / `base_url` / `api_key_env` / `temperature` / `max_tokens` / `timeout_s` | 常规调用参数 |
| `prompt_template` | 提示词模板，可用 `{prompt}` `{context}` 和用例 `vars` 里的任意变量 |
| `responses_file`（mock） | JSONL 录制：`{"case_id":"c1","response":"...","latency_ms":120}` 或 `{"match":"子串","response":"..."}`；命中顺序 case_id → match → `default_response` |

### 6.3 门禁（gate）

```yaml
gate:
  min_pass_rate: 0.8      # 绝对线：通过率低于它即失败
  max_regression: 0.05    # 相对线：比基线掉超过 5% 即失败（配合 --gate 基线）
```

## 7. 回归基线工作流（核心卖点）

```bash
evalhive run my-eval/config.yaml --save --label "v1 基线"   # 1) 跑并存历史
evalhive history                                            # 2) 查看历史，找到 run id
evalhive set-baseline 1                                     # 3) 钉基线
evalhive run my-eval/config.yaml --gate                     # 4) 之后每次跑都自动对比基线
```

第 4 步输出示例（质量退化时）：

```
── gate FAILED ✗
  ! pass_rate 60.00% below min_pass_rate 80.00%
  ! regression 20.00% exceeds max_regression ...
  ! newly failed cases: support-bot/c2
  drift -20.00% (95% CI [-60.00%, +0.00%], not significant)
```

CI 区间不跨 0 才算「统计显著」——防止在小样本上追噪声。也可以对两份 JSON 事后对比：
`evalhive diff out/run_v1.json out/run_v2.json`。

## 8. CI 集成（GitHub Actions）

把 [`templates/github-actions/eval-gate.yml`](../templates/github-actions/eval-gate.yml) 拷进自己仓库的
`.github/workflows/`：每次 PR 自动跑评测 → 失败则挂检查 → 并把 Markdown 摘要评论到 PR。
本仓库自己的 CI 就是用这个模式验证门禁的（健康示例必须过、退化示例必须拦）。

## 9. HTTP API（二次开发）

`evalhive serve` 后：

```bash
curl http://127.0.0.1:8000/api/runs                      # 历史列表
curl -X POST http://127.0.0.1:8000/api/runs \
     -H "Content-Type: application/json" \
     -d '{"config_path": "examples/rag-chat/config.yaml"}'   # 后台触发，返回 run_id
curl http://127.0.0.1:8000/api/runs/1                    # 详情（逐用例+指标）
curl http://127.0.0.1:8000/api/runs/1/report.html        # HTML 报告
curl -X POST http://127.0.0.1:8000/api/baseline \
     -H "Content-Type: application/json" -d '{"run_id": 1}'  # 设基线
curl "http://127.0.0.1:8000/api/diff?baseline=1&current=2"   # 两次对比
curl http://127.0.0.1:8000/api/trend                     # 趋势数据（看板同款）
```

交互式文档：`http://127.0.0.1:8000/docs`（FastAPI 自带 Swagger）。

## 10. Docker 方式

```bash
docker compose -f docker/docker-compose.yml up
# 打开 http://localhost:8000 ；run 历史/缓存在命名卷 history 中持久化
```

## 11. 目录与数据位置

```
examples/            三个离线示例（配置+数据集+mock 录制）
src/evalhive/
  cli/               命令行（run/diff/history/set-baseline/serve）
  core/              runner、指标、provider、对比统计、缓存
  api/               FastAPI 服务
  report/            JUnit/Markdown/HTML 报告
  storage/           SQLite 历史
web/static/          看板前端（ECharts 已本地化，离线可用）
templates/github-actions/   CI 工作流模板
```

运行时数据：`.evalhive/cache/`（响应缓存）、`.evalhive/history.sqlite3`（run 历史，
可用环境变量 `EVALHIVE_DB` 改路径）。想完全重跑：删除 `.evalhive/` 即可。

## 12. FAQ

- **Q：`--gate` 退出码 1 但我看不出哪挂了？** 加 `-v`，会列出每个失败用例和指标明细（含评委原始判词）。
- **Q：改了 mock 录制文件但结果没变？** 缓存按「fixture 内容指纹 + prompt」键控，改文件后自动失效；确认没传 `--no-cache` 以外的旧进程。
- **Q：评委输出乱七八糟导致指标挂？** 这是有意设计——解析失败记 fail 并保留原始判词，保证不静默放水；换更强的评委模型或收窄 rubric。
- **Q：能评中文用例吗？** 能，全链路 UTF-8，示例本身就有中文场景。
- **Q：并发怎么控？** `--concurrency N`（默认 5），主调用与评委调用各自限流，避免触发厂商 rate limit。
