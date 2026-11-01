"use strict";
// Hash routing keeps every URL relative, so the page works under any ingress prefix.
const view = document.getElementById("view");
const toolbarElement = document.getElementById("toolbar");
const ROUTE = /\/(job|compare|part|preset)\/[^?#]+$/;
const S = window.S;
const { e, icon, section, card, heading, tile, badge, empty, thumb } = window.UI;
const enc = encodeURIComponent;
const PAGE_SIZE = 50;

const api = async (path) => {
  const response = await fetch(`api/${path}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

// The selected printer is a viewer's convenience, storage can be unavailable.
let printers = [];
let printer = "";
try {
  printer = localStorage.getItem("printer") || "";
} catch (error) {
  // Keeps the default, all printers.
}
const scoped = (path) => (printer ? `${path}${path.includes("?") ? "&" : "?"}printer=${enc(printer)}` : path);
const printerName = (id) => printers.find((p) => p.id === id)?.name ?? id;

function printerSwitch() {
  if (printers.length < 2) return "";
  const items = printers.map((p) => `<option value="${e(p.id)}"${p.id === printer ? " selected" : ""}>${e(p.name)}</option>`);
  return `<select class="chip ${printer ? "on" : ""}" data-printer aria-label="${S.printer}" title="${S.printer}">
    <option value="">${S.all_printers}</option>${items.join("")}</select>`;
}

function setToolbar({ title = S.app_title, back = false, tab = "", actions = "" }) {
  const tabs = [["#/", S.nav_home, "home"], ["#/prints", S.nav_prints, "prints"]]
    .map(([href, label, id]) => `<a href="${href}" class="${id === tab ? "on" : ""}">${label}</a>`).join("");
  toolbarElement.innerHTML = `
    ${back ? `<a class="icon-button" href="#/prints" title="${S.back}" aria-label="${S.back}">${icon("arrow-left")}</a>` : ""}
    <div class="toolbar-title ellipsis" title="${e(title)}">${e(title)}</div>
    <nav class="toolbar-tabs">${tabs}</nav>
    <div class="toolbar-actions">${printerSwitch()}${actions}</div>`;
}

// --- tables --------------------------------------------------------------

function partsCell(row) {
  const planned = row.planned ? `/${e(row.planned)}` : "";
  const warning = row.excluded
    ? `<span title="${e(row.excluded_names || S.excluded_mark)}">${icon("alert")}</span>` : "";
  return `<span class="parts">${e(row.parts)}${planned}${warning}</span>`;
}

function fileCell(row) {
  const changed = row.changed ? `<span class="muted" title="${S.badge_changed}">${icon("tune-variant", "s18")}</span>` : "";
  return `<div class="file-cell"><a class="ellipsis" href="#/job/${enc(row.ref)}" title="${e(row.file)}">${e(row.file)}</a>${changed}</div>`;
}

const JOB_COLUMNS = [
  { label: "", cls: "icon-cell thumb-cell", cell: (j) => thumb(j.thumbnail) },
  { id: "date", label: S.col_date, cls: "nowrap", cell: (j) => UI.date(j.end_time) },
  { id: "printer", label: S.printer, cls: "nowrap hide-m", cell: (j) => e(printerName(j.printer_id)), multi: true },
  { id: "file", label: S.col_file, cls: "file", cell: fileCell },
  { id: "status", label: S.col_status, cls: "nowrap status-cell", cell: (j) => UI.status(j.status) },
  { id: "parts", label: S.col_parts, cls: "num", cell: partsCell },
  { id: "minutes", label: S.col_time, cls: "num", cell: (j) => UI.duration(j.minutes) },
  { id: "grams", label: S.col_grams, cls: "num hide-m", cell: (j) => UI.grams(j.grams) },
  { id: "cost", label: S.col_cost, cls: "num", cell: (j) => UI.money(j.cost) },
  { id: "per_part", label: S.col_per_part, cls: "num hide-l", cell: (j) => (j.per_part ? UI.money(j.per_part) : "-") },
  { id: "spool", label: S.col_spool, cls: "spool hide-l", cell: (j) => `<div class="ellipsis" title="${e(j.spool)}">${e(j.spool)}</div>` },
  { label: "", cls: "m-only", cell: (j) => `${UI.date(j.end_time)} · ${UI.duration(j.minutes)} · ${UI.money(j.cost)}` },
];

function headerCell(column, sort) {
  if (!sort || !column.id) return `<th class="${column.cls}">${e(column.label)}</th>`;
  const active = sort.column === column.id;
  const direction = active && sort.dir === "desc" ? "asc" : "desc";
  const arrow = active ? icon(sort.dir === "asc" ? "arrow-up" : "arrow-down", "s18") : "";
  return `<th class="${column.cls} ${active ? "sorted" : ""}"><a href="${e(sort.href(column.id, direction))}">${e(column.label)}${arrow}</a></th>`;
}

function dataTable(allColumns, rows, sort) {
  const columns = allColumns.filter((c) => !c.multi || (printers.length > 1 && !printer));
  const head = columns.filter((c) => c.cls !== "m-only").map((c) => headerCell(c, sort)).join("");
  const body = rows.map((row) => `<tr data-href="#/job/${enc(row.ref)}">
    ${columns.map((c) => `<td class="${c.cls}">${c.cell(row)}</td>`).join("")}</tr>`).join("");
  return `<table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// --- home ----------------------------------------------------------------

function partList(items, variable) {
  const top = Math.max(...items.map((p) => p.count));
  return items.map((p) => `<a class="list-row" href="#/part/${enc(p.name)}">
    <span class="ellipsis" title="${e(p.name)}">${e(p.name)}</span>
    <span class="badge count">${UI.number(p.count, 0)}${p.rate !== undefined ? ` · ${UI.number(p.rate, 0)}%` : ""}</span>
    <span class="bar" style="--c:var(${variable})"><i style="width:${(100 * p.count) / top}%"></i></span></a>`).join("");
}

const rescanButton = `<button class="text-button" data-action="rescan">${S.rescan}</button>`;

async function home() {
  setToolbar({ tab: "home" });
  const d = await api(scoped("stats"));
  UI.setCurrency(d.currency);
  printers = d.printers;
  setToolbar({ tab: "home" });
  const allPrints = `<a href="#/prints">${S.all_prints}${icon("chevron-right", "s18")}</a>`;
  return [
    section(`${heading("counter", S.stats)}<div class="tiles six">
      ${tile({ name: S.stat_prints, state: `${UI.number(d.total, 0)} · ${S.stat_breakdown(d.completed, d.cancelled, d.failed)}`, iconName: "printer-3d", variable: "--primary-color", href: "#/prints" })}
      ${tile({ name: S.stat_success, state: `${UI.percent(d.success_rate)} · ${S.stat_success_state(d.completed, d.total)}`, iconName: "check-decagram", variable: "--success-color" })}
      ${tile({ name: S.stat_parts, state: UI.number(d.parts, 0), iconName: "shape-outline", variable: "--info-color" })}
      ${tile({ name: S.stat_filament, state: UI.grams(d.filament_kg * 1000), iconName: "printer-3d-nozzle", variable: "--state-icon-color" })}
      ${tile({ name: S.stat_energy, state: UI.kwh(d.kwh), iconName: "lightning-bolt", variable: "--warning-color" })}
      ${tile({ name: S.stat_cost, state: `${UI.money(d.total_cost)}, ${S.stat_wasted(UI.money(d.wasted_cost))}`, iconName: "cash-multiple", variable: "--accent-color" })}
    </div>`, "span-all"),
    section(`${heading("history", S.last_prints, d.recent.length ? allPrints : "")}
      ${card(d.recent.length ? dataTable(JOB_COLUMNS, d.recent) : empty("printer-3d-nozzle", S.empty_prints, rescanButton))}`, "span-all"),
    `<div class="columns span-all">
      ${section(`${heading("star-outline", S.top_parts)}${card(d.top_parts.length ? partList(d.top_parts, "--primary-color") : empty("shape-outline", S.empty_parts))}`)}
      ${section(`${heading("close-circle-outline", S.top_excluded)}${card(d.top_excluded.length ? partList(d.top_excluded, "--warning-color") : empty("check-circle", S.empty_excluded))}`)}
    </div>`,
  ].join("");
}

// --- prints list ---------------------------------------------------------

const PERIODS = [7, 30, 90, 365];
const listParams = () => new URLSearchParams(location.hash.split("?")[1] || "");

function listHref(changes) {
  const params = listParams();
  params.delete("limit");
  for (const [key, value] of Object.entries(changes)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  return `#/prints${query ? `?${query}` : ""}`;
}

function apiQuery(params) {
  const query = new URLSearchParams(params);
  const days = Number(query.get("period"));
  query.delete("period");
  if (days) query.set("from", new Date(Date.now() - days * 86400000).toISOString().slice(0, 10));
  return query;
}

function selectChip(name, label, options, selected) {
  const items = options.map(([value, text]) =>
    `<option value="${e(value)}"${String(value) === selected ? " selected" : ""}>${e(text)}</option>`).join("");
  return `<select class="chip ${selected ? "on" : ""}" data-filter="${name}" aria-label="${e(label)}" title="${e(label)}">
    <option value="">${e(label)}</option>${items}</select>`;
}

async function prints() {
  const params = listParams();
  const search = `<form class="search" id="search" role="search">
    <button type="button" class="icon-button" data-action="search" aria-label="${S.search}" style="margin-left:-8px">${icon("magnify")}</button>
    <input type="search" name="file" value="${e(params.get("file") || "")}" placeholder="${S.search}" aria-label="${S.search}"></form>`;
  const download = `<a class="icon-button" href="api/jobs.csv?${e(apiQuery(params))}" download title="${S.export_csv}" aria-label="${S.export_csv}">${icon("download")}</a>`;
  setToolbar({ tab: "prints", title: S.nav_prints, actions: search + download });

  const limit = Number(params.get("limit")) || PAGE_SIZE;
  const query = apiQuery(params);
  query.set("limit", limit);
  const d = await api(scoped(`jobs?${query}`));
  UI.setCurrency(d.currency);
  printers = d.printers;
  setToolbar({ tab: "prints", title: S.nav_prints, actions: search + download });

  const status = params.get("status");
  const statusChips = ["completed", "cancelled", "error"].map((value) => {
    const active = status === value;
    return `<a class="chip ${active ? "on" : ""}" href="${e(listHref({ status: active ? "" : value }))}">
      ${UI.statusIcon(value, "s18")}${e(UI.statusLabel(value))}</a>`;
  }).join("");
  const presetNames = [...new Set(d.facets.presets.map((p) => p.name))].map((name) => [name, name]);
  const chips = `<div class="chips">${statusChips}
    ${selectChip("preset", S.filter_preset, presetNames, params.get("preset") || "")}
    ${selectChip("spool", S.filter_spool, d.facets.spools.map((s) => [s, s]), params.get("spool") || "")}
    ${selectChip("period", S.filter_period, PERIODS.map((p) => [p, S[`period_${p}`]]), params.get("period") || "")}</div>`;
  const sort = {
    column: params.get("sort") || "date", dir: params.get("dir") || "desc",
    href: (column, dir) => listHref({ sort: column, dir }),
  };
  const filtered = [...params.keys()].some((k) => !["sort", "dir", "limit"].includes(k));
  const clear = `<a class="text-button" href="#/prints">${S.clear_filters}</a>`;
  const nothing = filtered ? empty("magnify", S.empty_filter, clear) : empty("printer-3d-nozzle", S.empty_prints, rescanButton);
  const more = d.total > d.jobs.length ? `<div class="table-more">
    <a class="text-button" href="${e(`${listHref({})}${listHref({}).includes("?") ? "&" : "?"}limit=${limit + PAGE_SIZE}`)}">${S.more}</a></div>` : "";
  return section(`${chips}${card(d.jobs.length ? dataTable(JOB_COLUMNS, d.jobs, sort) + more : nothing)}
    ${d.jobs.length ? `<div class="muted">${e(S.found(d.jobs.length, d.total))}</div>` : ""}`, "span-all");
}

// --- settings ------------------------------------------------------------

function rawValue(v) {
  if (v.raw === null || v.raw === undefined) return `<span class="muted">-</span>`;
  if (v.flags) return e(v.flags.map((flag) => (flag ? S.yes : S.no)).join(", "));
  const text = v.text ?? v.raw;
  if (text === "") return `<span class="muted">${S.value_empty}</span>`;
  return text.length > 60 ? `<pre>${e(text.replaceAll("\\n", "\n"))}</pre>` : e(text);
}

const unit = (r) => (r.unit && !r.flags && r.raw ? `<span class="unit">${e(r.unit)}</span>` : "");
const tipRow = (r, value) => `<div class="row"${r.tooltip ? " data-tip" : ""}>
  <span>${e(r.label)}</span><span class="row-value">${value}</span>
  ${r.tooltip ? `<div class="tip" hidden>${e(r.tooltip)}</div>` : ""}</div>`;
const plainValue = (v) => (v.raw === null || v.raw === undefined ? "-" : v.flags
  ? v.flags.map((flag) => (flag ? S.yes : S.no)).join(", ") : (v.text ?? v.raw) || S.value_empty);
const diffRow = (r, a, b) => `<div class="diff-row"><span>${e(r.label)}${r.unit ? `, ${e(r.unit)}` : ""}</span>
  <div class="diff-values"><span class="old">${e(plainValue(a))}</span>${icon("chevron-right")}<span class="new">${e(plainValue(b))}</span></div></div>`;

function tabsHtml(tabs, rowHtml) {
  const panels = tabs.map((tab, i) => `<div data-panel="${i}"${i ? " hidden" : ""}>
    ${tab.pages.map((page) => `${page.title ? `<h3 class="page-title">${e(page.title)}</h3>` : ""}
      ${page.groups.map((g) => `${g.title ? `<div class="group-title">${e(g.title)}</div>` : ""}${g.rows.map(rowHtml).join("")}`).join("")}`).join("")}</div>`);
  const buttons = tabs.map((tab, i) =>
    `<button type="button" data-tab="${i}" class="${i ? "" : "on"}">${e(S[`tab_${tab.id}`])}</button>`);
  return `<div class="tabs">${buttons.join("")}</div>${panels.join("")}`;
}

function changeBlock(kind, change) {
  if (!change) return `<div class="diff-title">${S[`vs_${kind}`]}<span class="muted" style="margin-left:auto;font-weight:400">${S.no_baseline}</span></div>`;
  const link = `<a class="ellipsis" style="margin-left:auto" href="#/job/${enc(change.ref)}" title="${e(change.file)}">${e(change.file || change.ref)}</a>`;
  return `<div class="diff-title">${S[`vs_${kind}`]}${link}</div>
    ${change.diff.length ? change.diff.map((r) => diffRow(r, r.old, r.new)).join("") : `<div class="row muted">${S.no_changes}</div>`}`;
}

// --- print page ----------------------------------------------------------

function jobTiles(j) {
  const excluded = Object.keys(j.excluded || {}).join(", ");
  const parts = j.planned ? S.parts_state(j.parts, j.planned) : UI.number(j.parts, 0);
  const costState = j.wasted_cost ? S.wasted_note(UI.money(j.wasted_cost)) : S.cost_breakdown(UI.money(j.filament_cost), UI.money(j.energy_cost));
  return `<div class="tiles six">
    ${tile({ name: S.tile_time, state: UI.duration(j.minutes), iconName: "timer-outline", variable: "--primary-color" })}
    ${tile({ name: S.tile_filament, state: `${UI.grams(j.grams)} · ${UI.number(j.filament_mm / 1000, 1)} м${j.spool ? ` · ${j.spool}` : ""}`, iconName: "printer-3d-nozzle", variable: "--state-icon-color" })}
    ${tile({ name: S.tile_energy, state: j.kwh === null ? S.no_data : UI.kwh(j.kwh), iconName: "lightning-bolt", variable: "--warning-color" })}
    ${tile({ name: S.tile_cost, state: `${UI.money(j.total_cost)} · ${costState}`, iconName: "cash-multiple", variable: "--accent-color" })}
    ${tile({ name: S.tile_per_part, state: j.per_part ? UI.money(j.per_part) : "-", iconName: "shape-outline", variable: "--info-color" })}
    ${tile({ name: S.tile_parts, state: excluded ? `${parts} · ${S.parts_excluded(excluded)}` : parts, iconName: excluded ? "alert" : "check-circle", variable: excluded ? "--warning-color" : "--success-color" })}
  </div>`;
}

function presetBadges(j) {
  const items = Object.entries(j.presets).flatMap(([kind, names]) => names.map((name) => {
    const drift = j.drift[`${kind}/${name}`];
    return badge(`${S[`kind_${kind}`]}: ${name}`, {
      href: `#/preset/${kind}/${enc(name)}`, iconName: drift ? "alert" : "tune-variant",
      variable: drift ? "--warning-color" : undefined, cls: drift ? "warn" : "",
      title: drift ? `${S.drift}: ${drift.map((d) => d.label).join(", ")}` : undefined,
    });
  }));
  return items.join("");
}

async function jobPage(id) {
  setToolbar({ back: true, tab: "prints", title: S.nav_prints });
  const j = await api(`job/${enc(id)}`);
  UI.setCurrency(j.currency);
  setToolbar({ back: true, tab: "prints", title: j.file });
  const meta = [UI.date(j.end_time), j.slicer && `${j.slicer} ${j.slicer_version}`].filter(Boolean).join(" · ");
  const header = section(card(`<div class="job-head">${thumb(j.thumbnail, "job-thumb")}
      <div class="job-title"><h1>${e(j.file)}</h1>
        <div class="badges">${UI.statusBadge(j.status)}
          ${j.commit ? badge(`${S.commit} ${j.commit.slice(0, 8)}`, { iconName: "source-branch" }) : ""}</div>
        <div class="muted">${e(meta)}</div></div></div>
      ${j.live_data ? "" : `<div class="note">${icon("alert")}${S.best_effort}</div>`}`)
    + jobTiles(j), "span-all");
  if (j.config_missing) {
    return header + section(card(empty("image-off-outline", S.config_missing)), "span-all");
  }
  const others = (await api("jobs?limit=100")).jobs.filter((o) => o.ref !== j.ref);
  const picker = others.length ? `<div class="card-body"><select class="compare-select" id="compare" aria-label="${S.compare_with}">
    <option value="">${S.compare_with}</option>
    ${others.map((o) => `<option value="${e(o.ref)}">${e(UI.date(o.end_time))} · ${e(o.file)}</option>`).join("")}</select></div>` : "";
  const setting = (r) => tipRow(r, `${rawValue(r)}${unit(r)}`);
  return header
    + section(`${heading("tune-variant", S.presets)}<div class="badges">${presetBadges(j)}</div>`, "span-all")
    + `<div class="columns span-all job-columns">
      ${section(`${heading("file-compare", S.changes)}${card(["file", "process", "filament"].map((k) => changeBlock(k, j.changes[k])).join(""))}${card(picker)}`)}
      ${section(`${heading("printer-3d", S.settings)}${card(tabsHtml(j.settings, setting))}`)}
    </div>`;
}

// --- compare, part, preset -----------------------------------------------

async function comparePage(a, b) {
  setToolbar({ back: true, tab: "prints", title: S.compare });
  const d = await api(`compare/${enc(a)}/${enc(b)}`);
  const side = (j) => tile({ name: j.file, state: UI.date(j.end_time), iconName: UI.statusIconName(j.status), variable: UI.statusVariable(j.status), href: `#/job/${enc(j.ref)}` });
  return section(`${heading("compare-horizontal", S.compare)}<div class="tiles">${side(d.a)}${side(d.b)}</div>`, "span-all")
    + section(card(d.tabs.length ? tabsHtml(d.tabs, (r) => diffRow(r, r.a, r.b)) : empty("check-circle", S.compare_same)), "span-all");
}

async function partPage(name) {
  setToolbar({ back: true, tab: "prints", title: name });
  const d = await api(`part/${enc(name)}`);
  UI.setCurrency(d.currency);
  const rows = d.jobs.slice().reverse().map((j) => ({
    ...j, parts: j.part_printed, planned: j.part_printed + j.part_excluded, excluded: j.part_excluded > 0,
  }));
  const columns = JOB_COLUMNS.map((c) => (c.id === "spool"
    ? { ...c, id: "changes", label: S.col_changes, cell: (j) => `<div class="ellipsis" title="${e(j.changes.join(", "))}">${e(j.changes.join(", "))}</div>` } : c));
  return section(`${heading("shape-outline", d.name)}<div class="tiles">
      ${tile({ name: S.printed, state: UI.number(d.printed, 0), iconName: "check-circle", variable: "--success-color" })}
      ${tile({ name: S.excluded, state: UI.number(d.excluded, 0), iconName: "close-circle-outline", variable: "--warning-color" })}
      ${tile({ name: S.part_success, state: UI.percent(d.success_rate), iconName: "check-decagram", variable: "--primary-color" })}
    </div>`, "span-all")
    + section(card(dataTable(columns, rows)), "span-all");
}

async function presetPage(kind, name) {
  setToolbar({ back: true, tab: "prints", title: name });
  const d = await api(`preset/${enc(kind)}/${enc(name)}`);
  const entry = (t) => card(`<a class="diff-title" href="#/job/${enc(t.ref)}">
      ${UI.statusIcon(t.status)}<span class="ellipsis" title="${e(t.file)}">${e(t.file)}</span>
      <span class="muted" style="margin-left:auto;font-weight:400;white-space:nowrap">${e(UI.date(t.end_time))}</span></a>
    ${t.first ? `<div class="row muted">${S.preset_first}</div>` : t.diff.map((r) => diffRow(r, r.old, r.new)).join("")}`);
  return section(`${heading("tune-variant", `${S[`kind_${kind}`]}: ${d.name}`)}<div class="tiles">
      ${tile({ name: S.preset_prints, state: UI.number(d.prints, 0), iconName: "printer-3d", variable: "--primary-color" })}</div>`, "span-all")
    + section(`${heading("history", S.preset_history)}${d.timeline.map(entry).join("")}`, "span-all");
}

// --- router --------------------------------------------------------------

const skeletonTiles = (count) => `<div class="tiles">${Array.from({ length: count }, UI.skeletonTile).join("")}</div>`;
const LOADING = {
  home: () => section(skeletonTiles(6) + UI.skeletonRows(5), "span-all"),
  job: () => section(skeletonTiles(6) + UI.skeletonRows(6), "span-all"),
  list: () => section(UI.skeletonRows(8), "span-all"),
};

let renderRun = 0;
async function render() {
  const run = ++renderRun;
  const hash = location.hash.replace(/^#/, "") || "/";
  const [, page, ...rest] = hash.split("?")[0].split("/");
  const args = rest.map(decodeURIComponent);
  view.innerHTML = (LOADING[page === "job" ? "job" : page ? "list" : "home"])();
  window.scrollTo(0, 0);
  let html;
  try {
    if (page === "job") html = await jobPage(args[0]);
    else if (page === "prints") html = await prints();
    else if (page === "compare") html = await comparePage(args[0], args[1]);
    else if (page === "part") html = await partPage(args.join("/"));
    else if (page === "preset") html = await presetPage(args[0], args.slice(1).join("/"));
    else html = await home();
  } catch (error) {
    html = section(card(empty("alert-circle", `${S.error}: ${error.message}`)), "span-all");
  }
  if (run === renderRun) view.innerHTML = html;
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-tab], [data-tip], [data-action], tr[data-href]");
  if (!target || event.target.closest("a, select, pre") && !target.matches("[data-action]")) return;
  if (target.dataset.tab !== undefined) {
    const scope = target.closest(".card");
    scope.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b === target));
    scope.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== target.dataset.tab; });
  } else if (target.dataset.tip !== undefined) {
    const tip = target.querySelector(".tip");
    tip.hidden = !tip.hidden;
  } else if (target.dataset.action === "search") {
    const form = document.getElementById("search");
    form.classList.toggle("open");
    if (form.classList.contains("open")) form.elements.file.focus();
    else form.requestSubmit();
  } else if (target.dataset.action === "rescan") {
    target.disabled = true;
    try {
      await fetch("api/reconcile", { method: "POST" });
    } finally {
      render();
    }
  } else if (target.dataset.href) {
    location.hash = target.dataset.href;
  }
});

document.addEventListener("change", (event) => {
  if (event.target.dataset.printer !== undefined) {
    printer = event.target.value;
    try {
      localStorage.setItem("printer", printer);
    } catch (error) {
      // The choice lasts until the page reloads then.
    }
    render();
    return;
  }
  if (event.target.dataset.filter) location.hash = listHref({ [event.target.dataset.filter]: event.target.value });
  if (event.target.id === "compare" && event.target.value) {
    const current = location.hash.split("/")[2];
    location.hash = `#/compare/${current}/${enc(event.target.value)}`;
  }
});

document.addEventListener("submit", (event) => {
  if (event.target.id !== "search") return;
  event.preventDefault();
  location.hash = listHref({ file: event.target.elements.file.value.trim() });
});

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
