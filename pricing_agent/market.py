"""
Market intelligence layer: reads the marketplace database once and answers
"what does the market look like for a product like this?".

 * Hedonic price model  - what are these attributes worth on Meesho today?
 * Competitor retrieval - which live listings are most similar?
 * Demand model         - how strongly do orders fall as price rises (fitted)?
 * Returns, crowding, review complaints, and the seller's own track record.
"""
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import config, signals
from .stats import clip, percentile, weighted_median, wls

ATTRS = ["product_type", "fabric", "pattern", "occasion", "sleeve", "length"]
SIM_WEIGHTS = {"product_type": 3.0, "fabric": 2.0, "pattern": 1.5, "occasion": 1.0, "sleeve": 0.5, "length": 0.5}
BASELINE = {"product_type": "kurti", "fabric": "cotton", "pattern": "printed", "occasion": "daily",
            "sleeve": "three_quarter", "length": "knee"}
LEVELS = {"product_type": list(config.PRODUCT_TYPES), "fabric": list(config.FABRICS),
          "pattern": list(config.PATTERNS), "occasion": list(config.OCCASIONS),
          "sleeve": list(config.SLEEVES), "length": list(config.LENGTHS)}
MATURE_AFTER_DAYS = 30   # ignore a listing's first month (visibility ramp) when fitting demand
NEGATIVE_THEMES = {"size_issue": "sizing / fit problems", "fabric_thin": "thin or see-through fabric",
                   "color_mismatch": "colour not matching photos", "stitching": "poor stitching"}


def similarity(a: dict, b: dict) -> float:
    total = sum(SIM_WEIGHTS.values())
    return sum(w for k, w in SIM_WEIGHTS.items() if a.get(k) == b.get(k)) / total


def _design_row(attrs: dict):
    row = [1.0]
    for k in ATTRS:
        for lvl in LEVELS[k]:
            if lvl != BASELINE[k]:
                row.append(1.0 if attrs.get(k) == lvl else 0.0)
    return row


PRODUCT_SQL = f"""
    SELECT p.*, c.product_type_key AS product_type, s.seller_name, s.city, s.tier, s.is_demo_seller,
           COALESCE(m.days, 0) AS mature_days, COALESCE(m.imp, 0) AS imp, COALESCE(m.clk, 0) AS clk,
           COALESCE(m.ord, 0) AS ord, COALESCE(m.ret, 0) AS ret, COALESCE(m.rto, 0) AS rto,
           m.avg_price, m.first_day,
           COALESCE(a.all_ord, 0) AS all_ord, COALESCE(a.all_days, 0) AS all_days,
           COALESCE(r.n_reviews, 0) AS n_reviews, r.avg_rating
    FROM products p
    JOIN categories c USING (category_id)
    JOIN sellers s USING (seller_id)
    LEFT JOIN (
        SELECT dm.product_id, count(*) AS days, sum(impressions) AS imp, sum(clicks) AS clk,
               sum(orders) AS ord, sum(customer_returns) AS ret, sum(rto) AS rto,
               avg(dm.price) AS avg_price, min(metric_date) AS first_day
        FROM daily_product_metrics dm JOIN products p2 USING (product_id)
        WHERE dm.metric_date >= date(p2.listed_on, '+{MATURE_AFTER_DAYS} day')
        GROUP BY dm.product_id) m USING (product_id)
    LEFT JOIN (SELECT product_id, sum(orders) AS all_ord, count(*) AS all_days
               FROM daily_product_metrics GROUP BY product_id) a USING (product_id)
    LEFT JOIN (SELECT product_id, count(*) AS n_reviews, avg(rating) AS avg_rating
               FROM reviews GROUP BY product_id) r USING (product_id)
    {{where}}
"""


class Market:
    def __init__(self, db_path: str):
        self.db_path = db_path
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        self.snapshot = date.fromisoformat(con.execute("SELECT max(metric_date) FROM daily_product_metrics").fetchone()[0])
        self.window_start = date.fromisoformat(con.execute("SELECT min(metric_date) FROM daily_product_metrics").fetchone()[0])
        rows = con.execute(PRODUCT_SQL.format(where="")).fetchall()
        self.products = [dict(r) for r in rows]
        themes = defaultdict(Counter)
        for pid, theme, n in con.execute("SELECT product_id, theme, count(*) FROM reviews GROUP BY 1, 2"):
            themes[pid][theme] = n
        self.review_themes = themes
        self.sellers = {r["seller_id"]: dict(r) for r in con.execute("SELECT * FROM sellers")}
        # price "spells": stretches of mature days a listing sold at one price
        self.spells = defaultdict(list)
        for pid, price, first, last, n, orders in con.execute(f"""
                SELECT dm.product_id, dm.price, min(metric_date), max(metric_date), count(*), sum(orders)
                FROM daily_product_metrics dm JOIN products p2 USING (product_id)
                WHERE dm.metric_date >= date(p2.listed_on, '+{MATURE_AFTER_DAYS} day')
                GROUP BY dm.product_id, dm.price"""):
            self.spells[pid].append({"price": price, "first": date.fromisoformat(first),
                                     "last": date.fromisoformat(last), "days": n, "orders": orders})
        # how new listings do in their first month vs later (visibility ramp + no reviews yet)
        young = con.execute(f"""
            SELECT sum(CASE WHEN metric_date <  date(p.listed_on, '+{MATURE_AFTER_DAYS} day') THEN orders END) * 1.0 /
                   sum(CASE WHEN metric_date <  date(p.listed_on, '+{MATURE_AFTER_DAYS} day') THEN 1 END),
                   sum(CASE WHEN metric_date >= date(p.listed_on, '+{MATURE_AFTER_DAYS} day') THEN orders END) * 1.0 /
                   sum(CASE WHEN metric_date >= date(p.listed_on, '+{MATURE_AFTER_DAYS} day') THEN 1 END)
            FROM daily_product_metrics dm JOIN products p USING (product_id)
            WHERE p.listed_on >= (SELECT min(metric_date) FROM daily_product_metrics)""").fetchone()
        self.new_listing_factor = clip(young[0] / young[1], 0.4, 1.0) if young and young[0] and young[1] else 0.75
        con.close()

        self._mult_cache = {}
        for p in self.products:
            self._prepare(p)
        self.active = [p for p in self.products if p["status"] == "active"]
        self._fit_hedonic()
        self._category_stats()

    def _prepare(self, p):
        p["daily_orders"] = p["all_ord"] / p["all_days"] if p["all_days"] else 0.0
        p["mature_daily_orders"] = p["ord"] / p["mature_days"] if p["mature_days"] else 0.0
        p["ctr"] = p["clk"] / p["imp"] if p["imp"] else None
        p["mult_avg"] = self._avg_mult(p) if p["mature_days"] else 1.0

    def add_products(self, product_ids):
        """Load freshly listed products into the live market (they become visible to every seller)."""
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        q = ",".join("?" * len(product_ids))
        rows = con.execute(PRODUCT_SQL.format(where=f"WHERE p.product_id IN ({q})"), list(product_ids)).fetchall()
        con.close()
        for r in rows:
            p = dict(r)
            self._prepare(p)
            p["fair_price"] = self.fair_price(p)
            self.products.append(p)
            if p["status"] == "active":
                self.active.append(p)

    def set_price(self, product_id, price):
        for p in self.products:
            if p["product_id"] == product_id:
                p["current_price"] = price

    # ------------------------------------------------------------- helpers
    def _mult(self, d: date, fabric: str, occasion: str) -> float:
        key = (d, fabric, occasion)
        if key not in self._mult_cache:
            self._mult_cache[key] = signals.demand_multiplier(d, fabric, occasion)
        return self._mult_cache[key]

    def _avg_mult(self, p) -> float:
        start = date.fromisoformat(p["first_day"])
        n = (self.snapshot - start).days + 1
        return sum(self._mult(start + timedelta(days=i), p["fabric"], p["occasion"]) for i in range(n)) / n

    def history_multiplier(self, fabric: str, occasion: str) -> float:
        """Average demand multiplier over the data window (the 'normal' the model was trained on)."""
        n = (self.snapshot - self.window_start).days + 1
        return sum(self._mult(self.window_start + timedelta(days=i), fabric, occasion) for i in range(n)) / n

    # ------------------------------------------------------------- hedonic model
    def _fit_hedonic(self):
        X = [_design_row(p) for p in self.active]
        y = [math.log(p["current_price"]) for p in self.active]
        self.hedonic_coefs, self.hedonic_r2, resid = wls(X, y, ridge=1e-4)
        self.hedonic_sigma = math.sqrt(sum(r * r for r in resid) / max(1, len(resid) - len(X[0])))
        for p in self.active:
            p["fair_price"] = self.fair_price(p)

    def fair_price(self, attrs: dict) -> float:
        row = _design_row(attrs)
        return math.exp(sum(c * v for c, v in zip(self.hedonic_coefs, row)))

    def attribute_premiums(self, attrs: dict):
        """Rs premium/discount of each attribute vs a plain printed cotton kurti."""
        base = self.fair_price(BASELINE)
        out = []
        for k in ["product_type", "fabric", "pattern", "occasion"]:
            if attrs.get(k) != BASELINE[k]:
                alt = dict(BASELINE)
                alt[k] = attrs[k]
                out.append({"attribute": k, "value": attrs[k], "pct": round((self.fair_price(alt) / base - 1) * 100)})
        return base, out

    # ------------------------------------------------------------- category stats
    def _category_stats(self):
        self.cat = {}
        for ptype in config.PRODUCT_TYPES:
            ps = [p for p in self.active if p["product_type"] == ptype]
            imp = sum(p["imp"] for p in ps)
            clk = sum(p["clk"] for p in ps)
            orders = sum(p["ord"] for p in ps)
            days = sum(p["mature_days"] for p in ps)
            self.cat[ptype] = {
                "listings": len(ps),
                "ctr": clk / imp if imp else 0.03,
                "orders_per_listing_day": orders / days if days else 1.0,
                "return_rate": sum(p["ret"] for p in ps) / orders if orders else None,
                "rto_rate": sum(p["rto"] for p in ps) / orders if orders else None,
            }
        # photos -> CTR, learnt from the data
        by_n = defaultdict(lambda: [0, 0])
        for p in self.active:
            k = min(p["n_images"], 6)
            by_n[k][0] += p["clk"]
            by_n[k][1] += p["imp"]
        overall = sum(v[0] for v in by_n.values()) / max(1, sum(v[1] for v in by_n.values()))
        self.photo_ctr_index = {k: (v[0] / v[1]) / overall for k, v in by_n.items() if v[1] > 0}

    def photo_factor(self, n_images: int) -> float:
        k = clip(int(n_images), 1, 6)
        if k in self.photo_ctr_index:
            return self.photo_ctr_index[k]
        return 1.0

    # ------------------------------------------------------------- competitors
    def competitors(self, attrs: dict, exclude_seller=None):
        scored = []
        for p in self.active:
            if exclude_seller is not None and p["seller_id"] == exclude_seller:
                continue
            s = similarity(attrs, p)
            if p["product_type"] != attrs["product_type"]:
                s -= 0.15  # a 3-piece set is never a true substitute for a single kurti
            scored.append((s, p))
        scored.sort(key=lambda t: (-t[0], -t[1]["daily_orders"]))
        for threshold in (0.7, 0.6, 0.5, 0.35, -1):
            pool = [(s, p) for s, p in scored if s >= threshold]
            if len(pool) >= 25:
                break
        return pool

    def market_summary(self, attrs: dict, pool, fair_price: float):
        comps = pool[:80]
        prices = [p["current_price"] for _, p in comps]
        weights = [max(0.05, p["daily_orders"]) * s for s, p in comps]
        direct = [p for s, p in pool if s >= 0.7]
        seg_orders = sum(p["daily_orders"] for p in direct)
        cat = self.cat[attrs["product_type"]]
        # crowding: listings competing per daily order, relative to the category
        if direct and seg_orders > 0:
            crowding = (len(direct) / seg_orders) / (1.0 / cat["orders_per_listing_day"])
        else:
            crowding = 1.0
        top = sorted(comps, key=lambda t: -t[1]["daily_orders"] * (0.5 + t[0]))[:8]
        ratings = [p["avg_rating"] for _, p in comps if p["avg_rating"]]
        theme_counts = Counter()
        total_reviews = 0
        for _, p in comps:
            theme_counts.update(self.review_themes.get(p["product_id"], {}))
            total_reviews += p["n_reviews"]
        complaints = [{"theme": t, "label": NEGATIVE_THEMES[t], "share_pct": round(100 * n / total_reviews, 1)}
                      for t, n in theme_counts.most_common() if t in NEGATIVE_THEMES and total_reviews]
        return {
            "n_comparable": len(comps),
            "n_direct_competitors": len(direct),
            "direct_competitor_daily_orders": round(seg_orders, 1),
            "crowding_index": round(crowding, 2),
            "price_p10": percentile(prices, 10), "price_p25": percentile(prices, 25),
            "price_median": percentile(prices, 50), "price_p75": percentile(prices, 75),
            "price_p90": percentile(prices, 90),
            "sales_weighted_median": weighted_median(prices, weights),
            "fair_price": fair_price,
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "prices": prices,
            "top_competitors": [{
                "product_id": p["product_id"], "title": p["title"], "seller": p["seller_name"], "city": p["city"],
                "seller_id": p["seller_id"], "is_demo_seller": bool(p.get("is_demo_seller")),
                "price": p["current_price"], "mrp": p["mrp"], "rating": round(p["avg_rating"], 1) if p["avg_rating"] else None,
                "reviews": p["n_reviews"], "orders_per_day": round(p["daily_orders"], 1),
                "est_monthly_orders": int(round(p["daily_orders"] * 30)),
                "return_rate_pct": round(100 * p["ret"] / p["ord"], 1) if p["ord"] else None,
                "similarity_pct": round(100 * max(0, s))} for s, p in top],
            "complaints": complaints[:3],
        }

    # ------------------------------------------------------------- demand model
    def _spell_mult(self, sp, fabric, occasion):
        n = (sp["last"] - sp["first"]).days + 1
        return sum(self._mult(sp["first"] + timedelta(days=i), fabric, occasion) for i in range(n)) / n

    def fit_demand(self, pool, occasion=None):
        """
        Two-step demand model on comparable listings.

        1. Price sensitivity b - from listings that CHANGED their price (within-listing
           comparison, so a listing's own popularity cancels out):
               ln(orders/day ÷ season) = listing effect - b·(price ÷ fair price)
           shrunk toward a prior when few listings changed price.
        2. Demand level - cross-section of comparables at the fitted b:
               ln(orders/day ÷ season) + b·(rel price - 1) = a + g·(rating - 4)
        """
        prior = config.PRIOR_SENSITIVITY
        comps = [p for s, p in pool[:250] if p["mature_days"] >= 20 and p.get("avg_price")]
        # --- step 1: within-listing price variation. Buyers for the same occasion behave alike,
        # so use same-occasion listings when there are enough of them.
        changed = [p for p in comps if sum(1 for x in self.spells.get(p["product_id"], []) if x["days"] >= 7) >= 2]
        same = [p for p in changed if p["occasion"] == occasion]
        if occasion and len(same) >= 20:
            changed = same
        sxy = sxx = 0.0
        n_changed = 0
        for p in changed:
            sp = [x for x in self.spells.get(p["product_id"], []) if x["days"] >= 7]
            if len(sp) < 2:
                continue
            n_changed += 1
            xs, ys, ws = [], [], []
            for x in sp:
                xs.append(x["price"] / p["fair_price"])
                ys.append(math.log((x["orders"] + 0.5) / x["days"]) -
                          math.log(self._spell_mult(x, p["fabric"], p["occasion"])))
                ws.append(x["days"])
            wsum = sum(ws)
            xm = sum(w * v for w, v in zip(ws, xs)) / wsum
            ym = sum(w * v for w, v in zip(ws, ys)) / wsum
            for w, xv, yv in zip(ws, xs, ys):
                sxy += w * (xv - xm) * (yv - ym)
                sxx += w * (xv - xm) ** 2
        b_raw = -sxy / sxx if sxx > 1e-9 else None
        if b_raw is None:
            b = prior
        else:
            b = (n_changed * clip(b_raw, 0.5, 8.0) + config.PRIOR_STRENGTH * prior) / (n_changed + config.PRIOR_STRENGTH)
        b = clip(b, 1.2, 6.0)
        # --- step 2: level
        if len(comps) < 8:
            return {"b": b, "b_raw": b_raw, "n_price_changes": n_changed, "n": len(comps), "r2": None,
                    "coefs": None, "smear": 1.0,
                    "note": "Few comparable listings with sales history - demand level uses a category default."}
        X, y, w = [], [], []
        for p in comps:
            rel = p["avg_price"] / p["fair_price"]
            rating = p["avg_rating"] if p["avg_rating"] else 4.0
            X.append([1.0, rating - 4.0])
            y.append(math.log((p["ord"] + 0.5) / p["mature_days"]) - math.log(p["mult_avg"]) + b * (rel - 1.0))
            w.append(math.sqrt(p["mature_days"]))
        coefs, r2, resid = wls(X, y, w, ridge=1e-3)
        smear = sum(math.exp(r) for r in resid) / len(resid)   # Duan smearing (log -> level bias)
        return {"b": b, "b_raw": b_raw, "n_price_changes": n_changed, "n": len(comps), "r2": r2,
                "coefs": coefs, "smear": smear, "note": None}

    def base_demand(self, fit, rating: float = 4.0) -> float:
        """Expected orders/day for a typical established listing at fair price, season multiplier = 1."""
        if not fit["coefs"]:
            return 1.5
        a, g = fit["coefs"]
        return math.exp(a + g * (rating - 4.0)) * fit["smear"]

    # ------------------------------------------------------------- returns
    def return_rates(self, attrs: dict, pool):
        prior_ret, prior_rto = config.CATEGORY_RETURN_PRIORS[attrs["product_type"]]
        comps = [p for s, p in pool[:150]]
        orders = sum(p["ord"] for p in comps)
        k = 300.0  # prior weight in orders
        ret = (sum(p["ret"] for p in comps) + k * prior_ret) / (orders + k)
        rto = (sum(p["rto"] for p in comps) + k * prior_rto) / (orders + k)
        return ret, rto, orders

    # ------------------------------------------------------------- seller history
    def seller_history(self, seller_id, attrs: dict):
        if seller_id is None:
            return None
        seller = self.sellers.get(seller_id)
        own = [p for p in self.products if p["seller_id"] == seller_id]
        out = {"seller_id": seller_id, "seller_name": seller["seller_name"] if seller else "Unknown",
               "city": seller["city"] if seller else None, "tier": seller["tier"] if seller else None,
               "n_listings": len(own), "ctr_factor": 1.0, "ctr_pct": None, "category_ctr_pct": None,
               "closest": None}
        if not own:
            return out
        cat_ctr = sum(self.cat[t]["ctr"] * self.cat[t]["listings"] for t in self.cat) / \
            max(1, sum(self.cat[t]["listings"] for t in self.cat))
        imp = sum(p["imp"] for p in own)
        clk = sum(p["clk"] for p in own)
        if imp > 0:
            raw = (clk / imp) / cat_ctr
            weight = imp / (imp + 20000.0)          # trust more data more
            out["ctr_factor"] = round(clip(1 + (raw ** 0.6 - 1) * weight, 0.75, 1.4), 3)
            out["ctr_pct"] = round(100 * clk / imp, 2)
            out["category_ctr_pct"] = round(100 * cat_ctr, 2)
        best = max(own, key=lambda p: (similarity(attrs, p), p["daily_orders"]))
        out["closest"] = {
            "title": best["title"], "price": best["current_price"], "similarity_pct": round(100 * similarity(attrs, best)),
            "orders_per_day": round(best["daily_orders"], 1),
            "ctr_pct": round(100 * best["ctr"], 2) if best["ctr"] else None,
            "return_rate_pct": round(100 * best["ret"] / best["ord"], 1) if best["ord"] else None,
            "cogs": best["cogs"], "rating": round(best["avg_rating"], 1) if best["avg_rating"] else None,
        }
        return out

    # ------------------------------------------------------------- db explorer
    def db_overview(self):
        con = sqlite3.connect(self.db_path)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        out = []
        for t in tables:
            cols = [{"name": c[1], "type": c[2], "pk": bool(c[5])} for c in con.execute(f"PRAGMA table_info({t})")]
            fks = [{"column": f[3], "ref_table": f[2], "ref_column": f[4]} for f in con.execute(f"PRAGMA foreign_key_list({t})")]
            count = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            cur = con.execute(f"SELECT * FROM {t} ORDER BY random() LIMIT 5" if t != "pricing_recommendations"
                              else f"SELECT recommendation_id, created_at, seller_id, mode, recommended_price FROM {t} ORDER BY recommendation_id DESC LIMIT 5")
            sample_cols = [d[0] for d in cur.description]
            sample = [list(r) for r in cur.fetchall()]
            out.append({"table": t, "rows": count, "columns": cols, "foreign_keys": fks,
                        "sample_columns": sample_cols, "sample": sample})
        con.close()
        return out
