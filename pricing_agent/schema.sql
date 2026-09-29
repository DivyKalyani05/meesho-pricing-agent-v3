-- Meesho-style marketplace data model (prototype, SQLite).
-- Modelled on how a marketplace separates: catalogue (what is listed),
-- sellers (who lists), daily funnel metrics (how it performs), orders/returns,
-- reviews (what buyers say), and reference data (rate cards, calendar).

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------ taxonomy
CREATE TABLE categories (
    category_id      INTEGER PRIMARY KEY,
    parent_id        INTEGER REFERENCES categories(category_id),
    level            INTEGER NOT NULL,              -- 1 = Women Ethnic, 3 = leaf
    name             TEXT NOT NULL,
    product_type_key TEXT UNIQUE,                   -- leaf only, e.g. 'kurti'
    gst_rate         REAL NOT NULL DEFAULT 0.05,
    return_rate_prior REAL,                         -- customer returns
    rto_rate_prior   REAL                           -- return-to-origin (COD refusals)
);

-- ------------------------------------------------------------------ sellers
CREATE TABLE sellers (
    seller_id        INTEGER PRIMARY KEY,
    seller_name      TEXT NOT NULL,
    city             TEXT NOT NULL,
    state            TEXT NOT NULL,
    tier             TEXT NOT NULL CHECK (tier IN ('new','bronze','silver','gold')),
    seller_rating    REAL NOT NULL,                 -- 1..5, aggregate of all products
    joined_on        DATE NOT NULL,
    is_demo_seller   INTEGER NOT NULL DEFAULT 0     -- 1 = sellers used in the demo UI
);

-- ------------------------------------------------------------------ catalogue
-- Meesho groups similar products uploaded together into a "catalog".
CREATE TABLE catalogs (
    catalog_id       INTEGER PRIMARY KEY,
    seller_id        INTEGER NOT NULL REFERENCES sellers(seller_id),
    catalog_name     TEXT NOT NULL,
    created_on       DATE NOT NULL
);

CREATE TABLE products (
    product_id       INTEGER PRIMARY KEY,
    catalog_id       INTEGER NOT NULL REFERENCES catalogs(catalog_id),
    seller_id        INTEGER NOT NULL REFERENCES sellers(seller_id),
    category_id      INTEGER NOT NULL REFERENCES categories(category_id),
    title            TEXT NOT NULL,
    description      TEXT NOT NULL,
    fabric           TEXT NOT NULL,
    pattern          TEXT NOT NULL,
    sleeve           TEXT NOT NULL,
    length           TEXT NOT NULL,
    occasion         TEXT NOT NULL,
    color            TEXT NOT NULL,
    sizes            TEXT NOT NULL,                 -- comma list, e.g. 'S,M,L,XL'
    n_images         INTEGER NOT NULL,
    weight_g         INTEGER NOT NULL,              -- product weight (unpacked)
    package_size     TEXT NOT NULL CHECK (package_size IN ('S','M','L')),
    mrp              INTEGER NOT NULL,              -- strike-through price
    current_price    INTEGER NOT NULL,              -- price buyer pays (GST incl.)
    cogs             INTEGER,                       -- only known for our own sellers
    listed_on        DATE NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','delisted')),
    recommendation_id INTEGER REFERENCES pricing_recommendations(recommendation_id), -- set when listed via the agent
    origin           TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed','seller'))  -- demo data vs listed in the app
);
CREATE INDEX idx_products_segment ON products(category_id, fabric, pattern);
CREATE INDEX idx_products_seller ON products(seller_id);

CREATE TABLE inventory (
    product_id       INTEGER PRIMARY KEY REFERENCES products(product_id),
    units_available  INTEGER NOT NULL,
    updated_on       DATE NOT NULL
);

-- Every price change a seller makes (effective until the next row).
CREATE TABLE price_history (
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    effective_from   DATE NOT NULL,
    price            INTEGER NOT NULL,
    PRIMARY KEY (product_id, effective_from)
);

-- ------------------------------------------------------------------ performance
-- Daily funnel per product: impressions -> clicks (CTR) -> orders (CVR).
CREATE TABLE daily_product_metrics (
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    metric_date      DATE NOT NULL,
    price            INTEGER NOT NULL,
    impressions      INTEGER NOT NULL,
    clicks           INTEGER NOT NULL,
    orders           INTEGER NOT NULL,
    customer_returns INTEGER NOT NULL,
    rto              INTEGER NOT NULL,
    PRIMARY KEY (product_id, metric_date)
);
CREATE INDEX idx_metrics_date ON daily_product_metrics(metric_date);

CREATE TABLE reviews (
    review_id        INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products(product_id),
    rating           INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    theme            TEXT NOT NULL,                 -- tagged topic, e.g. 'size_issue'
    review_text      TEXT NOT NULL,
    review_date      DATE NOT NULL
);
CREATE INDEX idx_reviews_product ON reviews(product_id);

-- ------------------------------------------------------------------ reference
CREATE TABLE shipping_rate_card (
    max_weight_g     INTEGER PRIMARY KEY,
    forward_charge   INTEGER NOT NULL,
    reverse_charge   INTEGER NOT NULL
);

CREATE TABLE packaging_rate_card (
    size_class       TEXT PRIMARY KEY,
    cost             INTEGER NOT NULL,
    added_weight_g   INTEGER NOT NULL,
    description      TEXT NOT NULL
);

CREATE TABLE festival_calendar (
    event_name       TEXT NOT NULL,
    event_date       DATE NOT NULL,
    demand_uplift    REAL NOT NULL,
    lead_days        INTEGER NOT NULL,
    boosts_occasion  TEXT NOT NULL,
    PRIMARY KEY (event_name, event_date)
);

CREATE TABLE fabric_seasonality (
    fabric           TEXT NOT NULL,
    month            INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    demand_index     REAL NOT NULL,
    PRIMARY KEY (fabric, month)
);

-- ------------------------------------------------------------------ agent output
CREATE TABLE pricing_recommendations (
    recommendation_id INTEGER PRIMARY KEY,
    created_at       TEXT NOT NULL,
    seller_id        INTEGER REFERENCES sellers(seller_id),
    mode             TEXT NOT NULL,
    input_json       TEXT NOT NULL,
    recommended_price INTEGER NOT NULL,
    output_json      TEXT NOT NULL
);
