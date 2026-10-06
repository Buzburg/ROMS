"""
Interactive Dark-Mode HTML Telemetry & Neural Memory Dashboard Generator for mojo-cortex.
"""

import os
import html
from .memory import HybridNeuralMemory
from .sieve import ContextSieve
from .symdex import PolyglotSymdex
from .rewind import WorkspaceTimeMachine
from .shield import ExecutionShield


def generate_dashboard(cortex_dir: str = ".cortex", output_path: str = "cortex_dashboard.html") -> str:
    mem_stats = HybridNeuralMemory(cortex_dir).stats()
    sieve_stats = ContextSieve(cortex_dir).stats()
    sym_stats = PolyglotSymdex(cortex_dir).stats()
    snaps = WorkspaceTimeMachine(cortex_dir).list_snapshots()
    shield_stats = ExecutionShield(cortex_dir).stats()

    entries = list(mem_stats.get("entries", {}).values())
    symbols = sym_stats.get("symbols", [])[:25]

    mem_rows = ""
    for e in entries:
        mem_rows += f"""
        <tr>
          <td><code>{html.escape(str(e.get('key', '')))}</code></td>
          <td>{html.escape(str(e.get('value', '')))}</td>
          <td><span class="badge">{html.escape(str(e.get('category', '')))}</span></td>
          <td>{e.get('surprise_at_write', 0.0):.4f}</td>
        </tr>"""
    if not mem_rows:
        mem_rows = '<tr><td colspan="4" class="empty">No associative memories recorded yet.</td></tr>'

    sym_rows = ""
    for s in symbols:
        sym_rows += f"""
        <tr>
          <td><strong>{html.escape(s.get('name', ''))}</strong></td>
          <td><span class="badge">{html.escape(s.get('kind', ''))}</span></td>
          <td><code>{html.escape(s.get('file', ''))}:{s.get('line', 0)}</code></td>
          <td><span class="badge lang">{html.escape(s.get('language', ''))}</span></td>
        </tr>"""
    if not sym_rows:
        sym_rows = '<tr><td colspan="4" class="empty">Run <code>cortex index</code> to populate codebase graph.</td></tr>'

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>mojo-cortex | Agent Prefrontal Cortex & Telemetry</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card: #131b2e;
      --border: #23304d;
      --accent: #38bdf8;
      --emerald: #34d399;
      --amber: #fbbf24;
      --rose: #fb7185;
      --text: #f1f5f9;
      --muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 2rem;
      line-height: 1.5;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{ font-size: 1.6rem; font-weight: 700; color: var(--accent); }}
    .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1.2rem;
      margin-bottom: 2rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
    }}
    .kpi-label {{ color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    .kpi-val {{ font-size: 1.9rem; font-weight: 700; margin-top: 0.4rem; color: var(--emerald); }}
    .kpi-val.accent {{ color: var(--accent); }}
    .kpi-val.amber {{ color: var(--amber); }}
    .kpi-val.rose {{ color: var(--rose); }}
    .section {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
    }}
    h2 {{ font-size: 1.15rem; margin-bottom: 1rem; color: var(--text); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ text-align: left; padding: 0.75rem; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 600; }}
    code {{ background: #090d16; padding: 0.2rem 0.4rem; border-radius: 4px; color: var(--accent); }}
    .badge {{
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      font-size: 0.75rem;
    }}
    .empty {{ color: var(--muted); text-align: center; padding: 1.5rem; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>🧠 mojo-cortex Telemetry & Neural Memory Explorer</h1>
      <p class="subtitle">Titans Test-Time Memory • Gated DeltaNet-2 • BitNet b1.58 Router • SnapKV Sieve • Pre-Simulation Shield</p>
    </div>
    <span class="badge">v1.0.0 Active</span>
  </header>

  <div class="grid">
    <div class="card">
      <div class="kpi-label">Context Tokens Saved</div>
      <div class="kpi-val">{sieve_stats.get('saved_tokens', 0):,}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Neural Memory Entries</div>
      <div class="kpi-val accent">{len(entries)}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Memory Norm ||M||_F</div>
      <div class="kpi-val amber">{mem_stats.get('frobenius_norm', 0.0):.3f}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Indexed Code Symbols</div>
      <div class="kpi-val accent">{sym_stats.get('total_symbols', 0):,}</div>
    </div>
    <div class="card">
      <div class="kpi-label">CoW Snapshots</div>
      <div class="kpi-val">{len(snaps)}</div>
    </div>
    <div class="card">
      <div class="kpi-label">Hazards Intercepted</div>
      <div class="kpi-val rose">{shield_stats.get('intercepts', 0)}</div>
    </div>
  </div>

  <div class="section">
    <h2>⚡ Titans + DeltaNet-2 Associative Memory Catalog</h2>
    <table>
      <thead>
        <tr><th>Key</th><th>Value</th><th>Category</th><th>Surprise Residual</th></tr>
      </thead>
      <tbody>{mem_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>🔍 Polyglot Codebase Symbol Graph (Top 25)</h2>
    <table>
      <thead>
        <tr><th>Symbol</th><th>Kind</th><th>Location</th><th>Language</th></tr>
      </thead>
      <tbody>{sym_rows}</tbody>
    </table>
  </div>
</body>
</html>"""

    out_abs = os.path.abspath(output_path)
    with open(out_abs, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_abs
