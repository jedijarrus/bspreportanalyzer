"use strict";

const MAGENTA = "#e20074";
const DATA_COLOR = "#475569";  // neutraler Datenton (Slate) — Magenta nur als Akzent
const PALETTE = ["#475569", "#0ea5e9", "#10b981", "#f59e0b", "#7c3aed", "#ef4444", "#14b8a6", "#64748b", "#22c55e", "#e20074"];
const BUCKET_ORDER = ["abgelaufen", "0-3 Mon", "3-12 Mon", ">12 Mon", "ohne"];
const BUCKET_COLOR = { "abgelaufen": "#ef4444", "0-3 Mon": "#f59e0b", "3-12 Mon": "#0ea5e9", ">12 Mon": "#10b981", "ohne": "#94a3b8" };

// Facetten: field = Datenfeld, kind = single|multi|derived
const FACETS = [
  { key: "rahmenvertrag", label: "Rahmenvertrag", kind: "single" },
  { key: "tarif", label: "Tarif", kind: "single" },
  { key: "kartentyp", label: "Kartentyp", kind: "single" },
  { key: "__multisim", label: "MultiSIM", kind: "derived", fn: (c) => [multisimBucket(c)] },
  { key: "__auslastung", label: "Datenauslastung", kind: "derived", fn: (c) => [auslastungBucket(c._auslastung_pct)] },
  { key: "__status", label: "Status", kind: "derived", fn: (c) => [c.sperren ? "Gesperrt" : "Aktiv"] },
  { key: "__bindefrist", label: "Bindefrist", kind: "derived", fn: (c) => [bucket(c.bindefristende)] },
  { key: "vvl_berechtigung", label: "VVL-Berechtigung", kind: "single" },
  { key: "daten_optionen", label: "Daten-Optionen", kind: "multi" },
  { key: "voice_optionen", label: "Voice-Optionen", kind: "multi" },
  { key: "roaming_optionen", label: "Roaming-Optionen", kind: "multi" },
  { key: "__kosten", label: "Monatskosten", kind: "derived", fn: (c) => [kostenBucket(c._kosten_netto)] },
  { key: "__rabatt", label: "Rabatt", kind: "derived", fn: (c) => [c._rabatt ? "mit Rabatt" : "ohne"] },
];
const KOSTEN_ORDER = ["< 25 €", "25–75 €", "75–150 €", "> 150 €", "ohne"];
function kostenBucket(v) {
  if (v == null) return "ohne";
  if (v < 25) return "< 25 €";
  if (v < 75) return "25–75 €";
  if (v < 150) return "75–150 €";
  return "> 150 €";
}
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

const GRID_COLS = ["rufnummer", "rahmenvertrag", "kostenstellennutzer", "kostenstelle", "tarif", "_kosten_netto", "_rabatt", "_auslastung_pct", "bindefristende", "__status", "vvl_berechtigung"];
const MONEY_COLS = new Set(["_kosten_netto", "_rabatt"]);
const COL_LABEL = { __status: "Status", __bindefrist: "Bindefrist", __multisim: "MultiSIM",
  _kosten_netto: "Monatskosten", _rabatt: "Rabatt", _auslastung_pct: "Datenauslastung",
  __kosten: "Monatskosten", __rabatt: "Rabatt", __auslastung: "Datenauslastung" };
const AUSLASTUNG_ORDER = ["< 10 %", "10–25 %", "25–50 %", "50–100 %", "> 100 %", "keine"];
function auslastungBucket(p) {
  if (p == null) return "keine";
  if (p < 10) return "< 10 %";
  if (p < 25) return "10–25 %";
  if (p < 50) return "25–50 %";
  if (p <= 100) return "50–100 %";
  return "> 100 %";
}
const MS_ORDER = ["ohne", "1", "2", "3+"];

const state = {
  all: [], fields: {}, stand: null, notes: {}, invoices: [],
  filters: {},          // key -> Set(values)
  smart: null,          // optionaler Smart-Filter {label, fn}
  search: "",
  sortCol: "bindefristende", sortDir: 1,
  drawerKey: null,
  brutto: false, bruttoFactor: 1.19, rechnungStand: null,
  route: "vertraege",
};

// Betrag ggf. auf Brutto umrechnen
function moneyNum(v) { return v == null ? 0 : (state.brutto ? v * state.bruttoFactor : v); }
function money(v) {
  return v == null ? "–" : moneyNum(v).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
}
// Roh-Euro OHNE Netto/Brutto-Skalierung — für echte, gespeicherte Rechnungsbeträge
// (total_net/tax/gross), die exakt der Telekom-Rechnung entsprechen müssen.
function fmtEur(v) {
  return v == null ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
}
function pct(v, dec = 0) { return (v > 0 ? "+" : "") + v.toFixed(dec) + " %"; }
// Δ-Anzeige: Kostensteigerung = amber/rot (Achtung), Senkung = grün
function deltaBadge(v, pctVal, fmt = money) {
  if (v == null) return "–";
  const cls = v > 0 ? "delta-up" : v < 0 ? "delta-down" : "";
  const arrow = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `<span class="delta ${cls}">${arrow} ${fmt(Math.abs(v))}${pctVal != null ? " (" + pct(pctVal) + ")" : ""}</span>`;
}
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
  renderUsageBar();
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
  const kostenSum = rows.reduce((a, c) => a + (c._kosten_netto || 0), 0);
  const kpis = [
    ["Verträge", rows.length], ["Kosten / Monat", money(kostenSum)], ["Rahmenverträge", rvs],
    ["Gesperrt", gesperrt], ["Bindefrist ≤ 90 T", ablauf], ["mit MultiSIM", mitMs],
  ];
  document.getElementById("kpis").innerHTML = kpis.map(([l, n]) =>
    `<div class="card"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");
}

function renderUsageBar() {
  const box = document.getElementById("usageBar");
  const a = state.auslastung;
  if (!a || !a.anzahl) { box.innerHTML = ""; return; }
  const p = a.auslastung_pct;
  const cls = p < 40 ? "low" : p < 80 ? "mid" : "high";
  box.innerHTML = `
    <div class="usage-bar">
      <div class="usage-head">
        <span>Datenauslastung Flotte <span class="muted">(Rechnung ${fmtDate(state.rechnungStand)})</span></span>
        <b>${a.verbraucht_gb.toLocaleString("de-DE")} / ${a.gebucht_gb.toLocaleString("de-DE")} GB · ${p} %</b>
      </div>
      <div class="meter" title="${p}% des gebuchten Volumens genutzt"><div class="meter-fill ${cls}" style="width:${Math.min(100, p)}%"></div></div>
      <div class="usage-foot muted">${a.unter_25} Verträge &lt; 25 % genutzt (Downgrade-Potenzial) · ${a.ueber_100} Overage (&gt; 100 %)</div>
    </div>`;
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
    if (f.key === "__kosten") counts.sort((a, b) => KOSTEN_ORDER.indexOf(a[0]) - KOSTEN_ORDER.indexOf(b[0]));
    if (f.key === "__auslastung") counts.sort((a, b) => AUSLASTUNG_ORDER.indexOf(a[0]) - AUSLASTUNG_ORDER.indexOf(b[0]));
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
    ${GRID_COLS.map((col) => `<td class="${MONEY_COLS.has(col) ? "money" : ""}">${gridCell(c, col)}</td>`).join("")}
  </tr>`).join("");
  t.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  t._rows = sorted;
}

function gridCell(c, col) {
  if (col === "bindefristende") return bindefristBadge(c.bindefristende);
  if (col === "__status") return c.sperren ? '<span class="badge red">gesperrt</span>' : '<span class="badge green">aktiv</span>';
  if (col === "_auslastung_pct") {
    const p = c._auslastung_pct;
    if (p == null) return '<span class="muted">–</span>';
    const cls = p < 40 ? "low" : p <= 100 ? "mid" : "high";
    return `<div class="row-meter"><div class="mini-meter"><div class="mini-fill ${cls}" style="width:${Math.min(100, p)}%"></div></div><span class="mini-pct">${p}%</span></div>`;
  }
  if (MONEY_COLS.has(col)) return c[col] == null ? "–" : money(c[col]);
  return esc(c[col]);
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
  state.drawerRuf = contract.rufnummer;
  const note = state.notes[key] || "";
  const rv = contract.rahmenvertrag ? ` · ${esc(contract.rahmenvertrag)}` : "";
  document.getElementById("drawer").innerHTML =
    `<div class="drawer-head">
       <div><div class="muted">Vertrag${rv}</div><h3>${esc(contract.rufnummer)}</h3></div>
       <div class="drawer-actions">
         <button class="btn" id="drawerVerlauf" title="Monitoring über Monate">Verlauf</button>
         <button class="btn" id="drawerPrint" title="Drucken / als PDF speichern">🖨 Drucken</button>
         <button class="btn" id="drawerClose">✕</button>
       </div>
     </div>
     <div class="dg note-block">
       <h4>Notiz / Kennzeichnung</h4>
       <textarea id="noteText" placeholder="z. B. VVL angefragt, Kündigung geprüft …">${esc(note)}</textarea>
       <button class="btn" id="noteSave">Notiz speichern</button>
     </div>
     <div class="dg" id="drawerKosten"><h4>Kosten (Monat)</h4>
       ${contract._kosten_netto != null ? '<div class="hint">lade …</div>'
         : '<div class="hint">keine Rechnungsdaten für diese Rufnummer</div>'}
     </div>
     ${contract._auslastung_pct != null ? `<div class="dg"><h4>Datenauslastung</h4>
       <div class="dl"><span>genutzt / gebucht</span><b>${contract._data_used_gb} / ${contract._data_contracted_gb} GB</b></div>
       <div class="row-meter"><div class="mini-meter" style="max-width:none"><div class="mini-fill ${contract._auslastung_pct < 40 ? "low" : contract._auslastung_pct <= 100 ? "mid" : "high"}" style="width:${Math.min(100, contract._auslastung_pct)}%"></div></div><span class="mini-pct">${contract._auslastung_pct}%</span></div>
     </div>` : ""}${html}`;
  document.getElementById("drawer").hidden = false;
  document.getElementById("drawerOverlay").hidden = false;
  if (contract._kosten_netto != null) loadDrawerKosten(contract.rufnummer);
}

async function loadDrawerKosten(rufnummer) {
  try {
    const lines = await api(`/api/costs/lines/${encodeURIComponent(rufnummer)}`);
    const box = document.getElementById("drawerKosten");
    if (!box) return;
    const sum = (cat) => lines.filter((l) => l.category === cat).reduce((a, l) => a + (l.amount || 0), 0);
    const grund = sum("grundpreis"), opt = sum("option"), verb = sum("verbrauch"), rab = sum("rabatt");
    const netto = grund + opt + verb + rab;
    const row = (lbl, val, cls = "") => `<div class="krow ${cls}"><span>${lbl}</span><b>${money(val)}</b></div>`;
    let bd = row("Grundpreis", grund);
    if (opt) bd += row("Optionen", opt);
    if (verb) bd += row("Verbrauch", verb);
    if (rab) bd += row("Rabatt", rab, "rabatt");
    bd += row("Effektiv (netto)", netto, "total");
    const items = lines.filter((l) => l.amount).map((l) =>
      `<div class="dl"><span>${esc(l.item_name)} <span class="cat cat-${esc(l.category)}">${esc(l.category)}</span></span><b>${money(l.amount)}</b></div>`).join("");
    box.innerHTML = `<h4>Kosten (Monat)</h4>${bd}` +
      (items ? `<details class="kitems"><summary>Einzelpositionen (${lines.filter((l) => l.amount).length})</summary>${items}</details>` : "");
  } catch (e) { /* Drawer bleibt nutzbar */ }
}
function closeDrawer() {
  document.getElementById("drawer").hidden = true;
  document.getElementById("drawerOverlay").hidden = true;
}

// ---- CSV ------------------------------------------------------------------
function exportCsv() {
  const rows = filtered();
  const cols = Object.keys(state.fields);
  const extra = { _kosten_netto: "Monatskosten netto", _rabatt: "Rabatt", _grundpreis: "Grundpreis" };
  const allCols = [...cols, ...Object.keys(extra)];
  const head = allCols.map((c) => `"${(state.fields[c] || extra[c]).replace(/"/g, '""')}"`).join(";");
  const body = rows.map((c) => allCols.map((k) => {
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
  const [cur, fields, reports, notes, invoices] = await Promise.all([
    api("/api/current"), api("/api/fields"), api("/api/reports"), api("/api/notes"),
    api("/api/invoices"),
  ]);
  state.all = cur.contracts; state.fields = fields; state.stand = cur.stand; state.notes = notes;
  state.invoices = invoices; state.rahmenvertraege = cur.rahmenvertraege;
  state.bruttoFactor = cur.brutto_factor || 1.19; state.rechnungStand = cur.rechnung_stand;
  state.auslastung = cur.datenauslastung;
  state.frische = cur.frische || {}; state.stale = cur.stale;
  state.standAlterTage = cur.stand_alter_tage; state.maxAgeTage = cur.max_age_tage;
  renderStaleBadge();
  renderReportList(reports);
  renderInvoiceList(invoices);
  navigate();
}

// Globales Frische-Signal im Header: neuester Report älter als das Fenster.
// Nur Warnung — es wird nichts ausgeblendet (Fallback bleibt der neueste Report).
function renderStaleBadge() {
  const el = document.getElementById("staleBadge");
  if (!el) return;
  if (state.stale && state.standAlterTage != null) {
    el.textContent = `⚠ ${state.standAlterTage} Tage alt`;
    el.title = `Neuester Report ist älter als ${state.maxAgeTage} Tage — es gibt nichts Neueres.`;
    el.hidden = false;
  } else {
    el.hidden = true;
  }
}

function renderVertraege() {
  const empty = !state.all.length;
  document.getElementById("emptyState").hidden = !empty;
  document.getElementById("grid").hidden = empty;
  if (!empty) render(); else clearRendered();
}

// ---- Router ---------------------------------------------------------------
function currentRoute() {
  const [name, param] = location.hash.replace(/^#\/?/, "").split("/");
  return { name: ["vertraege", "rechnungen", "controlling"].includes(name) ? name : "vertraege", param };
}
function navigate() {
  if (!Array.isArray(state.all)) return;
  const m = location.hash.match(/^#\/linie\/(.+)$/);
  if (m) {
    if (!state.route) renderBase("vertraege");   // Hintergrund für Deep-Link
    openLinie(decodeURIComponent(m[1]));
    return;
  }
  hideLinie();
  const r = currentRoute();
  state.baseHash = location.hash || "#/vertraege";
  renderBase(r.name, r.param);
}
function renderBase(name, param) {
  state.route = name;
  document.querySelectorAll(".navtab").forEach((t) => t.classList.toggle("active", t.dataset.route === name));
  ["vertraege", "rechnungen", "controlling"].forEach((v) =>
    document.getElementById("view-" + v).hidden = v !== name);
  // Suche/Netto-Brutto nur in Verträgen relevant -> Suche ausblenden ausserhalb
  document.querySelector(".topbar-mid").style.visibility = (name === "vertraege" || name === "controlling") ? "visible" : "hidden";
  // Netto/Brutto-Umschalter auf Rechnungen ausblenden — dort gelten die echten Rechnungsbeträge (fmtEur)
  document.getElementById("netbrutto").style.visibility = name === "rechnungen" ? "hidden" : "visible";
  if (name === "vertraege") renderVertraege();
  else if (name === "rechnungen") renderRechnungen(param);
  else if (name === "controlling") renderControlling();
}
window.addEventListener("hashchange", navigate);
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
  const fr = state.frische || {};
  document.getElementById("rvList").innerHTML = items.length
    ? items.map(([rv, e]) => {
        const stale = fr[rv] && fr[rv].stale;
        const tag = stale ? ` <span class="tag-stale" title="älter als ${state.maxAgeTage} Tage">veraltet</span>` : "";
        return `<li data-rv="${esc(rv)}" class="${sel.has(rv) ? "on" : ""}">
           <strong>${esc(rv)}</strong>
           <div class="meta">${e.n} Verträge · Stand ${fmtDate(e.stand)}${tag}</div></li>`;
      }).join("")
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

function renderInvoiceList(invoices) {
  const ul = document.getElementById("invoiceList");
  if (!invoices.length) { ul.innerHTML = '<li class="muted">noch keine</li>'; return; }
  ul.innerHTML = invoices.map((r) =>
    `<li><span><strong>${fmtDate(r.period_start)}</strong> · <span class="meta">Nr. ${esc(r.invoice_number || "")}</span><br>
       <span class="meta">${money(r.total_net)} netto · ${r.line_count} Positionen</span></span>
       <button class="del" data-delinv="${r.id}" title="löschen">✕</button></li>`).join("");
}

// ---- auth -----------------------------------------------------------------
let authMode = "login";
function showAuth(mode) {
  authMode = mode;
  document.getElementById("authOverlay").hidden = false;
  document.getElementById("appMain").hidden = true;
  ["logoutBtn", "settingsBtn", "netbrutto", "mainnav"].forEach((i) => (document.getElementById(i).hidden = true));
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
  ["logoutBtn", "settingsBtn", "netbrutto", "mainnav"].forEach((i) => (document.getElementById(i).hidden = false));
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

// ===== Bereich 2: Rechnungen ==============================================
async function renderRechnungen(param) {
  const pane = document.getElementById("view-rechnungen");
  if (param) return renderRechnung(pane, +param);
  const invs = state.invoices;
  if (!invs.length) {
    pane.innerHTML = '<div class="page"><h1 class="page-title">Rechnungen</h1><div class="empty">Noch keine Rechnung geladen — lade oben eine Rechnung (.csv).</div></div>';
    return;
  }
  const rows = invs.map((r, i) => ({ r, delta: i > 0 ? r.total_net - invs[i - 1].total_net : null })).reverse();
  pane.innerHTML = `
    <div class="page">
      <h1 class="page-title">Rechnungen <span class="muted">· ${invs.length}</span></h1>
      <div class="table-wrap"><table class="grid-table">
        <thead><tr>
          <th>Zeitraum</th><th>Nr.</th><th>Ausgestellt</th>
          <th class="money">Netto</th><th class="money">USt</th><th class="money">Brutto</th>
          <th class="num">Pos.</th><th class="money">Δ Vormonat</th></tr></thead>
        <tbody>${rows.map(({ r, delta }) => `
          <tr data-invid="${r.id}">
            <td><strong>${fmtDate(r.period_start)}</strong></td>
            <td>${esc(r.invoice_number || "")}</td>
            <td>${fmtDate(r.issue_date)}</td>
            <td class="money">${fmtEur(r.total_net)}</td>
            <td class="money">${fmtEur(r.total_tax)}</td>
            <td class="money">${fmtEur(r.total_gross)}</td>
            <td class="num">${r.line_count}</td>
            <td class="money">${delta == null ? "–" : deltaBadge(delta, null, fmtEur)}</td>
          </tr>`).join("")}</tbody>
      </table></div>
    </div>`;
}

async function renderRechnung(pane, id) {
  pane.innerHTML = '<div class="page"><a class="back" href="#/rechnungen">← Alle Rechnungen</a><div class="hint">lade …</div></div>';
  const d = await api(`/api/invoices/${id}`);
  const inv = d.invoice, rec = d.reconcile, diff = d.diff;
  const dNet = diff ? diff.gesamt.delta : null;
  const dPct = diff && diff.gesamt.alt ? (dNet / diff.gesamt.alt) * 100 : null;
  const dl = (l, v, cls = "") => `<div class="dl ${cls}"><span>${esc(l)}</span><b>${fmtEur(v)}</b></div>`;
  const katSum = d.kategorie.reduce((a, [, v]) => a + Math.abs(v), 0) || 1;
  const anom = diff ? [
    diff.neu.length ? `<div class="dl"><span>neu berechnet</span><b>${diff.neu.length}</b></div>` : "",
    diff.weggefallen.length ? `<div class="dl"><span>weggefallen</span><b>${diff.weggefallen.length}</b></div>` : "",
    ...diff.je_rufnummer.slice(0, 5).filter((x) => x.delta).map((x) => `<div class="dl"><span>${esc(x.rufnummer)}</span><b>${deltaBadge(x.delta, null, fmtEur)}</b></div>`),
  ].join("") : '<span class="hint">keine Vorrechnung</span>';
  const au = d.datenauslastung;
  pane.innerHTML = `
    <div class="page">
      <a class="back" href="#/rechnungen">← Alle Rechnungen</a>
      <div class="inv-head">
        <div class="inv-kopf">
          <h1 class="page-title">Rechnung ${esc(inv.invoice_number || "")}</h1>
          <div class="dl"><span>Zeitraum</span><b class="plain">${fmtDate(inv.period_start)} – ${fmtDate(inv.period_end)}</b></div>
          <div class="dl"><span>Ausgestellt</span><b class="plain">${fmtDate(inv.issue_date)}</b></div>
          ${dl("Netto", inv.total_net)}
          ${dl("USt", inv.total_tax)}
          ${dl("Brutto", inv.total_gross, "total")}
          <div class="dl rec"><span>Zuordnung</span><b>${fmtEur(rec.zugeordnet)} · Rest ${fmtEur(rec.nicht_zugeordnet)}</b></div>
        </div>
        <div class="inv-delta ${dNet > 0 ? "delta-up" : dNet < 0 ? "delta-down" : ""}">
          <div class="muted">Δ zum Vormonat${d.prev_period ? " (" + fmtDate(d.prev_period) + ")" : ""}</div>
          <div class="delta-big">${dNet == null ? "–" : (dNet > 0 ? "+" : "") + fmtEur(dNet)}</div>
          ${dPct != null ? `<div class="muted">${pct(dPct, 1)}</div>` : ""}
        </div>
      </div>
      <div class="panel-grid">
        <div class="card2"><h3>Nach Kategorie</h3>${d.kategorie.map(([k, v]) => `<div class="dl"><span><span class="cat cat-${esc(k)}">${esc(k)}</span></span><b>${fmtEur(v)} <span class="muted">${Math.round(Math.abs(v) / katSum * 100)}%</span></b></div>`).join("")}</div>
        <div class="card2"><h3>Nach Rahmenvertrag</h3>${(d.je_rahmenvertrag || []).map((x) => `<div class="dl"><span>${esc(x.rahmenvertrag)} <span class="muted">· ${x.anzahl}</span></span><b>${fmtEur(x.netto)}</b></div>`).join("")}</div>
        <div class="card2"><h3>Top-Kostentreiber <span class="muted">(Mitarbeiter)</span></h3>${d.top_treiber.slice(0, 8).map((t) => `<div class="dl"><span>${esc(t.nutzer || t.rufnummer)}</span><b>${fmtEur(t.netto)}</b></div>`).join("")}</div>
        <div class="card2"><h3>Auffälligkeiten (Δ)</h3>${anom}</div>
        <div class="card2"><h3>Datenauslastung</h3>
          <div class="dl"><span>Gesamt-Auslastung</span><b>${au.auslastung_pct}%</b></div>
          <div class="dl"><span>gebucht / verbraucht</span><b>${au.gebucht_gb.toLocaleString("de-DE")} / ${au.verbraucht_gb.toLocaleString("de-DE")} GB</b></div>
          <div class="dl"><span>Downgrade-Kandidaten (&lt; 25%)</span><b class="warn">${au.unter_25}</b></div>
          <div class="dl"><span>Overage (&gt; 100%)</span><b>${au.ueber_100}</b></div>
        </div>
      </div>
    </div>`;
}

// ===== Bereich 3: Controlling =============================================
async function renderControlling() {
  const pane = document.getElementById("view-controlling");
  const invoices = state.invoices || [];
  if (!invoices.length) {
    pane.innerHTML = '<div class="page"><h1 class="page-title">Controlling</h1><div class="empty">Noch keine Rechnung geladen.</div></div>';
    return;
  }
  const sel = invoices.find((i) => i.id === state.ctrlInvoiceId) || invoices[invoices.length - 1];
  state.ctrlInvoiceId = sel.id;
  state.ctrlPeriod = sel.period_start;   // gewählter Monat -> Default beim Öffnen einer Linie
  const selIdx = invoices.indexOf(sel);
  const monthSel = `<span class="month-nav"><button class="btn btn-xs" id="ctrlPrev"${selIdx <= 0 ? " disabled" : ""}>‹</button><select id="ctrlMonth">${invoices.map((i) => `<option value="${i.id}"${i.id === sel.id ? " selected" : ""}>${fmtDate(i.period_start)}</option>`).join("")}</select><button class="btn btn-xs" id="ctrlNext"${selIdx >= invoices.length - 1 ? " disabled" : ""}>›</button></span>`;
  const [d, trend] = await Promise.all([
    api(`/api/invoices/${sel.id}`), api("/api/costs/trend")]);
  const inv = d.invoice, rec = d.reconcile, diff = d.diff;
  const dNet = diff ? diff.gesamt.delta : null;
  const dPct = diff && diff.gesamt.alt ? (dNet / diff.gesamt.alt) * 100 : null;
  const nSim = rec.anzahl_rufnummern || 1;
  const gb = d.gb_trend || [];
  const gbLatest = gb.length ? gb[gb.length - 1].gb : null;
  const gbPrev = gb.length > 1 ? gb[gb.length - 2].gb : null;
  const dGb = (gbLatest != null && gbPrev != null) ? gbLatest - gbPrev : null;
  const kpis = [
    ["Netto Monat", fmtEur(inv.total_net), dNet != null ? deltaBadge(dNet, dPct, fmtEur) : ""],
    ["Ø je Vertrag", money(inv.total_net / nSim), ""],
    ["Verträge", String(state.all.length), ""],
    ["Zuordnung", `${rec.anzahl_rufnummern} / ${state.all.length}`, ""],
    ["GB Flotte (Monat)", gbLatest != null ? gbLatest.toLocaleString("de-DE") + " GB" : "–",
      dGb != null ? `<span class="delta">${dGb >= 0 ? "▲" : "▼"} ${Math.abs(dGb).toLocaleString("de-DE")} GB</span>` : ""],
  ];
  const rv = d.je_rahmenvertrag || [];
  const changes = ((diff && diff.je_rufnummer) || []).filter((r) => r.delta !== 0).slice(0, 12);
  const changeBody = !diff
    ? '<div class="hint">erste Rechnung — kein Vormonatsvergleich</div>'
    : (changes.length
        ? `<table class="grid-table"><thead><tr><th>Rufnummer</th><th class="money">Vormonat</th><th class="money">Aktuell</th><th class="money">Δ</th></tr></thead><tbody>${changes.map((r) => `<tr class="linie-open" data-goto-ruf="${esc(r.rufnummer)}" title="Monitoring öffnen"><td>${esc(r.rufnummer)}</td><td class="money">${money(r.alt)}</td><td class="money">${money(r.neu)}</td><td class="money">${deltaBadge(r.delta, r.alt ? r.delta / r.alt * 100 : null)}</td></tr>`).join("")}</tbody></table>`
        : '<div class="hint">keine Kostenänderungen ggü. Vormonat</div>');
  const zl = d.zuordnungsluecken || { geister: [], ohne_rechnung: [] };
  const chip = (r) => `<span class="chip linie-open" data-goto-ruf="${esc(r)}">${esc(r)}</span>`;
  const zlHtml = (zl.geister.length || zl.ohne_rechnung.length)
    ? `<div class="hint" style="margin-bottom:10px">Kann normal sein — z. B. Anschluss nach dem Report dazugekommen/gekündigt oder kein passender (älterer) Report vorhanden.</div>
       <div class="zl-block"><div class="zl-lbl">Rechnung ohne Vertrag im aktuellen Report · ${zl.geister.length}</div><div class="badge-row">${zl.geister.slice(0, 40).map(chip).join(" ") || '<span class="muted">keine</span>'}</div></div>
       <div class="zl-block"><div class="zl-lbl">Vertrag ohne Rechnungsposition · ${zl.ohne_rechnung.length}</div><div class="badge-row">${zl.ohne_rechnung.slice(0, 40).map(chip).join(" ") || '<span class="muted">keine</span>'}</div></div>`
    : '<div class="hint">keine Zuordnungslücken — Rechnung und Report passen zusammen</div>';

  pane.innerHTML = `
    <div class="page">
      <h1 class="page-title">Controlling ${monthSel}</h1>
      <div class="kpis">${kpis.map(([l, v, dd]) => `<div class="card"><div class="num">${v}</div><div class="lbl">${l}${dd ? " · " + dd : ""}</div></div>`).join("")}</div>

      <div class="section-title">Was hat sich geändert? <span class="muted">(Netto je Linie ggü. Vormonat · Zeile klicken = Monitoring)</span></div>
      <div class="table-wrap" style="max-height:360px;overflow:auto">${changeBody}</div>

      <div class="section-grid">
        <div>
          <div class="section-title">Datenverbrauch der Flotte <span class="muted">(GB je Monat)</span></div>
          ${gb.length ? '<div class="chart-box" style="height:260px"><canvas id="ctrlGb"></canvas></div>' : '<div class="hint">Kein Datenverbrauch in den Rechnungen erfasst.</div>'}
        </div>
        <div>
          <div class="section-title">Kosten pro Monat <span class="muted">(Netto je Rechnung)</span></div>
          <div class="chart-box" style="height:260px"><canvas id="ctrlTrend"></canvas></div>
        </div>
      </div>

      <div class="section-grid">
        <div>
          <div class="section-title">Top-Kostentreiber <span class="muted">(dieser Monat · Zeile klicken = Monitoring)</span></div>
          <div class="table-wrap"><table class="grid-table"><thead><tr><th>Mitarbeiter</th><th>Rufnummer</th><th class="money">Netto</th></tr></thead>
            <tbody>${d.top_treiber.map((t) => `<tr class="linie-open" data-goto-ruf="${esc(t.rufnummer)}" title="Monitoring öffnen"><td>${esc(t.nutzer || "–")}</td><td>${esc(t.rufnummer)}</td><td class="money">${money(t.netto)}</td></tr>`).join("")}</tbody></table></div>
        </div>
        <div>
          <div class="section-title">Top-Kostentreiber gesamt <span class="muted">(alle Rechnungen · je Rufnummer · Zeile klicken = Monitoring)</span></div>
          <div class="table-wrap"><table class="grid-table"><thead><tr><th>Mitarbeiter</th><th>Rufnummer</th><th class="money">Netto gesamt</th></tr></thead>
            <tbody>${(d.top_gesamt || []).map((t) => `<tr class="linie-open" data-goto-ruf="${esc(t.rufnummer || "")}" title="Monitoring öffnen"><td>${esc(t.nutzer || "–")}</td><td>${esc(t.rufnummer)}</td><td class="money">${money(t.netto)}</td></tr>`).join("")}</tbody></table></div>
        </div>
      </div>

      <div class="section-title">Kosten je Rahmenvertrag</div>
      <div class="chart-box" style="height:260px"><canvas id="ctrlRv"></canvas></div>

      <div class="section-title">Zuordnung Rechnung ↔ Report <span class="muted">(klicken = Monitoring)</span></div>
      ${zlHtml}
    </div>`;
  const gbClick = (i) => gb[i] && selectCtrlByPeriod(gb[i].period);
  const trendClick = (i) => trend[i] && selectCtrlByPeriod(trend[i].period);
  if (gb.length) drawSeries("ctrlGb", "bar", gb.map((x) => fmtDate(x.period)), gb.map((x) => x.gb), "GB", gbClick);
  drawSeries("ctrlTrend", "line", trend.map((t) => fmtDate(t.period)), trend.map((t) => moneyNum(t.netto)), "€", trendClick);
  drawCtrlChart("ctrlRv", "bar", rv.map((x) => x.rahmenvertrag), rv.map((x) => moneyNum(x.netto)));
}
// Controlling-Monatswahl
function setCtrlInvoice(id) { state.ctrlInvoiceId = id; renderControlling(); }
function selectCtrlByPeriod(period) {
  const inv = (state.invoices || []).find((i) => i.period_start === period);
  if (inv) setCtrlInvoice(inv.id);
}
function stepCtrl(delta) {
  const inv = state.invoices || [];
  const cur = inv.find((i) => i.id === state.ctrlInvoiceId) || inv[inv.length - 1];
  const idx = inv.indexOf(cur) + delta;
  if (idx >= 0 && idx < inv.length) setCtrlInvoice(inv[idx].id);
}

function drawCtrlChart(id, type, labels, data) {
  if (charts[id]) charts[id].destroy();
  const ctx = document.getElementById(id);
  if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets: [{ data, backgroundColor: DATA_COLOR, borderColor: DATA_COLOR, borderRadius: 5, tension: .2, fill: false }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => money(c.parsed.y ?? c.parsed) } } },
      scales: { x: { ticks: { font: { size: 10 }, maxRotation: 55 } }, y: { beginAtZero: true, ticks: { callback: (v) => v.toLocaleString("de-DE") } } },
    },
  });
}

// ---- Linien-Monitoring (Rufnummer über Monate) ----------------------------
function gotoLinie(ruf) { if (ruf) location.hash = "#/linie/" + encodeURIComponent(ruf); }
function closeLinie() { location.hash = state.baseHash || "#/vertraege"; }
function hideLinie() {
  state.linieRuf = null;
  document.getElementById("liniePanel").hidden = true;
  document.getElementById("linieOverlay").hidden = true;
}
async function openLinie(ruf) {
  const panel = document.getElementById("liniePanel");
  if (state.linieRuf === ruf && !panel.hidden) return;
  state.linieRuf = ruf;
  panel.innerHTML = '<div class="drawer-head"><h3>Linie</h3><button class="btn" id="linieClose">✕</button></div><div class="hint">lade …</div>';
  panel.hidden = false;
  document.getElementById("linieOverlay").hidden = false;
  let d;
  try { d = await api("/api/linie/" + encodeURIComponent(ruf)); }
  catch (e) {
    panel.innerHTML = `<div class="drawer-head"><h3>${esc(ruf)}</h3><button class="btn" id="linieClose">✕</button></div><div class="empty">Keine Daten zu dieser Rufnummer.</div>`;
    return;
  }
  if (state.linieRuf !== ruf) return; // Antwort veraltet (andere Linie geöffnet)
  renderLinie(d);
}
const ALARM_TXT = { overage: "Overage", kostensprung: "Kosten", rabatt_weg: "Rabatt", option_neu: "Option +", option_weg: "Option −" };
function fmtVal(val, unit) {
  const n = Number(val).toLocaleString("de-DE", unit === "€" ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : {});
  return n + " " + unit;
}
function drawSeries(id, type, labels, data, unit, onPoint) {
  if (charts[id]) charts[id].destroy();
  const ctx = document.getElementById(id); if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets: [{ data, backgroundColor: DATA_COLOR, borderColor: DATA_COLOR, borderRadius: 5, tension: .25, fill: false }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      onClick: onPoint ? (evt, els) => { if (els && els.length) onPoint(els[0].index); } : undefined,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtVal(c.parsed.y ?? c.parsed, unit) } } },
      scales: { x: { ticks: { font: { size: 10 } } }, y: { beginAtZero: true, ticks: { callback: (val) => fmtVal(val, unit) } } },
    },
  });
}
// Kostensplit-HTML EINES Monats (Grundpreis -> Optionen einzeln -> Rabatt -> Netto)
function linieSplitHtml(m) {
  if (!m) return '<div class="hint">keine Rechnungsdaten für diese Rufnummer</div>';
  const row = (lbl, val, cls = "") => val ? `<div class="krow ${cls}"><span>${lbl}</span><b>${money(val)}</b></div>` : "";
  const items = (arr, icls = "") => (arr || []).map((o) => `<div class="krow opt ${icls}"><span>↳ ${esc(o.name)}</span><b>${money(o.amount)}</b></div>`).join("");
  // Gruppenkopf (Summe) + Einzelposten; ohne Posten fällt es auf eine schlichte Summenzeile zurück
  const group = (lbl, sum, arr, cls = "") => (arr && arr.length)
    ? `<div class="krow grp ${cls}"><span>${lbl}</span><b>${money(sum)}</b></div>` + items(arr, cls)
    : row(lbl, sum, cls);
  return row("Grundpreis", m.grundpreis)
    + group("Optionen", m.optionen, m.optionen_posten)
    + group("Verbrauch", m.verbrauch, m.verbrauch_posten)
    + group("Rabatte", m.rabatt, m.rabatte_posten, "rabatt")
    + `<div class="krow total"><span>Netto</span><b>${money(m.netto)}</b></div>`;
}
// Monat wählen (Klick auf Monatszeile oder Diagrammpunkt) -> Split umschalten
function selectLinieMonth(period) {
  const m = (state.linieVerlauf || []).find((x) => x.period === period);
  if (!m) return;
  state.linieMonth = period;
  const box = document.getElementById("linieSplit");
  if (box) box.innerHTML = linieSplitHtml(m);
  const lbl = document.getElementById("linieSplitMonth");
  if (lbl) lbl.textContent = fmtDate(period);
  document.querySelectorAll("#liniePanel [data-linie-month]").forEach((el) =>
    el.classList.toggle("active", el.dataset.linieMonth === period));
}
function renderLinie(d) {
  const panel = document.getElementById("liniePanel");
  const sd = d.stammdaten || {};
  const v = d.verlauf || [];
  const cur = v[v.length - 1], prev = v[v.length - 2];
  const dNet = (cur && prev) ? cur.netto - prev.netto : null;
  const dPct = (dNet != null && prev.netto) ? dNet / prev.netto * 100 : null;
  const rv = sd.rahmenvertrag ? ` · ${esc(sd.rahmenvertrag)}` : "";
  let vvlBadge = "";
  if (sd.bindefristende) {
    const days = Math.round((new Date(sd.bindefristende) - Date.now()) / 86400000);
    if (days < 0) vvlBadge = `<span class="vvl-badge red">Bindefrist abgelaufen</span>`;
    else if (days <= 90) vvlBadge = `<span class="vvl-badge red">VVL in ${days} T</span>`;
    else vvlBadge = `<span class="vvl-badge ok">Bindefrist bis ${fmtDate(sd.bindefristende)}</span>`;
  }
  const kpis = [
    ["Netto akt. Monat", cur ? money(cur.netto) : "–", dNet != null ? deltaBadge(dNet, dPct) : ""],
    ["Verbrauch akt.", cur && cur.data_used_gb != null ? `${cur.data_used_gb.toLocaleString("de-DE")} GB` : "–", ""],
    ["Datenvolumen", cur && cur.data_contracted_gb ? `${cur.data_contracted_gb} GB` : "unbegrenzt", ""],
    ["Monate erfasst", String(v.length), ""],
  ];
  state.linieVerlauf = v;
  // Startmonat = der auf Controlling gewählte (falls für diese Linie vorhanden), sonst neuester
  state.linieMonth = (state.ctrlPeriod && v.some((m) => m.period === state.ctrlPeriod))
    ? state.ctrlPeriod
    : (cur ? cur.period : null);
  const curMonth = v.find((m) => m.period === state.linieMonth) || cur;
  const alarms = (d.auffaelligkeiten || []).slice().reverse();
  const alarmHtml = alarms.length
    ? alarms.map((a) => `<div class="alarm"><span class="tag ${a.typ === "option_neu" || a.typ === "option_weg" ? "info" : "warn"}">${ALARM_TXT[a.typ] || a.typ}</span><span>${esc(a.text)}</span><span class="per">${fmtDate(a.period)}</span></div>`).join("")
    : '<div class="hint">keine Auffälligkeiten</div>';
  const rows = v.slice().reverse().map((m) =>
    `<tr class="linie-open${m.period === state.linieMonth ? " active" : ""}" data-linie-month="${m.period}" title="Aufstellung dieses Monats"><td>${fmtDate(m.period)}</td><td>${m.data_used_gb != null ? m.data_used_gb.toLocaleString("de-DE") + " GB" : "–"}</td><td>${m.auslastung_pct != null ? m.auslastung_pct + "%" : "–"}</td><td>${money(m.netto)}</td></tr>`).join("");
  const factRow = (f) => sd[f] ? `<div class="dl"><span>${esc((state.fields || {})[f] || f)}</span><b>${esc(sd[f])}</b></div>` : "";
  const facts = ["tarif", "vertragsstatus", "kartentyp", "vertragsbeginn", "bindefristende", "vvl_berechtigung", "daten_optionen", "voice_optionen", "roaming_optionen"].map(factRow).join("");
  const key = sd.rufnummer ? noteKey(sd) : null;
  state.linieNoteKey = key;
  const note = key ? (state.notes[key] || "") : "";

  panel.innerHTML = `
    <div class="drawer-head">
      <div><div class="muted">Rufnummer${rv}</div><h3>${esc(d.rufnummer)}</h3>
        <div class="muted">${esc(sd.kostenstellennutzer || "–")} · ${esc(sd.tarif || "–")} ${vvlBadge}</div></div>
      <div class="drawer-actions"><button class="btn" id="linieClose">✕</button></div>
    </div>
    <div class="linie-kpis">${kpis.map(([l, val, dd]) => `<div class="linie-kpi"><div class="num">${val}</div><div class="lbl">${l}${dd ? " · " + dd : ""}</div></div>`).join("")}</div>
    <div class="dg"><h4>Verbrauch pro Monat</h4>${v.length ? '<div class="linie-chart"><canvas id="linieGb"></canvas></div>' : '<div class="hint">keine Rechnungsmonate</div>'}</div>
    <div class="dg"><h4>Kosten pro Monat</h4>${v.length ? '<div class="linie-chart"><canvas id="linieNet"></canvas></div>' : '<div class="hint">keine Rechnungsmonate</div>'}</div>
    <div class="dg"><h4>Auffälligkeiten <span class="muted">(Monat zu Monat)</span></h4>${alarmHtml}</div>
    <div class="dg"><h4>Kostensplit <span class="muted" id="linieSplitMonth">${fmtDate(state.linieMonth)}</span></h4><div id="linieSplit">${linieSplitHtml(curMonth)}</div></div>
    ${rows ? `<div class="dg"><h4>Monatswerte <span class="muted">(Zeile/Diagrammpunkt klicken = Aufstellung des Monats)</span></h4><table class="mtab"><thead><tr><th>Monat</th><th>Verbrauch</th><th>Ausl.</th><th>Netto</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
    <div class="dg"><h4>Vertrag</h4>${facts || '<div class="hint">keine Stammdaten (Rufnummer nicht im aktuellen Report)</div>'}</div>
    ${key ? `<div class="dg note-block"><h4>Notiz / geprüft</h4><textarea id="linieNote" placeholder="z. B. geprüft am …, VVL angefragt">${esc(note)}</textarea><button class="btn" id="linieNoteSave">Notiz speichern</button></div>` : ""}`;

  if (v.length) {
    const labels = v.map((m) => fmtDate(m.period));
    const onPoint = (i) => selectLinieMonth(v[i].period);
    drawSeries("linieGb", "bar", labels, v.map((m) => m.data_used_gb || 0), "GB", onPoint);
    drawSeries("linieNet", "line", labels, v.map((m) => moneyNum(m.netto)), "€", onPoint);
  }
}

// ---- events ---------------------------------------------------------------
document.getElementById("authSubmit").addEventListener("click", submitAuth);
["authPw", "authPw2"].forEach((i) => document.getElementById(i).addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); }));

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  state.all = []; state.filters = {}; showAuth("login");
});

document.getElementById("search").addEventListener("input", (e) => { state.search = e.target.value.trim(); if (state.route === "vertraege") render(); });

document.getElementById("fileInput").addEventListener("change", async (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  let rep = 0, inv = 0, dup = 0, err = 0;
  for (const file of files) {                      // mehrere Dateien nacheinander
    const isInvoice = /\.csv$/i.test(file.name);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api(isInvoice ? "/api/invoices" : "/api/reports", { method: "POST", body: fd });
      if (isInvoice) { if (r.duplicate) dup++; else inv++; } else rep++;
    } catch (_) { err++; }
  }
  const parts = [];
  if (rep) parts.push(`${rep} Report${rep > 1 ? "s" : ""}`);
  if (inv) parts.push(`${inv} Rechnung${inv > 1 ? "en" : ""} geladen`);
  if (dup) parts.push(`${dup} Duplikat${dup > 1 ? "e" : ""} übersprungen`);
  if (err) parts.push(`${err} Fehler`);
  toast(parts.length ? parts.join(" · ") : "Nichts geladen", err > 0 && !rep && !inv);
  await loadData();
  e.target.value = "";
});

// Netto/Brutto-Umschalter
document.getElementById("netbrutto").addEventListener("click", (e) => {
  const opt = e.target.closest("[data-nb]"); if (!opt) return;
  state.brutto = opt.dataset.nb === "brutto";
  document.querySelectorAll("#netbrutto .nb-opt").forEach((b) => b.classList.toggle("active", b === opt));
  navigate();
  if (!document.getElementById("drawer").hidden && state.drawerRuf) loadDrawerKosten(state.drawerRuf);
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

document.getElementById("invoiceList").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-delinv]"); if (!del) return;
  if (!confirm("Diese Rechnung löschen?")) return;
  await api(`/api/invoices/${del.dataset.delinv}`, { method: "DELETE" });
  toast("Rechnung gelöscht"); await loadData();
});

// Klick auf Rechnungszeile -> Einzelrechnung
document.getElementById("view-rechnungen").addEventListener("click", (e) => {
  const tr = e.target.closest("[data-invid]");
  if (tr) location.hash = "#/rechnungen/" + tr.dataset.invid;
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
  if (e.target.id === "drawerVerlauf") { closeDrawer(); return gotoLinie(state.drawerRuf); }
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

// Linien-Panel: schließen + Notiz speichern
document.getElementById("liniePanel").addEventListener("click", async (e) => {
  if (e.target.id === "linieClose") return closeLinie();
  const mrow = e.target.closest("[data-linie-month]");
  if (mrow) return selectLinieMonth(mrow.dataset.linieMonth);
  if (e.target.id === "linieNoteSave") {
    const key = state.linieNoteKey;
    if (!key) return;
    const val = document.getElementById("linieNote").value;
    try {
      await api("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, note: val }) });
      if (val && val.trim()) state.notes[key] = val.trim(); else delete state.notes[key];
      toast("Notiz gespeichert");
    } catch (err) { toast("Speichern fehlgeschlagen: " + err.message, true); }
  }
});
document.getElementById("linieOverlay").addEventListener("click", closeLinie);
// Rufnummer aus Controlling-Listen -> Monitoring öffnen
document.getElementById("view-controlling").addEventListener("click", (e) => {
  if (e.target.id === "ctrlPrev") return stepCtrl(-1);
  if (e.target.id === "ctrlNext") return stepCtrl(1);
  const el = e.target.closest("[data-goto-ruf]");
  if (el) gotoLinie(el.dataset.gotoRuf);
});
document.getElementById("view-controlling").addEventListener("change", (e) => {
  if (e.target.id === "ctrlMonth") setCtrlInvoice(+e.target.value);
});
// Enter in der Suche: eindeutige Rufnummer -> direkt Monitoring öffnen
document.getElementById("search").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const raw = (state.search || "").trim();
  if (!raw) return;
  const q = raw.replace(/\D/g, "");            // Ziffern für Rufnummer-Suche
  const qLower = raw.toLowerCase();            // Text für Nutzer-Suche
  const hits = (state.all || []).filter((c) => {
    const num = String(c.rufnummer || "").replace(/\D/g, "");
    return (q && num.includes(q)) || String(c.kostenstellennutzer || "").toLowerCase().includes(qLower);
  });
  if (!hits.length) return;
  const exact = q ? hits.find((c) => String(c.rufnummer || "").replace(/\D/g, "") === q) : null;
  gotoLinie((exact || hits[0]).rufnummer);     // exakte Nummer bevorzugt, sonst erster Treffer
});

init();
