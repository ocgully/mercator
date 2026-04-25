// Mercator atlas — single-project viewer.
//
// This file is bundled into the generated HTML by mercator/render/atlas/__init__.py
// (everything inside the IIFE below ends up inside one inline <script>). It is
// authored as plain JS — no build step, no framework, no module graph at runtime.
//
// Data shape (read from #atlas-data JSON island):
//   {
//     mercator_version, schema_version,
//     project: { id, name, stack, root, category, tags },
//     systems:    { systems: [...], stack },
//     contracts:  { <system_name>: { items: [...] } },
//     boundaries: { layers, boundaries },
//     violations: [ { rule_name, severity, path, ... } ],
//     assets:     { assets: [...] },
//     strings:    { strings: [...] },
//     meta:       { generated_at, git_head, tools, ... },
//     repo_meta:  { ... },           // repo-level meta (may be empty)
//     projects:   [ ...summary objs ],   // sibling projects (multi-project mode)
//     href_back:  "../../atlas.html"     // set when viewing a child page
//   }

(() => {
  const DATA = JSON.parse(document.getElementById('atlas-data').textContent);
  const PROJECT = DATA.project || null;
  const SYSTEMS = DATA.systems.systems || [];
  const STACK = DATA.systems.stack || (PROJECT && PROJECT.stack) || '?';
  const CONTRACTS = DATA.contracts || {};
  const BOUNDARIES = DATA.boundaries || {};
  const VIOLATIONS = DATA.violations || [];
  const ASSETS = (DATA.assets && DATA.assets.assets) || [];
  const STRINGS = (DATA.strings && DATA.strings.strings) || [];
  const META = DATA.meta || {};
  const app = document.getElementById('app');
  const tabs = document.getElementById('tabs');

  // Topbar enrichment: project name, repo back link.
  if (PROJECT) {
    const h1 = document.getElementById('atlas-h1');
    if (h1) h1.innerHTML = `Mercator Atlas <span class="sub">${PROJECT.name || PROJECT.id} · v${DATA.mercator_version} · ${STACK}</span>`;
  }
  if (DATA.href_back) {
    tabs.insertAdjacentHTML('afterbegin',
      `<a href="${DATA.href_back}" style="color:var(--accent-2)">↑ Repo</a>`);
  }

  // ---------- helpers ------------------------------------------------------
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const link = (href, text) => `<a href="${href}">${esc(text)}</a>`;
  const el = (html) => { const t = document.createElement('template');
    t.innerHTML = html.trim(); return t.content.firstElementChild; };
  function byName(a, b) { return a.name.localeCompare(b.name); }

  function allEdges() {
    const names = new Set(SYSTEMS.map(s => s.name));
    const edges = [];
    for (const s of SYSTEMS) {
      for (const d of (s.dependencies || [])) {
        if (names.has(d.name)) edges.push([s.name, d.name]);
      }
    }
    return edges;
  }
  function mermaidSafe(n) { return String(n).replace(/[^A-Za-z0-9_]/g, '_'); }

  function globMatch(pattern, name) {
    if (pattern === name) return true;
    const re = new RegExp('^' + pattern
      .replace(/[.+^${}()|\\]/g, '\\$&')
      .replace(/\*/g, '.*').replace(/\?/g, '.') + '$');
    return re.test(name);
  }

  // ---------- mermaid builders --------------------------------------------
  function mermaidDepGraph(systems, edges, highlight) {
    const layers = (BOUNDARIES && BOUNDARIES.layers) || {};
    const members = new Map(systems.map(s => [s.name, s]));
    const assignments = new Map();
    for (const name of members.keys()) {
      for (const [ln, sels] of Object.entries(layers)) {
        if (sels.some(sel => globMatch(sel, name))) { assignments.set(name, ln); break; }
      }
    }
    const byLayer = {};
    const unassigned = [];
    for (const name of [...members.keys()].sort()) {
      const l = assignments.get(name);
      if (l) (byLayer[l] = byLayer[l] || []).push(name);
      else unassigned.push(name);
    }
    const out = ['graph LR'];
    for (const [ln, ms] of Object.entries(byLayer).sort()) {
      out.push(`  subgraph ${mermaidSafe(ln)}[${ln}]`);
      for (const n of ms) out.push(`    ${mermaidSafe(n)}[${n}]`);
      out.push('  end');
    }
    for (const n of unassigned) out.push(`  ${mermaidSafe(n)}[${n}]`);
    for (const [a, b] of edges) {
      const arrow = (highlight && highlight.has(a + '\0' + b)) ? '==>' : '-->';
      out.push(`  ${mermaidSafe(a)} ${arrow} ${mermaidSafe(b)}`);
    }
    if (highlight && highlight.size > 0)
      out.push('  linkStyle default stroke:#777');
    return out.join('\n');
  }

  function mermaidBoundaryOverlay() {
    const layers = (BOUNDARIES && BOUNDARIES.layers) || {};
    const rules = (BOUNDARIES && BOUNDARIES.boundaries) || [];
    const names = SYSTEMS.map(s => s.name);
    const memberSet = new Set(names);
    const forbidden = new Set();
    const resolveSel = (sel) => {
      if (memberSet.has(sel)) return [sel];
      if (layers[sel]) {
        const out = new Set();
        for (const s of layers[sel]) for (const n of names)
          if (globMatch(s, n)) out.add(n);
        return [...out];
      }
      return names.filter(n => globMatch(sel, n));
    };
    for (const r of rules) {
      const from = resolveSel(r.from);
      const not_to = resolveSel(r.not_to);
      for (const a of from) for (const b of not_to)
        if (a !== b) forbidden.add(a + '\0' + b);
    }
    const violEdges = new Set();
    for (const v of VIOLATIONS) {
      const p = v.path || [];
      for (let i = 0; i < p.length - 1; i++)
        violEdges.add(p[i] + '\0' + p[i + 1]);
    }
    const out = ['graph LR'];
    const byLayer = {}; const unassigned = [];
    for (const n of [...names].sort()) {
      let placed = false;
      for (const [ln, sels] of Object.entries(layers)) {
        if (sels.some(sel => globMatch(sel, n))) {
          (byLayer[ln] = byLayer[ln] || []).push(n); placed = true; break;
        }
      }
      if (!placed) unassigned.push(n);
    }
    for (const [ln, ms] of Object.entries(byLayer).sort()) {
      out.push(`  subgraph ${mermaidSafe(ln)}[${ln}]`);
      for (const n of ms) out.push(`    ${mermaidSafe(n)}[${n}]`);
      out.push('  end');
    }
    for (const n of unassigned) out.push(`  ${mermaidSafe(n)}[${n}]`);
    const curEdges = allEdges();
    for (const [a, b] of curEdges) {
      if (violEdges.has(a + '\0' + b)) continue;
      out.push(`  ${mermaidSafe(a)} --- ${mermaidSafe(b)}`);
    }
    for (const key of forbidden) {
      const [a, b] = key.split('\0');
      if (violEdges.has(key)) out.push(`  ${mermaidSafe(a)} x==x|VIOLATION| ${mermaidSafe(b)}`);
      else out.push(`  ${mermaidSafe(a)} -.-x|forbidden| ${mermaidSafe(b)}`);
    }
    return out.join('\n');
  }

  async function renderMermaid(container, src) {
    container.innerHTML = '';
    const host = el(`<div class="mermaid"></div>`);
    container.appendChild(host);
    const srcBlock = el(`<pre class="mermaid-src">${esc(src)}</pre>`);
    const toggle = el(`<div><button class="btn" style="margin-top:6px">view source</button></div>`);
    container.appendChild(toggle);
    container.appendChild(srcBlock);
    toggle.querySelector('button').onclick = () => {
      srcBlock.style.display = srcBlock.style.display === 'block' ? 'none' : 'block';
    };
    if (window.mermaid) {
      try {
        const id = 'm' + Math.random().toString(36).slice(2);
        const { svg } = await window.mermaid.render(id, src);
        host.innerHTML = svg;
      } catch (e) {
        host.innerHTML = `<div class="empty">Mermaid render failed: ${esc(e.message)}</div>`;
        srcBlock.style.display = 'block';
      }
    } else {
      host.innerHTML = `<div class="empty">Mermaid not loaded (offline?). Source shown below.</div>`;
      srcBlock.style.display = 'block';
    }
  }

  // ---------- routes -------------------------------------------------------

  function routeOverview() {
    const nsys = SYSTEMS.length;
    const ndep = allEdges().length;
    const nrules = ((BOUNDARIES && BOUNDARIES.boundaries) || []).length;
    const nviol = VIOLATIONS.length;
    const nassets = ASSETS.length;
    const nstrings = STRINGS.length;
    const errViol = VIOLATIONS.filter(v => v.severity === 'error').length;
    const sysList = [...SYSTEMS].sort(byName).slice(0, 40);
    app.innerHTML = `
      <section class="panel">
        <h2>Overview</h2>
        <dl class="kvs">
          ${PROJECT ? `<dt>Project</dt><dd><strong>${esc(PROJECT.name || PROJECT.id)}</strong> <span class="pill">${esc(PROJECT.category || '')}</span></dd>` : ''}
          <dt>Stack</dt><dd>${esc(STACK)}</dd>
          <dt>Mercator</dt><dd>v${esc(DATA.mercator_version)} (schema ${esc(DATA.schema_version)})</dd>
          <dt>Generated</dt><dd>${esc(META.generated_at || '—')}</dd>
          <dt>HEAD</dt><dd class="mono">${esc(META.git_head || '—')}</dd>
          <dt>Tool versions</dt><dd class="mono">${esc(JSON.stringify(META.tools || META.tool_versions || {}))}</dd>
        </dl>
      </section>
      <section class="panel">
        <h2>At a glance</h2>
        <div class="counts">
          <div class="count"><span class="n">${nsys}</span><span class="lbl">Systems</span></div>
          <div class="count"><span class="n">${ndep}</span><span class="lbl">Dep edges</span></div>
          <div class="count"><span class="n">${nrules}</span><span class="lbl">DMZ rules</span></div>
          <div class="count"><span class="n ${errViol ? 'sev-error' : ''}">${nviol}</span><span class="lbl">Violations</span></div>
          <div class="count"><span class="n">${nassets}</span><span class="lbl">Assets</span></div>
          <div class="count"><span class="n">${nstrings}</span><span class="lbl">Strings</span></div>
        </div>
      </section>
      <section class="panel">
        <h2>Jump to a system</h2>
        <div class="chips">
          ${sysList.map(s => `<a href="#/systems/${encodeURIComponent(s.name)}">${esc(s.name)}</a>`).join('')}
          ${SYSTEMS.length > 40 ? `<a href="#/systems">… all ${SYSTEMS.length}</a>` : ''}
        </div>
      </section>
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator info
mercator query systems${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}</pre>
      </section>
    `;
  }

  function routeSystems() {
    const edges = allEdges();
    const sorted = [...SYSTEMS].sort(byName);
    app.innerHTML = `
      <section class="panel">
        <h2>Dependency graph</h2>
        ${sorted.length > 80
          ? `<div class="empty">Graph suppressed (${sorted.length} > 80 systems). Use search to focus.</div>`
          : `<div id="sys-graph"></div>`}
      </section>
      <section class="panel">
        <h2>Systems (${sorted.length})</h2>
        <input class="filter" id="sys-filter" placeholder="Filter by name or manifest…" />
        <table id="sys-table">
          <thead><tr>
            <th>Name</th><th>Scope / manifest</th><th>Depends on</th><th>Depended by</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query systems${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query deps &lt;system&gt;
mercator query touches &lt;path&gt;</pre>
      </section>
    `;
    if (sorted.length <= 80) {
      renderMermaid(document.getElementById('sys-graph'), mermaidDepGraph(sorted, edges));
    }
    const dependedBy = new Map();
    for (const s of SYSTEMS) for (const d of (s.dependencies || [])) {
      if (!dependedBy.has(d.name)) dependedBy.set(d.name, []);
      dependedBy.get(d.name).push(s.name);
    }
    const tbody = app.querySelector('#sys-table tbody');
    const renderRows = (q) => {
      const ql = q.toLowerCase();
      tbody.innerHTML = sorted
        .filter(s => !q || s.name.toLowerCase().includes(ql) ||
                     (s.manifest_path || '').toLowerCase().includes(ql))
        .map(s => {
          const deps = (s.dependencies || []).filter(d =>
            SYSTEMS.find(x => x.name === d.name)).map(d => d.name);
          const rdeps = dependedBy.get(s.name) || [];
          return `<tr>
            <td><a href="#/systems/${encodeURIComponent(s.name)}"><strong>${esc(s.name)}</strong></a></td>
            <td class="mono">${esc(s.manifest_path || s.scope_dir || '')}</td>
            <td>${deps.map(d => `<span class="pill">${esc(d)}</span>`).join(' ') || '<span class="pill">—</span>'}</td>
            <td>${rdeps.map(d => `<span class="pill">${esc(d)}</span>`).join(' ') || '<span class="pill">—</span>'}</td>
          </tr>`;
        }).join('');
    };
    renderRows('');
    app.querySelector('#sys-filter').addEventListener('input', (e) => renderRows(e.target.value));
  }

  function routeSystem(name) {
    const entry = SYSTEMS.find(s => s.name === name);
    if (!entry) {
      app.innerHTML = `<section class="panel"><h2>Unknown system: ${esc(name)}</h2>
        <p><a href="#/systems">Back to systems</a></p></section>`;
      return;
    }
    const depsOut = (entry.dependencies || []).filter(d => SYSTEMS.find(x => x.name === d.name));
    const depsIn = SYSTEMS.filter(s => (s.dependencies || []).some(d => d.name === name));
    const contract = CONTRACTS[name];
    const local = new Set([name, ...depsOut.map(d => d.name), ...depsIn.map(s => s.name)]);
    const localSystems = SYSTEMS.filter(s => local.has(s.name));
    const localEdges = allEdges().filter(([a, b]) => local.has(a) && local.has(b));
    const hl = new Set();
    for (const d of depsOut) hl.add(name + '\0' + d.name);
    for (const s of depsIn) hl.add(s.name + '\0' + name);

    app.innerHTML = `
      <section class="panel">
        <h2>${esc(name)} <span class="pill">${esc(STACK)}</span></h2>
        <dl class="kvs">
          <dt>Manifest</dt><dd class="mono">${esc(entry.manifest_path || '—')}</dd>
          ${entry.scope_dir ? `<dt>Scope</dt><dd class="mono">${esc(entry.scope_dir)}</dd>` : ''}
          ${entry.version ? `<dt>Version</dt><dd>${esc(entry.version)}</dd>` : ''}
          ${entry.kind ? `<dt>Kind</dt><dd>${esc(Array.isArray(entry.kind) ? entry.kind.join(', ') : entry.kind)}</dd>` : ''}
        </dl>
      </section>
      <section class="panel">
        <h2>Neighbourhood</h2>
        <div id="sys-detail-graph"></div>
      </section>
      <section class="panel grid2">
        <div>
          <h3>Depends on (${depsOut.length})</h3>
          ${depsOut.length
            ? depsOut.map(d => `<span class="pill"><a href="#/systems/${encodeURIComponent(d.name)}">${esc(d.name)}</a></span>`).join(' ')
            : '<div class="empty">None.</div>'}
        </div>
        <div>
          <h3>Depended by (${depsIn.length})</h3>
          ${depsIn.length
            ? depsIn.map(d => `<span class="pill"><a href="#/systems/${encodeURIComponent(d.name)}">${esc(d.name)}</a></span>`).join(' ')
            : '<div class="empty">None.</div>'}
        </div>
      </section>
      ${contractSection(name, contract)}
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query system ${esc(name)}${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query deps ${esc(name)}
mercator query contract ${esc(name)}</pre>
      </section>
    `;
    renderMermaid(document.getElementById('sys-detail-graph'),
      mermaidDepGraph(localSystems, localEdges, hl));
  }

  function contractSection(name, contract) {
    if (!contract) {
      return `<section class="panel"><h2>Contract (Layer 2)</h2>
        <div class="empty">No contract file for this system.
        Either it doesn't exist or Layer 2 isn't implemented for stack "${esc(STACK)}".</div></section>`;
    }
    const items = contract.items || contract.public_items || contract.symbols || [];
    const rows = items.map(it => `
      <tr>
        <td><span class="pill">${esc(it.kind || '?')}</span></td>
        <td class="mono"><strong>${esc(it.name || '')}</strong></td>
        <td class="mono">${esc(it.path || it.file || '')}${it.line ? ':' + esc(it.line) : ''}</td>
        <td class="mono"><code>${esc(it.signature || it.sig || '')}</code></td>
      </tr>
    `).join('');
    return `<section class="panel">
      <h2>Contract (Layer 2) — ${items.length} public item${items.length === 1 ? '' : 's'}</h2>
      ${items.length ? `
        <input class="filter" id="contract-filter" placeholder="Filter items…" />
        <table id="contract-table">
          <thead><tr><th>Kind</th><th>Name</th><th>Path</th><th>Signature</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      ` : '<div class="empty">No public items detected.</div>'}
      <details style="margin-top:12px"><summary>Raw contract JSON</summary>
        <pre class="cmd">${esc(JSON.stringify(contract, null, 2))}</pre></details>
    </section>`;
  }

  function routeSymbols() {
    const all = [];
    for (const [sys, c] of Object.entries(CONTRACTS)) {
      const items = c.items || c.public_items || c.symbols || [];
      for (const it of items) all.push({ system: sys, ...it });
    }
    app.innerHTML = `
      <section class="panel">
        <h2>Symbols (${all.length})</h2>
        <input class="filter" id="sym-filter" placeholder="Filter by name…" />
        <select class="filter" id="sym-kind">
          <option value="">any kind</option>
          ${[...new Set(all.map(s => s.kind).filter(Boolean))].sort()
            .map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}
        </select>
        <select class="filter" id="sym-system">
          <option value="">any system</option>
          ${Object.keys(CONTRACTS).sort().map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('')}
        </select>
        <table id="sym-table">
          <thead><tr><th>Kind</th><th>Name</th><th>System</th><th>Path</th><th>Signature</th></tr></thead>
          <tbody></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query symbol &lt;name&gt;${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query symbol &lt;name&gt; --kind fn
mercator query symbol &lt;name&gt; --kinds fn,struct,trait</pre>
      </section>
    `;
    const tbody = app.querySelector('#sym-table tbody');
    const fName = app.querySelector('#sym-filter');
    const fKind = app.querySelector('#sym-kind');
    const fSys = app.querySelector('#sym-system');
    const render = () => {
      const q = fName.value.toLowerCase();
      const k = fKind.value;
      const s = fSys.value;
      const rows = all.filter(it =>
        (!q || (it.name || '').toLowerCase().includes(q)) &&
        (!k || it.kind === k) &&
        (!s || it.system === s)
      ).slice(0, 2000);
      tbody.innerHTML = rows.map(it => `
        <tr>
          <td><span class="pill">${esc(it.kind || '?')}</span></td>
          <td class="mono"><strong>${esc(it.name || '')}</strong></td>
          <td><a href="#/systems/${encodeURIComponent(it.system)}">${esc(it.system)}</a></td>
          <td class="mono">${esc(it.path || it.file || '')}${it.line ? ':' + esc(it.line) : ''}</td>
          <td class="mono"><code>${esc(it.signature || it.sig || '')}</code></td>
        </tr>`).join('') || '<tr><td colspan="5" class="empty">No matches.</td></tr>';
    };
    fName.addEventListener('input', render);
    fKind.addEventListener('change', render);
    fSys.addEventListener('change', render);
    render();
  }

  function routeBoundaries() {
    const rules = (BOUNDARIES && BOUNDARIES.boundaries) || [];
    const hasBoundaries = rules.length > 0;
    const vByRule = {};
    for (const v of VIOLATIONS) (vByRule[v.rule_name] = vByRule[v.rule_name] || []).push(v);
    app.innerHTML = `
      <section class="panel">
        <h2>DMZ rules</h2>
        ${!hasBoundaries
          ? '<div class="empty">No <code>.mercator/projects/&lt;id&gt;/boundaries.json</code>. Run <code>mercator boundaries init</code> to scaffold one.</div>'
          : `<table>
              <thead><tr><th>Rule</th><th>From</th><th>Not to</th><th>Severity</th><th>Transitive</th><th>Status</th></tr></thead>
              <tbody>
                ${rules.map(r => {
                  const vs = vByRule[r.name] || [];
                  const badge = vs.length
                    ? `<span class="pill danger">${vs.length} violation${vs.length===1?'':'s'}</span>`
                    : `<span class="pill ok">pass</span>`;
                  return `<tr>
                    <td><strong>${esc(r.name)}</strong>
                      ${r.rationale ? `<div style="color:var(--muted)">${esc(r.rationale)}</div>` : ''}
                    </td>
                    <td class="mono">${esc(r.from)}</td>
                    <td class="mono">${esc(r.not_to)}</td>
                    <td class="sev-${esc(r.severity || 'error')}">${esc(r.severity || 'error')}</td>
                    <td>${r.transitive === false ? 'direct only' : 'transitive'}</td>
                    <td>${badge}</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>`
        }
      </section>
      ${hasBoundaries ? `
        <section class="panel">
          <h2>Forbidden-edge overlay</h2>
          <div id="dmz-graph"></div>
        </section>
        <section class="panel">
          <h2>Violations (${VIOLATIONS.length})</h2>
          ${VIOLATIONS.length ? `
            <table>
              <thead><tr><th>Severity</th><th>Rule</th><th>Path</th><th>Rationale</th></tr></thead>
              <tbody>
                ${VIOLATIONS.map(v => `
                  <tr>
                    <td class="sev-${esc(v.severity)}">${esc(v.severity)}</td>
                    <td>${esc(v.rule_name)}</td>
                    <td class="mono">${v.path.map(p => link('#/systems/'+encodeURIComponent(p), p)).join(' → ')}</td>
                    <td>${esc(v.rationale || '')}</td>
                  </tr>`).join('')}
              </tbody>
            </table>` : '<div class="empty">✅ No violations. All rules pass.</div>'}
        </section>
      ` : ''}
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query boundaries${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query violations
mercator check                 # CI gate — exit 1 on error-severity (across all projects)
mercator boundaries init       # scaffold this project's boundaries.json</pre>
      </section>
    `;
    if (hasBoundaries) {
      renderMermaid(document.getElementById('dmz-graph'), mermaidBoundaryOverlay());
    }
  }

  function routeAssets() {
    const kinds = [...new Set(ASSETS.map(a => a.kind).filter(Boolean))].sort();
    const systems = [...new Set(ASSETS.map(a => a.owning_system).filter(Boolean))].sort();
    app.innerHTML = `
      <section class="panel">
        <h2>Assets (${ASSETS.length})</h2>
        <input class="filter" id="a-file" placeholder="Filter by file / path…" />
        <select class="filter" id="a-kind"><option value="">any kind</option>
          ${kinds.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}</select>
        <select class="filter" id="a-sys"><option value="">any system</option>
          ${systems.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('')}</select>
        <table id="a-table">
          <thead><tr><th>Kind</th><th>File</th><th>System</th><th>Size</th></tr></thead>
          <tbody></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query assets${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query assets --system &lt;system&gt;
mercator query assets --asset-kind texture</pre>
      </section>
    `;
    const fFile = app.querySelector('#a-file');
    const fKind = app.querySelector('#a-kind');
    const fSys = app.querySelector('#a-sys');
    const tbody = app.querySelector('#a-table tbody');
    const render = () => {
      const qf = fFile.value.toLowerCase();
      const qk = fKind.value;
      const qs = fSys.value;
      const rows = ASSETS.filter(a =>
        (!qf || (a.file || '').toLowerCase().includes(qf)) &&
        (!qk || a.kind === qk) &&
        (!qs || a.owning_system === qs)
      ).slice(0, 2000);
      tbody.innerHTML = rows.map(a => `
        <tr>
          <td><span class="pill">${esc(a.kind || '?')}</span></td>
          <td class="mono">${esc(a.file || '')}</td>
          <td>${a.owning_system ? link('#/systems/'+encodeURIComponent(a.owning_system), a.owning_system) : '<span class="pill">—</span>'}</td>
          <td class="mono">${a.bytes != null ? esc(a.bytes) : ''}</td>
        </tr>`).join('') || '<tr><td colspan="4" class="empty">No matches.</td></tr>';
    };
    fFile.addEventListener('input', render); fKind.addEventListener('change', render); fSys.addEventListener('change', render);
    render();
  }

  function routeStrings() {
    const systems = [...new Set(STRINGS.map(s => s.owning_system).filter(Boolean))].sort();
    app.innerHTML = `
      <section class="panel">
        <h2>Strings (${STRINGS.length})</h2>
        <input class="filter" id="s-key" placeholder="Filter by key (glob OK)…" />
        <input class="filter" id="s-file" placeholder="Filter by file…" />
        <select class="filter" id="s-sys"><option value="">any system</option>
          ${systems.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('')}</select>
        <table id="s-table">
          <thead><tr><th>Key</th><th>Value</th><th>System</th><th>File</th></tr></thead>
          <tbody></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Equivalent CLI</h2>
        <pre class="cmd">mercator query strings${PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : ''}
mercator query strings --key 'login.*'
mercator query strings --file &lt;path&gt;
mercator query strings --system &lt;system&gt;</pre>
      </section>
    `;
    const fKey = app.querySelector('#s-key');
    const fFile = app.querySelector('#s-file');
    const fSys = app.querySelector('#s-sys');
    const tbody = app.querySelector('#s-table tbody');
    const render = () => {
      const qk = fKey.value;
      const qf = fFile.value.toLowerCase();
      const qs = fSys.value;
      const matchKey = (s) => {
        if (!qk) return true;
        if (qk.includes('*') || qk.includes('?')) return globMatch(qk, s.key || '');
        return (s.key || '').toLowerCase().includes(qk.toLowerCase());
      };
      const rows = STRINGS.filter(s => matchKey(s) &&
        (!qf || (s.file || '').toLowerCase().includes(qf)) &&
        (!qs || s.owning_system === qs)
      ).slice(0, 2000);
      tbody.innerHTML = rows.map(s => `
        <tr>
          <td class="mono"><strong>${esc(s.key || '')}</strong></td>
          <td>${esc(s.value || '')}</td>
          <td>${s.owning_system ? link('#/systems/'+encodeURIComponent(s.owning_system), s.owning_system) : '<span class="pill">—</span>'}</td>
          <td class="mono">${esc(s.file || '')}</td>
        </tr>`).join('') || '<tr><td colspan="4" class="empty">No matches.</td></tr>';
    };
    fKey.addEventListener('input', render); fFile.addEventListener('input', render); fSys.addEventListener('change', render);
    render();
  }

  function shellQuote(s) {
    if (!/[\s"'\\$`*?\[\]()]/.test(s)) return s;
    return `'${s.replace(/'/g, `'\\''`)}'`;
  }

  function routeQuery() {
    const projFlag = PROJECT && PROJECT.id ? ` --project ${PROJECT.id}` : '';
    app.innerHTML = `
      <section class="panel">
        <h2>Query console</h2>
        <p class="empty" style="font-style:normal;color:var(--muted)">
          The atlas is read-only HTML, but every view maps to a CLI invocation.
          Pick a subject below to build the exact command an agent would run${PROJECT && PROJECT.id ? ` against project <strong>${esc(PROJECT.id)}</strong>` : ''}.
        </p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <label>Subject
            <select id="q-subject" class="filter">
              ${['systems','deps','contract','symbol','touches','system','boundaries','violations','assets','strings']
                .map(s => `<option>${s}</option>`).join('')}
            </select>
          </label>
          <label>Name/Path
            <input id="q-name" class="filter" placeholder="(depends on subject)" />
          </label>
          <label>--kind
            <select id="q-kind" class="filter">
              ${['','any','fn','struct','enum','trait','type','const','static','mod']
                .map(k => `<option value="${k}">${k || '(none)'}</option>`).join('')}
            </select>
          </label>
          <label>--kinds
            <input id="q-kinds" class="filter" placeholder="fn,struct" />
          </label>
          <label>--system
            <select id="q-system" class="filter">
              <option value="">(none)</option>
              ${SYSTEMS.map(s => `<option>${esc(s.name)}</option>`).join('')}
            </select>
          </label>
          <label>--asset-kind
            <input id="q-asset-kind" class="filter" placeholder="texture" />
          </label>
          <label>--key
            <input id="q-key" class="filter" placeholder="login.*" />
          </label>
          <label>--file
            <input id="q-file" class="filter" placeholder="path/to/file" />
          </label>
        </div>
        <h3>Command</h3>
        <pre class="cmd" id="q-cmd">mercator query systems${projFlag}</pre>
        <div style="display:flex;gap:8px;align-items:center">
          <button id="q-copy">Copy</button>
          <span id="q-hint" class="empty" style="font-style:normal"></span>
        </div>
      </section>
      <section class="panel">
        <h2>All query subjects</h2>
        <table>
          <thead><tr><th>Subject</th><th>Purpose</th><th>Args</th></tr></thead>
          <tbody>
            <tr><td><code>systems</code></td><td>Layer 1: all systems + deps</td><td>—</td></tr>
            <tr><td><code>deps &lt;system&gt;</code></td><td>Forward + reverse dep edges for one system</td><td>name</td></tr>
            <tr><td><code>contract &lt;system&gt;</code></td><td>Layer 2: public surface</td><td>name</td></tr>
            <tr><td><code>symbol &lt;name&gt;</code></td><td>Layer 3: definition lookup (Rust today)</td><td>name, --kind, --kinds</td></tr>
            <tr><td><code>touches &lt;path&gt;</code></td><td>Which system owns this file</td><td>path</td></tr>
            <tr><td><code>system &lt;name&gt;</code></td><td>Composite: Layer 1 entry + deps + contract</td><td>name</td></tr>
            <tr><td><code>boundaries</code></td><td>DMZ rules + per-rule pass/fail</td><td>—</td></tr>
            <tr><td><code>violations</code></td><td>Failing rules with violation paths</td><td>—</td></tr>
            <tr><td><code>assets</code></td><td>Layer 4: asset inventory</td><td>--system, --asset-kind</td></tr>
            <tr><td><code>strings</code></td><td>Layer 4: user-facing strings</td><td>--system, --key, --file</td></tr>
          </tbody>
        </table>
      </section>
    `;
    const $ = (id) => document.getElementById(id);
    const cmd = $('q-cmd');
    const subject = $('q-subject');
    const hint = $('q-hint');
    const build = () => {
      const s = subject.value;
      const name = $('q-name').value.trim();
      const parts = ['mercator query', s];
      const needsName = ['deps','contract','symbol','touches','system'];
      if (needsName.includes(s)) {
        if (name) parts.push(shellQuote(name));
        else hint.textContent = `${s} requires a name.`;
      } else {
        hint.textContent = '';
      }
      const k = $('q-kind').value;
      if (s === 'symbol' && k && k !== 'any') parts.push('--kind', k);
      const ks = $('q-kinds').value.trim();
      if (s === 'symbol' && ks) parts.push('--kinds', shellQuote(ks));
      const sys = $('q-system').value;
      if ((s === 'assets' || s === 'strings') && sys) parts.push('--system', shellQuote(sys));
      const ak = $('q-asset-kind').value.trim();
      if (s === 'assets' && ak) parts.push('--asset-kind', shellQuote(ak));
      const key = $('q-key').value.trim();
      if (s === 'strings' && key) parts.push('--key', shellQuote(key));
      const file = $('q-file').value.trim();
      if (s === 'strings' && file) parts.push('--file', shellQuote(file));
      if (PROJECT && PROJECT.id) parts.push('--project', PROJECT.id);
      cmd.textContent = parts.join(' ');
    };
    ['q-subject','q-name','q-kind','q-kinds','q-system','q-asset-kind','q-key','q-file']
      .forEach(id => {
        const elm = $(id);
        elm.addEventListener('input', build);
        elm.addEventListener('change', build);
      });
    $('q-copy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(cmd.textContent); hint.textContent = 'Copied.'; }
      catch { hint.textContent = 'Copy failed — select the text manually.'; }
    });
    build();
  }

  // ---------- global search / shortcuts ------------------------------------

  const globalSearch = document.getElementById('global-search');
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== globalSearch &&
        !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {
      e.preventDefault(); globalSearch.focus();
    }
  });
  globalSearch.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const q = globalSearch.value.trim();
    if (!q) return;
    if (SYSTEMS.find(s => s.name === q)) {
      location.hash = '#/systems/' + encodeURIComponent(q); return;
    }
    const sysHit = SYSTEMS.find(s => s.name.toLowerCase().startsWith(q.toLowerCase()));
    if (sysHit) { location.hash = '#/systems/' + encodeURIComponent(sysHit.name); return; }
    for (const [sys, c] of Object.entries(CONTRACTS)) {
      const items = c.items || c.public_items || c.symbols || [];
      if (items.some(it => (it.name || '').toLowerCase() === q.toLowerCase())) {
        location.hash = '#/symbols';
        setTimeout(() => {
          const f = document.getElementById('sym-filter');
          if (f) { f.value = q; f.dispatchEvent(new Event('input')); }
        }, 30);
        return;
      }
    }
    location.hash = '#/systems';
    setTimeout(() => {
      const f = document.getElementById('sys-filter');
      if (f) { f.value = q; f.dispatchEvent(new Event('input')); }
    }, 30);
  });

  // ---------- router -------------------------------------------------------

  // Parse `#/route?key=value&...` — splits the querystring off the last
  // hash segment so e.g. `#/symbols?q=foo` yields parts=['symbols'] and
  // params={q:'foo'}. Used by repo-wide search to deep-link with a prefilter.
  function parseHash() {
    const raw = location.hash || '#/overview';
    const noHash = raw.replace(/^#\//, '');
    const qIdx = noHash.indexOf('?');
    const path = qIdx >= 0 ? noHash.slice(0, qIdx) : noHash;
    const query = qIdx >= 0 ? noHash.slice(qIdx + 1) : '';
    const params = {};
    if (query) {
      for (const kv of query.split('&')) {
        if (!kv) continue;
        const eq = kv.indexOf('=');
        const k = eq >= 0 ? kv.slice(0, eq) : kv;
        const v = eq >= 0 ? kv.slice(eq + 1) : '';
        try { params[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' ')); }
        catch { params[k] = v; }
      }
    }
    return { parts: path.split('/'), params };
  }

  // Prefill a route's filter input with the `?q=...` hash param after the
  // route renders. Each route uses a different filter element id.
  function applyHashQuery(route, params) {
    if (!params || !params.q) return;
    const FILTER_BY_ROUTE = {
      systems: 'sys-filter',
      symbols: 'sym-filter',
      assets: 'a-file',
      strings: 's-key',
    };
    const id = FILTER_BY_ROUTE[route];
    if (!id) return;
    setTimeout(() => {
      const f = document.getElementById(id);
      if (f) { f.value = params.q; f.dispatchEvent(new Event('input')); }
    }, 30);
  }

  function router() {
    const { parts, params } = parseHash();
    for (const a of tabs.querySelectorAll('a')) a.classList.remove('active');
    const route = parts[0] || 'overview';
    const tab = tabs.querySelector(`a[href="#/${route}"]`);
    if (tab) tab.classList.add('active');
    switch (route) {
      case '': case 'overview': routeOverview(); break;
      case 'systems':
        if (parts[1]) { routeSystem(decodeURIComponent(parts[1])); break; }
        routeSystems(); applyHashQuery('systems', params); break;
      case 'symbols': routeSymbols(); applyHashQuery('symbols', params); break;
      case 'boundaries': routeBoundaries(); break;
      case 'assets': routeAssets(); applyHashQuery('assets', params); break;
      case 'strings': routeStrings(); applyHashQuery('strings', params); break;
      case 'query': routeQuery(); break;
      default: routeOverview();
    }
  }
  window.addEventListener('hashchange', router);

  // ---------- mermaid init -------------------------------------------------

  function initMermaid(cb) {
    if (window.mermaid) {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default',
      });
      cb();
      return;
    }
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    s.onload = () => {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default',
      });
      cb();
    };
    s.onerror = () => cb();
    document.head.appendChild(s);
  }

  initMermaid(router);
})();
