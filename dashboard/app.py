import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import is_relevant_title
from database import (
    get_job,
    get_jobs,
    get_last_scrape_run,
    get_stats,
    is_scrape_running,
    update_job_status,
)
from models import Job, JobDescriptionRequest, JobStatus, JobStatusUpdate
from utils.description import get_job_description_formatted

tags_metadata = [
    {
        "name": "Dashboard UI",
        "description": "HTML web interface endpoints for browsing jobs and details in browser.",
    },
    {
        "name": "Jobs API",
        "description": "REST API endpoints for querying and fetching job listings.",
    },
    {
        "name": "Job Actions API",
        "description": "REST API endpoints for updating status and triggering auto-fill tasks.",
    },
    {
        "name": "Job Description API",
        "description": "Endpoints to scrape and fetch formatted job descriptions in plain text.",
    },
    {
        "name": "Scraper API",
        "description": "REST API endpoints for manually triggering job scrapers and monitoring scraping status.",
    },
    {
        "name": "Stats API",
        "description": "REST API endpoints for aggregate job scraping statistics.",
    },
]

app = FastAPI(
    title="Gobhunter API",
    description="API documentation for the **Gobhunter** automated job scraper, status manager, and auto-filler backend.",
    version="1.0.0",
    docs_url="/api-docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
)

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.filters["relevant"] = is_relevant_title


# ==========================================
# Dashboard UI Endpoints
# ==========================================

@app.get(
    "/",
    response_class=HTMLResponse,
    tags=["Dashboard UI"],
    summary="Dashboard HTML View",
    description="Renders the main job dashboard UI with list of jobs and summary statistics.",
)
async def index(
    request: Request,
    source: str | None = Query(None, description="Filter by job source platform"),
    status: str | None = Query(None, description="Filter by job status"),
    relevant: str | None = Query(None, description="Filter by title relevance ('all' or 'true')"),
):
    filter_source = source if source and source != "all" else None
    filter_status = status if status and status != "all" else None
    filter_relevant = relevant != "all"
    jobs = get_jobs(source=filter_source, status=filter_status, relevant=filter_relevant)
    stats = get_stats()
    last_scrape = get_last_scrape_run()
    is_scraping = is_scrape_running()
    return templates.TemplateResponse(request, "index.html", {
        "jobs": jobs,
        "stats": stats,
        "last_scrape": last_scrape,
        "is_scraping": is_scraping,
        "current_source": source or "all",
        "current_status": status or "all",
        "current_relevant": relevant or "true",
        "sources": ["indeed", "naukri",  "instahyre", "cutshort", "linkedin", "wellfound"],
    })


@app.get(
    "/job/{job_id}",
    response_class=HTMLResponse,
    tags=["Dashboard UI"],
    summary="Job Detail HTML View",
    description="Renders detailed information page for a specific job by ID.",
)
async def job_detail(
    request: Request,
    job_id: int,
    source: str = Query("all", description="Back link source filter parameter"),
    status: str = Query("all", description="Back link status filter parameter"),
    relevant: str = Query("true", description="Back link relevance filter parameter"),
):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    return templates.TemplateResponse(request, "detail.html", {
        "job": job,
        "back_source": source,
        "back_status": status,
        "back_relevant": relevant,
    })


@app.post(
    "/job/{job_id}/status",
    tags=["Dashboard UI"],
    summary="Form POST: Update Job Status",
    description="Form handler to update job status from the web interface and redirect back to job detail.",
)
async def update_status(
    job_id: int,
    status: str = Form(...),
    source: str = Form("all"),
    cur_status: str = Form("all"),
    relevant: str = Form("true"),
):
    try:
        job_status = JobStatus(status)
        update_job_status(job_id, job_status)
    except ValueError:
        pass
    url = f"/job/{job_id}?source={source}&status={cur_status}&relevant={relevant}"
    return RedirectResponse(url=url, status_code=303)


@app.post(
    "/job/{job_id}/fill",
    tags=["Dashboard UI"],
    summary="Form POST: Trigger Auto-fill",
    description="Form handler to launch auto-fill subprocess for a job and redirect back to job detail.",
)
async def trigger_fill(
    job_id: int,
    source: str = Form("all"),
    status: str = Form("all"),
    relevant: str = Form("true"),
):
    project_root = Path(__file__).parent.parent
    subprocess.Popen(
        [sys.executable, "main.py", "fill", str(job_id)],
        cwd=str(project_root),
    )
    url = f"/job/{job_id}?source={source}&status={status}&relevant={relevant}"
    return RedirectResponse(url=url, status_code=303)


# ==========================================
# REST JSON API Endpoints
# ==========================================

@app.get(
    "/api/jobs",
    response_model=list[Job],
    tags=["Jobs API"],
    summary="List Jobs (JSON)",
    description="Retrieve job listings matching filter parameters in JSON format.",
)
async def api_get_jobs(
    source: str | None = Query(None, description="Filter by job source site (e.g. indeed, naukri, linkedin)"),
    status: JobStatus | None = Query(None, description="Filter by job status (new, applied, rejected, etc.)"),
    relevant: bool = Query(True, description="Filter title relevance based on config keywords"),
    exclude_dismissed: bool = Query(True, description="Exclude jobs marked as dismissed"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    status_val = status.value if status else None
    return get_jobs(
        source=source,
        status=status_val,
        relevant=relevant,
        exclude_dismissed=exclude_dismissed,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/jobs/{job_id}",
    response_model=Job,
    tags=["Jobs API"],
    summary="Get Job Details (JSON)",
    description="Retrieve complete details for a single job by ID.",
)
async def api_get_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")
    return job


@app.patch(
    "/api/jobs/{job_id}/status",
    response_model=Job,
    tags=["Job Actions API"],
    summary="Update Job Status (JSON)",
    description="Programmatically update job status and optional notes.",
)
async def api_update_job_status(job_id: int, payload: JobStatusUpdate):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")
    update_job_status(job_id, payload.status, notes=payload.notes)
    updated_job = get_job(job_id)
    return updated_job


@app.post(
    "/api/jobs/{job_id}/fill",
    tags=["Job Actions API"],
    summary="Trigger Auto-fill Process (JSON)",
    description="Launch background Playwright auto-fill subprocess for a job.",
)
async def api_trigger_fill(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")
    
    project_root = Path(__file__).parent.parent
    subprocess.Popen(
        [sys.executable, "main.py", "fill", str(job_id)],
        cwd=str(project_root),
    )
    return {
        "status": "success",
        "message": f"Auto-fill process initiated for job ID {job_id}",
        "job_id": job_id,
    }


@app.get(
    "/api/stats",
    tags=["Stats API"],
    summary="Get Scraping Statistics (JSON)",
    description="Retrieve aggregated job status and platform stats.",
)
async def api_get_stats():
    return get_stats()


@app.post(
    "/api/scrape",
    tags=["Scraper API"],
    summary="Trigger Manual Scraping (JSON)",
    description="Launch background job scraper subprocess if not currently running.",
)
async def api_trigger_scrape():
    if is_scrape_running():
        return {
            "status": "already_running",
            "message": "Scraper is already running in background.",
            "is_running": True,
        }

    project_root = Path(__file__).parent.parent
    subprocess.Popen(
        [sys.executable, "main.py", "scrape"],
        cwd=str(project_root),
    )
    return {
        "status": "started",
        "message": "Scraping process initiated.",
        "is_running": True,
    }


@app.get(
    "/api/scrape/status",
    tags=["Scraper API"],
    summary="Get Scraper Status (JSON)",
    description="Retrieve current running status and details of the latest scrape execution.",
)
async def api_get_scrape_status():
    last_run = get_last_scrape_run()
    running = is_scrape_running()
    return {
        "is_running": running,
        "last_run": last_run,
    }


# ==========================================
# Job Description Plain Text API Endpoints
# ==========================================

@app.get(
    "/api/description",
    response_class=PlainTextResponse,
    tags=["Job Description API"],
    summary="Get Formatted Job Description (Plain Text)",
    description="Fetch and format job details and description directly from a job URL and platform in plain text format.",
)
@app.get(
    "/api/job/description",
    response_class=PlainTextResponse,
    tags=["Job Description API"],
    include_in_schema=False,
)
async def api_get_job_description(
    url: str = Query(..., description="Job posting URL to scrape"),
    platform: str | None = Query(None, description="Platform name (indeed, naukri, instahyre, cutshort, linkedin, wellfound). Auto-detected if omitted."),
):
    try:
        return await get_job_description_formatted(url=url, platform=platform)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch job description: {str(e)}")


@app.post(
    "/api/description",
    response_class=PlainTextResponse,
    tags=["Job Description API"],
    summary="Get Formatted Job Description via POST (Plain Text)",
    description="Fetch and format job details and description directly from a job URL and platform in plain text format.",
)
@app.post(
    "/api/job/description",
    response_class=PlainTextResponse,
    tags=["Job Description API"],
    include_in_schema=False,
)
async def api_post_job_description(
    payload: JobDescriptionRequest,
):
    try:
        return await get_job_description_formatted(url=payload.url, platform=payload.platform)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to fetch job description: {str(e)}")


