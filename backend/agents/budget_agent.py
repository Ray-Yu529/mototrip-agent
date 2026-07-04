"""
Budget Agent — 純邏輯試算，不呼叫 LLM。
依各日實際路線距離（routing.py 算出的 OSRM 真實距離）換算油錢，
餐飲費用依使用者選擇的預算等級（Google price_level 0–4）粗估。
僅供參考，不含住宿與其他雜支。
"""

FUEL_CONSUMPTION_L_PER_100KM = {"機車": 3.0, "重機": 5.5, "汽車": 7.5}


def estimate_budget(
    itinerary: list[dict],
    transport: str,
    fuel_price_per_liter: float,
    meal_price_by_level: dict[int, int],
    min_price: int | None = None,
    max_price: int | None = None,
) -> dict:
    consumption = FUEL_CONSUMPTION_L_PER_100KM.get(transport)

    # 使用者有選預算等級就取範圍平均，否則用中間等級（2 = 中價位）當粗估基準
    if min_price is not None or max_price is not None:
        lo = min_price if min_price is not None else 0
        hi = max_price if max_price is not None else 4
        avg_level = (lo + hi) / 2
    else:
        avg_level = 2
    meal_unit_price = _interp_meal_price(avg_level, meal_price_by_level)

    per_day = []
    total_distance_km = 0.0
    total_fuel_cost = 0.0
    total_meal_cost = 0.0

    for day in itinerary:
        distance_km = day.get("route", {}).get("distance_km", 0.0)
        fuel_cost = round(distance_km / 100 * consumption * fuel_price_per_liter) if consumption else 0

        meal_stops = sum(1 for s in day.get("stops", []) if s.get("type") == "餐廳")
        meal_cost = round(meal_stops * meal_unit_price)

        per_day.append({
            "day": day.get("day"),
            "distance_km": distance_km,
            "fuel_cost_twd": fuel_cost,
            "meal_stops": meal_stops,
            "meal_cost_twd": meal_cost,
        })
        total_distance_km += distance_km
        total_fuel_cost += fuel_cost
        total_meal_cost += meal_cost

    return {
        "transport": transport,
        "total_distance_km": round(total_distance_km, 1),
        "total_fuel_cost_twd": round(total_fuel_cost),
        "total_meal_cost_twd": round(total_meal_cost),
        "estimated_total_twd": round(total_fuel_cost + total_meal_cost),
        "per_day": per_day,
        "note": "粗估值，不含住宿與其他雜支；油錢依平均油耗與現時油價換算，"
                "實際依路況、車型、駕駛習慣而異；" +
                ("自行車/大眾運輸不計油錢" if consumption is None else ""),
    }


def _interp_meal_price(level: float, meal_price_by_level: dict[int, int]) -> float:
    """price_level 允許是 0–4 之間的浮點平均值，線性內插對應價格。"""
    lo_level = int(level)
    hi_level = min(lo_level + 1, 4)
    lo_price = meal_price_by_level.get(lo_level, meal_price_by_level[2])
    hi_price = meal_price_by_level.get(hi_level, lo_price)
    frac = level - lo_level
    return lo_price + (hi_price - lo_price) * frac
