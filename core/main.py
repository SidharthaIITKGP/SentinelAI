"""FastAPI entry point for the currently available SentinelAI routes."""

from fastapi import FastAPI

from api.routes.responsibility import router as responsibility_router

app = FastAPI(title="SentinelAI", version="0.1.0")
app.include_router(responsibility_router)
