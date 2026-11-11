"""Analysis job control: start the pipeline, poll its progress."""

from fastapi import APIRouter, Request

from lib.session import require_user
from models.contribiq import AnalysisJob, AnalysisStatusResponse, StartAnalysisResponse
from services import pipeline

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/start", response_model=StartAnalysisResponse)
async def start_analysis(request: Request):
    user = await require_user(request)
    job = await pipeline.start_job(user, mode="full")
    return StartAnalysisResponse(job=AnalysisJob(**job))


@router.get("/status", response_model=AnalysisStatusResponse)
async def analysis_status(request: Request):
    user = await require_user(request)
    job = await pipeline.get_latest_job(user["id"])
    return AnalysisStatusResponse(job=AnalysisJob(**job) if job else None)
