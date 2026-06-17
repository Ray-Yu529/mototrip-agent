from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..agents.weather_agent import fetch_forecast, parse_riding_advice
from ..agents.rag_agent import analyze_lodging
from ..agents.routing_agent import generate_itinerary
from ..agents.poi_agent import fetch_pois
from ..core.geocode import enrich_itinerary_coords

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


@router.post("/generate")
async def generate(req: ItineraryRequest):
    theme_label = THEMES.get(req.theme, req.theme)
    transport_note = TRANSPORT_NOTES.get(req.transport, req.transport)

    pref = req.preferences

    # 處理城市清單：有途經城市就用它（含目的地），否則只用目的地
    cities = req.waypoints if req.waypoints else [req.destination]

    # Step 1+2: 逐城市查天氣 + POI
    pref = req.preferences
    weather_by_city: dict[str, dict] = {}
    poi_list = list(req.poi_list)               # routing 用的扁平清單
    poi_pool_by_city: dict[str, dict] = {}      # 回傳給前端
    # 城市多時縮減每類數量，控制 Google Places 用量
    limit_each = 2 if len(cities) > 2 else 4

    for city in cities:
        raw_w = await fetch_forecast(city)
        w = parse_riding_advice(raw_w, req.altitude_m)
        weather_by_city[city] = w
        rain = w.get("rain_risk_pct", 0) if "error" not in w else 0

        poi_result = fetch_pois(
            destination=city,
            cuisines=pref.cuisines,
            attraction_types=pref.attraction_types,
            min_rating=pref.min_rating,
            min_price=pref.min_price,
            max_price=pref.max_price,
            venue_pref=pref.venue_pref,
            rain_risk_pct=rain,
            limit_each=limit_each,
        )
        poi_pool_by_city[city] = poi_result
        for r in poi_result.get("restaurants", []):
            poi_list.append({"name": r["name"], "type": "餐廳", "city": city,
                             "rating": r["rating"], "venue": r["venue"]})
        for a in poi_result.get("attractions", []):
            poi_list.append({"name": a["name"], "type": "景點", "city": city,
                             "rating": a["rating"], "venue": a["venue"]})

    # 第一個城市的天氣作為前端 day chip 與相容欄位
    weather_info = weather_by_city[cities[0]]
    poi_result = poi_pool_by_city[cities[0]]

    # Step 3: Lodging RAG（有填民宿名稱才分析，失敗不中斷行程生成）
    lodging_info: dict = {}
    if req.lodging_name.strip():
        rag = await analyze_lodging(req.lodging_name.strip())
        lodging_info = rag if "error" not in rag else {"note": rag["error"]}

    # 組偏好說明字串給 LLM
    venue_label = {"indoor": "偏好室內", "outdoor": "偏好室外",
                   "auto": "依天氣自動調整"}.get(pref.venue_pref, "不限")
    pref_parts = [f"室內外：{venue_label}（實際套用：{poi_result.get('venue_applied','any')}）",
                  f"最低評分：{pref.min_rating}"]
    if pref.cuisines:
        pref_parts.append(f"餐廳類型：{', '.join(pref.cuisines)}")
    if pref.attraction_types:
        pref_parts.append(f"景點類型：{', '.join(pref.attraction_types)}")
    if pref.min_price is not None or pref.max_price is not None:
        pref_parts.append(f"預算等級：{pref.min_price or 0}–{pref.max_price or 4}")
    preferences_note = "；".join(pref_parts)

    # Step 4: Routing（單次 LLM 呼叫）
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

    # 補上各 stop 的經緯度（多城市時用各 stop 自己的 city 當提示）
    if result.get("itinerary"):
        await enrich_itinerary_coords(result["itinerary"], region_hint=cities[0])

    # 附帶天氣與 POI 查詢結果，前端不需再打一次
    result["weather"] = weather_info
    result["poi_pool"] = poi_result

    return result
