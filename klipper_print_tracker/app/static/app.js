"use strict";
// Hash routing keeps every URL relative, so the page works under any ingress prefix.
const view = document.getElementById("view");
const ROUTE = /\/(job|compare|part|preset)\/[^?#]+$/;
const S = window.S;
let currency = "";

const e = (value) => String(value ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;
const api = async (path) => {
  const response = await fetch(`api/${path}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const money = (value) => `${e(value ?? 0)} ${e(currency)}`;
const time = (minutes) => {
  const m = Math.round(minutes || 0);
  return `${Math.floor(m / 60)} ${S.hours} ${m % 60} ${S.minutes}`;
};
const statusLabel = (status) => `<span class="${e(status)}">${e(S[`status_${status}`] ?? status)}</span>`;
const stat = (label, value) => `<div class="stat"><b>${e(value)}</b><span>${e(label)}</span></div>`;
const cell = (label, html, cls = "") => `<td data-l="${e(label)}" class="${cls}">${html}</td>`;

function table(headers, rows) {
  if (!rows.length) return `<p class="muted">${S.empty}</p>`;
  const head = headers.map(([label, cls]) => `<th class="${cls || ""}">${e(label)}</th>`).join("");
  return `<table class="rows"><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function jobRow(j) {
  const parts = `${e(j.parts)}${j.planned ? `/${e(j.planned)}` : ""}${j.excluded ? ` <span title="${S.excluded_mark}">⚠️</span>` : ""}`;
  return `<tr>
    <td data-l="">${j.thumbnail ? `<img class="thumb" loading="lazy" alt="" src="${e(j.thumbnail)}">` : ""}</td>
    ${cell(S.col_date, e(j.date))}
    ${cell(S.col_file, `<a href="#/job/${enc(j.job_id)}">${e(j.file)}</a>${j.changed ? ` <span class="badge">${S.badge_changed}</span>` : ""}`)}
    ${cell(S.col_status, statusLabel(j.status))}
    ${cell(S.col_parts, parts, "num")}
    ${cell(S.col_time, time(j.minutes), "num")}
    ${cell(S.col_grams, e(j.grams), "num")}
    ${cell(S.col_cost, money(j.cost), "num")}
    ${cell(S.col_per_part, j.per_part ? money(j.per_part) : "-", "num")}
    ${cell(S.col_spool, e(j.spool))}
  </tr>`;
}
const JOB_HEADERS = [[""], [S.col_date], [S.col_file], [S.col_status], [S.col_parts, "num"], [S.col_time, "num"],
  [S.col_grams, "num"], [S.col_cost, "num"], [S.col_per_part, "num"], [S.col_spool]];

const partLink = (name) => `<a href="#/part/${enc(name)}">${e(name)}</a>`;

async function home() {
  const d = await api("stats");
  currency = d.currency;
  view.innerHTML = `
    <div class="stats">
      ${stat(S.stat_prints, d.total)}${stat(S.stat_success, `${d.success_rate}%`)}${stat(S.stat_parts, d.parts)}
      ${stat(S.stat_filament, d.filament_kg)}${stat(S.stat_energy, d.kwh)}
      ${stat(S.stat_cost, `${d.total_cost} ${d.currency}`)}${stat(S.stat_wasted, `${d.wasted_cost} ${d.currency}`)}
    </div>
    <div class="card"><h2>${S.last_prints}</h2>${table(JOB_HEADERS, d.recent.map(jobRow))}</div>
    <div class="cols">
      <div class="card"><h2>${S.top_parts}</h2>${table([[S.col_part], [S.col_count, "num"]], d.top_parts.map((p) =>
        `<tr>${cell(S.col_part, partLink(p.name))}${cell(S.col_count, e(p.count), "num")}</tr>`))}</div>
      <div class="card"><h2>${S.top_excluded}</h2>${table([[S.col_part], [S.col_count, "num"], [S.col_rate, "num"]], d.top_excluded.map((p) =>
        `<tr>${cell(S.col_part, partLink(p.name))}${cell(S.col_count, e(p.count), "num")}${cell(S.col_rate, `${e(p.rate)}%`, "num")}</tr>`))}</div>
    </div>`;
}

const PAGE = 50;
async function prints() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const query = (extra = {}) => new URLSearchParams({ ...Object.fromEntries(params), ...extra }).toString();
  const limit = Number(params.get("limit")) || PAGE;
  const d = await api(`jobs?${query({ limit })}`);
  currency = d.currency;
  const option = (value, label, selected) =>
    `<option value="${e(value)}"${value === selected ? " selected" : ""}>${e(label)}</option>`;
  const select = (name, label, items) => `<label>${label}<select name="${name}">
    ${option("", S.filter_all, params.get(name) || "")}${items.map(([v, l]) => option(v, l, params.get(name))).join("")}</select></label>`;
  const input = (name, label, type) =>
    `<label>${label}<input type="${type}" name="${name}" value="${e(params.get(name) || "")}"></label>`;
  view.innerHTML = `
    <h1>${S.nav_prints}</h1>
    <div class="card"><form class="filters" id="filters">
      ${input("file", S.filter_file, "search")}
      ${select("status", S.filter_status, ["completed", "cancelled", "error"].map((s) => [s, S[`status_${s}`]]))}
      ${select("preset", S.filter_preset, d.facets.presets.map((p) => [p.name, p.name]))}
      ${select("spool", S.filter_spool, d.facets.spools.map((s) => [s, s]))}
      ${input("from", S.filter_from, "date")}${input("to", S.filter_to, "date")}
      <button>${S.filter_apply}</button>
      <a href="api/jobs.csv?${e(query())}" download>${S.csv}</a>
    </form></div>
    <div class="card">
      <p class="muted">${S.total}: ${e(d.total)}</p>
      ${table(JOB_HEADERS, d.jobs.map(jobRow))}
      ${d.total > d.jobs.length ? `<button id="more">${S.more}</button>` : ""}
    </div>`;
  document.getElementById("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...new FormData(event.target)].filter(([, v]) => v);
    location.hash = `#/prints?${new URLSearchParams(values)}`;
  });
  document.getElementById("more")?.addEventListener("click", () => {
    location.hash = `#/prints?${query({ limit: limit + PAGE })}`;
  });
}

function value(v) {
  if (v.raw === null || v.raw === undefined) return `<span class="muted">-</span>`;
  if (v.flags) return e(v.flags.map((f) => (f ? S.yes : S.no)).join(", "));
  const text = v.text ?? v.raw;
  return text === "" ? `<span class="muted">${S.value_empty}</span>` : `<span class="val">${e(text)}</span>`;
}
const keyCell = (r) => `<span class="key">${e(r.label)}${r.unit ? `, ${e(r.unit)}` : ""}</span>
  ${r.tooltip ? `<div class="tip">${e(r.tooltip)}</div>` : ""}`;

function tabsHtml(tabs, rowHtml) {
  const groupHtml = (page) => page.groups.map((g) => `
    ${g.title ? `<h3>${e(g.title)}</h3>` : ""}<table><tbody>${g.rows.map(rowHtml).join("")}</tbody></table>`).join("");
  const panels = tabs.map((tab, i) => `<div data-panel="${i}"${i ? " hidden" : ""}>
    ${tab.pages.map((page) => `${page.title ? `<h2>${e(page.title)}</h2>` : ""}${groupHtml(page)}`).join("")}</div>`);
  const buttons = tabs.map((tab, i) =>
    `<button type="button" data-tab="${i}" class="${i ? "" : "on"}">${e(S[`tab_${tab.id}`])}</button>`);
  return `<div class="tabs">${buttons.join("")}</div>${panels.join("")}`;
}

function bindTabs() {
  view.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
    view.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b === button));
    view.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== button.dataset.tab; });
  }));
  view.querySelectorAll(".key").forEach((key) => key.addEventListener("click", () =>
    key.closest("tr").classList.toggle("open")));
}

const diffRow = (r) => `<tr><td>${keyCell(r)}</td><td><del>${value(r.old)}</del></td><td><ins>${value(r.new)}</ins></td></tr>`;

function changeBlock(kind, change) {
  const title = S[`vs_${kind}`];
  if (!change) return `<h3>${title}</h3><p class="muted">${S.no_baseline}</p>`;
  const link = `<a href="#/job/${enc(change.job_id)}">${e(change.file || change.job_id)}</a>`;
  return `<h3>${title} (${link})</h3>${change.diff.length
    ? `<table><tbody>${change.diff.map(diffRow).join("")}</tbody></table>` : `<p class="muted">${S.no_changes}</p>`}`;
}

async function jobPage(id) {
  const j = await api(`job/${enc(id)}`);
  currency = j.currency;
  const row = (label, html) => `<dt>${e(label)}</dt><dd>${html}</dd>`;
  const parts = (names) => Object.entries(names || {}).map(([n, c]) => `${partLink(n)} x${e(c)}`).join(", ") || "-";
  const presets = Object.entries(j.presets).flatMap(([kind, names]) => names.map((name) => {
    const drift = j.drift[`${kind}/${name}`];
    return `<dt>${S[`kind_${kind}`]}</dt><dd><a href="#/preset/${kind}/${enc(name)}">${e(name)}</a>
      <span class="badge">${drift ? `${S.drift}: ${drift.map((d) => e(d.label)).join(", ")}` : S.drift_none}</span></dd>`;
  })).join("");
  const others = (await api("jobs?limit=100")).jobs.filter((o) => o.job_id !== j.job_id);
  view.innerHTML = `
    <h1>${statusLabel(j.status)} ${e(j.file)}</h1>
    <div class="card">
      ${j.thumbnail ? `<img class="big" alt="" src="${e(j.thumbnail)}">` : ""}
      ${j.live_data ? "" : `<p class="note">${S.best_effort}</p>`}
      <dl>
        ${row(S.col_date, e(j.date))}${row(S.duration, time(j.minutes))}
        ${row(S.planned, e(j.planned))}${row(S.printed, parts(j.printed))}${row(S.excluded, parts(j.excluded))}
        ${row(S.filament, `${e(j.grams)} г (${e(j.filament_mm)} мм)`)}${row(S.spool, e(j.spool || "-"))}
        ${row(S.energy, j.kwh === null ? "-" : `${e(j.kwh)} кВт·год`)}${row(S.energy_cost, money(j.energy_cost))}
        ${row(S.filament_cost, money(j.filament_cost))}${row(S.total_cost, money(j.total_cost))}
        ${row(S.per_part, j.per_part ? money(j.per_part) : "-")}${j.wasted_cost ? row(S.wasted, money(j.wasted_cost)) : ""}
        ${j.slicer ? row(S.slicer, `${e(j.slicer)} ${e(j.slicer_version)}`) : ""}
        ${j.commit ? row(S.commit, `<code>${e(j.commit.slice(0, 8))}</code>`) : ""}
      </dl>
    </div>
    ${j.config_missing ? `<p class="note">${S.config_missing}</p>` : `
    <div class="card"><h2>${S.presets}</h2><dl>${presets}</dl></div>
    <div class="card"><h2>${S.changes}</h2>
      ${["file", "process", "filament"].map((k) => changeBlock(k, j.changes[k])).join("")}
      <h3>${S.compare_with}</h3>
      <select id="compare"><option value="">${S.compare_with}</option>
      ${others.map((o) => `<option value="${e(o.job_id)}">${e(o.date)} ${e(o.file)}</option>`).join("")}</select>
    </div>
    <div class="card"><h2>${S.settings}</h2>
      ${tabsHtml(j.settings, (r) => `<tr><td>${keyCell(r)}</td><td>${value(r)}</td></tr>`)}</div>`}`;
  bindTabs();
  document.getElementById("compare")?.addEventListener("change", (event) => {
    if (event.target.value) location.hash = `#/compare/${enc(j.job_id)}/${enc(event.target.value)}`;
  });
}

async function comparePage(a, b) {
  const d = await api(`compare/${enc(a)}/${enc(b)}`);
  const link = (j) => `<a href="#/job/${enc(j.job_id)}">${e(j.date)} ${e(j.file)}</a>`;
  view.innerHTML = `<h1>${S.compare}</h1>
    <div class="card"><del>${link(d.a)}</del> &rarr; <ins>${link(d.b)}</ins></div>
    <div class="card">${d.tabs.length ? tabsHtml(d.tabs, (r) =>
      `<tr><td>${keyCell(r)}</td><td><del>${value(r.a)}</del></td><td><ins>${value(r.b)}</ins></td></tr>`)
      : `<p class="muted">${S.compare_same}</p>`}</div>`;
  bindTabs();
}

async function partPage(name) {
  const d = await api(`part/${enc(name)}`);
  currency = d.currency;
  view.innerHTML = `<h1>${S.part}: ${e(d.name)}</h1>
    <div class="stats">${stat(S.printed, d.printed)}${stat(S.excluded, d.excluded)}${stat(S.part_success, `${d.success_rate}%`)}</div>
    <div class="card">${table([[S.col_date], [S.col_file], [S.col_status], [S.printed, "num"], [S.excluded, "num"], [S.col_per_part, "num"], [S.part_changes]],
      d.jobs.slice().reverse().map((j) => `<tr>${cell(S.col_date, e(j.date))}
        ${cell(S.col_file, `<a href="#/job/${enc(j.job_id)}">${e(j.file)}</a>`)}${cell(S.col_status, statusLabel(j.status))}
        ${cell(S.printed, e(j.part_printed), "num")}${cell(S.excluded, e(j.part_excluded), "num")}
        ${cell(S.col_per_part, j.per_part ? money(j.per_part) : "-", "num")}${cell(S.part_changes, e(j.changes.join(", ")))}</tr>`))}</div>`;
}

async function presetPage(kind, name) {
  const d = await api(`preset/${enc(kind)}/${enc(name)}`);
  view.innerHTML = `<h1>${S[`kind_${kind}`]}: ${e(d.name)}</h1>
    <p class="muted">${S.preset_prints}: ${e(d.prints)}</p>
    ${d.timeline.map((t) => `<div class="card">
      <h2><a href="#/job/${enc(t.job_id)}">${e(t.date)} ${e(t.file)}</a></h2>
      ${t.first ? `<p class="muted">${S.preset_first}</p>`
        : `<table><tbody>${t.diff.map(diffRow).join("")}</tbody></table>`}</div>`).join("")}`;
  bindTabs();
}

function setNav(active) {
  document.getElementById("nav").innerHTML = [["#/", S.nav_home, "home"], ["#/prints", S.nav_prints, "prints"]]
    .map(([href, label, id]) => `<a href="${href}" class="${id === active ? "on" : ""}">${label}</a>`).join("");
}

async function render() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [, page, ...rest] = hash.split("?")[0].split("/");
  const args = rest.map(decodeURIComponent);
  setNav(page === "prints" || page === "job" ? "prints" : page ? "" : "home");
  view.innerHTML = `<p class="muted">${S.loading}</p>`;
  window.scrollTo(0, 0);
  try {
    if (page === "job") await jobPage(args[0]);
    else if (page === "prints") await prints();
    else if (page === "compare") await comparePage(args[0], args[1]);
    else if (page === "part") await partPage(args.join("/"));
    else if (page === "preset") await presetPage(args[0], args.slice(1).join("/"));
    else await home();
  } catch (error) {
    view.innerHTML = `<p class="note">${S.error}: ${e(error.message)}</p>`;
  }
}

// Deep links: Home Assistant always loads the panel's root, the wanted page stays in the
// outer URL. The first load reads it directly, later changes arrive as panel properties.
let outerRoute = null;
function followOuter(path) {
  const match = path && path.match(ROUTE);
  if (match && match[0] !== outerRoute) {
    outerRoute = match[0];
    location.hash = `#${match[0]}`;
    return true;
  }
  return false;
}

window.addEventListener("hashchange", render);
if (window.parent !== window) {
  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (event.data?.type === "home-assistant/properties") followOuter(event.data.route?.path);
  });
  window.parent.postMessage({ type: "home-assistant/subscribe-properties" }, "*");
  try {
    if (!location.hash) followOuter(window.parent.location.pathname);
  } catch (error) {
    // Parent on another origin, the list is a fine start page then.
  }
}
render();
