"""
Turns the numbers into simple, seller-friendly reasons (English + Hindi).

Every reason is backed by a counterfactual: we re-run the optimiser with one
factor switched off, so "+Rs 20 because of Navratri" is a real, computed effect.
"""
from datetime import timedelta

from . import config

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
FEST_HI = {
    "Republic Day Sale": "रिपब्लिक डे सेल", "Holi": "होली", "Eid al-Fitr": "ईद", "Akshaya Tritiya": "अक्षय तृतीया",
    "Independence Day Sale": "इंडिपेंडेंस डे सेल", "Raksha Bandhan": "रक्षाबंधन", "Ganesh Chaturthi": "गणेश चतुर्थी",
    "Navratri / Garba": "नवरात्रि / गरबा", "Dussehra & Durga Puja": "दशहरा और दुर्गा पूजा", "Karwa Chauth": "करवा चौथ",
    "Diwali": "दिवाली", "Chhath Puja": "छठ पूजा", "Wedding Season": "शादी का सीज़न",
}
COMPLAINT_HI = {"size_issue": "साइज़ / फिटिंग की समस्या", "fabric_thin": "पतला कपड़ा",
                "color_mismatch": "फोटो से अलग रंग", "stitching": "खराब सिलाई"}
COMPLAINT_TIP = {
    "size_issue": ("Add a clear size chart (bust, length, hip in inches) - it is the #1 reason for returns.",
                   "साफ़ साइज़ चार्ट (छाती, लंबाई, हिप इंच में) ज़रूर डालें - रिटर्न की सबसे बड़ी वजह यही है।"),
    "fabric_thin": ("Mention fabric thickness / lining and show a close-up photo of the fabric.",
                    "कपड़े की मोटाई / लाइनिंग लिखें और कपड़े की क्लोज़-अप फोटो डालें।"),
    "color_mismatch": ("Shoot photos in daylight so the colour matches what buyers receive.",
                       "फोटो दिन की रोशनी में खींचें ताकि रंग असली जैसा दिखे।"),
    "stitching": ("Do a stitching quality check before dispatch - poor finishing drives 1-star reviews.",
                  "डिस्पैच से पहले सिलाई चेक करें - खराब फिनिशिंग से 1-स्टार रिव्यू आते हैं।"),
}


def inr(x):
    """Indian digit grouping: 123456 -> Rs 1,23,456."""
    neg = x < 0
    s = str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-₹" if neg else "₹") + s


def _signed(x):
    return ("+" if x > 0 else "−") + inr(abs(x))


def orders_phrase(opd):
    """3.2 -> 'about 3.2 orders a day'; 0.2 -> 'about 1 order every 5 days'."""
    if opd >= 0.95:
        return _t(f"about {round(opd, 1):g} orders a day", f"रोज़ लगभग {round(opd, 1):g} ऑर्डर")
    if opd >= 0.03:
        n = int(round(1 / opd))
        return _t(f"about 1 order every {n} days", f"लगभग हर {n} दिन में 1 ऑर्डर")
    return _t("very few orders", "बहुत कम ऑर्डर")


def _t(en, hi):
    return {"en": en, "hi": hi}


def build_explanation(res, cf, best, inp, eco, sc):
    rec = res["recommendation"]
    mkt = res["market"]
    dm = res["demand_model"]
    attrs = res["attributes"]
    price = rec["entry_price"]
    reasons, tips, warnings = [], [], []
    product_en = f"{attrs['fabric']['label']} {attrs['pattern']['label']} {attrs['product_type']['label']}".lower()

    # 1. market anchor ---------------------------------------------------------
    p25, p75, swm = int(mkt["price_p25"]), int(mkt["price_p75"]), int(mkt["sales_weighted_median"])
    pct = rec["percentile_in_market"]
    pos_en = (f"₹{price} is cheaper than {100 - pct}% of them" if pct < 50
              else f"₹{price} is priced above {pct}% of them")
    pos_hi = (f"₹{price} इनमें से {100 - pct}% से सस्ता है" if pct < 50 else f"₹{price} इनमें से {pct}% से ऊपर है")
    reasons.append({
        "icon": "market", "tone": "neutral", "effect": f"₹{p25}–₹{p75}",
        "title": _t("What similar kurtis sell for", "आपके जैसी कुर्तियाँ किस दाम पर बिकती हैं"),
        "text": _t(f"We studied {mkt['n_comparable']} live Meesho listings similar to your {product_en}. "
                   f"Most sell between ₹{p25} and ₹{p75}, and the best-sellers cluster around ₹{swm}. {pos_en}.",
                   f"हमने Meesho पर आपके प्रोडक्ट जैसी {mkt['n_comparable']} लिस्टिंग देखीं। ज़्यादातर ₹{p25} से ₹{p75} में "
                   f"बिकती हैं, और सबसे ज़्यादा बिकने वाली लगभग ₹{swm} पर हैं। {pos_hi}।"),
    })

    # 2. cost floor -----------------------------------------------------------
    be = rec["break_even_price"]
    ppo = rec["profit_per_order"]
    reasons.append({
        "icon": "cost", "tone": "positive" if ppo > 0 else "negative", "effect": f"min ₹{be}",
        "title": _t("Your cost floor", "आपकी न्यूनतम कीमत"),
        "text": _t(f"Your cost {inr(eco.cogs)} + shipping {inr(eco.fwd)} + packaging {inr(eco.packaging)} + GST + returns "
                   f"means anything below ₹{be} loses money. At ₹{price} you keep about {inr(ppo)} on every order "
                   f"({inr(rec['profit_per_delivered_order'])} on every order the buyer keeps).",
                   f"लागत {inr(eco.cogs)} + शिपिंग {inr(eco.fwd)} + पैकिंग {inr(eco.packaging)} + GST + रिटर्न जोड़कर, "
                   f"₹{be} से कम कीमत पर घाटा होगा। ₹{price} पर हर ऑर्डर पर लगभग {inr(ppo)} बचेंगे "
                   f"(जो ऑर्डर ग्राहक रखता है उस पर {inr(rec['profit_per_delivered_order'])})।"),
    })

    # 3. season & festivals -----------------------------------------------------
    d_season = price - cf["no_season"]["price"]
    demand_change = round(100 * (dm["window_multiplier"] / dm["history_multiplier"] - 1))
    launch = inp["launch_date"]
    fests = dm["festivals"]
    season_change = round(100 * (dm["season_index"] / dm["history_season_index"] - 1))
    fest_pct = round(100 * (dm["festival_index"] - 1))
    occ_en = attrs["occasion"]["label"].lower()
    if fests or abs(season_change) >= 4 or abs(demand_change) >= 5:
        parts_en, parts_hi = [], []
        if fests:
            names_en = " and ".join(f"{f['name']} ({f['days_away']} days away)" for f in fests[:2])
            names_hi = " और ".join(f"{FEST_HI.get(f['name'], f['name'])} ({f['days_away']} दिन में)" for f in fests[:2])
            parts_en.append(f"{names_en} fall in your selling window, lifting demand for {occ_en} kurtis by ~{fest_pct}% on average.")
            parts_hi.append(f"आपकी बिक्री के समय में {names_hi} आ रहे हैं, जिससे ऐसी कुर्तियों की माँग औसतन ~{fest_pct}% बढ़ेगी।")
        if abs(season_change) >= 4:
            mid = launch + timedelta(days=rec["horizon_days"] // 2)   # month the selling window is centred on
            mon_en, mon_hi = MONTHS_EN[mid.month - 1], MONTHS_HI[mid.month - 1]
            fab = attrs["fabric"]["label"]
            up = season_change > 0
            parts_en.append(f"{fab} is seasonally {'in higher' if up else 'in lower'} demand in {mon_en} "
                            f"({season_change:+d}% vs the last four months).")
            parts_hi.append(f"{mon_hi} में {fab} की माँग मौसम के हिसाब से {'ज़्यादा' if up else 'कम'} रहती है "
                            f"(पिछले चार महीनों से {season_change:+d}%)।")
        if demand_change >= 0:
            net_en = f"Overall we expect ~{demand_change}% more buyers than recent months, and they compare prices less"
            net_hi = f"कुल मिलाकर पिछले महीनों से ~{demand_change}% ज़्यादा ग्राहक आएँगे और वे कीमत कम तुलना करेंगे"
        else:
            net_en = f"Overall we expect ~{-demand_change}% fewer buyers than recent months, and they hunt for deals"
            net_hi = f"कुल मिलाकर पिछले महीनों से ~{-demand_change}% कम ग्राहक आएँगे और वे सस्ता ढूँढेंगे"
        if d_season:
            net_en += f", so the price moves {_signed(d_season)}."
            net_hi += f", इसलिए कीमत {_signed(d_season)} बदली है।"
        else:
            net_en += " - this changes how much you sell more than the best price."
            net_hi += " - इसका असर कीमत से ज़्यादा बिक्री पर है।"
        parts_en.append(net_en)
        parts_hi.append(net_hi)
        reasons.append({
            "icon": "festival" if fests else "season",
            "tone": "neutral" if abs(demand_change) < 3 else ("positive" if demand_change > 0 else "negative"),
            "effect": _signed(d_season) if d_season else f"{demand_change:+d}% demand",
            "title": _t("Festival & season effect" if fests else "Season effect", "त्योहार और सीज़न का असर" if fests else "सीज़न का असर"),
            "text": _t(" ".join(parts_en), " ".join(parts_hi)),
        })

    # 4. new listing -----------------------------------------------------------
    d_new = cf["no_new"]["price"] - price
    lost = round(100 * (1 - dm["new_listing_factor"]))
    steady = rec.get("steady_price")
    steady_en = f" Once you have 20-25 good reviews, move the price to ₹{steady}." if steady and steady > price else ""
    steady_hi = f" 20-25 अच्छे रिव्यू आने के बाद कीमत ₹{steady} कर दें।" if steady and steady > price else ""
    reasons.append({
        "icon": "new", "tone": "neutral", "effect": f"−₹{d_new}" if d_new > 0 else "₹0",
        "title": _t("Entry discount for a new listing", "नई लिस्टिंग के लिए शुरुआती छूट"),
        "text": _t(f"New listings have no ratings yet and on Meesho sell ~{lost}% less in their first month. "
                   f"Buyers without reviews to trust are more price-sensitive, so we start "
                   f"{'₹' + str(d_new) + ' lower' if d_new > 0 else 'at the market level'} to win the first orders and reviews, "
                   f"which lift your ranking in search.{steady_en}",
                   f"नई लिस्टिंग पर रेटिंग नहीं होती और पहले महीने में ~{lost}% कम बिक्री होती है। "
                   f"बिना रिव्यू के ग्राहक कीमत पर ज़्यादा ध्यान देते हैं, इसलिए हम "
                   f"{'₹' + str(d_new) + ' कम' if d_new > 0 else 'बाज़ार भाव'} से शुरू कर रहे हैं ताकि पहले ऑर्डर और रिव्यू जल्दी आएँ "
                   f"और सर्च में रैंक बढ़े।{steady_hi}"),
    })

    # 5. seller track record ----------------------------------------------------
    seller = res.get("seller")
    if seller and seller.get("ctr_pct"):
        f = seller["ctr_factor"]
        diff = round(100 * (f - 1))
        closest = seller.get("closest")
        extra_en = extra_hi = ""
        if closest and closest["similarity_pct"] >= 50:
            extra_en = (f" Your most similar past listing (\"{closest['title']}\") sold {closest['orders_per_day']} "
                        f"orders/day at ₹{closest['price']}.")
            extra_hi = f" आपकी मिलती-जुलती पुरानी लिस्टिंग ₹{closest['price']} पर रोज़ {closest['orders_per_day']} ऑर्डर बेचती थी।"
        reasons.append({
            "icon": "seller", "tone": "positive" if diff >= 0 else "negative", "effect": f"{diff:+d}% orders",
            "title": _t("Your past performance", "आपका पिछला प्रदर्शन"),
            "text": _t(f"Buyers click your listings {seller['ctr_pct']}% of the time vs {seller['category_ctr_pct']}% for the "
                       f"category, so we expect {abs(diff)}% {'more' if diff >= 0 else 'fewer'} orders than an average seller.{extra_en}",
                       f"ग्राहक आपकी लिस्टिंग पर {seller['ctr_pct']}% बार क्लिक करते हैं, जबकि कैटेगरी में औसत {seller['category_ctr_pct']}% है, "
                       f"इसलिए औसत से {abs(diff)}% {'ज़्यादा' if diff >= 0 else 'कम'} ऑर्डर की उम्मीद है।{extra_hi}"),
        })
    else:
        reasons.append({
            "icon": "seller", "tone": "neutral", "effect": "avg",
            "title": _t("Your past performance", "आपका पिछला प्रदर्शन"),
            "text": _t("You have no earlier kurti listings, so we assumed average click-through. As your first listing gets "
                       "views, the agent will learn your real click rate and fine-tune the price.",
                       "आपकी पहले कोई कुर्ती लिस्टिंग नहीं है, इसलिए हमने औसत क्लिक रेट माना है। लिस्टिंग चलने पर एजेंट "
                       "आपका असली क्लिक रेट सीखकर कीमत और सही करेगा।"),
        })

    # 6. competition -----------------------------------------------------------
    crowd = mkt["crowding_index"]
    d_crowd = price - cf["no_crowd"]["price"]
    if crowd >= 1.05 or crowd <= 0.95:
        busy = crowd >= 1.05
        reasons.append({
            "icon": "crowd", "tone": "negative" if busy else "positive",
            "effect": _signed(d_crowd) if d_crowd else ("crowded" if busy else "open"),
            "title": _t("How crowded this segment is", "इस सेगमेंट में कितनी भीड़ है"),
            "text": _t(f"{mkt['n_direct_competitors']} near-identical listings share about {round(mkt['direct_competitor_daily_orders'])} "
                       f"orders a day - {'more' if busy else 'less'} competition per order than the average kurti. "
                       + ("Buyers have many options, so a high price loses sales quickly." if busy
                          else "There is room to price a little higher."),
                       f"{mkt['n_direct_competitors']} लगभग एक जैसी लिस्टिंग रोज़ करीब {round(mkt['direct_competitor_daily_orders'])} ऑर्डर बाँटती हैं - "
                       f"औसत कुर्ती से {'ज़्यादा' if busy else 'कम'} मुकाबला। "
                       + ("ग्राहकों के पास बहुत विकल्प हैं, इसलिए ज़्यादा कीमत पर बिक्री तेज़ी से गिरती है।" if busy
                          else "कीमत थोड़ी ज़्यादा रखने की गुंजाइश है।")),
        })

    # 7. returns ---------------------------------------------------------------
    econ = res["economics"]
    ret_cost = eco.ret * eco.rev + eco.rto * config.RTO_CHARGE + eco.cogs * eco.ret * config.DAMAGED_RETURN_SHARE
    lost_rev = (eco.ret + eco.rto) * price
    reasons.append({
        "icon": "returns", "tone": "negative", "effect": f"{econ['return_rate_pct'] + econ['rto_rate_pct']:.0f}% come back",
        "title": _t("Returns are priced in", "रिटर्न का खर्च शामिल है"),
        "text": _t(f"About {econ['return_rate_pct']}% of kurtis like this are returned and {econ['rto_rate_pct']}% are refused at "
                   f"delivery (RTO). That costs you ~{inr(ret_cost)} per order in return shipping and damaged pieces - "
                   f"already included in the price.",
                   f"ऐसी कुर्तियों में लगभग {econ['return_rate_pct']}% रिटर्न होती हैं और {econ['rto_rate_pct']}% डिलीवरी पर "
                   f"वापस आती हैं (RTO)। इससे हर ऑर्डर पर ~{inr(ret_cost)} खर्च होता है - यह कीमत में पहले से शामिल है।"),
    })

    # 8. inventory / goal ------------------------------------------------------
    mode = inp["mode"]
    inv = inp["inventory"]
    dts = rec["days_to_sell_out"]
    if mode == "clear_inventory":
        if rec["note"] == "cannot_clear" and rec["has_expiry"]:
            txt_en = (f"Your stock must go before {inp['expiry_date'].strftime('%d %b')}. Selling all {inv} pieces would need a price "
                      f"so low that you'd lose more than by writing off the rest. At ₹{price} you sell about "
                      f"{rec['units_sold_in_horizon']} pieces - the smallest overall loss. A combo offer or Meesho ads can help sell the rest.")
            txt_hi = (f"आपका स्टॉक {inp['expiry_date'].strftime('%d %b')} से पहले बिकना चाहिए। सारे {inv} पीस बेचने के लिए कीमत इतनी कम करनी "
                      f"पड़ेगी कि नुकसान बचा स्टॉक छोड़ने से भी ज़्यादा होगा। ₹{price} पर लगभग {rec['units_sold_in_horizon']} पीस बिकेंगे - "
                      f"यह सबसे कम नुकसान वाला रास्ता है। बाकी के लिए कॉम्बो ऑफ़र या Meesho ads आज़माएँ।")
        elif rec["note"] == "cannot_clear":
            txt_en = (f"Even at ₹{price} we expect to sell about {rec['units_sold_in_horizon']} of your {inv} pieces in "
                      f"{rec['horizon_days']} days. Consider a longer window, a combo offer, or Meesho ads.")
            txt_hi = (f"₹{price} पर भी {rec['horizon_days']} दिनों में आपके {inv} में से लगभग {rec['units_sold_in_horizon']} पीस बिकेंगे। "
                      f"समय बढ़ाएँ, कॉम्बो ऑफ़र या Meesho ads आज़माएँ।")
        else:
            by_en = (f"before your sell-by date ({inp['expiry_date'].strftime('%d %b')}, {rec['horizon_days']} days away)"
                     if rec["has_expiry"] else f"within {rec['horizon_days']} days")
            by_hi = (f"sell-by date ({inp['expiry_date'].strftime('%d %b')}, {rec['horizon_days']} दिन बाद) से पहले"
                     if rec["has_expiry"] else f"{rec['horizon_days']} दिन में")
            txt_en = (f"Your goal is to clear {inv} pieces {by_en}. ₹{price} is the highest price at "
                      f"which we expect everything to sell in time (about {dts} days).")
            txt_hi = (f"आपका लक्ष्य {by_hi} {inv} पीस बेचना है। ₹{price} वह सबसे ऊँची कीमत है जिस पर "
                      f"सारा स्टॉक समय पर (लगभग {dts} दिन में) बिक जाएगा।")
        reasons.append({"icon": "stock", "tone": "neutral", "effect": f"{inv} pcs",
                        "title": _t("Clearing your stock", "स्टॉक खाली करना"), "text": _t(txt_en, txt_hi)})
    else:
        ul = cf.get("unlimited_stock")
        d_stock = price - ul["price"] if ul else 0
        if d_stock > 0:
            reasons.append({
                "icon": "stock", "tone": "positive", "effect": _signed(d_stock),
                "title": _t("Limited stock", "सीमित स्टॉक"),
                "text": _t(f"You have only {inv} pieces. At a lower price they would sell out too early, so we priced "
                           f"₹{d_stock} higher to earn more on each piece (sell-out in ~{dts} days).",
                           f"आपके पास सिर्फ़ {inv} पीस हैं। कम कीमत पर ये बहुत जल्दी बिक जाते, इसलिए कीमत ₹{d_stock} ज़्यादा रखी "
                           f"है ताकि हर पीस पर ज़्यादा कमाई हो (~{dts} दिन में स्टॉक खत्म)।"),
            })

    # 9. photos ----------------------------------------------------------------
    n_ph = inp["n_photos"]
    if n_ph < 4:
        gain = round(100 * (1.0 / max(dm["photo_factor"], 0.01) - 1)) if dm["photo_factor"] < 1 else 5
        tips.append(_t(f"Add at least 4 photos (you have {n_ph}). Listings with 4+ photos get noticeably more clicks "
                       f"- roughly {gain}% more orders for you.",
                       f"कम से कम 4 फोटो डालें (अभी {n_ph} हैं)। 4+ फोटो वाली लिस्टिंग पर ज़्यादा क्लिक आते हैं - "
                       f"लगभग {gain}% ज़्यादा ऑर्डर।"))
    # complaints -> tips
    for c in mkt.get("complaints", [])[:2]:
        en, hi = COMPLAINT_TIP[c["theme"]]
        tips.append(_t(f"{c['share_pct']}% of reviews on similar kurtis mention {c['label']}. {en}",
                       f"मिलती-जुलती कुर्तियों के {c['share_pct']}% रिव्यू में {COMPLAINT_HI[c['theme']]} की शिकायत है। {hi}"))
    if rec["suggested_mrp"] > price:
        tips.append(_t(f"Show an MRP of ₹{rec['suggested_mrp']} - similar listings display a similar strike-through discount "
                       f"({rec['discount_shown_pct']}% off).",
                       f"MRP ₹{rec['suggested_mrp']} दिखाएँ - मिलती-जुलती लिस्टिंग भी ऐसी ही छूट ({rec['discount_shown_pct']}% off) दिखाती हैं।"))

    # 10. offline channel --------------------------------------------------------
    off = res.get("offline")
    if off:
        diff = off["online_vs_offline_pct"]
        line_en = (f"Online price is {abs(diff)}% {'below' if diff < 0 else 'above'} your shop price of ₹{off['offline_price']}.")
        line_hi = (f"ऑनलाइन कीमत आपकी दुकान की कीमत ₹{off['offline_price']} से {abs(diff)}% {'कम' if diff < 0 else 'ज़्यादा'} है।")
        if "offline_profit_per_piece" in off:
            line_en += (f" In the shop you earn ₹{off['offline_profit_per_piece']} per piece; on Meesho you earn "
                        f"₹{off['online_profit_per_delivered']} per delivered piece, but reach buyers all over India.")
            line_hi += (f" दुकान में आप प्रति पीस ₹{off['offline_profit_per_piece']} कमाते हैं; Meesho पर प्रति डिलीवर्ड पीस "
                        f"₹{off['online_profit_per_delivered']} - लेकिन पूरे भारत के ग्राहक मिलते हैं।")
        reasons.append({"icon": "shop", "tone": "neutral", "effect": f"{diff:+.0f}% vs shop",
                        "title": _t("Compared with your shop", "आपकी दुकान से तुलना"), "text": _t(line_en, line_hi)})
        if diff > 10:
            warnings.append(_t("Your online price is well above your shop price - buyers who know your shop may notice.",
                               "ऑनलाइन कीमत दुकान से काफ़ी ज़्यादा है - दुकान के ग्राहक इसे देख सकते हैं।"))

    # warnings -----------------------------------------------------------------
    if rec["note"] == "no_profitable_price":
        warnings.append(_t("At this cost, the kurti can't be sold profitably. Try lowering the cost or choosing a different design.",
                           "इस लागत पर यह कुर्ती मुनाफ़े में नहीं बिक सकती। लागत कम करें या दूसरा डिज़ाइन चुनें।"))
    if price < be:
        warnings.append(_t(f"₹{price} is below your break-even of ₹{be}: you lose a little on each piece, but less than writing "
                           f"off unsold stock after the sell-by date.",
                           f"₹{price} आपकी न्यूनतम कीमत ₹{be} से कम है: हर पीस पर थोड़ा नुकसान होगा, लेकिन बचा स्टॉक फेंकने से कम।"))
    if inp["cogs_source"] != "seller":
        warnings.append(_t(f"We estimated your cost as {inr(eco.cogs)} from your shop price and margin. Enter the exact cost for a sharper price.",
                           f"आपकी लागत {inr(eco.cogs)} दुकान की कीमत और मार्जिन से अनुमानित है। सटीक कीमत के लिए असली लागत डालें।"))
    if dm.get("note"):
        warnings.append(_t(dm["note"], "इस सेगमेंट में डेटा कम है - अनुमान कैटेगरी औसत पर आधारित है।"))
    if be > mkt["price_p75"]:
        warnings.append(_t(f"Your break-even (₹{be}) is above what most similar kurtis sell for (₹{p25}–₹{p75}). "
                           f"Sales will be slow - try to reduce product or packaging cost, or position it as a premium design.",
                           f"आपकी न्यूनतम कीमत (₹{be}) मिलती-जुलती कुर्तियों के दाम (₹{p25}–₹{p75}) से ज़्यादा है। बिक्री धीमी रहेगी - "
                           f"लागत कम करें या इसे प्रीमियम डिज़ाइन की तरह पेश करें।"))
    elif mkt["price_p90"] and price > mkt["price_p90"]:
        warnings.append(_t("This price is in the top 10% of the market - make sure photos and quality look premium.",
                           "यह कीमत बाज़ार के टॉप 10% में है - फोटो और क्वालिटी प्रीमियम दिखनी चाहिए।"))

    # headline & summary ---------------------------------------------------------
    opd = rec["orders_per_day"]
    horizon = rec["horizon_days"]
    pcs = "piece" if inv == 1 else "pieces"
    if dts and dts <= horizon and rec["stock_limited"]:
        sell_en, sell_hi = f", selling all {inv} {pcs} in about {dts:g} days", f", और लगभग {dts:g} दिन में सारे {inv} पीस बिक जाएँगे"
    elif dts and dts <= horizon:
        sell_en = f". Your {inv} {pcs} will last about {dts:g} days - plan to restock"
        sell_hi = f"। आपके {inv} पीस लगभग {dts:g} दिन चलेंगे - दोबारा स्टॉक की तैयारी रखें"
    else:
        sell_en = sell_hi = ""
    tp = rec["total_profit"]
    if tp >= 0:
        prof_en, prof_hi = f"roughly {inr(tp)} profit", f"लगभग {inr(tp)} मुनाफ़ा"
    else:
        prof_en, prof_hi = f"a net loss of about {inr(-tp)}", f"लगभग {inr(-tp)} का कुल नुकसान"
    if rec.get("writeoff_if_unsold") and tp < 0:
        prof_en += f" (vs {inr(rec['writeoff_if_unsold'])} lost if the stock is not sold at all)"
        prof_hi += f" (स्टॉक न बिकने पर {inr(rec['writeoff_if_unsold'])} का नुकसान होता)"
    if rec["has_expiry"]:
        d = inp["expiry_date"].strftime("%d %b")
        window_en = f"by your sell-by date ({d}, {horizon} days away)"
        window_hi = f"आपकी sell-by date ({d}, {horizon} दिन बाद) तक "
    else:
        window_en, window_hi = f"in the next {horizon} days", f"अगले {horizon} दिनों में "
    summary = _t(
        f"Launch at ₹{price}{' (show MRP ₹' + str(rec['suggested_mrp']) + ')' if rec['suggested_mrp'] > price else ''}. "
        f"Expect {orders_phrase(opd)['en']} and {inr(abs(ppo))} {'profit' if ppo >= 0 else 'loss'} per order - {prof_en} "
        f"{window_en}{sell_en}.{steady_en}",
        f"₹{price} पर लॉन्च करें{' (MRP ₹' + str(rec['suggested_mrp']) + ' दिखाएँ)' if rec['suggested_mrp'] > price else ''}। "
        f"{orders_phrase(opd)['hi']} और हर ऑर्डर पर {inr(abs(ppo))} {'मुनाफ़े' if ppo >= 0 else 'नुकसान'} की उम्मीद है - {window_hi}"
        f"{prof_hi}{sell_hi}।{steady_hi}")
    headline = _t(f"₹{price} is the right entry price for your kurti", f"आपकी कुर्ती के लिए सही शुरुआती कीमत ₹{price} है")
    return {"headline": headline, "summary": summary, "reasons": reasons, "tips": tips, "warnings": warnings}
