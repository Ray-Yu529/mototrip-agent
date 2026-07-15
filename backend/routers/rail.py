from fastapi import APIRouter, HTTPException, Query
from ..agents import rail_agent

router = APIRouter(prefix="/rail", tags=["rail"])


@router.get("/stations")
async def search_stations(
    keyword: str = Query(..., description="車站關鍵字，例如：竹、台北"),
):
    return await rail_agent.search_stations(keyword)


@router.get("/timetable")
async def get_timetable(
    origin: str = Query(..., description="出發站，例如：台北"),
    destination: str = Query(..., description="到達站，例如：花蓮"),
    date: str | None = Query(None, description="乘車日期 YYYY-MM-DD，預設今天"),
):
    result = await rail_agent.fetch_od_timetable(origin, destination, date)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/liveboard")
async def get_liveboard(
    station: str = Query(..., description="車站名稱，例如：台北"),
):
    result = await rail_agent.fetch_station_liveboard(station)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result)
    return result
