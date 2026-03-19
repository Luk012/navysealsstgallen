from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.data_loader import data_store
from backend.routes import process, requests, feedback


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_store.load()
    yield


app = FastAPI(
    title="ChainIQ Sourcing Agent",
    description="Audit-Ready Autonomous Sourcing Agent for procurement",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "requests_loaded": len(data_store.requests_by_id)}


app.include_router(process.router, prefix="/api")
app.include_router(requests.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
