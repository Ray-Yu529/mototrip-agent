"""
真實路線規劃 — 呼叫 OSRM（Open Source Routing Machine）取得站點間的實際道路距離、
騎乘時間與路徑幾何座標，取代 LLM 憑印象猜測的 transfer 時間。

預設使用 OSRM 官方公用 demo server（router.project-osrm.org），僅供開發/展示用途，
正式環境建議自架 OSRM 服務並在 .env 設定 OSRM_BASE_URL。
"""
import asyncio
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .config import settings

_network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)

# OSRM demo server 只提供 driving profile；機車/重機/汽車路網相近，皆使用 driving，
# 自行車另外走 cycling profile（避開快速道路、路網不同）。
PROFILE_BY_TRANSPORT = {
    "機車": "driving",
    "重機": "driving",
    "汽車": "driving",
    "自行車": "cycling",
    "大眾運輸": "driving",  # 僅作參考距離，實際轉乘時間由 LLM 描述
}

# 平均速度回退值（km/h），OSRM 查詢失敗時用直線距離估算需要的粗略比例
FALLBACK_SPEED_KMH = {
    "機車": 40, "重機": 45, "自行車": 15, "汽車": 50, "大眾運輸": 35,
}

# 共用單一 AsyncClient（而非每次查詢都新建），多天行程平行查詢時重用連線池。
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15)
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


@_network_retry
async def _get_osrm_json(url: str) -> dict:
    resp = await _get_client().get(url, params={"overview": "full", "geometries": "geojson"})
    resp.raise_for_status()
    return resp.json()


async def get_route(
    coords: list[tuple[float, float]], transport: str = "機車"
) -> dict | None:
    """
    coords: [(lat, lon), ...] 依序連接的站點座標（至少 2 點）。
    回傳 {"distance_km": float, "duration_min": float, "geometry": [[lon,lat], ...]}；
    OSRM 查詢失敗（服務不可用/座標無法定位路網）回傳 None，呼叫端應 fallback 處理。
    """
    if len(coords) < 2:
        return None

    profile = PROFILE_BY_TRANSPORT.get(transport, "driving")
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"{settings.osrm_base_url}/route/v1/{profile}/{coord_str}"

    try:
        data = await _get_osrm_json(url)
    except Exception as exc:
        logger.warning(f"OSRM 路線查詢失敗（已重試）: {exc}")
        return None

    if data.get("code") != "Ok" or not data.get("routes"):
        logger.warning(f"OSRM 無法規劃路線: {data.get('code')}")
        return None

    route = data["routes"][0]
    return {
        "distance_km": round(route["distance"] / 1000, 1),
        "duration_min": round(route["duration"] / 60),
        "geometry": route["geometry"]["coordinates"],  # [[lon, lat], ...]
    }


async def get_routes_for_days(
    itinerary: list[dict], transport: str
) -> None:
    """
    為每一天的行程（依序連接有座標的 stops）查詢真實路線，
    寫回 day["route"] = {distance_km, duration_min, geometry}（in-place）。
    多天之間平行查詢加速。
    """
    async def _one_day(day: dict) -> None:
        coords = [
            (s["lat"], s["lon"])
            for s in day.get("stops", [])
            if s.get("lat") is not None and s.get("lon") is not None
        ]
        route = await get_route(coords, transport)
        if route:
            day["route"] = route

    await asyncio.gather(*(_one_day(day) for day in itinerary))
