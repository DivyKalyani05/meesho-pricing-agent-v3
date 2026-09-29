"use strict";
/* Seller app prototype - phone-first UI on top of the same pricing API. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const S = {
  meta: null, seller: null, view: "today", lang: "en", listings: null, loadingListings: false,
  done: {}, skipped: new Set(), gone: new Set(), shelfFilter: "all", shelfQ: "",
  wiz: null, result: null, lastBody: null, ai: null, slider: null, listed: null, sheetAi: {},
};

// ------------------------------------------------------------------ helpers
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (x, d = 0) => (x == null || Number.isNaN(x)) ? "–" : (Number(x) < 0 ? "−₹" : "₹") + Math.abs(Number(x)).toLocaleString("en-IN", { maximumFractionDigits: d });
const num = (x, d = 1) => x == null ? "–" : Number(x).toLocaleString("en-IN", { maximumFractionDigits: d });
const tr = o => o ? (o[S.lang] || o.en) : "";
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new Error("Can't reach the server. Is it running?"); }
  let data = null;
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) throw new Error((data && data.error) || `Server error (${res.status})`);
  return data;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("on"), 2600);
}
const shortDate = iso => { const [, m, d] = String(iso).split("-").map(Number); return `${d} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]}`; };

// ------------------------------------------------------------------ icons & drawings
const P = {
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>', down: '<path d="M12 5v14M19 12l-7 7-7-7"/>', box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>', trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>', users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  check: '<path d="M4 12.5l5 5L20 6.5"/>', rupee: '<path d="M6 4h12M6 9h12M13.5 20L7 13h3a4.5 4.5 0 0 0 0-9"/>', gift: '<path d="M4 11h16v10H4zM2 7h20v4H2zM12 7v14M12 7S9 2 6.5 4.5 12 7 12 7s3-5 5.5-2.5S12 7 12 7"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>', store: '<path d="M4 10v10h16V10M3 10l2-6h14l2 6M9 20v-6h6v6"/>',
  return: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>', eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.5 12h11L21 7H6"/>', palette: '<path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5 1-1.5 2-1.5h2a4 4 0 0 0 4-4c0-4.5-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  camera: '<path d="M3 8h4l2-3h6l2 3h4v12H3z"/><circle cx="12" cy="13" r="4"/>', target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>', scale: '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>', trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>', search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>', back: '<path d="M15 5l-7 7 7 7"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
};
const icon = (n, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || P.info}</svg>`;
const SW = { indigo: "#3f4a9a", maroon: "#7a1f2b", mustard: "#d4a017", white: "#f5f3ee", "off white": "#efe8d8", yellow: "#f2d33b", "sky blue": "#8cc8ec",
  peach: "#f6b99a", red: "#d33a3a", green: "#3f8f4f", grey: "#9a9aa0", black: "#2a2a2e", wine: "#6e1f3a", teal: "#1f8a8a", pink: "#f07aa8", "navy blue": "#23305e",
  lavender: "#b9a6e0", orange: "#f08a2c", magenta: "#c0288c", blue: "#3a6fd8", rust: "#b7472a", olive: "#6b7a2f", cream: "#f4ead2", purple: "#6b3fa0" };
const swatch = c => SW[String(c || "").toLowerCase()] || "#c98aa6";
function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const f = v => Math.max(0, Math.min(255, Math.round(v + (amt > 0 ? (255 - v) * amt : v * amt))));
  return "#" + [f(n >> 16), f((n >> 8) & 255), f(n & 255)].map(v => v.toString(16).padStart(2, "0")).join("");
}
function kurti(color, pattern = "") {
  const c = swatch(color), light = shade(c, 0.45), dark = shade(c, -0.25);
  const motif = pattern.includes("Block") || pattern.includes("Print")
    ? `<g fill="${light}" opacity=".85"><circle cx="19" cy="38" r="2"/><circle cx="31" cy="38" r="2"/><circle cx="25" cy="47" r="2"/><circle cx="19" cy="56" r="2"/><circle cx="31" cy="56" r="2"/></g>`
    : pattern.includes("Embroid") || pattern.includes("Chikan") || pattern.includes("Mirror")
      ? `<path d="M20 22 Q25 30 30 22" stroke="${light}" stroke-width="1.6" fill="none"/><g fill="${light}"><circle cx="25" cy="34" r="1.6"/><circle cx="21" cy="40" r="1.3"/><circle cx="29" cy="40" r="1.3"/></g>`
      : `<path d="M15 50h20" stroke="${light}" stroke-width="1.6"/>`;
  return `<svg viewBox="0 0 50 62" aria-hidden="true"><path d="M17 3l8 5 8-5 12 8-5 7-3-2v44H13V16l-3 2-5-7z" fill="${c}" stroke="${dark}" stroke-width=".8"/>
    <path d="M21 5.5l4 8 4-8" fill="none" stroke="${dark}" stroke-width="1"/>${motif}</svg>`;
}

// ------------------------------------------------------------------ boot
async function boot() {
  try { await api("/api/demo/restore", {}); } catch (e) { /* not critical */ }
  try { S.meta = await api("/api/meta"); } catch (e) { $("#view").innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  const sel = $("#seller-select");
  sel.innerHTML = S.meta.sellers.map(s => `<option value="${s.seller_id}">${esc(s.name)} · ${esc(s.city)}</option>`).join("");
  S.seller = S.meta.sellers.find(s => s.listings > 0) || S.meta.sellers[0];
  sel.value = S.seller.seller_id;
  sel.addEventListener("change", () => {
    S.seller = S.meta.sellers.find(s => String(s.seller_id) === sel.value);
    S.listings = null; S.done = {}; S.gone = new Set(); S.skipped = new Set(); S.sheetAi = {};
    paintSeller(); go(S.view === "new" ? "new" : S.view);
  });
  paintSeller();
  $$(".nav button").forEach(b => b.addEventListener("click", () => go(b.dataset.view)));
  $("#scrim").addEventListener("click", closeSheet);
  window.addEventListener("hashchange", () => go(location.hash.slice(1) || "today", true));
  go(location.hash.slice(1) || "today", true);
}
function paintSeller() {
  const n = S.seller.name.replace(/\(.*\)/, "").trim();
  $("#seller-name").textContent = n;
  $("#avatar").textContent = n.split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
}
function go(view, fromHash = false) {
  if (!["today", "new", "shelf"].includes(view)) view = "today";
  S.view = view;
  if (!fromHash && location.hash.slice(1) !== view) history.pushState(null, "", "#" + view);
  $$(".nav button").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  closeSheet();
  window.scrollTo(0, 0);
  if (view === "new") { if (!S.wiz) newWizard(); renderWizard(); }
  else if (view === "shelf") renderShelf();
  else renderToday();
}

async function ensureListings() {
  if (S.listings || S.loadingListings) return;
  S.loadingListings = true;
  try { S.listings = await api(`/api/listings?seller_id=${S.seller.seller_id}&mode=balanced`); }
  catch (e) { S.listings = { error: e.message }; }
  S.loadingListings = false;
  if (S.view === "today") renderToday();
  if (S.view === "shelf") renderShelf();
}
const variants = () => (S.listings && S.listings.groups ? S.listings.groups.flatMap(g => g.variants.map(v => ({ ...v, design: g.name, attrs: g.attributes }))) : [])
  .filter(v => !S.gone.has(v.product_id));

// ------------------------------------------------------------------ TODAY
function actionOf(v) {
  const up = v.recommended_price > v.current_price, down = v.recommended_price < v.current_price;
  if (up) return { cls: "up", icon: "up", verb: `Raise to ${inr(v.recommended_price)}` };
  if (down && v.stage === "Ageing") return { cls: "old", icon: "down", verb: `Clear at ${inr(v.recommended_price)}` };
  if (down) return { cls: "down", icon: "down", verb: `Lower to ${inr(v.recommended_price)}` };
  if (/restock/i.test(v.action_label)) return { cls: "hold", icon: "box", verb: "Restock now" };
  if (v.action === "old") return { cls: "old", icon: "gift", verb: "Bundle or liquidate" };
  return null;
}
const ORDER = ["stock", "variant", "old", "funnel", "festival", "cost", "market", "bundle", "season", "eye", "star", "rival"];
function oneLiner(v) {
  const r = [...v.reasons].sort((a, b) => (ORDER.indexOf(a.icon) + 99 * (ORDER.indexOf(a.icon) < 0)) - (ORDER.indexOf(b.icon) + 99 * (ORDER.indexOf(b.icon) < 0)))[0];
  const t = r ? r.text : "";
  const first = t.split(/(?<=[.!?])\s/)[0];
  return first.length > 150 ? first.slice(0, 147) + "…" : first;
}
function renderToday() {
  const view = $("#view");
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const name = S.seller.name.replace(/\(.*\)/, "").trim();
  if (!S.listings) {
    view.innerHTML = `<h1>${hello}</h1><p class="sub">${esc(name)}</p><div class="skel" style="height:180px"></div>
      <div class="pulse"><div class="skel" style="height:64px"></div><div class="skel" style="height:64px"></div><div class="skel" style="height:64px"></div></div>
      <div class="skel" style="height:130px;margin-top:22px"></div>`;
    ensureListings();
    return;
  }
  if (S.listings.error) { view.innerHTML = `<div class="err">${esc(S.listings.error)}</div>`; return; }
  const vs = variants();
  if (!vs.length) {
    view.innerHTML = `<h1>${hello}</h1><p class="sub">${esc(name)}</p>
      <div class="money"><div class="k">Welcome to Meesho selling</div><div class="v" style="font-size:1.9rem">Let's price your first kurti</div>
      <div class="d">Tell us about it in three quick steps. We'll check the market and suggest a price that sells.</div>
      <div style="margin-top:16px"><button class="btn primary" data-go="new">${icon("tag")}Start now</button></div></div>`;
    $$("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
    return;
  }
  const todo = vs.map(v => ({ v, a: actionOf(v) })).filter(x => x.a && !S.skipped.has(x.v.product_id))
    .sort((x, y) => Math.abs(y.v.profit_uplift_30d) - Math.abs(x.v.profit_uplift_30d));
  const total = todo.reduce((s, x) => s + Math.max(0, x.v.profit_uplift_30d), 0);
  const doneGain = todo.filter(x => S.done[x.v.product_id]).reduce((s, x) => s + Math.max(0, x.v.profit_uplift_30d), 0);
  const nDone = todo.filter(x => S.done[x.v.product_id]).length;
  const sum = S.listings.summary;
  const pct = total ? Math.round(100 * doneGain / total) : 0;
  view.innerHTML = `
    <h1>${hello}, ${esc(name.split(" ")[0])}</h1>
    <p class="sub">${todo.length ? `${todo.length} quick price ${todo.length === 1 ? "fix" : "fixes"} for your shop today.` : "Your prices look good today."}</p>
    ${!todo.length ? `<div class="money">
      <div class="k">${vs.every(v => v.stage === "New") ? "Your kurtis are live" : "Your shop is in good shape"}</div>
      <div class="v" style="font-size:1.9rem">${vs.every(v => v.stage === "New") ? "Now let the first orders come in" : "No price changes needed"}</div>
      <div class="d">${vs.every(v => v.stage === "New") ? "Keep the launch price. After about 3 weeks of sales we'll tell you if a colour should go up or down." : "We check your prices against the market every day and will tell you when something should change."}</div>
    </div>` : `<div class="money">
      <div class="k">${nDone ? "Extra profit unlocked" : "You could earn more"}</div>
      <div class="v">${nDone ? inr(doneGain) : "+" + inr(total)}</div>
      <div class="d">${nDone ? `of ${inr(total)} possible in the next 30 days.` : "in the next 30 days by updating the prices below. Each one takes a tap."}</div>
      <div class="progress"><i style="width:${pct}%"></i></div>
      <div class="progress-k">${nDone} of ${todo.length} done</div>
    </div>`}
    <div class="pulse">
      <div class="card"><div class="v">${num(sum.orders_30d, 0)}</div><div class="k">orders, 30 days</div></div>
      <div class="card"><div class="v">${num(sum.stock_units - sum.ageing_units, 0)}</div><div class="k">fresh of ${num(sum.stock_units, 0)} pcs</div></div>
      <div class="card"><div class="v" style="color:${sum.ageing_units ? "var(--red)" : "inherit"}">${num(sum.ageing_units, 0)}</div><div class="k">pieces ageing</div></div>
    </div>
    <h2>To do <small>biggest gains first</small></h2>
    <div class="todo">${todo.length ? todo.map(({ v, a }) => actCard(v, a)).join("") : `<div class="card allset"><div style="width:52px;height:52px;border-radius:50%;background:var(--green-soft);color:var(--green);display:grid;place-items:center;margin:0 auto">${icon("check")}</div><div class="big">All set</div><div class="muted">Nothing needs a price change right now.</div></div>`}</div>
    <p class="proto-note" style="margin-top:22px">Prototype: "Update price" here doesn't change your saved data. <a href="/">Open the full app</a></p>`;
  bindToday();
}
function actCard(v, a) {
  const done = S.done[v.product_id];
  const up = v.profit_uplift_30d;
  return `<div class="card act${done ? " done" : ""}" data-pid="${v.product_id}">
    <div class="thumb">${kurti(v.color, v.attrs.pattern)}<span class="n">${num(v.stock, 0)}</span></div>
    <div>
      <div class="meta">${esc(v.color)} · ${esc(v.design)}</div>
      <div class="title"><span class="verb ${a.cls}">${icon(a.icon)}${esc(a.verb)}</span></div>
      ${v.recommended_price !== v.current_price ? `<div class="pp">Now <s>${inr(v.current_price)}</s> → <b>${inr(v.recommended_price)}</b></div>` : ""}
      <p class="why1">${esc(oneLiner(v))}</p>
      ${up ? `<span class="gain${up < 0 ? " neg" : ""}">${up > 0 ? "+" : ""}${inr(up)} net in 30 days</span>` : ""}
      <div class="btns">${done ? `<span class="done-tag">${icon("check")}${esc(done)}</span><button class="btn link" data-undo="${v.product_id}">Undo</button>`
        : `${v.recommended_price !== v.current_price ? `<button class="btn primary" data-apply="${v.product_id}">Update price</button>`
          : `<button class="btn primary" data-apply="${v.product_id}" data-label="Marked as done">Got it</button>`}
          <button class="btn ghost" data-why="${v.product_id}">Why?</button>
          <button class="btn link" data-skip="${v.product_id}">Not now</button>`}</div>
    </div></div>`;
}
function bindToday() {
  $$("[data-apply]").forEach(b => b.addEventListener("click", () => {
    const v = variants().find(x => x.product_id === Number(b.dataset.apply));
    S.done[v.product_id] = b.dataset.label || `Price set to ${inr(v.recommended_price)}`;
    toast(b.dataset.label ? "Marked as done" : `${v.color} now ${inr(v.recommended_price)} (prototype - not saved)`);
    renderToday();
  }));
  $$("[data-undo]").forEach(b => b.addEventListener("click", () => { delete S.done[Number(b.dataset.undo)]; renderToday(); }));
  $$("[data-skip]").forEach(b => b.addEventListener("click", () => { S.skipped.add(Number(b.dataset.skip)); toast("Moved out of today's list"); renderToday(); }));
  $$("[data-why]").forEach(b => b.addEventListener("click", () => openItem(Number(b.dataset.why))));
}

// ------------------------------------------------------------------ SHELF (my kurtis)
const FILTERS = [["all", "All"], ["fix", "Needs a price change"], ["hot", "Selling well"], ["low", "Low stock"], ["old", "Ageing"]];
function matches(v, f) {
  if (f === "fix") return v.recommended_price !== v.current_price;
  if (f === "hot") return v.orders_per_day_28d >= 4 || (v.trend_pct || 0) >= 15;
  if (f === "low") return v.days_of_cover != null && v.days_of_cover < 14;
  if (f === "old") return v.stage === "Ageing";
  return true;
}
function renderShelf() {
  const view = $("#view");
  if (!S.listings) {
    view.innerHTML = `<h1>My kurtis</h1><div class="shelf">${"<div class='skel' style='height:230px'></div>".repeat(4)}</div>`;
    ensureListings();
    return;
  }
  const all = variants();
  const q = S.shelfQ.toLowerCase();
  const shown = all.filter(v => matches(v, S.shelfFilter) && (!q || `${v.title} ${v.color}`.toLowerCase().includes(q)));
  view.innerHTML = `
    <h1>My kurtis</h1><p class="sub">${all.length} live listings · tap one to see how it's doing</p>
    <label class="search">${icon("search")}<input id="shelf-q" type="search" placeholder="Search by name or colour" value="${esc(S.shelfQ)}"></label>
    <div class="chips">${FILTERS.map(([k, l]) => `<button class="chip${S.shelfFilter === k ? " on" : ""}" data-f="${k}">${l} · ${all.filter(v => matches(v, k)).length}</button>`).join("")}</div>
    ${all.length ? "" : `<div class="card allset"><div class="big">No kurtis yet</div><p class="muted">Price your first one and list it.</p><button class="btn primary" data-go="new">New kurti</button></div>`}
    <div class="shelf">${shown.map(itemCard).join("")}</div>
    ${all.length && !shown.length ? `<p class="muted" style="text-align:center;margin-top:20px">Nothing matches.</p>` : ""}`;
  const input = $("#shelf-q");
  input.addEventListener("input", () => { S.shelfQ = input.value; renderShelf(); const i = $("#shelf-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); });
  $$(".chip[data-f]").forEach(b => b.addEventListener("click", () => { S.shelfFilter = b.dataset.f; renderShelf(); }));
  $$(".item").forEach(b => b.addEventListener("click", () => openItem(Number(b.dataset.pid))));
  $$("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
}
function itemCard(v) {
  const a = actionOf(v);
  const flag = v.stage === "New" ? ["new", "New"] : a ? [a.cls, a.cls === "up" ? `Raise ${inr(v.recommended_price)}` : a.cls === "hold" ? "Restock" : a.cls === "old" ? "Clear" : `Lower ${inr(v.recommended_price)}`] : null;
  const cover = v.days_of_cover;
  const pct = cover == null ? 100 : Math.max(4, Math.min(100, cover / 90 * 100));
  const col = cover == null ? "#d9cfcb" : cover < 10 ? "var(--red)" : cover > 90 ? "var(--amber)" : "var(--green)";
  const price = S.done[v.product_id] && v.recommended_price !== v.current_price ? v.recommended_price : v.current_price;
  return `<button class="card item" data-pid="${v.product_id}">
    <div class="pic" style="background:${shade(swatch(v.color), 0.82)}">${kurti(v.color, v.attrs.pattern)}${flag ? `<span class="flag ${flag[0]}">${esc(flag[1])}</span>` : ""}</div>
    <div class="body"><div class="name">${esc(v.title)}</div>
      <div class="price">${inr(price)}</div>
      <div class="sold">${v.stage === "New" ? "Just listed" : `${num(v.orders_per_day_28d, 1)} orders a day`}${v.rating ? ` · ★ ${Number(v.rating).toFixed(1)}` : ""}</div>
      <div class="stockbar"><i style="width:${pct}%;background:${col}"></i></div>
      <div class="stockk">${num(v.stock, 0)} in stock${cover == null ? "" : cover >= 999 ? " · 999+ days" : ` · ${num(cover, 0)} days left`}</div>
    </div></button>`;
}

// ------------------------------------------------------------------ item sheet
const RICON = { market: "store", funnel: "cart", eye: "eye", stock: "box", variant: "palette", festival: "spark", season: "cal", old: "clock", bundle: "gift",
  star: "star", rival: "users", new: "tag", plan: "cal", wait: "clock", cost: "rupee", seller: "star", crowd: "users", returns: "return", shop: "store" };
const RLABEL = { market: "Market", funnel: "Buyers", eye: "Clicks", stock: "Stock", variant: "Colours", festival: "Festivals", season: "Season", old: "Old stock",
  bundle: "Clearance", star: "Reviews", rival: "Competition", new: "New listing", plan: "Plan", wait: "Timing", cost: "Margin" };
function openItem(pid) {
  const v = variants().find(x => x.product_id === pid);
  if (!v) return;
  const a = actionOf(v);
  const ai = S.sheetAi[pid];
  const texts = ai && ai.source === "ai" ? ai.points : v.reasons.map(r => r.text);
  const n = v.now, w = v.recommended;
  const changed = v.recommended_price !== v.current_price;
  openSheet(`
    <div style="display:grid;grid-template-columns:64px 1fr;gap:14px;align-items:center">
      <div class="thumb">${kurti(v.color, v.attrs.pattern)}</div>
      <div><div class="meta muted" style="font-size:.78rem">${esc(v.stage)} · listed ${esc(shortDate(v.listed_on))}</div><h3>${esc(v.title)}</h3></div>
    </div>
    <div class="facts">
      <div class="fact"><div class="v">${num(v.orders_per_day_28d, 1)}</div><div class="k">orders a day</div></div>
      <div class="fact"><div class="v">${num(v.stock, 0)}</div><div class="k">${v.days_of_cover == null ? "in stock" : v.days_of_cover >= 999 ? "pcs · 999+ days" : `pcs · ${num(v.days_of_cover, 0)} days`}</div></div>
      <div class="fact"><div class="v">${v.rating ? "★ " + Number(v.rating).toFixed(1) : "–"}</div><div class="k">${num(v.reviews, 0)} reviews</div></div>
    </div>
    <div class="card" style="box-shadow:none;background:#faf6f4;padding:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <div><div class="muted" style="font-size:.76rem">${changed ? "Recommended" : "Your price"}</div>
          <div style="font-size:1.8rem;font-weight:850;letter-spacing:-.03em" class="tnum">${inr(v.recommended_price)}
          ${changed ? `<span class="muted" style="font-size:.9rem;font-weight:600"> from <s>${inr(v.current_price)}</s></span>` : ""}</div></div>
        ${a ? `<span class="verb ${a.cls}" style="font-weight:750;font-size:.9rem">${icon(a.icon)}${esc(a.verb.split(" ")[0])}</span>` : ""}
      </div>
      <div class="facts" style="margin:10px 0 0">
        <div class="fact" style="background:#fff"><div class="v">${inr(n.profit_per_order)} → ${inr(w.profit_per_order)}</div><div class="k">profit per order</div></div>
        <div class="fact" style="background:#fff"><div class="v">${num(n.orders_per_day, 1)} → ${num(w.orders_per_day, 1)}</div><div class="k">orders a day</div></div>
        <div class="fact" style="background:#fff"><div class="v" style="color:${v.profit_uplift_30d >= 0 ? "var(--green)" : "var(--amber)"}">${v.profit_uplift_30d >= 0 ? "+" : ""}${inr(v.profit_uplift_30d)}</div><div class="k">net, 30 days</div></div>
      </div>
    </div>
    ${ai && ai.source === "ai" ? `<div class="summary-box">${esc(ai.summary)}</div>` : ""}
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:18px">
      <b>Why</b>${ai === "loading" ? `<span class="ai-note">${icon("spark")}Writing a clearer explanation…</span>` : ai && ai.source === "ai" ? `<span class="ai-note">${icon("spark")}AI-written · numbers checked</span>` : ""}</div>
    <div class="reasons">${v.reasons.map((r, i) => `<div class="reason"><div class="ic ${esc(r.tone)}">${icon(RICON[r.icon] || "info")}</div>
      <div><div class="t">${esc(RLABEL[r.icon] || "Note")}</div><div class="x">${esc(texts[i])}</div></div></div>`).join("")}</div>
    <div class="btns">
      ${changed && !S.done[v.product_id] ? `<button class="btn primary" id="s-apply">Update to ${inr(v.recommended_price)}</button>` : ""}
      <button class="btn danger" id="s-delist">${icon("trash")}Delist</button>
      <button class="btn ghost" id="s-close">Close</button>
    </div>
    <p class="proto-note" style="margin-top:14px">Prototype: updates and delists here aren't saved.</p>`);
  const ap = $("#s-apply");
  if (ap) ap.addEventListener("click", () => { S.done[pid] = `Price set to ${inr(v.recommended_price)}`; toast(`${v.color} now ${inr(v.recommended_price)} (prototype)`); closeSheet(); rerender(); });
  $("#s-delist").addEventListener("click", () => {
    const b = $("#s-delist");
    if (!b.dataset.sure) { b.dataset.sure = "1"; b.innerHTML = `${icon("trash")}Tap again to delist`; return; }
    S.gone.add(pid); toast(`${v.color} delisted (prototype)`); closeSheet(); rerender();
  });
  $("#s-close").addEventListener("click", closeSheet);
  if (!ai && S.meta.llm && S.meta.llm.enabled && v.stage !== "New") {
    S.sheetAi[pid] = "loading";
    openItem(pid);
    api("/api/narrate/listing", { product_id: pid, mode: "balanced" })
      .catch(() => ({ source: "template" }))
      .then(out => { S.sheetAi[pid] = out; if ($("#sheet").dataset.pid === String(pid)) openItem(pid); });
  }
  $("#sheet").dataset.pid = pid;
}
const rerender = () => (S.view === "shelf" ? renderShelf() : renderToday());
function openSheet(html) {
  const sh = $("#sheet"), sc = $("#scrim");
  const wasOpen = sh.classList.contains("on");
  sh.innerHTML = `<div class="grab"></div>${html}`;
  sh.hidden = false; sc.hidden = false;
  if (!wasOpen) requestAnimationFrame(() => { sh.classList.add("on"); sc.classList.add("on"); });
}
function closeSheet() {
  const sh = $("#sheet"), sc = $("#scrim");
  if (!sh.classList.contains("on")) return;
  sh.classList.remove("on"); sc.classList.remove("on");
  delete sh.dataset.pid;
  setTimeout(() => { if (!sh.classList.contains("on")) { sh.hidden = true; sc.hidden = true; } }, 280);
}

// ------------------------------------------------------------------ NEW KURTI wizard
const ATTRS = [["product_type", "Type"], ["fabric", "Fabric"], ["pattern", "Work"], ["occasion", "Occasion"], ["sleeve", "Sleeve"], ["length", "Length"]];
function newWizard() {
  S.wiz = { step: 1, photos: [], title: "", desc: "", colors: [], attrs: { product_type: "kurti", fabric: "cotton", pattern: "printed", occasion: "daily", sleeve: "three_quarter", length: "knee" },
    auto: new Set(), cogs: "", stock: 50, restock: true, sellBy: "", offline: false, shopPrice: "", shopMargin: "", goal: "balanced", err: "" };
  S.result = null; S.ai = null; S.slider = null; S.listed = null;
}
const label = (attr, val) => { const o = S.meta.options[attr].find(x => x.value === val); return o ? o.label : val; };
function renderWizard() {
  const w = S.wiz;
  if (w.step === 4 && S.result) return renderResult();
  const view = $("#view");
  const bar = `<div class="steps">${[1, 2, 3].map(i => `<i class="${i <= w.step ? "on" : ""}"></i>`).join("")}</div>`;
  let body = "";
  if (w.step === 1) {
    body = `<p class="q">Show us your kurti</p><p class="sub">Photos and a few words are enough - we'll work out the details.</p>
      <div class="photos">${w.photos.map((src, i) => `<div class="ph"><img src="${esc(src)}" alt="Photo ${i + 1}"></div>`).join("")}
        ${w.photos.length < 8 ? `<label class="ph add">${icon("camera")}${w.photos.length ? "Add more" : "Add photos"}<input type="file" accept="image/*" multiple id="w-photos"></label>` : ""}</div>
      <div class="field"><label for="w-title">Name</label><input class="in" id="w-title" placeholder="e.g. Jaipuri cotton block print kurti" value="${esc(w.title)}"></div>
      <div class="field"><label for="w-desc">Describe it</label><textarea class="in" id="w-desc" placeholder="Fabric, work, sleeve, length, occasion…">${esc(w.desc)}</textarea></div>
      <div class="field"><span class="lbl">We spotted <span class="muted" style="font-weight:500">· tap to change</span></span>
        <div class="spotted">${ATTRS.map(([k, l]) => `<label class="pick${w.auto.has(k) ? " auto" : ""}"><span><small>${l}</small>${esc(label(k, w.attrs[k]))}</span>
          <select data-attr="${k}">${S.meta.options[k].map(o => `<option value="${esc(o.value)}"${o.value === w.attrs[k] ? " selected" : ""}>${esc(o.label)}</option>`).join("")}</select></label>`).join("")}</div></div>
      <div class="field"><span class="lbl">Colours <span class="muted" style="font-weight:500">· one listing per colour</span></span>
        <div class="tags" id="w-tags">${w.colors.map((c, i) => `<span class="tag"><span class="sw" style="background:${swatch(c)}"></span>${esc(c)}<button data-rm="${i}" aria-label="Remove ${esc(c)}">×</button></span>`).join("")}
        <input id="w-color" placeholder="${w.colors.length ? "Add another" : "Type a colour and press Enter"}"></div></div>`;
  } else if (w.step === 2) {
    body = `<p class="q">Costs and stock</p><p class="sub">Only you see this. It's how we make sure every order earns you money.</p>
      <div class="field"><label for="w-cogs">What does one piece cost you?</label><div class="money-in"><span>₹</span><input id="w-cogs" type="number" inputmode="numeric" min="1" placeholder="150" value="${esc(w.cogs)}"></div>
        <div class="hint">Cloth, stitching and printing. We add shipping, packing, GST and returns for you.</div></div>
      <div class="field"><label>How many pieces do you have?</label><div class="stepper"><button data-step="-10" aria-label="10 fewer">−</button>
        <input id="w-stock" type="number" inputmode="numeric" min="1" value="${esc(w.stock)}"><button data-step="10" aria-label="10 more">+</button></div></div>
      <div class="field"><span class="lbl">Can you make more when these sell out?</span><div class="seg">
        <button data-restock="1" class="${w.restock ? "on" : ""}">Yes, I can restock</button><button data-restock="0" class="${!w.restock ? "on" : ""}">No, one-time lot</button></div></div>
      <div class="toggle-row"><div><b>Must sell by a date?</b><div class="muted" style="font-size:.82rem">Season end, old stock, or a deadline</div></div>
        <label class="switch"><input type="checkbox" id="w-sellby-on"${w.sellBy ? " checked" : ""}><span></span></label></div>
      ${w.sellBy ? `<div class="field"><input class="in" type="date" id="w-sellby" value="${esc(w.sellBy)}" min="${esc(S.meta.default_launch_date)}"></div>` : ""}
      <div class="toggle-row"><div><b>Do you sell it in a shop too?</b><div class="muted" style="font-size:.82rem">We'll compare your earnings</div></div>
        <label class="switch"><input type="checkbox" id="w-off-on"${w.offline ? " checked" : ""}><span></span></label></div>
      ${w.offline ? `<div class="seg" style="grid-template-columns:1fr 1fr;margin-bottom:10px">
        <div class="money-in"><span>₹</span><input id="w-shop" type="number" inputmode="numeric" placeholder="Shop price" value="${esc(w.shopPrice)}" style="font-size:1.1rem"></div>
        <div class="money-in"><input id="w-margin" type="number" inputmode="numeric" placeholder="Margin" value="${esc(w.shopMargin)}" style="font-size:1.1rem"><span>%</span></div></div>` : ""}`;
  } else if (w.step === 3) {
    const G = { balanced: ["scale", "Good profit, steady sales"], max_margin: ["rupee", "Earn the most per month"], scale: ["bolt", "Get orders and reviews fast"], clear_inventory: ["box", "Sell out all my stock"] };
    body = `<p class="q">What matters most right now?</p><p class="sub">You can change this any time.</p>
      <div class="goals">${S.meta.modes.map(m => `<button class="goal${w.goal === m.value ? " on" : ""}" data-goal="${m.value}">
        <span class="gi">${icon(G[m.value][0])}</span><span><b>${esc(m.label)}${m.value === "balanced" ? `<span class="rec">Recommended</span>` : ""}</b><span>${G[m.value][1]}</span></span></button>`).join("")}</div>`;
  } else if (w.step === 3.5) {
    return renderThinking();
  }
  view.innerHTML = `${bar}${w.err ? `<div class="err">${esc(w.err)}</div>` : ""}${body}
    <div class="wiz-foot">${w.step > 1 ? `<button class="btn ghost block" id="w-back" style="flex:0 0 auto;width:auto;padding:15px 20px">${icon("back")}</button>` : ""}
      <button class="btn primary block" id="w-next">${w.step === 3 ? "Find my price" : "Continue"}</button></div>`;
  bindWizard();
}
function bindWizard() {
  const w = S.wiz;
  const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
  on("#w-photos", "change", e => { for (const f of e.target.files) if (f.type.startsWith("image/") && w.photos.length < 8) w.photos.push(URL.createObjectURL(f)); renderWizard(); });
  let t;
  const detect = () => { clearTimeout(t); t = setTimeout(async () => {
    const text = `${w.title} ${w.desc}`.trim();
    if (!text) return;
    try {
      const { detected } = await api("/api/detect", { text });
      let changed = false;
      for (const [k, v] of Object.entries(detected)) if (w.attrs[k] !== v && !w.touched?.has(k)) { w.attrs[k] = v; w.auto.add(k); changed = true; }
      if (changed && w.step === 1) {
        const f = document.activeElement && document.activeElement.id, pos = f && document.activeElement.selectionStart;
        renderWizard();
        if (f) { const el = document.getElementById(f); el.focus(); if (pos != null) el.setSelectionRange(pos, pos); }
      }
    } catch (e) { /* convenience only */ }
  }, 500); };
  on("#w-title", "input", e => { w.title = e.target.value; detect(); });
  on("#w-desc", "input", e => { w.desc = e.target.value; detect(); });
  $$("select[data-attr]").forEach(s => s.addEventListener("change", () => { w.attrs[s.dataset.attr] = s.value; w.auto.delete(s.dataset.attr); (w.touched = w.touched || new Set()).add(s.dataset.attr); renderWizard(); }));
  on("#w-color", "keydown", e => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const c = e.target.value.trim().replace(/,$/, "");
      if (c && w.colors.length < 6 && !w.colors.some(x => x.toLowerCase() === c.toLowerCase())) w.colors.push(c.replace(/\b\w/g, m => m.toUpperCase()));
      renderWizard(); $("#w-color").focus();
    }
  });
  $$("[data-rm]").forEach(b => b.addEventListener("click", () => { w.colors.splice(Number(b.dataset.rm), 1); renderWizard(); }));
  on("#w-cogs", "input", e => { w.cogs = e.target.value; });
  on("#w-stock", "input", e => { w.stock = e.target.value; });
  $$("[data-step]").forEach(b => b.addEventListener("click", () => { w.stock = Math.max(1, (Number(w.stock) || 0) + Number(b.dataset.step)); $("#w-stock").value = w.stock; }));
  $$("[data-restock]").forEach(b => b.addEventListener("click", () => { w.restock = b.dataset.restock === "1"; renderWizard(); }));
  on("#w-sellby-on", "change", e => { w.sellBy = e.target.checked ? addDays(S.meta.default_launch_date, 45) : ""; renderWizard(); });
  on("#w-sellby", "input", e => { w.sellBy = e.target.value; });
  on("#w-off-on", "change", e => { w.offline = e.target.checked; renderWizard(); });
  on("#w-shop", "input", e => { w.shopPrice = e.target.value; });
  on("#w-margin", "input", e => { w.shopMargin = e.target.value; });
  $$("[data-goal]").forEach(b => b.addEventListener("click", () => { w.goal = b.dataset.goal; renderWizard(); }));
  on("#w-back", "click", () => { w.err = ""; w.step -= 1; renderWizard(); });
  on("#w-next", "click", () => {
    w.err = "";
    if (w.step === 1 && !w.title.trim() && !w.desc.trim()) { w.err = "Give your kurti a name or a short description."; return renderWizard(); }
    if (w.step === 2) {
      if (!(Number(w.cogs) > 0)) { w.err = "Enter what one piece costs you."; return renderWizard(); }
      if (!(Number(w.stock) >= 1)) { w.err = "Enter how many pieces you have."; return renderWizard(); }
      if (w.colors.length > Number(w.stock)) { w.err = `You have ${w.stock} pieces but ${w.colors.length} colours.`; return renderWizard(); }
    }
    if (w.step === 3) return findPrice();
    w.step += 1; renderWizard(); window.scrollTo(0, 0);
  });
}
function addDays(iso, n) { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

function body() {
  const w = S.wiz;
  return { seller_id: S.seller.seller_id, title: w.title, description: w.desc, ...w.attrs, cogs: w.cogs, inventory: w.stock, horizon_days: 30,
    launch_date: S.meta.default_launch_date, expiry_date: w.sellBy, limited_stock: !w.restock, offline_price: w.offline ? w.shopPrice : "",
    offline_margin_pct: w.offline ? w.shopMargin : "", n_photos: w.photos.length, colors: w.colors.join(", "), mode: w.goal };
}
const THINK = ["Reading your kurti", "Checking similar kurtis on Meesho", "Looking at festivals and season", "Adding up your costs", "Finding the best price"];
function renderThinking(step = 0) {
  $("#view").innerHTML = `<div class="thinking"><div class="orb"></div><p class="q" style="margin-bottom:18px">Working out your price…</p>
    <ul class="think-steps">${THINK.map((t, i) => `<li class="${i < step ? "ok" : i === step ? "on" : ""}"><span class="dot">${i < step ? "✓" : ""}</span>${t}</li>`).join("")}</ul></div>`;
}
async function findPrice() {
  const w = S.wiz;
  w.step = 3.5;
  S.lastBody = body();
  renderThinking(0);
  const req = api("/api/recommend", S.lastBody);
  for (let i = 1; i <= THINK.length; i++) { await sleep(420); if (S.view === "new") renderThinking(i); }
  try {
    S.result = await req;
  } catch (e) {
    w.step = e.message.match(/cost|COGS|inventory|units/i) ? 2 : 1;
    w.err = e.message;
    return renderWizard();
  }
  S.slider = null; S.ai = null; S.listed = null;
  w.step = 4;
  if (S.view === "new") { renderResult(); window.scrollTo(0, 0); }
  narrate(S.result);
}
async function narrate(result) {
  if (!S.meta.llm || !S.meta.llm.enabled || !result.recommendation_id) return;
  S.ai = "loading";
  if (S.view === "new" && S.result === result) renderResult();
  let out = { source: "template" };
  try { out = await api("/api/narrate/pricing", { recommendation_id: result.recommendation_id }); } catch (e) { /* keep template */ }
  if (out.source === "ai") {
    const ex = result.explanation;
    ex.headline = out.headline; ex.summary = out.summary; ex.tips = out.tips;
    ex.reasons.forEach((r, i) => { r.text = out.reasons[i]; });
  }
  S.ai = out.source;
  if (S.view === "new" && S.result === result) renderResult(true);
}

// ------------------------------------------------------------------ RESULT
function curveWindow(r) {
  const rec = r.recommendation;
  const lo = Math.max(r.curve[0].price, Math.min(rec.break_even_price * 0.9, rec.entry_price * 0.85), (r.market.price_p10 || 0) * 0.7);
  const hi = Math.max((r.market.price_p90 || rec.entry_price) * 1.3, rec.entry_price * 1.3, ...Object.values(r.modes).map(m => m.price * 1.1));
  const pts = r.curve.filter(c => c.price >= lo && c.price <= hi);
  return pts.length > 3 ? pts : r.curve;
}
function zoneOf(p, best, entry) {
  if (p.profit_per_order < 0) return ["bad", "Loses money on every order"];
  if (p.total_profit >= best * 0.92) return ["good", "Sweet spot"];
  if (p.total_profit < 0) return ["bad", "Unsold stock costs more than you earn"];
  return p.price < entry ? ["warn", "Sells faster, earns less"] : ["warn", "Sells slower, earns less"];
}
function renderResult(keepScroll = false) {
  const r = S.result, rec = r.recommendation, ex = r.explanation;
  const y = window.scrollY;
  const pts = curveWindow(r);
  const best = Math.max(...pts.map(p => p.total_profit));
  const price = S.slider ?? rec.entry_price;
  const cur = pts.reduce((a, b) => Math.abs(b.price - price) < Math.abs(a.price - price) ? b : a, pts[0]);
  const [zc, zt] = zoneOf(cur, best, rec.entry_price);
  const period = rec.sell_by ? `by ${shortDate(rec.sell_by)}` : `in ${rec.horizon_days} days`;
  const steady = rec.steady_price && rec.steady_price !== rec.entry_price;
  const G = S.meta.modes.find(m => m.value === rec.mode);
  const L = S.lang === "hi";
  $("#view").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin:6px 0 12px">
      <button class="btn ghost" id="r-edit" style="padding:8px 12px">${icon("back")}Edit</button>
      <div class="lang"><button data-lang="en" class="${!L ? "on" : ""}">English</button><button data-lang="hi" class="${L ? "on" : ""}">हिंदी</button></div>
    </div>
    <div class="card price-hero">
      <div class="k">${L ? "सुझाई गई कीमत" : "SELL AT"}</div>
      <div class="p">${inr(rec.entry_price)}</div>
      ${rec.suggested_mrp > rec.entry_price ? `<div class="mrp">Show MRP <s>${inr(rec.suggested_mrp)}</s> · <b>${rec.discount_shown_pct}% off</b></div>` : ""}
      <div class="verdict">${icon("check")}${esc(G ? G.label : "")} · ${L ? "सबसे सही कीमत" : "best price for your goal"}</div>
      <p class="headline">${esc(tr(ex.summary))}</p>
      ${S.ai === "loading" ? `<div class="ai-note" style="margin-top:8px">${icon("spark")}Writing a clearer explanation…</div>` : S.ai === "ai" ? `<div class="ai-note" style="margin-top:8px">${icon("spark")}AI-written · numbers checked</div>` : ""}
      <div class="trio">
        <div><div class="v">${num(rec.orders_per_day, 1)}</div><div class="k">orders a day</div></div>
        <div><div class="v">${inr(rec.profit_per_order)}</div><div class="k">profit per order</div></div>
        <div><div class="v">${inr(rec.total_profit)}</div><div class="k">profit ${period}</div></div>
      </div>
    </div>
    ${ex.warnings.length ? ex.warnings.map(x => `<div class="warn-card">${esc(tr(x))}</div>`).join("") : ""}

    <h2>Try your own price <small>drag the circle</small></h2>
    <div class="card try">
      <div class="readout"><div class="tp" id="t-price">${inr(cur.price)}</div><span class="zone ${zc}" id="t-zone">${zt}</span></div>
      <svg class="curve" id="t-curve" viewBox="0 0 300 86" preserveAspectRatio="none" aria-hidden="true"></svg>
      <input type="range" class="slider" id="t-range" min="${pts[0].price}" max="${pts[pts.length - 1].price}" step="10" value="${cur.price}" aria-label="Try a price">
      <div class="range-k"><span>${inr(pts[0].price)}</span><span>${inr(pts[pts.length - 1].price)}</span></div>
      <div class="row">
        <div><div class="v" id="t-opd">${num(cur.orders_per_day, 1)}</div><div class="k">orders a day</div></div>
        <div><div class="v" id="t-ppo">${inr(cur.profit_per_order)}</div><div class="k">per order</div></div>
        <div><div class="v" id="t-tot">${inr(cur.total_profit)}</div><div class="k">profit ${period}</div></div>
      </div>
      <div style="margin-top:10px;text-align:right"><button class="reset" id="t-reset"${cur.price === rec.entry_price ? " hidden" : ""}>Back to ${inr(rec.entry_price)}</button></div>
    </div>

    <h2>Why this price</h2>
    <div class="card"><div class="reasons" style="margin:0">${ex.reasons.map(rs => `<div class="reason"><div class="ic ${esc(rs.tone)}">${icon(RICON[rs.icon] || "info")}</div>
      <div><div class="t" style="display:flex;justify-content:space-between;gap:8px">${esc(tr(rs.title))}<span class="muted" style="font-weight:600">${esc(rs.effect)}</span></div>
      <div class="x">${esc(tr(rs.text))}</div></div></div>`).join("")}</div></div>

    <h2>Your price plan</h2>
    <div class="card"><div class="journey">
      <div class="on">Launch<b>${inr(rec.entry_price)}</b></div>
      <div>${steady ? "After 20–25 reviews" : "After reviews"}<b>${steady ? inr(rec.steady_price) : "Hold"}</b></div>
      <div class="floor">Never below<b>${inr(rec.break_even_price)}</b></div></div></div>

    ${ex.tips.length ? `<h2>Sell more</h2><div class="card">${ex.tips.map(t => `<div class="tip">${icon("spark")}<span>${esc(tr(t))}</span></div>`).join("")}</div>` : ""}

    <div style="text-align:center;margin-top:14px"><button class="btn link" id="r-new">Price another kurti</button></div>
    <div class="result-foot">
      ${S.listed ? `<button class="btn dark block" id="r-see">${icon("check")}Listed · see it in My kurtis</button>`
        : `<button class="btn primary block" id="r-list">List at ${inr(cur.price)}${S.wiz.colors.length > 1 ? ` · ${S.wiz.colors.length} colours` : ""}</button>`}
    </div>`;
  drawCurve(pts, best, cur, rec);
  bindResult(pts, best, rec, period);
  if (keepScroll) window.scrollTo(0, y);
}
function drawCurve(pts, best, cur, rec) {
  const svg = $("#t-curve");
  const W = 300, H = 86, pad = 6;
  const vals = pts.map(p => p.total_profit);
  const lo = Math.min(0, ...vals), hi = Math.max(1, ...vals);
  const x = p => (p - pts[0].price) / (pts[pts.length - 1].price - pts[0].price || 1) * W;
  const y = v => H - pad - (v - lo) / (hi - lo || 1) * (H - 2 * pad);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.total_profit).toFixed(1)}`).join(" ");
  const base = y(Math.max(lo, 0));
  const recPt = pts.find(p => p.price === rec.entry_price);
  svg.innerHTML = `<defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d6246e" stop-opacity=".22"/><stop offset="1" stop-color="#d6246e" stop-opacity="0"/></linearGradient></defs>
    ${lo < 0 ? `<line x1="0" x2="${W}" y1="${base}" y2="${base}" stroke="#e3d8d4" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>` : ""}
    <path d="${line} L${W},${base} L0,${base} Z" fill="url(#g1)"/>
    <path d="${line}" fill="none" stroke="#d6246e" stroke-width="2.2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    ${recPt ? `<circle cx="${x(recPt.price)}" cy="${y(recPt.total_profit)}" r="3.5" fill="#3b1033"/>` : ""}
    <line id="t-mark" x1="${x(cur.price)}" x2="${x(cur.price)}" y1="0" y2="${H}" stroke="#3b1033" stroke-width="1.2" vector-effect="non-scaling-stroke" opacity=".5"/>`;
  // colour the slider track by zone
  const stops = pts.map(p => { const z = zoneOf(p, best, rec.entry_price)[0]; const c = z === "good" ? "#0f8a4f" : z === "warn" ? "#e3a232" : "#e06a5f"; const pc = (x(p.price) / W * 100).toFixed(1); return `${c} ${pc}%`; });
  $("#t-range").style.setProperty("--track", `linear-gradient(90deg, ${stops.join(", ")})`);
}
function bindResult(pts, best, rec, period) {
  const range = $("#t-range");
  range.addEventListener("input", () => {
    const p = pts.reduce((a, b) => Math.abs(b.price - range.value) < Math.abs(a.price - range.value) ? b : a, pts[0]);
    S.slider = p.price;
    const [zc, zt] = zoneOf(p, best, rec.entry_price);
    $("#t-price").textContent = inr(p.price);
    const z = $("#t-zone"); z.className = `zone ${zc}`; z.textContent = zt;
    $("#t-opd").textContent = num(p.orders_per_day, 1);
    $("#t-ppo").textContent = inr(p.profit_per_order);
    $("#t-tot").textContent = inr(p.total_profit);
    const W = 300, xm = (p.price - pts[0].price) / (pts[pts.length - 1].price - pts[0].price || 1) * W;
    $("#t-mark").setAttribute("x1", xm); $("#t-mark").setAttribute("x2", xm);
    $("#t-reset").hidden = p.price === rec.entry_price;
    const lb = $("#r-list");
    if (lb) lb.textContent = `List at ${inr(p.price)}${S.wiz.colors.length > 1 ? ` · ${S.wiz.colors.length} colours` : ""}`;
  });
  $("#t-reset").addEventListener("click", () => { S.slider = null; renderResult(true); });
  $$(".lang button").forEach(b => b.addEventListener("click", () => { S.lang = b.dataset.lang; renderResult(true); }));
  $("#r-edit").addEventListener("click", () => { S.wiz.step = 1; renderWizard(); window.scrollTo(0, 0); });
  $("#r-new").addEventListener("click", () => { newWizard(); renderWizard(); window.scrollTo(0, 0); });
  const see = $("#r-see");
  if (see) see.addEventListener("click", () => go("shelf"));
  const lb = $("#r-list");
  if (lb) lb.addEventListener("click", async () => {
    const price = S.slider ?? rec.entry_price;
    lb.disabled = true; lb.textContent = "Listing…";
    try {
      const out = await api("/api/list", { ...S.lastBody, price, mrp: rec.suggested_mrp > price ? rec.suggested_mrp : "", recommendation_id: S.result.recommendation_id });
      S.listed = out; S.listings = null;
      try { S.meta = await api("/api/meta"); } catch (e) { /* cosmetic */ }
      toast(`Listed ${out.product_ids.length} ${out.product_ids.length > 1 ? "listings" : "listing"} at ${inr(out.price)}`);
      renderResult(true);
    } catch (e) {
      lb.disabled = false; lb.textContent = `List at ${inr(price)}`;
      toast(e.message);
    }
  });
}

boot();
