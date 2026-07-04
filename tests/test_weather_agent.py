from backend.agents.weather_agent import (
    altitude_temp_adjust, _normalize_county, parse_riding_advice, DATASET_MAP, TOWNSHIP_TO_COUNTY,
)


def test_altitude_temp_adjust_lapse_rate():
    # 每 100m 降 0.6°C
    assert altitude_temp_adjust(30.0, 1000) == 24.0
    assert altitude_temp_adjust(20.0, 0) == 20.0


def test_normalize_county_aliases_and_suffix():
    assert _normalize_county("台東") == "臺東縣"
    assert _normalize_county("宜蘭") == "宜蘭縣"
    assert _normalize_county("臺中市") == "臺中市"


def test_dataset_map_covers_all_22_counties():
    assert len(DATASET_MAP) == 22
    assert DATASET_MAP["南投縣"] == "F-D0047-023"
    assert DATASET_MAP["臺北市"] == "F-D0047-063"


def test_township_lookup_resolves_to_correct_county():
    assert TOWNSHIP_TO_COUNTY["仁愛鄉"] == "南投縣"
    assert TOWNSHIP_TO_COUNTY["秀林鄉"] == "花蓮縣"


def _slot(start: str, end: str, pop: str, min_t: str = "20", max_t: str = "30"):
    return {
        "StartTime": start, "EndTime": end,
        "ElementValue": [{"ProbabilityOfPrecipitation": pop,
                           "MinTemperature": min_t, "MaxTemperature": max_t}],
    }


def _forecast(day1_pop=("20", "80"), day2_pop=("10", "30")):
    return {
        "records": {"Locations": [{"Location": [{
            "LocationName": "仁愛鄉",
            "WeatherElement": [
                {"ElementName": "天氣現象", "Time": [
                    {"StartTime": "2026-07-10T06:00:00+08:00", "EndTime": "2026-07-10T18:00:00+08:00",
                     "ElementValue": [{"Weather": "多雲"}]},
                    {"StartTime": "2026-07-10T18:00:00+08:00", "EndTime": "2026-07-11T06:00:00+08:00",
                     "ElementValue": [{"Weather": "陰"}]},
                    {"StartTime": "2026-07-11T06:00:00+08:00", "EndTime": "2026-07-11T18:00:00+08:00",
                     "ElementValue": [{"Weather": "晴"}]},
                ]},
                {"ElementName": "12小時降雨機率", "Time": [
                    _slot("2026-07-10T06:00:00+08:00", "2026-07-10T18:00:00+08:00", day1_pop[0]),
                    _slot("2026-07-10T18:00:00+08:00", "2026-07-11T06:00:00+08:00", day1_pop[1]),
                    _slot("2026-07-11T06:00:00+08:00", "2026-07-11T18:00:00+08:00", day2_pop[0]),
                ]},
                {"ElementName": "最低溫度", "Time": [
                    _slot("2026-07-10T06:00:00+08:00", "2026-07-10T18:00:00+08:00", "0", min_t="15"),
                    _slot("2026-07-11T06:00:00+08:00", "2026-07-11T18:00:00+08:00", "0", min_t="18"),
                ]},
                {"ElementName": "最高溫度", "Time": [
                    _slot("2026-07-10T06:00:00+08:00", "2026-07-10T18:00:00+08:00", "0", max_t="25"),
                    _slot("2026-07-11T06:00:00+08:00", "2026-07-11T18:00:00+08:00", "0", max_t="28"),
                ]},
            ],
        }]}]},
    }


def test_parse_riding_advice_picks_correct_date_slot():
    forecast = _forecast()
    day1 = parse_riding_advice(forecast, altitude_m=0, target_date="2026-07-10")
    day2 = parse_riding_advice(forecast, altitude_m=0, target_date="2026-07-11")

    assert day1["date"] == "2026-07-10"
    # day1 有兩個時段 20% / 80%，最佳時段應挑 20% 那段
    assert day1["rain_risk_pct"] == 20
    assert day1["max_rain_risk_pct"] == 80
    assert day1["temp_range"].startswith("15.0")

    assert day2["date"] == "2026-07-11"
    assert day2["rain_risk_pct"] == 10
    assert day2["temp_range"].startswith("18.0")


def test_parse_riding_advice_altitude_correction_applied_per_date():
    forecast = _forecast()
    sea_level = parse_riding_advice(forecast, altitude_m=0, target_date="2026-07-10")
    high_alt = parse_riding_advice(forecast, altitude_m=1000, target_date="2026-07-10")
    # 海拔 1000m，氣溫應下修 6 度
    assert "9.0" in high_alt["temp_range"]
    assert "15.0" in sea_level["temp_range"]
