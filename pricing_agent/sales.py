"""
Sale planner: for a sale event, how deep should each live listing be discounted - or should it stay out?

Uses each listing's own demand model from the repricer (level, price sensitivity, fair price,
economics) and adds sale behaviour:
  * listings that join get the sale's traffic (e.g. 3x) plus the sale badge,
  * listings that stay out only get a little spill-over traffic,
  * sale shoppers compare prices harder (higher price sensitivity),
  * joining needs at least the event's minimum discount,
  * no restocking during a short sale: orders are capped by stock on hand.
Each discount is scored on sale profit plus the value of freeing up stock (which matters most for
ageing stock), and compared with staying out.
"""
import math
from datetime import timedelta

from . import config, signals
from .engine import InputError, Scenario
from .stats import clip

DISCOUNT_STEPS = [0.05 * i for i in range(1, 9)]      # 5% ... 40%


def _price_at(p0, d):
    """Price ending in 9 that is at least d below p0."""
    return int(math.floor(p0 * (1 - d) / 10.0)) * 10 - 1


def event_list():
    return [{"key": e["key"], "name": e["name"], "start": e["start"].isoformat(),
             "end": (e["start"] + timedelta(days=e["days"] - 1)).isoformat(), "days": e["days"],
             "traffic": e["traffic"], "min_discount_pct": round(100 * e["min_discount"])} for e in config.SALE_EVENTS]


def plan(repricer, seller_id, event_key):
    ev = next((e for e in config.SALE_EVENTS if e["key"] == event_key), None)
    if ev is None:
        raise InputError("Unknown sale event.")
    seller, ctxs = repricer.seller_contexts(seller_id)
    items = [_plan_one(c, ev) for c in ctxs]
    items.sort(key=lambda x: -(x["recommended"]["score"] - x["skip"]["score"]))
    join = [x for x in items if x["decision"] == "join"]
    pick = lambda x: x["recommended"] if x["decision"] == "join" else x["skip"]
    summary = {
        "listings": len(items), "joining": len(join),
        "sale_profit": round(sum(pick(x)["profit"] for x in items)),
        "profit_if_all_stay_out": round(sum(x["skip"]["profit"] for x in items)),
        "stock_value_freed": round(sum(x["recommended"]["stock_value_freed"] - x["skip"]["stock_value_freed"] for x in join)),
        "net_gain": round(sum(x["recommended"]["net"] - x["skip"]["net"] for x in join)),
        "units_sold": round(sum((x["recommended"] if x["decision"] == "join" else x["skip"])["units"] for x in items)),
        "ageing_units_cleared": round(sum(x["recommended"]["units"] for x in join if x["stage"] == "Ageing")),
    }
    for x in items:   # the score is internal
        for k in ("skip", "recommended"):
            x[k].pop("score", None)
        for o in x["options"]:
            o.pop("score", None)
    return {"event": next(e for e in event_list() if e["key"] == event_key), "events": event_list(),
            "seller": {"seller_id": seller["seller_id"], "name": seller["seller_name"]}, "summary": summary, "items": items}


def _plan_one(c, ev):
    p = c["p"]
    eco, fair, stock = c["eco"], c["fair"], c["stock"]
    p0 = c["p0"]
    days = ev["days"]
    win = signals.window_average(ev["start"], days, p["fabric"], p["occasion"])["combined"]
    adj = Scenario._season_adj
    b_sale = c["b"] * adj(win) / adj(c["hist"]) * c["crowd_adj"] * config.SALE_DEAL_SENSITIVITY
    level = c["level"]
    u = eco.units_per_order
    free_value = eco.cogs * c["holding"]           # value of each piece we no longer have to carry

    def outcome(price, joined):
        uplift = ev["traffic"] * config.SALE_BADGE_UPLIFT if joined else config.SALE_SPILLOVER
        q = level * win * uplift * math.exp(-b_sale * (price / fair - 1))
        orders = min(q * days, stock / u) if stock > 0 else 0.0
        units = orders * u
        pi = eco.profit(price)
        sells_out_day = (stock / (q * u)) if q > 0 and stock / (q * u) < days else None
        profit = pi * orders
        freed = free_value * units
        return {"price": price, "discount_pct": round(100 * (1 - price / p0)), "orders_per_day": round(q, 1),
                "orders": round(orders), "units": round(units), "profit_per_order": round(pi, 1),
                "margin_pct": round(100 * eco.margin(price), 1), "profit": round(profit),
                "stock_value_freed": round(freed), "net": round(profit + freed),
                "stock_left": max(0, round(stock - units)), "sells_out_day": round(sells_out_day, 1) if sells_out_day else None,
                "score": profit + freed}

    skip = outcome(p0, False)
    floor = (lambda x: eco.profit(x) >= -0.3 * eco.cogs) if c["is_old"] else (lambda x: eco.profit(x) >= 1)
    options = []
    for d in DISCOUNT_STEPS:
        if d + 1e-9 < ev["min_discount"]:
            continue
        price = _price_at(p0, d)
        if price < 49 or 1 - price / p0 > 0.405 or any(o["price"] == price for o in options):
            continue
        o = outcome(price, True)
        o["allowed"] = floor(price)
        options.append(o)
    allowed = [o for o in options if o["allowed"]]
    best = max(allowed, key=lambda o: (o["score"], -o["discount_pct"])) if allowed else None
    decision = "join" if best and best["score"] > skip["score"] + 1 else "skip"
    rec = best if decision == "join" else skip
    return {
        "product_id": p["product_id"], "title": p["title"], "color": p["color"], "design": c["design"],
        "pattern": p["pattern"], "stage": "Ageing" if c["is_old"] else ("New" if c["is_new"] else "Live"),
        "stock": stock, "current_price": p0, "break_even": round(eco.break_even()),
        "decision": decision, "label": _label(decision, rec, skip, c, ev, best),
        "reason": _reason(decision, rec, skip, c, ev, best, stock, days),
        "skip": skip, "recommended": rec, "options": options, "after_sale_price": p0,
    }


def _label(decision, rec, skip, c, ev, best):
    if decision == "skip":
        return "Stay out"
    if c["is_old"]:
        return f"Clear at {rec['discount_pct']}% off"
    return f"Join at {rec['discount_pct']}% off"


def _reason(decision, rec, skip, c, ev, best, stock, days):
    inr = lambda x: ("-₹" if x < 0 else "₹") + f"{abs(round(x)):,}"
    if decision == "join":
        head = (f"Sale traffic is about {ev['traffic']:g}× normal. At {inr(rec['price'])} ({rec['discount_pct']}% off) you sell "
                f"~{rec['orders']} in {days} days vs ~{skip['orders']} if you stay out.")
        d_profit = rec["profit"] - skip["profit"]
        d_units = rec["units"] - skip["units"]
        if d_profit >= 0:
            txt = f"{head} Profit {inr(rec['profit'])}, {inr(d_profit)} more than staying out."
        elif c["is_old"]:
            txt = (f"{head} Each piece loses {inr(-rec['profit_per_order'])}, but clearing {d_units} more pieces of ageing stock "
                   f"saves ~{inr(rec['stock_value_freed'] - skip['stock_value_freed'])} that it would otherwise lose. "
                   f"Net {inr(rec['net'] - skip['net'])} better than staying out.")
        else:
            txt = (f"{head} You earn {inr(-d_profit)} less during the sale, but move {d_units} more pieces of slow stock "
                   f"(~{inr(rec['stock_value_freed'] - skip['stock_value_freed'])} of cash freed). Net {inr(rec['net'] - skip['net'])} better.")
        if rec["sells_out_day"]:
            txt += f" Your {stock} pieces run out around day {rec['sells_out_day']:g}, so a deeper discount would only give away margin."
        return txt
    if best is None:
        return (f"Joining needs at least {round(100 * ev['min_discount'])}% off, which would take this kurti below "
                f"its break-even of {inr(c['eco'].break_even())}. Stay at {inr(skip['price'])}.")
    if skip["sells_out_day"] or stock <= skip["units"] + 1:
        return f"Only {stock} pieces left - they sell out at full price even without the sale. Keep {inr(skip['price'])}."
    return (f"At the {round(100 * ev['min_discount'])}% minimum discount each order earns {inr(best['profit_per_order'])} vs "
            f"{inr(skip['profit_per_order'])} at full price. Staying out earns more ({inr(skip['profit'])} vs {inr(best['profit'])}).")
