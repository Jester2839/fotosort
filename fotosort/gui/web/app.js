"use strict";
// UI Fotosortu. Veškerá práce běží v Pythonu (fotosort/gui/app.py) přes window.pywebview.api.

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("cs-CZ");
const n = (x) => nf.format(x ?? 0);
function size(b) {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${i < 2 ? Math.round(b) : b.toFixed(1).replace(".", ",")} ${u[i]}`;
}
const STRICT = {
  1: ["Mírná", "AI nic nevyhazuje – do _ke_smazani jdou jen technicky špatné fotky."],
  2: ["Vyvážená", "Nejslabších 20 % podle AI jde také do _ke_smazani."],
  3: ["Přísná", "Nejslabších 30 % jde do _ke_smazani, do výběru jen horních 30 %."],
};
const ICON = {
  back: '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  logo: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0B1220" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="12" cy="12" r="3.5"/></svg>',
  card: '<svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#7FB0FF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h9l4 4v14H6z"/><path d="M10 7v3M13 7v3M12 13v5M9.5 15.5L12 18l2.5-2.5"/></svg>',
  folder: '<svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#E8B04A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M8 13h8M12 9v8"/></svg>',
  check: '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#7DDBA6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>',
  warn: '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex:none;margin-top:2px"><path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
};

const S = {
  init: null, screen: "start",
  scan: null, scanError: "", cuts: new Set(), names: [], preview: null,
  opts: { sort: true, ai: true, categories: true, strictness: 2 },
  job: null, results: null,
};

// --- komunikace s Pythonem ------------------------------------------------------------------

async function call(method, ...args) {
  try {
    const r = await window.pywebview.api[method](...args);
    if (r && r.error) { toast(r.error); return null; }
    return r;
  } catch (e) { toast(`Chyba: ${e.message || e}`); return null; }
}
let toastTimer;
function toast(msg, ok = false) {
  const t = $("#toast"); t.textContent = msg; t.className = ok ? "toast ok" : "toast"; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ok ? 3500 : 8000);
}

// Události z běžící úlohy (Api._emit).
window.fs = {
  event(e) {
    const j = S.job; if (!j) return;
    if (e.type === "stage") { j.stage = e.stage; j.folder = e.folder || j.folder; j.done = 0; j.total = 0; j.name = "";
      if (e.stage === "analyze") j.eventIndex += 1; }
    else if (e.type === "progress") { j.stage = e.stage; j.done = e.done; j.total = e.total; j.name = e.name; }
    else if (e.type === "log") { j.log.push(e); }
    else if (e.type === "done") { S.results = e; S.job = null; go("done"); return; }
    else if (e.type === "cancelled") { S.job = null; toast("Zrušeno. Nic se nepřesunulo; už zkopírované soubory zůstaly."); go("start"); return; }
    else if (e.type === "error") { j.error = e.msg; }
    if (S.screen === "progress") renderProgress();
  },
};

function go(screen) { S.screen = screen; window.scrollTo(0, 0); render(); }

// --- horní lišta ----------------------------------------------------------------------------

function topbar({ back, title, sub } = {}) {
  const ai = S.init?.ai;
  $("#topbar").innerHTML = `
    ${back ? `<button class="icon-btn" aria-label="Zpět" data-act="${back}">${ICON.back}</button>` : ""}
    ${title ? `<div class="title"><b>${esc(title)}</b><span>${esc(sub || "")}</span></div>`
            : `<div class="brand" style="flex:1"><span class="logo">${ICON.logo}</span>Fotosort</div>`}
    <span class="status"><span class="dot ${ai ? "" : "off"}"></span>${ai ? "Lokální AI připravena" : "AI není nainstalovaná – jen technická kontrola"}</span>`;
}

// --- start ----------------------------------------------------------------------------------

function renderStart() {
  topbar();
  const { cards, recent, root, rootExists } = S.init;
  const banner = cards.length
    ? cards.map((c) => `<div class="banner">${ICON.card}<div class="t"><b>Připojena karta ${esc(c.label)}</b>
        <span>Fotky se zkopírují do knihovny, karta zůstane beze změny.</span></div>
        <button class="btn primary" data-act="import" data-card="${esc(c.path)}">Importovat</button></div>`).join("")
    : `<div class="note info">Vlož SD kartu – poznám ji podle složky DCIM.</div>`;
  $("#screen").innerHTML = `<main>
    ${banner}
    ${rootExists ? "" : `<div class="note warn">${ICON.warn}<span>Knihovna <span class="mono">${esc(root)}</span> neexistuje. Vytvoří se při prvním importu, nebo vyber jinou.</span></div>`}
    <div><h1>Co chceš udělat?</h1>
      <p class="lead">AI fotky jen hrubě roztřídí. Nic se nemaže – vyřazené čekají ve složce _ke_smazani.</p></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
      <button class="mode" data-act="import" data-card="${esc(cards[0]?.path || "")}" ${cards.length ? "" : "disabled"}>
        <span class="ico" style="background:#1e2e4d">${ICON.card}</span><b>Import z SD karty</b>
        <span>Rozdělí fotky na akce podle dnů, vytvoří složky, zkopíruje s ověřením a rovnou roztřídí.</span></button>
      <button class="mode" data-act="pick-cull">
        <span class="ico" style="background:#2a2620">${ICON.folder}</span><b>Roztřídit existující složku</b>
        <span>Vybereš složku akce. Vyřazené se přesunou do _ke_smazani, zbytek dostane hvězdičky v XMP.</span></button>
    </div>
    <section style="display:flex;flex-direction:column;gap:12px">
      <div class="row" style="justify-content:space-between"><h2>Poslední akce</h2>
        <span class="small">Knihovna: <span class="mono">${esc(root)}</span> · <button class="btn ghost" style="padding:4px 8px" data-act="root">Změnit…</button></span></div>
      ${recent.length ? `<div class="list">${recent.map((r) => `<div class="item">
          <span class="n">${esc(r.name)}</span>
          ${r.culled ? '<span class="pill good">Roztříděno</span>' : '<span class="pill neutral">Neroztříděno</span>'}
          <button class="btn" data-act="open" data-path="${esc(r.path)}">Otevřít</button>
          ${r.culled ? "" : `<button class="btn" data-act="cull" data-path="${esc(r.path)}">Roztřídit</button>`}
        </div>`).join("")}</div>`
        : `<div class="note info">Zatím tu nejsou žádné akce.</div>`}
    </section></main>`;
}

// --- import ---------------------------------------------------------------------------------

async function startImport(card) {
  S.scan = null; S.scanError = ""; S.preview = null; go("import");
  const r = await call("scan", card);
  if (!r) { S.scanError = "Kartu se nepodařilo načíst."; render(); return; }
  S.scan = r; S.cuts = new Set(r.cuts); S.names = [];
  render(); refreshPreview();
}

function renderImport() {
  topbar({ back: "home", title: "Import z SD karty", sub: S.scan ? S.scan.label : "Načítám kartu…" });
  const sc = S.scan;
  if (!sc) {
    $("#screen").innerHTML = `<main>${S.scanError
      ? `<div class="note bad">${ICON.warn}<span>${esc(S.scanError)}</span></div><div><button class="btn" data-act="home">Zpět</button></div>`
      : `<div class="loading"><span class="spinner"></span>Čtu data fotek z karty…</div>`}</main>`;
    return;
  }
  if (!sc.days.length) {
    $("#screen").innerHTML = `<main><div><h1>Všechno už je v knihovně</h1>
      <p class="lead">Na kartě je ${n(sc.total)} snímků a všechny už jsou importované. Není co dělat.</p></div>
      <div><button class="btn" data-act="home">Zpět na start</button></div></main>`;
    return;
  }
  const peak = Math.max(...sc.days.map((d) => d.count));
  const timeline = sc.days.map((d, i) => `
      ${i > 0 ? `<button class="cut ${S.cuts.has(i) ? "on" : ""}" data-act="cut" data-i="${i}" aria-pressed="${S.cuts.has(i)}">${S.cuts.has(i) ? "nová akce · kliknutím zrušíš" : "rozdělit tady"}</button>` : ""}
      <div class="day"><span>${esc(d.label)}</span><span class="bar" style="width:${Math.max(2, (d.count / peak) * 100)}%"></span><span class="c">${n(d.count)}</span></div>`).join("");
  const o = S.opts;
  $("#screen").innerHTML = `<main><div class="cols">
    <div class="main">
      <section class="panel"><h2>Karta</h2>
        <div class="stats">
          <div class="stat"><span>Nové fotky</span><b>${n(sc.photos)}${sc.pairs ? ` · ${n(sc.pairs)} RAW+JPG` : ""}</b></div>
          <div class="stat"><span>Nová videa</span><b>${n(sc.videos)}</b></div>
          <div class="stat"><span>Už v knihovně</span><b>${n(sc.old)} (přeskočím)</b></div>
          <div class="stat"><span>Dny focení</span><b>${n(sc.days.length)}</b></div>
        </div>
        ${sc.guessed ? `<div class="note warn">${ICON.warn}<span>${n(sc.guessed)} souborů nemá datum v metadatech – beru datum souboru, může být nepřesné.</span></div>` : ""}
      </section>
      <section class="panel"><h2>Rozdělení na akce</h2>
        <p class="small">Novou akci navrhuji po ${n(sc.gap)} a více dnech bez focení. Kliknutím mezi dny ji přidáš nebo zrušíš.</p>
        <div class="timeline">${timeline}</div>
        <div id="events" style="display:flex;flex-direction:column;gap:10px"></div>
      </section>
      <section class="panel"><h2>Třídění</h2>
        <label class="check"><input type="checkbox" data-opt="sort" ${o.sort ? "checked" : ""}><span>Po importu rovnou roztřídit<br><span class="d">Vyřazené do _ke_smazani, výběr ★★★ a nejisté ★ do XMP</span></span></label>
        ${optsHtml()}
      </section>
    </div>
    <aside class="side" id="import-side"></aside>
  </div></main>`;
  renderEvents();
  renderImportSide();
}

function optsHtml() {
  const o = S.opts, dis = S.init.ai ? "" : "disabled";
  return `
    <label class="check"><input type="checkbox" data-opt="ai" ${o.ai && S.init.ai ? "checked" : ""} ${dis}><span>AI hodnocení a zavřené oči<br><span class="d">${S.init.ai ? "Bez něj jen ostrost, série a expozice" : "Není nainstalované (viz README) – proběhne jen technická kontrola"}</span></span></label>
    <label class="check"><input type="checkbox" data-opt="categories" ${o.categories ? "checked" : ""} ${dis}><span>Klíčová slova podle obsahu<br><span class="d">Fotosort › Obsah › Lidi, Krajina, Zvířata…</span></span></label>
    <label class="field"><span>Přísnost: <b id="strict-label">${STRICT[o.strictness][0]}</b></span>
      <input type="range" min="1" max="3" step="1" value="${o.strictness}" data-opt="strictness" ${dis} aria-describedby="strict-help">
      <span class="small" id="strict-help">${STRICT[o.strictness][1]}</span></label>`;
}

function renderEvents() {
  const ev = $("#events"); if (!ev) return;
  const count = S.cuts.size + 1;
  S.names.length = count;
  ev.innerHTML = Array.from({ length: count }, (_, i) => `<div class="event">
      <div class="row" style="justify-content:space-between"><b data-ev-title="${i}">Akce ${i + 1}</b>
        <span class="small" data-ev-count="${i}"></span></div>
      <label class="name"><span data-ev-prefix="${i}"></span>
        <input type="text" data-name="${i}" value="${esc(S.names[i] || "")}" aria-label="Název akce ${i + 1}" placeholder="název, např. Norsko"></label></div>`).join("");
}

function renderImportSide() {
  const side = $("#import-side"); if (!side || !S.scan) return;
  const p = S.preview;
  // Popisky akcí měníme na místě, aby psaní do názvu neztrácelo fokus.
  (p?.events || []).forEach((e, i) => {
    const t = document.querySelector(`[data-ev-title="${i}"]`); if (!t) return;
    t.textContent = `Akce ${i + 1} · ${e.range}`;
    document.querySelector(`[data-ev-count="${i}"]`).textContent = `${n(e.photos)} fotek${e.videos ? `, ${n(e.videos)} videí` : ""}`;
    document.querySelector(`[data-ev-prefix="${i}"]`).textContent = `${e.prefix}_`;
  });
  const sorted = S.opts.sort;
  const short = (path) => path.split(/[\\/]/).slice(-2).join("\\");
  const tree = p ? p.events.map((e) => `${esc(short(e.path))}\\
  ├─ fotky (★★★ výběr, ★ nejisté)  → do Lightroomu
  ├─ _upraveno\\${e.videos ? "\n  ├─ video\\" : ""}
  └─ <span style="color:var(--bad)">_ke_smazani\\</span>${sorted ? "" : "  (až po třídění)"}`).join("\n\n") : "…";
  side.innerHTML = `
    <section class="panel"><h2>Kam to půjde</h2>
      <span class="small mono" style="overflow-wrap:anywhere">${esc(S.init.root)}\\</span><div class="tree mono">${tree}</div>
      <p class="small">Výběr a nejisté zůstanou přímo ve složce akce, rozliší je hvězdičky a klíčová slova v XMP.</p></section>
    ${p && !p.enough ? `<div class="note bad">${ICON.warn}<span>Na disku není dost místa: potřeba ${size(p.needed)}, volno ${size(p.free)}.</span></div>` : ""}
    <button class="btn primary big" data-act="run-import" ${p && p.enough ? "" : "disabled"}>${sorted ? "Spustit import a třídění" : "Spustit import"}</button>
    <span class="small" style="text-align:center">${p ? `${size(p.needed)} · volno ${size(p.free)}` : "Počítám…"}</span>`;
}

let previewTimer;
function refreshPreview(delay = 0) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const r = await call("preview", [...S.cuts], S.names.map((x) => x || ""));
    if (r) { S.preview = r; renderImportSide(); }
  }, delay);
}

// --- průběh ---------------------------------------------------------------------------------

const STAGES = { copy: "Kopírování a ověření", analyze: "Technická kontrola", ai: "AI hodnocení", apply: "Přesun a zápis XMP" };

function beginJob(kind, folders) {
  S.job = { kind, stage: kind === "import" ? "copy" : "analyze", done: 0, total: 0, name: "", log: [], error: "",
            eventIndex: 0, events: folders, folder: "" };
  go("progress");
}

function renderProgress() {
  const j = S.job; if (!j) return;
  const order = j.kind === "import" && S.opts.sort ? ["copy", "analyze", "ai", "apply"]
              : j.kind === "import" ? ["copy"] : ["analyze", "ai", "apply"];
  const steps = order.filter((s) => s !== "ai" || (S.opts.ai && S.init.ai));
  const cur = steps.indexOf(j.stage);
  const pct = j.total ? Math.floor((j.done / j.total) * 100) : 0;
  const amount = j.stage === "copy" ? `${size(j.done)} z ${size(j.total)}` : j.total ? `${n(j.done)} z ${n(j.total)}` : "";
  const multi = j.events > 1 && j.stage !== "copy" ? ` · akce ${j.eventIndex} z ${j.events}` : "";
  topbar({ title: j.kind === "import" ? "Import a třídění" : "Třídění", sub: (j.folder || "") + multi });
  $("#screen").innerHTML = `<main style="max-width:880px">
    ${j.error ? `<div class="note bad">${ICON.warn}<span>${esc(j.error)}</span></div><div><button class="btn" data-act="home">Zpět na start</button></div>` : `
    <section style="display:flex;flex-direction:column;gap:14px">
      <div class="row" style="justify-content:space-between;align-items:baseline">
        <h1>${esc(STAGES[j.stage])}… <span style="color:var(--accent-text)">${j.total ? pct + " %" : ""}</span></h1>
        <span class="small">${esc(amount)}</span></div>
      <div class="bar-wrap" role="progressbar" aria-label="Průběh" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="bar-fill" style="width:${pct}%"></div></div>
      <span class="small mono" style="min-height:1.5em">${esc(j.name)}</span>
    </section>`}
    <div class="cols">
      <ol class="steps panel main" style="flex:1 1 300px">${steps.map((s, i) => `<li class="${i < cur ? "ok" : i === cur && !j.error ? "now" : ""}"><span class="s">${i < cur ? ICON.check : ""}</span>${STAGES[s]}</li>`).join("")}</ol>
      <section class="panel side" style="position:static;flex:2 1 360px"><h2>Zprávy</h2>
        <div class="log" aria-live="polite">${j.log.length ? j.log.map((l) => `<span class="${l.level === "warn" ? "warn" : ""}">${esc(l.msg)}</span>`).join("") : '<span>Zatím nic.</span>'}</div></section>
    </div>
    ${j.error ? "" : `<div class="row"><button class="btn danger" data-act="cancel">Zrušit</button>
      <span class="small">Zrušení nic nepřesune. Při importu zůstanou už zkopírované soubory a příště se přeskočí.</span></div>`}
  </main>`;
}

// --- hotovo ---------------------------------------------------------------------------------

function renderDone() {
  const r = S.results;
  topbar({ back: "home", title: "Hotovo", sub: r.copied != null ? `Zkopírováno ${n(r.copied)} souborů, přeskočeno ${n(r.skipped)}` : "" });
  const cards = r.results.map((x) => {
    if (!x.sorted) return `<section class="panel result"><div class="head"><h2>${esc(x.name)}</h2><span class="pill neutral">Neroztříděno</span></div>
      <div class="row"><button class="btn" data-act="open" data-path="${esc(x.folder)}">Otevřít složku</button>
      <button class="btn primary" data-act="cull" data-path="${esc(x.folder)}">Roztřídit teď</button></div></section>`;
    if (!x.total) return `<section class="panel result"><h2>${esc(x.name)}</h2><p class="small">Ve složce nejsou žádné fotky.</p></section>`;
    const reasons = Object.entries(x.reasons).map(([k, v]) => `${esc(k)} ${n(v)}`).join(" · ") || "nic";
    return `<section class="panel result">
      <div class="head"><h2>${esc(x.name)}</h2><span class="small">${n(x.total)} snímků · ${n(x.series)} sérií</span></div>
      <div class="nums">
        ${x.used_ai ? `<div class="num"><span class="k good">Výběr · ★★★</span><span class="v">${n(x.good)}</span><span class="h">ve složce akce</span></div>
        <div class="num"><span class="k warn">Nejisté · ★</span><span class="v">${n(x.unsure)}</span><span class="h">ve složce akce</span></div>`
        : `<div class="num" style="grid-column:span 2"><span class="k">Bez AI</span><span class="v">${n(x.untouched)}</span><span class="h">zůstalo ve složce akce bez hodnocení</span></div>`}
        <div class="num"><span class="k bad">Ke smazání</span><span class="v">${n(x.delete)}</span><span class="h">${reasons}</span></div>
      </div>
      ${x.foreign ? `<div class="note warn">${ICON.warn}<span>${n(x.foreign)} fotek už mělo vlastní XMP (třeba z Lightroomu) – nechal jsem je bez hodnocení.</span></div>` : ""}
      <div class="row">
        <button class="btn" data-act="open" data-path="${esc(x.folder)}">Otevřít složku akce</button>
        ${x.delete ? `<button class="btn" data-act="open" data-path="${esc(x.folder)}\\_ke_smazani">Prohlédnout _ke_smazani</button>
        <button class="btn danger" data-act="trash" data-path="${esc(x.folder)}" data-count="${x.delete}">Přesunout _ke_smazani do Koše…</button>` : ""}
        <button class="btn ghost" data-act="undo" data-path="${esc(x.folder)}">Vrátit třídění</button>
      </div></section>`;
  }).join("");
  $("#screen").innerHTML = `<main><div class="cols">
    <div class="main">${cards}</div>
    <aside class="side"><section class="panel"><h2>Další krok v Lightroomu Classic</h2>
      <ol class="howto">
        <li>Import › <b>Přidat</b> složku akce, <b>bez</b> „Zahrnout podsložky“ (tím vynecháš _ke_smazani i _upraveno)</li>
        <li>Filtr podle hvězdiček: ★★★ = výběr, ★ = nejisté</li>
        <li>Klíčová slova Fotosort › … se hodí do chytrých kolekcí</li>
      </ol>
      ${S.init.lightroom ? '<button class="btn primary" data-act="lightroom">Otevřít Lightroom</button>' : '<span class="small">Lightroom jsem nenašel (cesta je v config.py).</span>'}
    </section>
    <button class="btn" data-act="home">Zpět na start</button></aside>
  </div></main>`;
}

// --- dialogy --------------------------------------------------------------------------------

function modal(html) { $("#modal").innerHTML = html ? `<div class="backdrop" data-act="close-modal-bg">${html}</div>` : ""; $("#modal").querySelector("button.primary, button.danger-solid")?.focus(); }

function cullDialog(folder) {
  S.pendingCull = folder;
  modal(`<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-t">
    <h2 id="dlg-t">Roztřídit složku</h2><p class="mono" style="overflow-wrap:anywhere">${esc(folder)}</p>
    ${optsHtml()}
    <div class="row"><button class="btn" data-act="close-modal">Zrušit</button><button class="btn primary" data-act="run-cull">Roztřídit</button></div></div>`);
}

function trashDialog(folder, count) {
  modal(`<div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t" aria-describedby="dlg-d">
    <h2 id="dlg-t">Přesunout _ke_smazani do Koše?</h2>
    <p id="dlg-d">${n(count)} fotek (RAW i JPG) půjde do Koše Windows. Dokud Koš nevysypeš, jdou obnovit. Vrátit třídění pak už nepůjde.</p>
    <div class="row"><button class="btn" data-act="close-modal">Nechat</button>
      <button class="btn danger-solid" data-act="do-trash" data-path="${esc(folder)}">Přesunout do Koše</button></div></div>`);
}

// --- akce -----------------------------------------------------------------------------------

async function act(name, el) {
  switch (name) {
    case "home": S.init = (await call("init")) || S.init; go("start"); break;
    case "import": if (el.dataset.card) startImport(el.dataset.card); break;
    case "root": { const r = await call("choose_root"); if (r) { S.init.root = r.root; S.init.recent = r.recent; render(); } break; }
    case "open": call("open_path", el.dataset.path); break;
    case "lightroom": call("open_lightroom"); break;
    case "pick-cull": { const f = await call("choose_folder"); if (f) cullDialog(f); break; }
    case "cull": cullDialog(el.dataset.path); break;
    case "cut": { const i = +el.dataset.i; S.cuts.has(i) ? S.cuts.delete(i) : S.cuts.add(i); renderImport(); refreshPreview(); break; }
    case "run-import": {
      const r = await call("start_import", [...S.cuts], S.names.map((x) => x || ""), { ...S.opts, ai: S.opts.ai && S.init.ai });
      if (r) beginJob("import", S.cuts.size + 1); break;
    }
    case "run-cull": {
      const r = await call("start_cull", S.pendingCull, { ...S.opts, ai: S.opts.ai && S.init.ai });
      if (r) { modal(""); beginJob("cull", 1); } break;
    }
    case "cancel": el.disabled = true; el.textContent = "Ruším…"; call("cancel"); break;
    case "undo": {
      const r = await call("undo", el.dataset.path);
      if (r) { toast(`Vráceno: ${n(r.restored)} souborů a XMP. Složka je jako před tříděním.`, true);
        S.results.results = S.results.results.map((x) => x.folder === el.dataset.path ? { folder: x.folder, name: x.name, sorted: false } : x); render(); }
      break;
    }
    case "trash": trashDialog(el.dataset.path, +el.dataset.count); break;
    case "do-trash": {
      const r = await call("trash", el.dataset.path); modal("");
      if (r) { toast("_ke_smazani je v Koši.", true);
        S.results.results = S.results.results.map((x) => x.folder === el.dataset.path ? { ...x, delete: 0, reasons: {} } : x); render(); }
      break;
    }
    case "close-modal": modal(""); break;
  }
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]"); if (!el || el.disabled) return;
  if (el.dataset.act === "close-modal-bg" && e.target !== el) return;  // klik do dialogu, ne na pozadí
  act(el.dataset.act === "close-modal-bg" ? "close-modal" : el.dataset.act, el);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#modal").innerHTML) modal(""); });
document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.dataset.name != null) { S.names[+t.dataset.name] = t.value; refreshPreview(300); }
  if (t.dataset.opt === "strictness") {
    S.opts.strictness = +t.value; $("#strict-label").textContent = STRICT[t.value][0]; $("#strict-help").textContent = STRICT[t.value][1];
  }
});
document.addEventListener("change", (e) => {
  const t = e.target; if (t.type !== "checkbox" || !t.dataset.opt) return;
  S.opts[t.dataset.opt] = t.checked;
  if (t.dataset.opt === "sort" && S.screen === "import") renderImportSide();
});

function render() {
  ({ start: renderStart, import: renderImport, progress: renderProgress, done: renderDone })[S.screen]();
}

// Karta se může připojit kdykoli – na startu se každé 3 s podíváme.
setInterval(async () => {
  if (S.screen !== "start" || !S.init) return;
  const cards = await window.pywebview.api.cards();
  if (JSON.stringify(cards) !== JSON.stringify(S.init.cards)) { S.init.cards = cards; renderStart(); }
}, 3000);

window.addEventListener("pywebviewready", async () => {
  S.init = await call("init");
  if (!S.init) return;
  S.opts.strictness = S.init.strictness;
  S.opts.ai = S.init.ai;
  render();
});
