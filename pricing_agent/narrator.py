"""
AI-written explanations with a safety net.

The pricing maths never depends on the LLM. The LLM only rewrites the template
explanations (which are built from computed numbers) into fresher, plainer
language. Its output is accepted only if:
  * it has exactly the expected structure (same number of reasons / tips), and
  * every number it mentions comes from the facts we gave it (rounding allowed).
Anything else -> the template text is used, so a bad or missing API never
shows the seller a wrong figure.
"""
import hashlib
import json
import re
import threading
from collections import OrderedDict

from .llm import LLMClient, LLMError

MAX_FIELD = 700
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

STYLE = """You write price explanations for small sellers on Meesho, India's value marketplace. Many readers run
small shops in tier-2 and tier-3 towns and read on a phone.

Rewrite the draft explanations you are given so they read like a helpful, experienced friend - clear, warm, specific
and not repetitive. Keep each point short (1-3 sentences). Lead with what matters to the seller's earnings.

Hard rules:
- Use ONLY the facts provided. Never invent numbers, percentages, dates, festivals, competitors or claims.
- Every number you write must appear in the facts (you may round, e.g. 2.84 -> 2.8). Write amounts as ₹349.
- Keep the same meaning and the same order as the drafts; do not merge, drop or add points.
- Avoid jargon such as "elasticity", "hedonic", "conversion rate optimisation".
- Reply with JSON only, matching the requested shape exactly."""


def _numbers(text):
    return [float(n.replace(",", "")) for n in NUM_RE.findall(str(text).translate(DEVANAGARI_DIGITS))]


def _allowed(facts):
    vals = set(_numbers(json.dumps(facts, ensure_ascii=False)))
    return vals | set(float(i) for i in range(0, 11))


def _number_ok(x, allowed):
    return any(abs(x - f) <= max(0.51, 0.012 * abs(f)) for f in allowed)


def check_numbers(texts, facts):
    """Return the first number in texts that is not supported by the facts, or None."""
    allowed = _allowed(facts)
    for t in texts:
        for x in _numbers(t):
            if not _number_ok(x, allowed):
                return x
    return None


def _text(v):
    return isinstance(v, str) and 0 < len(v.strip()) <= MAX_FIELD


class Narrator:
    def __init__(self, llm: LLMClient = None):
        self.llm = llm or LLMClient()
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def info(self):
        return self.llm.info()

    # ------------------------------------------------------------------ cache
    def _cached(self, kind, facts, build):
        key = hashlib.sha256(f"{kind}|{self.llm.model}|{json.dumps(facts, sort_keys=True, ensure_ascii=False)}"
                             .encode("utf-8")).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        out = build()
        if out.get("source") == "ai":
            with self._lock:
                self._cache[key] = out
                while len(self._cache) > 300:
                    self._cache.popitem(last=False)
        return out

    # ------------------------------------------------------------------ new product page
    def narrate_pricing(self, result: dict) -> dict:
        ex = result["explanation"]
        rec = result["recommendation"]
        mkt = result["market"]
        facts = {
            "product": {k: v["label"] for k, v in result["attributes"].items()},
            "title": result["input"].get("title") or None,
            "seller": (result.get("seller") or {}).get("seller_name"),
            "goal": rec["mode_label"],
            "launch_price": rec["entry_price"], "suggested_mrp": rec["suggested_mrp"],
            "discount_shown_pct": rec["discount_shown_pct"], "break_even_price": rec["break_even_price"],
            "price_after_reviews": rec["steady_price"], "orders_per_day": rec["orders_per_day"],
            "profit_per_order": rec["profit_per_order"], "margin_pct": rec["margin_pct"],
            "profit_in_horizon": rec["total_profit"], "horizon_days": rec["horizon_days"],
            "days_to_sell_stock": rec["days_to_sell_out"], "units_in_stock": rec["inventory"],
            "market_middle_range": [mkt["price_p25"], mkt["price_p75"]],
            "best_sellers_price": mkt["sales_weighted_median"], "comparable_listings": mkt["n_comparable"],
            "reasons": [{"topic": r["title"]["en"], "effect": r["effect"], "draft": r["text"]["en"]} for r in ex["reasons"]],
            "tips": [t["en"] for t in ex["tips"]],
            "draft_headline": ex["headline"]["en"], "draft_summary": ex["summary"]["en"],
        }
        n_r, n_t = len(ex["reasons"]), len(ex["tips"])
        shape = ('{"headline": {"en": str, "hi": str}, "summary": {"en": str, "hi": str}, '
                 f'"reasons": [{n_r} items of {{"en": str, "hi": str}}], "tips": [{n_t} items of {{"en": str, "hi": str}}]}}')
        prompt = (f"Facts (JSON):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
                  "Write: a one-line headline, a 2-3 sentence summary of the recommendation, one rewritten point per draft "
                  "reason and one per tip. Give each in English (en) and in simple everyday Hindi in Devanagari (hi); common "
                  "words like price, order, stock, MRP may stay in English. Use Western digits in both.\n\n"
                  f"JSON shape: {shape}")

        def build():
            try:
                out = self.llm.complete_json(STYLE, prompt)
                pair = lambda v: isinstance(v, dict) and _text(v.get("en")) and _text(v.get("hi"))
                if not (pair(out.get("headline")) and pair(out.get("summary"))):
                    raise LLMError("missing headline/summary")
                reasons, tips = out.get("reasons"), out.get("tips", [])
                if not (isinstance(reasons, list) and len(reasons) == n_r and all(pair(r) for r in reasons)):
                    raise LLMError("reasons do not match")
                if not (isinstance(tips, list) and len(tips) == n_t and all(pair(t) for t in tips)):
                    raise LLMError("tips do not match")
                texts = [out["headline"]["en"], out["headline"]["hi"], out["summary"]["en"], out["summary"]["hi"]]
                texts += [x[k] for x in reasons + tips for k in ("en", "hi")]
                bad = check_numbers(texts, facts)
                if bad is not None:
                    raise LLMError(f"unsupported number {bad:g}")
                return {"source": "ai", "provider": self.llm.provider, "headline": out["headline"],
                        "summary": out["summary"], "reasons": [{"en": r["en"], "hi": r["hi"]} for r in reasons],
                        "tips": [{"en": t["en"], "hi": t["hi"]} for t in tips]}
            except LLMError as e:
                return {"source": "template", "why": str(e)[:200]}

        return self._cached("pricing", facts, build)

    # ------------------------------------------------------------------ my listings page
    def narrate_listing(self, v: dict, design: str, seller: str, goal: str) -> dict:
        n, w = v["now"], v["recommended"]
        facts = {
            "seller": seller, "goal": goal, "design": design, "colour": v["color"], "stage": v["stage"],
            "action": v["action_label"], "current_price": v["current_price"], "recommended_price": v["recommended_price"],
            "change_pct": v["change_pct"], "target_price": v["target_price"], "stock": v["stock"],
            "days_of_stock": v["days_of_cover"], "orders_per_day_last_4_weeks": v["orders_per_day_28d"],
            "trend_vs_previous_month_pct": v["trend_pct"], "click_through_pct": v["ctr_pct"],
            "market_click_through_pct": v["segment_ctr_pct"], "conversion_pct": v["cvr_pct"],
            "market_conversion_pct": v["segment_cvr_pct"], "rating": v["rating"], "reviews": v["reviews"],
            "break_even": v["break_even"], "market_range": [v["market_p25"], v["market_p75"]],
            "next_30_days_now": {"orders_per_day": n["orders_per_day"], "profit_per_order": n["profit_per_order"],
                                 "net_profit": n["profit_30d"], "days_to_sell_stock": n["days_to_clear"]},
            "next_30_days_recommended": {"orders_per_day": w["orders_per_day"], "profit_per_order": w["profit_per_order"],
                                         "net_profit": w["profit_30d"], "days_to_sell_stock": w["days_to_clear"]},
            "draft_points": [r["text"] for r in v["reasons"]],
        }
        n_r = len(v["reasons"])
        prompt = (f"Facts (JSON):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
                  "Write a one or two sentence 'summary' telling the seller what to do with this listing's price and "
                  f"why it is best for their business, then rewrite each of the {n_r} draft points in English.\n\n"
                  f'JSON shape: {{"summary": str, "points": [{n_r} strings]}}')

        def build():
            try:
                out = self.llm.complete_json(STYLE, prompt)
                pts = out.get("points")
                if not (_text(out.get("summary")) and isinstance(pts, list) and len(pts) == n_r and all(_text(p) for p in pts)):
                    raise LLMError("points do not match")
                bad = check_numbers([out["summary"], *pts], facts)
                if bad is not None:
                    raise LLMError(f"unsupported number {bad:g}")
                return {"source": "ai", "provider": self.llm.provider, "summary": out["summary"], "points": pts}
            except LLMError as e:
                return {"source": "template", "why": str(e)[:200]}

        return self._cached("listing", facts, build)
