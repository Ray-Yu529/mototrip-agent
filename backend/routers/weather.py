from fastapi import APIRouter, Query
from ..agents.weather_agent import fetch_forecast, parse_riding_advice

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("/advice")
async def get_weather_advice(
    location: str = Query(..., description="鄉鎮名稱，例如：仁愛鄉"),
    altitude_m: int = Query(0, description="目的地海拔（公尺）"),
):
    raw = await fetch_forecast(location)
    return parse_riding_advice(raw, altitude_m)
