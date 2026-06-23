import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import is_relevant_title
from database import get_jobs, get_job, get_stats, update_job_status
from models import JobStatus

app = FastAPI()

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
templates.env.filters["relevant"] = is_relevant_title


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    source: str | None = None,
    status: str | None = None,
    relevant: str | None = None,
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


@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    source: str = "all",
    status: str = "all",
    relevant: str = "true",
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


@app.post("/job/{job_id}/status")
async def update_status(
    job_id: int,
    status: str = Form(...),
    source: str = "all",
    cur_status: str = "all",
    relevant: str = "true",
):
    try:
        job_status = JobStatus(status)
        update_job_status(job_id, job_status)
    except ValueError:
        pass
    url = f"/job/{job_id}?source={source}&status={cur_status}&relevant={relevant}"
    return RedirectResponse(url=url, status_code=303)


@app.post("/job/{job_id}/fill")
async def trigger_fill(
    job_id: int,
    source: str = "all",
    status: str = "all",
    relevant: str = "true",
):
    project_root = Path(__file__).parent.parent
    subprocess.Popen(
        [sys.executable, "main.py", "fill", str(job_id)],
        cwd=str(project_root),
    )
    url = f"/job/{job_id}?source={source}&status={status}&relevant={relevant}"
    return RedirectResponse(url=url, status_code=303)
