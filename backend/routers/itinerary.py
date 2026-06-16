from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..agents.weather_agent import fetch_forecast, parse_riding_advice
from ..agents.rag_agent import analyze_lodging
from ..agents.routing_agent import generate_itinerary

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


class ItineraryRequest(BaseModel):
    theme: str = "michelin"
    origin: str
    destination: str
    start_date: str                         # YYYY-MM-DD 出發日
    days: int = Field(1, ge=1, le=7)        # 旅遊天數
    transport: str = "機車"                 # 交通方式
    altitude_m: int = 0
    lodging_name: str = ""
    poi_list: list[dict] = []


@router.post("/generate")
async def generate(req: ItineraryRequest):
    theme_label = THEMES.get(req.theme, req.theme)
    transport_note = TRANSPORT_NOTES.get(req.transport, req.transport)

    # Step 1: Weather（只抓第一天，多日行程用同一份預報方向判斷）
    raw_weather = await fetch_forecast(req.destination)
    weather_info = parse_riding_advice(raw_weather, req.altitude_m)

    # Step 2: Lodging RAG（有填民宿名稱才分析，失敗不中斷行程生成）
    lodging_info: dict = {}
    if req.lodging_name.strip():
        result = await analyze_lodging(req.lodging_name.strip())
        if "error" not in result:
            lodging_info = result
        else:
            lodging_info = {"note": result["error"]}

    # Step 3: Routing（單次 LLM 呼叫）
    result = await generate_itinerary(
        theme=theme_label,
        origin=req.origin,
        destination=req.destination,
        start_date=req.start_date,
        days=req.days,
        transport=req.transport,
        transport_note=transport_note,
        weather_info=weather_info,
        poi_list=req.poi_list,
        lodging_info=lodging_info,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result
