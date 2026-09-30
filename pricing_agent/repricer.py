"""
Lifecycle repricing for a seller's existing listings.

For every live listing we combine what the listing itself did (last 28 days of
views, clicks, orders, returns at its actual price) with the market model
(fair price, learnt price sensitivity, season & festivals ahead, crowding) to
forecast the next 30 days at every candidate price. Then:

 * Colour variants of one design are priced together: raising the price of the
   colour that sells out pushes some buyers to its sibling colours, which helps
   clear their stock (coordinate search over the whole design).
 * Unsold stock carries a holding cost that grows sharply for "outdated" stock
   (old listing, falling sales, season ending, months of stock), so the agent
   marks it down before it becomes dead stock.
 * Guard rails: at most +15% / -25% per change (-35% for outdated stock), and
   changes smaller than max(Rs 10, 3%) are not worth making -> Hold.
"""
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from . import config, features, signals
from .engine import Economics, InputError, Scenario
from .market import ATTRS, similarity
from .stats import clip

HORIZON = 30
RESTOCK_DAYS = 10            # typical time out of stock while a seller restocks
SUBSTITUTION = 0.35          # share of buyers lost to a price rise who pick a sibling colour instead
CANNIBALISATION = 0.10       # share of a sibling's extra buyers (after a price cut) taken from this colour
OVERSTOCK_DAYS = 90          # never raise the price of something with 3+ months of stock
MAX_UP, MAX_DOWN, MAX_DOWN_OLD = 0.25, 0.25, 0.35   # search range for the target price
STEP_UP = 0.10               # raise in steps of at most 10%, then re-check (protects search ranking)
RANKING_FEEDBACK = 0.25      # a higher price lowers conversion, which also lowers Meesho search visibility


def _grid(lo, hi, current):
    start = int(math.floor(lo / 10.0)) * 10 + 9
    prices = set(p for p in range(max(49, start), int(hi) + 1, 10) if lo <= p <= hi)
    prices.add(int(current))
    return sorted(prices)


class Repricer:
    def __init__(self, agent):
        self.agent = agent
        self.m = agent.market
        self._fit_cache = {}

    # ------------------------------------------------------------------ data
    def _metrics(self, ids):
        con = sqlite3.connect(self.m.db_path)
        try:
            since = (self.m.snapshot - timedelta(days=59)).isoformat()
            q = ",".join("?" * len(ids))
            rows = con.execute(f"""SELECT product_id, metric_date, price, impressions, clicks, orders, customer_returns, rto
                                   FROM daily_product_metrics WHERE product_id IN ({q}) AND metric_date >= ?
                                   ORDER BY metric_date""", (*ids, since)).fetchall()
            inv = dict(con.execute(f"SELECT product_id, units_available FROM inventory WHERE product_id IN ({q})", ids))
            recs = {}
            for pid, out in con.execute(f"""SELECT p.product_id, r.output_json FROM products p
                                            JOIN pricing_recommendations r USING (recommendation_id)
                                            WHERE p.product_id IN ({q})""", ids):
                try:
                    recs[pid] = json.loads(out).get("recommendation", {})
                except ValueError:
                    pass
            names = dict(con.execute(f"""SELECT c.catalog_id, c.catalog_name FROM catalogs c
                                         JOIN products p USING (catalog_id) WHERE p.product_id IN ({q})""", ids))
            changed = dict(con.execute(f"""SELECT h.product_id, max(h.effective_from) FROM price_history h
                                           JOIN products p USING (product_id)
                                           WHERE h.product_id IN ({q}) AND h.effective_from > p.listed_on
                                           GROUP BY h.product_id""", ids))
        finally:
            con.close()
        by = defaultdict(list)
        for r in rows:
            by[r[0]].append({"date": r[1], "price": r[2], "imp": r[3], "clk": r[4], "ord": r[5], "ret": r[6], "rto": r[7]})
        return by, inv, recs, names, changed

    def _fit(self, attrs, pool):
        key = (attrs["product_type"], attrs["fabric"], attrs["pattern"], attrs["occasion"])
        if key not in self._fit_cache:
            self._fit_cache[key] = self.m.fit_demand(pool, attrs["occasion"])
        return self._fit_cache[key]

    # ------------------------------------------------------------------ one listing
    def _analyse(self, p, series, stock, today, seller_ctx):
        m = self.m
        attrs = {k: p[k] for k in ATTRS}
        pool = m.competitors(attrs, exclude_seller=p["seller_id"])
        fair = m.fair_price(attrs)
        summary = m.market_summary(attrs, pool, fair)
        fit = self._fit(attrs, pool)
        seg = [q for _, q in pool[:80] if q["imp"] > 0]
        seg_ctr = sum(q["clk"] for q in seg) / max(1, sum(q["imp"] for q in seg))
        seg_cvr = sum(q["ord"] for q in seg) / max(1, sum(q["clk"] for q in seg))

        cut = (m.snapshot - timedelta(days=27)).isoformat()
        prev_cut = (m.snapshot - timedelta(days=55)).isoformat()
        last = [r for r in series if r["date"] >= cut]
        prev = [r for r in series if prev_cut <= r["date"] < cut]
        agg = lambda rows, k: sum(r[k] for r in rows)
        days28 = len(last)
        ord28, prev_ord = agg(last, "ord"), agg(prev, "ord")
        opd28 = ord28 / days28 if days28 else 0.0
        opd_prev = prev_ord / len(prev) if prev else None
        p_recent = sum(r["price"] for r in last) / days28 if days28 else p["current_price"]
        ctr = agg(last, "clk") / agg(last, "imp") if agg(last, "imp") else None
        cvr = ord28 / agg(last, "clk") if agg(last, "clk") else None

        # returns: listing's own history blended with the segment
        seg_ret, seg_rto, _ = m.return_rates(attrs, pool)
        own_orders = p["ord"] + ord28
        ret = (p["ret"] + 100 * seg_ret) / (p["ord"] + 100) if p["ord"] else seg_ret
        rto = (p["rto"] + 100 * seg_rto) / (p["ord"] + 100) if p["ord"] else seg_rto
        pkg = features.estimate_package(p["product_type"], p["fabric"], p["package_size"])
        cogs = p["cogs"] or 0.44 * fair
        eco = Economics(cogs=cogs, ret=ret, rto=rto, packaging=pkg["packaging_cost"], fwd=pkg["shipping_forward"],
                        rev=pkg["shipping_reverse"], transit=config.TRANSIT_LOSS[p["product_type"]])

        # season & festivals: what the last 28 days looked like vs the next 30
        recent = signals.window_average(m.snapshot - timedelta(days=27), 28, p["fabric"], p["occasion"])
        fwd = signals.window_average(today, HORIZON, p["fabric"], p["occasion"])
        fwd90 = signals.window_average(today, 90, p["fabric"], p["occasion"])
        hist = m.history_multiplier(p["fabric"], p["occasion"])
        adj = Scenario._season_adj
        crowd_adj = clip(summary["crowding_index"] ** 0.15, 0.92, 1.1)
        b = fit["b"]
        b_recent = b * adj(recent["combined"]) / adj(hist) * crowd_adj
        b_fwd = b * adj(fwd["combined"]) / adj(hist) * crowd_adj * (1 + RANKING_FEEDBACK)

        # demand level: the listing's own sales, shrunk toward the market model when sales are thin
        prior = m.base_demand(fit, p["avg_rating"] or 4.0) * seller_ctx["ctr_factor"] * m.photo_factor(p["n_images"])
        listed = date.fromisoformat(p["listed_on"])
        age = (today - listed).days
        is_new = days28 == 0 or age < 21
        if is_new:
            level = prior * m.new_listing_factor
        else:
            observed = opd28 / (recent["combined"] * math.exp(-b_recent * (p_recent / fair - 1)))
            w = ord28 / (ord28 + 5.0)   # 4 weeks of the listing's own sales outweigh the market prior
            level = w * observed + (1 - w) * prior

        def own(price):
            return level * fwd["combined"] * math.exp(-b_fwd * (price / fair - 1))

        # outdated-stock score
        cover = stock / max(0.05, opd28 * eco.units_per_order) if not is_new else None
        age_f = clip((age - 120) / 180.0, 0, 1)
        trend = (opd28 / opd_prev) if opd_prev else None
        trend_f = clip((1 - trend) / 0.5, 0, 1) if trend is not None else 0.0
        season_f = clip((1 - fwd90["season"] / max(0.01, recent["season"])) / 0.25, 0, 1)
        cover_f = clip(((cover or 0) - 60) / 120.0, 0, 1)
        outdated = 0.0 if is_new else clip(0.35 * age_f + 0.25 * trend_f + 0.25 * season_f + 0.15 * cover_f, 0, 1)
        is_old = outdated >= 0.5
        # share of COGS lost on each unsold unit after 30 days: capital cost, plus the risk that
        # ageing stock ends up sold off at salvage value, plus a charge for months of excess stock
        excess = clip(((cover or 0) - 45) / 90.0, 0, 1)
        if is_old:   # ageing stock will likely end up sold off at salvage value
            holding = 0.03 + (1 - config.SALVAGE_SHARE_OF_COGS) * min(1.0, outdated / 0.7)
        else:
            holding = 0.03 + 0.15 * excess

        # rival listings from the other demo sellers
        rivals = []
        for q in m.active:
            if q["seller_id"] != p["seller_id"] and q["seller_id"] in seller_ctx["demo_ids"]:
                s = similarity(attrs, q)
                if s >= 0.6:
                    rivals.append((s, q))
        rivals.sort(key=lambda t: (-t[0], -t[1]["daily_orders"]))
        top_rival = None
        if rivals:
            s, q = rivals[0]
            top_rival = {"seller": q["seller_name"], "seller_id": q["seller_id"], "title": q["title"],
                         "price": q["current_price"], "orders_per_day": round(q["daily_orders"], 1),
                         "rating": round(q["avg_rating"], 1) if q["avg_rating"] else None,
                         "similarity_pct": round(100 * s)}
        themes = m.review_themes.get(p["product_id"], {})
        neg = {k: v for k, v in themes.items() if k in ("size_issue", "fabric_thin", "color_mismatch", "stitching")}
        top_complaint = max(neg, key=neg.get) if neg and p["n_reviews"] else None

        return {
            "p": p, "attrs": attrs, "fair": fair, "summary": summary, "fit": fit, "eco": eco, "own": own,
            "stock": stock, "p0": int(p["current_price"]), "is_new": is_new, "age": age, "listed": listed,
            "opd28": opd28, "opd_prev": opd_prev, "trend": trend, "ctr": ctr, "cvr": cvr, "seg_ctr": seg_ctr,
            "seg_cvr": seg_cvr, "cover": cover, "outdated": outdated, "is_old": is_old, "holding": holding,
            "fwd": fwd, "recent": recent, "fwd90": fwd90, "b_fwd": b_fwd, "top_rival": top_rival,
            "n_rivals": len(rivals), "top_complaint": top_complaint,
            "complaint_share": round(100 * neg[top_complaint] / p["n_reviews"]) if top_complaint else None,
            "series": series, "level": level, "b": b, "crowd_adj": crowd_adj, "hist": hist,
        }

    # ------------------------------------------------------------------ optimise one design
    def _optimise(self, ctxs, mode):
        ids = [c["p"]["product_id"] for c in ctxs]
        by = {c["p"]["product_id"]: c for c in ctxs}
        base_q = {i: by[i]["own"](by[i]["p0"]) for i in ids}

        def outcome(prices):
            own_now = {i: by[i]["own"](prices[i]) for i in ids}
            res = {}
            for i in ids:
                c = by[i]
                q = own_now[i]
                for j in ids:           # buyers switching between colours of the same design
                    if j == i:
                        continue
                    others = sum(base_q[k] for k in ids if k != j)
                    share = base_q[i] / others if others > 0 else 0
                    lost = base_q[j] - own_now[j]            # >0 when colour j got dearer
                    q += (SUBSTITUTION if lost > 0 else CANNIBALISATION) * lost * share
                q = max(0.3 * own_now[i], q)
                u = c["eco"].units_per_order
                cover = c["stock"] / (q * u) if q > 0 else float("inf")
                if c["is_old"]:
                    # ageing design: no restocking - only the stock on hand can be sold
                    orders = min(q * HORIZON, c["stock"] / u)
                    stockout = 0.0
                else:
                    # a reorder placed today lands in RESTOCK_DAYS: only thinner stock than that runs out
                    stockout = clip(RESTOCK_DAYS - cover, 0, RESTOCK_DAYS)
                    orders = q * (HORIZON - stockout)
                leftover = max(0.0, c["stock"] - orders * u)
                pi = c["eco"].profit(prices[i])
                sales_profit = pi * orders
                stock_cost = leftover * c["eco"].cogs * c["holding"]
                res[i] = {"price": prices[i], "orders_per_day": q, "orders": orders, "leftover": leftover,
                          "profit_per_order": pi, "sales_profit": sales_profit, "stock_cost": stock_cost,
                          "profit": sales_profit - stock_cost, "stockout_days": stockout,
                          "margin": c["eco"].margin(prices[i]),
                          "days_to_clear": c["stock"] / (q * u) if q > 0 else None,
                          "clear_penalty": leftover * c["eco"].cogs * 0.5,
                          }
            return res

        def group_score(res):
            """Same goals as the new-product pricer, applied to the whole design (all colours)."""
            profit = sum(r["profit"] for r in res.values())
            orders = sum(r["orders"] for r in res.values())
            if mode == "max_margin":
                return profit
            if mode == "scale":
                return orders + 1e-4 * profit
            if mode == "clear_inventory":
                return profit - sum(r["clear_penalty"] for r in res.values())
            # balanced: log(profit) + 0.5·log(orders)
            if profit <= 0:
                return -1e9 + profit
            return math.log(profit) + 0.5 * math.log(max(orders, 1e-6))

        grids = {}
        for i in ids:
            c = by[i]
            p0 = c["p0"]
            if c["is_new"] or c.get("changed_on"):
                grids[i] = [p0]      # new listing / price just changed: let data build up first
                continue
            down = MAX_DOWN_OLD if (c["is_old"] or mode == "clear_inventory") else MAX_DOWN
            eco = c["eco"]
            if c["is_old"] or mode == "clear_inventory":
                ok = lambda x: eco.profit(x) >= -0.3 * eco.cogs    # a small loss beats dead stock
            elif mode == "scale":
                ok = lambda x: eco.profit(x) >= config.MIN_PROFIT_PER_ORDER_SCALE and eco.margin(x) >= config.MIN_MARGIN_SCALE
            else:
                ok = lambda x: eco.profit(x) >= 1
            cover = c["cover"] or 0
            up = 0.0 if (c["is_old"] or cover > OVERSTOCK_DAYS) else MAX_UP   # never mark up ageing / excess stock
            if cover < RESTOCK_DAYS:
                down = 0.0                                                  # never cut a price that is about to sell out
            g = [x for x in _grid(p0 * (1 - down), p0 * (1 + up), p0) if ok(x)]
            grids[i] = g or [max(_grid(p0 * (1 - down), p0 * (1 + up), p0), key=eco.profit)]

        prices = {i: by[i]["p0"] for i in ids}
        for _ in range(3):   # coordinate search across colours of the design
            for i in ids:
                best, best_s = prices[i], None
                for x in grids[i]:
                    trial = dict(prices)
                    trial[i] = x
                    s = group_score(outcome(trial))
                    if best_s is None or s > best_s + 1e-9 or (abs(s - best_s) <= 1e-9 and abs(x - by[i]["p0"]) < abs(best - by[i]["p0"])):
                        best, best_s = x, s
                prices[i] = best
        targets = dict(prices)
        for i in ids:
            p0 = by[i]["p0"]
            # raise gradually: at most STEP_UP now, the rest after the next check
            step_cap = int(math.floor(p0 * (1 + STEP_UP) / 10.0)) * 10 - 1
            if prices[i] > p0 and prices[i] > step_cap:
                prices[i] = max(p0, step_cap)
            # changes too small to be worth it -> hold
            if abs(prices[i] - p0) < max(10, 0.03 * p0):
                prices[i] = p0
            if abs(targets[i] - p0) < max(10, 0.03 * p0):
                targets[i] = p0
        now = outcome({i: by[i]["p0"] for i in ids})
        new = outcome(prices)
        for i in ids:
            new[i]["target"] = targets[i]
        return now, new

    # ------------------------------------------------------------------ explain
    def _reasons(self, c, now, new, siblings):
        p0, p1 = c["p0"], new["price"]
        s = c["summary"]
        reasons = []
        gap = round(100 * (p0 / c["fair"] - 1))
        pos = "in line with it" if abs(gap) < 3 else f"{abs(gap)}% {'above' if gap > 0 else 'below'} that"
        reasons.append({"icon": "market", "tone": "neutral",
                        "text": f"Similar kurtis sell for ₹{int(s['price_p25'])}–₹{int(s['price_p75'])}; the fair price for this design "
                                f"is about ₹{round(c['fair'])}. Yours is {pos}."})
        up, down = p1 > p0, p1 < p0
        if c["cvr"] is not None and c["seg_cvr"]:
            rel = c["cvr"] / c["seg_cvr"]
            cv = f"({100 * c['cvr']:.1f}% vs {100 * c['seg_cvr']:.1f}%)"
            if rel < 0.85:
                reasons.append({"icon": "funnel", "tone": "negative",
                                "text": f"Shoppers open it but buy {round(100 * (1 - rel))}% less often than on similar listings {cv}"
                                        + (" - the price is putting them off." if down else
                                           (" - watch conversion after the change." if up else
                                            f" - but a lower price would lose money on each order (break-even ₹{round(c['eco'].break_even())})."))})
            elif rel > 1.15:
                reasons.append({"icon": "funnel", "tone": "positive",
                                "text": f"Shoppers who open it buy {round(100 * (rel - 1))}% more often than on similar listings {cv}"
                                        + (" - there is room to charge more." if not down else
                                           " - buyers like it; the problem is how much stock is left, not the price.")})
        if c["ctr"] is not None and c["seg_ctr"]:
            rel = c["ctr"] / c["seg_ctr"]
            if rel < 0.8 or rel > 1.2:
                reasons.append({"icon": "eye", "tone": "positive" if rel > 1 else "negative",
                                "text": f"Click-through is {100 * c['ctr']:.1f}% vs {100 * c['seg_ctr']:.1f}% for the segment"
                                        + (" - buyers love the photos and design." if rel > 1 else " - better photos would help more than a price cut.")})
        cover = c["cover"]
        if cover is not None:
            if cover < 14:
                reasons.append({"icon": "stock", "tone": "positive",
                                "text": f"Only {c['stock']} pieces left - about {cover:.0f} days of stock at today's pace. "
                                        f"A higher price earns more on the last pieces; restock soon."})
            elif cover > 60:
                reasons.append({"icon": "stock", "tone": "negative",
                                "text": f"{c['stock']} pieces in stock = about {min(cover, 999):.0f} days of sales at today's pace. "
                                        f"Money is stuck in inventory."})
        if siblings:
            mine = c["opd28"]
            fast = max(siblings, key=lambda x: x["opd28"])
            slow = min(siblings, key=lambda x: x["opd28"])
            color = c["p"]["color"]
            sib_up = any(x["new_price"] > x["p0"] for x in siblings)
            if slow["opd28"] > 0 and mine >= 1.8 * slow["opd28"]:
                ratio, other = mine / slow["opd28"], slow["p"]["color"]
                if up:
                    txt = (f"{color} sells {ratio:.1f}× faster than {other}. Raising {color}'s price earns more on the popular colour "
                           f"and sends ~{round(SUBSTITUTION * 100)}% of the buyers it loses to {other}, helping clear that stock.")
                elif down:
                    txt = f"{color} sells {ratio:.1f}× faster than {other}, so it needs a smaller cut than {other}."
                else:
                    txt = f"{color} sells {ratio:.1f}× faster than {other} - it is the colour to protect; keep it in stock."
                reasons.append({"icon": "variant", "tone": "positive", "text": txt})
            elif mine > 0 and fast["opd28"] >= 1.8 * mine:
                ratio, other = fast["opd28"] / mine, fast["p"]["color"]
                helper = f" {other}'s price rise sends some of its buyers here" if sib_up else ""
                if down:
                    txt = (f"{color} sells {ratio:.1f}× slower than {other} of the same design, so it gets a bigger cut to clear its stock."
                           + (f"{helper}, too." if helper else ""))
                elif not up:
                    txt = (f"{color} sells {ratio:.1f}× slower than {other}." + (f"{helper}, so {color}'s price can stay as it is."
                                                                                if helper else " Holding the price avoids a loss-making cut."))
                else:
                    txt = f"{color} sells {ratio:.1f}× slower than {other}, but it is still priced below what buyers will pay."
                reasons.append({"icon": "variant", "tone": "negative" if down else "neutral", "text": txt})
        fests = c["fwd"]["events"]
        dem = round(100 * (c["fwd"]["combined"] / max(0.01, c["recent"]["combined"]) - 1))
        if fests:
            names = " and ".join(f"{f['name']} ({f['days_away']} days)" for f in fests[:2])
            reasons.append({"icon": "festival", "tone": "positive" if dem > 0 else "neutral",
                            "text": f"{names} are coming up - demand for this kurti is expected to be {abs(dem)}% "
                                    f"{'higher' if dem >= 0 else 'lower'} than the last 4 weeks, and buyers compare prices less."})
        elif abs(dem) >= 8:
            reasons.append({"icon": "season", "tone": "positive" if dem > 0 else "negative",
                            "text": f"{c['p']['fabric'].replace('_', ' ').title()} demand is expected to be {abs(dem)}% "
                                    f"{'higher' if dem > 0 else 'lower'} next month than in the last 4 weeks (season)."})
        if c["is_old"]:
            bits = [f"listed {c['age']} days ago"]
            if c["trend"] is not None and c["trend"] < 0.9:
                bits.append(f"sales down {round(100 * (1 - c['trend']))}% vs the month before")
            if c["fwd90"]["season"] < c["recent"]["season"] * 0.92:
                bits.append(f"{c['p']['fabric'].replace('_', ' ')} season is ending")
            avoided = now["stock_cost"] - new["stock_cost"]
            reasons.append({"icon": "old", "tone": "negative",
                            "text": "This is ageing stock: " + ", ".join(bits) + ". "
                                    + (f"The markdown saves ~₹{round(avoided):,} of stock value that would otherwise be lost."
                                       if avoided > 50 else "It should be cleared before it loses more value.")})
            if new["leftover"] > 30:
                salvage = round(c["eco"].cogs * config.SALVAGE_SHARE_OF_COGS)
                reasons.append({"icon": "bundle", "tone": "neutral",
                                "text": f"Even after the cut, ~{round(new['leftover'])} pieces will be left in 30 days. Cutting deeper would lose "
                                        f"more per order (shipping + returns) than selling them in bulk (~₹{salvage}/piece) - "
                                        f"offer a 2-for combo or liquidate the rest."})
        thin = c["eco"].profit(p0)
        if thin < 15 and not c["is_old"]:
            reasons.append({"icon": "cost", "tone": "negative",
                            "text": f"At ₹{p0} you keep only ₹{round(thin)} per order after product cost, shipping, GST and returns "
                                    f"(break-even ₹{round(c['eco'].break_even())})."})
        rating = c["p"]["avg_rating"]
        if rating and rating < 3.6:
            reasons.append({"icon": "star", "tone": "negative",
                            "text": f"Rating is {rating:.1f}★" + (f" and {c['complaint_share']}% of reviews mention "
                                                                 f"{c['top_complaint'].replace('_', ' ')}" if c["top_complaint"] else "")
                                    + " - fix the product listing before raising the price."})
        if c["top_rival"]:
            r = c["top_rival"]
            reasons.append({"icon": "rival", "tone": "neutral",
                            "text": f"Closest rival: {r['seller']} sells “{r['title']}” at ₹{r['price']} "
                                    f"({r['orders_per_day']} orders/day)."})
        return reasons

    def _action(self, c, now, new, siblings):
        p0, p1 = c["p0"], new["price"]
        if c["is_new"]:
            return "new", "Launch phase - hold"
        if c.get("changed_on"):
            return "hold", "Recently changed - wait"
        if p1 > p0:
            if c["cover"] is not None and c["cover"] < 14:
                return "up", "Raise price · restock"
            if siblings and any(c["opd28"] > 1.8 * s["opd28"] for s in siblings):
                return "up", "Raise popular colour"
            return "up", "Raise price"
        if p1 < p0:
            if c["is_old"]:
                return "old", "Clear ageing stock"
            if siblings and any(s["opd28"] > 1.8 * c["opd28"] for s in siblings):
                return "down", "Lower to clear colour"
            return "down", "Lower price"
        if c["is_old"]:
            return "old", "Hold · bundle or liquidate"
        if c["cover"] is not None and c["cover"] < RESTOCK_DAYS:
            return "hold", "Hold · restock now"
        return "hold", "Hold price"

    # ------------------------------------------------------------------ public
    def seller_listings(self, seller_id, mode="balanced"):
        m = self.m
        try:
            seller_id = int(seller_id)
        except (TypeError, ValueError):
            raise InputError("Pick a seller.")
        if seller_id not in m.sellers:
            raise InputError("Seller not found.")
        if mode not in config.MODES:
            raise InputError(f"Unknown pricing goal: {mode}")
        today = m.snapshot + timedelta(days=1)
        seller = m.sellers[seller_id]
        demo_ids = {s["seller_id"] for s in m.sellers.values() if s["is_demo_seller"]}
        prods = [p for p in m.products if p["seller_id"] == seller_id and p["status"] == "active"]
        hist = m.seller_history(seller_id, {k: None for k in ATTRS})
        ctx_seller = {"ctr_factor": hist["ctr_factor"] if hist else 1.0, "demo_ids": demo_ids}
        base = {"seller": {"seller_id": seller_id, "name": seller["seller_name"], "city": seller["city"],
                           "tier": seller["tier"], "rating": seller["seller_rating"],
                           "ctr_pct": hist.get("ctr_pct") if hist else None,
                           "category_ctr_pct": hist.get("category_ctr_pct") if hist else None},
                "mode": mode, "mode_label": config.MODES[mode][0], "as_of": m.snapshot.isoformat(),
                "horizon_days": HORIZON}
        if not prods:
            return dict(base, summary=None, groups=[], rivals=self._rivals(seller_id, prods, demo_ids))

        ctxs, recs, names = self._contexts(prods, today, ctx_seller)
        groups = defaultdict(list)
        for c in ctxs:
            groups[c["p"]["catalog_id"]].append(c)

        out_groups = []
        tot = defaultdict(float)
        for cat_id, cs in groups.items():
            now, new = self._optimise(cs, mode)
            for c in cs:
                c["new_price"] = new[c["p"]["product_id"]]["price"]
            variants = []
            for c in cs:
                pid = c["p"]["product_id"]
                sibs = [x for x in cs if x is not c]
                kind, label = self._action(c, now[pid], new[pid], sibs)
                n, w = now[pid], new[pid]
                launch = recs.get(pid)
                tot["stock_units"] += c["stock"]
                tot["stock_value"] += c["stock"] * c["eco"].cogs
                tot["orders_30d"] += c["opd28"] * 30
                tot["revenue_30d"] += sum(r["ord"] * r["price"] for r in c["series"][-30:])
                tot["profit_now"] += n["profit"]
                tot["profit_new"] += w["profit"]
                tot["changes"] += int(w["price"] != c["p0"])
                tot["old_units"] += c["stock"] if c["is_old"] else 0
                variants.append({
                    "product_id": pid, "title": c["p"]["title"], "color": c["p"]["color"],
                    "origin": c["p"].get("origin", "seed"),
                    "listed_on": c["p"]["listed_on"], "age_days": c["age"], "stage": self._stage(c),
                    "stock": c["stock"], "current_price": c["p0"], "recommended_price": w["price"],
                    "change_pct": round(100 * (w["price"] / c["p0"] - 1), 1), "action": kind, "action_label": label,
                    "target_price": w["target"],
                    "orders_per_day_28d": round(c["opd28"], 2),
                    "trend_pct": round(100 * (c["trend"] - 1)) if c["trend"] is not None else None,
                    "ctr_pct": round(100 * c["ctr"], 2) if c["ctr"] is not None else None,
                    "segment_ctr_pct": round(100 * c["seg_ctr"], 2),
                    "cvr_pct": round(100 * c["cvr"], 1) if c["cvr"] is not None else None,
                    "segment_cvr_pct": round(100 * c["seg_cvr"], 1),
                    "rating": round(c["p"]["avg_rating"], 1) if c["p"]["avg_rating"] else None,
                    "reviews": c["p"]["n_reviews"],
                    "return_rate_pct": round(100 * c["eco"].ret, 1), "rto_rate_pct": round(100 * c["eco"].rto, 1),
                    "cogs": round(c["eco"].cogs), "break_even": round(c["eco"].break_even()),
                    "fair_price": round(c["fair"]), "market_p25": int(c["summary"]["price_p25"]),
                    "market_p75": int(c["summary"]["price_p75"]),
                    "outdated_score": round(c["outdated"], 2), "days_of_cover": _r(c["cover"]),
                    "now": _pack(n), "recommended": _pack(w),
                    "profit_uplift_30d": round(w["profit"] - n["profit"]),
                    "reasons": (self._new_reasons(c, launch) if c["is_new"] else
                                ([{"icon": "wait", "tone": "neutral",
                                   "text": f"You changed this price on {c['changed_on']}. Give it ~14 days of sales at the new price "
                                           f"before changing again - the agent will re-check then."}] if c.get("changed_on") else [])
                                + self._reasons(c, n, w, sibs)),
                    "changed_on": c.get("changed_on"),
                    "rival": c["top_rival"], "launch_plan": launch and {
                        "entry_price": launch.get("entry_price"), "steady_price": launch.get("steady_price"),
                        "break_even": launch.get("break_even_price")},
                    "history": [{"date": r["date"], "orders": r["ord"], "price": r["price"]} for r in c["series"]],
                })
            variants.sort(key=lambda v: -v["orders_per_day_28d"])
            first = cs[0]
            out_groups.append({
                "catalog_id": cat_id, "name": names.get(cat_id, first["p"]["title"]),
                "attributes": {k: _label(k, first["attrs"][k]) for k in ("product_type", "fabric", "pattern", "occasion")},
                "variants": variants,
                "profit_uplift_30d": round(sum(v["profit_uplift_30d"] for v in variants)),
                "has_variant_play": len(variants) > 1 and len({v["action"] for v in variants}) > 1,
            })
        out_groups.sort(key=lambda g: -abs(g["profit_uplift_30d"]))
        summary = {
            "listings": len(ctxs), "designs": len(out_groups), "stock_units": int(tot["stock_units"]),
            "stock_value": round(tot["stock_value"]), "orders_30d": round(tot["orders_30d"]),
            "revenue_30d": round(tot["revenue_30d"]), "profit_next_30d_now": round(tot["profit_now"]),
            "profit_next_30d_recommended": round(tot["profit_new"]),
            "profit_uplift": round(tot["profit_new"] - tot["profit_now"]), "changes": int(tot["changes"]),
            "ageing_units": int(tot["old_units"]),
        }
        return dict(base, summary=summary, groups=out_groups, rivals=self._rivals(seller_id, prods, demo_ids))

    def _contexts(self, prods, today, ctx_seller):
        """Per-listing demand + economics context for a seller's live listings."""
        m = self.m
        series, inv, recs, names, changed = self._metrics([p["product_id"] for p in prods])
        ctxs = [self._analyse(p, series.get(p["product_id"], []), inv.get(p["product_id"], 0), today, ctx_seller)
                for p in prods]
        for c in ctxs:
            last = changed.get(c["p"]["product_id"])
            c["changed_on"] = last if last and date.fromisoformat(last) > m.snapshot - timedelta(days=14) else None
            c["design"] = names.get(c["p"]["catalog_id"], c["p"]["title"])
        return ctxs, recs, names

    def seller_contexts(self, seller_id):
        """(seller dict, contexts) - used by the sale planner."""
        m = self.m
        try:
            seller_id = int(seller_id)
        except (TypeError, ValueError):
            raise InputError("Pick a seller.")
        if seller_id not in m.sellers:
            raise InputError("Seller not found.")
        today = m.snapshot + timedelta(days=1)
        demo_ids = {s["seller_id"] for s in m.sellers.values() if s["is_demo_seller"]}
        prods = [p for p in m.products if p["seller_id"] == seller_id and p["status"] == "active"]
        hist = m.seller_history(seller_id, {k: None for k in ATTRS})
        ctx_seller = {"ctr_factor": hist["ctr_factor"] if hist else 1.0, "demo_ids": demo_ids}
        ctxs = self._contexts(prods, today, ctx_seller)[0] if prods else []
        return m.sellers[seller_id], ctxs

    def find_variant(self, product_id, mode="balanced"):
        """(variant, design name, seller name, goal label) for one live listing, or None."""
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return None
        prod = next((p for p in self.m.products if p["product_id"] == product_id and p["status"] == "active"), None)
        if prod is None:
            return None
        data = self.seller_listings(prod["seller_id"], mode if mode in config.MODES else "balanced")
        for g in data["groups"]:
            for v in g["variants"]:
                if v["product_id"] == product_id:
                    return v, g["name"], data["seller"]["name"], data["mode_label"]
        return None

    def _new_reasons(self, c, launch):
        out = [{"icon": "new", "tone": "neutral",
                "text": "Just listed - there isn't enough sales data yet. Keep the launch price so the first orders and reviews come in."}]
        if launch and launch.get("steady_price") and launch["steady_price"] > c["p0"]:
            out.append({"icon": "plan", "tone": "positive",
                        "text": f"Plan from launch: move to ₹{launch['steady_price']} after 20-25 good reviews."})
        if c["top_rival"]:
            r = c["top_rival"]
            out.append({"icon": "rival", "tone": "neutral",
                        "text": f"Closest rival: {r['seller']} sells “{r['title']}” at ₹{r['price']} ({r['orders_per_day']} orders/day)."})
        return out

    @staticmethod
    def _stage(c):
        if c["age"] < 0:
            return "Scheduled"
        if c["is_new"]:
            return "New"
        if c["is_old"]:
            return "Ageing"
        if c["trend"] is not None and c["trend"] >= 1.15:
            return "Growing"
        if c["trend"] is not None and c["trend"] <= 0.8:
            return "Slowing"
        return "Mature"

    def _rivals(self, seller_id, prods, demo_ids):
        """Other demo sellers competing with this seller, and how."""
        m = self.m
        out = []
        for sid in sorted(demo_ids):
            if sid == seller_id:
                continue
            theirs = [q for q in m.active if q["seller_id"] == sid]
            if not theirs:
                continue
            overlap = []
            for q in theirs:
                best = max((similarity({k: p[k] for k in ATTRS}, q) for p in prods), default=0)
                if best >= 0.7:
                    overlap.append(q)
            s = m.sellers[sid]
            top = max(overlap or theirs, key=lambda q: q["daily_orders"])
            out.append({
                "seller_id": sid, "name": s["seller_name"], "city": s["city"], "tier": s["tier"],
                "listings": len(theirs), "overlapping": len(overlap),
                "avg_price_overlap": round(sum(q["current_price"] for q in overlap) / len(overlap)) if overlap else None,
                "orders_per_day_overlap": round(sum(q["daily_orders"] for q in overlap), 1),
                "top_listing": {"title": top["title"], "price": top["current_price"],
                                "orders_per_day": round(top["daily_orders"], 1)},
            })
        out.sort(key=lambda r: -r["overlapping"])
        return out


def _r(x):
    return None if x is None else round(min(x, 999), 1)


def _pack(r):
    return {"price": r["price"], "orders_per_day": round(r["orders_per_day"], 2), "orders_30d": round(r["orders"], 1),
            "profit_per_order": round(r["profit_per_order"], 1), "sales_profit_30d": round(r["sales_profit"]),
            "stock_cost_30d": round(r["stock_cost"]), "profit_30d": round(r["profit"]),
            "margin_pct": round(100 * r["margin"], 1), "days_to_clear": _r(r["days_to_clear"]),
            "stockout_days": round(r["stockout_days"], 1), "leftover_units": round(r["leftover"])}


def _label(attr, value):
    from .engine import _label as lbl
    return lbl(attr, value)
