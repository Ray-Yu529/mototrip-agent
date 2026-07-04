"""
Gas Station Agent — 沿著當天實際路線（來自 routing.py 的 OSRM geometry）
每隔一段距離用 Google Places Nearby Search 查詢加油站，
標出路線上真實找得到的加油站，並在無油站路段過長時提前警示。
自行車/大眾運輸不需要加油，略過此檢查。
"""
import math
import asyncio
from loguru import logger
from ..core.google_reviews import get_places_client

# 抽樣間隔（沿路線每隔多少公里查一次附近加油站）
SAMPLE_INTERVAL_KM = 20
# 單次查詢半徑（公尺）
SEARCH_RADIUS_M = 4000
# 最多抽樣點數，避免超長路線打爆 Places API 配額
MAX_SAMPLES = 12

# 建議提前預警的無油站最大安全距離（公里），保守值（非油箱極限）
WARNING_GAP_KM = {"機車": 80, "重機": 100, "汽車": 250}


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _sample_points(geometry: list[list[float]]) -> list[tuple[float, float, float]]:
    """
    geometry: [[lon, lat], ...]（OSRM 格式）。
    回傳等距抽樣點 [(lat, lon, cumulative_km), ...]，間隔 SAMPLE_INTERVAL_KM，最多 MAX_SAMPLES 個。
    """
    if len(geometry) < 2:
        return []

    points = [(lat, lon) for lon, lat in geometry]
    cumulative = [0.0]
    for i in range(1, len(points)):
        cumulative.append(cumulative[-1] + _haversine_km(points[i - 1], points[i]))
    total = cumulative[-1]
    if total <= 0:
        return [(points[0][0], points[0][1], 0.0)]

    n_samples = min(MAX_SAMPLES, max(2, int(total // SAMPLE_INTERVAL_KM) + 1))
    targets = [total * i / (n_samples - 1) for i in range(n_samples)]

    samples = []
    idx = 0
    for t in targets:
        while idx < len(cumulative) - 1 and cumulative[idx + 1] < t:
            idx += 1
        lat, lon = points[idx]
        samples.append((lat, lon, t))
    return samples


def _nearby_gas_stations_sync(lat: float, lon: float) -> list[dict]:
    gmaps = get_places_client()
    if gmaps is None:
        return []
    try:
        resp = gmaps.places_nearby(
            location=(lat, lon), radius=SEARCH_RADIUS_M, type="gas_station",
        )
    except Exception as exc:
        logger.warning(f"加油站查詢失敗 ({lat},{lon}): {exc}")
        return []
    out = []
    for p in resp.get("results", []):
        loc = p.get("geometry", {}).get("location", {})
        out.append({
            "name": p.get("name", ""),
            "place_id": p.get("place_id", ""),
            "lat": loc.get("lat"),
            "lon": loc.get("lng"),
        })
    return out


async def check_route_fuel_stops(
    geometry: list[list[float]], distance_km: float, transport: str
) -> dict:
    """
    回傳 {"stations": [...去重加油站含沿線公里數...], "warnings": [...]}。
    非機車/重機/汽車（如自行車、大眾運輸）直接回傳空結果。
    """
    if transport not in WARNING_GAP_KM or not geometry:
        return {"stations": [], "warnings": []}

    samples = _sample_points(geometry)
    if not samples:
        return {"stations": [], "warnings": []}

    results = await asyncio.gather(
        *(asyncio.to_thread(_nearby_gas_stations_sync, lat, lon) for lat, lon, _ in samples)
    )

    seen_ids: set[str] = set()
    stations: list[dict] = []
    for (lat, lon, km_mark), found in zip(samples, results):
        for st in found:
            key = st["place_id"] or st["name"]
            if not key or key in seen_ids:
                continue
            seen_ids.add(key)
            stations.append({**st, "approx_km_mark": round(km_mark, 1)})

    stations.sort(key=lambda s: s["approx_km_mark"])

    # 計算路線起點/加油站之間/終點的最大間距
    marks = [0.0] + [s["approx_km_mark"] for s in stations] + [distance_km]
    gaps = [marks[i + 1] - marks[i] for i in range(len(marks) - 1)]
    threshold = WARNING_GAP_KM[transport]

    warnings = []
    if not stations:
        if distance_km > threshold:
            warnings.append(
                f"本日路線沿線 {SEARCH_RADIUS_M // 1000}km 內查無加油站資料"
                f"（全程 {distance_km}km），出發前請確認油量充足"
            )
    else:
        max_gap = max(gaps) if gaps else 0
        if max_gap > threshold:
            warnings.append(
                f"本日路線有連續約 {round(max_gap)}km 路段沒有加油站"
                f"（安全建議 {threshold}km 內加油），請提前補滿油"
            )

    return {"stations": stations[:8], "warnings": warnings}
