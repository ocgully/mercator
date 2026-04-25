// Mercator atlas — multi-project repo index page (project picker).
//
// Phase 5 will enrich this with the cross-project graph, repo-wide search,
// and category sidebars. For now: stack/category filters + cards grouped
// by category, each linking to its project's atlas page.

(() => {
  const DATA = JSON.parse(document.getElementById('atlas-data').textContent);
  const SUMM = DATA.summaries || [];
  const META = DATA.repo_meta || {};
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const app = document.getElementById('app');

  const EDGES = (DATA.repo_edges && DATA.repo_edges.edges) || [];
  const totalSys = SUMM.reduce((a, s) => a + (s.systems_count || 0), 0);
  const totalCon = SUMM.reduce((a, s) => a + (s.contracts_count || 0), 0);
  const totalErr = SUMM.reduce((a, s) => a + (s.error_violations || 0), 0);
  const totalViol = SUMM.reduce((a, s) => a + (s.violation_count || 0), 0);
  const stacks = [...new Set(SUMM.map(s => s.stack))].sort();
  const cats = [...new Set(SUMM.map(s => s.category))].sort();

  const renderCard = (s) => {
    const violBadge = s.violation_count
      ? `<span class="pill ${s.error_violations ? 'danger' : 'warn'}">${s.violation_count} violation${s.violation_count===1?'':'s'}</span>`
      : `<span class="pill ok">clean</span>`;
    return `
      <div class="card">
        <h3><a href="${esc(s.href)}">${esc(s.name || s.id)}</a></h3>
        <div class="meta">${esc(s.root)}</div>
        <div>
          <span class="pill">${esc(s.stack)}</span>
          <span class="pill">${esc(s.category)}</span>
          ${(s.tags || []).map(t => `<span class="pill tag">${esc(t)}</span>`).join('')}
        </div>
        <div class="stats">
          <span class="pill">${s.systems_count} systems</span>
          <span class="pill">${s.contracts_count} contracts</span>
          ${violBadge}
        </div>
      </div>
    `;
  };

  // ---------- Cross-project mermaid graph ----------------------------------
  const mermaidSafe = (n) => String(n).replace(/[^A-Za-z0-9_]/g, '_');
  function buildCrossProjectGraph() {
    const lines = ['graph LR'];
    // Group nodes by category for visual clarity.
    const byCat = {};
    for (const s of SUMM) (byCat[s.category] = byCat[s.category] || []).push(s);
    for (const [cat, items] of Object.entries(byCat).sort()) {
      lines.push(`  subgraph ${mermaidSafe(cat)}[${cat}]`);
      for (const s of items.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))) {
        const label = `${s.name || s.id}\\n[${s.stack}]`;
        lines.push(`    ${mermaidSafe(s.id)}["${label}"]`);
      }
      lines.push('  end');
    }
    for (const e of EDGES) lines.push(`  ${mermaidSafe(e.from)} -->|${e.via}| ${mermaidSafe(e.to)}`);
    return lines.join('\n');
  }
  async function renderMermaidInto(container, src) {
    container.innerHTML = '';
    const host = document.createElement('div');
    host.className = 'mermaid';
    container.appendChild(host);
    if (window.mermaid) {
      try {
        const id = 'm' + Math.random().toString(36).slice(2);
        const { svg } = await window.mermaid.render(id, src);
        host.innerHTML = svg;
      } catch (e) {
        host.innerHTML = `<div class="empty">Mermaid render failed: ${esc(e.message)}</div>`;
      }
    } else {
      host.innerHTML = '<div class="empty">Mermaid not loaded (offline?).</div>';
    }
  }
  function ensureMermaid(cb) {
    if (window.mermaid) {
      window.mermaid.initialize({ startOnLoad: false,
        theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default' });
      cb();
      return;
    }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    s.onload = () => {
      window.mermaid.initialize({ startOnLoad: false,
        theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default' });
      cb();
    };
    s.onerror = () => cb();
    document.head.appendChild(s);
  }

  app.innerHTML = `
    <section class="panel">
      <h2>Repo overview</h2>
      <div class="counts">
        <div class="count"><span class="n">${SUMM.length}</span><span class="lbl">Projects</span></div>
        <div class="count"><span class="n">${stacks.length}</span><span class="lbl">Stacks</span></div>
        <div class="count"><span class="n">${totalSys}</span><span class="lbl">Systems (all)</span></div>
        <div class="count"><span class="n">${totalCon}</span><span class="lbl">Contracts</span></div>
        <div class="count"><span class="n" style="color:${totalErr ? 'var(--danger)' : 'var(--accent)'}">${totalViol}</span><span class="lbl">Violations</span></div>
      </div>
      <div style="color:var(--muted); font-size:12px;">
        Stacks: ${stacks.map(s => `<span class="pill">${esc(s)}</span>`).join(' ')}
        &middot; HEAD <code>${esc((META.git_head || '').slice(0, 8) || '—')}</code>
        &middot; Generated ${esc(META.generated_at || '—')}
      </div>
    </section>
    <section class="panel">
      <h2>Projects</h2>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">
        <input id="f-name" class="filter" placeholder="Filter by name…" />
        <select id="f-stack" class="filter"><option value="">any stack</option>${stacks.map(s => `<option>${esc(s)}</option>`).join('')}</select>
        <select id="f-cat" class="filter"><option value="">any category</option>${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select>
      </div>
      <div id="projects-by-cat"></div>
    </section>
    <section class="panel">
      <h2>Project graph</h2>
      ${SUMM.length === 0
        ? '<div class="empty">No projects detected.</div>'
        : '<div id="proj-graph"></div>'}
    </section>
    ${(() => {
      const RB = DATA.repo_boundaries;
      if (!RB) {
        return `<section class="panel">
          <h2>Repo-level boundaries</h2>
          <div class="empty">No <code>.mercator/repo-boundaries.json</code>. Run <code>mercator boundaries init --repo</code> to scaffold cross-project DMZ rules.</div>
        </section>`;
      }
      const rules = RB.rules || [];
      const violations = RB.violations || [];
      return `<section class="panel">
        <h2>Repo-level boundaries (${rules.length} rule${rules.length===1?'':'s'})</h2>
        ${rules.length === 0 ? '<div class="empty">No rules declared.</div>' : `
          <table>
            <thead><tr><th>Rule</th><th>From</th><th>Not to</th><th>Severity</th><th>Status</th></tr></thead>
            <tbody>
              ${rules.map(r => {
                const c = r.violation_count || 0;
                const badge = c
                  ? `<span class="pill ${r.severity === 'error' ? 'danger' : 'warn'}">${c} violation${c===1?'':'s'}</span>`
                  : `<span class="pill ok">pass</span>`;
                return `<tr>
                  <td><strong>${esc(r.name)}</strong>${r.rationale ? `<div style="color:var(--muted)">${esc(r.rationale)}</div>` : ''}</td>
                  <td class="mono">${esc(r.from_selector)}</td>
                  <td class="mono">${esc(r.not_to_selector)}</td>
                  <td class="sev-${esc(r.severity)}">${esc(r.severity)}</td>
                  <td>${badge}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>`}
        ${violations.length ? `
          <h3>Repo violations (${violations.length})</h3>
          <table>
            <thead><tr><th>Severity</th><th>Rule</th><th>Path (project chain)</th><th>Rationale</th></tr></thead>
            <tbody>
              ${violations.map(v => `<tr>
                <td class="sev-${esc(v.severity)}">${esc(v.severity)}</td>
                <td>${esc(v.rule_name)}</td>
                <td class="mono">${(v.path || []).map(p => `<a href="atlas/projects/${esc(p)}.html">${esc(p)}</a>`).join(' → ')}</td>
                <td>${esc(v.rationale || '')}</td>
              </tr>`).join('')}
            </tbody>
          </table>` : ''}
      </section>`;
    })()}
    <section class="panel">
      <h2>Cross-project edges (${EDGES.length})</h2>
      ${EDGES.length === 0
        ? '<div class="empty">No implicit edges detected — projects are independent at the build level.</div>'
        : `<table>
            <thead><tr><th>From</th><th>To</th><th>Via</th><th>Kind</th></tr></thead>
            <tbody>
              ${EDGES.map(e => `<tr>
                <td><a href="atlas/projects/${esc(e.from)}.html"><strong>${esc(e.from)}</strong></a></td>
                <td><a href="atlas/projects/${esc(e.to)}.html"><strong>${esc(e.to)}</strong></a></td>
                <td class="mono">${esc(e.via)}</td>
                <td><span class="pill">${esc(e.kind)}</span></td>
              </tr>`).join('')}
            </tbody>
          </table>
          <details style="margin-top:8px"><summary>How this works</summary>
            <div style="color:var(--muted);font-size:12px;margin-top:6px">
              Edges are inferred by matching each project's external dependency
              names against other projects' published manifest names (Cargo
              <code>name</code>, <code>package.json</code> name, pyproject
              <code>[project].name</code>, etc.). No edges file is authored —
              this is fully derived.
            </div>
          </details>`}
    </section>
    <section class="panel">
      <h2>Equivalent CLI</h2>
      <pre class="cmd">mercator projects list
mercator query systems --project &lt;id&gt;
mercator refresh --project &lt;id&gt;
mercator check                        # CI gate across ALL projects</pre>
    </section>
  `;
  const container = document.getElementById('projects-by-cat');
  const fName = document.getElementById('f-name');
  const fStack = document.getElementById('f-stack');
  const fCat = document.getElementById('f-cat');

  function render() {
    const q = (fName.value || '').toLowerCase();
    const ss = fStack.value;
    const sc = fCat.value;
    const filtered = SUMM.filter(s =>
      (!q || (s.name || s.id).toLowerCase().includes(q)) &&
      (!ss || s.stack === ss) &&
      (!sc || s.category === sc)
    );
    const grouped = {};
    for (const s of filtered) {
      (grouped[s.category] = grouped[s.category] || []).push(s);
    }
    container.innerHTML = Object.keys(grouped).sort().map(cat => `
      <div class="cat-h">${esc(cat)} (${grouped[cat].length})</div>
      <div class="cards-grid">${grouped[cat].map(renderCard).join('')}</div>
    `).join('') || `<div class="empty">No projects match.</div>`;
  }
  fName.addEventListener('input', render);
  fStack.addEventListener('change', render);
  fCat.addEventListener('change', render);
  render();

  // Render cross-project graph after the cards are in place so it sits
  // alongside the project list.
  if (SUMM.length > 0) {
    ensureMermaid(() => renderMermaidInto(
      document.getElementById('proj-graph'),
      buildCrossProjectGraph(),
    ));
  }
})();
