"use strict";
/* Air Quality Data Processing Tool — front end (no build step). Charts come from the Flask API as
   Plotly figure JSON and are drawn with Plotly.js. */

const OPT = window.AQ_OPTIONS;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const ICON = {
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v4h16v-4"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
  gap: '<svg viewBox="0 0 24 24"><path d="M8 3v18M16 3v18" stroke-dasharray="3 3"/></svg>',
};
const INST_ICON = {
  dusttrak: '<svg viewBox="0 0 24 24"><circle cx="7" cy="8" r="2"/><circle cx="16" cy="6" r="1.5"/><circle cx="13" cy="13" r="2.5"/><circle cx="6" cy="16" r="1.5"/><circle cx="18" cy="17" r="2"/></svg>',
  aws: '<svg viewBox="0 0 24 24"><path d="M3 8h11a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7"/></svg>',
  c12: '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="10" rx="2"/><circle cx="9" cy="12" r="2.2" fill="currentColor"/><path d="M14 12h4"/></svg>',
};
const SPARK_COLORS =["#0F766E", "#2563EB", "#D97706", "#7C3AED", "#DB2777", "#0891B2"];

// ===== HELPERS =====
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d }));
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
let uid = 0;
const nextId = (p) => `${p}-${++uid}`;

function fmtDate(s) {
  if (!s) return "–";
  const d = new Date(s.replace(" ", "T"));
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  let data;
  try { data = await res.json(); } catch { throw new Error(`Server error (${res.status})`); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
const postJSON = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const postForm = (url, form) => api(url, { method: "POST", body: form });

function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), type === "error" ? 7000 : 3500);
}

async function busy(btn, fn) {
  if (btn) { btn.classList.add("busy"); btn.disabled = true; }
  try { return await fn(); }
  catch (e) { console.error(e); toast(e.message, "error"); }
  finally { if (btn) { btn.classList.remove("busy"); btn.disabled = false; } }
}

// ===== UI BUILDERS =====
const stat = (label, value, sub = "", tone = "") =>
  `<div class="stat ${tone ? "tone-" + tone : ""}"><div class="stat-label">${esc(label)}</div>` +
  `<div class="stat-value">${value}</div>${sub ? `<div class="stat-sub">${sub}</div>` : ""}</div>`;

const select = (cls, options, value) =>
  `<select class="${cls}">${options.map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;

const pills = (name, options, selected = options) =>
  `<div class="pills">${options.map((o) => `<label class="pill"><input type="checkbox" name="${name}" value="${esc(o)}" ${selected.includes(o) ? "checked" : ""}><span>${esc(o)}</span></label>`).join("")}</div>`;
const checked = (root, name) => $$(`input[name="${name}"]:checked`, root).map((i) => i.value);

const segmented = (name, options, value) =>
  `<div class="segmented">${options.map(([v, label]) => `<label><input type="radio" name="${name}" value="${esc(v)}" ${v === value ? "checked" : ""}><span>${esc(label)}</span></label>`).join("")}</div>`;
const radioValue = (root, name) => $(`input[name="${name}"]:checked`, root)?.value;

const rangeCtl = (key, min, max, step, value, suffix = "") =>
  `<div class="range-row"><input type="range" data-key="${key}" min="${min}" max="${max}" step="${step}" value="${value}">` +
  `<span class="range-value" data-suffix="${suffix}">${value}${suffix}</span></div>`;

const field = (label, control, hint = "") =>
  `<div class="field"><label>${esc(label)}</label>${control}${hint ? `<span class="hint">${hint}</span>` : ""}</div>`;

function cell(v) {
  if (typeof v === "number") return `<td class="num">${fmt(v, 3)}</td>`;
  if (v === null || v === undefined) return `<td class="muted">–</td>`;
  return `<td>${esc(v)}</td>`;
}

function tableHTML(data, { maxHeight } = {}) {
  if (!data.rows.length) return `<div class="chart-empty">No rows to show</div>`;
  const head = data.columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = data.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("");
  return `<div class="table-wrap" ${maxHeight ? `style="max-height:${maxHeight}px"` : ""}><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function sparkSVG(values, color) {
  if (!values || values.length < 2) return "";
  const w = 200, h = 44, min = Math.min(...values), max = Math.max(...values), r = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 3 - ((v - min) / r) * (h - 6)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const gid = nextId("grad");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">` +
    `<stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>` +
    `<path d="${line} L${w} ${h} L0 ${h} Z" fill="url(#${gid})"/><path d="${line}" fill="none" stroke="${color}" stroke-width="1.8" vector-effect="non-scaling-stroke"/></svg>`;
}

async function pagedTable(container, url) {
  let offset = 0, rows = [], columns = [];
  const load = async () => {
    const d = await api(`${url}?offset=${offset}&limit=100`);
    columns = d.columns;
    rows = rows.concat(d.rows);
    offset += d.rows.length;
    container.innerHTML = tableHTML({ columns, rows }, { maxHeight: 460 }) +
      `<div class="muted" style="margin-top:8px">Showing ${fmt(rows.length, 0)} of ${fmt(d.total, 0)} rows</div>` +
      (offset < d.total ? `<div class="table-more"><button class="btn">Load 100 more</button></div>` : "");
    const btn = $(".table-more .btn", container);
    if (btn) btn.onclick = () => busy(btn, load);
  };
  try { await load(); } catch (e) { toast(e.message, "error"); }
}

// ===== CHARTS =====
const PLOT_CONFIG = {
  responsive: true, displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
  toImageButtonOptions: { format: "png", scale: 2, filename: "air_quality_chart" },
};

async function drawChart(el, loader) {
  el.classList.add("loading");
  try {
    const res = await loader();
    if ($(".chart-empty", el)) el.innerHTML = "";
    await Plotly.react(el, res.figure.data, res.figure.layout, PLOT_CONFIG);
    return res.extra || {};
  } catch (e) {
    toast(e.message, "error");
    return null;
  } finally {
    el.classList.remove("loading");
  }
}

function chartMessage(el, msg) {
  Plotly.purge(el);
  el.innerHTML = `<div class="chart-empty">${esc(msg)}</div>`;
}

function gapNote(gaps, collapsed) {
  if (!gaps || !gaps.length) return "";
  const list = gaps.slice(0, 5).map((g) => `<b>${esc(g.length)}</b> (${esc(g.start)} → ${esc(g.end)})`).join(", ");
  const more = gaps.length > 5 ? ` and ${gaps.length - 5} more` : "";
  return `${ICON.gap}<div><b>${gaps.length} gap${gaps.length > 1 ? "s" : ""} with no data</b> — ` +
    (collapsed ? "collapsed so the series and trendlines run continuously. Each gap is marked by" : "shown at full length and marked by") +
    ` two red dashed lines <span class="gap-lines"><i></i><i></i></span>: ${list}${more}.</div>`;
}

/** Time-series panel with variable, trendline, reference-line and gap controls */
function Explorer(root, { numericCols, defaults, endpoint, extra = {} }) {
  const name = nextId("cols");
  root.innerHTML = `
    <div class="explorer-controls">
      <div class="field wide"><label>Variables</label>${pills(name, numericCols, defaults)}</div>
      ${field("Trendline", select("x-trend", OPT.trend_options, "Rolling average"))}
      ${field("Smoothing window", select("x-window", OPT.windows, "1 hour"))}
      ${field("Reference line", `<div class="inline"><input type="number" class="x-ref" min="0" step="any" placeholder="Value">` +
        `<input type="text" class="x-ref-label" placeholder="Label, e.g. guideline"></div>`)}
      <div class="toggles wide">
        <label class="check"><input type="checkbox" class="x-collapse" checked> Collapse data gaps</label>
        <label class="check"><input type="checkbox" class="x-fade" checked> Fade raw lines when a trend is shown</label>
        <label class="check"><input type="checkbox" class="x-log"> Log scale</label>
      </div>
    </div>
    <div class="gap-note"></div>
    <div class="chart chart-lg"></div>`;
  const chart = $(".chart", root), note = $(".gap-note", root);

  const update = debounce(async () => {
    const p = {
      ...extra,
      cols: checked(root, name),
      trend: $(".x-trend", root).value,
      window: $(".x-window", root).value,
      ref_value: parseFloat($(".x-ref", root).value) || 0,
      ref_label: $(".x-ref-label", root).value,
      collapse_gaps: $(".x-collapse", root).checked,
      fade: $(".x-fade", root).checked,
      log_y: $(".x-log", root).checked,
    };
    $(".x-window", root).disabled = !p.trend.startsWith("Rolling");
    if (!p.cols.length) { note.innerHTML = ""; chartMessage(chart, "Select at least one variable to plot"); return; }
    const res = await drawChart(chart, () => postJSON(endpoint, p));
    if (res) note.innerHTML = gapNote(res.gaps, p.collapse_gaps);
  }, 200);

  root.addEventListener("change", update);
  root.addEventListener("input", (e) => { if (e.target.matches(".x-ref, .x-ref-label")) update(); });
  update();
}

// ===== DROPZONE =====
const filePath = (f) => f.relPath || f.webkitRelativePath || f.name;

/** Files from a drop, walking into dropped folders (C-12 downloads arrive as folders) */
async function droppedFiles(dt) {
  const entries = [...(dt.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dt.files];
  const out = [];
  const walk = async (entry, path) => {
    if (entry.isFile) {
      const f = await new Promise((res, rej) => entry.file(res, rej));
      f.relPath = path + f.name;
      out.push(f);
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        for (const e of batch) await walk(e, `${path}${entry.name}/`);
      }
    }
  };
  for (const e of entries) await walk(e, "");
  return out;
}

function Dropzone(root, { multiple = false, onChange = () => {} } = {}) {
  let files = [], mode = { exts: ["csv"], folders: false, hint: "" };
  root.innerHTML = `<input type="file" class="dz-input" ${multiple ? "multiple" : ""} hidden>
    <input type="file" class="dz-folder" webkitdirectory multiple hidden>
    <div class="dz-inner"><div class="dz-icon">${ICON.upload}</div><div>
      <div class="dz-title"></div><div class="dz-sub"></div></div></div>
    <div class="dz-files"></div>`;
  const input = $(".dz-input", root), folderInput = $(".dz-folder", root), list = $(".dz-files", root);

  const describe = () => {
    const kinds = mode.exts.map((e) => "." + e).join(", ");
    $(".dz-title", root).innerHTML = `Drop ${mode.folders ? "folders or files" : multiple ? "files" : "a file"} here or <span class="link">browse</span>` +
      (mode.folders ? ` · <span class="link dz-pick-folder">choose a folder</span>` : "");
    $(".dz-sub", root).textContent = `${mode.hint || (multiple ? "Select several files at once" : "One file")} · ${kinds} · up to 500 MB`;
    input.accept = kinds;
  };
  const render = () => {
    list.innerHTML = files.map((f, i) => `<span class="file-chip">${esc(filePath(f))} <small>${(f.size / 1024).toFixed(1)} KB</small>` +
      `<button type="button" data-i="${i}" title="Remove">${ICON.x}</button></span>`).join("");
  };
  const add = (incoming) => {
    const pattern = new RegExp(`\\.(${mode.exts.join("|")})$`, "i");
    const ok = [...incoming].filter((f) => pattern.test(f.name));
    const skipped = incoming.length - ok.length;
    if (incoming.length && !ok.length) toast(`Only ${mode.exts.map((e) => "." + e).join(", ")} files are accepted`, "error");
    else if (skipped) toast(`Ignored ${skipped} file(s) of other types`);
    files = multiple ? [...files, ...ok.filter((f) => !files.some((g) => filePath(g) === filePath(f)))] : ok.slice(0, 1);
    render();
    onChange(files);
  };
  root.addEventListener("click", (e) => {
    if (e.target.closest(".dz-pick-folder")) { e.stopPropagation(); folderInput.click(); }
    else if (e.target.closest(".dz-inner")) input.click();
  });
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  folderInput.addEventListener("change", () => { add(folderInput.files); folderInput.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => root.addEventListener(ev, (e) => { e.preventDefault(); root.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => root.addEventListener(ev, (e) => { e.preventDefault(); root.classList.remove("drag"); }));
  root.addEventListener("drop", async (e) => add(await droppedFiles(e.dataTransfer)));
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    files.splice(+b.dataset.i, 1);
    render();
    onChange(files);
  });
  describe();
  return {
    get files() { return files; },
    configure(next) { mode = { ...mode, ...next }; files = []; render(); describe(); onChange(files); },
  };
}

/** Append files keeping their folder path, so the server can pair each C-12 Data.CSV with its Settings file */
const appendFiles = (fd, files) => files.forEach((f) => fd.append("files", f, filePath(f)));

// ===== TABS =====
function bindTabs(tabsEl, onShow = () => {}) {
  const card = tabsEl.parentElement;
  const activate = (name) => {
    $$(".tab", tabsEl).forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(":scope > .tab-panel", card).forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
    const panel = $(`:scope > .tab-panel[data-panel="${name}"]`, card);
    onShow(name, panel);
    $$(".js-plotly-plot", panel).forEach((el) => Plotly.Plots.resize(el));
  };
  tabsEl.addEventListener("click", (e) => { const t = e.target.closest(".tab"); if (t) activate(t.dataset.tab); });
  return activate;
}

// ===== STATE & NAVIGATION =====
const state = { instrument: "dusttrak", batch: null, merged: null, dataset: null, result: null };
const instLabel = (key) => (OPT.instruments[key] || { label: "Other / generic" }).label;
const VIEWS = ["convert", "merge", "clean", "results"];

function go(view) {
  if (!VIEWS.includes(view)) view = "convert";
  $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  history.replaceState(null, "", `#${view}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
  setTimeout(() => $$(`#view-${view} .js-plotly-plot`).forEach((el) => el.offsetParent && Plotly.Plots.resize(el)), 0);
}
const markDone = (view) => $(`.nav-item[data-view="${view}"]`).classList.add("done");

function setActiveDataset(ds) {
  $("#active-dataset .side-card-value").textContent = ds.name;
  $("#active-dataset .side-card-sub").textContent = `${ds.instrument_label} · ${fmt(ds.rows, 0)} rows · ${ds.columns.length} columns`;
}

// ===== INSTRUMENT =====
$("#inst-switch").innerHTML = Object.entries(OPT.instruments).map(([key, v]) =>
  `<button class="inst-btn" data-inst="${key}" title="${esc(v.name)}"><span class="inst-icon">${INST_ICON[key]}</span>` +
  `<span><b>${esc(v.label)}</b><small>${esc(v.sub)}</small></span></button>`).join("");
$("#inst-switch").addEventListener("click", (e) => {
  const b = e.target.closest(".inst-btn");
  if (b && b.dataset.inst !== state.instrument) { setInstrument(b.dataset.inst); toast(`Instrument: ${instLabel(b.dataset.inst)}`); }
});

const INST_EXTS = { dusttrak: ["csv"], aws: ["txt", "csv", "tsv"], c12: ["csv", "txt"] };

function convertOptionsHTML(key) {
  if (key === "c12") return field("Concentration units", segmented("c12-unit", [["ng/m3", "ng/m³ (as logged)"], ["µg/m3", "µg/m³"]], "ng/m3"));
  if (key === "aws") return `<label class="check"><input type="checkbox" id="aws-bar-hpa" checked> Convert the barometer to hPa when the file records inHg</label>`;
  return "";
}

/** Switch the instrument used by Convert and Merge (Clean has its own profile picker) */
function setInstrument(key) {
  state.instrument = key;
  const info = OPT.instruments[key];
  try { localStorage.setItem("aq-instrument", key); } catch {}
  $$(".inst-btn").forEach((b) => b.classList.toggle("active", b.dataset.inst === key));
  $("#convert-title").textContent = info.convert_title;
  $("#convert-desc").textContent = info.convert_desc;
  $("#include-extra-label").textContent = info.extra_label;
  $("#include-extra").checked = false;
  $("#convert-options").innerHTML = convertOptionsHTML(key);
  $$(".inst-name").forEach((el) => { el.textContent = info.label; });
  convertDrop.configure({ exts: INST_EXTS[key], folders: info.folders, hint: info.files_hint });
  mergeDrop.configure({ exts: ["csv", "txt", "tsv"], folders: info.folders, hint: `Converted CSVs or raw ${info.label} exports` });

  const batchMatches = state.batch && state.batch.instrument === key;
  $("#convert-result").hidden = !batchMatches;
  const batchRadio = $('input[name="merge-source"][value="batch"]');
  batchRadio.disabled = !batchMatches;
  if (!batchMatches) $('input[name="merge-source"][value="upload"]').checked = true;
  $("#merge-batch-label").textContent = batchMatches ? `Files converted in step 1 (${state.batch.files.length})` : "Files converted in step 1";
  updateMergeControls();
}

const convertFormOptions = (fd) => {
  fd.append("instrument", state.instrument);
  fd.append("include_extra", $("#include-extra").checked);
  fd.append("unit", radioValue(document, "c12-unit") || "ng/m3");
  fd.append("bar_to_hpa", $("#aws-bar-hpa") ? $("#aws-bar-hpa").checked : true);
};

$$(".nav-item").forEach((n) => n.addEventListener("click", () => go(n.dataset.view)));
document.addEventListener("click", (e) => { const g = e.target.closest("[data-goto]"); if (g) go(g.dataset.goto); });
document.addEventListener("input", (e) => {
  if (e.target.type === "range") {
    const out = e.target.nextElementSibling;
    if (out?.classList.contains("range-value")) out.textContent = e.target.value + (out.dataset.suffix || "");
  }
});

// -------------------------------
// STEP 1: CONVERT
// -------------------------------
const convertDrop = Dropzone($("#convert-drop"), { multiple: true, onChange: (f) => { $("#convert-btn").disabled = !f.length; } });

$("#convert-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  const fd = new FormData();
  appendFiles(fd, convertDrop.files);
  convertFormOptions(fd);
  renderConverted(await postForm("/api/convert", fd));
}));

function renderConverted(res) {
  $("#convert-result").hidden = false;
  $("#convert-failures").innerHTML = res.failures.map((f) =>
    `<div class="notice error">Could not convert <b>${esc(f.file)}</b>: ${esc(f.reason)}</div>`).join("");
  if (!res.batch_id) {
    $("#convert-stats").innerHTML = "";
    $("#convert-table").innerHTML = "";
    $("#convert-alarms").hidden = true;
    toast("No files could be converted", "error");
    return;
  }
  state.batch = res;
  $("#convert-stats").innerHTML = res.stats.map((s, i) => stat(s.label, fmt(s.value, 0),
    i === 0 ? (res.failures.length ? `${res.failures.length} failed` : "All files read") : esc(s.sub || ""), s.tone || "")).join("");

  const cols = ["source", "output", ...res.info_columns];
  $("#convert-table").innerHTML = tableHTML({
    columns: ["Source file", "Output file", ...res.info_columns],
    rows: res.files.map((f) => cols.map((c) => f[c])),
  });
  $("#convert-zip").href = `/api/batch/${res.batch_id}/zip`;
  $("#convert-alarms").hidden = !res.alarms;
  if (res.alarms) $("#convert-alarms-table").innerHTML = tableHTML(res.alarms, { maxHeight: 320 });

  const sel = $("#convert-preview-select");
  sel.innerHTML = res.files.map((f) => `<option>${esc(f.output)}</option>`).join("");
  sel.onchange = () => { $("#convert-preview").innerHTML = `<div class="mt">${tableHTML(res.preview[sel.value])}</div>`; };
  sel.onchange();

  const batchRadio = $('input[name="merge-source"][value="batch"]');
  batchRadio.disabled = false;
  batchRadio.checked = true;
  $("#merge-batch-label").textContent = `Files converted in step 1 (${res.files.length})`;
  updateMergeControls();
  markDone("convert");
  toast(`${res.files.length} file(s) converted`, "success");
}

$("#to-merge").addEventListener("click", () => go("merge"));

// -------------------------------
// STEP 2: MERGE
// -------------------------------
const mergeDrop = Dropzone($("#merge-drop"), { multiple: true, onChange: () => updateMergeControls() });

function updateMergeControls() {
  const src = radioValue(document, "merge-source");
  $("#merge-drop").hidden = src === "batch";
  $("#merge-btn").disabled = src === "batch" ? !state.batch : !mergeDrop.files.length;
}
$("#merge-source").addEventListener("change", updateMergeControls);
updateMergeControls();

$("#merge-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  const fd = new FormData();
  if (radioValue(document, "merge-source") === "batch") fd.append("batch_id", state.batch.batch_id);
  else appendFiles(fd, mergeDrop.files);
  fd.append("dedupe", $("#merge-dedupe").checked);
  fd.append("add_source", $("#merge-source-col").checked);
  convertFormOptions(fd);
  const res = await postForm("/api/merge", fd);
  res.warnings.forEach((w) => toast(w, "error"));
  renderMerged(res.dataset);
}));

function renderMerged(ds) {
  state.merged = ds;
  $("#merge-result").hidden = false;
  const gaps = ds.gaps || [];
  $("#merge-stats").innerHTML =
    stat("Total rows", fmt(ds.rows, 0), `${ds.meta.files} file(s) combined`) +
    stat("Start", fmtDate(ds.start), `ends ${fmtDate(ds.end)}`, "blue") +
    stat("Duration", esc(ds.span), "first to last reading") +
    stat("Sampling interval", esc(ds.interval), "typical spacing") +
    stat("Data gaps", gaps.length, gaps.length ? "pauses in monitoring" : "continuous record", gaps.length ? "red" : "") +
    stat("Duplicates removed", fmt(ds.meta.duplicates, 0), "repeated timestamps", ds.meta.duplicates ? "amber" : "");

  $("#merge-sparks").innerHTML = ds.pm_cards.map((c, i) =>
    `<div class="spark-card"><div class="stat-label">Mean ${esc(c.column)}</div><div class="stat-value">${fmt(c.mean)}</div>` +
    `<div class="stat-sub">max ${fmt(c.max, 0)}</div>${sparkSVG(c.spark, SPARK_COLORS[i % SPARK_COLORS.length])}</div>`).join("");

  Explorer($("#merge-explorer"), { numericCols: ds.numeric_cols, defaults: ds.default_plot_cols, endpoint: `/api/dataset/${ds.id}/timeseries` });
  $("#merge-preview").innerHTML = tableHTML(ds.preview);
  $("#merge-download").href = `/api/dataset/${ds.id}/csv`;

  const mergedRadio = $('input[name="clean-source"][value="merged"]');
  mergedRadio.disabled = false;
  setActiveDataset(ds);
  markDone("merge");
  toast(`Merged ${fmt(ds.rows, 0)} rows`, "success");
}

$("#to-clean").addEventListener("click", () => {
  $('input[name="clean-source"][value="merged"]').checked = true;
  updateCleanSource();
  go("clean");
});

// -------------------------------
// STEP 3: CLEAN
// -------------------------------
const cleanDrop = Dropzone($("#clean-drop"), { onChange: (f) => { $("#clean-load-btn").disabled = !f.length; } });

function updateCleanSource() {
  const src = radioValue(document, "clean-source");
  $("#clean-upload-area").hidden = src === "merged";
  if (src === "merged" && state.merged && state.dataset?.id !== state.merged.id) loadDataset(state.merged);
}
$("#clean-source").addEventListener("change", updateCleanSource);

$("#clean-load-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  const fd = new FormData();
  fd.append("file", cleanDrop.files[0]);
  fd.append("dayfirst", $("#dayfirst").checked);
  const res = await postForm("/api/upload", fd);
  loadDataset(res.dataset);
  toast(`Loaded ${res.dataset.name}`, "success");
}));

const PROFILE_NOTES = {
  dusttrak: "PM limits start at zero and size fractions are checked (PM1 ≤ PM2.5 ≤ PM10).",
  aws: "Plausibility limits for temperature, humidity, wind and pressure; highs, lows, rain and wind direction are averaged correctly.",
  c12: "Status codes are decoded from the Met One C-12 manual; flow and all-zero readings are checked before the statistical steps.",
  generic: "No instrument detected: every numeric column starts with a lower limit of zero.",
};

$("#clean-profile").innerHTML = [...Object.keys(OPT.instruments), "generic"].map((k) => `<option value="${k}">${esc(instLabel(k))}</option>`).join("");
$("#clean-profile").addEventListener("change", (e) => busy(null, async () => {
  const res = await api(`/api/dataset/${state.dataset.id}?instrument=${encodeURIComponent(e.target.value)}`);
  loadDataset(res.dataset);
  toast(`Using the ${res.dataset.instrument_label} profile`, "success");
}));

function loadDataset(ds) {
  state.dataset = ds;
  setActiveDataset(ds);
  if (ds.instrument in OPT.instruments && ds.instrument !== state.instrument && !state.batch) setInstrument(ds.instrument);
  $("#clean-workspace").hidden = false;
  const notice = $("#clean-notice");
  notice.hidden = !ds.meta.converted_from_raw;
  notice.textContent = `This looks like a raw ${instLabel(ds.meta.converted_from_raw)} export — it was converted automatically.`;
  $("#clean-profile").value = ds.instrument;
  $("#clean-profile-note").textContent = PROFILE_NOTES[ds.instrument] + " All defaults can be changed below.";

  $("#clean-stats").innerHTML =
    stat("Rows", fmt(ds.rows, 0), esc(ds.name)) +
    stat("Columns", ds.columns.length, `${ds.numeric_cols.length} numeric`, "blue") +
    stat("Time span", esc(ds.span || "–"), ds.interval ? `every ${esc(ds.interval)}` : "no timestamp column") +
    stat("Data gaps", (ds.gaps || []).length, "pauses in monitoring", (ds.gaps || []).length ? "red" : "") +
    stat("Missing cells", `${fmt(ds.missing_pct)}%`, "across all columns", ds.missing_pct > 0 ? "amber" : "");

  $("#ov-preview").innerHTML = tableHTML(ds.preview);
  $("#ov-profile").innerHTML = profileHTML(ds.profile);
  $("#ov-missing").innerHTML = missingHTML(ds.profile);
  buildPipeline(ds);
}

function profileHTML(profile) {
  const head = ["Column", "Type", "Non-missing", "Missing", "Unique", "Min", "Mean", "Max"].map((c) => `<th>${c}</th>`).join("");
  const body = profile.map((p) => `<tr><td><b>${esc(p.Column)}</b></td><td><span class="badge badge-muted">${esc(p.Type)}</span></td>` +
    `<td class="num">${fmt(p["Non-missing"], 0)}</td>` +
    `<td><div class="bar-cell"><div class="bar-track"><div class="bar-fill" style="width:${p["Missing %"]}%"></div></div>${fmt(p["Missing %"], 1)}%</div></td>` +
    `<td class="num">${fmt(p.Unique, 0)}</td>${cell(p.Min ?? null)}${cell(p.Mean ?? null)}${cell(p.Max ?? null)}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function missingHTML(profile) {
  const rows = profile.filter((p) => p["Missing %"] > 0).sort((a, b) => b["Missing %"] - a["Missing %"]);
  if (!rows.length) return `<div class="notice">No missing values in this dataset.</div>`;
  return rows.map((p) => `<div class="bar-cell" style="margin-bottom:10px"><span style="width:220px">${esc(p.Column)}</span>` +
    `<div class="bar-track"><div class="bar-fill" style="width:${p["Missing %"]}%"></div></div><b>${fmt(p["Missing %"], 1)}%</b></div>`).join("");
}

bindTabs($('[data-tabs="overview"]'));

// ===== PIPELINE =====
const outlierState = { sigmaK: 3, iqr: 1.5, window: 31, hampelK: 3, lo: 1, hi: 99 };
const STEP_NAMES = {
  columns: "Columns", duplicates: "Duplicates", qc: "Instrument QC", range: "Range limits", consistency: "Consistency",
  flatline: "Stuck sensor", outliers: "Outliers", missing: "Missing values", averaging: "Averaging",
};

function stepCard(n, key, title, desc, on, body, { toggle = true, disabled = false } = {}) {
  return `<section class="step ${on ? "on" : ""}" data-step="${key}">
    <div class="step-head"><div class="step-num">${n}</div>
      <div class="step-text"><div class="step-title">${esc(title)}</div><div class="step-desc">${esc(desc)}</div></div>
      <span class="step-state">${on ? "On" : "Off"}</span>
      ${toggle ? `<label class="switch" title="Turn this step on or off"><input type="checkbox" class="step-toggle" ${on ? "checked" : ""} ${disabled ? "disabled" : ""}><span class="slider"></span></label>` : ""}
      ${ICON.chev}</div>
    <div class="step-body">${body}</div></section>`;
}

/** Instrument QC step body: C-12 status codes, flow and zero checks; AWS radio reception */
function qcBody(ds) {
  const qc = ds.defaults.qc;
  if (ds.instrument === "c12") {
    const rows = qc.status_col ? qc.codes.map((c) => `<tr class="${c.default ? "" : "info-code"}" data-code="${c.code}">` +
      `<td><input type="checkbox" class="qc-code" ${c.default ? "checked" : ""}></td><td class="num">${c.code}</td>` +
      `<td><b>${esc(c.label)}</b>${c.default ? "" : ' <span class="badge badge-muted">not an error</span>'}</td>` +
      `<td class="num">${c.count ? `<span class="badge ${c.default ? "badge-red" : "badge-amber"}">${fmt(c.count, 0)}</span>` : '<span class="muted">0</span>'}</td></tr>`).join("") : "";
    return `
      ${qc.status_col ? `<div class="qc-block">${field("Remove readings carrying these status codes", `<div class="table-wrap qc-table"><table>
        <thead><tr><th>Remove</th><th>Code</th><th>Meaning</th><th>Readings in data</th></tr></thead><tbody>${rows}</tbody></table></div>`,
        "Codes and meanings from the Met One C-12 operation manual (C-12-9800 Rev A), Table 7-1. A reading can carry several codes; its Status is their sum. " +
        "The manual describes 32 (automatic tape advance) and 65536 (tape move) as not error conditions; tick them to drop readings taken at a tape advance as well.")}</div>` : ""}
      ${qc.flow_col ? `<div class="qc-block"><label class="check"><input type="checkbox" class="qc-flow-on" checked> Remove readings with flow out of regulation</label>
        <div class="grid-3 mt">${field("Nominal flow (lpm)", `<input type="number" class="qc-flow-nominal" value="${qc.flow_nominal}" step="0.05" min="0">`)}
        ${field("Tolerance (%)", `<input type="number" class="qc-flow-tol" value="${qc.flow_tol}" step="1" min="0">`)}</div>
        <span class="hint muted">Manual defaults: nominal flow 1 lpm; the instrument raises a flow failure when flow is 10% out of regulation for over a minute.
        ${fmt(qc.flow_off, 0)} reading(s) in this dataset fall outside 1 lpm ± 10%.</span></div>` : ""}
      ${qc.zero_cols.length ? `<div class="qc-block"><label class="check"><input type="checkbox" class="qc-zero-on" checked>
        Remove readings that are exactly zero in every channel (${fmt(qc.zero_count, 0)} found)</label>
        <span class="hint muted">An exact zero on both wavelengths usually means the monitor was not measuring, for example just after a power cycle. Untick if you expect genuine zeros.</span></div>` : ""}`;
  }
  if (ds.instrument === "aws") {
    return qc.reception_col ? `<label class="check"><input type="checkbox" class="qc-rec-on" checked> Remove records with weak radio reception from the outdoor sensors</label>
      <div class="grid-3 mt">${field(`Minimum ${qc.reception_col}`, `<input type="number" class="qc-rec-min" value="50" min="0" max="100" step="5">`)}</div>
      <span class="hint muted">Reception is the share of sensor transmissions the console received in each record; low values mean the record rests on fewer samples.</span>`
      : `<span class="muted">No reception column (e.g. "ISS Recept") was found in this dataset.</span>`;
  }
  return "";
}

const AVG_WORDS = { sum: "summed", max: "as maximum", min: "as minimum", circular: "vector-averaged", bitor: "keeping every status code" };

function buildPipeline(ds) {
  const num = ds.numeric_cols, all = ds.columns, hasDt = ds.datetime_cols.length > 0;
  const rules = ds.consistency_rules, def = ds.defaults;
  const toLocal = (s) => (s ? s.replace(" ", "T").slice(0, 19) : "");
  const actions = OPT.actions.map((a) => [a, a]);
  const [REMOVE, BLANK] = OPT.actions;
  const hasQc = ds.instrument === "c12" || ds.instrument === "aws";
  const special = Object.entries(def.avg_special);
  const rangeRow = (c) => {
    const [lo, hi, on] = def.ranges[c] || [null, null, false];
    return `<tr data-col="${esc(c)}"><td><input type="checkbox" class="r-apply" ${on ? "checked" : ""}></td><td><b>${esc(c)}</b></td>` +
      `<td><input type="number" class="r-min" value="${lo ?? ""}" placeholder="No limit" step="any"></td>` +
      `<td><input type="number" class="r-max" value="${hi ?? ""}" placeholder="No limit" step="any"></td></tr>`;
  };
  const rangeHint = {
    aws: "Suggested plausibility limits — temperatures assume °C unless the data look like °F. Adjust them for your site and the units the station logs.",
    c12: "Concentrations cannot be negative. Box temperature and pressure limits are the sensor limits in the C-12 manual (Table 7-3).",
  }[ds.instrument] || "Concentrations below zero are physically impossible. Set a maximum to drop values above the instrument's measurable range.";
  let n = 0;

  const html = [
    `<div class="card timestamp-card">${field("Timestamp column", select("p-dt", [...ds.datetime_cols, "(none)"], ds.datetime_cols[0] || "(none)"),
      "Used for sorting, the time window, time-weighted interpolation and averaging")}</div>`,

    stepCard(++n, "columns", "Columns & time window", "Choose which columns to keep and, optionally, a time range", false, `
      ${field("Columns to keep", pills("p-keep", all, all))}
      ${hasDt ? `<div class="field"><label class="check"><input type="checkbox" class="p-tw-on"> Restrict to a time window</label>
        <div class="grid-2">${field("From", `<input type="datetime-local" step="1" class="p-tw-start" value="${toLocal(ds.start)}">`)}
        ${field("To", `<input type="datetime-local" step="1" class="p-tw-end" value="${toLocal(ds.end)}">`)}</div></div>` : ""}`, { toggle: false }),

    stepCard(++n, "duplicates", "Duplicate records", "Drop repeated readings, keeping the first", true,
      field("Treat rows as duplicates when they share…", segmented("p-dedupe-by", [["time", "The same timestamp"], ["row", "Identical values in every column"]], "time"))),

    hasQc ? stepCard(++n, "qc", `Instrument QC — ${ds.instrument_label}`,
      ds.instrument === "c12" ? "Drop readings the monitor flagged itself: status codes, off-nominal flow, all-zero readings"
        : "Drop records the station flagged as poorly received", ds.instrument === "c12", qcBody(ds)) : "",

    stepCard(++n, "range", "Valid range limits", "Physical and instrument limits for each variable", true, `
      <div class="table-wrap range-table"><table><thead><tr><th>Apply</th><th>Column</th><th>Minimum</th><th>Maximum</th></tr></thead><tbody>
      ${num.map(rangeRow).join("")}
      </tbody></table></div>
      <span class="hint muted">${esc(rangeHint)}</span>
      ${field("Values outside the limits", segmented("p-range-act", actions, BLANK))}`),

    stepCard(++n, "consistency", def.consistency_label, def.consistency_desc,
      rules.length > 0, rules.length ? `
      ${field("Rules to check", `<div class="pills">${rules.map((r, i) => `<label class="pill"><input type="checkbox" name="p-rules" value="${i}" checked><span>${esc(r[0])} ≤ ${esc(r[1])}</span></label>`).join("")}</div>`)}
      ${field("Tolerance", rangeCtl("tol", 0, 20, 0.5, 0, "%"), "Allow the first column to exceed the second by this much before flagging (instrument noise)")}
      ` : `<span class="muted">No pairs of related columns (such as "PM2.5" and "PM10") were found in this dataset.</span>`, { disabled: !rules.length }),

    stepCard(++n, "flatline", "Stuck sensor / flatline", "Find runs of identical consecutive readings", false, `
      ${field("Columns", pills("p-flat-cols", num, def.flat_cols), ds.instrument === "aws" ? "Rain and wind are left out by default: long runs of zero rain or calm wind are normal." : "")}
      <div class="grid-3">${field("Minimum run length", `<input type="number" class="p-flat-n" min="3" value="10" step="1">`, "Consecutive identical readings")}</div>
      ${field("Flagged readings", segmented("p-flat-act", [[BLANK, BLANK], [REMOVE, REMOVE]], BLANK))}`),

    stepCard(++n, "outliers", "Outlier detection", "Statistical spike and outlier filters", false, `
      <div class="grid-2">${field("Method", select("p-out-method", OPT.outlier_methods, OPT.outlier_methods[0]),
        "Hampel compares each reading with its neighbours, catching short spikes without removing genuine pollution episodes")}
        <div class="p-out-params"></div></div>
      ${field("Columns", pills("p-out-cols", num, ds.default_plot_cols))}
      ${field("Outliers", segmented("p-out-act", actions, REMOVE), "'Set value to blank' keeps the rest of the row, e.g. PM2.5 is kept when only PM10 is an outlier")}
      <div class="p-out-preview"></div>`),

    stepCard(++n, "missing", "Missing values", "Fill or drop gaps — also handles values blanked by the steps above", false, `
      <div class="grid-2">${field("Handling method", select("p-miss-method", OPT.missing_methods.filter((m) => hasDt || m !== "Time-weighted interpolation"), "Leave as is"))}
        ${field("Max consecutive gap to fill", `<input type="number" class="p-miss-limit" min="0" value="5" step="1">`, "Number of readings; 0 = no limit")}</div>
      ${field("Columns", pills("p-miss-cols", all, num))}`, { toggle: false }),

    stepCard(++n, "averaging", "Time averaging", hasDt ? "Resample to 15-minute, hourly, 8-hour or daily values" : "Needs a timestamp column", false, hasDt ? `
      <div class="grid-3">${field("Averaging period", select("p-avg-rule", OPT.averaging_rules, "1 hour"))}
        ${field("Statistic", select("p-avg-how", ["mean", "median", "max", "min"], "mean"))}
        ${field("Minimum data completeness", rangeCtl("comp", 0, 100, 5, 75, "%"), "Periods with fewer valid readings are left blank")}</div>
      <label class="check"><input type="checkbox" class="p-avg-drop" checked> Drop periods with no valid data</label>
      ${special.length ? `<label class="check"><input type="checkbox" class="p-avg-smart" checked> Instrument-aware aggregation</label>
        <span class="hint muted">${special.map(([c, how]) => `${esc(c)} ${AVG_WORDS[how]}`).join(" · ")}; other columns use the statistic above.</span>` : ""}` :
      `<span class="muted">Select a timestamp column to enable averaging.</span>`, { disabled: !hasDt }),
  ];

  const root = $("#pipeline");
  root.innerHTML = html.join("");
  renderOutlierParams();
  refreshPipeline();
}

function renderOutlierParams() {
  const root = $("#pipeline");
  const m = $(".p-out-method", root).value;
  const [SIGMA, IQR, HAMPEL] = OPT.outlier_methods;
  const s = outlierState;
  let html;
  if (m === SIGMA) html = field("k (number of standard deviations)", rangeCtl("sigmaK", 1.5, 6, 0.5, s.sigmaK));
  else if (m === IQR) html = field("IQR multiplier", rangeCtl("iqr", 1, 5, 0.5, s.iqr));
  else if (m === HAMPEL) html = `<div class="grid-2">${field("Window (readings)", rangeCtl("window", 5, 241, 2, s.window))}${field("k (scaled MADs)", rangeCtl("hampelK", 2, 8, 0.5, s.hampelK))}</div>`;
  else html = `<div class="grid-2">${field("Lower percentile", rangeCtl("lo", 0, 25, 0.5, s.lo))}${field("Upper percentile", rangeCtl("hi", 75, 100, 0.5, s.hi))}</div>`;
  $(".p-out-params", root).innerHTML = html;
}

function outlierParams(method) {
  const s = outlierState;
  return { k: method === OPT.outlier_methods[2] ? s.hampelK : s.sigmaK, iqr_mult: s.iqr, window: s.window, pct_range: [s.lo, s.hi] };
}

const isOn = (key) => !!$(`.step[data-step="${key}"] .step-toggle`)?.checked;

function refreshPipeline() {
  const root = $("#pipeline"), ds = state.dataset;
  const status = {
    columns: checked(root, "p-keep").length < ds.columns.length || !!$(".p-tw-on", root)?.checked,
    duplicates: isOn("duplicates"),
    qc: isOn("qc"),
    range: isOn("range"),
    consistency: isOn("consistency") && checked(root, "p-rules").length > 0,
    flatline: isOn("flatline"),
    outliers: isOn("outliers"),
    missing: $(".p-miss-method", root).value !== "Leave as is",
    averaging: isOn("averaging"),
  };
  if (!$('.step[data-step="qc"]', root)) delete status.qc;
  Object.entries(status).forEach(([key, on]) => {
    const step = $(`.step[data-step="${key}"]`, root);
    step.classList.toggle("on", on);
    $(".step-state", step).textContent = on ? "On" : "Off";
  });
  $("#pipeline-chips").innerHTML = Object.entries(status).map(([k, on]) => `<span class="chip ${on ? "" : "off"}">${STEP_NAMES[k]}</span>`).join("");
}

const refreshOutlierPreview = debounce(async () => {
  const root = $("#pipeline"), box = $(".p-out-preview", root);
  if (!isOn("outliers")) { box.innerHTML = ""; return; }
  const method = $(".p-out-method", root).value;
  const cols = checked(root, "p-out-cols");
  if (!cols.length) { box.innerHTML = `<span class="muted">Select at least one column.</span>`; return; }
  try {
    const dt = $(".p-dt", root).value;
    const res = await postJSON(`/api/dataset/${state.dataset.id}/outlier-preview`,
      { method, params: outlierParams(method), cols, dt_col: dt === "(none)" ? null : dt });
    box.innerHTML = field("Preview — readings flagged in the original data", tableHTML({
      columns: ["Column", "Flagged", "% of readings"], rows: res.rows.map((r) => [r.Column, r.Flagged, r["% of readings"]]),
    }));
  } catch (e) { box.innerHTML = `<span class="muted">${esc(e.message)}</span>`; }
}, 300);

$("#pipeline").addEventListener("click", (e) => {
  if (e.target.closest(".switch")) return;
  const head = e.target.closest(".step-head");
  if (head) head.parentElement.classList.toggle("open");
});
$("#pipeline").addEventListener("change", (e) => {
  if (e.target.matches(".step-toggle")) {
    const step = e.target.closest(".step");
    if (e.target.checked) step.classList.add("open");
  }
  if (e.target.matches(".p-out-method")) renderOutlierParams();
  refreshPipeline();
  if (e.target.closest('[data-step="outliers"]') || e.target.matches(".p-dt")) refreshOutlierPreview();
});
$("#pipeline").addEventListener("input", (e) => {
  const key = e.target.dataset.key;
  if (key && key in outlierState) { outlierState[key] = parseFloat(e.target.value); refreshOutlierPreview(); }
});

function collectConfig() {
  const root = $("#pipeline"), ds = state.dataset;
  const dt = $(".p-dt", root).value;
  const num = (sel) => { const v = $(sel, root)?.value; return v === "" || v === undefined ? null : parseFloat(v); };
  const method = $(".p-out-method", root).value;
  const twOn = $(".p-tw-on", root)?.checked;
  return {
    dt_col: dt === "(none)" ? null : dt,
    keep_cols: checked(root, "p-keep"),
    time_window: twOn ? [$(".p-tw-start", root).value.replace("T", " "), $(".p-tw-end", root).value.replace("T", " ")] : null,
    dedupe: isOn("duplicates"),
    dedupe_by_time: radioValue(root, "p-dedupe-by") === "time",
    range_on: isOn("range"),
    range_rules: $$(".range-table tbody tr", root).filter((tr) => $(".r-apply", tr).checked).map((tr) => ({
      Column: tr.dataset.col,
      Min: $(".r-min", tr).value === "" ? null : parseFloat($(".r-min", tr).value),
      Max: $(".r-max", tr).value === "" ? null : parseFloat($(".r-max", tr).value),
    })),
    range_action: radioValue(root, "p-range-act"),
    consistency_on: isOn("consistency"),
    consistency_rules: checked(root, "p-rules").map((i) => ds.consistency_rules[+i]),
    consistency_tol: num('[data-key="tol"]') || 0,
    flat_on: isOn("flatline"),
    flat_cols: checked(root, "p-flat-cols"),
    flat_n: num(".p-flat-n") || 10,
    flat_action: radioValue(root, "p-flat-act"),
    outlier_on: isOn("outliers"),
    outlier_cols: checked(root, "p-out-cols"),
    outlier_method: method,
    outlier_params: outlierParams(method),
    outlier_action: radioValue(root, "p-out-act"),
    missing_method: $(".p-miss-method", root).value,
    missing_cols: checked(root, "p-miss-cols"),
    missing_limit: num(".p-miss-limit") || 0,
    avg_on: isOn("averaging"),
    avg_rule: $(".p-avg-rule", root)?.value || "1 hour",
    avg_how: $(".p-avg-how", root)?.value || "mean",
    avg_completeness: num('[data-key="comp"]') ?? 75,
    avg_drop_empty: $(".p-avg-drop", root)?.checked ?? true,
    avg_smart: $(".p-avg-smart", root)?.checked ?? true,
    qc_on: isOn("qc"),
    qc: collectQc(root, ds),
  };
}

function collectQc(root, ds) {
  const qc = ds.defaults.qc;
  if (!qc || !isOn("qc")) return {};
  const val = (sel, d) => { const v = parseFloat($(sel, root)?.value); return Number.isFinite(v) ? v : d; };
  if (ds.instrument === "c12") {
    return {
      status_col: qc.status_col,
      codes: $$(".qc-code", root).filter((i) => i.checked).map((i) => +i.closest("tr").dataset.code),
      flow_col: qc.flow_col, flow_on: !!$(".qc-flow-on", root)?.checked,
      flow_nominal: val(".qc-flow-nominal", qc.flow_nominal), flow_tol: val(".qc-flow-tol", qc.flow_tol),
      zero_cols: qc.zero_cols, zero_on: !!$(".qc-zero-on", root)?.checked,
    };
  }
  return { reception_col: qc.reception_col, reception_on: !!$(".qc-rec-on", root)?.checked, reception_min: val(".qc-rec-min", 50) };
}

$("#apply-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
  const res = await postJSON("/api/clean", { dataset_id: state.dataset.id, config: collectConfig() });
  renderResults(res);
  markDone("clean");
  go("results");
  toast("Cleaning pipeline applied", "success");
}));

// -------------------------------
// STEP 4: RESULTS
// -------------------------------
const activateResultTab = bindTabs($('[data-tabs="results"]'), (name, panel) => {
  if (!panel.dataset.ready && state.result) {
    panel.dataset.ready = "1";
    RESULT_PANELS[name](panel, state.result);
  }
});

function renderResults(r) {
  state.result = r;
  $("#results-empty").hidden = true;
  $("#results-body").hidden = false;
  $("#results-sub").textContent = `Pipeline applied to ${state.dataset.name}. Change options in the Clean step and apply again to update.`;
  $("#results-time").textContent = `Applied at ${r.applied_at}`;
  $("#results-stats").innerHTML =
    stat("Initial rows", fmt(r.initial_rows, 0)) +
    stat("Rows removed", fmt(r.rows_removed, 0), "see Removed rows tab", r.rows_removed ? "red" : "") +
    stat("Values changed", fmt(r.values_changed, 0), "blanked, capped or filled", r.values_changed ? "amber" : "") +
    stat("Final rows", fmt(r.final_rows, 0), r.resampled ? "time-averaged periods" : "readings", "blue") +
    stat("Rows retained", `${fmt(r.retained_pct)}%`, "before any averaging");

  const head = ["Step", "Details", "Rows removed", "Values changed"].map((c) => `<th>${c}</th>`).join("");
  const badge = (n, cls) => (n ? `<span class="badge ${cls}">${fmt(n, 0)}</span>` : `<span class="muted">0</span>`);
  $("#results-log").innerHTML = `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${r.log.map((l) =>
    `<tr><td><b>${esc(l.Step)}</b></td><td style="white-space:normal">${esc(l.Details)}</td>` +
    `<td class="num">${badge(l["Rows removed"], "badge-red")}</td><td class="num">${badge(l["Values changed"], "badge-amber")}</td></tr>`).join("")}</tbody></table></div>`;

  const instTab = $('[data-tabs="results"] [data-tab="inst"]');
  instTab.hidden = !r.instrument_tab;
  instTab.textContent = r.instrument_tab || "Instrument";
  $$('[data-tabs="results"] ~ .tab-panel').forEach((p) => {
    $$(".js-plotly-plot", p).forEach((el) => Plotly.purge(el));
    p.innerHTML = "";
    delete p.dataset.ready;
  });
  const base = `/api/result/${r.result_id}/download`;
  $("#dl-cleaned").href = `${base}/cleaned`;
  $("#dl-report").href = `${base}/report`;
  $("#dl-removed").href = `${base}/removed`;
  $("#dl-removed").classList.toggle("disabled", !r.removed_count);
  $("#dl-zip").href = `${base}/zip`;
  // Draw after the results view is visible so charts get their full width
  setTimeout(() => activateResultTab("ts"), 0);
}

const resultURL = (r) => `/api/result/${r.result_id}/chart`;

const RESULT_PANELS = {
  ts(panel, r) {
    Explorer(panel, { numericCols: r.numeric_cols, defaults: r.default_plot_cols, endpoint: resultURL(r), extra: { type: "timeseries" } });
  },

  ba(panel, r) {
    panel.innerHTML = `<div class="controls-row">${field("Variable", select("ba-col", r.numeric_cols, r.default_plot_cols[0]))}
      <label class="check" style="padding-bottom:10px"><input type="checkbox" class="ba-collapse" checked> Collapse data gaps</label></div>
      <div class="chart chart-lg"></div><div class="mini-stats"></div>`;
    const draw = async () => {
      const extra = await drawChart($(".chart", panel), () => postJSON(resultURL(r),
        { type: "before_after", col: $(".ba-col", panel).value, collapse_gaps: $(".ba-collapse", panel).checked }));
      if (extra?.stats) {
        $(".mini-stats", panel).innerHTML = Object.entries(extra.stats).map(([k, s]) =>
          stat(k, fmt(s.value, 2), `<span class="delta">${s.delta >= 0 ? "+" : ""}${fmt(s.delta, 2)} vs original</span>`)).join("");
      }
    };
    panel.addEventListener("change", draw);
    draw();
  },

  dist(panel, r) {
    panel.innerHTML = `<div class="controls-row">${field("Variable", select("d-col", r.numeric_cols, r.default_plot_cols[0]))}
      ${field("Number of bins", rangeCtl("bins", 10, 150, 5, 50))}</div>
      <div class="grid-2" style="grid-template-columns:3fr 2fr"><div class="chart d-hist"></div><div class="chart d-box"></div></div>`;
    const draw = debounce(() => {
      const col = $(".d-col", panel).value;
      drawChart($(".d-hist", panel), () => postJSON(resultURL(r), { type: "distribution", col, bins: +$('[data-key="bins"]', panel).value }));
      drawChart($(".d-box", panel), () => postJSON(resultURL(r), { type: "box", col }));
    }, 200);
    panel.addEventListener("change", draw);
    draw();
  },

  diurnal(panel, r) {
    if (!r.dt_col) { panel.innerHTML = `<div class="chart-empty">A timestamp column is needed for the diurnal profile.</div>`; return; }
    const name = nextId("diu");
    panel.innerHTML = `<div class="controls-row"><div class="field" style="flex:1">${"<label>Variables</label>" + pills(name, r.numeric_cols, r.default_plot_cols)}</div>
      <label class="check" style="padding-bottom:8px"><input type="checkbox" class="diu-split"> Weekdays vs weekends</label></div>
      <div class="chart chart-lg"></div>
      <p class="muted" style="margin-top:10px">How concentrations typically vary through the day. Data covering several days gives a more meaningful pattern.</p>`;
    const draw = () => {
      const cols = checked(panel, name);
      if (!cols.length) return chartMessage($(".chart", panel), "Select at least one variable");
      drawChart($(".chart", panel), () => postJSON(resultURL(r), { type: "diurnal", cols, split: $(".diu-split", panel).checked }));
    };
    panel.addEventListener("change", draw);
    draw();
  },

  rel(panel, r) {
    if (r.numeric_cols.length < 2) { panel.innerHTML = `<div class="chart-empty">At least two numeric columns are needed.</div>`; return; }
    const [a, b] = r.default_plot_cols.length > 1 ? r.default_plot_cols : r.numeric_cols;
    panel.innerHTML = `<div class="controls-row">${field("X axis", select("rel-x", r.numeric_cols, b))}${field("Y axis", select("rel-y", r.numeric_cols, a))}</div>
      <div class="grid-2" style="grid-template-columns:3fr 2fr"><div class="chart rel-scatter"></div><div class="chart rel-corr"></div></div>
      <div class="mini-stats"></div>`;
    const draw = async () => {
      const x = $(".rel-x", panel).value, y = $(".rel-y", panel).value;
      const extra = await drawChart($(".rel-scatter", panel), () => postJSON(resultURL(r), { type: "relationship", x, y }));
      const s = extra?.stats;
      $(".mini-stats", panel).innerHTML = s ? stat("R²", fmt(s.r2, 3)) + stat("Slope", fmt(s.slope, 3)) +
        stat(`Median ratio ${y} / ${x}`, fmt(s.median_ratio, 2)) + stat("Paired readings", fmt(s.n, 0)) : "";
    };
    panel.addEventListener("change", draw);
    draw();
    drawChart($(".rel-corr", panel), () => postJSON(resultURL(r), { type: "correlation" }));
  },

  async data(panel, r) {
    panel.innerHTML = `<div class="field"><label>Descriptive statistics (cleaned)</label><div class="d-stats"></div></div>
      <div class="field mt"><label>Cleaned data</label><div class="d-table"></div></div>`;
    try { $(".d-stats", panel).innerHTML = tableHTML(await api(`/api/result/${r.result_id}/table/stats`)); }
    catch (e) { toast(e.message, "error"); }
    pagedTable($(".d-table", panel), `/api/result/${r.result_id}/table/cleaned`);
  },

  removed(panel, r) {
    if (!r.removed_count) { panel.innerHTML = `<div class="notice">No rows were removed by this pipeline.</div>`; return; }
    panel.innerHTML = `<div class="chart" style="min-height:260px"></div><div class="field mt"><label>Removed rows with reasons</label><div class="rm-table"></div></div>`;
    drawChart($(".chart", panel), () => postJSON(resultURL(r), { type: "removed" }));
    pagedTable($(".rm-table", panel), `/api/result/${r.result_id}/table/removed`);
  },

  inst(panel, r) {
    if (r.instrument === "aws") {
      const name = nextId("rose");
      panel.innerHTML = `<div class="controls-row">${field("Data", segmented(name, [["clean", "Cleaned"], ["raw", "Original"]], "clean"))}</div>
        <div class="chart chart-lg"></div><p class="muted rose-note" style="margin-top:10px"></p>`;
      const draw = async () => {
        const extra = await drawChart($(".chart", panel), () => postJSON(resultURL(r), { type: "windrose", stage: radioValue(panel, name) }));
        if (extra?.stats) $(".rose-note", panel).textContent = `Share of ${fmt(extra.stats.readings, 0)} readings by direction and speed class ` +
          `(speed in the units the station logs). ${fmt(extra.stats.calm_pct)}% had no direction recorded (calm or missing) and are not drawn. ` +
          "Built from readings before any time averaging.";
      };
      panel.addEventListener("change", draw);
      draw();
    } else if (r.instrument === "c12") {
      panel.innerHTML = `<div class="chart" style="min-height:300px"></div>
        <p class="muted" style="margin-top:10px">Readings in the original data carrying each status code (a reading can carry several).
        Red codes are error conditions; amber codes are logged by the instrument as not errors. Meanings follow the Met One C-12 operation manual (C-12-9800 Rev A), Table 7-1.</p>`;
      drawChart($(".chart", panel), () => postJSON(resultURL(r), { type: "alarms" }));
    }
  },
};

// ===== START =====
cleanDrop.configure({ exts: ["csv", "txt", "tsv"], hint: "A converted CSV, or one raw DustTrak, station or C-12 Data.CSV file" });
let savedInstrument = "dusttrak";
try { savedInstrument = localStorage.getItem("aq-instrument") || "dusttrak"; } catch {}
setInstrument(savedInstrument in OPT.instruments ? savedInstrument : "dusttrak");
go(location.hash.slice(1) || "convert");
