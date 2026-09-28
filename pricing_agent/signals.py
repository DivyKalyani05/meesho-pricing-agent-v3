"""Seasonality and festival demand signals (shared by the data generator and the engine)."""
from datetime import date, timedelta

from . import config


def season_index(d: date, fabric: str) -> float:
    """Monthly fabric demand index, linearly interpolated so it moves smoothly day to day."""
    months = config.FABRIC_SEASON.get(fabric, [1.0] * 12)
    m = d.month - 1
    frac = (d.day - 1) / 30.0
    # blend this month (weight falls through the month) with the next month
    this_m, next_m = months[m], months[(m + 1) % 12]
    return this_m + (next_m - this_m) * max(0.0, frac - 0.5)


def _festival_sensitivity(occasion: str, boosts: str) -> float:
    if boosts == "all":
        return 0.8
    if boosts == occasion:
        return 1.0
    if boosts == "festive":
        return config.OCCASION_FESTIVAL_SENSITIVITY.get(occasion, 0.5)
    return 0.5


def festival_index(d: date, occasion: str):
    """Demand multiplier from festivals around date d, plus the festival driving it (or None)."""
    best, best_name = 1.0, None
    for name, fdate, uplift, lead, boosts in config.FESTIVALS:
        days_before = (fdate - d).days
        if -1 <= days_before <= lead:
            # ramps up towards the festival, stays at peak for the day after
            ramp = 1.0 if days_before <= 0 else 1.0 - days_before / (lead + 1)
            val = 1.0 + (uplift - 1.0) * ramp * _festival_sensitivity(occasion, boosts)
            if val > best:
                best, best_name = val, name
    return best, best_name


def demand_multiplier(d: date, fabric: str, occasion: str) -> float:
    return season_index(d, fabric) * festival_index(d, occasion)[0]


def window_average(start: date, days: int, fabric: str, occasion: str) -> dict:
    """Average season / festival effect over a selling window, and the festivals inside it."""
    days = max(1, int(days))
    s_sum = f_sum = c_sum = 0.0
    for i in range(days):
        d = start + timedelta(days=i)
        s = season_index(d, fabric)
        f, name = festival_index(d, occasion)
        s_sum += s
        f_sum += f
        c_sum += s * f
    upcoming = []
    end = start + timedelta(days=days)
    for name, fdate, uplift, lead, boosts in config.FESTIVALS:
        if start <= fdate < end:
            peak = (uplift - 1.0) * _festival_sensitivity(occasion, boosts)
            upcoming.append({"name": name, "date": fdate.isoformat(), "days_away": (fdate - start).days,
                             "peak_uplift_pct": round(peak * 100)})
    upcoming.sort(key=lambda e: e["date"])
    return {"season": s_sum / days, "festival": f_sum / days, "combined": c_sum / days,
            "events": upcoming}
