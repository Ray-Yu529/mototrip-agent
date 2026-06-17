"""
Weather Agent — pure logic, no LLM call.

支援兩個 CWA 端點：
  - F-C0032-001：縣市層級（輸入「南投縣」）
  - F-D0047-XXX：鄉鎮層級（輸入「仁愛鄉」）精度更高

鄉鎮對應的 dataset_id 請參考 TOWNSHIP_DATASET_MAP。
"""
import httpx
from loguru import logger
from ..core.config import settings

CWA_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"

# 縣市 → dataset_id 對照表（+2 ID = 15 要素 12 小時版，掃描自 CWA 確認）
# 縣市名稱查詢時回傳縣治/第一鄉鎮作為代表
TOWNSHIP_DATASET_MAP: dict[str, str] = {
    "宜蘭縣": "F-D0047-003",
    "新竹縣": "F-D0047-011",
    "苗栗縣": "F-D0047-015",
    "南投縣": "F-D0047-023",
    "嘉義縣": "F-D0047-031",
    "屏東縣": "F-D0047-035",
    "臺東縣": "F-D0047-039",  # 掃描確認
    "花蓮縣": "F-D0047-043",
    "臺中市": "F-D0047-075",  # 掃描確認
}

# 台/臺 異體字 + 簡稱互通
COUNTY_ALIASES: dict[str, str] = {
    "台東縣": "臺東縣", "台中市": "臺中市",
}

# 鄉鎮 → 所屬縣市（用來查正確的 dataset）
TOWNSHIP_TO_COUNTY: dict[str, str] = {
    "仁愛鄉": "南投縣", "信義鄉": "南投縣", "魚池鄉": "南投縣",
    "埔里鎮": "南投縣", "鹿谷鄉": "南投縣", "國姓鄉": "南投縣",
    "和平區": "台中市",
    "秀林鄉": "花蓮縣", "卓溪鄉": "花蓮縣", "玉里鎮": "花蓮縣",
    "大同鄉": "宜蘭縣", "南澳鄉": "宜蘭縣",
    "尖石鄉": "新竹縣", "五峰鄉": "新竹縣",
    "泰安鄉": "苗栗縣",
    "阿里山鄉": "嘉義縣", "阿里山": "嘉義縣",
    "三地門鄉": "屏東縣", "霧台鄉": "屏東縣",
    "清境": "南投縣", "武嶺": "南投縣", "合歡山": "南投縣",
    "太平山": "宜蘭縣", "明池": "宜蘭縣",
}

LAPSE_RATE = 0.6  # °C per 100 m gain


def altitude_temp_adjust(base_temp_c: float, altitude_m: float) -> float:
    return base_temp_c - (altitude_m / 100) * LAPSE_RATE


def _normalize_county(name: str) -> str:
    """把城市簡稱/異體字補成對照表的正式縣市名，例『宜蘭』→『宜蘭縣』、『台東』→『臺東縣』。"""
    if name in TOWNSHIP_DATASET_MAP:
        return name
    for suffix in ("", "縣", "市"):
        cand = name + suffix
        cand = COUNTY_ALIASES.get(cand, cand)   # 台→臺
        if cand in TOWNSHIP_DATASET_MAP:
            return cand
    return name


def _resolve_endpoint(location: str) -> tuple[str, str]:
    """
    判斷要呼叫哪個端點。
    回傳 (dataset_url, location_name_for_filter)
    """
    # 城市簡稱正規化（宜蘭 → 宜蘭縣）
    location = _normalize_county(location)

    # 直接是縣市名稱 → 用該縣市的鄉鎮端點，回傳第一個鄉鎮作代表
    if location in TOWNSHIP_DATASET_MAP:
        return f"{CWA_BASE}/{TOWNSHIP_DATASET_MAP[location]}", location

    # 已知鄉鎮或景區簡稱 → 找對應縣市的鄉鎮端點
    county = TOWNSHIP_TO_COUNTY.get(location)
    if county and county in TOWNSHIP_DATASET_MAP:
        # 以景區名查詢，找不到時 _filter_location 會用第一筆 fallback
        return f"{CWA_BASE}/{TOWNSHIP_DATASET_MAP[county]}", location

    # 最後 fallback：南投縣端點（跑山最常用）
    logger.warning(f"'{location}' 不在對照表，fallback 用南投縣端點")
    return f"{CWA_BASE}/{TOWNSHIP_DATASET_MAP['南投縣']}", "南投市"


async def fetch_forecast(location: str) -> dict:
    """呼叫 CWA API，回傳原始 JSON。"""
    if not settings.cwa_api_key:
        logger.warning("CWA API key 未設定，使用 mock 資料")
        return _mock_forecast(location)

    url, api_location = _resolve_endpoint(location)
    params = {
        "Authorization": settings.cwa_api_key,
        "locationName": api_location,
    }
    # verify=False: CWA 使用 TWCA 憑證，Python certifi 不包含此 CA
    async with httpx.AsyncClient(timeout=10, verify=False) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    # CWA 不保證 locationName 參數一定有效過濾，改為 client-side 篩選
    _filter_location(data, api_location)
    return data


def _filter_location(data: dict, target_name: str) -> None:
    """
    從 Locations[0].Location 陣列中保留符合 target_name 的那筆，in-place 修改。
    若 target_name 是縣市名稱（在 dataset 中找不到），保留第一筆作為縣治代表。
    """
    try:
        locs = data["records"]["Locations"][0]["Location"]
        matched = [l for l in locs if l["LocationName"] == target_name]
        if matched:
            data["records"]["Locations"][0]["Location"] = matched
        # 縣市名稱查詢：不警告，直接用第一筆（縣治）
    except (KeyError, IndexError):
        pass


def parse_riding_advice(forecast_json: dict, altitude_m: int = 0) -> dict:
    """
    將 CWA JSON 轉成騎乘建議 dict。
    兩個端點（F-C0032-001 縣市 / F-D0047-XXX 鄉鎮）現在回傳相同的 PascalCase 結構，
    統一用此函式解析。
    """
    try:
        location = forecast_json["records"]["Locations"][0]["Location"][0]
        elements = {e["ElementName"]: e for e in location["WeatherElement"]}

        # 降雨機率
        pop_slots = elements["12小時降雨機率"]["Time"]
        best_idx = min(
            range(len(pop_slots)),
            key=lambda i: _safe_int(
                pop_slots[i]["ElementValue"][0].get("ProbabilityOfPrecipitation", 100)
            ),
        )
        best_window = (
            f"{pop_slots[best_idx]['StartTime'][11:16]}"
            f"–{pop_slots[best_idx]['EndTime'][11:16]}"
        )
        rain_risk = _safe_int(
            pop_slots[best_idx]["ElementValue"][0].get("ProbabilityOfPrecipitation", 0)
        )

        # 天氣現象（最佳時段）
        wx_slots = elements.get("天氣現象", {}).get("Time", [])
        wx_desc = wx_slots[best_idx]["ElementValue"][0].get("Weather", "") if wx_slots else ""

        # 氣溫
        raw_min = _safe_float(
            elements["最低溫度"]["Time"][0]["ElementValue"][0].get("MinTemperature", 20)
        )
        raw_max = _safe_float(
            elements["最高溫度"]["Time"][0]["ElementValue"][0].get("MaxTemperature", 30)
        )
        adj_min = round(altitude_temp_adjust(raw_min, altitude_m), 1)
        adj_max = round(altitude_temp_adjust(raw_max, altitude_m), 1)

        return {
            "location": location["LocationName"],
            "altitude_m": altitude_m,
            "best_riding_window": best_window,
            "weather_desc": wx_desc,
            "rain_risk_pct": rain_risk,
            "temp_range": f"{adj_min}–{adj_max} °C（海拔修正後）",
            "clothing_tip": _clothing_tip(adj_min),
        }
    except Exception as exc:
        logger.error(f"parse_riding_advice 失敗: {exc}")
        return {"error": str(exc)}


def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clothing_tip(min_temp: float) -> str:
    if min_temp < 10:
        return "氣溫極低，建議全套防寒裝備（底層排汗衣 + 保暖中層 + 防風外層 + 防寒手套）"
    if min_temp < 15:
        return "氣溫偏涼，建議保暖中層搭防風騎士外套，備暖暖包"
    if min_temp < 22:
        return "氣溫舒適，騎士夾克即可，備薄防水層應對午後雷陣雨"
    return "氣溫偏高，透氣網眼外套或短袖騎士服，注意日曬防曬"


def _mock_forecast(location: str) -> dict:
    return {
        "_source_type": "county",
        "records": {
            "location": [{
                "locationName": location,
                "weatherElement": [
                    {"elementName": "Wx", "time": [
                        {"startTime": "2026-06-17 06:00:00", "endTime": "2026-06-17 12:00:00", "parameter": {"parameterName": "多雲時晴"}},
                        {"startTime": "2026-06-17 12:00:00", "endTime": "2026-06-17 18:00:00", "parameter": {"parameterName": "午後雷陣雨"}},
                        {"startTime": "2026-06-17 18:00:00", "endTime": "2026-06-18 06:00:00", "parameter": {"parameterName": "多雲"}},
                    ]},
                    {"elementName": "PoP", "time": [
                        {"startTime": "2026-06-17 06:00:00", "endTime": "2026-06-17 12:00:00", "parameter": {"parameterValue": "20"}},
                        {"startTime": "2026-06-17 12:00:00", "endTime": "2026-06-17 18:00:00", "parameter": {"parameterValue": "80"}},
                        {"startTime": "2026-06-17 18:00:00", "endTime": "2026-06-18 06:00:00", "parameter": {"parameterValue": "30"}},
                    ]},
                    {"elementName": "MinT", "time": [{"startTime": "2026-06-17 06:00:00", "endTime": "2026-06-18 06:00:00", "parameter": {"parameterValue": "22"}}]},
                    {"elementName": "MaxT", "time": [{"startTime": "2026-06-17 06:00:00", "endTime": "2026-06-18 06:00:00", "parameter": {"parameterValue": "31"}}]},
                ],
            }]
        },
    }
