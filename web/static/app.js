"use strict";

const MAGENTA = "#e20074";
const PALETTE = ["#e20074", "#7c3aed", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#64748b", "#14b8a6", "#ec4899", "#22c55e"];
const BUCKET_ORDER = ["abgelaufen", "0-3 Mon", "3-12 Mon", ">12 Mon", "ohne"];
const BUCKET_COLOR = { "abgelaufen": "#ef4444", "0-3 Mon": "#f59e0b", "3-12 Mon": "#0ea5e9", ">12 Mon": "#10b981", "ohne": "#94a3b8" };

// Facetten: field = Datenfeld, kind = single|multi|derived
const FACETS = [
  { key: "rahmenvertrag", label: "Rahmenvertrag", kind: "single" },
  { key: "tarif", label: "Tarif", kind: "single" },
  { key: "kartentyp", label: "Kartentyp", kind: "single" },
  { key: "__multisim", label: "MultiSIM", kind: "derived", fn: (c) => [multisimBucket(c)] },
  { key: "__status", label: "Status", kind: "derived", fn: (c) => [c.sperren ? "Gesperrt" : "Aktiv"] },
  { key: "__bindefrist", label: "Bindefrist", kind: "derived", fn: (c) => [bucket(c.bindefristende)] },
  { key: "vvl_berechtigung", label: "VVL-Berechtigung", kind: "single" },
  { key: "daten_optionen", label: "Daten-Optionen", kind: "multi" },
  { key: "voice_optionen", label: "Voice-Optionen", kind: "multi" },
  { key: "roaming_optionen", label: "Roaming-Optionen", kind: "multi" },
];
const FACET_BY_KEY = Object.fromEntries(FACETS.map((f) => [f.key, f]));

const CHARTS = [
  { id: "rahmenvertrag", title: "Rahmenvertrag", type: "doughnut" },
  { id: "kartentyp", title: "Kartentyp", type: "doughnut" },
  { id: "__multisim", title: "MultiSIM", type: "bar" },
  { id: "__bindefrist", title: "Bindefrist", type: "bar" },
  { id: "tarif", title: "Tarife", type: "bar" },
  { id: "daten_optionen", title: "Daten-Optionen", type: "bar" },
  { id: "voice_optionen", title: "Voice-Optionen", type: "bar" },
  { id: "roaming_optionen", title: "Roaming-Optionen", type: "bar" },
];

const GRID_COLS = ["rufnummer", "rahmenvertrag", "kostenstellennutzer", "kostenstelle", "tarif", "bindefristende", "__status", "vvl_berechtigung"];
const COL_LABEL = { __status: "Status", __bindefrist: "Bindefrist", __multisim: "MultiSIM" };
const MS_ORDER = ["ohne", "1", "2", "3+"];

const state = {
  all: [], fields: {}, stand: null, notes: {},
  filters: {},          // key -> Set(values)
  smart: null,          // optionaler Smart-Filter {label, fn}
  search: "",
  sortCol: "bindefristende", sortDir: 1,
  drawerKey: null,
};
function noteKey(c) { return (c.rahmenvertrag || "") + "|" + (c.rufnummer || ""); }
const charts = {};

// ---- helpers --------------------------------------------------------------
function esc(v) {
  if (v == null) return "";
  return String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtDate(iso) { return iso ? String(iso).slice(0, 10) : "–"; }
function label(key) { return COL_LABEL[key] || state.fields[key] || key; }

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (res.status === 401) { showAuth("login"); throw new Error("nicht angemeldet"); }
  if (!res.ok) { let m = res.statusText; try { m = (await res.json()).detail || m; } catch (e) {} throw new Error(m); }
  return res.status === 204 ? null : res.json();
}
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 3200);
}
function bucket(iso) {
  if (!iso) return "ohne";
  const days = (new Date(String(iso).slice(0, 10)) - new Date()) / 86400000;
  if (days < 0) return "abgelaufen";
  if (days < 90) return "0-3 Mon";
  if (days < 365) return "3-12 Mon";
  return ">12 Mon";
}
// Werte eines Vertrags für eine Facette (immer Array)
function valuesOf(c, f) {
  if (f.kind === "derived") return f.fn(c);
  const v = c[f.key];
  if (v == null || v === "") return [];
  if (f.kind === "multi") return String(v).split(",").map((s) => s.trim()).filter(Boolean);
  return [String(v)];
}

// ---- filtering ------------------------------------------------------------
function passesSearch(c) {
  if (!state.search) return true;
  const q = state.search.toLowerCase();
  return ["rufnummer", "kostenstellennutzer", "kostenstelle", "tarif", "rahmenvertrag"]
    .some((k) => String(c[k] || "").toLowerCase().includes(q));
}
function multisimCount(c) {
  let n = 0;
  for (let i = 1; i <= 10; i++) { const v = c["multisim_karten_profilnummer_" + i]; if (v != null && v !== "") n++; }
  return n;
}
function multisimBucket(c) { const n = multisimCount(c); return n === 0 ? "ohne" : n >= 3 ? "3+" : String(n); }
function vvlOk(c) { return /^(j|berecht)/i.test(c.vvl_berechtigung || ""); }
function daysTo(iso) { return iso ? (new Date(String(iso).slice(0, 10)) - new Date()) / 86400000 : Infinity; }
function passesSmart(c) { return !state.smart || state.smart.fn(c); }
function passesFacets(c, ignoreKey) {
  for (const key in state.filters) {
    if (key === ignoreKey) continue;
    const sel = state.filters[key];
    if (!sel || !sel.size) continue;
    const vals = valuesOf(c, FACET_BY_KEY[key]);
    if (!vals.some((v) => sel.has(v))) return false;
  }
  return true;
}
function filtered(ignoreKey) {
  return state.all.filter((c) => passesSearch(c) && passesSmart(c) && passesFacets(c, ignoreKey));
}
function toggleFilter(key, value) {
  if (!state.filters[key]) state.filters[key] = new Set();
  const s = state.filters[key];
  s.has(value) ? s.delete(value) : s.add(value);
  if (!s.size) delete state.filters[key];
  render();
}
function clearFilters() { state.filters = {}; state.smart = null; state.search = ""; document.getElementById("search").value = ""; render(); }

// ---- aggregation ----------------------------------------------------------
function countValues(rows, f) {
  const m = new Map();
  for (const c of rows) for (const v of valuesOf(c, f)) m.set(v, (m.get(v) || 0) + 1);
  return m;
}

// ---- render ---------------------------------------------------------------
function render() {
  const rows = filtered();
  renderRvList();
  renderChips();
  renderKpis(rows);
  renderHandlungsbedarf();
  renderCharts(rows);
  renderFacets();
  renderGrid(rows);
}

function renderChips() {
  const box = document.getElementById("chips");
  const chips = [];
  if (state.search) chips.push(`<span class="chip">Suche: ${esc(state.search)} <b data-clear-search>✕</b></span>`);
  if (state.smart) chips.push(`<span class="chip smart">${esc(state.smart.label)} <b data-rm-smart>✕</b></span>`);
  for (const key in state.filters)
    for (const v of state.filters[key])
      chips.push(`<span class="chip">${esc(label(key))}: ${esc(v)} <b data-rm="${esc(key)}|${esc(v)}">✕</b></span>`);
  box.innerHTML = chips.length
    ? chips.join("") + `<button class="chip-clear" id="clearAll">alle löschen</button>`
    : `<span class="muted">Kein Filter aktiv – alle Verträge</span>`;
}

function renderKpis(rows) {
  const gesperrt = rows.filter((c) => c.sperren).length;
  const ablauf = rows.filter((c) => ["abgelaufen", "0-3 Mon"].includes(bucket(c.bindefristende))).length;
  const rvs = new Set(rows.map((c) => c.rahmenvertrag).filter(Boolean)).size;
  const kst = new Set(rows.map((c) => c.kostenstelle).filter(Boolean)).size;
  const mitMs = rows.filter((c) => multisimCount(c) > 0).length;
  const kpis = [
    ["Verträge", rows.length], ["Rahmenverträge", rvs], ["Gesperrt", gesperrt],
    ["Bindefrist ≤ 90 T", ablauf], ["mit MultiSIM", mitMs], ["Kostenstellen", kst],
  ];
  document.getElementById("kpis").innerHTML = kpis.map(([l, n]) =>
    `<div class="card"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
}

function renderHandlungsbedarf() {
  const a = state.all;
  const abg = a.filter((c) => bucket(c.bindefristende) === "abgelaufen").length;
  const bald = a.filter((c) => bucket(c.bindefristende) === "0-3 Mon").length;
  const gesp = a.filter((c) => c.sperren).length;
  const vvl2 = a.filter((c) => vvlOk(c) && daysTo(c.bindefristende) <= 60).length;
  const cards = [
    { t: "VVL fällig ≤ 2 Monate", n: vvl2, cls: "green",
      smart: { label: "VVL fällig ≤ 2 Monate", fn: (c) => vvlOk(c) && daysTo(c.bindefristende) <= 60 } },
    { t: "Bindefrist abgelaufen", n: abg, cls: "red", f: ["__bindefrist", ["abgelaufen"]] },
    { t: "Läuft in ≤ 90 Tagen aus", n: bald, cls: "amber", f: ["__bindefrist", ["0-3 Mon"]] },
    { t: "Gesperrte Verträge", n: gesp, cls: "red", f: ["__status", ["Gesperrt"]] },
  ];
  document.getElementById("handlungsbedarf").innerHTML = cards.map((c, i) =>
    `<div class="action-card ${c.cls}" data-action="${i}">
       <div class="action-num">${c.n}</div><div class="action-lbl">${c.t}</div></div>`).join("");
  document.getElementById("handlungsbedarf")._cards = cards;
}

function renderCharts(rows) {
  const box = document.getElementById("charts");
  if (!box._built) {
    box.innerHTML = CHARTS.map((c) => `<div class="chart-box small"><canvas id="ch_${c.id}"></canvas></div>`).join("");
    box._built = true;
  }
  for (const cfg of CHARTS) {
    const f = FACET_BY_KEY[cfg.id];
    let counts = countValues(rows, f);
    let labels, data, colors;
    if (cfg.id === "__bindefrist") {
      labels = BUCKET_ORDER.filter((b) => counts.get(b));
      data = labels.map((b) => counts.get(b));
      colors = labels.map((b) => BUCKET_COLOR[b]);
    } else if (cfg.id === "__multisim") {
      labels = MS_ORDER.filter((b) => counts.get(b));
      data = labels.map((b) => counts.get(b));
      colors = MAGENTA;
    } else {
      const ent = [...counts.entries()].sort((x, y) => y[1] - x[1]).slice(0, 10);
      labels = ent.map((e) => e[0]); data = ent.map((e) => e[1]);
      colors = cfg.type === "doughnut" ? PALETTE : MAGENTA;
    }
    drawChart(`ch_${cfg.id}`, cfg.type, labels, data, cfg.title, colors, cfg.id);
  }
}

function drawChart(id, type, labels, data, title, colors, facetKey) {
  if (charts[id]) charts[id].destroy();
  const ctx = document.getElementById(id);
  if (!ctx) return;
  const isPie = type === "doughnut";
  charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: isPie ? 0 : 6 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: isPie, position: "bottom", labels: { boxWidth: 12, font: { size: 10 } } },
                 title: { display: true, text: title } },
      scales: isPie ? {} : { x: { ticks: { font: { size: 10 } } }, y: { beginAtZero: true, ticks: { precision: 0 } } },
      onClick: (evt, els) => { if (els.length) toggleFilter(facetKey, labels[els[0].index]); },
    },
  });
}

function renderFacets() {
  const wrap = document.getElementById("facets");
  wrap.innerHTML = FACETS.map((f) => {
    const base = filtered(f.key);
    const counts = [...countValues(base, f).entries()].sort((a, b) => b[1] - a[1]);
    if (f.key === "__bindefrist") counts.sort((a, b) => BUCKET_ORDER.indexOf(a[0]) - BUCKET_ORDER.indexOf(b[0]));
    if (f.key === "__multisim") counts.sort((a, b) => MS_ORDER.indexOf(a[0]) - MS_ORDER.indexOf(b[0]));
    const sel = state.filters[f.key] || new Set();
    const items = counts.slice(0, 12).map(([v, n]) =>
      `<li class="${sel.has(v) ? "on" : ""}" data-facet="${esc(f.key)}" data-val="${esc(v)}">
         <span>${esc(v)}</span><span class="fc">${n}</span></li>`).join("");
    return `<div class="facet"><div class="facet-h">${esc(f.label)}</div><ul>${items || '<li class="muted">–</li>'}</ul></div>`;
  }).join("");
}

function bindefristBadge(iso) {
  const b = bucket(iso);
  const cls = { "abgelaufen": "red", "0-3 Mon": "amber", "3-12 Mon": "", ">12 Mon": "green", "ohne": "" }[b];
  return `<span class="badge ${cls}">${fmtDate(iso)}</span>`;
}

function renderGrid(rows) {
  document.getElementById("gridCount").textContent = `(${rows.length})`;
  const sc = state.sortCol;
  const sorted = [...rows].sort((a, b) => {
    let x = a[sc] ?? "", y = b[sc] ?? "";
    return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir;
  });
  const t = document.getElementById("grid");
  const head = "<th></th>" + GRID_COLS.map((c) => {
    const arrow = sc === c ? (state.sortDir > 0 ? " ▲" : " ▼") : "";
    return `<th data-sort="${esc(c)}">${esc(label(c))}${arrow}</th>`;
  }).join("");
  const body = sorted.slice(0, 500).map((c, i) => `<tr data-row="${i}">
    <td class="detail-cell"><span class="detail-btn">Details ▸</span>${state.notes[noteKey(c)] ? ' <span class="note-mark" title="Notiz vorhanden">📝</span>' : ""}</td>
    <td>${esc(c.rufnummer)}</td>
    <td>${esc(c.rahmenvertrag)}</td>
    <td>${esc(c.kostenstellennutzer)}</td>
    <td>${esc(c.kostenstelle)}</td>
    <td>${esc(c.tarif)}</td>
    <td>${bindefristBadge(c.bindefristende)}</td>
    <td>${c.sperren ? '<span class="badge red">gesperrt</span>' : '<span class="badge green">aktiv</span>'}</td>
    <td>${esc(c.vvl_berechtigung)}</td>
  </tr>`).join("");
  t.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  t._rows = sorted;
}

// ---- detail drawer --------------------------------------------------------
function groupOf(field) {
  if (field.startsWith("gp_")) return "Geschäftspartner";
  if (field.startsWith("re_")) return "Rechnungsempfänger";
  if (field.startsWith("evn_")) return "EVN-Empfänger";
  if (field.startsWith("multisim")) return "MultiSIM";
  return "Vertrag & SIM";
}
function openDrawer(contract) {
  const groups = {};
  for (const field in state.fields) {
    const v = contract[field];
    if (v == null || v === "") continue;
    const g = groupOf(field);
    (groups[g] = groups[g] || []).push([state.fields[field], v]);
  }
  const order = ["Vertrag & SIM", "MultiSIM", "Geschäftspartner", "Rechnungsempfänger", "EVN-Empfänger"];
  const html = order.filter((g) => groups[g]).map((g) =>
    `<div class="dg"><h4>${esc(g)}</h4>` +
    groups[g].map(([k, v]) => `<div class="dl"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("") + `</div>`).join("");
  const key = noteKey(contract);
  state.drawerKey = key;
  const note = state.notes[key] || "";
  const rv = contract.rahmenvertrag ? ` · ${esc(contract.rahmenvertrag)}` : "";
  document.getElementById("drawer").innerHTML =
    `<div class="drawer-head">
       <div><div class="muted">Vertrag${rv}</div><h3>${esc(contract.rufnummer)}</h3></div>
       <div class="drawer-actions">
         <button class="btn" id="drawerPrint" title="Drucken / als PDF speichern">🖨 Drucken</button>
         <button class="btn" id="drawerClose">✕</button>
       </div>
     </div>
     <div class="dg note-block">
       <h4>Notiz / Kennzeichnung</h4>
       <textarea id="noteText" placeholder="z. B. VVL angefragt, Kündigung geprüft …">${esc(note)}</textarea>
       <button class="btn" id="noteSave">Notiz speichern</button>
     </div>${html}`;
  document.getElementById("drawer").hidden = false;
  document.getElementById("drawerOverlay").hidden = false;
}
function closeDrawer() {
  document.getElementById("drawer").hidden = true;
  document.getElementById("drawerOverlay").hidden = true;
}

// ---- CSV ------------------------------------------------------------------
function exportCsv() {
  const rows = filtered();
  const cols = Object.keys(state.fields);
  const head = cols.map((c) => `"${state.fields[c].replace(/"/g, '""')}"`).join(";");
  const body = rows.map((c) => cols.map((k) => {
    const v = c[k] == null ? "" : String(c[k]).replace(/"/g, '""');
    return `"${v}"`;
  }).join(";")).join("\r\n");
  const blob = new Blob(["﻿" + head + "\r\n" + body], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `verträge_${(state.stand || "").slice(0, 10)}_${rows.length}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---- data loading ---------------------------------------------------------
async function loadData() {
  const [cur, fields, reports, notes] = await Promise.all([
    api("/api/current"), api("/api/fields"), api("/api/reports"), api("/api/notes"),
  ]);
  state.all = cur.contracts; state.fields = fields; state.stand = cur.stand; state.notes = notes;
  document.getElementById("stand").textContent = cur.stand ? "Stand: " + fmtDate(cur.stand) : "";
  renderReportList(reports);
  fillVerlaufRv(cur.rahmenvertraege);
  const empty = !state.all.length;
  document.getElementById("emptyState").hidden = !empty;
  document.getElementById("grid").hidden = empty;
  if (!empty) render(); else clearRendered();
}
function clearRendered() {
  ["chips", "kpis", "handlungsbedarf", "facets", "grid"].forEach((id) => (document.getElementById(id).innerHTML = ""));
  if (document.getElementById("charts")) { document.getElementById("charts").innerHTML = ""; document.getElementById("charts")._built = false; }
}
function renderRvList() {
  const m = new Map();
  for (const c of state.all) {
    const rv = c.rahmenvertrag || "(ohne)";
    const e = m.get(rv) || { n: 0, stand: "" };
    e.n++; const d = c._report_date || ""; if (d > e.stand) e.stand = d;
    m.set(rv, e);
  }
  const sel = state.filters["rahmenvertrag"] || new Set();
  const items = [...m.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1));
  document.getElementById("rvList").innerHTML = items.length
    ? items.map(([rv, e]) =>
        `<li data-rv="${esc(rv)}" class="${sel.has(rv) ? "on" : ""}">
           <strong>${esc(rv)}</strong>
           <div class="meta">${e.n} Verträge · Stand ${fmtDate(e.stand)}</div></li>`).join("")
    : '<li class="muted">noch keine Daten</li>';
}

function renderReportList(reports) {
  const ul = document.getElementById("reportList");
  if (!reports.length) { ul.innerHTML = '<li class="muted">noch keine</li>'; return; }
  ul.innerHTML = reports.map((r) =>
    `<li><span><strong>${fmtDate(r.report_date)}</strong> · <span class="meta">${esc(r.filename || "")}</span><br>
       <span class="meta">${r.row_count} Verträge</span></span>
       <button class="del" data-del="${r.id}" title="löschen">✕</button></li>`).join("");
}

// ---- auth -----------------------------------------------------------------
let authMode = "login";
function showAuth(mode) {
  authMode = mode;
  document.getElementById("authOverlay").hidden = false;
  document.getElementById("appMain").hidden = true;
  ["logoutBtn", "verlaufBtn", "settingsBtn"].forEach((i) => (document.getElementById(i).hidden = true));
  const setup = mode === "setup";
  document.getElementById("authTitle").textContent = setup ? "Passwort festlegen" : "Anmelden";
  document.getElementById("authHint").textContent = setup
    ? "Erstes Setup: Passwort für den Zugang festlegen (mind. 8 Zeichen)." : "Bitte Passwort eingeben.";
  document.getElementById("authPw2").hidden = !setup;
  ["authPw", "authPw2"].forEach((i) => (document.getElementById(i).value = ""));
  document.getElementById("authError").textContent = "";
  document.getElementById("authPw").focus();
}
function showApp() {
  document.getElementById("authOverlay").hidden = true;
  document.getElementById("appMain").hidden = false;
  ["logoutBtn", "verlaufBtn", "settingsBtn"].forEach((i) => (document.getElementById(i).hidden = false));
  loadData();
}
async function submitAuth() {
  const pw = document.getElementById("authPw").value;
  const err = document.getElementById("authError"); err.textContent = "";
  try {
    if (authMode === "setup") {
      const pw2 = document.getElementById("authPw2").value;
      if (pw.length < 8) { err.textContent = "Mindestens 8 Zeichen."; return; }
      if (pw !== pw2) { err.textContent = "Passwörter stimmen nicht überein."; return; }
      await api("/api/auth/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
    } else {
      const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
      if (!res.ok) { err.textContent = "Falsches Passwort."; return; }
    }
    showApp();
  } catch (e) { err.textContent = e.message || "Fehler."; }
}
async function init() {
  try {
    const st = await api("/api/auth/status");
    if (!st.configured) showAuth("setup");
    else if (!st.authenticated) showAuth("login");
    else showApp();
  } catch (e) { showAuth("login"); }
}

// ---- verlauf (per RV) -----------------------------------------------------
function fillVerlaufRv(rvs) {
  document.getElementById("verlaufRv").innerHTML = (rvs || []).map((r) => `<option>${esc(r)}</option>`).join("");
}
async function showVerlauf() {
  document.getElementById("verlaufOverlay").hidden = false;
  // einfacher Verlauf über alle Trend-Punkte (serverseitig)
  const data = await api("/api/trend");
  const labels = data.map((d) => fmtDate(d.report_date));
  if (charts.verlauf) charts.verlauf.destroy();
  charts.verlauf = new Chart(document.getElementById("chartVerlauf"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Verträge", data: data.map((d) => d.total), borderColor: MAGENTA, tension: .2 },
      { label: "gesperrt", data: data.map((d) => d.gesperrt), borderColor: PALETTE[2], tension: .2 },
      { label: "Bindefrist ≤ 90 T", data: data.map((d) => d.ablaufend_90), borderColor: PALETTE[4], tension: .2 },
    ] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
  });
}

// ---- events ---------------------------------------------------------------
document.getElementById("authSubmit").addEventListener("click", submitAuth);
["authPw", "authPw2"].forEach((i) => document.getElementById(i).addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); }));

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  state.all = []; state.filters = {}; showAuth("login");
});

document.getElementById("search").addEventListener("input", (e) => { state.search = e.target.value.trim(); render(); });

document.getElementById("fileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const fd = new FormData(); fd.append("file", file);
  try { const r = await api("/api/reports", { method: "POST", body: fd }); toast(`Importiert: ${r.row_count} Verträge`); await loadData(); }
  catch (err) { toast("Upload fehlgeschlagen: " + err.message, true); }
  e.target.value = "";
});

document.getElementById("rvList").addEventListener("click", (e) => {
  const li = e.target.closest("[data-rv]");
  if (li && li.dataset.rv !== "(ohne)") toggleFilter("rahmenvertrag", li.dataset.rv);
});

document.getElementById("settingsBtn").addEventListener("click", () => { document.getElementById("settingsOverlay").hidden = false; });
document.getElementById("settingsClose").addEventListener("click", () => { document.getElementById("settingsOverlay").hidden = true; });
document.getElementById("settingsOverlay").addEventListener("click", (e) => { if (e.target.id === "settingsOverlay") e.currentTarget.hidden = true; });

document.getElementById("reportList").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]"); if (!del) return;
  if (!confirm("Diesen Report löschen?")) return;
  await api(`/api/reports/${del.dataset.del}`, { method: "DELETE" });
  toast("Report gelöscht"); await loadData();
});

document.getElementById("chips").addEventListener("click", (e) => {
  if (e.target.id === "clearAll") return clearFilters();
  if (e.target.hasAttribute("data-rm-smart")) { state.smart = null; return render(); }
  if (e.target.hasAttribute("data-clear-search")) { state.search = ""; document.getElementById("search").value = ""; return render(); }
  const rm = e.target.getAttribute("data-rm");
  if (rm) { const [k, v] = rm.split("|"); toggleFilter(k, v); }
});

document.getElementById("facets").addEventListener("click", (e) => {
  const li = e.target.closest("[data-facet]"); if (li) toggleFilter(li.dataset.facet, li.dataset.val);
});

document.getElementById("handlungsbedarf").addEventListener("click", (e) => {
  const card = e.target.closest("[data-action]"); if (!card) return;
  const cfg = document.getElementById("handlungsbedarf")._cards[+card.dataset.action];
  if (cfg.smart) { state.smart = cfg.smart; return render(); }
  if (cfg.f) { const [key, vals] = cfg.f; state.filters[key] = new Set(vals); render(); }
});

document.getElementById("grid").addEventListener("click", (e) => {
  const th = e.target.closest("[data-sort]");
  if (th) { const c = th.dataset.sort; state.sortDir = state.sortCol === c ? -state.sortDir : 1; state.sortCol = c; return render(); }
  const tr = e.target.closest("[data-row]");
  if (tr) openDrawer(document.getElementById("grid")._rows[+tr.dataset.row]);
});

document.getElementById("drawer").addEventListener("click", async (e) => {
  if (e.target.id === "drawerClose") return closeDrawer();
  if (e.target.id === "drawerPrint") return window.print();
  if (e.target.id === "noteSave") {
    const key = state.drawerKey;
    const v = document.getElementById("noteText").value;
    try {
      await api("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, note: v }) });
      if (v && v.trim()) state.notes[key] = v.trim(); else delete state.notes[key];
      toast("Notiz gespeichert");
      renderGrid(filtered());  // Marker aktualisieren, Drawer bleibt offen
    } catch (err) { toast("Speichern fehlgeschlagen: " + err.message, true); }
  }
});
document.getElementById("drawerOverlay").addEventListener("click", closeDrawer);
document.getElementById("csvBtn").addEventListener("click", exportCsv);
document.getElementById("verlaufBtn").addEventListener("click", showVerlauf);
document.getElementById("verlaufClose").addEventListener("click", () => (document.getElementById("verlaufOverlay").hidden = true));
document.getElementById("verlaufOverlay").addEventListener("click", (e) => { if (e.target.id === "verlaufOverlay") e.currentTarget.hidden = true; });

init();
