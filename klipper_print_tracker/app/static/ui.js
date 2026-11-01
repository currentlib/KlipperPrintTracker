"use strict";
// Formatters and the HTML of HA-like components.
window.UI = (() => {
  const S = window.S;
  const LOCALE = "uk-UA";
  let currency = "";

  const e = (value) => String(value ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls = "") =>
    `<svg class="mdi ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${window.ICONS[name]}"/></svg>`;

  const number = (value, digits = 2) =>
    new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits }).format(value ?? 0);
  const money = (value) => `${number(value)} ${e(currency)}`;
  const percent = (value) => `${number(value, 1)}%`;
  const kwh = (value) => `${number(value, 2)} ${S.unit_kwh}`;
  const grams = (value) => (value >= 1000
    ? `${number(value / 1000, 1)} ${S.unit_kg}` : `${number(value, 1)} ${S.unit_g}`);
  function duration(minutes) {
    const total = Math.round(minutes || 0);
    const hours = Math.floor(total / 60);
    return hours ? `${hours} ${S.unit_hours} ${total % 60} ${S.unit_minutes}` : `${total} ${S.unit_minutes}`;
  }
  function date(timestamp) {
    if (!timestamp) return "";
    const d = new Date(timestamp * 1000);
    const two = (n) => String(n).padStart(2, "0");
    const year = d.getFullYear() === new Date().getFullYear() ? "" : `.${d.getFullYear()}`;
    return `${two(d.getDate())}.${two(d.getMonth() + 1)}${year} ${two(d.getHours())}:${two(d.getMinutes())}`;
  }

  const STATUS = {
    completed: ["check-circle", "--success-color"],
    cancelled: ["stop-circle", "--warning-color"],
    error: ["alert-circle", "--error-color"],
    printing: ["printer-3d-nozzle", "--primary-color"],
  };
  const statusLabel = (status) => S[`status_${status}`] ?? status;
  const color = (name) => `--c:var(${name})`;
  function statusIcon(status, cls = "") {
    const [name, variable] = STATUS[status] || STATUS.error;
    return `<span class="status-icon" style="${color(variable)}" title="${e(statusLabel(status))}">${icon(name, cls)}</span>`;
  }
  const status = (value) =>
    `<span class="status">${statusIcon(value)}<span class="status-text">${e(statusLabel(value))}</span></span>`;
  function statusBadge(value) {
    const [name, variable] = STATUS[value] || STATUS.error;
    return `<span class="badge" style="${color(variable)}">${icon(name)}${e(statusLabel(value))}</span>`;
  }

  const heading = (iconName, title, side = "") => `<div class="heading">${icon(iconName)}
    <h2 class="heading-title ellipsis">${e(title)}</h2>${side ? `<div class="heading-side">${side}</div>` : ""}</div>`;
  const section = (body, cls = "") => `<section class="section ${cls}">${body}</section>`;
  const card = (body, cls = "") => `<div class="card ${cls}">${body}</div>`;
  function tile({ name, state, iconName, variable = "--state-icon-color", href }) {
    const tag = href ? "a" : "div";
    return `<${tag} class="tile"${href ? ` href="${e(href)}"` : ""}>
      <span class="tile-icon" style="${color(variable)}">${icon(iconName)}</span>
      <span class="tile-info"><span class="tile-name">${e(name)}</span>
      <span class="tile-state" title="${e(state)}">${e(state)}</span></span></${tag}>`;
  }
  function badge(text, { iconName, variable, href, cls = "", title } = {}) {
    const tag = href ? "a" : "span";
    return `<${tag} class="badge ${cls}"${href ? ` href="${e(href)}"` : ""}${variable ? ` style="${color(variable)}"` : ""}
      title="${e(title ?? text)}">${iconName ? icon(iconName) : ""}<span class="ellipsis">${e(text)}</span></${tag}>`;
  }
  function empty(iconName, text, action = "") {
    return `<div class="empty"><span class="empty-icon">${icon(iconName)}</span><span>${e(text)}</span>${action}</div>`;
  }
  const thumb = (src, cls = "thumb") => (src
    ? `<img class="${cls}" loading="lazy" alt="" src="${e(src)}">` : `<span class="${cls}">${icon("image-off-outline")}</span>`);

  const skeletonLine = (width) => `<span class="skeleton line" style="width:${width}"></span>`;
  const skeletonTile = () => `<div class="tile"><span class="skeleton circle"></span>
    <span class="tile-info" style="flex:1;gap:6px">${skeletonLine("50%")}${skeletonLine("70%")}</span></div>`;
  const skeletonRows = (count) => card(Array.from({ length: count }, () =>
    `<div class="skeleton-row"><span class="skeleton" style="width:40px;height:40px;border-radius:8px"></span>
     ${skeletonLine("24%")}${skeletonLine("32%")}${skeletonLine("12%")}</div>`).join(""));

  // One series, zero baseline. Labels are HTML so they stay sharp in a stretched plot.
  function barChart(items, { format = number, max } = {}) {
    // An even top keeps the middle label a whole number of prints.
    const peak = Math.max(2, ...items.map((item) => item.value));
    const top = max ?? peak + (peak % 2);
    const width = 100 / items.length;
    const bar = Math.min(width * 0.7, 6);
    const bars = items.map((item, i) => {
      const height = (98 * item.value) / top;
      return `<g data-chart-tip="${e(item.label)}: ${e(format(item.value))}">
        <rect class="chart-hit" x="${i * width}" y="0" width="${width}" height="100"/>
        <rect class="chart-bar" x="${i * width + (width - bar) / 2}" y="${100 - height}" width="${bar}" height="${height}"/></g>`;
    }).join("");
    const grid = [0, 50, 100].map((y) => `<line x1="0" x2="100" y1="${y}" y2="${y}" vector-effect="non-scaling-stroke"/>`).join("");
    const labels = [items[0], items[Math.floor(items.length / 2)], items[items.length - 1]];
    const axis = (items.length > 3 ? labels : items).map((item) => `<span>${e(item.label)}</span>`).join("");
    return `<div class="chart"><div class="chart-scale"><span>${e(format(top))}</span><span>${e(format(top / 2))}</span><span>${e(format(0))}</span></div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"><g class="chart-grid">${grid}</g>${bars}</svg>
      <div class="chart-axis">${axis}</div></div>`;
  }

  const statusIconName = (value) => (STATUS[value] || STATUS.error)[0];
  const statusVariable = (value) => (STATUS[value] || STATUS.error)[1];
  const setCurrency = (value) => { currency = value; };
  return {
    barChart, statusIconName, statusVariable, e, icon, number, money, percent, kwh, grams, duration, date, status, statusBadge, statusIcon, statusLabel, heading,
    section, card, tile, badge, empty, thumb, skeletonTile, skeletonRows, setCurrency,
  };
})();
