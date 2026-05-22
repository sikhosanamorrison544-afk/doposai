"""DoposAI AI microservice entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router as ai_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="DoposAI AI Service",
    description="Business Intelligence reasoning via vLLM + Qwen3",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)


@app.get("/")
def root():
    return {
        "service": "DoposAI AI Service",
        "advisor": "DoposAI Business Advisor",
        "llm": "vLLM + Qwen3",
        "docs": "/docs",
    }
