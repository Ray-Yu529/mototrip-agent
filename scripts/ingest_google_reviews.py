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

from backend.core.google_reviews import get_places_client, fetch_reviews_by_name
from backend.agents.rag_agent import add_reviews


def build_client():
    gmaps = get_places_client()
    if gmaps is None:
        print("錯誤：請在 .env 填入 GOOGLE_PLACES_API_KEY")
        print("申請：https://console.cloud.google.com/ → 啟用 Places API")
        sys.exit(1)
    return gmaps


def ingest_place(name: str) -> None:
    logger.info(f"搜尋：{name}")
    found = fetch_reviews_by_name(name)
    if found is None:
        logger.error(f"  找不到地點：{name}")
        return

    official_name, reviews = found
    logger.info(f"  找到：{official_name}")
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

    build_client()  # 提早檢查 API key 是否設定
    for name in args.names:
        ingest_place(name)

    print("\n完成！在 Streamlit「住宿防雷分析」頁輸入民宿名稱即可測試。")


if __name__ == "__main__":
    main()
