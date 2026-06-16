"""
從 Google Places API 抓取真實民宿評論並存入 ChromaDB。

使用方式：
    python -m scripts.ingest_google_reviews --names "清境農場" "合歡山松雪樓"

需求：
    .env 內填入 GOOGLE_PLACES_API_KEY
    Google Cloud Console 開啟「Places API」

注意：
    Google Places API 每間地點最多回傳 5 則評論（官方限制）。
"""
import sys
import argparse
from pathlib import Path
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

import googlemaps
from backend.core.config import settings
from backend.agents.rag_agent import add_reviews


def build_client() -> googlemaps.Client:
    if not settings.google_places_api_key:
        print("錯誤：請在 .env 填入 GOOGLE_PLACES_API_KEY")
        print("申請：https://console.cloud.google.com/ → 啟用 Places API")
        sys.exit(1)
    return googlemaps.Client(key=settings.google_places_api_key)


def find_place_id(gmaps: googlemaps.Client, name: str) -> tuple[str, str]:
    """回傳 (place_id, 正式名稱)。找不到拋出 ValueError。"""
    result = gmaps.find_place(
        input=name,
        input_type="textquery",
        fields=["place_id", "name"],
        language="zh-TW",
    )
    candidates = result.get("candidates", [])
    if not candidates:
        raise ValueError(f"找不到地點：{name}")
    place = candidates[0]
    return place["place_id"], place.get("name", name)


def fetch_reviews(gmaps: googlemaps.Client, place_id: str) -> list[str]:
    """取得評論文字（最多 5 則，Google 官方上限）。"""
    result = gmaps.place(
        place_id=place_id,
        fields=["name", "rating", "reviews"],
        language="zh-TW",
        reviews_sort="newest",
    )
    place_data = result.get("result", {})
    reviews = place_data.get("reviews", [])

    texts = []
    for r in reviews:
        text = r.get("text", "").strip()
        rating = r.get("rating", "?")
        if text:
            texts.append(f"[{rating}星] {text}")

    return texts


def ingest_place(gmaps: googlemaps.Client, name: str) -> None:
    logger.info(f"搜尋：{name}")
    try:
        place_id, official_name = find_place_id(gmaps, name)
        logger.info(f"  找到：{official_name}（{place_id}）")
    except ValueError as e:
        logger.error(f"  {e}")
        return

    reviews = fetch_reviews(gmaps, place_id)
    if not reviews:
        logger.warning(f"  {official_name} 無公開評論，跳過")
        return

    count = add_reviews(official_name, reviews)
    logger.success(f"  匯入 {count} 則評論 → ChromaDB key：{official_name}")
    for i, r in enumerate(reviews, 1):
        preview = r[:80] + ("…" if len(r) > 80 else "")
        print(f"    [{i}] {preview}")


def main():
    parser = argparse.ArgumentParser(description="從 Google Maps 抓評論存入 ChromaDB")
    parser.add_argument(
        "--names", nargs="+", required=True,
        metavar="民宿名稱",
        help='要查詢的民宿名稱，例如 "清境農場" "廬山溫泉民宿"',
    )
    args = parser.parse_args()

    gmaps = build_client()
    for name in args.names:
        ingest_place(gmaps, name)

    print("\n完成！在 Streamlit「住宿防雷分析」頁輸入民宿名稱即可測試。")


if __name__ == "__main__":
    main()
