/* EvalHive dashboard logic — talks to the FastAPI service, renders ECharts. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const fmtPct = (v) => (v * 100).toFixed(1) + "%";
const fmtTime = (iso) => iso ? iso.replace("T", " ").slice(0, 19) : "";

const trendChart = echarts.init($("#trend"));
const costChart = echarts.init($("#cost"));

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

function renderTrend(points) {
  trendChart.setOption({
    grid: { left: 48, right: 20, top: 30, bottom: 28 },
    tooltip: { trigger: "axis", valueFormatter: (v) => v + "%" },
    legend: { data: ["pass rate %"], top: 0 },
    xAxis: { type: "category", data: points.map((p) => "#" + p.id) },
    yAxis: { type: "value", max: 100, axisLabel: { formatter: "{value}%" } },
    series: [{
      name: "pass rate %", type: "line", smooth: true,
      data: points.map((p) => +(p.pass_rate * 100).toFixed(2)),
      label: { show: points.length <= 15, formatter: "{c}%" },
      markLine: points.some((p) => p.is_baseline) ? {
        symbol: "none", data: [{
          xAxis: "#" + points.find((p) => p.is_baseline).id,
          label: { formatter: "baseline", position: "insideEndTop" },
        }],
      } : undefined,
      lineStyle: { width: 2.5 },
      areaStyle: { opacity: 0.08 },
    }],
  });
}

function renderCost(points) {
  costChart.setOption({
    grid: { left: 48, right: 48, top: 30, bottom: 28 },
    legend: { top: 0 },
    xAxis: { type: "category", data: points.map((p) => "#" + p.id) },
    yAxis: [
      { type: "value", name: "ms", axisLabel: { formatter: "{value}" } },
      { type: "value", name: "USD", position: "right" },
    ],
    series: [
      { name: "avg latency", type: "bar", data: points.map((p) => p.avg_latency_ms) },
      { name: "cost", type: "line", yAxisIndex: 1, data: points.map((p) => p.cost_usd), smooth: true },
    ],
  });
}

function renderRuns(runs) {
  const tb = $("#runs tbody");
  tb.innerHTML = "";
  for (const r of runs) {
    const tr = document.createElement("tr");
    const rateColor = r.pass_rate >= 0.999 ? "var(--ok)" : r.pass_rate >= 0.8 ? "var(--warn)" : "var(--bad)";
    tr.innerHTML = `
      <td>#${r.id}</td>
      <td class="label">${escapeHtml(r.label)}</td>
      <td><code>${r.config_hash || "—"}</code></td>
      <td>${fmtTime(r.created_at)}</td>
      <td>${r.n_passed}/${r.n_cases}</td>
      <td class="num"><b style="color:${rateColor}">${fmtPct(r.pass_rate)}</b></td>
      <td>${r.is_baseline ? "★ baseline" : ""}</td>
      <td class="actions">
        <button class="ghost" data-act="detail" data-id="${r.id}">view</button>
        <button class="ghost" data-act="baseline" data-id="${r.id}" ${r.is_baseline ? "disabled" : ""}>set baseline</button>
      </td>`;
    tb.appendChild(tr);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function openDetail(id) {
  const run = await api(`/api/runs/${id}`);
  $("#detail-title").textContent = `Run #${run.id} — ${run.label}`;
  $("#detail-html").href = `/api/runs/${id}/report.html`;
  const rows = Object.values(run.summaries).map((s) =>
    `<tr><td>${s.provider_id}</td><td class="num">${s.passed}/${s.total}</td>
     <td class="num">${fmtPct(s.pass_rate)}</td><td class="num">${s.avg_latency_ms.toFixed(0)}ms</td>
     <td class="num">$${s.total_cost_usd.toFixed(4)}</td></tr>`).join("");
  const cases = run.results.map((e) => {
    const m = e.error ? `<span class="bad">ERROR ${escapeHtml(e.error.slice(0, 80))}</span>`
      : e.metrics.map((x) => `${x.passed ? "✓" : '<span class="bad">✗</span>'} ${x.metric}`).join(" ");
    return `<tr><td><code>${e.provider_id}${e.prompt_id && e.prompt_id !== "default" ? "/" + e.prompt_id : ""}/${e.case_id}</code></td>
      <td>${e.passed ? '<span class="ok">PASS</span>' : '<span class="bad">FAIL</span>'}</td>
      <td class="metrics">${m}</td></tr>`;
  }).join("");
  $("#detail-body").innerHTML = `
    <table><thead><tr><th>provider</th><th class="num">pass</th><th class="num">rate</th>
      <th class="num">latency</th><th class="num">cost</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <h4>cases</h4>
    <table><thead><tr><th>case</th><th>result</th><th>metrics</th></tr></thead>
      <tbody>${cases}</tbody></table>`;
  $("#detail-modal").classList.remove("hidden");
}

async function refresh() {
  const [runs, trend] = await Promise.all([api("/api/runs"), api("/api/trend")]);
  renderRuns(runs);
  renderTrend(trend);
  renderCost(trend);
  const running = runs.filter((r) => r.status === "running").length;
  $("#status-line").textContent =
    `${runs.length} runs · ${running ? `${running} running…` : "idle"} · auto-refresh every 4s while running`;
  if (running) setTimeout(refresh, 4000);
}

$("#runs").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.act === "detail") openDetail(id).catch((e) => alert(e.message));
  if (btn.dataset.act === "baseline") {
    await api("/api/baseline", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: +id }) });
    refresh();
  }
});

$("#detail-close").onclick = () => $("#detail-modal").classList.add("hidden");
$("#refresh").onclick = refresh;

$("#run-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cfg = $("#run-config").value;
  $("#status-line").textContent = `triggering ${cfg} …`;
  try {
    await api("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config_path: cfg }) });
    setTimeout(refresh, 1200);
  } catch (e) {
    $("#status-line").textContent = "run failed: " + e.message;
  }
});

refresh().catch((e) => { $("#status-line").textContent = "API error: " + e.message; });
