"""
End-to-end tests for the Kurti pricing agent.   Run:  python3 -m unittest -v
Uses a freshly generated database in a temp folder, so the demo database is untouched.
"""
import json
import math
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pricing_agent import config, features, seed  # noqa: E402
from pricing_agent.engine import Economics, InputError, PricingAgent  # noqa: E402
from pricing_agent.explain import inr  # noqa: E402
from pricing_agent.llm import LLMClient, LLMError  # noqa: E402
from pricing_agent.narrator import Narrator, check_numbers  # noqa: E402
from pricing_agent.repricer import Repricer  # noqa: E402
from pricing_agent.server import serve  # noqa: E402

TMP = tempfile.mkdtemp(prefix="kurti-test-")
DB = os.path.join(TMP, "test.db")
AGENT = None

EXAMPLES = [
    dict(seller_id=1, title="Jaipuri Cotton Hand Block Print Kurti",
         description="Pure cotton, 3/4 sleeve, knee length, daily wear", cogs=150, inventory=200, n_photos=5),
    dict(seller_id=3, title="Banarasi Silk Kurta Set with Dupatta",
         description="Festive silk blend with zari embroidery, full sleeve, calf length", cogs=420, inventory=80,
         offline_price=1299, offline_margin_pct=45, n_photos=6),
    dict(seller_id=2, title="Rayon Printed Kurti with Palazzo", description="office wear, 3/4 sleeve",
         cogs=180, inventory=120, expiry_date="2026-11-15", limited_stock=True, n_photos=3),
]


def setUpModule():
    global AGENT
    seed.build(DB, verbose=False)
    AGENT = PricingAgent(DB)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def rec(**kw):
    return AGENT.recommend(kw, save=False)


class TestDatabase(unittest.TestCase):
    def test_tables_and_integrity(self):
        con = sqlite3.connect(DB)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ["categories", "sellers", "catalogs", "products", "inventory", "price_history",
                  "daily_product_metrics", "reviews", "shipping_rate_card", "packaging_rate_card",
                  "festival_calendar", "fabric_seasonality", "pricing_recommendations"]:
            self.assertIn(t, tables)
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertGreater(con.execute("SELECT count(*) FROM products").fetchone()[0], 1500)
        con.close()

    def test_realistic_funnel(self):
        con = sqlite3.connect(DB)
        imp, clk, orders, ret, rto = con.execute(
            "SELECT sum(impressions), sum(clicks), sum(orders), sum(customer_returns), sum(rto) FROM daily_product_metrics").fetchone()
        con.close()
        self.assertTrue(0.01 < clk / imp < 0.06)
        self.assertTrue(0.10 < ret / orders < 0.30)
        self.assertTrue(0.05 < rto / orders < 0.20)

    def test_deterministic(self):
        other = os.path.join(TMP, "again.db")
        seed.build(other, verbose=False)
        q = "SELECT count(*), sum(current_price) FROM products"
        results = []
        for path in (DB, other):
            con = sqlite3.connect(path)
            results.append(con.execute(q).fetchone())
            con.close()
        self.assertEqual(results[0], results[1])


class TestModel(unittest.TestCase):
    def test_recovers_hidden_price_sensitivity(self):
        """The generator's hidden sensitivity must be rediscovered from data (within 20%)."""
        m = AGENT.market
        for occ, fab, pt, pat in [("daily", "cotton", "kurti", "block_print"), ("office", "rayon", "kurti_bottom", "printed")]:
            attrs = dict(product_type=pt, fabric=fab, pattern=pat, occasion=occ, sleeve="three_quarter", length="knee")
            fit = m.fit_demand(m.competitors(attrs), occ)
            truth = seed.TRUE_SENSITIVITY[occ]
            self.assertLess(abs(fit["b"] - truth) / truth, 0.2, f"{occ}: fitted {fit['b']:.2f} vs true {truth}")

    def test_hedonic_price_model(self):
        self.assertGreater(AGENT.market.hedonic_r2, 0.7)
        base = dict(product_type="kurti", fabric="cotton", pattern="printed", occasion="daily", sleeve="three_quarter", length="knee")
        richer = dict(base, product_type="kurta_set_dupatta", fabric="silk_blend", pattern="embroidered")
        self.assertGreater(AGENT.market.fair_price(richer), 1.8 * AGENT.market.fair_price(base))

    def test_economics(self):
        eco = Economics(cogs=150, ret=0.18, rto=0.11, packaging=7, fwd=62, rev=78)
        self.assertAlmostEqual(eco.profit(eco.break_even()), 0, places=6)
        self.assertGreater(eco.profit(400), eco.profit(300))
        bd = eco.breakdown(349)
        self.assertAlmostEqual(sum(l["amount"] for l in bd[:-1]), bd[-1]["amount"], delta=0.5)


class TestRecommendations(unittest.TestCase):
    def test_modes_are_ordered(self):
        for ex in EXAMPLES[:2]:
            r = rec(**ex)
            p = {k: v["price"] for k, v in r["modes"].items()}
            self.assertLessEqual(p["scale"], p["balanced"])
            self.assertLessEqual(p["balanced"], p["max_margin"])
            self.assertLessEqual(p["clear_inventory"], p["balanced"])

    def test_price_is_profitable_and_meesho_style(self):
        for ex in EXAMPLES:
            for mode in config.MODES:
                r = rec(**dict(ex, mode=mode))
                price = r["recommendation"]["entry_price"]
                self.assertEqual(price % 10, 9)
                if not r["recommendation"]["has_expiry"]:
                    self.assertGreaterEqual(price, r["recommendation"]["break_even_price"])

    def test_festival_raises_festive_price(self):
        silk = EXAMPLES[1]
        oct_price = rec(**dict(silk, launch_date="2026-09-29"))["recommendation"]["entry_price"]
        may_price = rec(**dict(silk, launch_date="2027-05-10"))["recommendation"]["entry_price"]
        self.assertGreater(oct_price, may_price)

    def test_cotton_sells_more_in_summer(self):
        cot = EXAMPLES[0]
        may = rec(**dict(cot, launch_date="2027-05-01"))["recommendation"]["orders_per_day"]
        dec = rec(**dict(cot, launch_date="2026-12-15"))["recommendation"]["orders_per_day"]
        self.assertGreater(may, dec * 1.2)

    def test_seller_ctr_increases_demand(self):
        good = rec(**dict(EXAMPLES[0], seller_id=1))["recommendation"]["orders_per_day"]
        new = rec(**dict(EXAMPLES[0], seller_id=3))["recommendation"]["orders_per_day"]
        self.assertGreater(good, new)

    def test_more_photos_more_orders(self):
        few = rec(**dict(EXAMPLES[0], n_photos=1))["recommendation"]["orders_per_day"]
        many = rec(**dict(EXAMPLES[0], n_photos=5))["recommendation"]["orders_per_day"]
        self.assertGreater(many, few)

    def test_cogs_from_offline_margin(self):
        r = rec(title="cotton kurti", offline_price=500, offline_margin_pct=40, inventory=20)
        self.assertAlmostEqual(r["economics"]["cogs"], 300, delta=0.5)
        self.assertTrue(any("estimated your cost" in w["en"] for w in r["explanation"]["warnings"]))

    def test_explanations_complete_and_clean(self):
        for ex in EXAMPLES:
            ex_ = rec(**ex)["explanation"]
            items = [ex_["headline"], ex_["summary"]] + ex_["tips"] + ex_["warnings"]
            items += [r["title"] for r in ex_["reasons"]] + [r["text"] for r in ex_["reasons"]]
            for it in items:
                for lang in ("en", "hi"):
                    self.assertTrue(it[lang].strip())
                    for bad in ("None", "nan", "inf", "{", "}"):
                        self.assertNotIn(bad, it[lang], it[lang])

    def test_indian_number_format(self):
        self.assertEqual(inr(1234567), "₹12,34,567")
        self.assertEqual(inr(-950), "-₹950")


class TestInputs(unittest.TestCase):
    def test_validation(self):
        bad = [None, {}, {"cogs": "abc", "inventory": 5}, {"cogs": 100}, {"cogs": 100, "inventory": 0},
               {"cogs": 100, "inventory": 5, "fabric": "wool"}, {"cogs": 100, "inventory": 5, "mode": "x"},
               {"cogs": 100, "inventory": 5, "seller_id": 999}, {"cogs": 100, "inventory": 5, "launch_date": "nope"},
               {"cogs": 100, "inventory": 5, "expiry_date": "2020-01-01"}, {"cogs": "nan", "inventory": 5},
               {"cogs": 100, "inventory": 5, "horizon_days": 2}, {"cogs": 100, "inventory": 5, "package_size": "XL"}]
        for b in bad:
            with self.assertRaises(InputError, msg=str(b)):
                AGENT.recommend(b, save=False)

    def test_attribute_detection(self):
        d = features.detect_attributes("Lucknowi chikankari georgette anarkali, full sleeve, party wear")
        self.assertEqual(d["pattern"], "chikankari")
        self.assertEqual(d["fabric"], "georgette")
        self.assertEqual(d["product_type"], "anarkali")
        self.assertEqual(d["sleeve"], "full")
        self.assertEqual(d["occasion"], "party")
        self.assertEqual(features.detect_attributes("Jaipur hand block printed cotton")["pattern"], "block_print")
        self.assertEqual(features.detect_attributes(""), {})

    def test_package_estimate(self):
        self.assertEqual(features.estimate_package("kurti", "georgette")["package_size"], "S")
        self.assertEqual(features.estimate_package("kurta_set_dupatta", "khadi")["package_size"], "L")

    def test_fuzz_never_crashes(self):
        rng = random.Random(7)
        choices = {"product_type": config.PRODUCT_TYPES, "fabric": config.FABRICS, "pattern": config.PATTERNS,
                   "sleeve": config.SLEEVES, "length": config.LENGTHS, "occasion": config.OCCASIONS}
        for _ in range(150):
            body = {k: rng.choice(list(v)) for k, v in choices.items()}
            body.update(seller_id=rng.choice([1, 2, 3, None]), cogs=rng.choice([1, 50, 150, 400, 1200, 5000]),
                        inventory=rng.choice([1, 5, 80, 1000, 100000]), mode=rng.choice(list(config.MODES)),
                        n_photos=rng.randint(0, 8), horizon_days=rng.choice([7, 30, 90, 180]),
                        limited_stock=rng.random() < 0.3,
                        launch_date=rng.choice(["2026-09-29", "2027-01-10", "2027-04-20", "2027-08-01"]))
            if rng.random() < 0.3:
                body["expiry_date"] = "2027-09-15"
            if rng.random() < 0.3:
                body.update(offline_price=rng.randint(200, 2000), offline_margin_pct=rng.randint(5, 60))
            r = AGENT.recommend(body, save=False)
            json.dumps(r, allow_nan=False, default=str)   # no NaN / inf leaks to the UI
            self.assertGreater(r["recommendation"]["entry_price"], 0)


class TestListings(unittest.TestCase):
    """Lifecycle repricing of existing listings."""

    @classmethod
    def setUpClass(cls):
        cls.rp = Repricer(AGENT)
        cls.data = {sid: cls.rp.seller_listings(sid, "balanced") for sid in (1, 2, 4, 5)}

    def variants(self, sid):
        return [v for g in self.data[sid]["groups"] for v in g["variants"]]

    def find(self, sid, text):
        return next(v for v in self.variants(sid) if text in v["title"])

    def test_every_demo_seller_has_listings(self):
        for sid, d in self.data.items():
            self.assertGreater(d["summary"]["listings"], 5, sid)
            for v in self.variants(sid):
                self.assertEqual(v["recommended_price"] % 10, 9)
                self.assertTrue(v["reasons"])
                json.dumps(v, allow_nan=False)

    def test_guard_rails(self):
        for sid in self.data:
            for v in self.variants(sid):
                p0, p1 = v["current_price"], v["recommended_price"]
                self.assertLessEqual(p1, p0 * 1.10 + 1, v["title"])        # raise in steps of <=10%
                self.assertGreaterEqual(p1, p0 * 0.65 - 10, v["title"])    # never more than a 35% cut
                if v["stage"] == "Ageing" or (v["days_of_cover"] or 0) > 90:
                    self.assertLessEqual(p1, p0, v["title"])                # never mark up old / excess stock
                if v["days_of_cover"] is not None and v["days_of_cover"] < 10:
                    self.assertGreaterEqual(p1, p0, v["title"])             # never cut what is about to sell out

    def test_popular_colour_up_slow_colour_not(self):
        indigo, maroon = self.find(1, "Indigo Dabu"), self.find(1, "Maroon Dabu")
        self.assertGreater(indigo["recommended_price"], indigo["current_price"])
        self.assertLessEqual(maroon["recommended_price"], maroon["current_price"])
        self.assertTrue(any(r["icon"] == "variant" for r in indigo["reasons"]))

    def test_ageing_stock_is_marked_down(self):
        old = [v for v in self.variants(1) if "Mulmul" in v["title"]]
        self.assertTrue(all(v["stage"] == "Ageing" for v in old))
        self.assertTrue(all(v["recommended_price"] < v["current_price"] for v in old))

    def test_overpriced_listing_is_lowered(self):
        khadi = self.find(1, "Khadi")
        self.assertLess(khadi["recommended_price"], khadi["current_price"])

    def test_sellers_see_each_other(self):
        rivals = {r["name"]: r for r in self.data[1]["rivals"]}
        self.assertGreater(rivals["Sanganeri Cotton Co."]["overlapping"], 0)
        self.assertTrue(any(v["rival"] and v["rival"]["seller"] == "Sanganeri Cotton Co." for v in self.variants(1)))

    def test_all_goals_run(self):
        for mode in config.MODES:
            d = self.rp.seller_listings(2, mode)
            self.assertEqual(d["mode"], mode)
        with self.assertRaises(InputError):
            self.rp.seller_listings(999)
        with self.assertRaises(InputError):
            self.rp.seller_listings(1, "nope")


class FakeLLM(LLMClient):
    """Stands in for Gemini/Groq: returns whatever the test hands it."""

    def __init__(self, reply):
        super().__init__({"GEMINI_API_KEY": "test"})
        self.reply = reply
        self.calls = 0

    def complete_json(self, system, user, timeout=25.0):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(user) if callable(self.reply) else self.reply


class TestNarrator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = AGENT.recommend(dict(EXAMPLES[0]), save=False)

    def good_reply(self, _prompt):
        ex = self.result["explanation"]
        price = self.result["recommendation"]["entry_price"]
        pair = lambda t: {"en": t, "hi": t}
        return {"headline": pair(f"Launch at ₹{price}"), "summary": pair(f"Start at ₹{price} and watch the first orders."),
                "reasons": [pair("A clearer point.") for _ in ex["reasons"]], "tips": [pair("A tip.") for _ in ex["tips"]]}

    def test_no_key_means_templates(self):
        n = Narrator(LLMClient({}))
        self.assertFalse(n.info()["enabled"])
        self.assertEqual(n.narrate_pricing(self.result)["source"], "template")

    def test_valid_ai_text_is_used(self):
        fake = FakeLLM(self.good_reply)
        out = Narrator(fake).narrate_pricing(self.result)
        self.assertEqual(out["source"], "ai", out)
        self.assertEqual(len(out["reasons"]), len(self.result["explanation"]["reasons"]))

    def test_invented_numbers_are_rejected(self):
        def lying(prompt):
            r = self.good_reply(prompt)
            r["summary"] = {"en": "Sell at ₹123457 for 97% more orders.", "hi": "x"}
            return r
        self.assertEqual(Narrator(FakeLLM(lying)).narrate_pricing(self.result)["source"], "template")
        self.assertIsNotNone(check_numbers(["costs ₹999999"], {"price": 349}))
        self.assertIsNone(check_numbers(["about ₹349 and 2.8 orders a day"], {"price": 349, "opd": 2.84}))

    def test_bad_shape_and_errors_fall_back(self):
        for reply in ({"headline": "no"}, LLMError("quota"), {"headline": {"en": "a", "hi": "b"}, "summary": {"en": "a", "hi": "b"},
                                                              "reasons": [], "tips": []}):
            self.assertEqual(Narrator(FakeLLM(reply)).narrate_pricing(self.result)["source"], "template")

    def test_ai_results_are_cached(self):
        fake = FakeLLM(self.good_reply)
        n = Narrator(fake)
        n.narrate_pricing(self.result)
        n.narrate_pricing(self.result)
        self.assertEqual(fake.calls, 1)

    def test_listing_narration(self):
        rp = Repricer(AGENT)
        v, design, seller, goal = rp.find_variant(next(p["product_id"] for p in AGENT.market.active
                                                      if p["seller_id"] == 1 and "Dabu" in p["title"]))
        ok = FakeLLM({"summary": f"Move to ₹{v['recommended_price']}.", "points": ["Point."] * len(v["reasons"])})
        self.assertEqual(Narrator(ok).narrate_listing(v, design, seller, goal)["source"], "ai")
        short = FakeLLM({"summary": "x", "points": ["only one"]})
        if len(v["reasons"]) != 1:
            self.assertEqual(Narrator(short).narrate_listing(v, design, seller, goal)["source"], "template")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.port = serve(DB, "127.0.0.1", 18765)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        r = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_endpoints(self):
        self.assertEqual(self.req("/api/health")[0], 200)
        s, b = self.req("/api/meta")
        self.assertEqual(s, 200)
        self.assertEqual(len(json.loads(b)["sellers"]), 5)
        s, b = self.req("/")
        self.assertEqual(s, 200)
        self.assertIn(b"Kurti Pricing Agent", b)
        for f in ("/static/app.js", "/static/style.css"):
            self.assertEqual(self.req(f)[0], 200)
        s, b = self.req("/api/db")
        self.assertEqual(s, 200)
        self.assertEqual(len(json.loads(b)["tables"]), 13)

    def test_recommend_and_save(self):
        s, b = self.req("/api/recommend", EXAMPLES[0])
        self.assertEqual(s, 200)
        out = json.loads(b)
        self.assertIn("recommendation_id", out)
        con = sqlite3.connect(DB)
        self.assertEqual(con.execute("SELECT recommended_price FROM pricing_recommendations WHERE recommendation_id=?",
                                     (out["recommendation_id"],)).fetchone()[0], out["recommendation"]["entry_price"])
        con.close()

    def test_list_then_reprice_flow(self):
        body = dict(seller_id=3, title="Lucknowi Chikankari Cotton Kurti", description="office wear", cogs=170,
                    inventory=41, n_photos=4)
        s, b = self.req("/api/recommend", body)
        rec = json.loads(b)
        s, b = self.req("/api/list", dict(body, price=rec["recommendation"]["entry_price"], colors="White, peach, white",
                                          recommendation_id=rec["recommendation_id"]))
        self.assertEqual(s, 200, b)
        out = json.loads(b)
        self.assertEqual(out["colors"], ["White", "Peach"])
        s, b = self.req("/api/listings?seller_id=3&mode=balanced")
        d = json.loads(b)
        vs = [v for g in d["groups"] for v in g["variants"]]
        self.assertEqual(sorted(v["stock"] for v in vs), [20, 21])
        self.assertTrue(all(v["action"] == "new" for v in vs))
        # the new listing shows up for the rival Lucknow seller
        s, b = self.req("/api/listings?seller_id=5")
        self.assertIn("Naya Kurti House (new seller)", [r["name"] for r in json.loads(b)["rivals"] if r["overlapping"]])
        # apply a recommended change on an existing listing -> it holds afterwards
        s, b = self.req("/api/listings?seller_id=1")
        v = next(v for g in json.loads(b)["groups"] for v in g["variants"] if v["recommended_price"] != v["current_price"])
        s, b = self.req("/api/listings/apply", {"product_id": v["product_id"], "price": v["recommended_price"]})
        self.assertEqual(s, 200)
        s, b = self.req("/api/listings?seller_id=1")
        v2 = next(x for g in json.loads(b)["groups"] for x in g["variants"] if x["product_id"] == v["product_id"])
        self.assertEqual(v2["current_price"], v["recommended_price"])
        self.assertEqual(v2["recommended_price"], v2["current_price"])
        self.assertEqual(self.req("/api/listings?seller_id=abc")[0], 400)
        self.assertEqual(self.req("/api/list", dict(body, seller_id=None, price=300))[0], 400)
        self.assertEqual(self.req("/api/listings/apply", {"product_id": 1, "price": 300})[0], 400)

    def test_data_browser(self):
        s, b = self.req("/api/db/schema")
        tables = {t["table"]: t for t in json.loads(b)["tables"]}
        self.assertIn("sellers", tables["products"]["columns"][2]["fk"]["table"])
        s, b = self.req("/api/db/table?name=products&page=2&size=10&sort=current_price&dir=desc")
        d = json.loads(b)
        self.assertEqual((s, d["page"], len(d["rows"])), (200, 2, 10))
        prices = [r[[c["name"] for c in d["columns"]].index("current_price")] for r in d["rows"]]
        self.assertEqual(prices, sorted(prices, reverse=True))
        s, b = self.req("/api/db/table?name=products&q=Chikankari&size=100")
        self.assertTrue(all("chikankari" in json.dumps(r).lower() for r in json.loads(b)["rows"]))
        s, b = self.req("/api/db/table?name=sellers&filter_col=seller_id&filter_val=1")
        self.assertEqual(json.loads(b)["total"], 1)
        s, b = self.req("/api/db/export.csv?name=sellers&filter_col=seller_id&filter_val=1")
        self.assertEqual((s, b.decode().count("\n")), (200, 2))
        for bad in ("/api/db/table?name=sqlite_master", "/api/db/table?name=products;drop",
                    "/api/db/table?name=products&sort=1;drop", "/api/db/table?name=products&filter_col=x"):
            self.assertEqual(self.req(bad)[0], 400, bad)

    def test_delist_relist_and_restore(self):
        s, b = self.req("/api/listings?seller_id=4")
        v = json.loads(b)["groups"][0]["variants"][0]
        before = json.loads(b)["summary"]["listings"]
        self.assertEqual(self.req("/api/listings/delist", {"product_id": v["product_id"]})[0], 200)
        d = json.loads(self.req("/api/listings?seller_id=4")[1])
        self.assertEqual(d["summary"]["listings"], before - 1)
        self.assertNotIn(v["product_id"], [x["product_id"] for g in d["groups"] for x in g["variants"]])
        from pricing_agent.server import Handler
        self.assertNotIn(v["product_id"], [p["product_id"] for p in Handler.agent.market.active])
        self.assertEqual(self.req("/api/listings/relist", {"product_id": v["product_id"]})[0], 200)
        self.assertEqual(json.loads(self.req("/api/listings?seller_id=4")[1])["summary"]["listings"], before)
        # example listings come back on page load
        self.req("/api/listings/delist", {"product_id": v["product_id"]})
        s, b = self.req("/api/demo/restore", {})
        self.assertEqual(json.loads(b)["restored"], 1)
        self.assertEqual(json.loads(self.req("/api/listings?seller_id=4")[1])["summary"]["listings"], before)
        self.assertEqual(self.req("/api/listings/delist", {"product_id": 999999})[0], 400)

    def test_narrate_endpoints_without_key(self):
        s, b = self.req("/api/narrate/pricing", {"recommendation_id": 123456})
        self.assertEqual(json.loads(b)["source"], "template")
        s, b = self.req("/api/narrate/listing", {"product_id": 1000})
        self.assertIn(json.loads(b)["source"], ("template", "ai"))

    def test_head_and_odd_requests(self):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/health", method="HEAD")
        with urllib.request.urlopen(r, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read(), b"")
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/", method="DELETE")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(r, timeout=10)
        self.assertEqual(ctx.exception.code, 501)
        self.assertEqual(self.req("/api/health")[0], 200)     # server still healthy

    def test_errors_are_friendly(self):
        s, b = self.req("/api/recommend", {"inventory": 5})
        self.assertEqual(s, 400)
        self.assertIn("COGS", json.loads(b)["error"])
        s, b = self.req("/api/recommend", b"{not json")
        self.assertEqual(s, 400)
        self.assertEqual(self.req("/static/../pricing_agent/config.py")[0], 404)
        self.assertEqual(self.req("/static/%2e%2e/run.py")[0], 404)
        self.assertEqual(self.req("/nope")[0], 404)
        s, b = self.req("/api/detect", {"text": "rayon anarkali"})
        self.assertEqual(json.loads(b)["detected"]["fabric"], "rayon")


if __name__ == "__main__":
    unittest.main()
