import base64
import json
import logging
import subprocess
import sys
from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import is_relevant_title
from database import (
    CITY_ALIASES,
    classify_work_mode,
    job_work_mode,
    get_job,
    get_job_by_resume_job_id,
    get_jobs,
    get_last_scrape_run,
    get_stats,
    is_scrape_running,
    save_job_resume_pdf,
    update_job_resume_status,
    update_job_scraped_details,
    update_job_status,
)
from models import (
    Job,
    JobDescriptionRequest,
    JobStatus,
    JobStatusUpdate,
    ResumeGenerateRequest,
)
from utils.description import fetch_job_details, get_job_description_formatted
from utils.shapeshifter import submit_resume_job

logger = logging.getLogger("dashboard")

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
        "name": "Shapeshifter Resume API",
        "description": "Endpoints for triggering, checking, receiving (webhook), and downloading tailored resumes from Shapeshifter.",
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

# The city the dashboard opens on when the URL names none. Must be a key in
# CITY_ALIASES, or "all" for no default filter.
DEFAULT_CITY = "bangalore"

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.filters["relevant"] = is_relevant_title
templates.env.filters["work_mode"] = classify_work_mode
templates.env.filters["job_mode"] = job_work_mode


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
    city: str | None = Query(None, description="Filter by city, e.g. 'bangalore' or 'remote'"),
    work_mode: str | None = Query(None, description="'remote', 'hybrid', 'onsite' or 'unknown'"),
    posted_within: str | None = Query(None, description="Time window: 30m, 1h, 24h, 3d, 7d"),
    q: str | None = Query(None, description="Search job title or company"),
    max_exp: str | None = Query(None, description="Hide roles demanding more than N years"),
):
    filter_source = source if source and source != "all" else None
    filter_status = status if status and status != "all" else None
    filter_relevant = relevant != "all"
    # Bangalore unless the URL says otherwise. `city=all` turns it off, so the
    # dropdown can still reach every city; only the unset default changes.
    effective_city = city if city else DEFAULT_CITY
    filter_city = effective_city if effective_city != "all" else None
    filter_mode = work_mode if work_mode and work_mode != "all" else None
    filter_within = posted_within if posted_within and posted_within != "all" else None
    search = q.strip() if q and q.strip() else None
    try:
        exp_cap = int(max_exp) if max_exp and max_exp != "all" else None
    except ValueError:
        exp_cap = None

    jobs = get_jobs(
        source=filter_source,
        status=filter_status,
        relevant=filter_relevant,
        city=filter_city,
        work_mode=filter_mode,
        posted_within=filter_within,
        search=search,
        max_exp_years=exp_cap,
    )
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
        "current_city": effective_city,
        "current_work_mode": work_mode or "all",
        "current_posted_within": posted_within or "all",
        "current_q": search or "",
        "current_max_exp": max_exp or "all",
        "cities": list(CITY_ALIASES.keys()),
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


@app.get(
    "/job/{job_id}/resume",
    tags=["Dashboard UI"],
    summary="Download Tailored Resume PDF",
    description="Download the customized PDF resume for the job.",
)
@app.get(
    "/job/{job_id}/resume/download",
    tags=["Dashboard UI"],
    include_in_schema=False,
)
async def download_resume_ui(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not job.resume_path or not Path(job.resume_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Resume PDF has not been generated for this job yet. Click 'Tailor Resume' to generate one.",
        )
    safe_company = "".join(c for c in job.company if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    safe_title = "".join(c for c in job.title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    filename = f"Resume_{safe_company}_{safe_title}.pdf"
    return FileResponse(
        path=job.resume_path,
        filename=filename,
        media_type="application/pdf",
    )


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


@app.post(
    "/api/jobs/{job_id}/fetch-description",
    tags=["Job Actions API"],
    summary="Fetch and Save Job Description (JSON)",
    description="Scrape full job description and details from source URL, update database, and return updated job.",
)
async def api_fetch_and_save_job_description(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")

    try:
        details = await fetch_job_details(platform=job.source, url=job.source_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch job description: {str(e)}",
        )

    if not details or not details.get("description"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scraper completed but no description was extracted from {job.source}.",
        )

    desc = details["description"]
    salary = details.get("salary_range") or job.salary_range
    update_job_scraped_details(job_id, description=desc, salary_range=salary)
    updated_job = get_job(job_id)

    return {
        "status": "success",
        "message": "Description fetched and saved to database successfully.",
        "job_id": job_id,
        "description": desc,
        "salary_range": salary,
        "job": updated_job,
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


# ==========================================
# Shapeshifter Resume Webhook & API Endpoints
# ==========================================

@app.post(
    "/api/v1/resumes/{resume_job_id}",
    tags=["Shapeshifter Resume API"],
    summary="Shapeshifter Webhook: Receive Resume Result",
    description="Webhook callback called by Shapeshifter with the tailored PDF resume payload.",
)
async def shapeshifter_webhook_callback(
    resume_job_id: str,
    payload: dict = Body(...),
):
    logger.info("Received Shapeshifter callback for job ID: %s", resume_job_id)
    job = get_job_by_resume_job_id(resume_job_id)
    if not job:
        payload_job_id = payload.get("jobId")
        if payload_job_id:
            job = get_job_by_resume_job_id(payload_job_id)

    status_val = payload.get("status", "succeeded")
    meta_val = json.dumps(payload.get("meta", {}))

    if not job:
        logger.warning("No job found in DB matching resume_job_id: %s", resume_job_id)
        return {"status": "unmatched_job", "jobId": resume_job_id}

    if status_val == "succeeded" and payload.get("pdfBase64"):
        try:
            pdf_bytes = base64.b64decode(payload["pdfBase64"])
            saved_path = save_job_resume_pdf(
                job_id=job.id,
                pdf_bytes=pdf_bytes,
                filename=payload.get("filename"),
                resume_job_id=resume_job_id,
                meta=meta_val,
            )
            logger.info("Successfully saved resume for job %d to %s", job.id, saved_path)
            return {"status": "saved", "job_id": job.id, "path": saved_path}
        except Exception as e:
            logger.error("Failed to decode/save resume for job %d: %s", job.id, e)
            update_job_resume_status(
                job_id=job.id,
                resume_status="failed",
                resume_job_id=resume_job_id,
                resume_meta=json.dumps({"error": str(e)}),
            )
            return {"status": "error", "error": str(e)}
    else:
        update_job_resume_status(
            job_id=job.id,
            resume_status="failed" if status_val == "failed" else status_val,
            resume_job_id=resume_job_id,
            resume_meta=meta_val,
        )
        return {"status": "updated", "job_id": job.id, "resume_status": status_val}


@app.post(
    "/api/jobs/{job_id}/resume/generate",
    tags=["Shapeshifter Resume API"],
    summary="Trigger Resume Tailoring (JSON)",
    description="Submit job description and profile to Shapeshifter for customized resume generation.",
)
async def api_generate_resume(
    job_id: int,
    request: Request,
    payload: ResumeGenerateRequest | None = None,
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    template = payload.template if payload else "modern"
    # Build callback URL matching dashboard host
    base_url_str = str(request.base_url).rstrip("/")
    callback_base_url = f"{base_url_str}/api/v1/resumes"

    try:
        result = await submit_resume_job(
            job_id=job_id,
            template=template,
            callback_base_url=callback_base_url,
        )
        return {
            "status": "success",
            "message": "Resume tailoring job submitted to Shapeshifter.",
            "data": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get(
    "/api/jobs/{job_id}/resume/status",
    tags=["Shapeshifter Resume API"],
    summary="Get Resume Status (JSON)",
    description="Check current tailoring status from local database and provide download URL if ready.",
)
async def api_get_resume_status(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    has_file = bool(job.resume_path and Path(job.resume_path).exists())
    return {
        "job_id": job.id,
        "resume_status": job.resume_status or "none",
        "resume_job_id": job.resume_job_id,
        "has_resume": has_file,
        "download_url": f"/job/{job.id}/resume" if has_file else None,
        "resume_updated_at": job.resume_updated_at,
        "resume_meta": job.resume_meta,
    }


@app.get(
    "/api/jobs/{job_id}/resume/download",
    tags=["Shapeshifter Resume API"],
    summary="Download Resume PDF (Binary)",
    description="Download the generated tailored resume PDF for the job.",
)
async def api_download_resume(job_id: int):
    return await download_resume_ui(job_id)


