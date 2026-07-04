"""
POI Agent — 透過 Google Places API 查詢餐廳與景點。
依使用者偏好（餐廳類型、預算、景點類型、評分門檻、室內外）篩選，
並結合天氣做室內外加權。本 Agent 不呼叫 LLM。

googlemaps client 是同步 API，用 asyncio.to_thread 包起來避免卡住 event loop，
同一次查詢的多個關鍵字（不同餐廳類型/景點類型）用 asyncio.gather 平行送出。
"""
import asyncio
from loguru import logger
from ..core.google_reviews import get_places_client as _client

# 餐廳類型 → Google Places keyword
CUISINE_KEYWORDS = {
    "小吃麵食": "小吃 麵",
    "火鍋": "火鍋",
    "咖啡廳": "咖啡",
    "特色料理": "特色 餐廳",
    "素食": "素食",
    "夜市": "夜市",
}

# 景點類型 → (Google Places type, keyword)
ATTRACTION_TYPES = {
    "自然風景": ("tourist_attraction", "風景 步道 瀑布"),
    "文化古蹟": ("tourist_attraction", "古蹟 廟 老街"),
    "打卡熱點": ("tourist_attraction", "景觀 打卡"),
    "溫泉": ("spa", "溫泉"),
}

# 由 Place types 推斷室內 / 室外
INDOOR_TYPES = {
    "museum", "aquarium", "shopping_mall", "art_gallery",
    "spa", "movie_theater", "library", "cafe", "restaurant",
}
OUTDOOR_TYPES = {
    "park", "natural_feature", "campground", "tourist_attraction",
    "hiking_area", "zoo", "amusement_park",
}


def _infer_venue(types: list[str]) -> str:
    """由 Place types 推斷 indoor / outdoor / unknown。"""
    tset = set(types)
    if tset & INDOOR_TYPES and not tset & OUTDOOR_TYPES:
        return "indoor"
    if tset & OUTDOOR_TYPES:
        return "outdoor"
    return "unknown"


def _search_sync(query: str, place_type: str, min_rating: float,
                  min_price: int | None, max_price: int | None) -> list[dict]:
    """文字搜尋 Google Places（同步呼叫），回傳結構化清單。"""
    gmaps = _client()
    if gmaps is None:
        return []
    try:
        kwargs = {"query": query, "language": "zh-TW", "type": place_type}
        if min_price is not None:
            kwargs["min_price"] = min_price
        if max_price is not None:
            kwargs["max_price"] = max_price
        resp = gmaps.places(**kwargs)
    except Exception as exc:
        logger.error(f"Google Places 查詢失敗 ({query}): {exc}")
        return []

    out = []
    for p in resp.get("results", []):
        rating = p.get("rating", 0) or 0
        if rating < min_rating:
            continue
        loc = p.get("geometry", {}).get("location", {})
        out.append({
            "name": p.get("name", ""),
            "rating": rating,
            "price_level": p.get("price_level"),
            "address": p.get("formatted_address", ""),
            "types": p.get("types", []),
            "venue": _infer_venue(p.get("types", [])),
            "lat": loc.get("lat"),
            "lon": loc.get("lng"),
        })
    return out


async def _search(query: str, place_type: str, min_rating: float,
                   min_price: int | None, max_price: int | None) -> list[dict]:
    return await asyncio.to_thread(
        _search_sync, query, place_type, min_rating, min_price, max_price
    )


async def fetch_pois(
    destination: str,
    cuisines: list[str],
    attraction_types: list[str],
    min_rating: float = 4.0,
    min_price: int | None = None,
    max_price: int | None = None,
    venue_pref: str = "auto",     # indoor | outdoor | auto
    rain_risk_pct: int = 0,
    limit_each: int = 4,
) -> dict:
    """
    回傳 {"restaurants": [...], "attractions": [...]}。
    室內外加權：venue_pref=auto 且降雨機率高時，優先室內。
    每個關鍵字的查詢平行送出，避免序列等待拖慢多城市/多類型行程。
    """
    # 決定實際的室內外偏好
    effective_venue = venue_pref
    if venue_pref == "auto":
        effective_venue = "indoor" if rain_risk_pct >= 60 else "any"

    restaurant_tasks = [
        _search(f"{destination} {CUISINE_KEYWORDS.get(c, c)}", "restaurant",
                min_rating, min_price, max_price)
        for c in (cuisines or ["特色料理"])
    ]
    attraction_tasks = [
        _search(f"{destination} {ATTRACTION_TYPES.get(a, ('tourist_attraction', a))[1]}",
                ATTRACTION_TYPES.get(a, ("tourist_attraction", a))[0],
                min_rating, None, None)
        for a in (attraction_types or ["自然風景"])
    ]

    restaurant_results, attraction_results = await asyncio.gather(
        asyncio.gather(*restaurant_tasks),
        asyncio.gather(*attraction_tasks),
    )
    restaurants = [item for sub in restaurant_results for item in sub]
    attractions = [item for sub in attraction_results for item in sub]

    # 室內外加權排序：偏好的 venue 排前面
    def venue_sort_key(item: dict):
        if effective_venue in ("indoor", "outdoor"):
            match = 0 if item["venue"] == effective_venue else 1
        else:
            match = 0
        return (match, -item["rating"])

    restaurants = _dedup(restaurants)
    attractions = _dedup(attractions)
    restaurants.sort(key=venue_sort_key)
    attractions.sort(key=venue_sort_key)

    return {
        "restaurants": restaurants[:limit_each],
        "attractions": attractions[:limit_each],
        "venue_applied": effective_venue,
    }


def _dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        out.append(it)
    return out
