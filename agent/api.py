"""
FastAPI Backend — AI Coding Agent API
Exposes the LangGraph agent over HTTP so the React frontend can use it.
"""

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import analyze_repo

app = FastAPI(title="AI Coding Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request/Response models ──────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    repo_path: str
    question: str


class AnalyzeResponse(BaseModel):
    result: str
    repo_path: str
    question: str


class RepoInfoRequest(BaseModel):
    repo_path: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "ai-coding-agent"}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze a repository and answer a question about it."""
    repo = Path(request.repo_path)
    if not repo.exists() or not repo.is_dir():
        raise HTTPException(status_code=400, detail=f"Repository path not found: {request.repo_path}")

    result = await analyze_repo(request.repo_path, request.question)
    return AnalyzeResponse(
        result=result,
        repo_path=request.repo_path,
        question=request.question,
    )


@app.post("/quick-summary")
async def quick_summary(request: RepoInfoRequest) -> dict:
    """Get a quick summary of a repository without a specific question."""
    repo = Path(request.repo_path)
    if not repo.exists():
        raise HTTPException(status_code=400, detail="Repository path not found")

    result = await analyze_repo(
        request.repo_path,
        "Give me a comprehensive summary of this repository: its purpose, architecture, "
        "main components, frameworks used, and how the code is organized.",
    )
    return {"summary": result, "repo_path": request.repo_path}


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
