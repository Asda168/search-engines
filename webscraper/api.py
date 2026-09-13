"""FastAPI endpoint: GET /search?url=...&q=...&threshold=60

Run with: uvicorn webscraper.api:app --reload
Then open http://127.0.0.1:8000/ for a browser test UI.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .scraper import ScrapeError, scrape_and_search

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Web Scraper Search", version="1.0.0")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/search")
def search(
    url: str = Query(..., description="Target webpage URL"),
    q: str = Query(..., description="Search keyword or phrase"),
    threshold: int = Query(60, ge=0, le=100, description="Minimum fuzzy match score"),
):
    try:
        return scrape_and_search(url, q, threshold=threshold)
    except ScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok"}
