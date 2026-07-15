from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .routers import weather, lodging, itinerary, rail
from .core.config import settings
from .core import routing as routing_core
from .agents import weather_agent, rail_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MotoTrip Agent API started")
    yield
    await weather_agent.aclose_client()
    await routing_core.aclose_client()
    await rail_agent.aclose_client()


app = FastAPI(
    title="MotoTrip Agent API",
    description="山林騎旅全能管家後端",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(weather.router)
app.include_router(lodging.router)
app.include_router(itinerary.router)
app.include_router(rail.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mototrip-agent"}
