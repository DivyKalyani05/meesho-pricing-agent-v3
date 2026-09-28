"""
Business constants for the Kurti pricing prototype.

Everything in this file is an ASSUMPTION that should be replaced by real
Meesho numbers (rate cards, return rates, festival calendar) before
production. They are kept in one place so that swapping them is trivial.
"""
from datetime import date

# Date the synthetic marketplace snapshot is "taken" on. History covers the
# HISTORY_DAYS before this date.
SNAPSHOT_DATE = date(2026, 9, 28)
HISTORY_DAYS = 120

# ---------------------------------------------------------------------------
# Catalogue taxonomy (leaf categories under Women Ethnic > Kurtis & Kurta Sets)
# ---------------------------------------------------------------------------
PRODUCT_TYPES = {
    # key: (display name, price multiplier vs plain kurti, base weight grams)
    "kurti": ("Kurti", 1.00, 190),
    "kurti_bottom": ("Kurti with Bottom (2-pc)", 1.55, 360),
    "kurta_set_dupatta": ("Kurta Set with Dupatta (3-pc)", 2.05, 520),
    "anarkali": ("Anarkali Kurti", 1.35, 300),
}

FABRICS = {
    # key: (display, price multiplier, weight multiplier, typical cogs per plain kurti Rs)
    "cotton": ("Cotton", 1.00, 1.00, 165),
    "rayon": ("Rayon", 0.92, 0.95, 150),
    "georgette": ("Georgette", 1.05, 0.70, 170),
    "crepe": ("Crepe", 0.88, 0.80, 140),
    "silk_blend": ("Silk Blend", 1.35, 0.90, 230),
    "chanderi": ("Chanderi", 1.30, 0.75, 220),
    "khadi": ("Khadi", 1.15, 1.20, 195),
}

PATTERNS = {
    "printed": ("Printed", 1.00),
    "solid": ("Solid", 0.95),
    "block_print": ("Hand Block Print", 1.12),
    "embroidered": ("Embroidered", 1.25),
    "chikankari": ("Chikankari", 1.30),
    "mirror_work": ("Mirror / Sequin Work", 1.35),
}

SLEEVES = {"three_quarter": "3/4 Sleeve", "full": "Full Sleeve", "short": "Short Sleeve", "sleeveless": "Sleeveless"}
LENGTHS = {"short": "Short (hip length)", "knee": "Knee Length", "calf": "Calf / Long"}
OCCASIONS = {"daily": "Daily / Casual", "office": "Office Wear", "festive": "Festive", "party": "Party Wear"}

# Keywords used to auto-detect attributes from a seller's free-text description.
KEYWORDS = {
    "fabric": {
        "cotton": ["cotton", "cambric", "mulmul", "jaipuri cotton"],
        "rayon": ["rayon", "viscose", "reyon"],
        "georgette": ["georgette", "georget"],
        "crepe": ["crepe", "american crepe"],
        "silk_blend": ["silk", "art silk", "banarasi", "satin"],
        "chanderi": ["chanderi"],
        "khadi": ["khadi", "handloom"],
    },
    "pattern": {
        "chikankari": ["chikan", "chikankari", "lucknowi"],
        "mirror_work": ["mirror", "sequin", "sequence", "gota"],
        "embroidered": ["embroider", "thread work", "zari"],
        "block_print": ["block print", "hand block", "bagru", "sanganeri", "dabu", "ajrakh"],
        "solid": ["solid", "plain"],
        "printed": ["print", "floral", "bandhani", "leheriya"],
    },
    "product_type": {
        "kurta_set_dupatta": ["dupatta", "3 piece", "3-piece", "three piece", "suit set"],
        "kurti_bottom": ["pant", "palazzo", "sharara", "bottom", "2 piece", "2-piece", "legging", "salwar"],
        "anarkali": ["anarkali", "flared", "gown"],
    },
    "sleeve": {
        "sleeveless": ["sleeveless"],
        "short": ["short sleeve", "half sleeve", "cap sleeve"],
        "full": ["full sleeve", "long sleeve"],
        "three_quarter": ["3/4", "three quarter", "three-quarter"],
    },
    "length": {
        "short": ["short kurti", "hip length", "top length"],
        "calf": ["calf", "long kurti", "ankle", "floor length"],
        "knee": ["knee"],
    },
    "occasion": {
        "festive": ["festive", "festival", "diwali", "navratri", "wedding", "puja", "eid"],
        "party": ["party", "evening"],
        "office": ["office", "formal", "work wear", "workwear"],
        "daily": ["daily", "casual", "regular", "everyday"],
    },
}

# ---------------------------------------------------------------------------
# Unit economics (ASSUMED rate cards - replace with actual Meesho numbers)
# ---------------------------------------------------------------------------
GST_RATE = 0.05                  # apparel <= Rs 2,500; price is GST-inclusive
PLATFORM_COMMISSION_PCT = 0.0    # Meesho: zero commission to sellers
SHIPPING_SLABS = [               # (max packed grams, forward shipping Rs, reverse shipping Rs)
    (500, 62, 78),
    (1000, 84, 98),
    (1500, 104, 120),
    (99999, 132, 150),
]
RTO_CHARGE = 40                  # charge per undelivered (return-to-origin) order
PACKAGING = {                    # size class: (Rs per unit, packed weight add-on g, description)
    "S": (7, 40, "Small courier poly-bag (up to 26x32 cm)"),
    "M": (10, 60, "Medium poly-bag (32x40 cm) + tag"),
    "L": (15, 90, "Large poly-bag / thin box (40x50 cm)"),
}
DAMAGED_RETURN_SHARE = 0.12      # share of customer returns that can't be resold
SALVAGE_SHARE_OF_COGS = 0.35     # what unsold stock fetches after its sell-by date

# Guard rails for the optimiser
MIN_PROFIT_PER_ORDER_SCALE = 12  # Rs; Scale mode never goes below this
MIN_MARGIN_SCALE = 0.08          # 8% of net revenue
PRICE_ENDINGS = 9                # prices end in 9 (e.g. 349) - common on Meesho
NEW_LISTING_SENSITIVITY_BOOST = 1.15  # buyers are more price sensitive w/o reviews
PRIOR_SENSITIVITY = 3.0          # prior for price sensitivity when data is thin
PRIOR_STRENGTH = 25              # pseudo-observations for the prior

MODES = {
    "balanced": ("Balanced", "Good profit with healthy sales speed"),
    "max_margin": ("Maximum Profit", "Earn the most total profit, even if sales are slower"),
    "scale": ("Scale Fast", "Maximise orders and ranking while staying profitable"),
    "clear_inventory": ("Clear Inventory", "Sell out all stock within the target days"),
}

# ---------------------------------------------------------------------------
# Seasonality: monthly demand index by fabric (1.0 = average month)
# ---------------------------------------------------------------------------
#                   Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec
FABRIC_SEASON = {
    "cotton":     [0.80, 0.90, 1.12, 1.30, 1.35, 1.22, 1.05, 1.00, 0.98, 0.95, 0.85, 0.78],
    "rayon":      [0.92, 0.95, 1.05, 1.10, 1.10, 1.05, 1.02, 1.00, 1.00, 1.00, 0.95, 0.90],
    "georgette":  [1.05, 1.00, 0.92, 0.88, 0.85, 0.90, 0.95, 1.00, 1.05, 1.18, 1.15, 1.10],
    "crepe":      [1.00, 1.00, 1.00, 0.98, 0.95, 0.98, 1.00, 1.00, 1.02, 1.05, 1.02, 1.00],
    "silk_blend": [1.10, 1.05, 0.90, 0.85, 0.80, 0.82, 0.90, 1.00, 1.08, 1.30, 1.25, 1.15],
    "chanderi":   [1.05, 1.00, 0.95, 0.92, 0.88, 0.90, 0.95, 1.02, 1.08, 1.25, 1.18, 1.08],
    "khadi":      [1.25, 1.15, 0.95, 0.80, 0.72, 0.78, 0.90, 1.00, 1.02, 1.08, 1.15, 1.25],
}

# ---------------------------------------------------------------------------
# Festival / event calendar. Dates are approximate (verify with a panchang
# before production). uplift = peak demand multiplier for ethnic wear;
# lead = days before the event that demand starts ramping up.
# ---------------------------------------------------------------------------
FESTIVALS = [
    # (name, date, uplift, lead_days, which occasions it boosts most)
    ("Republic Day Sale", date(2026, 1, 26), 1.10, 5, "all"),
    ("Holi", date(2026, 3, 4), 1.15, 10, "daily"),
    ("Eid al-Fitr", date(2026, 3, 20), 1.30, 14, "festive"),
    ("Akshaya Tritiya", date(2026, 4, 19), 1.08, 6, "festive"),
    ("Independence Day Sale", date(2026, 8, 15), 1.12, 6, "all"),
    ("Raksha Bandhan", date(2026, 8, 28), 1.25, 12, "festive"),
    ("Ganesh Chaturthi", date(2026, 9, 14), 1.15, 8, "festive"),
    ("Navratri / Garba", date(2026, 10, 11), 1.40, 14, "festive"),
    ("Dussehra & Durga Puja", date(2026, 10, 20), 1.35, 10, "festive"),
    ("Karwa Chauth", date(2026, 10, 29), 1.25, 8, "festive"),
    ("Diwali", date(2026, 11, 8), 1.55, 21, "festive"),
    ("Chhath Puja", date(2026, 11, 15), 1.15, 6, "festive"),
    ("Wedding Season", date(2026, 12, 5), 1.20, 14, "party"),
    ("Republic Day Sale", date(2027, 1, 26), 1.10, 5, "all"),
    ("Holi", date(2027, 3, 22), 1.15, 10, "daily"),
    ("Eid al-Fitr", date(2027, 3, 10), 1.30, 14, "festive"),
    ("Raksha Bandhan", date(2027, 8, 17), 1.25, 12, "festive"),
    ("Navratri / Garba", date(2027, 9, 30), 1.40, 14, "festive"),
    ("Diwali", date(2027, 10, 29), 1.55, 21, "festive"),
]

# How strongly a festival lifts a product, by the product's occasion.
OCCASION_FESTIVAL_SENSITIVITY = {"festive": 1.0, "party": 0.8, "office": 0.35, "daily": 0.5}

# ---------------------------------------------------------------------------
# Returns (category priors; the engine blends these with observed data)
# ---------------------------------------------------------------------------
CATEGORY_RETURN_PRIORS = {
    # product_type: (customer return rate, RTO rate)
    "kurti": (0.17, 0.11),
    "kurti_bottom": (0.21, 0.11),
    "kurta_set_dupatta": (0.19, 0.10),
    "anarkali": (0.22, 0.12),
}
