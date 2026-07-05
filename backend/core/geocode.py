"""
地名 → 經緯度轉換（geocoding）。
優先使用 Google Places Geocoding API（若有設定 GOOGLE_PLACES_API_KEY）：
可平行查詢、配額寬鬆，大幅縮短多 stop 行程的定位時間；
未設定 API key 或查無結果時，fallback 用 OpenStreetMap Nominatim
（免費、免 key，但依使用條款限制每秒最多 1 次查詢，用全域 lock 節流）。
結果快取到 data/geocode_cache.json，避免重複查詢。
"""
import json
import asyncio
from pathlib import Path
import httpx
from loguru import logger
from .config import BASE_DIR, settings
from .google_reviews import geocode_address, get_places_client

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CACHE_FILE = BASE_DIR / "data" / "geocode_cache.json"
# Nominatim 使用條款要求自訂 User-Agent
HEADERS = {"User-Agent": "MotoTripAgent/1.0 (academic project)"}

_cache: dict[str, list[float] | None] | None = None
_cache_dirty = False

# Nominatim 每秒最多 1 次查詢；用 lock + 上次呼叫時間節流，
# 讓多個 coroutine 平行呼叫 geocode_one 時 Nominatim 路徑仍能安全排隊，
# Google 路徑則不受此限制、可真正平行送出。
_nominatim_lock = asyncio.Lock()
_last_nominatim_call = 0.0


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if CACHE_FILE.exists():
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        else:
            _cache = {}
    return _cache


def _save_cache(force: bool = False) -> None:
    """寫回快取檔。預設只在有新資料（dirty）時才寫，避免高頻率重複寫檔。"""
    global _cache_dirty
    if _cache is not None and (_cache_dirty or force):
        CACHE_FILE.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _cache_dirty = False


def _geocode_google_sync(query: str) -> list[float] | None:
    gmaps = get_places_client()
    if gmaps is None:
        return None
    coord = geocode_address(gmaps, query)
    return [coord[0], coord[1]] if coord else None


async def _geocode_nominatim(client: httpx.AsyncClient, query: str) -> list[float] | None:
    global _last_nominatim_call
    async with _nominatim_lock:
        now = asyncio.get_event_loop().time()
        wait = 1.0 - (now - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            resp = await client.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "tw"},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json()
        except Exception as exc:
            logger.warning(f"Nominatim geocode '{query}' 失敗: {exc}")
            results = []
        finally:
            _last_nominatim_call = asyncio.get_event_loop().time()

    if results:
        return [float(results[0]["lat"]), float(results[0]["lon"])]
    return None


async def geocode_one(
    client: httpx.AsyncClient, place: str, region_hint: str = ""
) -> list[float] | None:
    """回傳 [lat, lon]，找不到回傳 None。優先用 Google（可平行），查無資料再 fallback Nominatim。"""
    global _cache_dirty
    cache = _load_cache()
    key = f"{place}@{region_hint}"
    if key in cache:
        return cache[key]

    query = f"{place} {region_hint} 台灣".strip()

    coord = None
    if settings.google_places_api_key:
        coord = await asyncio.to_thread(_geocode_google_sync, query)
    if coord is None:
        coord = await _geocode_nominatim(client, query)

    cache[key] = coord
    _cache_dirty = True
    return coord


def _lookup_known_coord(
    place: str, known_coords: dict[str, tuple[float, float]]
) -> tuple[float, float] | None:
    """
    先精確比對，再模糊比對（互為子字串）。
    LLM 常會省略 POI 全名的部分字詞（例如把「紅河谷步道瀑布」寫成「紅河谷步道」），
    或 Google Places 本身的商家名稱含大量 SEO 關鍵字堆疊，兩種情況都用子字串比對解決，
    命中多筆時取字串最短者（通常最貼近核心名稱）。
    """
    if place in known_coords:
        return known_coords[place]
    hits = [k for k in known_coords if place in k or k in place]
    if hits:
        return known_coords[min(hits, key=len)]
    return None


def _stop_places(stop: dict) -> list[str]:
    """收集本 stop 需定位的地名：主地點 + 各候選（去重）。"""
    places = []
    main = stop.get("place", "")
    if main:
        places.append(main)
    for opt in stop.get("options", []) or []:
        p = opt.get("place", "")
        if p and p not in places:
            places.append(p)
    return places


async def enrich_itinerary_coords(
    itinerary: list[dict],
    region_hint: str = "",
    known_coords: dict[str, tuple[float, float]] | None = None,
) -> None:
    """
    為行程的每個 stop 補上 lat / lon（in-place）。
    known_coords: 名稱 -> (lat, lon) 的既有座標（例如 Google Places 已查到的 POI），
                  命中的地名直接沿用，不必再查詢；
                  只有清單外、LLM 自行生成的地名才會實際呼叫 geocode_one。

    清單外地名彼此獨立、去重後一次平行送出（asyncio.gather）：
    有 Google API key 時完全平行；退回 Nominatim 時則由 geocode_one 內的
    lock 自動排隊節流，呼叫端不需要再手動 sleep。
    """
    known_coords = known_coords or {}

    # 去重收集所有需要實際查詢的地名（跳過已知座標者）
    to_query: dict[str, asyncio.Task] = {}
    async with httpx.AsyncClient() as client:
        for day in itinerary:
            for stop in day.get("stops", []):
                for place in _stop_places(stop):
                    if place in to_query or _lookup_known_coord(place, known_coords) is not None:
                        continue
                    to_query[place] = asyncio.create_task(
                        geocode_one(client, place, region_hint)
                    )

        if to_query:
            await asyncio.gather(*to_query.values())
        _save_cache()

    resolved = {place: task.result() for place, task in to_query.items()}

    for day in itinerary:
        for stop in day.get("stops", []):
            for idx, place in enumerate(_stop_places(stop)):
                matched_known = _lookup_known_coord(place, known_coords)
                coord = matched_known if matched_known is not None else resolved.get(place)
                if not coord:
                    continue
                if idx == 0:
                    stop["lat"], stop["lon"] = coord[0], coord[1]
                # 同步寫回對應候選，供前端切換時更新地圖
                for opt in stop.get("options", []) or []:
                    if opt.get("place") == place:
                        opt["lat"], opt["lon"] = coord[0], coord[1]
