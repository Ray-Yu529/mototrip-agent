"""
地名 → 經緯度轉換（geocoding）。
使用 OpenStreetMap Nominatim，免費、免 API key。
結果快取到 data/geocode_cache.json，避免重複查詢並遵守速率限制。
"""
import json
import asyncio
from pathlib import Path
import httpx
from loguru import logger
from .config import BASE_DIR

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CACHE_FILE = BASE_DIR / "data" / "geocode_cache.json"
# Nominatim 使用條款要求自訂 User-Agent
HEADERS = {"User-Agent": "MotoTripAgent/1.0 (academic project)"}

_cache: dict[str, list[float] | None] | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if CACHE_FILE.exists():
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        else:
            _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is not None:
        CACHE_FILE.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def geocode_one(
    client: httpx.AsyncClient, place: str, region_hint: str = ""
) -> list[float] | None:
    """回傳 [lat, lon]，找不到回傳 None。"""
    cache = _load_cache()
    key = f"{place}@{region_hint}"
    if key in cache:
        return cache[key]

    query = f"{place} {region_hint} 台灣".strip()
    try:
        resp = await client.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "tw",
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            coord = [float(results[0]["lat"]), float(results[0]["lon"])]
        else:
            coord = None
    except Exception as exc:
        logger.warning(f"geocode '{place}' 失敗: {exc}")
        coord = None

    cache[key] = coord
    _save_cache()
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


async def enrich_itinerary_coords(
    itinerary: list[dict],
    region_hint: str = "",
    known_coords: dict[str, tuple[float, float]] | None = None,
) -> None:
    """
    為行程的每個 stop 補上 lat / lon（in-place）。
    known_coords: 名稱 -> (lat, lon) 的既有座標（例如 Google Places 已查到的 POI），
                  命中的地名直接沿用，不必再查 Nominatim；
                  只有清單外、LLM 自行生成的地名才會呼叫 Nominatim（並受其每秒 1 次的速率限制）。
    """
    known_coords = known_coords or {}
    async with httpx.AsyncClient() as client:
        for day in itinerary:
            for stop in day.get("stops", []):
                # 收集本 stop 需定位的地名：主地點 + 各候選（去重）
                places = []
                main = stop.get("place", "")
                if main:
                    places.append(main)
                for opt in stop.get("options", []) or []:
                    p = opt.get("place", "")
                    if p and p not in places:
                        places.append(p)

                for idx, place in enumerate(places):
                    matched_known = _lookup_known_coord(place, known_coords)
                    if matched_known is not None:
                        coord = matched_known
                    else:
                        cache = _load_cache()
                        was_cached = f"{place}@{region_hint}" in cache
                        coord = await geocode_one(client, place, region_hint)
                        if not was_cached:
                            await asyncio.sleep(1.0)  # 遵守 Nominatim 速率限制

                    if coord:
                        if idx == 0:
                            stop["lat"], stop["lon"] = coord[0], coord[1]
                        # 同步寫回對應候選，供前端切換時更新地圖
                        for opt in stop.get("options", []) or []:
                            if opt.get("place") == place:
                                opt["lat"], opt["lon"] = coord[0], coord[1]
