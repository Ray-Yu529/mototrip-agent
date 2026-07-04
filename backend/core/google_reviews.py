"""
Google Places 評論抓取共用邏輯。
被 scripts/ingest_google_reviews.py（CLI 批次匯入）與
backend/agents/rag_agent.py（找不到民宿時即時自動補資料）共用。
"""
from functools import lru_cache
import googlemaps
from loguru import logger
from .config import settings


@lru_cache(maxsize=1)
def get_places_client() -> googlemaps.Client | None:
    if not settings.google_places_api_key:
        logger.warning("GOOGLE_PLACES_API_KEY 未設定，無法查詢 Google Places")
        return None
    return googlemaps.Client(key=settings.google_places_api_key)


def find_place_id(gmaps: googlemaps.Client, name: str) -> tuple[str, str] | None:
    """回傳 (place_id, 正式名稱)；找不到回傳 None。"""
    try:
        result = gmaps.find_place(
            input=name,
            input_type="textquery",
            fields=["place_id", "name"],
            language="zh-TW",
        )
    except Exception as exc:
        logger.error(f"Google Places find_place 失敗 ({name}): {exc}")
        return None
    candidates = result.get("candidates", [])
    if not candidates:
        return None
    place = candidates[0]
    return place["place_id"], place.get("name", name)


def fetch_place_reviews(gmaps: googlemaps.Client, place_id: str) -> list[str]:
    """取得評論文字（最多 5 則，Google 官方上限）。"""
    try:
        result = gmaps.place(
            place_id=place_id,
            fields=["name", "rating", "reviews"],
            language="zh-TW",
            reviews_sort="newest",
        )
    except Exception as exc:
        logger.error(f"Google Places place() 失敗 ({place_id}): {exc}")
        return []
    reviews = result.get("result", {}).get("reviews", [])
    texts = []
    for r in reviews:
        text = r.get("text", "").strip()
        rating = r.get("rating", "?")
        if text:
            texts.append(f"[{rating}星] {text}")
    return texts


def fetch_reviews_by_name(name: str) -> tuple[str, list[str]] | None:
    """
    一次到位：用地點名稱找 place_id → 抓評論。
    回傳 (官方名稱, 評論清單)；查無地點或 API 未設定時回傳 None。
    """
    gmaps = get_places_client()
    if gmaps is None:
        return None
    found = find_place_id(gmaps, name)
    if found is None:
        return None
    place_id, official_name = found
    reviews = fetch_place_reviews(gmaps, place_id)
    return official_name, reviews
