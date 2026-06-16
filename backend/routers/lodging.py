from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..agents.rag_agent import add_reviews, analyze_lodging

router = APIRouter(prefix="/lodging", tags=["lodging"])


class IngestRequest(BaseModel):
    lodging_name: str
    reviews: list[str]


@router.post("/ingest")
async def ingest_reviews(req: IngestRequest):
    """匯入民宿評論至 ChromaDB（開發期手動呼叫）。"""
    if not req.reviews:
        raise HTTPException(status_code=400, detail="reviews 不可為空")
    count = add_reviews(req.lodging_name, req.reviews)
    return {"lodging": req.lodging_name, "ingested": count}


@router.get("/analyze")
async def analyze(lodging_name: str):
    """RAG 防雷分析：潔癖指數 + 機車友善指數。"""
    result = await analyze_lodging(lodging_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
