"use strict";
/* Shared visual building blocks: line icons, kurti illustrations, price ladder, money bar. */

const ICON_PATHS = {
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>', down: '<path d="M12 5v14M19 12l-7 7-7-7"/>', flat: '<path d="M5 12h14"/>',
  box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>', trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  check: '<path d="M4 12.5l5 5L20 6.5"/>', rupee: '<path d="M6 4h12M6 9h12M13.5 20L7 13h3a4.5 4.5 0 0 0 0-9"/>',
  gift: '<path d="M4 11h16v10H4zM2 7h20v4H2zM12 7v14M12 7S9 2 6.5 4.5 12 7 12 7s3-5 5.5-2.5S12 7 12 7"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>', store: '<path d="M4 10v10h16V10M3 10l2-6h14l2 6M9 20v-6h6v6"/>',
  return: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>', eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.5 12h11L21 7H6"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5 1-1.5 2-1.5h2a4 4 0 0 0 4-4c0-4.5-4-8-9-8z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  camera: '<path d="M3 8h4l2-3h6l2 3h4v12H3z"/><circle cx="12" cy="13" r="4"/>', target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>', scale: '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  truck: '<path d="M2 6h11v10H2zM13 10h4l3 3v3h-7z"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>', tax: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  wallet: '<path d="M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a1 1 0 0 1-1-1z"/><path d="M3 7V5a1 1 0 0 1 1-1h12v3"/><circle cx="16.5" cy="13.5" r="1.2"/>',
  percent: '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>', user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  shirt: '<path d="M8 3l4 3 4-3 5 4-3 3v11H6V10L3 7z"/>', warn: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>', rocket: '<path d="M5 15c-2 2-2 5-2 5s3 0 5-2M9 11l4 4M14 4c3 0 6 3 6 6l-7 7-6-6z"/><circle cx="15" cy="9" r="1.5"/>',
  sale: '<path d="M3 12V4h8l10 10-8 8z"/><path d="M9 15l6-6"/><circle cx="9.5" cy="10" r=".8"/><circle cx="14" cy="14.5" r=".8"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>', chevron: '<path d="M9 6l6 6-6 6"/>',
};
function icon(name, cls = "i") {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name] || ICON_PATHS.info}</svg>`;
}

const KURTI_COLORS = { indigo: "#3f4a9a", maroon: "#7a1f2b", mustard: "#d4a017", white: "#f5f3ee", "off white": "#efe8d8", yellow: "#f2d33b",
  "sky blue": "#8cc8ec", peach: "#f6b99a", red: "#d33a3a", green: "#3f8f4f", grey: "#9a9aa0", gray: "#9a9aa0", black: "#2a2a2e",
  wine: "#6e1f3a", teal: "#1f8a8a", pink: "#f07aa8", "navy blue": "#23305e", lavender: "#b9a6e0", orange: "#f08a2c", magenta: "#c0288c",
  blue: "#3a6fd8", beige: "#e3d3b5", brown: "#7a5230", rust: "#b7472a", olive: "#6b7a2f", cream: "#f4ead2", purple: "#6b3fa0", gold: "#c9a227" };
function colorOf(name) { return KURTI_COLORS[String(name || "").toLowerCase()] || null; }
/** First colour word found in a title, e.g. "Navy Blue Rayon Kurti" -> "navy blue". */
function colorFromTitle(title) {
  const t = String(title || "").toLowerCase();
  let best = null;
  for (const c of Object.keys(KURTI_COLORS)) if (t.startsWith(c + " ") && (!best || c.length > best.length)) best = c;
  return best;
}
function shadeHex(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const f = v => Math.max(0, Math.min(255, Math.round(v + (amt > 0 ? (255 - v) * amt : v * amt))));
  return "#" + [f(n >> 16), f((n >> 8) & 255), f(n & 255)].map(v => v.toString(16).padStart(2, "0")).join("");
}
/** Small kurti illustration in the product's colour, with a motif for the work type. */
function kurtiSvg(color, pattern = "", cls = "kurti") {
  const c = colorOf(color) || "#c98aa6", light = shadeHex(c, 0.45), dark = shadeHex(c, -0.25);
  const pt = String(pattern || "").toLowerCase();
  const motif = /block|print/.test(pt)
    ? `<g fill="${light}" opacity=".85"><circle cx="19" cy="38" r="2"/><circle cx="31" cy="38" r="2"/><circle cx="25" cy="47" r="2"/><circle cx="19" cy="56" r="2"/><circle cx="31" cy="56" r="2"/></g>`
    : /embroid|chikan|mirror|sequin/.test(pt)
      ? `<path d="M20 22 Q25 30 30 22" stroke="${light}" stroke-width="1.6" fill="none"/><g fill="${light}"><circle cx="25" cy="34" r="1.6"/><circle cx="21" cy="40" r="1.3"/><circle cx="29" cy="40" r="1.3"/></g>`
      : `<path d="M15 50h20" stroke="${light}" stroke-width="1.6"/>`;
  return `<svg class="${cls}" viewBox="0 0 50 62" aria-hidden="true"><path d="M17 3l8 5 8-5 12 8-5 7-3-2v44H13V16l-3 2-5-7z" fill="${c}" stroke="${dark}" stroke-width=".8"/>
    <path d="M21 5.5l4 8 4-8" fill="none" stroke="${dark}" stroke-width="1"/>${motif}</svg>`;
}
function thumb(color, pattern, size = "") {
  const c = colorOf(color) || "#c98aa6";
  return `<span class="thumb ${size}" style="background:${shadeHex(c, 0.84)}">${kurtiSvg(color, pattern)}</span>`;
}

/** Horizontal price ladder: market range, middle 50%, best-seller price, break-even and your price. */
function priceLadder({ p10, p25, p75, p90, best, breakEven, you, youLabel = "You", shop }) {
  const lo = Math.min(p10, breakEven, you, shop || Infinity) * 0.94;
  const hi = Math.max(p90, you, shop || 0) * 1.06;
  const x = v => ((v - lo) / (hi - lo) * 100).toFixed(2) + "%";
  const inr = v => "₹" + Math.round(v).toLocaleString("en-IN");
  const mk = (v, cls, label, ic) => `<div class="lad-mk ${cls}" style="left:${x(v)}"><span class="lad-pin"></span><span class="lad-lab">${ic ? icon(ic) : ""}${label}<b>${inr(v)}</b></span></div>`;
  return `<div class="ladder" role="img" aria-label="Your price ${inr(you)} against the market ${inr(p25)} to ${inr(p75)}">
    <div class="lad-track"><div class="lad-range" style="left:${x(p10)};width:calc(${x(p90)} - ${x(p10)})"></div>
      <div class="lad-mid" style="left:${x(p25)};width:calc(${x(p75)} - ${x(p25)})"></div></div>
    ${mk(breakEven, "be", "Break-even", "shield")}
    ${best ? `<div class="lad-dot" style="left:${x(best)}" title="Best-sellers ${inr(best)}"></div>` : ""}
    ${shop ? mk(shop, "shop", "Shop", "store") : ""}
    ${mk(you, "you", youLabel, "tag")}
    <div class="lad-keys"><span><i class="k-mid"></i>Most similar kurtis ${inr(p25)}–${inr(p75)}</span>${best ? `<span><i class="k-dot"></i>Best-sellers ${inr(best)}</span>` : ""}</div>
  </div>`;
}

/** Where each rupee of price goes, as one stacked bar. */
function moneyBar(breakdown, price) {
  const parts = [];
  const byIcon = ic => breakdown.find(l => l.icon === ic && !l.total);
  const profit = breakdown.find(l => l.total);
  // the bar splits the money actually received (price minus unpaid orders)
  const add = (label, amt, cls, ic) => { if (amt > 0.5) parts.push({ label, amt, cls, ic }); };
  add("Your profit", Math.max(0, profit.amount), "m-profit", "wallet");
  add("Product cost", -(byIcon("tag") || { amount: 0 }).amount, "m-cost", "tag");
  add("Return shipping", -(byIcon("return") || { amount: 0 }).amount, "m-ship", "return");
  add("GST", -(byIcon("tax") || { amount: 0 }).amount, "m-tax", "tax");
  add("Packaging", -(byIcon("box") || { amount: 0 }).amount, "m-pack", "box");
  add("Transit loss", -(byIcon("truck") || { amount: 0 }).amount, "m-transit", "truck");
  const total = parts.reduce((s, p) => s + p.amt, 0) || 1;
  const inr = v => "₹" + Math.round(v).toLocaleString("en-IN");
  return `<div class="mbar">${parts.map(p => `<span class="${p.cls}" style="width:${(p.amt / total * 100).toFixed(1)}%" title="${p.label} ${inr(p.amt)}"></span>`).join("")}</div>
    <div class="mbar-keys">${parts.map(p => `<span><i class="${p.cls}"></i>${icon(p.ic)}${p.label} <b>${inr(p.amt)}</b></span>`).join("")}</div>`;
}

/** First sentence, for short-by-default text. */
function firstSentence(t) {
  const m = String(t || "").match(/^.*?[.!?।](\s|$)/);
  return m ? m[0].trim() : String(t || "");
}
