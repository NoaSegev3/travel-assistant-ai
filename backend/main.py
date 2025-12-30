# Role: FastAPI app bootstrap. Loads environment config early, registers routers, and exposes health/docs endpoints.

from fastapi import FastAPI

import backend.config
backend.config.load_env()

from backend.api.chat import router as chat_router
from backend.api.state import router as state_router

app = FastAPI(title="Travel Assistant API", version="0.1.0")
app.include_router(chat_router)
app.include_router(state_router)

@app.get("/")
def root() -> dict:
    # Role: quick discoverability for clients (where are docs/health).
    return {
        "message": "Travel Assistant API is running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
