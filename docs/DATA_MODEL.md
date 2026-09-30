# Data model

A marketplace like Meesho keeps five kinds of data. The pricing agent needs all five. Full DDL is in
`pricing_agent/schema.sql`.

```
                        categories ──┐
                                     │ category_id
sellers ──< catalogs ──< products >──┘
   │                        │
   │                        ├──< price_history          (every price change)
   │                        ├──< daily_product_metrics  (impressions → clicks → orders → returns/RTO)
   │                        ├──< reviews                (rating + tagged theme)
   │                        └──  inventory
   │
   └──< pricing_recommendations  (agent output, for audit & learning)

reference: shipping_rate_card · packaging_rate_card · festival_calendar · fabric_seasonality
```

| Group | Table | Grain | Used by the agent for |
|---|---|---|---|
| Catalogue | `categories` | one row per category node (L1 → L3) | GST, return/RTO priors, transit-loss rate |
| | `catalogs` | one design in several colours (a seller's upload batch) | colour variants are repriced together |
| | `products` | one live listing (one colour of a design) | attributes → fair price, similarity, package size, MRP. `recommendation_id` links listings created by the agent to their launch plan |
| | `inventory` | stock per listing | — (the seller's stock comes from the form) |
| | `price_history` | one row per price change | **price sensitivity** (before vs after a listing's own change) |
| Sellers | `sellers` | seller account | tier, city, the seller's own listings → CTR factor |
| Performance | `daily_product_metrics` | listing × day | CTR, conversion, orders, return and RTO rates, new-listing ramp |
| | `reviews` | one review | rating, complaint themes → tips |
| Reference | `shipping_rate_card` | weight slab | forward and reverse shipping cost |
| | `packaging_rate_card` | S / M / L | packaging cost, added weight |
| | `festival_calendar` | event | demand uplift and lead time |
| | `fabric_seasonality` | fabric × month | seasonal demand index |
| Agent | `pricing_recommendations` | one recommendation | audit trail. Later, compare against actual sales to retrain |

## Why this shape

- **Daily funnel, not just orders.** Pricing depends on *conversion*. Separating impressions, clicks
  and orders lets the agent tell apart "nobody saw it" (visibility, photos) from "people saw it and
  the price put them off".
- **Price history is first-class.** Without it you can only compare *different* listings, and cheaper
  listings are often cheaper for other reasons. Before/after comparisons on the *same* listing isolate
  the price effect. That's why the agent recovers the true sensitivity.
- **COGS is nullable.** The marketplace never knows competitors' costs, only the seller's own.
- **Recommendations are logged.** This is the feedback loop that turns the prototype into a learning
  system.

## Synthetic data (current prototype)

`seed.py` creates, deterministically (seed `20260928`):

| | |
|---|---|
| Sellers | 265 (5 demo sellers + 260 competitors across 10 textile hubs: Jaipur, Surat, Lucknow…) |
| Listings | ~2,000 across 4 leaf categories, 7 fabrics, 6 work types, 4 occasions |
| Demo sellers | Rangreza Prints and Sanganeri Cotton Co. (Jaipur cotton rivals), Surat Silk Mart, Lucknow Chikan Studio, and Naya Kurti House (new, no listings) |
| Daily metrics | ~200k rows, 1 Jun – 28 Sep 2026 |
| Reviews | ~32k with themes (size issue, thin fabric, colour mismatch, stitching, positive) |

City specialities shape the catalogue (Jaipur is block-print cotton, Lucknow chikankari, Surat
georgette/silk). Demand follows a hidden funnel model with season, festival, rating, photo and seller
effects. The engine never reads these hidden parameters. It has to rediscover them from the tables.
