import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import is_relevant_title
from database import get_job, get_jobs, get_stats, update_job_status
from models import Job, JobStatus, JobStatusUpdate

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
    return templates.TemplateResponse(request, "index.html", {
        "jobs": jobs,
        "stats": stats,
        "current_source": source or "all",
        "current_status": status or "all",
        "current_relevant": relevant or "true",
        "sources": ["indeed", "naukri", "shine", "timesjobs", "instahyre", "cutshort", "linkedin", "wellfound"],
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
