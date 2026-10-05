"""Env Intelligence — Agentic AI Environmental Pollution Monitoring & Regulatory Alert System (FastAPI)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import CORS_ORIGINS, SEED_ON_STARTUP
from .database import init_db
from .ml.anomaly_model import get_metrics
from .seed import seed
from .tools import rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if SEED_ON_STARTUP:
        seed()
    rag.build_index(force=True)
    get_metrics()
    yield


app = FastAPI(title="Env Intelligence API", version="1.0.0", lifespan=lifespan,
              description="Multi-agent environmental monitoring & regulatory alert system. Decision support only — no legal determinations.")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/")
def root():
    return {"service": "Env Intelligence API", "docs": "/docs", "health": "/api/health"}
