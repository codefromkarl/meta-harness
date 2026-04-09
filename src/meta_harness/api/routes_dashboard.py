from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def _json_script(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def _load_benchmark_cards(reports_root: Path, *, limit: int = 8) -> dict[str, object]:
    items: list[dict[str, str]] = []
    benchmark_root = reports_root / "benchmarks"
    suite_root = reports_root / "benchmark-suites"

    if benchmark_root.exists():
        for path in sorted(benchmark_root.glob("*.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": str(payload.get("experiment", path.stem)),
                    "kind": "benchmark",
                    "title": str(payload.get("experiment", path.stem)),
                    "subtitle": f"best={payload.get('best_variant', 'unknown')}",
                    "meta": str(payload.get("artifact_path", path.name)),
                }
            )
    if suite_root.exists():
        for path in sorted(suite_root.glob("*.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": str(payload.get("suite", path.stem)),
                    "kind": "benchmark-suite",
                    "title": str(payload.get("suite", path.stem)),
                    "subtitle": f"results={len(payload.get('results', []))}",
                    "meta": str(payload.get("artifact_path", path.name)),
                }
            )

    return {"items": items[:limit]}


def _render_dashboard_html(config: dict[str, str]) -> str:
    config_json = _json_script(config)
    return dedent(
        f"""\
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Meta-Harness Dashboard</title>
            <style>
              :root {{
                --bg: #f4efe6;
                --bg-alt: #efe3d1;
                --panel: rgba(255, 251, 244, 0.86);
                --panel-strong: #fff9f1;
                --border: rgba(72, 53, 34, 0.14);
                --text: #2c241b;
                --muted: #6b5a49;
                --accent: #0d6b63;
                --accent-soft: rgba(13, 107, 99, 0.12);
                --danger: #a9482f;
                --shadow: 0 18px 60px rgba(86, 66, 44, 0.12);
                --radius-lg: 24px;
                --radius-md: 16px;
                --radius-sm: 12px;
              }}

              * {{
                box-sizing: border-box;
              }}

              html, body {{
                margin: 0;
                min-height: 100%;
                background:
                  radial-gradient(circle at top left, rgba(13, 107, 99, 0.14), transparent 30%),
                  radial-gradient(circle at top right, rgba(169, 72, 47, 0.12), transparent 34%),
                  linear-gradient(180deg, var(--bg), #f7f3ed 46%, var(--bg-alt));
                color: var(--text);
                font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
              }}

              body {{
                padding: 32px 20px 56px;
              }}

              .shell {{
                max-width: 1440px;
                margin: 0 auto;
              }}

              .hero {{
                display: grid;
                grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.9fr);
                gap: 20px;
                margin-bottom: 20px;
              }}

              .hero-card,
              .panel {{
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                background: var(--panel);
                backdrop-filter: blur(16px);
                box-shadow: var(--shadow);
              }}

              .hero-card {{
                padding: 28px;
              }}

              .eyebrow {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 999px;
                background: var(--accent-soft);
                color: var(--accent);
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
              }}

              h1,
              h2,
              h3 {{
                margin: 0;
                font-family: "Fraunces", "Iowan Old Style", "Georgia", serif;
                font-weight: 700;
                letter-spacing: -0.02em;
              }}

              h1 {{
                margin-top: 16px;
                font-size: clamp(2.3rem, 4vw, 4rem);
                line-height: 0.96;
              }}

              .hero p {{
                max-width: 60ch;
                margin: 16px 0 0;
                color: var(--muted);
                font-size: 1rem;
                line-height: 1.7;
              }}

              .stats {{
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
              }}

              .stat {{
                padding: 18px;
                border-radius: var(--radius-md);
                border: 1px solid var(--border);
                background: var(--panel-strong);
              }}

              .stat-label {{
                font-size: 0.78rem;
                color: var(--muted);
                text-transform: uppercase;
                letter-spacing: 0.08em;
              }}

              .stat-value {{
                margin-top: 8px;
                font-size: 2rem;
                font-weight: 700;
              }}

              .toolbar {{
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 12px;
                padding: 20px;
                margin-bottom: 20px;
              }}

              label {{
                display: flex;
                flex-direction: column;
                gap: 8px;
                font-size: 0.86rem;
                color: var(--muted);
              }}

              input {{
                width: 100%;
                min-height: 46px;
                padding: 12px 14px;
                border: 1px solid rgba(72, 53, 34, 0.18);
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.85);
                color: var(--text);
                font: inherit;
              }}

              input:focus,
              button:focus {{
                outline: 2px solid rgba(13, 107, 99, 0.32);
                outline-offset: 2px;
              }}

              .toolbar-actions {{
                grid-column: 1 / -1;
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 12px;
              }}

              .toolbar-note {{
                color: var(--muted);
                font-size: 0.92rem;
              }}

              button {{
                min-width: 136px;
                min-height: 46px;
                padding: 12px 18px;
                border: 0;
                border-radius: 999px;
                background: linear-gradient(135deg, #0d6b63, #167b71);
                color: #fff;
                font: inherit;
                font-weight: 700;
                cursor: pointer;
              }}

              .grid {{
                display: grid;
                grid-template-columns: repeat(12, minmax(0, 1fr));
                gap: 20px;
              }}

              .panel {{
                grid-column: span 6;
                padding: 22px;
              }}

              .panel.wide {{
                grid-column: span 12;
              }}

              .panel-header {{
                display: flex;
                align-items: baseline;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 16px;
              }}

              .panel-header p {{
                margin: 0;
                color: var(--muted);
                font-size: 0.92rem;
              }}

              .status {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                min-height: 28px;
                padding: 6px 10px;
                border-radius: 999px;
                background: rgba(44, 36, 27, 0.06);
                color: var(--muted);
                font-size: 0.78rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
              }}

              .status.error {{
                color: var(--danger);
                background: rgba(169, 72, 47, 0.12);
              }}

              .list {{
                display: grid;
                gap: 10px;
              }}

              .item {{
                padding: 14px 16px;
                border: 1px solid var(--border);
                border-radius: var(--radius-sm);
                background: rgba(255, 255, 255, 0.62);
              }}

              .item-title {{
                font-weight: 700;
              }}

              .item-subtitle,
              .item-meta {{
                margin-top: 4px;
                color: var(--muted);
                font-size: 0.92rem;
                line-height: 1.55;
              }}

              .item-meta {{
                font-family: "IBM Plex Mono", "SFMono-Regular", monospace;
                font-size: 0.8rem;
              }}

              .empty {{
                padding: 18px;
                border-radius: var(--radius-sm);
                border: 1px dashed rgba(72, 53, 34, 0.18);
                color: var(--muted);
                background: rgba(255, 255, 255, 0.45);
              }}

              .footer-note {{
                margin-top: 20px;
                color: var(--muted);
                font-size: 0.9rem;
              }}

              @media (max-width: 1080px) {{
                .hero,
                .toolbar {{
                  grid-template-columns: 1fr;
                }}

                .panel {{
                  grid-column: span 12;
                }}
              }}

              @media (prefers-reduced-motion: no-preference) {{
                .hero-card,
                .panel {{
                  animation: rise 240ms ease-out;
                }}
              }}

              @keyframes rise {{
                from {{
                  opacity: 0;
                  transform: translateY(10px);
                }}

                to {{
                  opacity: 1;
                  transform: translateY(0);
                }}
              }}
            </style>
          </head>
          <body>
            <div class="shell">
              <section class="hero">
                <article class="hero-card">
                  <div class="eyebrow">Meta-Harness Dashboard</div>
                  <h1>Artifact-first control room for runs, lineage, and gates.</h1>
                  <p>
                    这是一版内嵌在 API 里的 dashboard shell。它直接消费现有 HTTP API，
                    不引入额外前端构建链，优先把 Runs、Candidates、Datasets、Gate Policies、
                    Jobs 和 Proposals 的产品面补齐。
                  </p>
                </article>
                <aside class="hero-card">
                  <div class="stats">
                    <div class="stat">
                      <div class="stat-label">Runs</div>
                      <div class="stat-value" data-stat="runs">-</div>
                    </div>
                    <div class="stat">
                      <div class="stat-label">Jobs</div>
                      <div class="stat-value" data-stat="jobs">-</div>
                    </div>
                    <div class="stat">
                      <div class="stat-label">Datasets</div>
                      <div class="stat-value" data-stat="datasets">-</div>
                    </div>
                    <div class="stat">
                      <div class="stat-label">Policies</div>
                      <div class="stat-value" data-stat="policies">-</div>
                    </div>
                  </div>
                </aside>
              </section>

              <form class="panel toolbar" id="dashboard-config-form">
                <label>
                  `runs_root`
                  <input id="runs-root" name="runs_root" type="text">
                </label>
                <label>
                  `reports_root`
                  <input id="reports-root" name="reports_root" type="text">
                </label>
                <label>
                  `datasets_root`
                  <input id="datasets-root" name="datasets_root" type="text">
                </label>
                <label>
                  `candidates_root`
                  <input id="candidates-root" name="candidates_root" type="text">
                </label>
                <label>
                  `config_root`
                  <input id="config-root" name="config_root" type="text">
                </label>
                <div class="toolbar-actions">
                  <div class="toolbar-note">
                    资源根只影响页面发起的 API 查询，不会改写服务端状态。
                  </div>
                  <button type="submit">Refresh Dashboard</button>
                </div>
              </form>

              <section class="grid">
                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Runs</h2>
                      <p>最近运行摘要、profile、project、candidate 绑定。</p>
                    </div>
                    <div class="status" data-status="runs">Loading</div>
                  </div>
                  <div class="list" id="runs-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Benchmarks</h2>
                      <p>最近 benchmark 与 suite 报告的入口。</p>
                    </div>
                    <div class="status" data-status="benchmarks">Loading</div>
                  </div>
                  <div class="list" id="benchmarks-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Current Candidates</h2>
                      <p>实验当前推荐 candidate 视图和 lineage 入口。</p>
                    </div>
                    <div class="status" data-status="candidates">Loading</div>
                  </div>
                  <div class="list" id="candidates-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Datasets</h2>
                      <p>可用 dataset 版本和 case 集管理入口。</p>
                    </div>
                    <div class="status" data-status="datasets">Loading</div>
                  </div>
                  <div class="list" id="datasets-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Gate Policies</h2>
                      <p>策略对象清单，可作为后续审批与治理 UI 的基础。</p>
                    </div>
                    <div class="status" data-status="policies">Loading</div>
                  </div>
                  <div class="list" id="policies-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Trace Exports</h2>
                      <p>最近 trace export job 与导出 artifact 入口。</p>
                    </div>
                    <div class="status" data-status="trace-exports">Loading</div>
                  </div>
                  <div class="list" id="trace-exports-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Jobs</h2>
                      <p>异步任务状态、产物引用与结果预览入口。</p>
                    </div>
                    <div class="status" data-status="jobs">Loading</div>
                  </div>
                  <div class="list" id="jobs-list"></div>
                </article>

                <article class="panel">
                  <div class="panel-header">
                    <div>
                      <h2>Proposals</h2>
                      <p>proposal 生命周期入口，便于与 optimize 主线联动。</p>
                    </div>
                    <div class="status" data-status="proposals">Loading</div>
                  </div>
                  <div class="list" id="proposals-list"></div>
                </article>

                <article class="panel wide">
                  <div class="panel-header">
                    <div>
                      <h2>Notes</h2>
                      <p>这一版优先补产品壳，保留更细粒度 lineage 卡片和 trace/export drill-down 的后续演进空间。</p>
                    </div>
                  </div>
                  <div class="empty">
                    当前 dashboard 直接使用已有 API surface。
                    如果要继续做 `6.4 UI / dashboard` 收口，下一步更合理的是补 benchmark 列表面、
                    current candidate 的更细粒度 lineage 卡片，以及 trace / export 的更深层 drill-down 视图。
                  </div>
                </article>
              </section>

              <p class="footer-note">
                所有数据仍以本地 artifact 为真相源；页面只是投影层。
              </p>
            </div>

            <script>
              window.META_HARNESS_DASHBOARD_CONFIG = {config_json};
              window.META_HARNESS_DASHBOARD_ENDPOINTS = {{
                "runs": "/runs",
                "benchmarks": "/dashboard/benchmarks",
                "candidatesCurrent": "/candidates/current",
                "datasets": "/datasets",
                "gatePolicies": "/gate-policies",
                "jobs": "/jobs",
                "proposals": "/proposals"
              }};

              const config = window.META_HARNESS_DASHBOARD_CONFIG;
              const endpoints = window.META_HARNESS_DASHBOARD_ENDPOINTS;

              const sections = {{
                runs: {{
                  endpoint: endpoints.runs,
                  params: () => ({{ runs_root: config.runsRoot, limit: "8" }}),
                  targetId: "runs-list",
                  statKey: "runs",
                  render: payload => renderItems(payload.items, item => {{
                    const profile = item.profile || "unknown-profile";
                    const project = item.project || "unknown-project";
                    const candidateId = item.candidate_id || "none";
                    return renderCard(
                      item.run_id || "run",
                      `${{profile}} / ${{project}}`,
                      `candidate=${{candidateId}}`
                    );
                  }})
                }},
                benchmarks: {{
                  endpoint: endpoints.benchmarks,
                  params: () => ({{ reports_root: config.reportsRoot, limit: "8" }}),
                  targetId: "benchmarks-list",
                  statKey: "benchmarks",
                  render: payload => renderItems(payload.items, item =>
                    renderCard(
                      item.title || item.id || "benchmark",
                      item.subtitle || item.kind || "",
                      item.meta || ""
                    )
                  )
                }},
                candidates: {{
                  endpoint: endpoints.candidatesCurrent,
                  params: () => ({{
                    candidates_root: config.candidatesRoot,
                    runs_root: config.runsRoot
                  }}),
                  targetId: "candidates-list",
                  render: payload => {{
                    const current = payload.current_recommended_candidate_by_experiment || {{}};
                    const entries = Object.entries(current).map(([experiment, record]) =>
                      renderCard(
                        experiment,
                        record.candidate_id || "no candidate",
                        formatLineageMeta(record.lineage)
                      )
                    );
                    return entries.length ? entries.join("") : renderEmpty("当前没有推荐 candidate。");
                  }}
                }},
                datasets: {{
                  endpoint: endpoints.datasets,
                  params: () => ({{ datasets_root: config.datasetsRoot, limit: "8" }}),
                  targetId: "datasets-list",
                  statKey: "datasets",
                  render: payload => renderItems(payload.items, item => {{
                    if (typeof item === "string") {{
                      return renderCard(item, "dataset", "");
                    }}
                    return renderCard(
                      item.dataset_id || item.version || "dataset",
                      item.version ? `version=${{item.version}}` : "dataset",
                      item.split ? `split=${{item.split}}` : ""
                    );
                  }})
                }},
                policies: {{
                  endpoint: endpoints.gatePolicies,
                  params: () => ({{ config_root: config.configRoot, limit: "8" }}),
                  targetId: "policies-list",
                  statKey: "policies",
                  render: payload => renderItems(payload.items, item => {{
                    if (typeof item === "string") {{
                      return renderCard(item, "gate policy", "");
                    }}
                    return renderCard(item.policy_id || "policy", item.description || "", "");
                  }})
                }},
                jobs: {{
                  endpoint: endpoints.jobs,
                  params: () => ({{ reports_root: config.reportsRoot, limit: "8" }}),
                  targetId: "jobs-list",
                  statKey: "jobs",
                  render: payload => renderItems(payload.items, item => {{
                    return renderCard(
                      item.job_id || "job",
                      item.status || item.job_type || "unknown",
                      item.result_ref ? JSON.stringify(item.result_ref) : ""
                    );
                  }})
                }},
                "trace-exports": {{
                  endpoint: endpoints.jobs,
                  params: () => ({{
                    reports_root: config.reportsRoot,
                    job_type: "run.export_trace",
                    limit: "8"
                  }}),
                  targetId: "trace-exports-list",
                  render: payload => renderItems(payload.items, item => {{
                    const preview = item.result_preview || item.result_ref || {{}};
                    const meta = preview.path || preview.target_id || "";
                    return renderCard(
                      item.job_id || "trace-export",
                      item.status || "unknown",
                      meta
                    );
                  }})
                }},
                proposals: {{
                  endpoint: endpoints.proposals,
                  params: () => ({{ proposals_root: config.proposalsRoot, limit: "8" }}),
                  targetId: "proposals-list",
                  render: payload => renderItems(payload.items, item => {{
                    return renderCard(
                      item.proposal_id || "proposal",
                      item.status || item.proposer_kind || "",
                      item.strategy || ""
                    );
                  }})
                }}
              }};

              function renderCard(title, subtitle, meta) {{
                return `
                  <article class="item">
                    <div class="item-title">${{escapeHtml(title)}}</div>
                    <div class="item-subtitle">${{escapeHtml(subtitle || "")}}</div>
                    <div class="item-meta">${{escapeHtml(meta || "")}}</div>
                  </article>
                `;
              }}

              function formatLineageMeta(lineage) {{
                if (!lineage || typeof lineage !== "object") {{
                  return "lineage unavailable";
                }}
                const parts = [];
                if (lineage.proposal_id) {{
                  parts.push(`proposal=${{lineage.proposal_id}}`);
                }}
                if (lineage.iteration_id) {{
                  parts.push(`iteration=${{lineage.iteration_id}}`);
                }}
                if (Array.isArray(lineage.source_run_ids) && lineage.source_run_ids.length) {{
                  parts.push(`runs=${{lineage.source_run_ids.join(",")}}`);
                }}
                if (Array.isArray(lineage.source_artifacts) && lineage.source_artifacts.length) {{
                  parts.push(`artifacts=${{lineage.source_artifacts.length}}`);
                }}
                return parts.length ? parts.join(" | ") : "lineage unavailable";
              }}

              function renderEmpty(text) {{
                return `<div class="empty">${{escapeHtml(text)}}</div>`;
              }}

              function renderItems(items, renderer) {{
                if (!Array.isArray(items) || items.length === 0) {{
                  return renderEmpty("暂无数据。");
                }}
                return items.map(renderer).join("");
              }}

              function escapeHtml(value) {{
                return String(value)
                  .replaceAll("&", "&amp;")
                  .replaceAll("<", "&lt;")
                  .replaceAll(">", "&gt;")
                  .replaceAll('"', "&quot;")
                  .replaceAll("'", "&#39;");
              }}

              function setStatus(key, text, isError = false) {{
                const node = document.querySelector(`[data-status="${{key}}"]`);
                if (!node) {{
                  return;
                }}
                node.textContent = text;
                node.classList.toggle("error", isError);
              }}

              function setStat(key, value) {{
                const node = document.querySelector(`[data-stat="${{key}}"]`);
                if (node) {{
                  node.textContent = String(value);
                }}
              }}

              function buildUrl(path, params) {{
                const url = new URL(path, window.location.origin);
                Object.entries(params).forEach(([name, value]) => {{
                  if (value !== null && value !== undefined && value !== "") {{
                    url.searchParams.set(name, value);
                  }}
                }});
                return url.toString();
              }}

              async function loadSection(key, definition) {{
                const target = document.getElementById(definition.targetId);
                setStatus(key, "Loading");
                try {{
                  const response = await fetch(buildUrl(definition.endpoint, definition.params()), {{
                    headers: {{ Accept: "application/json" }}
                  }});
                  if (!response.ok) {{
                    throw new Error(`HTTP ${{response.status}}`);
                  }}
                  const payload = await response.json();
                  target.innerHTML = definition.render(payload);
                  const collectionSize = Array.isArray(payload.items)
                    ? payload.items.length
                    : Object.keys(payload.current_recommended_candidate_by_experiment || {{}}).length;
                  if (definition.statKey) {{
                    setStat(definition.statKey, collectionSize);
                  }}
                  setStatus(key, "Ready");
                }} catch (error) {{
                  target.innerHTML = renderEmpty(`加载失败: ${{error.message}}`);
                  if (definition.statKey) {{
                    setStat(definition.statKey, "!");
                  }}
                  setStatus(key, "Error", true);
                }}
              }}

              async function refreshDashboard() {{
                await Promise.all(
                  Object.entries(sections).map(([key, definition]) => loadSection(key, definition))
                );
              }}

              function syncFormFromConfig() {{
                document.getElementById("runs-root").value = config.runsRoot;
                document.getElementById("reports-root").value = config.reportsRoot;
                document.getElementById("datasets-root").value = config.datasetsRoot;
                document.getElementById("candidates-root").value = config.candidatesRoot;
                document.getElementById("config-root").value = config.configRoot;
              }}

              function updateConfigFromForm(form) {{
                const formData = new FormData(form);
                config.runsRoot = String(formData.get("runs_root") || "");
                config.reportsRoot = String(formData.get("reports_root") || "");
                config.datasetsRoot = String(formData.get("datasets_root") || "");
                config.candidatesRoot = String(formData.get("candidates_root") || "");
                config.configRoot = String(formData.get("config_root") || "");
                const url = new URL(window.location.href);
                url.searchParams.set("runs_root", config.runsRoot);
                url.searchParams.set("reports_root", config.reportsRoot);
                url.searchParams.set("datasets_root", config.datasetsRoot);
                url.searchParams.set("candidates_root", config.candidatesRoot);
                url.searchParams.set("config_root", config.configRoot);
                window.history.replaceState({{}}, "", url);
              }}

              document
                .getElementById("dashboard-config-form")
                .addEventListener("submit", event => {{
                  event.preventDefault();
                  updateConfigFromForm(event.currentTarget);
                  refreshDashboard();
                }});

              syncFormFromConfig();
              refreshDashboard();
            </script>
          </body>
        </html>
        """
    )


def register_dashboard_routes(app: FastAPI) -> None:
    @app.get("/dashboard/benchmarks")
    def dashboard_benchmarks(
        reports_root: str = "reports",
        limit: int = 8,
    ) -> dict[str, object]:
        return _load_benchmark_cards(Path(reports_root), limit=limit)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(
        config_root: str = "configs",
        runs_root: str = "runs",
        reports_root: str = "reports",
        datasets_root: str = "datasets",
        candidates_root: str = "candidates",
        proposals_root: str = "proposals",
    ) -> HTMLResponse:
        config = {
            "configRoot": config_root,
            "runsRoot": runs_root,
            "reportsRoot": reports_root,
            "datasetsRoot": datasets_root,
            "candidatesRoot": candidates_root,
            "proposalsRoot": proposals_root,
        }
        return HTMLResponse(_render_dashboard_html(config))
