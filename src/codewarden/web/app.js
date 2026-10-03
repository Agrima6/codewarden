(() => {
'use strict';

/* ---------- tiny DOM helper: text is always set via textContent/text nodes, never innerHTML ---------- */
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'open') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else el.append(c.nodeType ? c : document.createTextNode(String(c)));
  };
  kids.forEach(add);
  return el;
}
const $ = (s, r = document) => r.querySelector(s);
const SEV = ['critical', 'high', 'medium', 'low'];
const ICONS = {
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  plus: 'M12 5v14M5 12h14',
  flask: 'M9 3h6M10 3v6l-5.500 9.500A2 2 0 0 0 6.200 21h11.600a2 2 0 0 0 1.700-2.500L14 9V3',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.300-4.300',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.400 15a1.700 1.700 0 0 0 .3 1.800l.1.1a2 2 0 1 1-2.800 2.800l-.1-.1a1.700 1.700 0 0 0-1.800-.3 1.700 1.700 0 0 0-1 1.500V21a2 2 0 1 1-4 0v-.1a1.700 1.700 0 0 0-1.100-1.500 1.700 1.700 0 0 0-1.800.3l-.1.1a2 2 0 1 1-2.800-2.800l.1-.1a1.700 1.700 0 0 0 .3-1.800 1.700 1.700 0 0 0-1.500-1H3a2 2 0 1 1 0-4h.1a1.700 1.700 0 0 0 1.500-1.100 1.700 1.700 0 0 0-.3-1.800l-.1-.1a2 2 0 1 1 2.800-2.800l.1.100a1.700 1.700 0 0 0 1.800.3H9a1.700 1.700 0 0 0 1-1.500V3a2 2 0 1 1 4 0v.1a1.700 1.700 0 0 0 1 1.500 1.700 1.700 0 0 0 1.800-.3l.1-.1a2 2 0 1 1 2.800 2.800l-.1.100a1.700 1.700 0 0 0-.3 1.800V9a1.700 1.700 0 0 0 1.500 1H21a2 2 0 1 1 0 4h-.1a1.700 1.700 0 0 0-1.500 1z',
};
function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(ns, 'path');
  p.setAttribute('d', ICONS[name]);
  svg.append(p);
  return svg;
}

/* ---------- api ---------- */
let token = sessionStorage.getItem('cw_token') || '';
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const res = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401) {
    const t = window.prompt('This dashboard requires an access token:');
    if (t) { token = t; sessionStorage.setItem('cw_token', t); return api(path, opts); }
    throw new Error('Unauthorized');
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) throw new Error((data && (data.error || data.detail)) || `Request failed (${res.status})`);
  return data;
}

/* ---------- utilities ---------- */
function toast(msg, isErr) {
  const t = h('div', { class: 'toast' + (isErr ? ' err' : '') }, msg);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), isErr ? 7000 : 3500);
}
function ago(ts) {
  const s = Math.max(1, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' h ago';
  return new Date(ts * 1000).toLocaleDateString();
}
const fmtMs = (ms) => (ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' s');
const pct = (x) => (x == null ? 'n/a' : Math.round(x * 100) + '%');
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const SOURCE_LABEL = { diff: 'Pasted diff', pr: 'GitHub PR', sample: 'Sample', demo: 'Sample PR', webhook: 'Webhook' };
async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied'); }
  catch (_) { toast('Copy failed. Select the text and copy manually.', true); }
}
function busy(btn, fn) {
  return async (...a) => {
    const old = btn.textContent;
    btn.disabled = true; btn.replaceChildren(h('span', { class: 'spin' }), ' Working');
    try { return await fn(...a); } finally { btn.disabled = false; btn.textContent = old; }
  };
}
function sevBar(by) {
  const total = SEV.reduce((n, s) => n + (by[s] || 0), 0);
  return h('div', { class: 'sevbar', title: SEV.map((s) => `${by[s] || 0} ${s}`).join(', '), role: 'img', 'aria-label': `${total} findings` },
    SEV.map((s) => (by[s] ? h('i', { class: 'sev-' + s, style: `width:${(by[s] / total) * 100}%` }) : null)));
}
const sevBadge = (s) => h('span', { class: 'badge ' + s }, s);
function emptyState(title, text, ...actions) {
  return h('div', { class: 'card empty' }, h('h2', {}, title), h('p', {}, text), h('div', { class: 'row', style: 'justify-content:center' }, actions));
}
function skeleton(n = 4) {
  return h('div', { class: 'card card-pad', 'aria-busy': 'true' }, Array.from({ length: n }, () => h('div', { class: 'skeleton', style: 'margin:12px 0;width:' + (50 + Math.random() * 45) + '%' })));
}
function modal(title, ...body) {
  const m = $('#modal');
  m.replaceChildren(h('div', { class: 'modal-head' }, h('strong', {}, title), h('button', { class: 'btn small', onclick: () => m.close(), 'aria-label': 'Close' }, 'Close')), h('div', { class: 'modal-body' }, body));
  m.showModal();
}
$('#modal').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

/* ---------- shared state ---------- */
let providers = null, config = null;
async function loadMeta() {
  [providers, config] = await Promise.all([api('/api/providers'), api('/api/config')]);
}
function defaultProvider() {
  const ok = (id) => providers.find((p) => p.id === id && p.available);
  return (ok('gemini') || ok('ollama') || ok('rules')).id;
}
function providerPicker(initial) {
  const sel = h('select', { id: 'provider', 'aria-label': 'Model provider' }, providers.map((p) =>
    h('option', { value: p.id, disabled: !p.available, selected: p.id === initial }, p.label + (p.available ? '' : ' (unavailable)'))));
  const model = h('input', { type: 'text', id: 'model', placeholder: 'Default model', list: 'models', 'aria-label': 'Model name' });
  const dl = h('datalist', { id: 'models' });
  const note = h('div', { class: 'hint' });
  const sync = () => {
    const p = providers.find((x) => x.id === sel.value);
    dl.replaceChildren(...(p.models || []).map((m) => h('option', { value: m })));
    model.disabled = p.id === 'rules';
    if (p.id === 'rules') model.value = '';
    note.textContent = p.detail;
  };
  sel.addEventListener('change', sync); sync();
  return { sel, model, dl, note, value: () => ({ provider: sel.value, model: model.value.trim() || null }) };
}

/* ---------- pages ---------- */
async function pageOverview() {
  const [stats, reviews] = await Promise.all([api('/api/stats'), api('/api/reviews?limit=15')]);
  const view = h('div', {});
  const seed = h('button', { class: 'btn' }, 'Load sample pull requests');
  seed.addEventListener('click', busy(seed, async () => { await api('/api/demo/seed', { method: 'POST' }); toast('Sample reviews loaded'); render(); }));
  view.append(h('div', { class: 'page-head' },
    h('div', {}, h('h1', {}, 'Overview'), h('p', { class: 'sub' }, 'What CodeWarden has reviewed and found across your pull requests.')),
    h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '#/new' }, icon('plus'), 'New review'))));
  if (!stats.reviews) {
    view.append(emptyState('No reviews yet', 'Review a diff or a GitHub pull request to see findings here. Want to explore first? Load the bundled sample pull requests to explore.',
      h('a', { class: 'btn primary', href: '#/new' }, 'Start a review'), seed));
    return view;
  }
  const hi = stats.by_severity.critical + stats.by_severity.high;
  view.append(h('div', { class: 'card strip' },
    ...[[stats.reviews, 'Reviews'], [stats.findings, 'Findings'], [hi, 'Critical + high'], [fmtMs(stats.avg_duration_ms), 'Avg review time']].map(([n, l]) =>
      h('div', {}, h('div', { class: 'kpi-n' }, n), h('div', { class: 'kpi-l' }, l)))));
  const maxCat = Math.max(1, ...Object.values(stats.by_category));
  view.append(h('div', { class: 'grid-2', style: 'margin-bottom:16px' },
    h('div', { class: 'card card-pad' }, h('h2', {}, 'Findings by severity'),
      h('div', { class: 'barlist' }, SEV.map((s) => h('div', { class: 'bar-row' }, h('span', {}, sevBadge(s)),
        h('div', { class: 'bar-track' }, h('div', { class: 'bar-fill sev-' + s, style: `width:${(stats.by_severity[s] / Math.max(1, stats.findings)) * 100}%` })),
        h('span', { class: 'v' }, stats.by_severity[s])))),
      h('h2', { style: 'margin-top:20px' }, 'By category'),
      h('div', { class: 'barlist' }, Object.entries(stats.by_category).map(([c, n]) => h('div', { class: 'bar-row' }, h('span', {}, cap(c)),
        h('div', { class: 'bar-track' }, h('div', { class: 'bar-fill', style: `width:${(n / maxCat) * 100}%` })), h('span', { class: 'v' }, n))))),
    h('div', { class: 'card card-pad' }, h('h2', {}, 'Most common issues'),
      h('div', { class: 'list' }, stats.top_issues.map((t) => h('div', {}, h('span', {}, t.title), h('span', { class: 'row' }, sevBadge(t.severity), h('b', {}, '×' + t.count))))),
      h('h2', { style: 'margin-top:20px' }, 'Files with the most findings'),
      h('div', { class: 'list' }, stats.hot_files.map((f) => h('div', {}, h('code', {}, f.path), h('b', {}, f.count)))))));
  view.append(h('div', { class: 'card' }, h('div', { class: 'card-pad', style: 'padding-bottom:4px' }, h('h2', {}, 'Recent reviews')),
    h('div', { class: 'table-wrap' }, h('table', { class: 't' },
      h('thead', {}, h('tr', {}, ...['Review', 'Source', 'Model', 'Files', 'Findings', ''].map((c) => h('th', {}, c)))),
      h('tbody', {}, reviews.map((r) => h('tr', { class: 'link', tabindex: 0, onclick: () => (location.hash = '#/reviews/' + r.id), onkeydown: (e) => { if (e.key === 'Enter') location.hash = '#/reviews/' + r.id; } },
        h('td', {}, h('div', {}, h('b', {}, r.title)), h('div', { class: 'hint' }, ago(r.created_at) + (r.repo ? ' · ' + r.repo + (r.pr_number ? '#' + r.pr_number : '') : ''))),
        h('td', {}, h('span', { class: 'badge plain' }, SOURCE_LABEL[r.source] || r.source)),
        h('td', {}, r.provider + (r.model ? ' / ' + r.model : '')),
        h('td', { class: 'num' }, r.n_files),
        h('td', { style: 'min-width:150px' }, h('div', { class: 'row' }, sevBar(r.by_severity), h('b', {}, r.n_findings))),
        h('td', {}, r.posted ? h('span', { class: 'badge ok' }, 'posted') : null))))))));
  return view;
}

async function pageNew() {
  if (!providers) await loadMeta();
  const samples = await api('/api/samples');
  const pick = providerPicker(defaultProvider());
  let mode = 'diff';
  const diff = h('textarea', { id: 'diff', placeholder: 'Paste the output of `git diff` here', spellcheck: 'false', 'aria-label': 'Unified diff' });
  const url = h('input', { type: 'text', id: 'pr', placeholder: 'https://github.com/owner/repo/pull/123', 'aria-label': 'Pull request URL' });
  const sample = h('select', { id: 'sample', 'aria-label': 'Sample' }, samples.map((s) => h('option', { value: s.id }, `${s.group}: ${s.label}`)));
  const rag = h('input', { type: 'checkbox', id: 'rag', checked: true });
  const panes = { diff: h('div', { class: 'field' }, h('label', { for: 'diff' }, 'Unified diff'), diff),
    pr: h('div', { class: 'field' }, h('label', { for: 'pr' }, 'Pull request URL'), url,
      h('div', { class: 'hint' }, 'Public repositories work as is. Private ones need GITHUB_TOKEN on the server.')),
    sample: h('div', { class: 'field' }, h('label', { for: 'sample' }, 'Bundled sample'), sample,
      h('div', { class: 'hint' }, samples.length ? 'Sample pull requests and the seeded-bug cases used for evaluation.' : 'No samples found. Run from the repository root.')) };
  const body = h('div', {});
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Diff source' });
  const setMode = (m) => {
    mode = m; body.replaceChildren(panes[m]);
    [...seg.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.m === m)));
  };
  [['diff', 'Paste diff'], ['pr', 'GitHub PR'], ['sample', 'Sample']].forEach(([m, l]) => seg.append(h('button', { type: 'button', 'data-m': m, onclick: () => setMode(m) }, l)));
  setMode(samples.length ? 'sample' : 'diff');
  const run = h('button', { class: 'btn primary', type: 'button' }, 'Run review');
  run.addEventListener('click', busy(run, async () => {
    const payload = { source: mode, ...pick.value(), rag: rag.checked };
    if (mode === 'diff') payload.diff = diff.value;
    if (mode === 'pr') payload.pr_url = url.value;
    if (mode === 'sample') payload.sample = sample.value;
    try { const rv = await api('/api/reviews', { method: 'POST', body: payload }); location.hash = '#/reviews/' + rv.id; }
    catch (e) { toast(e.message, true); }
  }));
  return h('div', {},
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'New review'), h('p', { class: 'sub' }, 'Run the same pipeline the GitHub Action uses, and inspect the result before anything is posted.'))),
    h('div', { class: 'grid-2', style: 'grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)' },
      h('div', { class: 'card card-pad' }, seg, body),
      h('div', { class: 'card card-pad' }, h('h2', {}, 'Settings'),
        h('div', { class: 'field' }, h('label', { for: 'provider' }, 'Reviewer'), pick.sel, pick.note),
        h('div', { class: 'field' }, h('label', { for: 'model' }, 'Model'), pick.model, pick.dl),
        h('label', { class: 'check', for: 'rag', style: 'margin-bottom:16px' }, rag,
          h('span', {}, h('b', {}, 'Use repository context (RAG)'), h('div', { class: 'hint' }, `Retrieves related code from ${config.repo_root}/ so the model sees helpers and conventions, not just the diff.`))),
        run)));
}

function buildMarkdown(rv) {
  const f = rv.result.findings;
  const lines = [`## CodeWarden review: ${rv.title}`, '', f.length ? `${f.length} finding(s)` : 'No issues found.', ''];
  f.forEach((x) => lines.push(`- **[${x.severity.toUpperCase()}]** \`${x.path}:${x.line}\` ${x.title}: ${x.explanation}`));
  return lines.join('\n');
}

async function pageReview(id) {
  if (!config) await loadMeta();
  const rv = await api('/api/reviews/' + id);
  const findings = rv.result.findings;
  const skipped = rv.result.files_skipped;
  const byFile = {};
  findings.forEach((f) => (byFile[f.path] = byFile[f.path] || []).push(f));
  const counts = Object.fromEntries(SEV.map((s) => [s, findings.filter((f) => f.severity === s).length]));
  const active = new Set(SEV);
  const filesEl = h('div', {});

  const findingCard = (f) => h('div', { class: 'finding ' + f.severity },
    h('div', { class: 'meta' }, sevBadge(f.severity), h('span', { class: 'badge plain' }, cap(f.category)), h('span', { class: 'hint' }, `confidence ${Math.round(f.confidence * 100)}%`)),
    h('h3', {}, f.title), h('p', {}, f.explanation),
    f.suggestion ? h('div', { class: 'fix' }, h('b', {}, 'Suggested fix: '), f.suggestion) : null,
    f.replacement ? h('div', { class: 'suggest', 'aria-label': 'Suggested replacement' }, h('div', { class: 'm' }, '- ' + f.line_text), h('div', { class: 'p' }, '+ ' + f.replacement)) : null,
    f.replacement ? h('div', { style: 'margin-top:6px' }, h('button', { class: 'btn small', onclick: () => copy(f.replacement) }, 'Copy replacement')) : null);

  function renderFiles() {
    filesEl.replaceChildren();
    const shown = rv.files.filter((f) => !(f.path in skipped));
    shown.forEach((file) => {
      const fs = (byFile[file.path] || []).filter((f) => active.has(f.severity));
      const anchored = {};
      fs.filter((f) => f.anchored).forEach((f) => (anchored[f.line] = anchored[f.line] || []).push(f));
      const loose = fs.filter((f) => !f.anchored);
      const refs = rv.result.context_used[file.path] || [];
      const rows = [];
      file.hunks.forEach((hk) => {
        rows.push(h('tr', { class: 'hunk' }, h('td', { colspan: 4 }, hk.header)));
        hk.lines.forEach((ln) => {
          const hit = ln.k !== '-' && anchored[ln.n];
          rows.push(h('tr', { class: (ln.k === '+' ? 'add' : ln.k === '-' ? 'del' : '') + (hit ? ' flag' : '') },
            h('td', { class: 'ln' }, ln.o == null ? '' : ln.o), h('td', { class: 'ln' }, ln.n == null ? '' : ln.n),
            h('td', { class: 'sg' }, ln.k === ' ' ? '' : ln.k), h('td', { class: 'code' }, ln.t)));
          if (hit) rows.push(h('tr', {}, h('td', { colspan: 4, class: 'fcell' }, anchored[ln.n].map(findingCard))));
        });
      });
      const gen = h('button', { class: 'btn small' }, 'Generate tests');
      gen.addEventListener('click', busy(gen, async () => {
        try {
          const out = await api(`/api/reviews/${rv.id}/tests`, { method: 'POST', body: { path: file.path, provider: rv.provider, model: rv.model || null } });
          modal('Suggested tests for ' + file.path, out.code
            ? [out.filename ? h('p', { class: 'hint' }, 'Suggested file: ' + out.filename) : null, h('pre', { class: 'pre' }, out.code), h('div', { class: 'row', style: 'margin-top:10px' }, h('button', { class: 'btn', onclick: () => copy(out.code) }, 'Copy'))]
            : h('p', {}, out.note || 'Nothing to generate.'));
        } catch (e) { toast(e.message, true); }
      }));
      filesEl.append(h('section', { class: 'card file', id: 'f-' + encodeURIComponent(file.path) },
        h('div', { class: 'file-head' }, h('span', { class: 'path' }, file.path),
          file.is_new ? h('span', { class: 'badge ok' }, 'new') : null,
          fs.length ? h('span', { class: 'badge ' + fs[0].severity }, fs.length + (fs.length === 1 ? ' finding' : ' findings')) : h('span', { class: 'badge plain' }, 'no findings'),
          h('span', { class: 'spacer' }), gen),
        refs.length ? h('details', { class: 'ctx' }, h('summary', {}, `Repository context sent to the model (${refs.length})`), h('div', {}, refs.map((r) => h('code', {}, r)))) : null,
        loose.length ? h('div', { class: 'fcell', style: 'padding-left:14px!important' }, h('div', { class: 'hint' }, 'Outside the changed lines (not postable inline)'), loose.map(findingCard)) : null,
        h('div', { class: 'table-wrap' }, h('table', { class: 'diff' }, h('tbody', {}, rows)))));
    });
    if (!shown.length) filesEl.append(emptyState('Nothing to show', 'Every file in this change was skipped.'));
  }

  const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Filter by severity' }, SEV.map((s) =>
    h('button', { class: 'chip', type: 'button', 'aria-pressed': 'true', onclick: (e) => {
      active.has(s) ? active.delete(s) : active.add(s);
      e.currentTarget.setAttribute('aria-pressed', String(active.has(s))); renderFiles();
    } }, sevBadge(s), counts[s])));

  const post = h('button', { class: 'btn' }, 'Post to GitHub');
  post.addEventListener('click', busy(post, async () => {
    if (!confirm(`Publish ${findings.filter((f) => f.anchored).length} inline comment(s) on ${rv.repo}#${rv.pr_number}? They will appear under the server's GitHub token.`)) return;
    try { const r = await api(`/api/reviews/${rv.id}/post`, { method: 'POST' }); toast(`Posted ${r.posted} comment(s)`); render(); }
    catch (e) { toast(e.message, true); }
  }));
  const del = h('button', { class: 'btn danger' }, 'Delete');
  del.addEventListener('click', async () => { if (confirm('Delete this review?')) { await api('/api/reviews/' + rv.id, { method: 'DELETE' }); location.hash = '#/'; } });

  renderFiles();
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('a', { href: '#/' }, '← Overview'), h('h1', { style: 'margin-top:6px' }, rv.title),
        h('p', { class: 'sub row' }, h('span', { class: 'badge plain' }, SOURCE_LABEL[rv.source] || rv.source),
          rv.repo ? h('span', {}, rv.repo + (rv.pr_number ? '#' + rv.pr_number : '')) : null,
          h('span', {}, rv.provider + (rv.model ? ' / ' + rv.model : '')),
          h('span', { class: 'badge plain', title: 'Repository context retrieval' }, rv.rag ? 'RAG on' : 'RAG off'),
          h('span', {}, `${fmtMs(rv.duration_ms)} · ${rv.requests} model call(s) · ${ago(rv.created_at)}`))),
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => copy(buildMarkdown(rv)) }, 'Copy summary'),
        rv.repo && rv.pr_number && config.github_token && findings.length && !rv.posted ? post : null, del)),
    rv.result.errors.length ? h('div', { class: 'banner err' }, h('b', {}, 'Some requests failed: '), rv.result.errors.join(' | ')) : null,
    h('div', { class: 'card card-pad row', style: 'margin-bottom:16px' },
      h('div', {}, h('div', { class: 'kpi-n' }, findings.length), h('div', { class: 'kpi-l' }, findings.length === 1 ? 'finding' : 'findings')),
      h('div', { class: 'spacer' }), findings.length ? chips : h('span', { class: 'badge ok' }, 'No issues found'),
      rv.result.dropped.over_cap || rv.result.dropped.duplicates ? h('span', { class: 'hint' }, `${rv.result.dropped.over_cap} over the comment cap, ${rv.result.dropped.duplicates} already reported`) : null),
    h('div', { class: 'review-layout' },
      h('nav', { class: 'card filelist', 'aria-label': 'Files' }, rv.files.map((f) => {
        const n = (byFile[f.path] || []).length;
        return h('a', { href: '#/reviews/' + rv.id, onclick: (e) => { e.preventDefault(); const t = document.getElementById('f-' + encodeURIComponent(f.path)); if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, style: f.path in skipped ? 'opacity:.5' : '' },
          h('span', { class: 'p', title: f.path }, '‎' + f.path), n ? h('b', {}, n) : null);
      })),
      h('div', {}, filesEl,
        Object.keys(skipped).length ? h('details', { class: 'card card-pad' }, h('summary', {}, `${Object.keys(skipped).length} file(s) skipped`),
          h('div', { class: 'list', style: 'margin-top:8px' }, Object.entries(skipped).map(([p, why]) => h('div', {}, h('code', {}, p), h('span', { class: 'hint' }, why))))) : null)));
}

async function pageEval() {
  if (!providers) await loadMeta();
  const runs = await api('/api/eval');
  const pick = providerPicker(providers.find((p) => p.id !== 'rules' && p.available) ? defaultProvider() : 'rules');
  const run = h('button', { class: 'btn primary' }, 'Run evaluation');
  run.addEventListener('click', busy(run, async () => {
    try { await api('/api/eval', { method: 'POST', body: pick.value() }); toast('Evaluation complete'); render(); }
    catch (e) { toast(e.message, true); }
  }));
  const view = h('div', {}, h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Evaluation'),
    h('p', { class: 'sub' }, 'Score a reviewer on seeded-bug diffs with known answers. A finding is a hit if it lands within 2 lines of a planted bug.')),
    h('div', { class: 'row' }, h('div', { style: 'width:210px' }, pick.sel), h('div', { style: 'width:190px' }, pick.model), pick.dl, run)),
    h('p', { class: 'hint', style: 'margin-top:-8px' }, pick.note));
  if (!runs.length) { view.append(emptyState('No evaluation runs yet', 'Run the evaluation to compare reviewers. Start with the offline baseline, then try a real model.')); return view; }
  const latest = new Map();
  runs.forEach((r) => { const k = r.provider + '|' + r.model; if (!latest.has(k)) latest.set(k, r); });
  view.append(h('div', { class: 'card card-pad', style: 'margin-bottom:16px' }, h('h2', {}, 'Latest run per reviewer'),
    h('div', { class: 'barlist' }, [...latest.values()].map((r) => h('div', {},
      h('div', { class: 'row', style: 'margin-bottom:4px' }, h('b', {}, r.provider + (r.model ? ' / ' + r.model : '')), h('span', { class: 'hint' }, `${r.false_positives} false positive(s) · ${ago(r.created_at)}`)),
      ...[['Precision', r.precision], ['Recall', r.recall]].map(([l, v]) => h('div', { class: 'bar-row', style: 'grid-template-columns:80px minmax(0,1fr) 44px' }, h('span', {}, l),
        h('div', { class: 'bar-track' }, h('div', { class: 'bar-fill', style: `width:${(v || 0) * 100}%` })), h('span', { class: 'v' }, pct(v)))))))));
  const sel = runs[0];
  view.append(h('div', { class: 'card' }, h('div', { class: 'card-pad', style: 'padding-bottom:4px' }, h('h2', {}, `Cases from the latest run (${sel.provider}${sel.model ? ' / ' + sel.model : ''})`)),
    h('div', { class: 'table-wrap' }, h('table', { class: 't' }, h('thead', {}, h('tr', {}, ...['Case', 'Planted bug', 'Reviewer found', 'Result'].map((c) => h('th', {}, c)))),
      h('tbody', {}, sel.cases.map((c) => {
        const trap = c.expected === 0;
        const ok = trap ? c.findings === 0 : c.matched === c.expected && c.findings === c.true_positive_findings;
        const label = trap ? (c.findings === 0 ? 'Clean' : 'False alarm') : (c.matched ? (ok ? 'Found' : 'Found + extra') : 'Missed');
        return h('tr', {}, h('td', {}, h('b', {}, c.name.replace(/_/g, ' '))), h('td', { class: 'hint' }, c.expected_desc), h('td', { class: 'hint' }, c.found_desc),
          h('td', {}, h('span', { class: 'badge ' + (ok ? 'ok' : trap ? 'high' : c.matched ? 'medium' : 'critical') }, label)));
      }))))));
  return view;
}

async function pageAsk() {
  if (!providers) await loadMeta();
  const pick = providerPicker(defaultProvider());
  const q = h('input', { type: 'search', placeholder: 'e.g. How should I run a database query safely?', 'aria-label': 'Question', style: 'flex:1;min-width:240px' });
  const out = h('div', { style: 'margin-top:16px' });
  const go = h('button', { class: 'btn primary' }, 'Ask');
  const doAsk = busy(go, async () => {
    out.replaceChildren(skeleton(3));
    try {
      const r = await api('/api/ask', { method: 'POST', body: { question: q.value, ...pick.value() } });
      out.replaceChildren(h('div', {},
        r.error ? h('div', { class: 'banner err' }, r.error) : null,
        r.answer ? h('div', { class: 'card card-pad' }, h('h2', {}, 'Answer'), h('div', { class: 'answer' }, r.answer)) : null,
        h('div', { class: 'card card-pad', style: 'margin-top:12px' }, h('h2', {}, `Retrieved code (${r.sources.length})`),
          r.sources.map((s, i) => h('details', { class: 'src', open: i === 0 }, h('summary', {}, `${s.path}:${s.start}-${s.end}`), h('pre', { class: 'pre' }, s.text))))));
    } catch (e) { out.replaceChildren(); toast(e.message, true); }
  });
  go.addEventListener('click', doAsk);
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
  return h('div', {}, h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Ask the repository'),
    h('p', { class: 'sub' }, `Retrieval-augmented Q&A over ${config.repo_root}/. With the offline reviewer you see only the retrieved code, which is exactly what a model would receive as context.`))),
    h('div', { class: 'card card-pad' }, h('div', { class: 'row' }, q, h('div', { style: 'width:200px' }, pick.sel), h('div', { style: 'width:180px' }, pick.model), pick.dl, go), h('div', { class: 'hint', style: 'margin-top:8px' }, pick.note)),
    out);
}

async function pageSettings() {
  await loadMeta();
  const health = await api('/api/health');
  const row = (k, v) => h('div', {}, h('span', {}, k), h('span', { class: 'mono' }, String(v)));
  return h('div', {}, h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Settings'), h('p', { class: 'sub' }, 'Read-only view of how this server is configured. Change it with environment variables and .codewarden.yml.'))),
    h('div', { class: 'grid-2' },
      h('div', { class: 'card card-pad' }, h('h2', {}, 'Model providers'),
        h('div', { class: 'list' }, providers.map((p) => h('div', {}, h('span', { class: 'row' }, h('span', { class: 'dot ' + (p.available ? 'on' : 'off') }), h('b', {}, p.label)), h('span', { class: 'hint' }, p.detail))))),
      h('div', { class: 'card card-pad' }, h('h2', {}, 'Pipeline'),
        h('div', { class: 'list' }, row('Indexed repository', config.repo_root + '/'), row('RAG backend', config.rag.backend), row('Chunker', config.rag.chunker), row('Top-k context chunks', config.rag.top_k),
          row('Min severity', config.min_severity), row('Min confidence', config.min_confidence), row('Comment cap', config.max_comments), row('Redact secrets', config.redact_secrets))),
      h('div', { class: 'card card-pad' }, h('h2', {}, 'GitHub'),
        h('div', { class: 'list' }, h('div', {}, h('span', {}, 'GITHUB_TOKEN (posting + private repos)'), h('span', { class: 'badge ' + (config.github_token ? 'ok' : '') }, config.github_token ? 'set' : 'not set')),
          h('div', {}, h('span', {}, 'Webhook endpoint'), h('code', {}, '/webhook/github')),
          h('div', {}, h('span', {}, 'GITHUB_WEBHOOK_SECRET'), h('span', { class: 'badge ' + (config.webhook ? 'ok' : '') }, config.webhook ? 'set' : 'not set')))),
      h('div', { class: 'card card-pad' }, h('h2', {}, 'Server'),
        h('div', { class: 'list' }, row('Version', health.version), row('Access token required', health.auth_required),
          h('div', {}, h('span', {}, 'Sample data'), h('button', { class: 'btn small danger', onclick: async () => { await api('/api/demo', { method: 'DELETE' }); toast('Sample reviews removed'); } }, 'Remove sample reviews'))))));
}

/* ---------- router ---------- */
const NAV = [['#/', 'Overview', 'grid'], ['#/new', 'New review', 'plus'], ['#/eval', 'Evaluation', 'flask'], ['#/ask', 'Ask the repo', 'search'], ['#/settings', 'Settings', 'gear']];
function drawNav() {
  const cur = location.hash.startsWith('#/reviews/') ? '#/' : (location.hash || '#/');
  $('#nav').replaceChildren(...NAV.map(([href, label, ic]) => h('a', { href, 'aria-current': href === cur ? 'page' : false }, icon(ic), label)));
}
async function render() {
  document.body.classList.remove('nav-open');
  drawNav();
  const view = $('#view');
  const hash = location.hash || '#/';
  view.replaceChildren(skeleton());
  try {
    if (!config) { await loadMeta(); }
    let page;
    if (hash === '#/') page = await pageOverview();
    else if (hash === '#/new') page = await pageNew();
    else if (hash === '#/eval') page = await pageEval();
    else if (hash === '#/ask') page = await pageAsk();
    else if (hash === '#/settings') page = await pageSettings();
    else if (/^#\/reviews\/\d+$/.test(hash)) page = await pageReview(hash.split('/')[2]);
    else page = emptyState('Page not found', 'That address does not exist.', h('a', { class: 'btn', href: '#/' }, 'Go to overview'));
    view.replaceChildren(page);
    window.scrollTo(0, 0);
  } catch (e) {
    view.replaceChildren(h('div', { class: 'banner err' }, e.message), h('button', { class: 'btn', onclick: render }, 'Try again'));
  }
}
$('#menu').addEventListener('click', () => document.body.classList.toggle('nav-open'));
$('#theme').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('cw_theme', next); } catch (_) { /* storage unavailable */ }
});
try {
  const saved = localStorage.getItem('cw_theme');
  if (saved) document.documentElement.dataset.theme = saved;
  else if (matchMedia('(prefers-color-scheme: dark)').matches) document.documentElement.dataset.theme = 'dark';
} catch (_) { /* storage unavailable */ }
window.addEventListener('hashchange', render);
api('/api/health').then((h2) => { $('#version').textContent = 'v' + h2.version; }).catch(() => {});
render();
})();
