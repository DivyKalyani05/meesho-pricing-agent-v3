"""
Builds a synthetic but realistic Meesho-style marketplace for the Kurti category.

The data is generated from an explicit "ground truth" demand model
(funnel: impressions -> CTR -> conversion) so that the pricing engine can be
checked: it should *recover* price sensitivity and seasonality from the data
without being told them.

Run:  python -m pricing_agent.seed   (or just `python run.py`, which seeds if needed)
"""
import math
import os
import random
import sqlite3
import time
from datetime import date, timedelta

from . import config, signals

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(HERE), "data", "meesho_kurtis.db")

SEED = 20260928
N_COMPETITOR_SELLERS = 260

# Ground-truth price sensitivity by occasion (the engine never reads these).
TRUE_SENSITIVITY = {"daily": 3.6, "office": 3.2, "festive": 2.6, "party": 2.8}

SCHEMA_VERSION = 4

# Demo sellers with hand-designed catalogues. Each variant = (colour, popularity, units in stock).
# Rangreza and Sanganeri compete head-on in Jaipur cotton; Surat Silk Mart and Lucknow Chikan Studio
# overlap in georgette / festive wear - so the sellers show up in each other's competitor lists.
DEMO_SELLERS = [
    (1, "Rangreza Prints", "Jaipur", 0.45, 1.35, 900, [
        dict(name="Dabu Block Print Kurti", type="kurti", fabric="cotton", pattern="block_print", occasion="daily",
             sleeve="three_quarter", length="knee", age=150, rel=0.98,
             variants=[("Indigo", 1.0, 18), ("Maroon", -0.6, 230)]),          # one colour flies, one is stuck
        dict(name="Sanganeri Floral Kurti with Palazzo", type="kurti_bottom", fabric="cotton", pattern="block_print",
             occasion="office", sleeve="three_quarter", length="calf", age=95, rel=0.84,
             variants=[("Mustard", 0.35, 120), ("White", 0.25, 110)]),         # underpriced vs market
        dict(name="Summer Mulmul Short Kurti", type="kurti", fabric="cotton", pattern="printed", occasion="daily",
             sleeve="short", length="short", age=320, rel=1.04, decay=0.18,
             variants=[("Yellow", -0.25, 210), ("Sky Blue", -0.35, 190), ("Peach", -0.3, 160)]),  # outdated stock
        dict(name="Bagru Print Festive Anarkali", type="anarkali", fabric="cotton", pattern="block_print",
             occasion="festive", sleeve="full", length="calf", age=70, rel=0.97,
             variants=[("Red", 0.5, 60), ("Green", 0.4, 55)]),                  # Navratri upside
        dict(name="Chanderi Printed Office Kurti", type="kurti", fabric="chanderi", pattern="printed", occasion="office",
             sleeve="three_quarter", length="knee", age=110, rel=1.0,
             variants=[("Off White", 0.7, 9)]),                                  # bestseller about to stock out
        dict(name="Khadi Solid Kurta Set", type="kurta_set_dupatta", fabric="khadi", pattern="solid", occasion="office",
             sleeve="full", length="calf", age=45, rel=1.24,
             variants=[("Grey", -0.1, 80)]),                                     # overpriced
    ]),
    (2, "Surat Silk Mart", "Surat", 0.0, 0.95, 700, [
        dict(name="Georgette Mirror Work Party Kurti", type="kurti", fabric="georgette", pattern="mirror_work",
             occasion="party", sleeve="sleeveless", length="knee", age=120, rel=0.93,
             variants=[("Black", 0.45, 70), ("Wine", 0.3, 65)]),
        dict(name="Silk Blend Embroidered Kurta Set with Dupatta", type="kurta_set_dupatta", fabric="silk_blend",
             pattern="embroidered", occasion="festive", sleeve="full", length="calf", age=60, rel=0.92,
             variants=[("Maroon", 0.8, 15), ("Teal", -0.5, 150), ("Pink", 0.1, 50)]),
        dict(name="Rayon Printed Kurti with Palazzo", type="kurti_bottom", fabric="rayon", pattern="printed",
             occasion="office", sleeve="three_quarter", length="knee", age=200, rel=1.14,
             variants=[("Navy Blue", -0.1, 100), ("Green", -0.2, 100)]),         # overpriced, low conversion
        dict(name="Crepe Printed Daily Kurti", type="kurti", fabric="crepe", pattern="printed", occasion="daily",
             sleeve="three_quarter", length="knee", age=380, rel=1.0, decay=0.2,
             variants=[("Pink", -0.6, 250), ("Grey", -0.7, 240)]),              # outdated stock
    ]),
    (3, "Naya Kurti House (new seller)", "Lucknow", 0.0, 1.0, 20, []),
    (4, "Sanganeri Cotton Co.", "Jaipur", 0.15, 1.05, 650, [
        dict(name="Jaipuri Hand Block Print Kurti", type="kurti", fabric="cotton", pattern="block_print", occasion="daily",
             sleeve="three_quarter", length="knee", age=200, rel=0.9,
             variants=[("Indigo", 0.55, 80), ("Pink", 0.2, 70)]),
        dict(name="Hand Block Kurti with Pant", type="kurti_bottom", fabric="cotton", pattern="block_print",
             occasion="office", sleeve="three_quarter", length="calf", age=130, rel=0.95,
             variants=[("Mustard", 0.2, 90), ("Teal", 0.0, 60)]),
        dict(name="Cotton Printed Short Kurti", type="kurti", fabric="cotton", pattern="printed", occasion="daily",
             sleeve="short", length="short", age=280, rel=1.0, decay=0.15,
             variants=[("White", -0.4, 150)]),
        dict(name="Festive Mirror Work Anarkali", type="anarkali", fabric="cotton", pattern="mirror_work",
             occasion="festive", sleeve="full", length="calf", age=50, rel=0.97,
             variants=[("Red", 0.6, 25), ("Yellow", -0.4, 110)]),
    ]),
    (5, "Lucknow Chikan Studio", "Lucknow", 0.3, 1.2, 800, [
        dict(name="Lucknowi Chikankari Cotton Kurti", type="kurti", fabric="cotton", pattern="chikankari",
             occasion="office", sleeve="three_quarter", length="calf", age=160, rel=1.02,
             variants=[("White", 0.9, 30), ("Peach", 0.1, 80), ("Sky Blue", -0.3, 120)]),
        dict(name="Georgette Chikankari Anarkali", type="anarkali", fabric="georgette", pattern="chikankari",
             occasion="festive", sleeve="full", length="calf", age=90, rel=0.9,
             variants=[("Pink", 0.5, 40), ("Lavender", 0.3, 45)]),
        dict(name="Chikankari Kurta Set with Dupatta", type="kurta_set_dupatta", fabric="cotton", pattern="chikankari",
             occasion="festive", sleeve="three_quarter", length="calf", age=40, rel=1.0,
             variants=[("Off White", 0.3, 35)]),
        dict(name="Rayon Chikan Straight Kurti", type="kurti", fabric="rayon", pattern="chikankari", occasion="daily",
             sleeve="three_quarter", length="knee", age=300, rel=1.08, decay=0.15,
             variants=[("Black", -0.6, 140), ("Mustard", -0.5, 150)]),
    ]),
]


def needs_rebuild(db_path: str = DB_PATH) -> bool:
    if not os.path.exists(db_path):
        return True
    try:
        con = sqlite3.connect(db_path)
        v = con.execute("PRAGMA user_version").fetchone()[0]
        con.close()
        return v != SCHEMA_VERSION
    except sqlite3.DatabaseError:
        return True


CITIES = {
    # city: (state, fabric weights, pattern weights)
    "Jaipur": ("Rajasthan", {"cotton": 6, "rayon": 2, "chanderi": 1}, {"block_print": 5, "printed": 4, "mirror_work": 1}),
    "Surat": ("Gujarat", {"georgette": 4, "rayon": 4, "crepe": 3, "silk_blend": 3}, {"printed": 5, "embroidered": 3, "mirror_work": 2, "solid": 1}),
    "Lucknow": ("Uttar Pradesh", {"cotton": 5, "georgette": 3, "rayon": 1}, {"chikankari": 7, "embroidered": 2, "solid": 1}),
    "Kolkata": ("West Bengal", {"cotton": 5, "khadi": 3, "silk_blend": 1}, {"printed": 4, "solid": 2, "embroidered": 2}),
    "Delhi": ("Delhi", {"rayon": 5, "cotton": 4, "georgette": 2}, {"printed": 6, "embroidered": 2, "solid": 2}),
    "Ahmedabad": ("Gujarat", {"cotton": 5, "rayon": 3}, {"mirror_work": 4, "printed": 4, "block_print": 2}),
    "Ludhiana": ("Punjab", {"rayon": 4, "khadi": 3, "cotton": 2}, {"embroidered": 4, "printed": 3, "solid": 2}),
    "Tiruppur": ("Tamil Nadu", {"cotton": 8, "rayon": 2}, {"solid": 4, "printed": 5}),
    "Indore": ("Madhya Pradesh", {"chanderi": 4, "cotton": 3, "silk_blend": 3}, {"printed": 3, "embroidered": 3, "block_print": 1}),
    "Mumbai": ("Maharashtra", {"crepe": 4, "rayon": 4, "georgette": 3}, {"printed": 5, "solid": 3, "embroidered": 1}),
}

NAME_A = ["Shree", "Radhe", "Krishna", "Maa", "Jai", "Sai", "Om", "Laxmi", "Kavya", "Anaya", "Riddhi", "Aarohi",
          "Meera", "Rangoli", "Suta", "Vastra", "Neel", "Gulabo", "Chhavi", "Tanvi", "Ishita", "Nandini", "Saanvi", "Rudra"]
NAME_B = ["Fashion", "Creations", "Textiles", "Trends", "Enterprises", "Collections", "Handicrafts", "Boutique",
          "Clothing", "Prints", "Ethnics", "Garments"]
COLORS = ["Maroon", "Navy Blue", "Mustard", "Pink", "Black", "White", "Green", "Red", "Peach", "Sky Blue", "Yellow",
          "Wine", "Teal", "Lavender", "Off White", "Orange", "Grey", "Magenta"]
REVIEW_TEXT = {
    "good_quality": ["Fabric quality is very good", "Nice quality, same as picture", "Good stitching and soft fabric"],
    "value_for_money": ["Value for money", "Worth the price", "Very good at this price"],
    "nice_color": ["Colour is beautiful", "Lovely colour, got compliments", "Colour exactly as shown"],
    "perfect_fit": ["Perfect fitting", "Size is perfect", "Fits well, comfortable"],
    "size_issue": ["Size is smaller than chart", "Too loose, size chart is wrong", "Fitting not proper"],
    "fabric_thin": ["Fabric is very thin", "Transparent fabric, need inner", "Cloth quality is poor"],
    "color_mismatch": ["Colour different from photo", "Colour faded after one wash", "Shade is dull in real"],
    "stitching": ["Stitching came out", "Loose threads everywhere", "Poor finishing"],
}
POSITIVE_THEMES = ["good_quality", "value_for_money", "nice_color", "perfect_fit"]
NEGATIVE_THEMES = ["size_issue", "fabric_thin", "color_mismatch", "stitching"]


# ------------------------------------------------------------------ helpers
def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 40:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(1 for _ in range(n) if rng.random() < p)


def weighted_choice(rng: random.Random, weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def price_ending_9(x: float) -> int:
    """Round to the nearest price ending in 9 (e.g. 347 -> 349, 352 -> 349)."""
    return max(99, int(round((x + 1) / 10.0)) * 10 - 1)


def fair_price(ptype: str, fabric: str, pattern: str) -> float:
    """Ground-truth 'what these attributes are worth' (hidden from the engine)."""
    cost = config.FABRICS[fabric][3] * config.PRODUCT_TYPES[ptype][1] * config.PATTERNS[pattern][1]
    return cost * 1.55 + 70


def package_for(ptype: str, fabric: str):
    weight = config.PRODUCT_TYPES[ptype][2] * config.FABRICS[fabric][2]
    size = "S" if weight < 260 else ("M" if weight < 450 else "L")
    return int(round(weight)), size


def pick_occasion(rng, fabric, pattern):
    if fabric in ("silk_blend", "chanderi") or pattern in ("mirror_work", "embroidered"):
        w = {"festive": 5, "party": 3, "office": 1, "daily": 1}
    elif pattern == "chikankari":
        w = {"festive": 3, "office": 3, "daily": 3, "party": 1}
    else:
        w = {"daily": 5, "office": 3, "festive": 1.5, "party": 0.5}
    return weighted_choice(rng, w)


def make_title(fabric, pattern, ptype, color, occasion):
    words = [color, config.FABRICS[fabric][0], config.PATTERNS[pattern][0], config.PRODUCT_TYPES[ptype][0]]
    if occasion in ("festive", "party"):
        words.insert(0, "Trendy" if occasion == "party" else "Festive")
    return " ".join(words).replace("  ", " ")


# ------------------------------------------------------------------ build
def build(db_path: str = DB_PATH, verbose: bool = True) -> str:
    t0 = time.time()
    rng = random.Random(SEED)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    tmp_path = db_path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    con = sqlite3.connect(tmp_path)
    with open(os.path.join(HERE, "schema.sql")) as f:
        con.executescript(f.read())

    snapshot = config.SNAPSHOT_DATE
    window_start = snapshot - timedelta(days=config.HISTORY_DAYS - 1)
    days = [window_start + timedelta(days=i) for i in range(config.HISTORY_DAYS)]

    # --- reference tables
    con.execute("INSERT INTO categories VALUES (1, NULL, 1, 'Women Ethnic', NULL, 0.05, NULL, NULL, NULL)")
    con.execute("INSERT INTO categories VALUES (2, 1, 2, 'Kurtis & Kurta Sets', NULL, 0.05, NULL, NULL, NULL)")
    cat_id = {}
    for i, (key, (name, _, _)) in enumerate(config.PRODUCT_TYPES.items()):
        cid = 10 + i
        cat_id[key] = cid
        ret, rto = config.CATEGORY_RETURN_PRIORS[key]
        con.execute("INSERT INTO categories VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, 2, 3, name, key, config.GST_RATE, ret, rto, config.TRANSIT_LOSS[key]))
    con.executemany("INSERT INTO shipping_rate_card VALUES (?,?,?)", config.SHIPPING_SLABS)
    con.executemany("INSERT INTO packaging_rate_card VALUES (?,?,?,?)",
                    [(k, v[0], v[1], v[2]) for k, v in config.PACKAGING.items()])
    con.executemany("INSERT INTO festival_calendar VALUES (?,?,?,?,?)",
                    [(n, d.isoformat(), u, l, b) for n, d, u, l, b in config.FESTIVALS])
    con.executemany("INSERT INTO fabric_seasonality VALUES (?,?,?)",
                    [(f, m + 1, v) for f, vals in config.FABRIC_SEASON.items() for m, v in enumerate(vals)])

    # --- sellers
    sellers = []   # (id, name, city, quality, ctr_skill, age_days, n_products, catalog_specs, is_demo)
    used_names = set()
    for sid, name, city, q, ctr, age_days, specs in DEMO_SELLERS:
        sellers.append((sid, name, city, q, ctr, age_days, 0, specs, True))
        used_names.add(name)
    sid = 100
    for _ in range(N_COMPETITOR_SELLERS):
        city = rng.choice(list(CITIES))
        while True:
            name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}"
            if name in used_names:
                name = f"{name} {city}"
            if name not in used_names:
                break
        used_names.add(name)
        q = rng.gauss(0, 0.5)
        ctr = math.exp(rng.gauss(0, 0.18))
        n = max(2, int(rng.lognormvariate(1.95, 0.55)))
        sellers.append((sid, name, city, q, ctr, rng.randint(120, 1400), n, None, False))
        sid += 1

    seller_rows = []
    for s_id, name, city, q, ctr, age_days, n, specs, is_demo in sellers:
        joined = snapshot - timedelta(days=age_days)
        tier = "new" if age_days < 90 else ("gold" if q > 0.4 and age_days > 500 else ("silver" if q > -0.2 else "bronze"))
        rating = round(min(4.8, max(3.1, 3.95 + 0.45 * q + rng.gauss(0, 0.08))), 1)
        seller_rows.append((s_id, name, city, CITIES[city][0], tier, rating, joined.isoformat(), int(is_demo)))
    con.executemany("INSERT INTO sellers VALUES (?,?,?,?,?,?,?,?)", seller_rows)

    # --- catalogue
    products, catalogs, inventory, price_hist, metrics, reviews = [], [], [], [], [], []
    counters = {"pid": 1000, "rid": 1}

    def emit_product(catalog_id, s_id, s_q, s_ctr, is_demo, ptype, fabric, pattern, occasion, sleeve, length,
                     color, listed, rel_pos, popularity, quality, stock, n_images, decay=0.0, name=None):
        """Generate one listing plus its full history (prices, daily funnel, reviews)."""
        pid = counters["pid"]
        counters["pid"] += 1
        weight, pkg = package_for(ptype, fabric)
        fp = fair_price(ptype, fabric, pattern)
        cogs_true = fp * rng.uniform(0.58, 0.66)   # sellers pay no delivery on kept orders, so making cost is ~60% of price
        final_price = price_ending_9(fp * rel_pos)
        sizes = rng.choice(["S,M,L,XL,XXL", "M,L,XL,XXL", "S,M,L,XL,XXL,3XL", "Free Size"])
        title = f"{color} {name}" if name else make_title(fabric, pattern, ptype, color, occasion)
        desc = (f"{title}. {config.SLEEVES[sleeve]}, {config.LENGTHS[length].lower()}, "
                f"ideal for {config.OCCASIONS[occasion].lower()}. Sizes: {sizes}.")
        mrp = int(round(final_price * rng.uniform(1.8, 3.0), -1)) - 1
        status = "active" if is_demo or rng.random() > 0.04 else "paused"
        age_at_snapshot = (snapshot - listed).days
        photo_factor = {1: 0.72, 2: 0.85, 3: 0.95}.get(n_images, 1.0 + 0.03 * min(n_images - 4, 3))
        base_ret, base_rto = config.CATEGORY_RETURN_PRIORS[ptype]
        ret_rate = min(0.45, max(0.05, base_ret * (1 - 0.45 * quality) * (1.1 if sizes == "Free Size" else 1.0)))
        rto_rate = min(0.25, max(0.04, base_rto * (1 - 0.2 * quality)))
        b_true = TRUE_SENSITIVITY[occasion]

        # price path during the window: start price, then 0-3 changes, ending at final_price
        n_changes = rng.choice([0, 0, 1, 1, 2, 3])
        change_days = sorted(rng.sample(range(10, config.HISTORY_DAYS - 35 if is_demo else config.HISTORY_DAYS - 5), n_changes))
        path = [final_price]
        for _c in range(n_changes):
            path.insert(0, price_ending_9(path[0] * math.exp(rng.gauss(0, 0.07))))
        first_day = max(window_start, listed)
        price_hist.append((pid, listed.isoformat(), path[0]))
        for cd, p_new in zip(change_days, path[1:]):
            d = window_start + timedelta(days=cd)
            if d > listed:
                price_hist.append((pid, d.isoformat(), p_new))

        pre_days = max(0, (window_start - listed).days)
        base_daily = 2.1 * math.exp(popularity) * photo_factor * s_ctr
        review_count = poisson(rng, base_daily * pre_days * 0.035)

        price_idx = 0
        current = path[0]
        if status == "active":
            for d in days:
                if d < first_day:
                    continue
                while price_idx < len(change_days) and d >= window_start + timedelta(days=change_days[price_idx]):
                    price_idx += 1
                    current = path[price_idx]
                age = (d - listed).days
                age_ramp = min(1.0, 0.35 + age / 30.0)
                mult = signals.demand_multiplier(d, fabric, occasion)
                b_eff = b_true * min(1.15, max(0.7, 1 - 0.35 * (mult - 1)))
                rel = current / fp
                rating_now = 3.9 + 0.5 * quality
                pop_now = popularity - decay * (d - window_start).days / 30.0   # ageing designs lose appeal
                impressions = poisson(rng, 950 * age_ramp * mult * math.exp(pop_now) * rng.uniform(0.85, 1.15))
                ctr = 0.031 * s_ctr * photo_factor * (1 + 0.08 * (rating_now - 4)) * math.exp(-0.6 * (rel - 1))
                clicks = poisson(rng, impressions * min(0.2, ctr))
                cvr = 0.072 * math.exp(-(b_eff - 0.6) * (rel - 1)) * (1 + review_count) ** 0.08 * math.exp(0.25 * quality)
                orders = poisson(rng, clicks * min(0.5, cvr))
                returns = binomial(rng, orders, ret_rate)
                rto = binomial(rng, orders - returns, rto_rate / (1 - ret_rate))
                review_count += binomial(rng, orders - returns - rto, 0.035)
                metrics.append((pid, d.isoformat(), current, impressions, clicks, orders, returns, rto))

        mean_rating = min(4.7, max(2.6, 3.85 + 0.55 * quality))
        for _r in range(review_count):
            stars = int(min(5, max(1, round(rng.gauss(mean_rating, 0.95)))))
            if stars >= 4:
                theme = rng.choice(POSITIVE_THEMES)
            elif stars == 3:
                theme = rng.choice(POSITIVE_THEMES + NEGATIVE_THEMES)
            else:
                theme = weighted_choice(rng, {"size_issue": 4 if ptype != "kurti" else 3,
                                              "fabric_thin": 3 if fabric in ("cotton", "georgette", "rayon") else 1,
                                              "color_mismatch": 2, "stitching": max(0.2, 1.5 - quality)})
            r_date = snapshot - timedelta(days=rng.randint(0, max(0, age_at_snapshot)))
            reviews.append((counters["rid"], pid, stars, theme, rng.choice(REVIEW_TEXT[theme]), r_date.isoformat()))
            counters["rid"] += 1

        cogs = int(round(cogs_true)) if is_demo else None
        products.append((pid, catalog_id, s_id, cat_id[ptype], title, desc, fabric, pattern, sleeve, length,
                         occasion, color, sizes, n_images, weight, pkg, mrp, final_price, cogs,
                         listed.isoformat(), status, None, "seed"))
        inventory.append((pid, stock, snapshot.isoformat()))

    cid_counter = 5000
    for s_id, name, city, s_q, s_ctr, age_days, n_products, specs, is_demo in sellers:
        if is_demo:
            # hand-designed catalogues so the demo shows every repricing situation
            for spec in specs:
                created = snapshot - timedelta(days=spec["age"])
                catalogs.append((cid_counter, s_id, spec["name"], created.isoformat()))
                for color, pop, stock in spec["variants"]:
                    emit_product(cid_counter, s_id, s_q, s_ctr, True, spec["type"], spec["fabric"], spec["pattern"],
                                 spec["occasion"], spec["sleeve"], spec["length"], color, created,
                                 spec["rel"] * math.exp(rng.gauss(0, 0.02)), pop,
                                 0.6 * s_q + spec.get("quality", 0.0) + rng.gauss(0, 0.1), stock, 5,
                                 decay=spec.get("decay", 0.0), name=spec["name"])
                cid_counter += 1
            continue
        fab_w, pat_w = CITIES[city][1], CITIES[city][2]
        made = 0
        while made < n_products:
            cat_size = min(n_products - made, rng.randint(2, 5))
            ptype = weighted_choice(rng, {"kurti": 45, "kurti_bottom": 25, "kurta_set_dupatta": 20, "anarkali": 10})
            fabric = weighted_choice(rng, fab_w) if rng.random() < 0.8 else rng.choice(list(config.FABRICS))
            pattern = weighted_choice(rng, pat_w) if rng.random() < 0.8 else rng.choice(list(config.PATTERNS))
            if pattern == "chikankari" and fabric not in ("cotton", "georgette", "rayon"):
                pattern = "embroidered"
            occasion = pick_occasion(rng, fabric, pattern)
            # a catalogue = one design in several colours (same sleeve / length)
            sleeve = weighted_choice(rng, {"three_quarter": 55, "full": 15, "short": 20, "sleeveless": 10})
            length = weighted_choice(rng, {"knee": 45, "calf": 40, "short": 15})
            max_age = max(10, min(age_days - 5, 420))
            created = snapshot - timedelta(days=rng.randint(10, max_age))
            catalog_name = f"{config.FABRICS[fabric][0]} {config.PATTERNS[pattern][0]} {config.PRODUCT_TYPES[ptype][0]} Vol {rng.randint(1, 40)}"
            catalogs.append((cid_counter, s_id, catalog_name, created.isoformat()))
            design_pop = rng.gauss(0.0, 0.45) + 0.3 * s_q
            design_rel = math.exp(rng.gauss(0.0, 0.12) + 0.05 * s_q)
            for color in rng.sample(COLORS, cat_size):
                emit_product(cid_counter, s_id, s_q, s_ctr, False, ptype, fabric, pattern, occasion, sleeve, length,
                             color, created + timedelta(days=rng.randint(0, 3)),
                             design_rel * math.exp(rng.gauss(0, 0.05)), design_pop + rng.gauss(0, 0.3),
                             rng.gauss(0.0, 0.4) + 0.6 * s_q, rng.randint(0, 60),
                             rng.choice([1, 2, 3, 4, 4, 5, 5, 6, 7]))
                made += 1
            cid_counter += 1

    con.executemany("INSERT INTO catalogs VALUES (?,?,?,?)", catalogs)
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", products)
    con.executemany("INSERT INTO inventory VALUES (?,?,?)", inventory)
    con.executemany("INSERT OR REPLACE INTO price_history VALUES (?,?,?)", price_hist)
    con.executemany("INSERT INTO daily_product_metrics VALUES (?,?,?,?,?,?,?,?)", metrics)
    con.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?)", reviews)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()
    con.execute("ANALYZE")
    con.close()
    os.replace(tmp_path, db_path)
    if verbose:
        print(f"Built {db_path}: {len(seller_rows)} sellers, {len(products)} products, "
              f"{len(metrics):,} daily metric rows, {len(reviews):,} reviews in {time.time() - t0:.1f}s")
    return db_path


if __name__ == "__main__":
    build()
