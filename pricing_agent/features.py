"""Understanding the seller's product: attributes from text, and package size / weight."""
import re

from . import config


def detect_attributes(text: str) -> dict:
    """Keyword-based attribute detection from title + description. Returns only what it found."""
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    found = {}
    for attr, options in config.KEYWORDS.items():
        best, best_pos = None, None
        for value, words in options.items():
            for w in words:
                pos = t.find(w)
                if pos >= 0 and (best_pos is None or pos < best_pos):
                    best, best_pos = value, pos
        if best:
            found[attr] = best
    # 'printed' matches inside 'block printed'; prefer the more specific pattern
    if found.get("pattern") == "printed" and any(w in t for w in config.KEYWORDS["pattern"]["block_print"]):
        found["pattern"] = "block_print"
    # a chikankari / mirror / embroidered description implies it is not plain
    return found


def estimate_package(product_type: str, fabric: str, override_size: str = None) -> dict:
    """Estimate packed weight, packaging class and shipping slab for a product."""
    base_w = config.PRODUCT_TYPES[product_type][2] * config.FABRICS[fabric][2]
    size = override_size if override_size in config.PACKAGING else (
        "S" if base_w < 260 else ("M" if base_w < 450 else "L"))
    pack_cost, pack_w, pack_desc = config.PACKAGING[size]
    packed = int(round(base_w + pack_w))
    for max_w, fwd, rev in config.SHIPPING_SLABS:
        if packed <= max_w:
            break
    slab_lo = 0
    for mw, _, _ in config.SHIPPING_SLABS:
        if mw == max_w:
            break
        slab_lo = mw
    return {
        "product_weight_g": int(round(base_w)), "packed_weight_g": packed, "package_size": size,
        "package_desc": pack_desc, "packaging_cost": pack_cost, "shipping_forward": fwd, "shipping_reverse": rev,
        "shipping_slab": f"{slab_lo}-{max_w} g" if max_w < 99999 else f"{slab_lo}+ g",
    }
