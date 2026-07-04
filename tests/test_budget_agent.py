from backend.agents.budget_agent import estimate_budget

MEAL_PRICE = {0: 100, 1: 150, 2: 300, 3: 600, 4: 1200}


def _itinerary_with_distance(distance_km: float, meal_stops: int):
    return [{
        "day": 1,
        "route": {"distance_km": distance_km},
        "stops": [{"type": "餐廳"} for _ in range(meal_stops)] + [{"type": "景點"}],
    }]


def test_estimate_budget_motorcycle_fuel_cost():
    itinerary = _itinerary_with_distance(100.0, meal_stops=2)
    result = estimate_budget(itinerary, "機車", fuel_price_per_liter=32.0,
                              meal_price_by_level=MEAL_PRICE)
    # 機車 3L/100km * 100km * 32 = 96
    assert result["total_fuel_cost_twd"] == 96
    assert result["total_meal_cost_twd"] == 600  # 2 餐 * 300（預設中價位）
    assert result["estimated_total_twd"] == 696


def test_estimate_budget_bicycle_has_no_fuel_cost():
    itinerary = _itinerary_with_distance(50.0, meal_stops=1)
    result = estimate_budget(itinerary, "自行車", fuel_price_per_liter=32.0,
                              meal_price_by_level=MEAL_PRICE)
    assert result["total_fuel_cost_twd"] == 0
    assert "不計油錢" in result["note"]


def test_estimate_budget_respects_price_preference_range():
    itinerary = _itinerary_with_distance(0.0, meal_stops=1)
    cheap = estimate_budget(itinerary, "機車", 32.0, MEAL_PRICE, min_price=0, max_price=0)
    expensive = estimate_budget(itinerary, "機車", 32.0, MEAL_PRICE, min_price=4, max_price=4)
    assert cheap["total_meal_cost_twd"] < expensive["total_meal_cost_twd"]
    assert cheap["total_meal_cost_twd"] == 100
    assert expensive["total_meal_cost_twd"] == 1200


def test_estimate_budget_missing_route_defaults_to_zero_distance():
    itinerary = [{"day": 1, "stops": [{"type": "餐廳"}]}]  # 沒有 route（OSRM 查詢失敗的情況）
    result = estimate_budget(itinerary, "機車", 32.0, MEAL_PRICE)
    assert result["per_day"][0]["distance_km"] == 0.0
    assert result["per_day"][0]["fuel_cost_twd"] == 0
