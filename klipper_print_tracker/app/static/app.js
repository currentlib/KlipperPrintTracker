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
  const tabs = [["#/", S.nav_home, "home"], ["#/prints", S.nav_prints, "prints"], ["#/calibration", S.nav_calibration, "calibration"], ["#/maintenance", S.nav_maintenance, "maintenance"], ["#/projects", S.nav_projects, "projects"], ["#/analysis", S.nav_analysis, "analysis"]]
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

function ratingIcon(rating) {
  if (rating === "good") return `<span class="status-icon" style="--c:var(--success-color)" title="${S.rate_good}">${icon("thumb-up", "s18")}</span>`;
  if (rating === "bad") return `<span class="status-icon" style="--c:var(--error-color)" title="${S.rate_bad}">${icon("thumb-down", "s18")}</span>`;
  return "";
}

const JOB_COLUMNS = [
  { label: "", cls: "icon-cell thumb-cell", cell: (j) => thumb(j.thumbnail) },
  { id: "date", label: S.col_date, cls: "nowrap", cell: (j) => UI.date(j.end_time) },
  { id: "printer", label: S.printer, cls: "nowrap hide-m", cell: (j) => e(printerName(j.printer_id)), multi: true },
  { id: "file", label: S.col_file, cls: "file", cell: fileCell },
  { id: "rating", label: S.col_rating, cls: "icon-col hide-m", cell: (j) => ratingIcon(j.rating) },
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
  const banner = d.unrated ? section(`<a class="banner" href="#/prints?rating=none">${icon("star-outline")}
    <span>${e(S.unrated_banner(d.unrated))}</span><span class="banner-action">${S.rate_now}${icon("chevron-right", "s18")}</span></a>`, "span-all") : "";
  return [
    banner,
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
  const rating = params.get("rating");
  const ratingChip = (value, label, name) => `<a class="chip ${rating === value ? "on" : ""}" href="${e(listHref({ rating: rating === value ? "" : value }))}">${icon(name)}${label}</a>`;
  const chips = `<div class="chips">${statusChips}
    ${ratingChip("none", S.unrated, "star-outline")}${ratingChip("good", S.rate_good, "thumb-up")}${ratingChip("bad", S.rate_bad, "thumb-down")}
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

function failureBlock(j) {
  if (j.status === "completed" || !j.interruption) return "";
  const details = [
    j.progress !== null && S.at_progress(UI.percent(j.progress)),
    j.current_layer && S.at_layer(j.current_layer, j.total_layer),
    j.chamber_temp !== null && S.chamber(UI.number(j.chamber_temp, 0)),
  ].filter(Boolean).join(" · ");
  return section(`${heading("alert-circle", S.failure_details)}${card(`<div class="card-body">
    <div>${e(S[`interrupted_${j.interruption}`] ?? j.interruption)}</div>
    ${details ? `<div class="muted">${e(details)}</div>` : ""}
    ${j.error_message ? `<div class="mono muted">${e(j.error_message)}</div>` : ""}</div>`)}`, "span-all");
}

function spoolBlock(check) {
  if (!check) return "";
  const text = {
    no_spool: () => S.spool_no_spool,
    not_enough: (w) => S.spool_not_enough(UI.grams(w.required_g), UI.grams(w.remaining_g)),
    material_mismatch: (w) => S.spool_material(w.wanted, w.actual),
    preset_mismatch: (w) => S.spool_preset(w.preset),
  };
  const lines = check.warnings.map((w) => `<div class="note">${icon(w.info ? "tune-variant" : "alert")}${e(text[w.code](w))}</div>`);
  if (check.paused) lines.push(`<div class="note">${icon("pause")}${S.spool_paused}</div>`);
  const body = lines.length ? lines.join("") : empty("check-circle", S.spool_ok);
  return section(`${heading("printer-3d-nozzle", S.spool_check)}${card(body)}`, "span-all");
}

function ratingBlock(j, tagList) {
  const button = (value, label, name, variable) => `<button type="button" class="chip ${j.rating === value ? "on" : ""}" data-rate="${value}" style="--c:var(${variable})">${icon(name)}${label}</button>`;
  const allTags = [...new Set([...tagList, ...j.issues])];
  const chips = allTags.map((tag) => `<button type="button" class="chip ${j.issues.includes(tag) ? "on" : ""}" data-issue="${e(tag)}">${e(tag)}</button>`).join("");
  const reasons = ["adhesion", "spaghetti", "clog", "other"].map((reason) =>
    `<option value="${reason}"${j.failure_reason === reason ? " selected" : ""}>${S[`reason_${reason}`]}</option>`).join("");
  return card(`<div class="card-body rating" data-ref="${e(j.ref)}">
    <div class="chips">${button("good", S.rate_good, "thumb-up", "--success-color")}${button("bad", S.rate_bad, "thumb-down", "--error-color")}
      ${j.status === "completed" ? "" : `<select class="chip ${j.failure_reason ? "on" : ""}" data-reason aria-label="${S.failure_reason}">
        <option value="">${S.failure_reason}</option>${reasons}</select>`}</div>
    <div class="group-label">${S.issues}</div><div class="chips">${chips}</div>
    <textarea class="field" data-note rows="2" placeholder="${S.note_hint}" aria-label="${S.note}">${e(j.note)}</textarea>
    <details class="manage"><summary>${S.manage_tags}</summary>
      <textarea class="field" id="tags" rows="6" aria-label="${S.tags_hint}">${e(tagList.join("\n"))}</textarea>
      <button type="button" class="text-button" data-action="save-tags">${S.save}</button></details>
  </div>`);
}

async function rate(ref, fields) {
  const response = await fetch(`api/job/${enc(ref)}/rating`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
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
    return header + section(`${heading("thumb-up", S.rating)}${ratingBlock(j, await api("tags").then((t) => t.tags))}`, "span-all")
      + section(card(empty("image-off-outline", S.config_missing)), "span-all");
  }
  const others = (await api("jobs?limit=100")).jobs.filter((o) => o.ref !== j.ref);
  const { tags: tagList } = await api("tags");
  const picker = others.length ? `<div class="card-body"><select class="compare-select" id="compare" aria-label="${S.compare_with}">
    <option value="">${S.compare_with}</option>
    ${others.map((o) => `<option value="${e(o.ref)}">${e(UI.date(o.end_time))} · ${e(o.file)}</option>`).join("")}</select></div>` : "";
  const setting = (r) => tipRow(r, `${rawValue(r)}${unit(r)}`);
  return header
    + section(`${heading("thumb-up", S.rating)}${ratingBlock(j, tagList)}`, "span-all")
    + projectPicker(j) + calibrationBlock(j) + failureBlock(j) + spoolBlock(j.spool_check)
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
  const side = (j) => tile({ name: j.file, state: [UI.date(j.end_time), j.rating && S[`rate_${j.rating}`], ...j.issues].filter(Boolean).join(" · "), iconName: UI.statusIconName(j.status), variable: UI.statusVariable(j.status), href: `#/job/${enc(j.ref)}` });
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

function resultLine(r) {
  const result = r.results;
  if (!result || !(result.good || result.bad)) return "";
  const tags = Object.entries(result.tags).map(([tag, count]) => `${tag} x${count}`).join(", ");
  return `<div class="row-note">${e(S.results_for_value(r.new.raw))}: ${icon("thumb-up", "s18")}${result.good} ${icon("thumb-down", "s18")}${result.bad}${tags ? ` · ${e(tags)}` : ""}</div>`;
}

async function presetPage(kind, name) {
  setToolbar({ back: true, tab: "prints", title: name });
  const d = await api(`preset/${enc(kind)}/${enc(name)}`);
  const entry = (t) => card(`<a class="diff-title" href="#/job/${enc(t.ref)}">
      ${UI.statusIcon(t.status)}<span class="ellipsis" title="${e(t.file)}">${e(t.file)}</span>
      <span class="muted" style="margin-left:auto;font-weight:400;white-space:nowrap">${e(UI.date(t.end_time))}</span></a>
    ${t.issues.length || t.rating ? `<div class="row-note">${ratingIcon(t.rating)}${e(t.issues.join(", "))}</div>` : ""}
    ${t.first ? `<div class="row muted">${S.preset_first}</div>` : t.diff.map((r) => diffRow(r, r.old, r.new) + resultLine(r)).join("")}`);
  return section(`${heading("tune-variant", `${S[`kind_${kind}`]}: ${d.name}`)}<div class="tiles">
      ${tile({ name: S.preset_prints, state: UI.number(d.prints, 0), iconName: "printer-3d", variable: "--primary-color" })}</div>`, "span-all")
    + section(`${heading("history", S.preset_history)}${d.timeline.map(entry).join("")}`, "span-all");
}

// --- maintenance ---------------------------------------------------------

const post = (path, body) => fetch(`api/${path}`, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

function taskState(t) {
  if (!t.enabled) return S.maint_disabled;
  if (t.snoozed) return S.maint_snoozed;
  const worst = t.worst;
  if (!worst) return "";
  return worst.remaining < 0 ? S.maint_over(UI.number(-worst.remaining, 0), worst.unit)
    : S.maint_left(UI.number(worst.remaining, 0), worst.unit);
}

function taskForm(t) {
  const input = (name, label, value, type = "number") => `<label class="form-field">${label}
    <input class="field" name="${name}" type="${type}" value="${e(value ?? "")}"></label>`;
  return `<details class="manage"><summary>${S.maint_edit}</summary><form class="task-form" data-task="${t.id}">
    ${input("name", S.maint_name, t.name, "text")}${input("note", S.maint_note, t.note, "text")}
    ${input("hours", S.maint_hours, t.hours)}${input("days", S.maint_days, t.days)}${input("grams", S.maint_grams, t.grams)}
    ${input("prints", S.maint_prints, t.prints)}${input("abrasive_grams", S.maint_abrasive, t.abrasive_grams)}
    ${input("material_pattern", S.maint_material, t.material_pattern, "text")}
    <label class="form-check"><input type="checkbox" name="enabled"${t.enabled ? " checked" : ""}>${S.maint_enabled}</label>
    <div class="form-actions"><button class="text-button">${S.save}</button>
    <button type="button" class="text-button danger" data-delete-task="${t.id}">${S.maint_delete}</button></div></form></details>`;
}

function taskCard(t) {
  const variable = t.due ? "--error-color" : t.percent_used >= 80 ? "--warning-color" : "--success-color";
  return card(`<div class="task">
    <div class="tile-row">${tile({ name: t.name, state: taskState(t), iconName: t.due ? "alert" : "wrench", variable })}
      <button class="text-button" data-done="${t.id}">${S.maint_done}</button></div>
    <span class="bar" style="--c:var(${variable})"><i style="width:${Math.min(100, t.percent_used)}%"></i></span>
    ${t.note ? `<div class="muted small">${e(t.note)}</div>` : ""}${taskForm(t)}</div>`);
}

function setupCard(p) {
  const today = new Date().toISOString().slice(0, 10);
  const rows = p.tasks.map((t) => `<label class="setup-row"><span>${e(t.name)}</span>
    <input class="field" type="date" name="${t.id}" max="${today}" value="${today}"></label>`).join("");
  return card(`<form class="card-body setup" data-setup="${e(p.id)}"><p>${S.maint_setup}</p>${rows}
    <div class="form-actions"><button class="text-button">${S.maint_confirm}</button></div></form>`);
}

async function maintenancePage() {
  setToolbar({ tab: "maintenance", title: S.maintenance });
  const d = await api(scoped("maintenance"));
  return d.printers.map((p) => {
    const log = p.log.map((l) => `<div class="list-row"><span class="ellipsis">${e(l.name)}${l.note ? ` · ${e(l.note)}` : ""}</span>
      <span class="muted">${e(UI.date(l.done_at))}</span></div>`).join("");
    return section(`${heading("wrench", d.printers.length > 1 ? p.name : S.maintenance, `<a href="#" data-add-task="${e(p.id)}">${S.maint_add}</a>`)}
      ${p.needs_setup ? setupCard(p) : ""}
      <div class="task-grid">${p.tasks.map(taskCard).join("") || card(empty("wrench", S.maint_empty))}</div>
      ${log ? `${heading("history", S.maint_history)}${card(log)}` : ""}`, "span-all");
  }).join("");
}

// --- calibration ---------------------------------------------------------

function calibrationBlock(j) {
  const c = j.calibration;
  const options = j.calibration_types.map((t) => `<option value="${t}"${c?.type === t ? " selected" : ""}>${S[`cal_${t}`]}</option>`).join("");
  const range = c && c.range_start !== null ? S.cal_range(UI.number(c.range_start, 4), UI.number(c.range_end, 4), UI.number(c.range_step, 4)) : "";
  const form = `<form class="card-body task-form" data-calibrate="${e(j.ref)}">
    <label class="form-field span-row">${S.cal_type}<select class="field" name="type">${options}</select></label>
    ${c ? "" : ["start", "end", "step"].map((name) => `<label class="form-field wide">${S[`cal_${name}`]}<input class="field" name="${name}" inputmode="decimal"></label>`).join("")}
    <label class="form-field span-row">${S.cal_value}<input class="field" name="value" inputmode="decimal" value="${e(c?.value ?? "")}"></label>
    <div class="form-actions"><button class="text-button">${S.save}</button></div></form>`;
  if (c) return section(`${heading("target", `${S.calibration}: ${S[`cal_${c.type}`]}`, e(range))}${card(form)}`, "span-all");
  return section(card(`<details class="manage card-body"><summary>${S.cal_mark}</summary>${form}</details>`), "span-all");
}

function calibrationRow(group, c) {
  const flags = [c.stale && badge(S.cal_stale, { iconName: "alert", variable: "--warning-color", cls: "warn" }),
    c.new_spool && badge(S.cal_new_spool, {})].filter(Boolean).join("");
  const mismatch = c.mismatch ? `<div class="note">${icon("alert")}${e(S.cal_mismatch(S[`cal_group_${group}`], UI.number(c.value, 4), UI.number(c.used, 4)))}</div>` : "";
  return `<a class="list-row" href="#/job/${enc(`${c.printer_id}:${c.job_id}`)}">
    <span>${S[`cal_group_${group}`]}: <b>${UI.number(c.value, 4)}</b></span><span class="muted small">${e(UI.date(c.created_at))}</span>
    <span class="muted small span-row">${e([c.spool, S.cal_days(c.age_days)].filter(Boolean).join(" · "))}</span>
    ${flags ? `<span class="badges span-row">${flags}</span>` : ""}</a>${mismatch}`;
}

async function calibrationPage() {
  setToolbar({ tab: "calibration", title: S.calibration });
  const d = await api(scoped("calibration"));
  printers = d.printers;
  setToolbar({ tab: "calibration", title: S.calibration });
  if (!d.presets.length) return section(card(empty("target", S.cal_empty)), "span-all");
  return d.presets.map((p) => {
    const latest = Object.entries(p.latest).map(([group, c]) => calibrationRow(group, c)).join("");
    const history = p.history.map((h) => `<a class="list-row" href="#/job/${enc(`${h.printer_id}:${h.job_id}`)}">
      <span class="ellipsis">${S[`cal_${h.type}`]}${h.value === null ? ` · ${S.cal_no_value}` : ` · ${UI.number(h.value, 4)}`}</span>
      <span class="muted small">${e(UI.date(h.created_at))}</span></a>`).join("");
    return section(`${heading("target", [p.preset, p.material].filter(Boolean).join(" · "))}
      ${latest ? card(latest) : ""}
      <div class="group-label">${S.cal_history}</div>${card(history)}`);
  }).join("");
}

// --- projects ------------------------------------------------------------

function projectBar(p) {
  return `<span class="bar" style="--c:var(--primary-color)"><i style="width:${p.percent}%"></i></span>`;
}

function projectCard(p) {
  return `<a class="card project-card" href="#/project/${p.id}">
    <span class="tile-row"><span class="tile-name ellipsis">${e(p.name)}</span>
      <span class="badge count">${S[`proj_${p.status}`]}</span></span>
    ${projectBar(p)}
    <span class="muted small">${e(S.proj_progress(p.done, p.target))} · ${UI.number(p.percent, 0)}%${p.deadline ? ` · ${e(p.deadline)}` : ""}</span></a>`;
}

async function projectsPage() {
  setToolbar({ tab: "projects", title: S.projects });
  const d = await api("projects");
  const add = `<button class="text-button" data-action="add-project">${S.proj_add}</button>`;
  return section(`${heading("folder-multiple-outline", S.projects, add)}
    ${d.projects.length ? `<div class="task-grid">${d.projects.map(projectCard).join("")}</div>` : card(empty("folder-multiple-outline", S.proj_empty))}`, "span-all");
}

function projectForm(p) {
  const rule = (kind) => p.rules.filter((r) => r.kind === kind).map((r) => r.pattern).join("\n");
  const targets = p.targets.map((t) => `${t.part} = ${t.quantity}`).join("\n");
  const statuses = ["active", "done", "archived"].map((s) => `<option value="${s}"${p.status === s ? " selected" : ""}>${S[`proj_${s}`]}</option>`).join("");
  const text = (name, label, value, type = "text") => `<label class="form-field span-row">${label}<input class="field" type="${type}" name="${name}" value="${e(value ?? "")}"></label>`;
  const area = (name, label, value) => `<label class="form-field span-row">${label}<textarea class="field" name="${name}" rows="3">${e(value)}</textarea></label>`;
  return card(`<details class="manage card-body"><summary>${S.proj_edit}</summary><form class="task-form" data-project="${p.id}">
    ${text("name", S.proj_name, p.name)}${text("description", S.proj_description, p.description)}
    ${text("deadline", S.proj_deadline, p.deadline, "date")}
    <label class="form-field span-row">${S.proj_status}<select class="field" name="status">${statuses}</select></label>
    ${area("targets", S.proj_targets, targets)}${area("file_rules", S.proj_rules_file, rule("file"))}${area("part_rules", S.proj_rules_part, rule("part"))}
    <div class="form-actions"><button class="text-button">${S.save}</button>
    <button type="button" class="text-button danger" data-delete-project="${p.id}">${S.proj_delete}</button></div></form></details>`);
}

async function projectPage(id) {
  setToolbar({ back: true, tab: "projects", title: S.projects });
  const p = await api(`project/${enc(id)}`);
  UI.setCurrency(p.currency);
  setToolbar({ back: true, tab: "projects", title: p.name });
  const left = p.estimate ? S.proj_left_state(UI.duration(p.estimate.hours * 60), UI.grams(p.estimate.grams)) : S.proj_left_none;
  const parts = p.parts.map((part) => `<a class="list-row" href="#/part/${enc(part.name)}">
    <span class="ellipsis" title="${e(part.name)}">${e(part.name)}</span><span class="badge count">${part.printed} / ${part.target}</span>
    <span class="bar" style="--c:var(--primary-color)"><i style="width:${Math.min(100, (100 * part.printed) / part.target)}%"></i></span></a>`).join("");
  const total = (key) => p.success[key] + p.failed[key];
  return section(`${heading("folder-multiple-outline", p.name, UI.percent(p.percent))}
      ${p.description ? `<div class="muted">${e(p.description)}</div>` : ""}
      <div class="tiles six">
      ${tile({ name: S.proj_parts, state: S.proj_progress(p.done, p.target), iconName: "shape-outline", variable: "--primary-color" })}
      ${tile({ name: S.proj_left, state: left, iconName: "timer-outline", variable: "--info-color" })}
      ${tile({ name: S.proj_time, state: UI.duration(total("hours") * 60), iconName: "timer-outline", variable: "--state-icon-color" })}
      ${tile({ name: S.proj_filament, state: `${UI.grams(total("grams"))}, ${S.proj_failed(UI.grams(p.failed.grams))}`, iconName: "printer-3d-nozzle", variable: "--state-icon-color" })}
      ${tile({ name: S.proj_energy, state: UI.kwh(total("kwh")), iconName: "lightning-bolt", variable: "--warning-color" })}
      ${tile({ name: S.proj_cost, state: `${UI.money(total("cost"))}, ${S.proj_failed(UI.money(p.failed.cost))}`, iconName: "cash-multiple", variable: "--accent-color" })}
      </div>`, "span-all")
    + section(`${heading("shape-outline", S.proj_parts)}${card(parts || empty("shape-outline", S.empty_parts))}${projectForm(p)}`, "span-all")
    + section(`${heading("history", S.proj_prints)}${card(p.jobs.length ? dataTable(JOB_COLUMNS, p.jobs) : empty("printer-3d-nozzle", S.empty_prints))}`, "span-all");
}

function projectPicker(j) {
  const items = j.projects.map((p) => `<option value="${p.id}"${j.project_id === p.id ? " selected" : ""}>${e(p.name)}</option>`).join("");
  if (!j.projects.length && !j.project_id) return "";
  return section(`${heading("folder-multiple-outline", S.proj_assign, j.project_id ? `<a href="#/project/${j.project_id}">${icon("chevron-right", "s18")}</a>` : "")}
    ${card(`<div class="card-body"><select class="compare-select" data-assign="${e(j.ref)}" aria-label="${S.proj_assign}">
    <option value="">${S.proj_none}</option>${items}</select></div>`)}`, "span-all");
}

// --- analysis ------------------------------------------------------------

function dimensionRows(items) {
  return items.map((g) => {
    const reasons = Object.entries(g.reasons).sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => `${S[`reason_${reason}`] ?? reason} x${count}`).join(", ");
    return `<div class="list-row"><span class="ellipsis" title="${e(g.name)}">${e(g.name)}</span>
      <span class="badge count">${g.failed}/${g.total}</span>
      <span class="bar" style="--c:var(--error-color)"><i style="width:${g.rate}%"></i></span>
      ${reasons ? `<span class="muted small span-row">${e(reasons)}</span>` : ""}</div>`;
  }).join("") || empty("chart-box-outline", S.an_empty);
}

function dimensionTabs(dimensions) {
  const names = Object.keys(dimensions);
  const buttons = names.map((name, i) => `<button type="button" data-tab="${i}" class="${i ? "" : "on"}">${S[`dim_${name}`]}</button>`);
  const panels = names.map((name, i) => `<div data-panel="${i}"${i ? " hidden" : ""}>${dimensionRows(dimensions[name])}</div>`);
  return card(`<div class="tabs">${buttons.join("")}</div>${panels.join("")}`);
}

const tagRows = (items) => items.map((t) => `<div class="list-row"><span class="ellipsis">${e(t.tag)} · ${e(t.name)}</span>
  <span class="badge count">${t.count}</span></div>`).join("") || empty("thumb-up", S.an_empty);

async function analysisPage() {
  setToolbar({ tab: "analysis", title: S.analysis });
  const params = listParams();
  const query = new URLSearchParams();
  for (const key of ["days", "material", "include_power"]) if (params.get(key)) query.set(key, params.get(key));
  const d = await api(scoped(`analysis?${query}`));
  UI.setCurrency(d.currency);
  const change = (name, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    return `#/analysis?${next}`;
  };
  const filters = `<div class="chips">
    ${[30, 90, 365].map((days) => { const on = params.get("days") === String(days); return `<a class="chip ${on ? "on" : ""}" href="${e(change("days", on ? "" : days))}">${S[`period_${days}`]}</a>`; }).join("")}
    ${selectChip("material", S.dim_material, d.facets.materials.map((m) => [m, m]), params.get("material") || "").replace("data-filter", "data-analysis-filter")}
    <a class="chip ${params.get("include_power") ? "on" : ""}" href="${e(change("include_power", params.get("include_power") ? "" : "1"))}">${S.an_with_offline}</a></div>`;
  const offline = d.offline && !params.get("include_power") ? `<div class="muted small">${e(S.an_offline(d.offline))}</div>` : "";
  if (!d.total) return section(filters + card(empty("chart-box-outline", S.an_empty)), "span-all");
  const hours = (value) => UI.duration(value * 60);
  const count = (value) => UI.number(value, 0);
  const percent = (value) => `${UI.number(value, 0)}%`;
  const weekly = d.weekly.map((w) => ({ label: w.week, value: w.rate }));
  return section(`${filters}${offline}<div class="tiles six">
      ${tile({ name: S.an_success, state: `${UI.percent(d.success_rate)} · ${d.completed} з ${d.total}`, iconName: "check-decagram", variable: "--success-color" })}
      ${tile({ name: S.an_failed, state: UI.number(d.failed, 0), iconName: "alert-circle", variable: "--error-color" })}
      ${tile({ name: S.an_top_reason, state: d.top_reason ? S[`reason_${d.top_reason}`] : S.reason_unknown, iconName: "alert", variable: "--warning-color" })}
      ${tile({ name: S.an_lost_time, state: hours(d.wasted.hours), iconName: "timer-outline", variable: "--primary-color" })}
      ${tile({ name: S.an_lost_filament, state: UI.grams(d.wasted.grams), iconName: "printer-3d-nozzle", variable: "--state-icon-color" })}
      ${tile({ name: S.an_lost_money, state: UI.money(d.wasted.cost), iconName: "cash-multiple", variable: "--accent-color" })}
    </div>`, "span-all")
    + section(`${heading("chart-box-outline", S.an_weekly)}${card(`<div class="card-body">${UI.barChart(weekly, { format: percent, max: 100 })}</div>`)}`, "span-all")
    + `<div class="columns span-all">
      ${section(`${heading("chart-box-outline", S.an_progress)}${card(`<div class="card-body">${UI.barChart(d.progress.map((b) => ({ label: b.label, value: b.count })), { format: count })}</div>`)}`)}
      ${section(`${heading("chart-box-outline", S.an_layers)}${card(`<div class="card-body">${UI.barChart(d.layers.map((b) => ({ label: b.label, value: b.count })), { format: count })}</div>`)}`)}
    </div>`
    + section(`${heading("alert-circle", S.an_reasons)}${dimensionTabs(d.dimensions)}`, "span-all")
    + `<div class="columns span-all">
      ${section(`${heading("shape-outline", S.an_problem_parts)}${card(d.problem_parts.map((p) => `<a class="list-row" href="#/part/${enc(p.name)}">
        <span class="ellipsis" title="${e(p.name)}">${e(p.name)}</span><span class="badge count">${UI.number(p.problem_rate, 0)}%</span>
        <span class="muted small span-row">${e(S.an_problem_state(p.excluded, p.failed_prints))}</span></a>`).join("") || empty("check-circle", S.an_empty))}`)}
      ${section(`${heading("thumb-down", `${S.an_tags}: ${S.an_tags_material}`)}${card(tagRows(d.tags_by_material))}`)}
      ${section(`${heading("thumb-down", `${S.an_tags}: ${S.an_tags_preset}`)}${card(tagRows(d.tags_by_preset))}`)}
    </div>`;
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
    else if (page === "maintenance") html = await maintenancePage();
    else if (page === "analysis") html = await analysisPage();
    else if (page === "calibration") html = await calibrationPage();
    else if (page === "projects") html = await projectsPage();
    else if (page === "project") html = await projectPage(args[0]);
    else if (page === "compare") html = await comparePage(args[0], args[1]);
    else if (page === "part") html = await partPage(args.join("/"));
    else if (page === "preset") html = await presetPage(args[0], args.slice(1).join("/"));
    else html = await home();
  } catch (error) {
    html = section(card(empty("alert-circle", `${S.error}: ${error.message}`)), "span-all");
  }
  if (run === renderRun) view.innerHTML = html;
}

async function saveRating(block, fields) {
  await rate(block.dataset.ref, fields);
}

document.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-done], [data-delete-task], [data-add-task], [data-delete-project]");
  if (action) {
    event.preventDefault();
    if (action.dataset.deleteProject) {
      await fetch(`api/project/${action.dataset.deleteProject}`, { method: "DELETE" });
      location.hash = "#/projects";
      return;
    }
    if (action.dataset.done) await post(`maintenance/task/${action.dataset.done}/done`, {});
    else if (action.dataset.deleteTask) await fetch(`api/maintenance/task/${action.dataset.deleteTask}`, { method: "DELETE" });
    else await post(`maintenance/${enc(action.dataset.addTask)}`, { name: S.maint_add, hours: 100 });
    render();
    return;
  }
  const rater = event.target.closest("[data-rate], [data-issue]");
  if (rater) {
    const block = rater.closest(".rating");
    if (rater.dataset.rate) {
      const on = !rater.classList.contains("on");
      block.querySelectorAll("[data-rate]").forEach((b) => b.classList.remove("on"));
      rater.classList.toggle("on", on);
      await saveRating(block, { rating: on ? rater.dataset.rate : null });
    } else {
      rater.classList.toggle("on");
      await saveRating(block, { issues: [...block.querySelectorAll("[data-issue].on")].map((b) => b.dataset.issue) });
    }
    return;
  }
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
  } else if (target.dataset.action === "add-project") {
    const { id } = await (await post("projects", { name: S.proj_new })).json();
    location.hash = `#/project/${id}`;
  } else if (target.dataset.action === "save-tags") {
    await fetch("api/tags", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: document.getElementById("tags").value.split("\n") }),
    });
    render();
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

document.addEventListener("pointermove", (event) => {
  const tip = document.getElementById("chart-tip");
  const mark = event.target.closest?.("[data-chart-tip]");
  tip.hidden = !mark;
  if (mark) {
    tip.textContent = mark.dataset.chartTip;
    tip.style.left = `${Math.min(event.clientX + 12, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${event.clientY + 12}px`;
  }
});

document.addEventListener("change", (event) => {
  if (event.target.dataset.assign) {
    post(`job/${enc(event.target.dataset.assign)}/project`, { project_id: event.target.value ? Number(event.target.value) : null });
    return;
  }
  if (event.target.dataset.analysisFilter) {
    const next = new URLSearchParams(listParams());
    if (event.target.value) next.set(event.target.dataset.analysisFilter, event.target.value);
    else next.delete(event.target.dataset.analysisFilter);
    location.hash = `#/analysis?${next}`;
    return;
  }
  if (event.target.dataset.reason !== undefined) {
    saveRating(event.target.closest(".rating"), { failure_reason: event.target.value || null });
    return;
  }
  if (event.target.dataset.note !== undefined) {
    saveRating(event.target.closest(".rating"), { note: event.target.value });
    return;
  }
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

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.dataset.task) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const numbers = ["hours", "days", "grams", "prints", "abrasive_grams"];
    for (const key of numbers) data[key] = data[key] === "" ? null : Number(data[key]);
    data.material_pattern = data.material_pattern || null;
    data.enabled = form.elements.enabled.checked ? 1 : 0;
    await post(`maintenance/task/${form.dataset.task}`, data);
    render();
    return;
  }
  if (form.dataset.project) {
    event.preventDefault();
    const data = new FormData(form);
    const lines = (name) => data.get(name).split("\n").map((line) => line.trim()).filter(Boolean);
    const targets = lines("targets").map((line) => {
      const [part, quantity] = line.split("=").map((x) => x.trim());
      return { part, quantity: Number(quantity) || 1 };
    });
    await post(`project/${form.dataset.project}`, {
      name: data.get("name"), description: data.get("description"), deadline: data.get("deadline") || null, status: data.get("status"), targets,
      rules: [...lines("file_rules").map((pattern) => ({ kind: "file", pattern })), ...lines("part_rules").map((pattern) => ({ kind: "part", pattern }))],
    });
    render();
    return;
  }
  if (form.dataset.calibrate) {
    event.preventDefault();
    await post(`job/${enc(form.dataset.calibrate)}/calibration`, Object.fromEntries(new FormData(form)));
    render();
    return;
  }
  if (form.dataset.setup) {
    event.preventDefault();
    await post(`maintenance/${enc(form.dataset.setup)}/confirm`, { dates: Object.fromEntries(new FormData(form)) });
    render();
    return;
  }
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
