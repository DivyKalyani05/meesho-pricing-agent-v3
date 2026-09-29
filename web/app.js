"use strict";
/* Kurti Pricing Agent - front end (vanilla JS, no external dependencies) */

const state = { meta: null, result: null, lang: "en", photos: [], touched: new Set(), dbLoaded: false, busy: false,
  lastBody: null, listed: null, lSeller: null, lMode: "balanced", lData: null, lFilter: "all", lOpen: new Set(),
  ai: {}, lAi: {}, confirmDelist: null, toast: null,
  db: { schema: null, table: null, page: 1, size: 25, q: "", filterCol: "", filterVal: "", sort: "", dir: "asc" } };
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const form = $("#form");
const ATTRS = ["product_type", "fabric", "pattern", "occasion", "sleeve", "length"];
// namedItem() avoids collisions with built-ins such as form.elements.length
const fe = name => form.elements.namedItem(name);

// ------------------------------------------------------------------ utils
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inr(x, digits = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  const n = Number(x);
  const s = Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return (n < 0 ? "−₹" : "₹") + s;
}
function num(x, d = 1) {
  if (x === null || x === undefined) return "–";
  return Number(x).toLocaleString("en-IN", { maximumFractionDigits: d });
}
function tr(obj) { return obj ? (obj[state.lang] || obj.en) : ""; }
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new Error("Can't reach the pricing server. Is it still running?"); }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Server error (${res.status})`);
  return data;
}

// ------------------------------------------------------------------ setup
async function init() {
  try { await api("/api/demo/restore", {}); } catch (e) { /* not critical */ }
  try {
    state.meta = await api("/api/meta");
  } catch (e) {
    $("#empty").innerHTML = `<h2>Couldn't start</h2><p class="error">${esc(e.message)}</p>`;
    return;
  }
  const m = state.meta;
  const sellerSel = fe("seller_id");
  sellerSel.innerHTML = m.sellers.map(s => `<option value="${s.seller_id}">${esc(s.name)} · ${esc(s.city)}</option>`).join("") +
    `<option value="">Other seller (no history)</option>`;
  for (const a of ATTRS) {
    fe(a).innerHTML = m.options[a].map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
    fe(a).addEventListener("change", () => { state.touched.add(a); fe(a).closest("label").classList.remove("detected"); });
  }
  $("#modes").innerHTML = m.modes.map((md, i) => `
    <label class="mode${i === 0 ? " selected" : ""}"><input type="radio" name="mode" value="${esc(md.value)}"${i === 0 ? " checked" : ""}>
      <b>${esc(md.label)}</b><span>${esc(md.hint)}</span></label>`).join("");
  $$("#modes input").forEach(r => r.addEventListener("change", () => {
    $$("#modes .mode").forEach(l => l.classList.toggle("selected", l.querySelector("input").checked));
  }));
  fe("launch_date").value = m.default_launch_date;
  fe("launch_date").min = m.snapshot_date;
  sellerSel.addEventListener("change", sellerHint);
  ["expiry_date", "launch_date"].forEach(n => fe(n).addEventListener("input", horizonHint));
  horizonHint();
  sellerHint();

  $("#photos").addEventListener("change", e => addPhotos(e.target.files));
  $("#detect").addEventListener("click", () => detect(true));
  let t = null;
  const auto = () => { clearTimeout(t); t = setTimeout(() => detect(false), 600); };
  fe("title").addEventListener("input", auto);
  fe("description").addEventListener("input", auto);
  $$(".examples .chip").forEach(b => b.addEventListener("click", () => loadExample(Number(b.dataset.example)).catch(showFormError)));
  form.addEventListener("submit", e => { e.preventDefault(); submit(); });
  $$(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#db-select").addEventListener("change", e => openTable(e.target.value));
}

// a sell-by date sets the planning window; say so next to "Plan for"
function horizonHint() {
  const exp = fe("expiry_date").value, launch = fe("launch_date").value || state.meta.default_launch_date;
  const box = $("#horizon-hint"), input = fe("horizon_days");
  const days = exp ? Math.round((Date.parse(exp) - Date.parse(launch)) / 86400000) : null;
  if (days && days > 0) {
    input.disabled = true;
    box.textContent = `Your sell-by date sets this: ${days} days, until ${shortDate(exp)}.`;
    box.hidden = false;
  } else {
    input.disabled = false;
    box.hidden = true;
  }
}

function showFormError(e) {
  const box = $("#form-error");
  box.textContent = (e && e.message) || "Something went wrong.";
  box.hidden = false;
}

function sellerHint() {
  const id = fe("seller_id").value;
  const s = state.meta.sellers.find(x => String(x.seller_id) === id);
  $("#seller-hint").textContent = s
    ? `${s.tier[0].toUpperCase() + s.tier.slice(1)} seller · ${s.city} · ${s.listings} kurti listings on record`
    : "No past listings - the agent will assume average performance.";
}

function switchTab(name) {
  $$(".tab").forEach(b => { const on = b.dataset.tab === name; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); });
  $("#tab-price").hidden = name !== "price";
  $("#tab-listings").hidden = name !== "listings";
  $("#tab-db").hidden = name !== "db";
  if (name === "db" && !state.dbLoaded) loadDb();
  if (name === "listings") loadListings();
}

// ------------------------------------------------------------------ photos
function addPhotos(files) {
  for (const f of Array.from(files || [])) {
    if (!f.type.startsWith("image/") || state.photos.length >= 12) continue;
    state.photos.push(URL.createObjectURL(f));
  }
  renderThumbs();
}
function samplePhotos(n, hue) {
  // simple generated placeholders so examples look real without shipping images
  state.photos = [];
  for (let i = 0; i < n; i++) {
    const h = (hue + i * 23) % 360;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="54"><rect width="44" height="54" fill="#f1f0ec"/>
      <path d="M14 8 L22 13 L30 8 L37 16 L32 19 L32 49 L12 49 L12 19 L7 16 Z" fill="hsl(${h},38%,${46 + i * 4}%)"/>
      <path d="M17 24 H27 M17 30 H27 M17 36 H27" stroke="hsl(${h},30%,${70 + i * 3}%)" stroke-width="1.2"/></svg>`;
    state.photos.push("data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg));
  }
  renderThumbs();
}
function renderThumbs() {
  const n = state.photos.length;
  $("#thumbs").innerHTML = state.photos.map(src => `<img src="${esc(src)}" alt="">`).join("") +
    (n ? `<span class="count">${n} photo${n > 1 ? "s" : ""} · <a href="#" id="clear-photos">Remove</a></span>` : "");
  const c = $("#clear-photos");
  if (c) c.addEventListener("click", e => { e.preventDefault(); state.photos = []; renderThumbs(); });
}

// ------------------------------------------------------------------ attribute detection
async function detect(force) {
  const text = `${fe("title").value} ${fe("description").value}`.trim();
  if (!text) return;
  try {
    const { detected } = await api("/api/detect", { text });
    for (const [k, v] of Object.entries(detected)) {
      if (!fe(k) || (!force && state.touched.has(k))) continue;
      fe(k).value = v;
      fe(k).closest("label").classList.add("detected");
      if (force) state.touched.delete(k);
    }
  } catch (e) { /* detection is a convenience; ignore failures */ }
}

// ------------------------------------------------------------------ examples
const EXAMPLES = [
  { seller_id: "1", title: "Jaipuri Cotton Hand Block Print Kurti",
    description: "Pure cotton kurti, hand block printed in Jaipur. 3/4 sleeve, knee length. Perfect for daily and office wear.",
    cogs: 150, inventory: 200, horizon_days: 30, mode: "balanced", photos: 5, hue: 200 },
  { seller_id: "3", title: "Banarasi Silk Kurta Set with Dupatta",
    description: "Festive silk blend kurta set with zari embroidery and matching dupatta. Full sleeve, calf length. Ideal for Navratri, Diwali and weddings.",
    cogs: 420, offline_price: 1299, offline_margin_pct: 45, inventory: 80, horizon_days: 30, mode: "balanced", photos: 6, hue: 330 },
  { seller_id: "2", title: "Rayon Printed Kurti with Palazzo",
    description: "Rayon printed kurti with palazzo pants, 3/4 sleeve, knee length. Comfortable office wear.",
    cogs: 180, inventory: 120, horizon_days: 30, mode: "clear_inventory", expiry_date: "2026-11-15", limited_stock: true, photos: 3, hue: 40 },
];
async function loadExample(i) {
  const ex = EXAMPLES[i];
  form.reset();
  state.touched.clear();
  $$(".detected").forEach(l => l.classList.remove("detected"));
  fe("launch_date").value = state.meta.default_launch_date;
  for (const [k, v] of Object.entries(ex)) {
    const el = fe(k);
    if (!el || ["mode", "photos", "hue"].includes(k)) continue;
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  }
  $$("#modes input").forEach(r => { r.checked = r.value === ex.mode; });
  $$("#modes .mode").forEach(l => l.classList.toggle("selected", l.querySelector("input").checked));
  sellerHint();
  horizonHint();
  samplePhotos(ex.photos, ex.hue);
  await detect(true);
  submit();
}

// ------------------------------------------------------------------ submit
function collect() {
  const f = new Proxy({}, { get: (_, k) => fe(k) });
  const body = {
    seller_id: f.seller_id.value || null, title: f.title.value, description: f.description.value,
    cogs: f.cogs.value, offline_price: f.offline_price.value, offline_margin_pct: f.offline_margin_pct.value,
    inventory: f.inventory.value, horizon_days: f.horizon_days.value, launch_date: f.launch_date.value,
    expiry_date: f.expiry_date.value, limited_stock: f.limited_stock.checked, package_size: f.package_size.value,
    mode: (form.querySelector("input[name=mode]:checked") || {}).value || "balanced", n_photos: state.photos.length,
    colors: f.colors.value,
  };
  // detected (not hand-picked) attributes are sent as "auto" so the server re-derives and labels them
  for (const a of ATTRS) body[a] = fe(a).closest("label").classList.contains("detected") ? "auto" : fe(a).value;
  return body;
}
function clientCheck(b) {
  $$("input.invalid").forEach(i => i.classList.remove("invalid"));
  const bad = (name, msg) => { fe(name).classList.add("invalid"); fe(name).focus(); return msg; };
  const hasOffline = b.offline_price !== "" && b.offline_margin_pct !== "";
  if (b.cogs === "" && !hasOffline) return bad("cogs", "Enter your cost per piece (or your offline price and margin).");
  if (b.cogs !== "" && !(Number(b.cogs) > 0)) return bad("cogs", "Cost per piece must be more than ₹0.");
  if (b.inventory === "" || !(Number(b.inventory) >= 1)) return bad("inventory", "Enter how many units you have (at least 1).");
  if (b.horizon_days !== "" && (Number(b.horizon_days) < 7 || Number(b.horizon_days) > 180)) return bad("horizon_days", "Plan for 7 to 180 days.");
  if (b.offline_margin_pct !== "" && (Number(b.offline_margin_pct) < 0 || Number(b.offline_margin_pct) > 95)) return bad("offline_margin_pct", "Offline margin must be between 0 and 95%.");
  if (b.expiry_date && b.launch_date && b.expiry_date <= b.launch_date) return bad("expiry_date", "Sell-by date must be after the launch date.");
  return null;
}
async function submit() {
  if (state.busy) return;
  let body;
  try { body = collect(); } catch (e) { showFormError(e); return; }
  const errBox = $("#form-error");
  const err = clientCheck(body);
  if (err) { errBox.textContent = err; errBox.hidden = false; return; }
  errBox.hidden = true;
  const btn = $("#submit");
  state.busy = true;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Scanning the market…`;
  try {
    const result = await api("/api/recommend", body);
    state.result = result;
    state.lastBody = body;
    state.listed = null;
    render();
    narratePricing(result);
    if (window.innerWidth <= 960) $("#results").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    errBox.textContent = e.message;
    errBox.hidden = false;
  } finally {
    state.busy = false;
    btn.disabled = false;
    btn.textContent = "Get my price";
  }
}

// ------------------------------------------------------------------ render results
function render() {
  const r = state.result;
  if (!r) return;
  const rec = r.recommendation, ex = r.explanation;
  $("#empty").hidden = true;
  const out = $("#output");
  out.hidden = false;
  const steady = rec.steady_price && rec.steady_price !== rec.entry_price;
  const L = state.lang === "hi";
  const T = (en, hi) => (L ? hi : en);
  const stats = [
    [rec.orders_per_day >= 1 ? num(rec.orders_per_day, 1) : num(rec.orders_per_day, 2), T("orders a day", "ऑर्डर / दिन")],
    [inr(rec.profit_per_order), T("profit per order", "मुनाफ़ा / ऑर्डर")],
    [`${num(rec.margin_pct, 1)}%`, T("margin", "मार्जिन")],
    [inr(rec.total_profit), windowText(rec, L).stat],
    [rec.days_to_sell_out === null ? "–" : `${num(rec.days_to_sell_out, 0)} ${T("days", "दिन")}`,
      T(`to sell ${rec.inventory} pieces`, `${rec.inventory} पीस बिकने में`)],
  ];
  const notes = [
    ...ex.warnings.map(w => ["warn", T("Check", "ध्यान दें"), tr(w)]),
  ];
  const tips = ex.tips.map(t => ["tip", T("Tip", "सुझाव"), tr(t)]);

  out.innerHTML = `
  <div class="panel">
    <div class="result-top">
      <p class="eyebrow" style="margin:0">${T("Recommendation", "सुझाव")} · ${esc(rec.mode_label)}</p>
      <div class="lang" role="group" aria-label="Language">
        <button data-lang="en" class="${state.lang === "en" ? "active" : ""}">English</button>
        <button data-lang="hi" class="${state.lang === "hi" ? "active" : ""}">हिंदी</button>
      </div>
    </div>
    <div class="result-head">
      <div class="price-block">
        <div class="big">${inr(rec.entry_price)}</div>
        ${rec.suggested_mrp > rec.entry_price ? `<div class="mrp"><s>MRP ${inr(rec.suggested_mrp)}</s><span class="off">${rec.discount_shown_pct}% off</span></div>` : ""}
        <div class="goal-note">${T("Launch price", "शुरुआती कीमत")}</div>
      </div>
      <div>
        <div class="headline">${esc(tr(ex.headline))}</div>
        <p class="summary">${esc(tr(ex.summary))}</p>
        <div class="plan-line">
          <div class="plan-pt on"><div class="k">${T("Launch", "लॉन्च")}</div><div class="v">${inr(rec.entry_price)}</div></div>
          <div class="plan-pt${steady ? "" : " off-pt"}"><div class="k">${T("After 20–25 reviews", "20–25 रिव्यू के बाद")}</div><div class="v">${steady ? inr(rec.steady_price) : T("Hold", "यही रखें")}</div></div>
          <div class="plan-pt floor"><div class="k">${T("Never go below", "इससे कम नहीं")}</div><div class="v">${inr(rec.break_even_price)}</div></div>
        </div>
        <div class="list-row">
          ${state.listed
            ? `<button class="btn-primary done" disabled>${T("Listed", "लिस्ट हो गया")}</button>
               <span class="list-msg">${esc(state.listed.msg)} <a href="#" id="go-listings">${T("Open My listings", "मेरी लिस्टिंग खोलें")}</a></span>`
            : `<button class="btn-primary" id="list-btn">${T(`List at ${inr(rec.entry_price)}`, `₹${rec.entry_price} पर लिस्ट करें`)}</button>
               <span class="list-msg" id="list-msg">${T("Creates one listing per colour in My listings.", "“मेरी लिस्टिंग” में हर रंग की एक लिस्टिंग बनेगी।")}</span>`}
        </div>
      </div>
    </div>
    <div class="stat-strip">${stats.map(([v, k]) => `<div class="stat"><div class="stat-v">${esc(v)}</div><div class="stat-k">${esc(k)}</div></div>`).join("")}</div>
  </div>

  ${notes.length ? `<div class="panel alert"><div class="notes">${notes.map(noteRow).join("")}</div></div>` : ""}

  <div class="panel">
    <div class="panel-head"><h2>${T("Why this price", "यह कीमत क्यों")}</h2>${aiBadge(r)}</div>
    <div class="ledger">${ex.reasons.map(rs => `
      <div class="ledger-row">
        <div class="ledger-label">${esc(tr(rs.title))}</div>
        <div class="ledger-text">${esc(tr(rs.text))}</div>
        <div class="ledger-effect ${esc(rs.tone)}">${esc(rs.effect)}</div>
      </div>`).join("")}
    </div>
  </div>

  <div class="row2">
    <div class="panel chart">
      <div class="panel-head"><div><h2>${T("Where your price sits", "बाज़ार में आपकी कीमत")}</h2>
        <div class="panel-sub">${T(`Prices of ${r.market.n_comparable} comparable live listings`, `${r.market.n_comparable} मिलती-जुलती लिस्टिंग की कीमतें`)}</div></div></div>
      <div id="chart-dist"></div>
      <div class="legend">
        <span><i style="background:var(--series-1)"></i>${T("Listings", "लिस्टिंग")}</span>
        <span><i style="background:var(--accent)"></i>${T("Your price", "आपकी कीमत")}</span>
        <span><i style="background:var(--bad)"></i>${T("Break-even", "न्यूनतम कीमत")}</span>
        ${r.offline ? `<span><i style="background:var(--text-2)"></i>${T("Shop price", "दुकान की कीमत")}</span>` : ""}
      </div>
    </div>
    <div class="panel chart">
      <div class="panel-head"><div><h2>${T("Profit at every price", "हर कीमत पर मुनाफ़ा")}</h2>
        <div class="panel-sub">${windowText(rec, L).chart}${rec.stock_limited ? T(`, ${rec.inventory} pieces`, `, ${rec.inventory} पीस`) : ""}. ${T("Hover the line.", "")}</div></div></div>
      <div id="chart-curve"></div>
      <div class="legend">
        <span><i style="background:var(--series-1)"></i>${T("Total profit", "कुल मुनाफ़ा")}</span>
        <span><i class="dot" style="background:var(--accent)"></i>${T("Price for each goal", "हर लक्ष्य की कीमत")}</span>
      </div>
    </div>
  </div>

  <div class="row2">
    <div class="panel">
      <div class="panel-head"><div><h2>${T("Compare goals", "लक्ष्यों की तुलना")}</h2>
        <div class="panel-sub">${windowText(rec, L).table}</div></div></div>
      <div class="table-wrap"><table>
        <thead><tr><th>${T("Goal", "लक्ष्य")}</th><th class="num">${T("Price", "कीमत")}</th><th class="num">${T("Orders/day", "ऑर्डर/दिन")}</th><th class="num">${T("Per order", "प्रति ऑर्डर")}</th><th class="num">${T("Profit", "मुनाफ़ा")}</th></tr></thead>
        <tbody>${Object.entries(r.modes).map(([k, m]) => `
          <tr class="${k === rec.mode ? "chosen" : ""}"><td>${esc(m.label)}</td><td class="num">${inr(m.price)}</td>
          <td class="num">${num(m.orders_per_day, 1)}</td><td class="num ${m.profit_per_order < 0 ? "neg" : ""}">${inr(m.profit_per_order)}</td>
          <td class="num ${m.total_profit < 0 ? "neg" : ""}">${inr(m.total_profit)}</td></tr>`).join("")}
        </tbody></table></div>
    </div>
    <div class="panel">
      <div class="panel-head"><div><h2>${T("Where the money goes", "पैसा कहाँ जाता है")}</h2>
        <div class="panel-sub">${T(`Per order at ${inr(rec.entry_price)}, averaged over returns`, `₹${rec.entry_price} पर प्रति ऑर्डर`)}</div></div></div>
      <table><tbody>${r.economics.breakdown.map(l => `
        <tr class="${l.total ? "total" : ""}"><td>${esc(l.label)}</td><td class="num ${l.amount < 0 ? "neg" : (l.total ? "pos" : "")}">${inr(l.amount, 1)}</td></tr>`).join("")}
      </tbody></table>
      <p class="muted small" style="margin:12px 0 0">${r.economics.kept_share_pct}% of orders are kept by buyers. Shipping and packaging rates are assumptions.</p>
    </div>
  </div>

  ${tips.length ? `<div class="panel"><div class="panel-head"><h2>${T("To sell more", "बेहतर बिक्री के लिए")}</h2></div><div class="notes">${tips.map(noteRow).join("")}</div></div>` : ""}

  <div class="panel">
    <div class="panel-head"><h2>${T("Closest competing listings", "सबसे करीबी प्रतिस्पर्धी")}</h2></div>
    <div class="table-wrap"><table>
      <thead><tr><th>${T("Listing", "लिस्टिंग")}</th><th>${T("Seller", "विक्रेता")}</th><th class="num">${T("Price", "कीमत")}</th><th class="num">${T("Rating", "रेटिंग")}</th><th class="num">${T("Orders/mo", "ऑर्डर/माह")}</th><th class="num">${T("Returns", "रिटर्न")}</th><th class="num">${T("Match", "मेल")}</th></tr></thead>
      <tbody>${r.market.top_competitors.map(c => `
        <tr><td>${esc(c.title)}</td><td>${esc(c.seller)}${c.is_demo_seller ? `<span class="tag">demo</span>` : ""}<div class="sub-line">${esc(c.city)}</div></td>
        <td class="num">${inr(c.price)}<div class="sub-line"><s>${inr(c.mrp)}</s></div></td>
        <td class="num">${c.rating ? "★ " + Number(c.rating).toFixed(1) : "–"}<div class="sub-line">${num(c.reviews, 0)}</div></td>
        <td class="num">${num(c.est_monthly_orders, 0)}</td><td class="num">${c.return_rate_pct === null ? "–" : c.return_rate_pct + "%"}</td>
        <td class="num">${c.similarity_pct}%</td></tr>`).join("")}
      </tbody></table></div>
  </div>

  <div class="panel">
    <details>
      <summary>${T("How the agent worked it out", "एजेंट ने यह कैसे निकाला")}</summary>
      <div class="row2 model-cols">${modelDetails(r)}</div>
    </details>
  </div>`;

  $$(".lang button", out).forEach(b => b.addEventListener("click", () => { state.lang = b.dataset.lang; render(); }));
  const lb = $("#list-btn", out);
  if (lb) lb.addEventListener("click", listProduct);
  const gl = $("#go-listings", out);
  if (gl) gl.addEventListener("click", e => { e.preventDefault(); state.lSeller = String(state.listed.seller_id); switchTab("listings"); window.scrollTo(0, 0); });
  drawDistribution($("#chart-dist"), r);
  drawCurve($("#chart-curve"), r);
}

// ------------------------------------------------------------------ AI explanations (template text is the fallback)
function aiBadge(r) {
  const st = state.ai[r.recommendation_id];
  if (!state.meta.llm || !state.meta.llm.enabled || !st) return "";
  if (st === "loading") return `<span class="ai-badge"><span class="spinner"></span>Writing a clearer explanation…</span>`;
  if (st === "ai") return `<span class="ai-badge on" title="Rewritten by an AI model. Every number was checked against the pricing engine.">AI-written · numbers checked</span>`;
  return `<span class="ai-badge" title="The AI explanation was unavailable, so the standard explanation is shown.">Standard explanation</span>`;
}

async function narratePricing(result) {
  const id = result.recommendation_id;
  if (!state.meta.llm || !state.meta.llm.enabled || !id || state.ai[id]) return;
  state.ai[id] = "loading";
  if (state.result === result) render();
  let out = { source: "template" };
  try { out = await api("/api/narrate/pricing", { recommendation_id: id }); } catch (e) { /* keep template */ }
  if (out.source === "ai") {
    const ex = result.explanation;
    ex.headline = out.headline;
    ex.summary = out.summary;
    ex.reasons.forEach((r, i) => { r.text = out.reasons[i]; });
    ex.tips = out.tips;
  }
  state.ai[id] = out.source === "ai" ? "ai" : "template";
  if (state.result === result) render();
}

function shortDate(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]}`;
}

// how the planning window is named everywhere: a sell-by date replaces "plan for N days"
function windowText(rec, L) {
  const n = rec.horizon_days;
  if (rec.sell_by) {
    const d = shortDate(rec.sell_by);
    return { stat: L ? `${d} तक मुनाफ़ा` : `profit by ${d}`,
             chart: L ? `sell-by date (${d}, ${n} दिन) तक` : `Until your sell-by date, ${d} (${n} days)`,
             table: L ? `मुनाफ़ा sell-by date (${d}, ${n} दिन) तक का है` : `Profit until your sell-by date, ${d} (${n} days)`,
             tip: `Profit by ${d}` };
  }
  return { stat: L ? `${n} दिन का मुनाफ़ा` : `profit in ${n} days`, chart: L ? `अगले ${n} दिन` : `Next ${n} days`,
           table: L ? `मुनाफ़ा अगले ${n} दिनों का है` : `Profit is for the next ${n} days`, tip: `Profit in ${n} days` };
}

function noteRow([kind, label, text]) {
  return `<div class="note-row"><div class="note-kind ${kind}">${esc(label)}</div><div>${esc(text)}</div></div>`;
}

function modelDetails(r) {
  const d = r.demand_model, p = r.package, a = r.attributes, s = r.seller;
  const fest = d.festivals.length ? d.festivals.map(f => `${esc(f.name)} (${f.days_away}d, +${f.peak_uplift_pct}%)`).join(", ") : "none";
  const src = k => a[k].source === "detected" ? ` <span class="tag">auto</span>` : "";
  const kv = rows => `<div class="kv">${rows.map(([k, v]) => `<div>${k}</div><div>${v}</div>`).join("")}</div>`;
  return `
  <div>
    <h3>Product</h3>
    ${kv([
      ["Type", esc(a.product_type.label) + src("product_type")], ["Fabric", esc(a.fabric.label) + src("fabric")],
      ["Work / pattern", esc(a.pattern.label) + src("pattern")], ["Occasion", esc(a.occasion.label) + src("occasion")],
      ["Weight, packed", `${p.product_weight_g} g (${p.packed_weight_g} g)`],
      ["Package", `${esc(p.package_size)} · ${esc(p.package_desc)}`], ["Shipping slab", `${esc(p.shipping_slab)} → ${inr(p.shipping_forward)}`],
      ["Photos effect on clicks", `×${d.photo_factor}`],
    ])}
    <h3>Market</h3>
    ${kv([
      ["Fair price for these attributes", inr(r.market.fair_price)], ["Price model fit (R²)", d.hedonic_r2],
      ["Comparable listings", r.market.n_comparable], ["Near-identical competitors", r.market.n_direct_competitors],
      ["Crowding (1 = category average)", r.market.crowding_index], ["Average rating of comparables", r.market.avg_rating ? "★ " + r.market.avg_rating : "–"],
      ["Returns / RTO", `${r.economics.return_rate_pct}% / ${r.economics.rto_rate_pct}%`],
    ])}
  </div>
  <div>
    <h3>Demand model</h3>
    ${kv([
      ["Price sensitivity (learnt)", `${d.price_sensitivity}`],
      ["Learnt from", `${d.listings_with_price_changes} listings that changed price`],
      ["At launch (new, season, crowding)", d.price_sensitivity_effective],
      ["Typical listing, orders/day", num(d.typical_orders_per_day, 2)],
      ["New-listing demand", `×${d.new_listing_factor}`],
      ["Season · festival index", `${d.season_index} · ${d.festival_index}`],
      ["Demand vs last 4 months", `×${num(d.window_multiplier / d.history_multiplier, 2)}`],
      ["Festivals in window", fest],
      ["Your click-through", s && s.ctr_pct ? `×${s.ctr_factor} (${s.ctr_pct}% vs ${s.category_ctr_pct}%)` : "×1 (no history)"],
    ])}
    <p class="muted small" style="margin-top:12px">Price sensitivity is how fast orders fall as price rises: at 3.5, a price 10% above the
      fair price loses about 30% of orders. It is learnt by comparing each listing's sales before and after its own price changes.</p>
  </div>`;
}

// ------------------------------------------------------------------ charts
const tip = $("#tooltip");
function showTip(e, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTip() { tip.hidden = true; }
function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}
function short(v) {
  const a = Math.abs(v);
  if (a >= 100000) return (v / 100000).toFixed(1).replace(/\.0$/, "") + "L";
  if (a >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return String(Math.round(v));
}

function drawDistribution(el, r) {
  const bins = r.price_distribution.bins;
  if (!bins.length) { el.innerHTML = `<p class="muted">Not enough listings to chart.</p>`; return; }
  const W = 480, H = 240, m = { l: 30, r: 10, t: 44, b: 26 };
  const xs = [bins[0].from, bins[bins.length - 1].to];
  const be = r.recommendation.break_even_price, rec = r.recommendation.entry_price;
  const off = r.offline ? r.offline.offline_price : null;
  const lo = Math.min(xs[0], be, off || Infinity), hi = Math.max(xs[1], be + 10, off ? off + 10 : 0);
  const x = v => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
  const maxC = Math.max(...bins.map(b => b.count), 1);
  const y = v => H - m.b - v / maxC * (H - m.t - m.b);
  const yt = niceTicks(0, maxC, 4).filter(v => Number.isInteger(v));
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Histogram of competitor prices">`;
  yt.forEach(v => { s += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`; });
  const p25 = r.market.price_p25, p75 = r.market.price_p75;
  s += `<rect x="${x(p25)}" y="${m.t}" width="${Math.max(0, x(p75) - x(p25))}" height="${H - m.t - m.b}" fill="var(--series-1-soft)" opacity=".35"/>`;
  s += `<text x="${(x(p25) + x(p75)) / 2}" y="${m.t + 12}" text-anchor="middle">middle 50%</text>`;
  bins.forEach(b => {
    const bw = Math.max(2, x(b.to) - x(b.from) - 2), bx = x(b.from) + 1, top = y(b.count), h = H - m.b - top;
    if (b.count > 0) {
      const r4 = Math.min(4, bw / 2, h);
      s += `<path d="M${bx},${H - m.b} V${top + r4} Q${bx},${top} ${bx + r4},${top} H${bx + bw - r4} Q${bx + bw},${top} ${bx + bw},${top + r4} V${H - m.b} Z" fill="var(--series-1)"/>`;
    }
    s += `<rect class="hit" data-tip="${esc(`<b>${inr(b.from)}–${inr(b.to - 1)}</b>${b.count} listing${b.count === 1 ? "" : "s"}`)}" x="${x(b.from)}" y="${m.t}" width="${Math.max(1, x(b.to) - x(b.from))}" height="${H - m.t - m.b}" fill="transparent"/>`;
  });
  s += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
  niceTicks(lo, hi, 6).filter(v => x(v) > m.l + 10 && x(v) < W - 16).forEach(v => { s += `<text x="${x(v)}" y="${H - m.b + 16}" text-anchor="middle">₹${short(v)}</text>`; });
  // marker labels sit in the top margin on their own rows so they never collide
  const marker = (v, color, label, row) => {
    const right = x(v) > W * 0.6;
    const ly = 12 + row * 14;
    s += `<line x1="${x(v)}" x2="${x(v)}" y1="${ly + 3}" y2="${H - m.b}" stroke="${color}" stroke-width="2"/>`;
    s += `<text x="${x(v) + (right ? -5 : 5)}" y="${ly}" text-anchor="${right ? "end" : "start"}" style="fill:${color};font-weight:700">${label}</text>`;
  };
  marker(rec, "var(--accent)", `Your price ${inr(rec)}`, 0);
  marker(be, "var(--bad)", `Break-even ${inr(be)}`, 1);
  if (off) marker(off, "var(--text-2)", `Shop ${inr(off)}`, 2);
  s += `</svg>`;
  el.innerHTML = s;
  $$(".hit", el).forEach(h => {
    h.addEventListener("mousemove", e => showTip(e, h.dataset.tip));
    h.addEventListener("mouseleave", hideTip);
  });
}

function drawCurve(el, r) {
  const rec = r.recommendation;
  const lo = Math.max(r.curve[0].price, Math.min(rec.break_even_price * 0.97, rec.entry_price * 0.9), r.market.price_p10 * 0.7);
  const hiRaw = Math.max(r.market.price_p90 * 1.35, ...Object.values(r.modes).map(md => md.price * 1.15));
  let pts = r.curve.filter(c => c.price >= lo && c.price <= hiRaw);
  if (pts.length < 3) pts = r.curve;
  const W = 480, H = 240, m = { l: 44, r: 12, t: 24, b: 26 };
  const xmin = pts[0].price, xmax = pts[pts.length - 1].price;
  const vals = pts.map(p => p.total_profit);
  const ymin = Math.min(0, ...vals), ymax = Math.max(1, ...vals);
  const pad = (ymax - ymin) * 0.08;
  const Y0 = ymin < 0 ? ymin - pad : 0, Y1 = ymax + pad;
  const x = v => m.l + (v - xmin) / (xmax - xmin || 1) * (W - m.l - m.r);
  const y = v => H - m.b - (v - Y0) / (Y1 - Y0 || 1) * (H - m.t - m.b);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Total profit versus price">`;
  niceTicks(Y0, Y1, 4).forEach(v => { s += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${v < 0 ? "−" : ""}₹${short(Math.abs(v))}</text>`; });
  if (Y0 < 0) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--muted)" stroke-width="1"/>`;
  niceTicks(xmin, xmax, 6).filter(v => x(v) > m.l + 10 && x(v) < W - 16).forEach(v => { s += `<text x="${x(v)}" y="${H - m.b + 16}" text-anchor="middle">₹${short(v)}</text>`; });
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.total_profit).toFixed(1)}`).join(" ");
  const base = y(Math.max(Y0, 0));
  s += `<path d="${line} L${x(xmax)},${base} L${x(xmin)},${base} Z" fill="var(--series-1)" opacity=".1"/>`;
  s += `<path d="${line}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  // mode markers (label only the chosen one directly; the rest via hover)
  const modeAt = {};
  Object.entries(r.modes).forEach(([k, md]) => { (modeAt[md.price] = modeAt[md.price] || []).push(md.label); });
  Object.entries(modeAt).forEach(([price, labels]) => {
    const p = r.curve.find(c => c.price === Number(price));
    if (!p || p.price < xmin || p.price > xmax) return;
    const chosen = Number(price) === rec.entry_price;
    s += `<circle cx="${x(p.price)}" cy="${y(p.total_profit)}" r="${chosen ? 6 : 4.5}" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`;
    if (chosen) {
      const right = x(p.price) > W * 0.7;
      s += `<text x="${x(p.price) + (right ? -9 : 9)}" y="${y(p.total_profit) - 8}" text-anchor="${right ? "end" : "start"}" style="fill:var(--accent);font-weight:700">${esc(labels.join(" / "))} · ${inr(p.price)}</text>`;
    }
  });
  s += `<line id="xh" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)" stroke-width="1" visibility="hidden"/>`;
  s += `<circle id="xd" r="4" fill="var(--series-1)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`;
  s += `<rect id="hover" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  s += `</svg>`;
  el.innerHTML = s;
  const svg = $("svg", el), xh = $("#xh", el), xd = $("#xd", el), hov = $("#hover", el);
  hov.addEventListener("mousemove", e => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM().inverse());
    const price = xmin + (loc.x - m.l) / (W - m.l - m.r) * (xmax - xmin);
    let best = pts[0];
    for (const p of pts) if (Math.abs(p.price - price) < Math.abs(best.price - price)) best = p;
    xh.setAttribute("x1", x(best.price)); xh.setAttribute("x2", x(best.price)); xh.setAttribute("visibility", "visible");
    xd.setAttribute("cx", x(best.price)); xd.setAttribute("cy", y(best.total_profit)); xd.setAttribute("visibility", "visible");
    const goals = modeAt[best.price] ? `<div style="color:var(--accent);font-weight:600">${esc(modeAt[best.price].join(" / "))}</div>` : "";
    showTip(e, `<b>At ${inr(best.price)}</b>${goals}Orders/day: ${num(best.orders_per_day, 2)}<br>Profit/order: ${inr(best.profit_per_order, 1)}<br>${windowText(rec, false).tip}: ${inr(best.total_profit)}`);
  });
  hov.addEventListener("mouseleave", () => { hideTip(); xh.setAttribute("visibility", "hidden"); xd.setAttribute("visibility", "hidden"); });
}

// ------------------------------------------------------------------ database tab
const TABLE_INFO = {
  categories: ["Catalogue", "Category tree (Women Ethnic → Kurtis & Kurta Sets → leaf types) with GST and return-rate priors."],
  sellers: ["Sellers", "Supplier accounts: location, tier and rating. Three demo sellers drive the UI."],
  catalogs: ["Catalogue", "Meesho groups similar products uploaded together into a catalog."],
  products: ["Catalogue", "Every live listing with its attributes, photos, weight, package size, MRP and current price."],
  inventory: ["Catalogue", "Units available per product."],
  price_history: ["Catalogue", "Every price change a seller made - the key to learning price sensitivity."],
  daily_product_metrics: ["Performance", "Daily funnel per product: impressions → clicks → orders → returns / RTO, with the price that day."],
  reviews: ["Performance", "Buyer ratings and tagged review themes (size issue, thin fabric…)."],
  shipping_rate_card: ["Reference", "Forward and reverse shipping by packed-weight slab (assumed)."],
  packaging_rate_card: ["Reference", "Packaging cost and added weight by package size."],
  festival_calendar: ["Reference", "Festivals and sale events with demand uplift and lead time."],
  fabric_seasonality: ["Reference", "Monthly demand index by fabric (cotton peaks in summer, silk at festivals)."],
  pricing_recommendations: ["Agent output", "Every recommendation the agent made - input, price and reasoning - for learning and audit."],
};
const DB_GROUPS = ["Catalogue", "Sellers", "Performance", "Reference", "Agent output"];

async function loadDb() {
  const box = $("#db-main");
  if (!state.db.schema) {
    box.innerHTML = `<div class="panel muted"><span class="spinner"></span>Loading…</div>`;
    try {
      state.db.schema = (await api("/api/db/schema")).tables;
    } catch (e) {
      box.innerHTML = `<div class="panel error">${esc(e.message)}</div>`;
      return;
    }
  }
  state.dbLoaded = true;
  renderDbNav();
  if (!state.db.table) state.db.table = "products";
  await loadDbTable();
}

function renderDbNav() {
  const tables = state.db.schema;
  const groups = {};
  tables.forEach(t => { const g = (TABLE_INFO[t.table] || ["Other"])[0]; (groups[g] = groups[g] || []).push(t); });
  const order = [...DB_GROUPS.filter(g => groups[g]), ...Object.keys(groups).filter(g => !DB_GROUPS.includes(g))];
  $("#db-nav").innerHTML = order.map(g => `<div class="db-nav-group"><div class="db-nav-title">${esc(g)}</div>
    ${groups[g].map(t => `<button class="db-nav-item${state.db.table === t.table ? " active" : ""}" data-t="${esc(t.table)}">
      <span>${esc(t.table)}</span><span class="n">${num(t.rows, 0)}</span></button>`).join("")}</div>`).join("");
  $("#db-select").innerHTML = order.map(g => `<optgroup label="${esc(g)}">${groups[g].map(t =>
    `<option value="${esc(t.table)}"${state.db.table === t.table ? " selected" : ""}>${esc(t.table)} (${num(t.rows, 0)})</option>`).join("")}</optgroup>`).join("");
  $$("#db-nav .db-nav-item").forEach(b => b.addEventListener("click", () => openTable(b.dataset.t)));
}

function openTable(name, filterCol = "", filterVal = "") {
  Object.assign(state.db, { table: name, page: 1, q: "", sort: "", dir: "asc", filterCol, filterVal });
  renderDbNav();
  loadDbTable();
  if (window.innerWidth < 900) $("#db-main").scrollIntoView({ behavior: "smooth" });
}

async function loadDbTable() {
  const d = state.db;
  const params = new URLSearchParams({ name: d.table, page: d.page, size: d.size, q: d.q, sort: d.sort, dir: d.dir,
    filter_col: d.filterCol, filter_val: d.filterVal });
  const box = $("#db-data");
  if (box) box.classList.add("loading");
  let res;
  try {
    res = await api(`/api/db/table?${params}`);
  } catch (e) {
    $("#db-main").innerHTML = `<div class="panel error">${esc(e.message)}</div>`;
    return;
  }
  d.page = res.page;
  renderDbTable(res, params);
}

function renderDbTable(res, params) {
  const d = state.db;
  const meta = state.db.schema.find(t => t.table === res.table) || { referenced_by: [], rows: res.total };
  const cols = res.columns;
  const csvParams = new URLSearchParams(params);
  csvParams.delete("page"); csvParams.delete("size");
  const sortMark = c => d.sort === c ? (d.dir === "asc" ? " ▲" : " ▼") : "";
  const cell = (v, c) => {
    if (v === null || v === undefined) return `<span class="null">NULL</span>`;
    if (c.fk) return `<button class="cell-link" data-t="${esc(c.fk.table)}" data-c="${esc(c.fk.column)}" data-v="${esc(v)}" title="Open ${esc(c.fk.table)} row">${esc(v)}</button>`;
    return esc(v);
  };
  const first = (res.page - 1) * res.size + 1, last = Math.min(res.total, res.page * res.size);
  $("#db-main").innerHTML = `
    <div class="panel">
      <div class="panel-head"><div>
        <h2 class="mono">${esc(res.table)}</h2>
        <div class="panel-sub">${esc((TABLE_INFO[res.table] || ["", ""])[1])}</div>
      </div><div class="muted small">${num(meta.rows, 0)} rows · ${cols.length} columns</div></div>
      <details class="structure">
        <summary>Structure</summary>
        <div class="table-wrap"><table class="schema">
          <thead><tr><th>Column</th><th>Type</th><th>Key</th><th>Links to</th></tr></thead>
          <tbody>${cols.map(c => `<tr><td class="mono">${esc(c.name)}</td><td class="muted mono">${esc(c.type)}</td>
            <td>${c.pk ? "Primary key" : (c.fk ? "Foreign key" : "")}</td>
            <td>${c.fk ? `<button class="btn-link table-link" data-t="${esc(c.fk.table)}">${esc(c.fk.table)}.${esc(c.fk.column)}</button>` : ""}</td></tr>`).join("")}
          </tbody></table></div>
        ${meta.referenced_by.length ? `<p class="small muted" style="margin:10px 0 0">Used by: ${meta.referenced_by.map(t =>
          `<button class="btn-link table-link" data-t="${esc(t)}">${esc(t)}</button>`).join(", ")}</p>` : ""}
      </details>
    </div>

    <div class="panel data-panel">
      <div class="data-tools">
        <input type="search" id="db-q" placeholder="Search this table" value="${esc(d.q)}" aria-label="Search this table">
        <label class="inline">Rows <select id="db-size">${[25, 50, 100].map(n => `<option${n === d.size ? " selected" : ""}>${n}</option>`).join("")}</select></label>
        <a class="btn-secondary" href="/api/db/export.csv?${csvParams}" download="${esc(res.table)}.csv">${res.total > 20000 ? "Download CSV (first 20,000 rows)" : "Download CSV"}</a>
      </div>
      ${d.filterCol ? `<div class="filter-chip">Showing rows where <b class="mono">${esc(d.filterCol)} = ${esc(d.filterVal)}</b>
        <button class="btn-link" id="db-clear-filter">Show all rows</button></div>` : ""}
      <div class="table-wrap" id="db-data"><table class="data">
        <thead><tr>${cols.map(c => `<th><button class="sort" data-c="${esc(c.name)}">${esc(c.name)}${sortMark(c.name)}</button></th>`).join("")}</tr></thead>
        <tbody>${res.rows.length ? res.rows.map(r => `<tr>${r.map((v, i) => `<td>${cell(v, cols[i])}</td>`).join("")}</tr>`).join("")
          : `<tr><td colspan="${cols.length}" class="muted">No rows match.</td></tr>`}</tbody>
      </table></div>
      <div class="pager">
        <span class="muted small">${res.total ? `${num(first, 0)}–${num(last, 0)} of ${num(res.total, 0)}` : "0 rows"}</span>
        <div class="pager-btns">
          <button class="btn-secondary" id="db-prev"${res.page <= 1 ? " disabled" : ""}>Previous</button>
          <span class="small">Page ${res.page} of ${res.pages}</span>
          <button class="btn-secondary" id="db-next"${res.page >= res.pages ? " disabled" : ""}>Next</button>
        </div>
      </div>
    </div>`;

  let t = null;
  $("#db-q").addEventListener("input", e => {
    clearTimeout(t);
    t = setTimeout(() => { d.q = e.target.value.trim(); d.page = 1; loadDbTable().then(() => { const q = $("#db-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 350);
  });
  $("#db-size").addEventListener("change", e => { d.size = Number(e.target.value); d.page = 1; loadDbTable(); });
  $("#db-prev").addEventListener("click", () => { d.page -= 1; loadDbTable(); });
  $("#db-next").addEventListener("click", () => { d.page += 1; loadDbTable(); });
  const clear = $("#db-clear-filter");
  if (clear) clear.addEventListener("click", () => { d.filterCol = ""; d.filterVal = ""; d.page = 1; loadDbTable(); });
  $$("#db-main .sort").forEach(b => b.addEventListener("click", () => {
    const c = b.dataset.c;
    d.dir = d.sort === c && d.dir === "asc" ? "desc" : "asc";
    d.sort = c; d.page = 1;
    loadDbTable();
  }));
  $$("#db-main .table-link").forEach(b => b.addEventListener("click", () => openTable(b.dataset.t)));
  $$("#db-main .cell-link").forEach(b => b.addEventListener("click", () => openTable(b.dataset.t, b.dataset.c, b.dataset.v)));
}

// ------------------------------------------------------------------ list a product (pricing page)
async function listProduct() {
  const r = state.result, body = state.lastBody;
  const msg = $("#list-msg"), btn = $("#list-btn");
  if (!r || !body) return;
  if (!body.seller_id) {
    msg.innerHTML = `<span class="bad-t">Pick a seller account (section 1) and get the price again to list it.</span>`;
    return;
  }
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Listing…`;
  try {
    const out = await api("/api/list", { ...body, colors: fe("colors").value, price: r.recommendation.entry_price, mrp: r.recommendation.suggested_mrp,
      recommendation_id: r.recommendation_id });
    const n = out.product_ids.length;
    state.listed = { seller_id: out.seller_id,
      msg: `${n} listing${n > 1 ? "s" : ""} (${out.colors.join(", ")}) added for ${out.seller_name} at ${inr(out.price)}.` };
    try { state.meta = await api("/api/meta"); sellerHint(); } catch (e) { /* hint refresh is cosmetic */ }
    render();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = `List at ${inr(r.recommendation.entry_price)}`;
    msg.innerHTML = `<span class="bad-t">${esc(e.message)}</span>`;
  }
}

// ------------------------------------------------------------------ my listings tab
const SWATCH = { indigo: "#3f4a9a", maroon: "#7a1f2b", mustard: "#d4a017", white: "#ffffff", "off white": "#f3efe4",
  yellow: "#f2d33b", "sky blue": "#8cc8ec", peach: "#f6b99a", red: "#d33a3a", green: "#3f8f4f", grey: "#9a9aa0",
  gray: "#9a9aa0", black: "#222", wine: "#6e1f3a", teal: "#1f8a8a", pink: "#f07aa8", "navy blue": "#23305e",
  lavender: "#b9a6e0", rust: "#b7472a", olive: "#6b7a2f", cream: "#f4ead2", purple: "#6b3fa0", gold: "#c9a227", orange: "#f08a2c", magenta: "#c0288c", blue: "#3a6fd8", beige: "#e3d3b5", brown: "#7a5230" };
const REASON_LABEL = { market: "Market", funnel: "Conversion", eye: "Clicks", stock: "Stock", variant: "Colours",
  festival: "Festivals", season: "Season", old: "Ageing stock", bundle: "Clearance", star: "Reviews", rival: "Rival",
  new: "New listing", plan: "Plan", wait: "Timing", cost: "Margin" };
const FILTERS = [["all", "All"], ["up", "Raise"], ["down", "Lower or clear"], ["hold", "Hold"], ["old", "Ageing stock"]];

function initListingsControls() {
  if ($("#l-seller").options.length) return;
  const sel = $("#l-seller");
  sel.addEventListener("change", () => { state.lSeller = sel.value; state.lOpen.clear(); loadListings(); });
  $("#l-mode").innerHTML = state.meta.modes.map(m =>
    `<button data-mode="${esc(m.value)}" title="${esc(m.hint)}">${esc(m.label)}</button>`).join("");
  $$("#l-mode button").forEach(b => b.addEventListener("click", () => { state.lMode = b.dataset.mode; loadListings(); }));
}

async function loadListings() {
  initListingsControls();
  const sel = $("#l-seller");
  sel.innerHTML = state.meta.sellers.map(s => `<option value="${s.seller_id}">${esc(s.name)} · ${esc(s.city)}</option>`).join("");
  if (!state.lSeller) state.lSeller = String((state.meta.sellers.find(s => s.listings > 0) || state.meta.sellers[0]).seller_id);
  sel.value = state.lSeller;
  $$("#l-mode button").forEach(b => b.classList.toggle("active", b.dataset.mode === state.lMode));
  $("#l-groups").innerHTML = `<div class="panel muted"><span class="spinner"></span>Analysing listings…</div>`;
  try {
    state.lData = await api(`/api/listings?seller_id=${encodeURIComponent(state.lSeller)}&mode=${encodeURIComponent(state.lMode)}`);
    renderListings();
  } catch (e) {
    $("#l-groups").innerHTML = `<div class="card error">${esc(e.message)}</div>`;
  }
}

function matchesFilter(v) {
  const f = state.lFilter;
  if (f === "all") return true;
  if (f === "down") return v.action === "down" || (v.action === "old" && v.recommended_price < v.current_price);
  if (f === "old") return v.stage === "Ageing";
  if (f === "hold") return v.action === "hold" || v.action === "new" || (v.action === "old" && v.recommended_price === v.current_price);
  return v.action === f;
}

function renderListings() {
  const d = state.lData;
  const s = d.summary;
  if (!s) {
    $("#l-summary").innerHTML = "";
    $("#l-rivals").innerHTML = rivalsCard(d);
    $("#l-filters").innerHTML = "";
    $("#l-groups").innerHTML = `<div class="panel empty-l"><p class="eyebrow">No live listings</p>
      <h2>${esc(d.seller.name)} hasn't listed anything yet</h2>
      <p class="muted">Price a kurti on the Price a product page and press List. It will show up here with its launch plan.</p>
      <button class="btn-primary" id="l-go-price" style="margin-top:8px">Price a product</button></div>`;
    $("#l-go-price").addEventListener("click", () => { switchTab("price"); fe("seller_id").value = String(d.seller.seller_id); sellerHint(); });
    renderToast();
    return;
  }
  const upl = s.profit_uplift;
  const stat = (v, k, sub, cls = "") => `<div class="stat"><div class="stat-v ${cls}">${v}</div><div class="stat-k">${k}</div>${sub ? `<div class="stat-sub">${sub}</div>` : ""}</div>`;
  $("#l-summary").innerHTML = `<div class="panel summary-panel">
    <div class="stat-strip six">
      ${stat(s.listings, "live listings", `${s.designs} designs`)}
      ${stat(num(s.stock_units, 0), "units in stock", `${inr(s.stock_value)} at cost`)}
      ${stat(num(s.orders_30d, 0), "orders, last 30 days", `${inr(s.revenue_30d)} in sales`)}
      ${stat(num(s.ageing_units, 0), "units of ageing stock", s.ageing_units ? "to clear" : "none")}
      ${stat(s.changes, "price changes suggested", `goal: ${esc(d.mode_label)}`)}
      ${stat(`${upl >= 0 ? "+" : ""}${inr(upl)}`, "net profit, next 30 days", `${inr(s.profit_next_30d_now)} → ${inr(s.profit_next_30d_recommended)}`, upl >= 0 ? "good-t" : "bad-t")}
    </div>
    <p class="summary-foot">Net profit is expected sales profit minus the value lost on stock that ages unsold. Data as of ${esc(d.as_of)}; forecasts cover the next ${d.horizon_days} days.</p>
  </div>`;
  $("#l-rivals").innerHTML = rivalsCard(d);
  const all = d.groups.flatMap(g => g.variants);
  const count = k => { const f = state.lFilter; state.lFilter = k; const n = all.filter(matchesFilter).length; state.lFilter = f; return n; };
  $("#l-filters").innerHTML = FILTERS.map(([k, label]) =>
    `<button class="chip${state.lFilter === k ? " active" : ""}" data-f="${k}">${label}<span class="n">${count(k)}</span></button>`).join("");
  $$("#l-filters .chip").forEach(b => b.addEventListener("click", () => { state.lFilter = b.dataset.f; renderListings(); }));
  const groups = d.groups.map(g => ({ ...g, shown: g.variants.filter(matchesFilter) })).filter(g => g.shown.length);
  $("#l-groups").innerHTML = groups.length ? groups.map(groupCard).join("") : `<div class="panel muted">No listings match this filter.</div>`;
  $$("#l-groups tr.vrow").forEach(r => r.addEventListener("click", e => {
    if (e.target.closest("button")) return;
    const id = Number(r.dataset.pid);
    state.lOpen.has(id) ? state.lOpen.delete(id) : state.lOpen.add(id);
    renderListings();
  }));
  $$("#l-groups .apply").forEach(b => b.addEventListener("click", () => applyPrice(Number(b.dataset.pid), Number(b.dataset.price), b)));
  $$("#l-groups .delist").forEach(b => b.addEventListener("click", () => { state.confirmDelist = Number(b.dataset.pid); renderListings(); }));
  $$("#l-groups .delist-cancel").forEach(b => b.addEventListener("click", () => { state.confirmDelist = null; renderListings(); }));
  $$("#l-groups .delist-yes").forEach(b => b.addEventListener("click", () => delist(Number(b.dataset.pid), b)));
  renderToast();
  for (const id of state.lOpen) {
    const v = all.find(x => x.product_id === id);
    if (v) narrateListing(v);
  }
}

function aiKey(v) { return `${v.product_id}|${state.lMode}|${v.current_price}|${v.recommended_price}`; }

async function narrateListing(v) {
  if (!state.meta.llm || !state.meta.llm.enabled || v.action === "new") return;
  const key = aiKey(v);
  if (state.lAi[key]) return;
  state.lAi[key] = { status: "loading" };
  let out = { source: "template" };
  try { out = await api("/api/narrate/listing", { product_id: v.product_id, mode: state.lMode }); } catch (e) { /* keep template */ }
  state.lAi[key] = out.source === "ai" ? { status: "ai", summary: out.summary, points: out.points } : { status: "template" };
  if (state.lOpen.has(v.product_id) && !$("#tab-listings").hidden) renderListings();
}

function renderToast() {
  const el = $("#l-toast");
  const t = state.toast;
  if (!t) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="toast"><span>Delisted <b>${esc(t.title)}</b>. It is no longer visible to buyers.</span>
    <button class="btn-link" id="undo-delist">Undo</button><button class="toast-x" id="close-toast" aria-label="Dismiss">×</button></div>`;
  $("#undo-delist").addEventListener("click", async () => {
    try { await api("/api/listings/relist", { product_id: t.pid }); } catch (e) { /* ignore */ }
    state.toast = null;
    loadListings();
  });
  $("#close-toast").addEventListener("click", () => { state.toast = null; renderToast(); });
}

async function delist(pid, btn) {
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Delisting…`;
  try {
    const out = await api("/api/listings/delist", { product_id: pid });
    state.confirmDelist = null;
    state.lOpen.delete(pid);
    state.toast = { pid, title: out.title };
    await loadListings();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Yes, delist";
    btn.insertAdjacentHTML("afterend", `<span class="bad-t small">${esc(e.message)}</span>`);
  }
}

function rivalsCard(d) {
  const rs = d.rivals.filter(r => r.overlapping > 0);
  const others = d.rivals.filter(r => r.overlapping === 0);
  return `<div class="panel">
    <div class="panel-head"><div><h2>Sellers competing with you</h2>
      <div class="panel-sub">Other sellers on this demo whose kurtis are close to yours</div></div></div>
    ${rs.length ? `<div class="rival-rows">${rs.map(r => `<div class="rival-row">
        <div class="who"><b>${esc(r.name)}</b><span>${esc(r.city)} · ${esc(r.tier)} seller</span></div>
        <div>${r.overlapping} of their ${r.listings} listings compete with yours
          <div class="best">Best seller: ${esc(r.top_listing.title)}, ${inr(r.top_listing.price)}, ${num(r.top_listing.orders_per_day, 1)} orders/day</div></div>
        <div class="fig">avg ${inr(r.avg_price_overlap)}<div class="vs">${num(r.orders_per_day_overlap, 1)} orders/day</div></div>
      </div>`).join("")}</div>`
      : `<p class="muted small" style="margin:0">No other demo seller lists kurtis close to yours right now.</p>`}
    ${others.length && rs.length ? `<p class="muted small" style="margin:12px 0 0">Not competing head-on: ${others.map(r => esc(r.name)).join(", ")}.</p>` : ""}
  </div>`;
}

function groupCard(g) {
  const a = g.attributes;
  const multi = g.variants.length > 1;
  const up = g.profit_uplift_30d;
  return `<div class="panel group">
    <div class="g-head">
      <div><h3>${esc(g.name)}</h3><div class="g-meta">${esc(a.product_type)} · ${esc(a.fabric)} · ${esc(a.pattern)} · ${esc(a.occasion)}${multi ? ` · ${g.variants.length} colours` : ""}</div></div>
      <div class="g-uplift"><div class="v ${up > 0 ? "good-t" : (up < 0 ? "bad-t" : "")}">${up > 0 ? "+" : ""}${inr(up)}</div><div class="k">net profit, 30 days</div></div>
    </div>
    ${g.has_variant_play ? `<div class="variant-note">Colours are priced together. The colour that sells out goes up, which moves some buyers to the slower colour and helps clear it.</div>` : ""}
    <div class="table-wrap"><table class="vt">
      <thead><tr><th>Colour</th><th class="num">Stock</th><th class="num">Orders/day</th><th class="num">Click-through</th><th class="num">Conversion</th>
        <th class="num">Rating</th><th class="num">Price now</th><th class="num">Recommended</th></tr></thead>
      <tbody>${g.shown.map(variantRows).join("")}</tbody>
    </table></div>
  </div>`;
}

function cmp(val, seg, unit = "%") {
  if (val === null || val === undefined) return `<span class="muted">–</span>`;
  const cls = val > seg * 1.1 ? "good-t" : (val < seg * 0.9 ? "bad-t" : "");
  return `<span class="${cls}">${num(val, 1)}${unit}</span><div class="vs">market ${num(seg, 1)}${unit}</div>`;
}

function variantRows(v) {
  const open = state.lOpen.has(v.product_id);
  const sw = SWATCH[(v.color || "").toLowerCase()] || "#c9c9cf";
  const trend = v.trend_pct === null ? "" : `<div class="vs ${v.trend_pct > 5 ? "good-t" : (v.trend_pct < -5 ? "bad-t" : "")}">${v.trend_pct > 0 ? "+" : ""}${v.trend_pct}% vs last month</div>`;
  const changed = v.recommended_price !== v.current_price;
  const cover = v.days_of_cover === null ? "new" : (v.days_of_cover >= 999 ? "999+ days" : `${num(v.days_of_cover, 0)} days`);
  const row = `<tr class="vrow${open ? " open" : ""}" data-pid="${v.product_id}" aria-expanded="${open}">
    <td><span class="swatch" style="background:${sw}"></span><b>${esc(v.color)}</b><span class="stage">${esc(v.stage)}</span>
      <div class="expand">${open ? "Hide details" : "Why this price"}</div></td>
    <td class="num">${num(v.stock, 0)}<div class="vs">${cover}</div></td>
    <td class="num">${num(v.orders_per_day_28d, 1)}${trend}</td>
    <td class="num">${cmp(v.ctr_pct, v.segment_ctr_pct)}</td>
    <td class="num">${cmp(v.cvr_pct, v.segment_cvr_pct)}</td>
    <td class="num">${v.rating ? `★ ${Number(v.rating).toFixed(1)}` : "–"}<div class="vs">${num(v.reviews, 0)} reviews</div></td>
    <td class="num">${inr(v.current_price)}</td>
    <td class="num"><span class="newprice">${inr(v.recommended_price)}</span>${changed ? ` <span class="vs">${v.change_pct > 0 ? "+" : ""}${num(v.change_pct, 1)}%</span>` : ""}
      <div style="margin-top:4px"><span class="act ${esc(v.action)}">${esc(v.action_label)}</span></div></td>
  </tr>`;
  return row + (open ? detailRow(v) : "");
}

function detailRow(v) {
  const n = v.now, w = v.recommended;
  const line = (label, a, b, fmt, better) => {
    const good = better === "up" ? b > a : (better === "down" ? b < a : null);
    const cls = a === b || good === null ? "" : (good ? "good-t" : "bad-t");
    return `<tr><td>${label}</td><td class="num">${fmt(a)}</td><td class="num ${cls}">${fmt(b)}</td></tr>`;
  };
  const days = x => x === null ? "–" : (x >= 999 ? "999+" : num(x, 0));
  const changed = v.recommended_price !== v.current_price;
  const ai = state.lAi[aiKey(v)] || {};
  const texts = ai.status === "ai" ? ai.points : v.reasons.map(r => r.text);
  const badge = ai.status === "loading" ? `<span class="ai-badge"><span class="spinner"></span>Writing…</span>`
    : (ai.status === "ai" ? `<span class="ai-badge on" title="Rewritten by an AI model. Every number was checked against the pricing engine.">AI-written · numbers checked</span>` : "");
  const confirming = state.confirmDelist === v.product_id;
  return `<tr class="detail"><td colspan="8"><div class="detail-grid">
    <div>
      <div class="why-head"><h4>${changed ? `Why ${inr(v.recommended_price)}` : `Why hold at ${inr(v.current_price)}`}</h4>${badge}</div>
      ${ai.status === "ai" ? `<p class="ai-summary">${esc(ai.summary)}</p>` : ""}
      <ul class="why">${v.reasons.map((r, i) => `<li><span class="why-k ${esc(r.tone)}">${esc(REASON_LABEL[r.icon] || "Note")}</span><span>${esc(texts[i])}</span></li>`).join("")}</ul>
      ${v.target_price && v.target_price > v.recommended_price ? `<div class="target">The model sees room up to <b>${inr(v.target_price)}</b>. Raise in steps of up to 10% and check again after about 14 days, because a big jump can cost search ranking.</div>` : ""}
    </div>
    <div>
      <h4>Next 30 days</h4>
      <table class="impact"><thead><tr><th></th><th class="num">Now</th><th class="num">Recommended</th></tr></thead><tbody>
        ${line("Price", n.price, w.price, x => inr(x), null)}
        ${line("Orders a day", n.orders_per_day, w.orders_per_day, x => num(x, 1), "up")}
        ${line("Profit per order", n.profit_per_order, w.profit_per_order, x => inr(x), "up")}
        ${line("Sales profit", n.sales_profit_30d, w.sales_profit_30d, x => inr(x), "up")}
        ${line("Stock ageing cost", n.stock_cost_30d, w.stock_cost_30d, x => inr(x), "down")}
        ${line("Net profit", n.profit_30d, w.profit_30d, x => inr(x), "up")}
        ${line("Days to sell stock", n.days_to_clear ?? 999, w.days_to_clear ?? 999, days, "down")}
      </tbody></table>
      <p class="detail-foot">Cost ${inr(v.cogs)} · break-even ${inr(v.break_even)} · returns ${num(v.return_rate_pct, 1)}% · RTO ${num(v.rto_rate_pct, 1)}% · market ${inr(v.market_p25)}–${inr(v.market_p75)}</p>
      ${sparks(v)}
      <div class="apply-row">
        ${changed ? `<button class="btn-primary apply" data-pid="${v.product_id}" data-price="${v.recommended_price}">Apply ${inr(v.recommended_price)}</button>` : `<span class="vs">No price change needed right now.</span>`}
        <button class="btn-danger delist" data-pid="${v.product_id}"${confirming ? " hidden" : ""}>Delist</button>
      </div>
      ${confirming ? `<div class="confirm">
        <p><b>Delist ${esc(v.title)}?</b> It will be removed from sale and buyers won't find it on Meesho.
          ${v.origin === "seed" ? "This is an example listing, so it comes back when the page is reloaded." : "You can undo this right after."}</p>
        <div class="confirm-actions"><button class="btn-danger solid delist-yes" data-pid="${v.product_id}">Yes, delist</button>
          <button class="btn-secondary delist-cancel">Cancel</button></div>
      </div>` : ""}
    </div>
  </div></td></tr>`;
}

function sparks(v) {
  const h = v.history || [];
  if (h.length < 2) return `<div class="spark-wrap vs">No sales history yet.</div>`;
  const W = 300, H = 40, n = h.length, bw = W / n;
  const maxO = Math.max(1, ...h.map(x => x.orders));
  const bars = h.map((x, i) => `<rect x="${(i * bw).toFixed(1)}" y="${(H - x.orders / maxO * (H - 2)).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${(x.orders / maxO * (H - 2)).toFixed(1)}" fill="var(--series-1)" rx="1"><title>${esc(x.date)}: ${x.orders} orders at ${inr(x.price)}</title></rect>`).join("");
  const ps = h.map(x => x.price), lo = Math.min(...ps), hi = Math.max(...ps);
  const py = p => hi === lo ? H / 2 : H - 4 - (p - lo) / (hi - lo) * (H - 8);
  let path = `M0,${py(ps[0]).toFixed(1)}`;
  h.forEach((x, i) => { path += ` H${(i * bw).toFixed(1)} V${py(x.price).toFixed(1)}`; });
  path += ` H${W}`;
  return `<div class="spark-wrap">
    <div class="k"><span>Orders per day, last ${n} days</span><span>peak ${maxO}</span></div>
    <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Daily orders">${bars}</svg>
    <div class="k" style="margin-top:8px"><span>Price, last ${n} days</span><span>${lo === hi ? inr(lo) : `${inr(lo)}–${inr(hi)}`}</span></div>
    <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Price history"><path d="${path}" fill="none" stroke="var(--text-2)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
  </div>`;
}

async function applyPrice(pid, price, btn) {
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Applying…`;
  try {
    await api("/api/listings/apply", { product_id: pid, price });
    await loadListings();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = `Apply ${inr(price)}`;
    btn.insertAdjacentHTML("afterend", `<span class="bad-t small">${esc(e.message)}</span>`);
  }
}

init();
