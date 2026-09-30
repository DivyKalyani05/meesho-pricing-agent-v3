"""
The pricing agent: seller inputs + market intelligence -> entry price + explanation.

Pipeline
  1. validate & enrich inputs (attributes from text, package size, COGS from offline margin)
  2. market scan: comparable listings, fair price, crowding, returns, complaints
  3. demand model: price sensitivity (learnt), demand level, season/festival, seller CTR, photos
  4. unit economics per order at every candidate price
  5. optimise for the seller's goal (mode) under inventory / expiry constraints
  6. counterfactuals -> plain-language reasons
"""
import json
import math
from collections import OrderedDict
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from . import config, features, signals
from .explain import build_explanation
from .market import Market
from .stats import clip, percentile


class InputError(ValueError):
    pass


# ---------------------------------------------------------------- input handling
def _num(d, key, lo=None, hi=None, required=False, integer=False, label=None):
    label = label or key.replace("_", " ")
    v = d.get(key)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        if required:
            raise InputError(f"Please enter {label}.")
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise InputError(f"{label.capitalize()} must be a number.")
    if math.isnan(v) or math.isinf(v):
        raise InputError(f"{label.capitalize()} must be a number.")
    if lo is not None and v < lo:
        raise InputError(f"{label.capitalize()} must be at least {lo:g}.")
    if hi is not None and v > hi:
        raise InputError(f"{label.capitalize()} must be at most {hi:g}.")
    return int(round(v)) if integer else v


def _date(d, key, label):
    v = d.get(key)
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise InputError(f"{label} must be a valid date (YYYY-MM-DD).")


def clean_input(raw: dict, market: Market) -> dict:
    if not isinstance(raw, dict):
        raise InputError("Invalid request.")
    text = f"{raw.get('title', '')} {raw.get('description', '')}"
    detected = features.detect_attributes(text)
    attrs = {}
    choices = {"product_type": config.PRODUCT_TYPES, "fabric": config.FABRICS, "pattern": config.PATTERNS,
               "sleeve": config.SLEEVES, "length": config.LENGTHS, "occasion": config.OCCASIONS}
    defaults = {"product_type": "kurti", "fabric": "cotton", "pattern": "printed", "sleeve": "three_quarter",
                "length": "knee", "occasion": "daily"}
    sources = {}
    for k, allowed in choices.items():
        v = raw.get(k)
        if v in (None, "", "auto"):
            v = detected.get(k, defaults[k])
            sources[k] = "detected" if k in detected else "default"
        elif v not in allowed:
            raise InputError(f"Unknown {k.replace('_', ' ')}: {v}")
        else:
            sources[k] = "seller"
        attrs[k] = v

    seller_id = raw.get("seller_id")
    if seller_id in ("", None, "none"):
        seller_id = None
    else:
        try:
            seller_id = int(seller_id)
        except (TypeError, ValueError):
            raise InputError("Invalid seller.")
        if seller_id not in market.sellers:
            raise InputError("Seller not found.")

    offline_price = _num(raw, "offline_price", lo=1, hi=100000, label="offline selling price")
    offline_margin = _num(raw, "offline_margin_pct", lo=0, hi=95, label="offline margin %")
    cogs = _num(raw, "cogs", lo=1, hi=50000, label="cost of goods (COGS)")
    cogs_source = "seller"
    if cogs is None:
        if offline_price and offline_margin is not None:
            cogs = offline_price * (1 - offline_margin / 100.0)
            cogs_source = "derived from offline price and margin"
        else:
            raise InputError("Please enter your cost per piece (COGS), or your offline price and offline margin.")
    inventory = _num(raw, "inventory", lo=1, hi=1_000_000, required=True, integer=True, label="inventory (units)")
    horizon = _num(raw, "horizon_days", lo=7, hi=180, integer=True, label="planning horizon (days)") or 30
    n_photos = _num(raw, "n_photos", lo=0, hi=20, integer=True, label="number of photos")
    n_photos = 0 if n_photos is None else n_photos

    launch = _date(raw, "launch_date", "Launch date") or (market.snapshot + timedelta(days=1))
    if launch < market.snapshot - timedelta(days=1) or launch > market.snapshot + timedelta(days=400):
        raise InputError("Launch date must be between today and about one year ahead.")
    expiry = _date(raw, "expiry_date", "Sell-by / expiry date")
    if expiry is not None and expiry <= launch:
        raise InputError("Sell-by / expiry date must be after the launch date.")

    mode = raw.get("mode") or "balanced"
    if mode not in config.MODES:
        raise InputError(f"Unknown pricing goal: {mode}")
    package_size = raw.get("package_size")
    if package_size in ("", "auto", None):
        package_size = None
    elif package_size not in config.PACKAGING:
        raise InputError("Package size must be S, M or L.")

    return {
        "seller_id": seller_id, "title": (raw.get("title") or "").strip()[:200],
        "description": (raw.get("description") or "").strip()[:2000],
        "attrs": attrs, "attr_sources": sources, "cogs": float(cogs), "cogs_source": cogs_source,
        "offline_price": offline_price, "offline_margin_pct": offline_margin, "inventory": inventory,
        "horizon_days": horizon, "launch_date": launch, "expiry_date": expiry, "mode": mode,
        "n_photos": n_photos, "package_size": package_size,
        "limited_stock": str(raw.get("limited_stock", "")).lower() in ("1", "true", "yes", "on"),
    }


# ---------------------------------------------------------------- economics
@dataclass
class Economics:
    """
    Expected money per order PLACED. Out of every order:
      transit  lost / damaged on the way   -> no revenue, piece lost
      ret      delivered then returned     -> no revenue, seller pays forward + reverse shipping
      rto      refused at the door (RTO)   -> no revenue, no charges, piece comes back
      kept     the rest                    -> revenue, no shipping charge to the seller
    Return legs can also be lost in transit.
    """
    cogs: float
    ret: float          # customer return rate
    rto: float          # return-to-origin rate
    packaging: float
    fwd: float
    rev: float
    transit: float = 0.0

    @property
    def kept(self):
        return 1.0 - self.transit - self.ret - self.rto

    @property
    def gst_share(self):
        return config.GST_RATE / (1 + config.GST_RATE)

    @property
    def net_factor(self):
        return self.kept * (1 - self.gst_share) * (1 - config.PLATFORM_COMMISSION_PCT)

    @property
    def product_cost(self):
        """Pieces that leave for good in the normal course: kept + damaged returns."""
        return self.cogs * (self.kept + self.ret * config.DAMAGED_RETURN_SHARE)

    @property
    def transit_cost(self):
        """Pieces lost in transit: forward shipments, plus return and RTO legs."""
        return self.cogs * self.transit * (1 + self.ret + self.rto)

    @property
    def shipping_cost(self):
        fwd_kept = self.kept * self.fwd if config.SELLER_PAYS_FORWARD_ON_KEPT else 0.0
        return fwd_kept + self.ret * (self.fwd + self.rev) + self.rto * config.RTO_CHARGE

    @property
    def cost_per_order(self):
        return self.product_cost + self.transit_cost + self.packaging + self.shipping_cost

    @property
    def units_per_order(self):
        """Stock that leaves for good per order."""
        return self.kept + self.ret * config.DAMAGED_RETURN_SHARE + self.transit * (1 + self.ret + self.rto)

    def profit(self, p):
        return p * self.net_factor - self.cost_per_order

    def break_even(self):
        return self.cost_per_order / self.net_factor

    def margin(self, p):
        collected = self.kept * p
        return self.profit(p) / collected if collected > 0 else 0.0

    def breakdown(self, p):
        k = self.kept
        lines = [
            ("Price", p, "rupee"),
            (f"Not paid: returns, RTO & lost in transit ({1 - k:.0%} of orders)", -(1 - k) * p, "percent"),
            (f"GST ({config.GST_RATE:.0%} of price)", -k * p * self.gst_share, "tax"),
            ("Product cost", -self.product_cost, "tag"),
            ("Packaging", -self.packaging, "box"),
            (f"Return shipping, both ways ({self.ret:.0%} returns)", -self.ret * (self.fwd + self.rev), "return"),
            (f"Lost in transit ({self.transit:.1%} of shipments)", -self.transit_cost, "truck"),
            (f"RTO ({self.rto:.0%} not delivered) - no charge", -self.rto * config.RTO_CHARGE, "home"),
        ]
        if config.SELLER_PAYS_FORWARD_ON_KEPT:
            lines.insert(4, ("Delivery on kept orders", -k * self.fwd, "truck"))
        if config.PLATFORM_COMMISSION_PCT:
            lines.insert(2, ("Platform commission", -k * p * (1 - self.gst_share) * config.PLATFORM_COMMISSION_PCT, "tax"))
        return [{"label": l, "amount": round(v, 1), "icon": i} for l, v, i in lines] + \
               [{"label": "Profit per order placed", "amount": round(self.profit(p), 1), "icon": "wallet", "total": True},
                {"label": "Profit per kept order", "amount": round(self.profit(p) / k, 1) if k > 0 else 0.0,
                 "icon": "check", "note": True}]


# ---------------------------------------------------------------- demand scenario
@dataclass
class Scenario:
    fair: float            # attribute-based fair price on Meesho
    level: float           # orders/day at fair price for a typical established listing, season = 1
    b: float               # price sensitivity at historical season
    window_mult: float     # season x festival over the selling window
    hist_mult: float       # season x festival over the training window
    crowd_adj: float       # extra price sensitivity from crowding
    seller_factor: float   # seller CTR vs category
    photo_factor: float    # listing photos vs average
    new_listing: bool
    new_factor: float      # demand of a brand-new listing vs established

    @staticmethod
    def _season_adj(m):
        return clip(1 - 0.35 * (m - 1), 0.7, 1.15)

    @property
    def b_eff(self):
        b = self.b * self._season_adj(self.window_mult) / self._season_adj(self.hist_mult) * self.crowd_adj
        return b * (config.NEW_LISTING_SENSITIVITY_BOOST if self.new_listing else 1.0)

    def demand(self, p):
        base = self.level * self.window_mult * self.seller_factor * self.photo_factor
        if self.new_listing:
            base *= self.new_factor
        return base * math.exp(-self.b_eff * (p / self.fair - 1.0))


def price_grid(lo, hi):
    start = int(math.floor(lo / 10.0)) * 10 + 9
    return list(range(max(49, start), int(hi) + 10, 10))


def evaluate(p, sc: Scenario, eco: Economics, inventory, horizon, has_expiry, capped=True):
    """Outcome of pricing at p. capped=False means the seller restocks, so stock never limits sales."""
    q = sc.demand(p)
    u = eco.units_per_order
    orders = min(q * horizon, inventory / u) if capped else q * horizon
    units = orders * u
    leftover = max(0.0, inventory - units)
    pi = eco.profit(p)
    penalty = leftover * eco.cogs * (1 - config.SALVAGE_SHARE_OF_COGS) if has_expiry else 0.0
    return {
        "price": p, "orders_per_day": q, "orders": orders, "units_sold": units, "leftover": leftover,
        "profit_per_order": pi, "margin": eco.margin(p), "total_profit": pi * orders - penalty,
        "writeoff": penalty, "gmv": orders * p,
        "days_to_sell_out": inventory / (q * u) if q > 0 else float("inf"),
    }


def choose(mode, rows, eco: Economics, inventory, has_expiry):
    """Pick the best candidate for the seller's goal. Returns (row, note)."""
    profitable = [r for r in rows if r["profit_per_order"] >= 1]
    if not profitable:
        return max(rows, key=lambda r: r["profit_per_order"]), "no_profitable_price"
    if mode == "max_margin":
        return max(profitable, key=lambda r: r["total_profit"]), None
    if mode == "balanced":
        ok = [r for r in profitable if r["total_profit"] > 0]
        if not ok:
            return max(profitable, key=lambda r: r["total_profit"]), None
        return max(ok, key=lambda r: math.log(r["total_profit"]) + 0.5 * math.log(max(r["orders"], 1e-9))), None
    if mode == "scale":
        ok = [r for r in profitable if r["profit_per_order"] >= config.MIN_PROFIT_PER_ORDER_SCALE
              and r["margin"] >= config.MIN_MARGIN_SCALE] or profitable
        top = max(r["orders"] for r in ok)
        near = [r for r in ok if r["orders"] >= 0.98 * top]
        return max(near, key=lambda r: r["total_profit"]), None
    if mode == "clear_inventory":
        if has_expiry:
            # below cost is acceptable if it loses less than writing the stock off
            floor = -0.5 * eco.cogs * (1 - config.SALVAGE_SHARE_OF_COGS) * eco.units_per_order
            allowed = [r for r in rows if r["profit_per_order"] >= floor]
        else:
            allowed = profitable
        clears = [r for r in allowed if r["units_sold"] >= 0.98 * inventory]
        if clears:
            return max(clears, key=lambda r: r["total_profit"]), None
        if has_expiry:
            # can't sell everything: best trade-off between selling cheap and writing stock off
            return max(allowed, key=lambda r: r["total_profit"]), "cannot_clear"
        return max(allowed, key=lambda r: (r["units_sold"], r["total_profit"])), "cannot_clear"
    raise ValueError(mode)


# ---------------------------------------------------------------- the agent
class PricingAgent:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.market = Market(db_path)
        self.recent = OrderedDict()

    def meta(self):
        demo = [{"seller_id": s["seller_id"], "name": s["seller_name"], "city": s["city"], "tier": s["tier"],
                 "listings": sum(1 for p in self.market.products if p["seller_id"] == s["seller_id"])}
                for s in self.market.sellers.values() if s["is_demo_seller"]]
        opt = lambda d: [{"value": k, "label": (v[0] if isinstance(v, tuple) else v)} for k, v in d.items()]
        return {
            "snapshot_date": self.market.snapshot.isoformat(),
            "default_launch_date": (self.market.snapshot + timedelta(days=1)).isoformat(),
            "sellers": demo,
            "options": {"product_type": opt(config.PRODUCT_TYPES), "fabric": opt(config.FABRICS),
                        "pattern": opt(config.PATTERNS), "sleeve": opt(config.SLEEVES),
                        "length": opt(config.LENGTHS), "occasion": opt(config.OCCASIONS)},
            "modes": [{"value": k, "label": v[0], "hint": v[1]} for k, v in config.MODES.items()],
            "market_size": {"listings": len(self.market.active), "sellers": len(self.market.sellers)},
        }

    def detect(self, text):
        return features.detect_attributes(text)

    # ------------------------------------------------------------------
    def recommend(self, raw: dict, save: bool = True) -> dict:
        inp = clean_input(raw, self.market)
        m = self.market
        attrs = inp["attrs"]

        # 1. package & economics inputs
        pkg = features.estimate_package(attrs["product_type"], attrs["fabric"], inp["package_size"])
        pool = m.competitors(attrs, exclude_seller=inp["seller_id"])
        fair = m.fair_price(attrs)
        summary = m.market_summary(attrs, pool, fair)
        ret, rto, ret_orders = m.return_rates(attrs, pool)
        eco = Economics(cogs=inp["cogs"], ret=ret, rto=rto, packaging=pkg["packaging_cost"],
                        fwd=pkg["shipping_forward"], rev=pkg["shipping_reverse"],
                        transit=config.TRANSIT_LOSS[attrs["product_type"]])

        # 2. demand
        fit = m.fit_demand(pool, attrs["occasion"])
        level = m.base_demand(fit, rating=4.0)
        launch, expiry = inp["launch_date"], inp["expiry_date"]
        has_expiry = expiry is not None and (expiry - launch).days <= 365
        horizon = clip((expiry - launch).days, 3, 365) if has_expiry else inp["horizon_days"]
        win = signals.window_average(launch, horizon, attrs["fabric"], attrs["occasion"])
        hist = signals.window_average(m.window_start, (m.snapshot - m.window_start).days + 1,
                                      attrs["fabric"], attrs["occasion"])
        hist_mult = hist["combined"]
        seller = m.seller_history(inp["seller_id"], attrs)
        seller_factor = seller["ctr_factor"] if seller else 1.0
        photo_factor = m.photo_factor(max(1, inp["n_photos"]))
        crowd_adj = clip(summary["crowding_index"] ** 0.15, 0.92, 1.1)
        base_sc = Scenario(fair=fair, level=level, b=fit["b"], window_mult=win["combined"], hist_mult=hist_mult,
                           crowd_adj=crowd_adj, seller_factor=seller_factor, photo_factor=photo_factor,
                           new_listing=True, new_factor=m.new_listing_factor)

        lo = min(0.45 * fair, 0.8 * eco.break_even())
        hi = max(2.0 * fair, 1.6 * eco.break_even(), (inp["offline_price"] or 0) * 1.2)
        grid = price_grid(lo, hi)
        inv = inp["inventory"]

        def is_capped(mode):
            return has_expiry or inp["limited_stock"] or mode == "clear_inventory"

        def solve(sc, mode=inp["mode"], inventory=inv):
            capped = is_capped(mode)
            rows = [evaluate(p, sc, eco, inventory, horizon, has_expiry, capped) for p in grid]
            if mode == "clear_inventory":
                # "clear fast" never prices above what the Balanced goal would charge
                ref_rows = [evaluate(p, sc, eco, inventory, horizon, has_expiry, False) for p in grid]
                ref_price = choose("balanced", ref_rows, eco, inventory, has_expiry)[0]["price"]
                rows = [r for r in rows if r["price"] <= ref_price]
            best, note = choose(mode, rows, eco, inventory, has_expiry)
            return best, note, rows

        best, note, _ = solve(base_sc)
        rows = [evaluate(p, base_sc, eco, inv, horizon, has_expiry, is_capped(inp["mode"])) for p in grid]
        all_modes = {}
        for mk in config.MODES:
            r, n, _ = solve(base_sc, mk)
            all_modes[mk] = {"price": r["price"], "orders_per_day": round(r["orders_per_day"], 2),
                             "total_profit": round(r["total_profit"]), "profit_per_order": round(r["profit_per_order"], 1),
                             "margin_pct": round(100 * r["margin"], 1), "days_to_sell_out": _days(r["days_to_sell_out"]),
                             "units_sold": round(r["units_sold"]), "note": n,
                             "label": config.MODES[mk][0], "hint": config.MODES[mk][1]}

        # 3. price plan: after launch, once the listing has reviews
        launch_days = min(horizon, 30)
        launch_units = min(best["orders_per_day"] * launch_days * eco.units_per_order, inv)
        remaining = max(1, int(inv - launch_units))
        steady_sc = replace(base_sc, new_listing=False)
        steady_best = None
        if not is_capped(inp["mode"]):
            remaining = inv
        if remaining > 1 and inp["mode"] != "clear_inventory":
            steady_best, _, _ = solve(steady_sc, inventory=remaining)

        # 4. counterfactuals for the explanation (each switches one factor off)
        cf = {}
        cf["no_season"] = solve(replace(base_sc, window_mult=hist_mult))[0]
        cf["no_new"] = solve(replace(base_sc, new_listing=False))[0]
        cf["no_crowd"] = solve(replace(base_sc, crowd_adj=1.0))[0]
        cf["unlimited_stock"] = solve(base_sc, inventory=10 ** 7)[0] if is_capped(inp["mode"]) and inp["mode"] != "clear_inventory" else None

        # 5. package the answer
        price = best["price"]
        mrp_ratios = [p["mrp"] / p["current_price"] for _, p in pool[:80]]
        mrp_ratio = percentile(mrp_ratios, 50) or 2.0
        suggested_mrp = int(round(price * mrp_ratio, -1)) - 1
        pct_rank = round(100 * sum(1 for x in summary["prices"] if x < price) / max(1, len(summary["prices"])))
        result = {
            "input": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in inp.items()},
            "attributes": {k: {"value": v, "label": _label(k, v), "source": inp["attr_sources"][k]}
                           for k, v in attrs.items()},
            "package": pkg,
            "recommendation": {
                "mode": inp["mode"], "mode_label": config.MODES[inp["mode"]][0],
                "entry_price": price, "suggested_mrp": suggested_mrp,
                "discount_shown_pct": round(100 * (1 - price / suggested_mrp)) if suggested_mrp > price else 0,
                "break_even_price": round(eco.break_even()),
                "orders_per_day": round(best["orders_per_day"], 2),
                "orders_in_horizon": round(best["orders"]),
                "units_sold_in_horizon": round(best["units_sold"]),
                "profit_per_order": round(best["profit_per_order"], 1),
                "profit_per_delivered_order": round(best["profit_per_order"] / eco.kept, 1),
                "margin_pct": round(100 * best["margin"], 1),
                "total_profit": round(best["total_profit"]),
                "gmv": round(best["gmv"]),
                "days_to_sell_out": _days(best["days_to_sell_out"]),
                "horizon_days": horizon, "has_expiry": has_expiry, "writeoff": round(best["writeoff"]),
                "sell_by": expiry.isoformat() if has_expiry else None,
                "stock_limited": is_capped(inp["mode"]), "inventory": inv,
                "writeoff_if_unsold": round(inv * inp["cogs"] * (1 - config.SALVAGE_SHARE_OF_COGS)) if has_expiry else None,
                "percentile_in_market": pct_rank, "note": note,
                "steady_price": steady_best["price"] if steady_best else None,
                "steady_orders_per_day": round(steady_best["orders_per_day"], 2) if steady_best else None,
                "launch_phase_days": launch_days,
            },
            "modes": all_modes,
            "economics": {"breakdown": eco.breakdown(price), "return_rate_pct": round(100 * ret, 1),
                          "rto_rate_pct": round(100 * rto, 1), "return_rate_based_on_orders": ret_orders,
                          "transit_loss_pct": round(100 * eco.transit, 1),
                          "cost_per_order": round(eco.cost_per_order, 1), "cogs": round(inp["cogs"], 1),
                          "cogs_source": inp["cogs_source"], "kept_share_pct": round(100 * eco.kept, 1)},
            "market": {k: v for k, v in summary.items() if k != "prices"},
            "price_distribution": _histogram(summary["prices"], price),
            "demand_model": {
                "price_sensitivity": round(fit["b"], 2),
                "price_sensitivity_effective": round(base_sc.b_eff, 2),
                "price_sensitivity_raw": round(fit["b_raw"], 2) if fit["b_raw"] is not None else None,
                "listings_with_price_changes": fit["n_price_changes"], "listings_used": fit["n"],
                "note": fit["note"],
                "typical_orders_per_day": round(level * win["combined"], 2),
                "new_listing_factor": round(m.new_listing_factor, 2),
                "season_index": round(win["season"], 2), "festival_index": round(win["festival"], 2),
                "window_multiplier": round(win["combined"], 2), "history_multiplier": round(hist_mult, 2),
                "history_season_index": round(hist["season"], 2), "history_festival_index": round(hist["festival"], 2),
                "festivals": win["events"], "seller_ctr_factor": seller_factor,
                "photo_factor": round(photo_factor, 2), "crowding_adj": round(crowd_adj, 3),
                "hedonic_r2": round(m.hedonic_r2, 2),
            },
            "seller": seller,
            "curve": [{"price": r["price"], "orders_per_day": round(r["orders_per_day"], 3),
                       "profit_per_order": round(r["profit_per_order"], 1), "total_profit": round(r["total_profit"]),
                       "orders": round(r["orders"], 1)} for r in rows],
            "offline": _offline(inp, eco, price),
        }
        result["explanation"] = build_explanation(result, cf, best, inp, eco, base_sc)
        if save:
            result["recommendation_id"] = self._save(inp, raw, result)
            self.recent[result["recommendation_id"]] = result      # kept for the AI explanation step
            while len(self.recent) > 200:
                self.recent.popitem(last=False)
        return result

    # ------------------------------------------------------------------ listing actions
    def list_product(self, raw: dict) -> dict:
        """Create a live listing (one product per colour) from the pricing form + chosen price."""
        inp = clean_input(raw, self.market)
        if inp["seller_id"] is None:
            raise InputError("Choose a seller account to list this product.")
        price = _num(raw, "price", lo=49, hi=100000, required=True, integer=True, label="listing price")
        mrp = _num(raw, "mrp", lo=1, hi=500000, integer=True, label="MRP")
        if not mrp or mrp <= price:
            mrp = int(round(price * 2.2, -1)) - 1
        colors = raw.get("colors") or ""
        if isinstance(colors, str):
            colors = colors.split(",")
        seen, clean = set(), []
        for c in colors:
            c = " ".join(str(c).split())[:30].title()
            if c and c.lower() not in seen:
                seen.add(c.lower())
                clean.append(c)
        clean = clean[:6] or ["Multicolour"]
        if inp["inventory"] < len(clean):
            raise InputError(f"You have {inp['inventory']} units but {len(clean)} colours - add stock or remove a colour.")
        rec_id = raw.get("recommendation_id")
        attrs = inp["attrs"]
        pkg = features.estimate_package(attrs["product_type"], attrs["fabric"], inp["package_size"])
        base_title = inp["title"] or f"{_label('fabric', attrs['fabric'])} {_label('pattern', attrs['pattern'])} {_label('product_type', attrs['product_type'])}"
        con = sqlite3.connect(self.db_path)
        try:
            if rec_id is not None:
                try:
                    rec_id = int(rec_id)
                except (TypeError, ValueError):
                    rec_id = None
                if rec_id is not None and not con.execute("SELECT 1 FROM pricing_recommendations WHERE recommendation_id=?",
                                                          (rec_id,)).fetchone():
                    rec_id = None
            cat_id = con.execute("SELECT category_id FROM categories WHERE product_type_key=?", (attrs["product_type"],)).fetchone()[0]
            catalog_id = con.execute("SELECT COALESCE(max(catalog_id), 0) + 1 FROM catalogs").fetchone()[0]
            next_pid = con.execute("SELECT COALESCE(max(product_id), 0) + 1 FROM products").fetchone()[0]
            listed = inp["launch_date"].isoformat()
            con.execute("INSERT INTO catalogs VALUES (?,?,?,?)", (catalog_id, inp["seller_id"], base_title, listed))
            ids = []
            per, extra = divmod(inp["inventory"], len(clean))
            for k, color in enumerate(clean):
                pid = next_pid + k
                title = base_title if color == "Multicolour" else f"{color} {base_title}"
                desc = inp["description"] or title
                con.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (pid, catalog_id, inp["seller_id"], cat_id, title, desc, attrs["fabric"], attrs["pattern"],
                             attrs["sleeve"], attrs["length"], attrs["occasion"], color, "S,M,L,XL,XXL",
                             max(1, inp["n_photos"]), pkg["product_weight_g"], pkg["package_size"], mrp, price,
                             int(round(inp["cogs"])), listed, "active", rec_id, "seller"))
                con.execute("INSERT INTO inventory VALUES (?,?,?)", (pid, per + (1 if k < extra else 0), listed))
                con.execute("INSERT INTO price_history VALUES (?,?,?)", (pid, listed, price))
                ids.append(pid)
            con.commit()
        finally:
            con.close()
        self.market.add_products(ids)
        seller = self.market.sellers[inp["seller_id"]]
        return {"product_ids": ids, "catalog_id": catalog_id, "seller_id": inp["seller_id"],
                "seller_name": seller["seller_name"], "colors": clean, "price": price}

    def apply_price(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise InputError("Invalid request.")
        pid = _num(raw, "product_id", required=True, integer=True, label="product")
        price = _num(raw, "price", lo=49, hi=100000, required=True, integer=True, label="price")
        prod = next((p for p in self.market.products if p["product_id"] == pid and p["status"] == "active"), None)
        if prod is None:
            raise InputError("Listing not found.")
        today = (self.market.snapshot + timedelta(days=1)).isoformat()
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE products SET current_price=? WHERE product_id=?", (price, pid))
            con.execute("INSERT OR REPLACE INTO price_history VALUES (?,?,?)", (pid, today, price))
            con.commit()
        finally:
            con.close()
        self.market.set_price(pid, price)
        return {"product_id": pid, "price": price, "effective_from": today}

    def set_status(self, raw: dict, status: str) -> dict:
        """Delist or relist one listing."""
        if not isinstance(raw, dict):
            raise InputError("Invalid request.")
        pid = _num(raw, "product_id", required=True, integer=True, label="product")
        prod = next((p for p in self.market.products if p["product_id"] == pid), None)
        if prod is None or prod["status"] == "paused":
            raise InputError("Listing not found.")
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("UPDATE products SET status=? WHERE product_id=?", (status, pid))
            con.commit()
        finally:
            con.close()
        self.market.set_status(pid, status)
        return {"product_id": pid, "status": status, "title": prod["title"], "origin": prod.get("origin", "seed")}

    def restore_examples(self) -> dict:
        """Bring back demo (seed) listings that someone delisted - runs on every page load."""
        gone = [p["product_id"] for p in self.market.products if p["status"] == "delisted" and p.get("origin") == "seed"]
        if gone:
            con = sqlite3.connect(self.db_path)
            try:
                con.executemany("UPDATE products SET status='active' WHERE product_id=?", [(i,) for i in gone])
                con.commit()
            finally:
                con.close()
            for pid in gone:
                self.market.set_status(pid, "active")
        return {"restored": len(gone)}

    def _save(self, inp, raw, result):
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(
                "INSERT INTO pricing_recommendations (created_at, seller_id, mode, input_json, recommended_price, output_json) "
                "VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), inp["seller_id"], inp["mode"],
                 json.dumps(raw, default=str), result["recommendation"]["entry_price"],
                 json.dumps({k: result[k] for k in ("recommendation", "modes", "economics")}, default=str)))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()


# ---------------------------------------------------------------- small helpers
def _days(x):
    return None if x is None or math.isinf(x) or x > 9999 else round(x, 1)


def _label(attr, value):
    table = {"product_type": config.PRODUCT_TYPES, "fabric": config.FABRICS, "pattern": config.PATTERNS,
             "sleeve": config.SLEEVES, "length": config.LENGTHS, "occasion": config.OCCASIONS}[attr]
    v = table[value]
    return v[0] if isinstance(v, tuple) else v


def _histogram(prices, rec_price, n_bins=14):
    if not prices:
        return {"bins": [], "recommended": rec_price}
    lo, hi = min(prices), max(prices)
    lo, hi = min(lo, rec_price), max(hi, rec_price)
    width = max(10, int(math.ceil((hi - lo + 1) / n_bins / 10.0)) * 10)
    start = int(lo // 10 * 10)
    bins = []
    x = start
    while x <= hi:
        bins.append({"from": x, "to": x + width, "count": sum(1 for p in prices if x <= p < x + width)})
        x += width
    return {"bins": bins, "recommended": rec_price}


def _offline(inp, eco, price):
    if not inp["offline_price"]:
        return None
    out = {"offline_price": round(inp["offline_price"]),
           "online_vs_offline_pct": round(100 * (price / inp["offline_price"] - 1), 1)}
    if inp["offline_margin_pct"] is not None:
        off_profit = inp["offline_price"] * inp["offline_margin_pct"] / 100
        out["offline_profit_per_piece"] = round(off_profit)
        out["offline_margin_pct"] = round(inp["offline_margin_pct"], 1)
    out["online_profit_per_delivered"] = round(eco.profit(price) / eco.kept)
    out["online_margin_pct"] = round(100 * eco.margin(price), 1)
    return out
