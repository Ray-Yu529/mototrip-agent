from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .routers import weather, lodging, itinerary

app = FastAPI(
    title="MotoTrip Agent API",
    description="山林騎旅全能管家後端",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit dev origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(weather.router)
app.include_router(lodging.router)
app.include_router(itinerary.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mototrip-agent"}


@app.on_event("startup")
async def startup():
    logger.info("MotoTrip Agent API started")
