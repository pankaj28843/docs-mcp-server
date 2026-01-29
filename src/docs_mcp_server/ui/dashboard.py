"""HTML dashboard renderer."""

from __future__ import annotations

import json


def render_dashboard_html(tenant_codenames: list[str]) -> str:
    tenants_json = json.dumps(sorted(tenant_codenames))
    template = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Docs MCP Dashboard</title>
    <script src=\"https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4\"></script>
    <script src=\"https://cdn.jsdelivr.net/npm/chart.js\"></script>
  </head>
  <body class=\"min-h-screen bg-slate-950 text-slate-100\">
    <div class=\"max-w-6xl mx-auto px-6 py-8\">
      <header class=\"flex flex-wrap items-center justify-between gap-4 mb-8\">
        <div>
          <p class=\"text-xs uppercase tracking-widest text-slate-400\">Docs MCP</p>
          <h1 class=\"text-3xl font-semibold\">Tenant Crawl Dashboard</h1>
          <p class=\"text-sm text-slate-400\">Last refresh: <span id=\"last-refresh\">—</span></p>
        </div>
        <div class=\"flex items-center gap-3\">
          <label class=\"text-xs uppercase tracking-widest text-slate-400\" for=\"tenant-select\">Focus</label>
          <select id=\"tenant-select\" class=\"bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm\"></select>
          <button id=\"refresh-now\" class=\"bg-cyan-500 hover:bg-cyan-400 text-slate-900 font-semibold px-4 py-2 rounded text-sm\">Refresh</button>
        </div>
      </header>

      <section class=\"grid grid-cols-1 md:grid-cols-4 gap-4 mb-8\">
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <p class=\"text-xs text-slate-400 uppercase\">Tenants</p>
          <p id=\"metric-tenants\" class=\"text-2xl font-semibold\">—</p>
        </div>
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <p class=\"text-xs text-slate-400 uppercase\">Tracked URLs</p>
          <p id=\"metric-urls\" class=\"text-2xl font-semibold\">—</p>
        </div>
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <p class=\"text-xs text-slate-400 uppercase\">Success</p>
          <p id=\"metric-success\" class=\"text-2xl font-semibold\">—</p>
        </div>
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <p class=\"text-xs text-slate-400 uppercase\">Failures</p>
          <p id=\"metric-fail\" class=\"text-2xl font-semibold\">—</p>
        </div>
      </section>

      <section class=\"grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8\">
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <h2 class=\"text-sm uppercase tracking-widest text-slate-400 mb-3\">Overall Status</h2>
          <canvas id=\"summaryChart\" height=\"140\"></canvas>
        </div>
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <h2 class=\"text-sm uppercase tracking-widest text-slate-400 mb-3\">Queue Depth by Tenant</h2>
          <canvas id=\"queueChart\" height=\"140\"></canvas>
        </div>
      </section>

      <section class=\"grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8\">
        <div class=\"lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <h2 class=\"text-sm uppercase tracking-widest text-slate-400 mb-3\">Focused Tenant</h2>
          <div class=\"grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4\">
            <div>
              <p class=\"text-xs text-slate-400 uppercase\">Queue</p>
              <p id=\"tenant-queue\" class=\"text-xl font-semibold\">—</p>
            </div>
            <div>
              <p class=\"text-xs text-slate-400 uppercase\">Success</p>
              <p id=\"tenant-success\" class=\"text-xl font-semibold\">—</p>
            </div>
            <div>
              <p class=\"text-xs text-slate-400 uppercase\">Failures</p>
              <p id=\"tenant-fail\" class=\"text-xl font-semibold\">—</p>
            </div>
          </div>
          <canvas id=\"tenantChart\" height=\"160\"></canvas>
        </div>
        <div class=\"bg-slate-900 border border-slate-800 rounded-xl p-4\">
          <h2 class=\"text-sm uppercase tracking-widest text-slate-400 mb-3\">Tenants</h2>
          <div class=\"overflow-auto max-h-96\">
            <table class=\"w-full text-sm\">
              <thead class=\"text-xs uppercase text-slate-500\">
                <tr>
                  <th class=\"text-left pb-2\">Tenant</th>
                  <th class=\"text-right pb-2\">Queue</th>
                  <th class=\"text-right pb-2\">Success</th>
                  <th class=\"text-right pb-2\">Fail</th>
                </tr>
              </thead>
              <tbody id=\"tenant-rows\" class=\"divide-y divide-slate-800\"></tbody>
            </table>
          </div>
        </div>
      </section>

      <footer class=\"text-xs text-slate-500\">Powered by /tenants/status and /{{tenant}}/sync/status</footer>
    </div>

    <script>
      const TENANTS = __TENANTS_JSON__;
      const summaryUrl = "/tenants/status";
      const tenantUrl = (tenant) => `/${{tenant}}/sync/status`;

      const byId = (id) => document.getElementById(id);
      const fmt = (value) => (Number.isFinite(value) ? value.toLocaleString() : "—");
      const parseNumber = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0);

      const tenantSelect = byId("tenant-select");
      const tenantHistory = [];
      const maxHistory = 60;

      function setText(id, value) {
        byId(id).textContent = value;
      }

      function updateLastRefresh() {
        setText("last-refresh", new Date().toLocaleTimeString());
      }

      TENANTS.forEach((tenant) => {
        const option = document.createElement("option");
        option.value = tenant;
        option.textContent = tenant;
        tenantSelect.appendChild(option);
      });

      if (TENANTS.length > 0) {
        tenantSelect.value = TENANTS[0];
      }

      let summaryChart;
      let queueChart;
      let tenantChart;

      function initCharts() {
        const summaryCtx = byId("summaryChart").getContext("2d");
        summaryChart = new Chart(summaryCtx, {
          type: "doughnut",
          data: {
            labels: ["Success", "Pending", "Failed"],
            datasets: [
              {
                data: [0, 0, 0],
                backgroundColor: ["#22d3ee", "#f59e0b", "#f43f5e"],
                borderWidth: 0,
              },
            ],
          },
          options: {
            plugins: {
              legend: { labels: { color: "#cbd5f5" } },
            },
          },
        });

        const queueCtx = byId("queueChart").getContext("2d");
        queueChart = new Chart(queueCtx, {
          type: "bar",
          data: {
            labels: [],
            datasets: [{ label: "Queue", data: [], backgroundColor: "#38bdf8" }],
          },
          options: {
            indexAxis: "y",
            plugins: { legend: { labels: { color: "#cbd5f5" } } },
            scales: {
              x: { ticks: { color: "#94a3b8" } },
              y: { ticks: { color: "#94a3b8" } },
            },
          },
        });

        const tenantCtx = byId("tenantChart").getContext("2d");
        tenantChart = new Chart(tenantCtx, {
          type: "line",
          data: {
            labels: [],
            datasets: [
              {
                label: "Queue Depth",
                data: [],
                borderColor: "#22d3ee",
                tension: 0.25,
              },
            ],
          },
          options: {
            plugins: { legend: { labels: { color: "#cbd5f5" } } },
            scales: {
              x: { ticks: { color: "#94a3b8" } },
              y: { ticks: { color: "#94a3b8" } },
            },
          },
        });
      }

      async function fetchSummary() {
        try {
          const res = await fetch(summaryUrl, { cache: "no-store" });
          if (!res.ok) throw new Error(`Summary status ${res.status}`);
          const data = await res.json();
          updateSummary(data.tenants || []);
          updateLastRefresh();
        } catch (err) {
          console.warn("Failed to fetch summary", err);
        }
      }

      function updateSummary(tenants) {
        const totalTenants = tenants.length;
        let totalUrls = 0;
        let success = 0;
        let pending = 0;
        let failed = 0;

        const queueLabels = [];
        const queueValues = [];

        const rows = tenants
          .map((tenant) => {
            const stats = tenant.crawl?.stats || {};
            const queue = parseNumber(stats.queue_depth ?? stats.queueDepth ?? 0);
            const ok = parseNumber(stats.metadata_successful ?? 0);
            const pend = parseNumber(stats.metadata_pending ?? 0);
            const fail = parseNumber(stats.failed_url_count ?? 0);
            const total = parseNumber(stats.metadata_total_urls ?? 0);
            totalUrls += total;
            success += ok;
            pending += pend;
            failed += fail;

            queueLabels.push(tenant.tenant);
            queueValues.push(queue);

            return { tenant: tenant.tenant, queue, ok, fail };
          })
          .sort((a, b) => b.queue - a.queue);

        setText("metric-tenants", fmt(totalTenants));
        setText("metric-urls", fmt(totalUrls));
        setText("metric-success", fmt(success));
        setText("metric-fail", fmt(failed));

        summaryChart.data.datasets[0].data = [success, pending, failed];
        summaryChart.update();

        queueChart.data.labels = queueLabels;
        queueChart.data.datasets[0].data = queueValues;
        queueChart.update();

        const tbody = byId("tenant-rows");
        tbody.innerHTML = "";
        rows.forEach((row) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td class=\"py-2 text-slate-200\">${row.tenant}</td>
            <td class=\"py-2 text-right\">${fmt(row.queue)}</td>
            <td class=\"py-2 text-right text-cyan-300\">${fmt(row.ok)}</td>
            <td class=\"py-2 text-right text-rose-300\">${fmt(row.fail)}</td>
          `;
          tbody.appendChild(tr);
        });
      }

      async function fetchTenant() {
        const tenant = tenantSelect.value;
        if (!tenant) return;
        try {
          const res = await fetch(tenantUrl(tenant), { cache: "no-store" });
          if (!res.ok) throw new Error(`Tenant status ${res.status}`);
          const data = await res.json();
          updateTenant(data);
        } catch (err) {
          console.warn("Failed to fetch tenant", err);
        }
      }

      function updateTenant(payload) {
        const stats = payload.stats || {};
        const queue = parseNumber(stats.queue_depth ?? 0);
        const ok = parseNumber(stats.metadata_successful ?? 0);
        const fail = parseNumber(stats.failed_url_count ?? 0);

        setText("tenant-queue", fmt(queue));
        setText("tenant-success", fmt(ok));
        setText("tenant-fail", fmt(fail));

        tenantHistory.push({ t: new Date().toLocaleTimeString(), queue });
        if (tenantHistory.length > maxHistory) tenantHistory.shift();

        tenantChart.data.labels = tenantHistory.map((point) => point.t);
        tenantChart.data.datasets[0].data = tenantHistory.map((point) => point.queue);
        tenantChart.update();
      }

      tenantSelect.addEventListener("change", () => {
        tenantHistory.length = 0;
        fetchTenant();
      });

      byId("refresh-now").addEventListener("click", () => {
        fetchSummary();
        fetchTenant();
      });

      initCharts();
      fetchSummary();
      fetchTenant();
      setInterval(fetchSummary, 60000);
      setInterval(fetchTenant, 7000);
    </script>
  </body>
</html>"""
    return template.replace("__TENANTS_JSON__", tenants_json)
