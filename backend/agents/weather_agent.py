"""
Weather Agent — pure logic, no LLM call.

使用 CWA F-D0047 系列「各縣市鄉鎮未來1週逐12小時天氣預報」。
涵蓋全台 22 縣市、349 個全國唯一命名的鄉鎮/區（跨縣市同名者如「東區」不收錄，
請改用縣市全名查詢），對照表見 backend/data/cwa_locations.json
（由實際掃描 CWA API 產生，見該檔案的 _comment）。

每次查詢回傳未來 7 天、每天 2 個 12 小時時段的預報，
parse_riding_advice() 可依指定日期挑出當天對應時段，讓多日行程每天都有正確天氣。
"""
import json
import ssl
import httpx
from datetime import date, datetime
from pathlib import Path
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ..core.config import settings

_network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)

CWA_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
LOCATIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "cwa_locations.json"

_locations = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))
DATASET_MAP: dict[str, str] = _locations["dataset_map"]
TOWNSHIP_TO_COUNTY: dict[str, str] = _locations["township_map"]

# 台/臺 異體字 + 簡稱互通
COUNTY_ALIASES: dict[str, str] = {
    "台東縣": "臺東縣", "台中市": "臺中市", "台北市": "臺北市", "台南市": "臺南市",
}

LAPSE_RATE = 0.6  # °C per 100 m gain

# TWCA 政府憑證缺少 Subject Key Identifier 擴充欄位，OpenSSL 3.2+ 預設嚴格模式會拒絕。
# 僅關閉這一項嚴格檢查（憑證鏈、到期日、主機名稱仍正常驗證），
# 不使用 verify=False（會關閉所有驗證，有中間人風險）。
_TWCA_SSL_CTX = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    _TWCA_SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

# 共用單一 AsyncClient（而非每次查詢都新建），減少 TLS handshake 開銷；
# 多城市行程會平行呼叫多次 fetch_forecast，共用連線池效果更明顯。
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10, verify=_TWCA_SSL_CTX)
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def altitude_temp_adjust(base_temp_c: float, altitude_m: float) -> float:
    return base_temp_c - (altitude_m / 100) * LAPSE_RATE


def _normalize_county(name: str) -> str:
    """把城市簡稱/異體字補成對照表的正式縣市名，例『宜蘭』→『宜蘭縣』、『台東』→『臺東縣』。"""
    if name in DATASET_MAP:
        return name
    for suffix in ("", "縣", "市"):
        cand = name + suffix
        cand = COUNTY_ALIASES.get(cand, cand)   # 台→臺
        if cand in DATASET_MAP:
            return cand
    return name


def _resolve_endpoint(location: str) -> tuple[str, str]:
    """
    判斷要呼叫哪個端點。
    回傳 (dataset_url, location_name_for_filter)
    """
    # 城市簡稱正規化（宜蘭 → 宜蘭縣）
    normalized = _normalize_county(location)

    # 直接是縣市名稱 → 用該縣市的鄉鎮端點，回傳原輸入供 client-side 篩選第一鄉鎮代表
    if normalized in DATASET_MAP:
        return f"{CWA_BASE}/{DATASET_MAP[normalized]}", location

    # 已知鄉鎮/區名稱 → 找對應縣市的端點
    county = TOWNSHIP_TO_COUNTY.get(location)
    if county:
        return f"{CWA_BASE}/{DATASET_MAP[county]}", location

    # 最後 fallback：南投縣端點（跑山最常用）
    logger.warning(f"'{location}' 不在對照表，fallback 用南投縣端點")
    return f"{CWA_BASE}/{DATASET_MAP['南投縣']}", "南投市"


@_network_retry
async def _get_cwa_json(url: str, params: dict) -> dict:
    resp = await _get_client().get(url, params=params)
    resp.raise_for_status()
    return resp.json()


async def fetch_forecast(location: str) -> dict:
    """呼叫 CWA API，回傳原始 JSON（含未來 7 天、每天 2 個 12 小時時段）。"""
    if not settings.cwa_api_key:
        logger.warning("CWA API key 未設定，使用 mock 資料")
        return _mock_forecast(location)

    url, api_location = _resolve_endpoint(location)
    params = {
        "Authorization": settings.cwa_api_key,
        "locationName": api_location,
    }
    try:
        data = await _get_cwa_json(url, params)
    except Exception as exc:
        logger.error(f"CWA API 呼叫失敗（已重試 3 次）: {exc}，改用 mock 資料")
        return _mock_forecast(location)

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


def parse_riding_advice(
    forecast_json: dict, altitude_m: int = 0, target_date: str | None = None
) -> dict:
    """
    將 CWA JSON 轉成騎乘建議 dict。

    target_date: "YYYY-MM-DD"，若指定則只挑該日期涵蓋的時段（通常 2 段：日間/夜間）；
                 未指定或超出預報範圍（>7 天）時，fallback 用最近的可用時段。
    """
    try:
        location = forecast_json["records"]["Locations"][0]["Location"][0]
        elements = {e["ElementName"]: e for e in location["WeatherElement"]}

        pop_slots = elements["12小時降雨機率"]["Time"]
        candidate_idxs = _slots_for_date(pop_slots, target_date)

        # 挑候選時段中降雨風險最低者作為最佳騎乘時段
        best_idx = min(
            candidate_idxs,
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
        # 當天所有時段中的最高降雨機率（給室內外決策用，避免只看到最佳時段而低估風險）
        max_rain_risk = max(
            _safe_int(pop_slots[i]["ElementValue"][0].get("ProbabilityOfPrecipitation", 0))
            for i in candidate_idxs
        )

        # 天氣現象（最佳時段）
        wx_slots = elements.get("天氣現象", {}).get("Time", [])
        wx_desc = wx_slots[best_idx]["ElementValue"][0].get("Weather", "") if wx_slots else ""

        # 氣溫：找當天（或候選時段）涵蓋範圍內的最低/最高溫
        min_slots = elements["最低溫度"]["Time"]
        max_slots = elements["最高溫度"]["Time"]
        min_idxs = _slots_for_date(min_slots, target_date) or [0]
        max_idxs = _slots_for_date(max_slots, target_date) or [0]
        raw_min = min(
            _safe_float(min_slots[i]["ElementValue"][0].get("MinTemperature", 20))
            for i in min_idxs
        )
        raw_max = max(
            _safe_float(max_slots[i]["ElementValue"][0].get("MaxTemperature", 30))
            for i in max_idxs
        )
        adj_min = round(altitude_temp_adjust(raw_min, altitude_m), 1)
        adj_max = round(altitude_temp_adjust(raw_max, altitude_m), 1)

        return {
            "location": location["LocationName"],
            "date": target_date or pop_slots[best_idx]["StartTime"][:10],
            "altitude_m": altitude_m,
            "best_riding_window": best_window,
            "weather_desc": wx_desc,
            "rain_risk_pct": rain_risk,
            "max_rain_risk_pct": max_rain_risk,
            "temp_range": f"{adj_min}–{adj_max} °C（海拔修正後）",
            "clothing_tip": _clothing_tip(adj_min),
        }
    except Exception as exc:
        logger.error(f"parse_riding_advice 失敗: {exc}")
        return {"error": str(exc)}


def _slots_for_date(slots: list[dict], target_date: str | None) -> list[int]:
    """回傳涵蓋 target_date 的時段 index 清單；沒指定或超出範圍時 fallback 到最早可用時段。"""
    if not target_date:
        return list(range(len(slots)))
    matched = [i for i, s in enumerate(slots) if s["StartTime"][:10] == target_date
               or s["EndTime"][:10] == target_date]
    if matched:
        return matched
    # 超出 CWA 7 天預報範圍：用最後一天的時段代替，並記錄警告
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        last_date = datetime.strptime(slots[-1]["StartTime"][:10], "%Y-%m-%d").date()
        if target > last_date:
            logger.debug(f"{target_date} 超出 CWA 7 天預報範圍，改用最後可用時段 {last_date}")
            return [len(slots) - 1]
    except ValueError:
        pass
    return list(range(len(slots)))


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
    today = date.today().isoformat()
    return {
        "records": {
            "Locations": [{
                "Location": [{
                    "LocationName": location,
                    "WeatherElement": [
                        {"ElementName": "天氣現象", "Time": [
                            {"StartTime": f"{today}T06:00:00+08:00", "EndTime": f"{today}T18:00:00+08:00",
                             "ElementValue": [{"Weather": "多雲時晴"}]},
                            {"StartTime": f"{today}T18:00:00+08:00", "EndTime": f"{today}T06:00:00+08:00",
                             "ElementValue": [{"Weather": "多雲"}]},
                        ]},
                        {"ElementName": "12小時降雨機率", "Time": [
                            {"StartTime": f"{today}T06:00:00+08:00", "EndTime": f"{today}T18:00:00+08:00",
                             "ElementValue": [{"ProbabilityOfPrecipitation": "20"}]},
                            {"StartTime": f"{today}T18:00:00+08:00", "EndTime": f"{today}T06:00:00+08:00",
                             "ElementValue": [{"ProbabilityOfPrecipitation": "30"}]},
                        ]},
                        {"ElementName": "最低溫度", "Time": [
                            {"StartTime": f"{today}T06:00:00+08:00", "EndTime": f"{today}T18:00:00+08:00",
                             "ElementValue": [{"MinTemperature": "22"}]},
                        ]},
                        {"ElementName": "最高溫度", "Time": [
                            {"StartTime": f"{today}T06:00:00+08:00", "EndTime": f"{today}T18:00:00+08:00",
                             "ElementValue": [{"MaxTemperature": "31"}]},
                        ]},
                    ],
                }],
            }],
        },
    }
