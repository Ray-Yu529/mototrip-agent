from backend.routers.itinerary import _slim_itinerary_for_llm, _harvest_known_coords


def test_slim_itinerary_strips_route_gas_and_extra_fields():
    itinerary_data = {
        "theme": "hardcore",
        "transport": "重機",
        "total_days": 1,
        "survival_tips": ["帶雨衣"],
        "weather_by_city": {"仁愛鄉": {}},   # 不該保留給 LLM
        "poi_pool": {"restaurants": []},      # 不該保留給 LLM
        "itinerary": [
            {
                "day": 1,
                "date": "2026-07-10",
                "city": "仁愛鄉",
                "route": {"distance_km": 42.0, "geometry": [[121.0, 24.0]] * 500},
                "gas_stations": [{"name": "中油"}],
                "gas_warnings": ["油量不足"],
                "stops": [
                    {
                        "time": "09:00", "place": "清境農場", "city": "仁愛鄉",
                        "type": "景點", "note": "風景優美",
                        "transfer": "行程起點", "parking": "免費停車場",
                        "options": [{"place": "清境農場", "note": "推薦", "rating": 4.5}],
                        "lat": 24.05, "lon": 121.15,  # 座標不該送回給 LLM
                    },
                ],
            },
        ],
    }

    slim = _slim_itinerary_for_llm(itinerary_data)

    assert slim["theme"] == "hardcore"
    assert "weather_by_city" not in slim
    assert "poi_pool" not in slim

    day = slim["itinerary"][0]
    assert "route" not in day
    assert "gas_stations" not in day
    assert "gas_warnings" not in day
    assert set(day.keys()) == {"day", "date", "city", "stops"}

    stop = day["stops"][0]
    assert "lat" not in stop and "lon" not in stop
    assert stop["place"] == "清境農場"
    assert stop["options"] == [{"place": "清境農場", "note": "推薦", "rating": 4.5}]


def test_harvest_known_coords_collects_stops_options_and_poi_pool():
    itinerary_data = {
        "itinerary": [
            {
                "stops": [
                    {
                        "place": "清境農場", "lat": 24.05, "lon": 121.15,
                        "options": [
                            {"place": "清境農場", "lat": 24.05, "lon": 121.15},
                            {"place": "小瑞士花園", "lat": 24.06, "lon": 121.16},
                        ],
                    },
                    {"place": "無座標景點"},  # 沒有 lat/lon，不該被收錄
                ],
            },
        ],
        "poi_pool": {
            "restaurants": [{"name": "廬山溫泉餐廳", "lat": 23.9, "lon": 121.3}],
            "attractions": [{"name": "紅香瀑布", "lat": 24.02, "lon": 121.2}],
        },
    }

    coords = _harvest_known_coords(itinerary_data)

    assert coords["清境農場"] == (24.05, 121.15)
    assert coords["小瑞士花園"] == (24.06, 121.16)
    assert coords["廬山溫泉餐廳"] == (23.9, 121.3)
    assert coords["紅香瀑布"] == (24.02, 121.2)
    assert "無座標景點" not in coords
