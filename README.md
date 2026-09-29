# Kurti Pricing Agent — prototype

A pricing copilot for Meesho sellers, with two parts:

1. **Price my product** (new listings). The seller describes a new kurti (photos, description, cost,
   stock, optional shop price/margin, sell-by date) and picks a goal. The agent scans comparable live
   listings, learns how buyers react to price, factors in festivals and season, the seller's own track
   record, shipping, packaging and returns, and recommends an **entry price**, with reasons in simple
   English or Hindi. **List** publishes it: one listing per colour.
2. **My listings** (listings already live). Every live listing of a seller, with its analytics:
   stock and days of cover, orders and trend, CTR and conversion against the market, rating, returns,
   and 60-day sales and price history. Each listing gets the price it should have *now* across its
   lifecycle, with the 30-day business impact and plain-language reasons. Colours of one design are
   priced together, ageing stock gets cleared, and one click applies the new price.

This prototype covers one category (**Women Ethnic › Kurtis & Kurta Sets**) on a synthetic,
Meesho-style database.

## Run it

Requires Python 3.9+. Nothing to install (standard library only).

```bash
python3 run.py
```

This opens http://127.0.0.1:8000. On first run it generates the database in about 2 seconds.

- `python3 run.py --rebuild` regenerates the marketplace data and clears saved recommendations.
- `python3 run.py --port 9000 --no-browser`
- `python3 -m unittest -v` runs 40 end-to-end tests: data integrity, model recovery, pricing logic,
  repricing guard rails, the list → reprice → apply → delist flow, AI-text checks (with a fake model), the data browser, the HTTP API and a 150-case fuzz test.
- The database rebuilds automatically when the schema changes. `--rebuild` also wipes any listings
  and price changes made during a demo, so each demo starts clean.

## AI-written explanations (optional)

The prices never depend on an AI model. With a free API key, a model rewrites the explanations in fresher,
plainer English and Hindi. Its text is shown only if every number in it matches the pricing engine; otherwise
(or with no key, no quota or no internet) the built-in template text is used. The key stays on the server.

1. Get a free key at [Google AI Studio](https://aistudio.google.com) → **Get API key** → **Create API key**.
2. **Locally:** create a file named `.env` in this folder containing `GEMINI_API_KEY=your-key`. It is already
   in `.gitignore`, so it never goes to GitHub. Restart `python3 run.py`; the console prints "AI explanations: gemini".
3. **On Render:** open the service → **Environment** → **Add environment variable** → `GEMINI_API_KEY` = your key →
   **Save changes**. Render redeploys automatically.

Groq's free tier also works: use `GROQ_API_KEY` instead. `LLM_MODEL` overrides the model name.
On Gemini the model is chosen automatically if the default is retired.

## 3-minute demo script

1. **Jaipur cotton kurti** (established seller). The recommended price is ₹349, inside the market's
   ₹319–₹389 middle band. The breakdown shows the ₹284 break-even, the seller's 26% better
   click-through, and a ₹10 launch discount. The plan is to move to ₹359 after 20–25 reviews.
2. **Festive silk set, new seller.** Navratri is 12 days away and Dussehra 21, and silk is in
   season. Price goes up by +₹60 compared with a normal month (*why* is computed, not written by
   hand). Switch to **हिंदी**. Then change the launch date to May 2027 and the price drops.
3. **Clear stock before sell-by.** 120 pieces must go before 15 Nov. The agent picks the highest price
   that still sells out in time.
4. On any result, type colours (e.g. "Rust, Olive") and press **List**, then **View in My listings**. The
   new listings appear with their launch plan and closest rival.
5. **My listings → Rangreza Prints.** Walk through these rows:
   - *Dabu Block Print*: Indigo sells 5× faster than Maroon and has 2 days of stock. Indigo goes up;
     Maroon holds because the buyers Indigo loses switch to Maroon.
   - *Summer Mulmul*: ageing cotton stock heading into winter is marked down 15–25%. The reasons explain
     why cutting deeper would lose more than selling the leftovers in bulk.
   - *Khadi Kurta Set*: 21% above fair price with weak conversion, so it comes down.
   - Press **Apply** on a row and it moves to "Recently changed – wait" (it re-checks after 14 days).
6. Switch goals (Balanced / Max Profit / Scale / Clear) and switch sellers. **Sanganeri Cotton Co.** and
   **Rangreza** compete in Jaipur cotton and show up as each other's rivals.
7. Open the **Marketplace data** tab to show the data model the agent runs on.

## How it works

```
seller input ─► understand product ─► market scan ─► demand model ─► unit economics ─► optimise for goal ─► explain
                (attrs from text,      (comparable     (price          (GST, shipping,     (Balanced / Max      (counterfactual
                 package & weight)      listings, fair  sensitivity,     packaging, returns,  profit / Scale /     reasons, EN + HI)
                                        price, crowding, season,         RTO, COGS)           Clear inventory)
                                        complaints)      festivals, CTR)
```

| Step | What it does | Where |
|---|---|---|
| Fair price | Hedonic regression: log price on fabric, work, type, occasion, sleeve, length (R² ≈ 0.83) | `market.py` |
| Competitors | Weighted attribute similarity. Top listings with price, rating, orders, return rate | `market.py` |
| **Price sensitivity** | Learnt *within* listings that changed their own price, so popularity cancels out. Uses same-occasion listings, and is shrunk toward a prior when data is thin. It recovers the generator's hidden truth within about 5–15% | `market.py::fit_demand` |
| Demand level | Cross-section of comparables, with season removed, adjusted for rating, photos (CTR learnt from data), seller CTR, and a new-listing factor (new listings sell about 27% less in month 1, learnt from data) | `market.py`, `engine.py` |
| Season & festivals | Fabric × month index plus festival calendar ramps, weighted by occasion. Busier periods mean more buyers and lower price sensitivity | `signals.py`, `config.py` |
| Unit economics | Per order placed: GST, COGS, packaging, forward/return shipping, RTO charges, damaged returns | `engine.py::Economics` |
| Optimiser | Evaluates every "…9" price. Takes stock, restock ability and sell-by write-offs into account | `engine.py` |
| Explanations | Each reason reruns the optimiser with one factor switched off. For example, "+₹150 from festivals" is a real, computed difference | `explain.py` |

Every recommendation is saved in `pricing_recommendations` for audit, and later for learning from
outcomes.

### Repricing live listings (`repricer.py`)

| Step | What it does |
|---|---|
| Listing's own demand | Last 28 days of orders at its actual price, corrected for season. It's blended with the market model only when sales are thin |
| Forecast | Next 30 days at every candidate price. Includes the season and festivals ahead, and the learnt price sensitivity plus a ranking effect (a higher price lowers conversion, which lowers visibility) |
| Colour variants | All colours of a design are optimised together. When one colour gets dearer, ~35% of the buyers it loses switch to its sibling colours |
| Stock | Sellers restock within ~10 days, so only listings with less stock than that lose sales. Excess stock carries a holding cost |
| Ageing stock | Scored from age, sales trend, the season ahead and months of stock. Ageing stock can't be restocked and loses most of its value if unsold, so it gets marked down, with a bundle or liquidation tip |
| Guard rails | Raises go in steps of at most 10% (the full target is shown). Cuts are at most 25% (35% for ageing stock). Changes under max(₹10, 3%) are skipped. Ageing or overstocked items are never marked up, and items about to sell out are never cut. A price is not re-changed within 14 days |
| Goals | The same four goals as for new products, applied to the whole design |

## What's real and what's assumed

- **Synthetic data.** 265 sellers, about 2,000 listings, 120 days of daily funnel data (~200k rows) and
  33k reviews, all generated by `seed.py` from an explicit demand model. It is realistic, but it isn't
  Meesho data. The 5 demo sellers have hand-designed catalogues, so every repricing situation appears
  at least once: hot/slow colours, ageing stock, stock-outs, and under- and over-priced items.
- **Assumed rate cards.** Shipping slabs, RTO charge, packaging, 0% commission, 5% GST, festival dates
  (approximate) and seasonality indices are all in `config.py`, one place to swap in the real numbers.
- **Photos.** Only the photo *count* is used today: CTR by photo count is learnt from the data. Package
  size and weight are estimated from type and fabric.

## Next steps toward production

1. Point `market.py` at real catalogue, funnel and price-history tables. The schema in
   `docs/DATA_MODEL.md` shows the shape.
2. Use a vision model on photos to extract attributes and garment dimensions, and to score photo quality.
3. Replace the synthetic "search" with live competitor retrieval (catalogue embeddings).
4. Close the loop: compare recommended and actual sales, then re-fit sensitivity per segment each week.
   Run A/B price tests to sharpen the estimates.
5. Add an LLM layer to answer seller follow-up questions ("what if I price at ₹399?").
6. Extend to more categories. Only `config.py` priors and the attribute lists are kurti-specific.

## Files

```
run.py                      start server (builds DB if needed)
pricing_agent/
  config.py                 business assumptions (rate cards, festivals, seasonality)
  schema.sql                marketplace data model
  seed.py                   synthetic marketplace generator (hidden ground truth)
  signals.py                season & festival demand signals
  market.py                 market intelligence + demand model
  features.py               attribute detection, package estimation
  engine.py                 validation, economics, optimiser, listing & price-change actions
  repricer.py               lifecycle repricing of live listings (variants, ageing stock, rivals)
  explain.py                plain-language reasons (English + Hindi)
  llm.py                    tiny Gemini / Groq client (standard library only)
  narrator.py               AI explanations with number checks and template fallback
  dbview.py                 Data tab: paged, searchable, sortable table browser + CSV export
  server.py                 JSON API + static files
web/                        UI (vanilla JS, hand-drawn SVG charts, works offline)
tests/test_agent.py         end-to-end tests
docs/DATA_MODEL.md          data model reference
```
