import asyncio
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from ..agents.weather_agent import fetch_forecast, parse_riding_advice
from ..agents.rag_agent import analyze_lodging
from ..agents.routing_agent import generate_itinerary, adjust_itinerary
from ..agents.poi_agent import fetch_pois
from ..agents.gas_agent import check_route_fuel_stops
from ..agents.budget_agent import estimate_budget
from ..core.geocode import enrich_itinerary_coords
from ..core.routing import get_routes_for_days
from ..core.export import build_gpx, build_ics
from ..core.config import settings

router = APIRouter(prefix="/itinerary", tags=["itinerary"])

THEMES = {
    "michelin": "米其林必比登吃貨之旅",
    "couple":   "雙人浪漫微旅行",
    "hardcore": "硬派跑山刷彎",
    "photo":    "秘境攝影打卡",
}

TRANSPORT_NOTES = {
    "機車":   "避開國道與高架；山路彎道多，每段騎程建議不超過 1.5 小時；注意加油站間距",
    "重機":   "避開國道與高架；適合跑山刷彎，每段騎程可延長至 2 小時；注意停車場是否能停重機",
    "自行車": "只走省道與縣道；速度約 15–20 km/h；每日騎程建議不超過 80 公里；需安排補給點",
    "汽車":   "可走國道快速抵達，再轉縣道探訪景點；停車較容易但山區路窄需注意會車",
    "大眾運輸": "以火車/客運為主幹，景點間搭計程車或步行；行程節奏較慢，適合輕旅行",
}


class TripPreferences(BaseModel):
    """可擴充的偏好物件，貫穿 POI 查詢與行程規劃。"""
    cuisines: list[str] = []                 # 餐廳類型
    attraction_types: list[str] = []         # 景點類型
    min_rating: float = Field(4.0, ge=0, le=5)
    min_price: int | None = Field(None, ge=0, le=4)   # Google price level
    max_price: int | None = Field(None, ge=0, le=4)
    venue_pref: str = "auto"                 # indoor | outdoor | auto


class ItineraryRequest(BaseModel):
    theme: str = "michelin"
    origin: str
    destination: str
    waypoints: list[str] = []                # 途經城市（多目的地，環島用）
    start_date: str                         # YYYY-MM-DD 出發日
    days: int = Field(1, ge=1, le=10)       # 旅遊天數
    transport: str = "機車"                 # 交通方式
    altitude_m: int = 0
    lodging_name: str = ""
    preferences: TripPreferences = TripPreferences()
    poi_list: list[dict] = []                # 手動景點（選填，會與自動查詢合併）


class AdjustRequest(BaseModel):
    itinerary: dict          # /generate 回傳的完整行程物件
    instruction: str         # 使用者的修改指令，例如「Day 2 不要去清境農場」


class ExportRequest(BaseModel):
    itinerary: dict


async def _attach_gas_info(day: dict, transport: str) -> None:
    route = day.get("route")
    if not route:
        return
    gas_info = await check_route_fuel_stops(
        route.get("geometry", []), route.get("distance_km", 0), transport
    )
    day["gas_stations"] = gas_info["stations"]
    if gas_info["warnings"]:
        day["gas_warnings"] = gas_info["warnings"]


async def _enrich_route_gas_budget(
    itinerary: list[dict], transport: str, preferences: TripPreferences | None = None
) -> dict:
    """真實路線（OSRM）→ 加油站檢查 → 預算估算，共用於 /generate 與 /adjust。"""
    await get_routes_for_days(itinerary, transport)
    await asyncio.gather(*(_attach_gas_info(day, transport) for day in itinerary))
    pref = preferences or TripPreferences()
    return estimate_budget(
        itinerary, transport,
        settings.fuel_price_per_liter, settings.meal_price_by_level,
        pref.min_price, pref.max_price,
    )


@router.post("/generate")
async def generate(req: ItineraryRequest):
    theme_label = THEMES.get(req.theme, req.theme)
    transport_note = TRANSPORT_NOTES.get(req.transport, req.transport)
    pref = req.preferences

    # 處理城市清單：有途經城市就用它（含目的地），否則只用目的地
    cities = req.waypoints if req.waypoints else [req.destination]

    start = date.fromisoformat(req.start_date)
    trip_dates = [(start + timedelta(days=i)).isoformat() for i in range(req.days)]

    # 城市多時縮減每類數量，控制 Google Places 用量
    # （至少 3 個，讓 LLM 能為每個餐廳/景點 stop 給 2–3 個候選供使用者挑選）
    limit_each = 3 if len(cities) > 2 else 4

    async def _fetch_city(city: str) -> tuple[str, dict, dict]:
        raw_w = await fetch_forecast(city)
        weather_dates = {d: parse_riding_advice(raw_w, req.altitude_m, target_date=d)
                          for d in trip_dates}
        # 用整趟行程期間「最高」降雨風險決定室內外候選比重（保守，而非只看最佳時段）
        max_rain = max(
            (w.get("max_rain_risk_pct", w.get("rain_risk_pct", 0))
             for w in weather_dates.values() if "error" not in w),
            default=0,
        )
        poi_result = await fetch_pois(
            destination=city,
            cuisines=pref.cuisines,
            attraction_types=pref.attraction_types,
            min_rating=pref.min_rating,
            min_price=pref.min_price,
            max_price=pref.max_price,
            venue_pref=pref.venue_pref,
            rain_risk_pct=max_rain,
            limit_each=limit_each,
        )
        return city, weather_dates, poi_result

    # 各城市查詢彼此獨立，與住宿 RAG 分析（若有）一起平行送出
    city_task = asyncio.gather(*(_fetch_city(c) for c in cities))
    lodging_task = (
        analyze_lodging(req.lodging_name.strip()) if req.lodging_name.strip() else None
    )
    if lodging_task is not None:
        city_results, rag = await asyncio.gather(city_task, lodging_task)
    else:
        city_results = await city_task
        rag = None

    weather_by_city: dict[str, dict] = {}
    poi_pool_by_city: dict[str, dict] = {}
    poi_list = list(req.poi_list)               # routing 用的扁平清單
    known_coords: dict[str, tuple[float, float]] = {}  # POI 已知座標，減少重複 geocode

    for city, weather_dates, poi_result in city_results:
        weather_by_city[city] = weather_dates
        poi_pool_by_city[city] = poi_result
        for r in poi_result.get("restaurants", []):
            poi_list.append({"name": r["name"], "type": "餐廳", "city": city,
                             "rating": r["rating"], "venue": r["venue"]})
            if r.get("lat") is not None and r.get("lon") is not None:
                known_coords[r["name"]] = (r["lat"], r["lon"])
        for a in poi_result.get("attractions", []):
            poi_list.append({"name": a["name"], "type": "景點", "city": city,
                             "rating": a["rating"], "venue": a["venue"]})
            if a.get("lat") is not None and a.get("lon") is not None:
                known_coords[a["name"]] = (a["lat"], a["lon"])

    # 第一個城市第一天的天氣，作為前端相容欄位（day chip 預設值）
    weather_info = weather_by_city[cities[0]].get(trip_dates[0], {})
    poi_result_first = poi_pool_by_city[cities[0]]

    lodging_info: dict = {}
    if rag is not None:
        lodging_info = rag if "error" not in rag else {"note": rag["error"]}

    # 組偏好說明字串給 LLM
    venue_label = {"indoor": "偏好室內", "outdoor": "偏好室外",
                   "auto": "依天氣自動調整"}.get(pref.venue_pref, "不限")
    pref_parts = [f"室內外：{venue_label}（實際套用：{poi_result_first.get('venue_applied','any')}）",
                  f"最低評分：{pref.min_rating}"]
    if pref.cuisines:
        pref_parts.append(f"餐廳類型：{', '.join(pref.cuisines)}")
    if pref.attraction_types:
        pref_parts.append(f"景點類型：{', '.join(pref.attraction_types)}")
    if pref.min_price is not None or pref.max_price is not None:
        pref_parts.append(f"預算等級：{pref.min_price or 0}–{pref.max_price or 4}")
    preferences_note = "；".join(pref_parts)

    # Routing（單次 LLM 呼叫）
    result = await generate_itinerary(
        theme=theme_label,
        origin=req.origin,
        destination=req.destination,
        cities=cities,
        weather_by_city=weather_by_city,
        start_date=req.start_date,
        days=req.days,
        transport=req.transport,
        transport_note=transport_note,
        weather_info=weather_info,
        poi_list=poi_list,
        lodging_info=lodging_info,
        preferences_note=preferences_note,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    if result.get("itinerary"):
        # 補上各 stop 的經緯度（多城市時用各 stop 自己的 city 當提示；POI 已知座標優先，減少 Nominatim 查詢）
        await enrich_itinerary_coords(
            result["itinerary"], region_hint=cities[0], known_coords=known_coords
        )
        # 真實路線（OSRM 距離/時間/幾何）→ 沿線加油站 → 預算估算
        result["budget"] = await _enrich_route_gas_budget(
            result["itinerary"], req.transport, pref
        )

    # 附帶天氣與 POI 查詢結果，前端不需再打一次
    result["weather"] = weather_info
    result["weather_by_city"] = weather_by_city   # 每城市每日期的完整預報，供前端每日天氣晶片使用
    result["poi_pool"] = poi_result_first

    return result


_STOP_KEYS_FOR_LLM = ("time", "place", "city", "type", "note", "transfer", "parking", "options")


def _slim_itinerary_for_llm(itinerary_data: dict) -> dict:
    """
    後端會把 route（OSRM 完整路線幾何，可能上千個座標點）、gas_stations、gas_warnings
    附加回 itinerary 物件，這些對 LLM 重新規劃毫無幫助，卻會把 prompt 撐爆
    （曾實測 2 天行程把完整物件丟回去，prompt 直接超過模型 25 萬 token 上限）。
    這裡只保留 LLM 需要、當初自己輸出過的欄位。
    """
    slim_days = []
    for day in itinerary_data.get("itinerary", []) or []:
        slim_day = {k: day[k] for k in ("day", "date", "city") if k in day}
        slim_day["stops"] = [
            {k: stop[k] for k in _STOP_KEYS_FOR_LLM if k in stop}
            for stop in day.get("stops", [])
        ]
        slim_days.append(slim_day)
    return {
        **{k: itinerary_data[k] for k in ("theme", "transport", "total_days", "survival_tips")
           if k in itinerary_data},
        "itinerary": slim_days,
    }


def _harvest_known_coords(itinerary_data: dict) -> dict[str, tuple[float, float]]:
    """從既有行程（已定位過的 stops/options）與 poi_pool 收集座標，減少微調後重複 geocode。"""
    coords: dict[str, tuple[float, float]] = {}
    for day in itinerary_data.get("itinerary", []) or []:
        for stop in day.get("stops", []):
            if stop.get("place") and stop.get("lat") is not None and stop.get("lon") is not None:
                coords.setdefault(stop["place"], (stop["lat"], stop["lon"]))
            for opt in stop.get("options", []) or []:
                if opt.get("place") and opt.get("lat") is not None and opt.get("lon") is not None:
                    coords.setdefault(opt["place"], (opt["lat"], opt["lon"]))
    pool = itinerary_data.get("poi_pool", {}) or {}
    for item in pool.get("restaurants", []) + pool.get("attractions", []):
        if item.get("lat") is not None and item.get("lon") is not None:
            coords.setdefault(item["name"], (item["lat"], item["lon"]))
    return coords


@router.post("/adjust")
async def adjust(req: AdjustRequest):
    """對話式行程微調：帶著既有行程 + 一句話指令，重新排一次（額外 1 次 LLM 呼叫）。"""
    slim = _slim_itinerary_for_llm(req.itinerary)
    known_coords = _harvest_known_coords(req.itinerary)

    result = await adjust_itinerary(slim, req.instruction)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    transport = result.get("transport", req.itinerary.get("transport", "機車"))
    if result.get("itinerary"):
        await enrich_itinerary_coords(result["itinerary"], known_coords=known_coords)
        result["budget"] = await _enrich_route_gas_budget(result["itinerary"], transport)

    # 保留原本附帶的天氣/POI 資訊（微調不會重新查天氣或景點）
    for key in ("weather", "weather_by_city", "poi_pool"):
        if key in req.itinerary:
            result[key] = req.itinerary[key]

    return result


@router.post("/export/gpx")
async def export_gpx(req: ExportRequest):
    gpx = build_gpx(req.itinerary.get("itinerary", []), req.itinerary.get("theme", "行程"))
    return PlainTextResponse(gpx, media_type="application/gpx+xml")


@router.post("/export/ics")
async def export_ics(req: ExportRequest):
    ics = build_ics(req.itinerary.get("itinerary", []), req.itinerary.get("theme", "行程"))
    return PlainTextResponse(ics, media_type="text/calendar")
