import asyncio
import json
import logging
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import settings
from database import (
    get_job,
    save_job_resume_pdf,
    update_job_resume_status,
    update_job_scraped_details,
)
from models import Job
from utils.description import fetch_job_details, format_job_details

logger = logging.getLogger("shapeshifter")


def build_job_description_payload(job: Job) -> str:
    """Format job details into the standard formatted text format matching description CLI/API."""
    details = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "salary_range": job.salary_range,
        "description": job.description,
    }
    return format_job_details(job.source or "unknown", details)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "http://localhost:3001"
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url.rstrip("/")


def get_candidate_profile() -> str:
    profile_path = Path(settings.profile_path)
    if not profile_path.is_absolute():
        profile_path = Path(__file__).parent.parent / profile_path

    if profile_path.exists():
        try:
            content = profile_path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception as e:
            logger.warning("Failed to read profile file at %s: %s", profile_path, e)

    # Fallback to config settings
    parts = []
    if settings.applicant_name:
        parts.append(f"Name: {settings.applicant_name}")
    if settings.applicant_email:
        parts.append(f"Email: {settings.applicant_email}")
    if settings.applicant_phone:
        parts.append(f"Phone: {settings.applicant_phone}")
    if settings.applicant_linkedin:
        parts.append(f"LinkedIn: {settings.applicant_linkedin}")
    if settings.applicant_portfolio:
        parts.append(f"Portfolio: {settings.applicant_portfolio}")
    if settings.applicant_cover_letter:
        parts.append(f"\nBackground / Summary:\n{settings.applicant_cover_letter}")
    return "\n".join(parts) if parts else "Software Engineer"


def _http_request_sync(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    req_headers = {"User-Agent": "gobhunter/1.0", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = Request(url=url, data=body, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            status_code = response.status
            resp_body = response.read().decode("utf-8")
            try:
                parsed = json.loads(resp_body)
                return status_code, parsed
            except Exception:
                return status_code, resp_body
    except HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        try:
            parsed_err = json.loads(err_body)
            return e.code, parsed_err
        except Exception:
            return e.code, err_body or str(e)
    except URLError as e:
        raise ConnectionError(f"Could not connect to {url}: {e.reason}") from e


async def http_request(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    return await asyncio.to_thread(_http_request_sync, url, method, data, headers, timeout)


async def submit_resume_job(
    job_id: int,
    template: str = "modern",
    callback_base_url: str | None = None,
    user_id: str | None = None,
) -> dict:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job with ID {job_id} not found")

    # If job has no description, try to auto-fetch it first
    description = job.description
    if not description or len(description.strip()) < 20:
        logger.info("Job %d description missing or short. Attempting to fetch description first...", job_id)
        try:
            details = await fetch_job_details(platform=job.source, url=job.source_url)
            if details and details.get("description"):
                description = details["description"]
                salary = details.get("salary_range") or job.salary_range
                update_job_scraped_details(job_id, description=description, salary_range=salary)
                job = get_job(job_id)
        except Exception as e:
            logger.warning("Could not auto-fetch description for job %d: %s", job_id, e)

    if not description or not description.strip():
        raise ValueError(
            "Job description is empty. Please click 'Fetch Description' for this job first."
        )

    # Build the full formatted job description (matching Description CLI / API)
    formatted_job_description = build_job_description_payload(job)

    profile_text = get_candidate_profile()
    if not profile_text or not profile_text.strip():
        raise ValueError(
            "Candidate profile is empty. Please configure profile.md or applicant info in .env."
        )

    # Determine callback URL (Base URL - Shapeshifter appends jobId)
    cb_url = callback_base_url or settings.shapeshifter_callback_url
    if not cb_url:
        cb_url = f"http://localhost:{settings.dashboard_port}/api/v1/resumes"
    cb_url = cb_url.rstrip("/")

    uid = user_id or settings.shapeshifter_user_id or "default"
    base_ss_url = normalize_url(settings.shapeshifter_url)
    submit_url = f"{base_ss_url}/api/v1/users/{uid}/resumes"

    req_payload = {
        "profile": profile_text,
        "jobDescription": formatted_job_description,
        "callbackUrl": cb_url,
        "template": template or settings.shapeshifter_template or "modern",
    }

    update_job_resume_status(job_id=job_id, resume_status="queued")

    try:
        status_code, resp = await http_request(
            url=submit_url,
            method="POST",
            data=req_payload,
            timeout=15.0,
        )
    except Exception as e:
        update_job_resume_status(
            job_id=job_id,
            resume_status="failed",
            resume_meta=json.dumps({"error": f"Connection error to Shapeshifter: {str(e)}"}),
        )
        raise ConnectionError(
            f"Failed to connect to Shapeshifter at {submit_url}: {str(e)}. "
            "Please ensure Shapeshifter is running and SHAPESHIFTER_URL in .env is correct."
        ) from e

    if status_code not in (200, 201, 202):
        err_msg = resp if isinstance(resp, str) else json.dumps(resp)
        update_job_resume_status(
            job_id=job_id,
            resume_status="failed",
            resume_meta=json.dumps({"status_code": status_code, "error": err_msg}),
        )
        raise RuntimeError(f"Shapeshifter rejected request ({status_code}): {err_msg}")

    resp_dict = resp if isinstance(resp, dict) else {}
    shapeshifter_job_id = resp_dict.get("jobId")

    update_job_resume_status(
        job_id=job_id,
        resume_status="queued",
        resume_job_id=shapeshifter_job_id,
        resume_meta=json.dumps(resp_dict),
    )

    return {
        "status": "queued",
        "job_id": job_id,
        "resume_job_id": shapeshifter_job_id,
        "queue_position": resp_dict.get("queuePosition", 0),
        "shapeshifter_response": resp_dict,
    }


async def poll_shapeshifter_status(job_id: int) -> dict:
    """Optional polling helper to check if Shapeshifter has finished the job."""
    job = get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    if not job.resume_job_id:
        return {"job_id": job_id, "status": job.resume_status or "none"}

    base_ss_url = normalize_url(settings.shapeshifter_url)
    uid = settings.shapeshifter_user_id or "default"
    
    # Try user-specific or general resume status endpoint if available
    poll_urls = [
        f"{base_ss_url}/api/v1/users/{uid}/resumes/{job.resume_job_id}",
        f"{base_ss_url}/api/v1/resumes/{job.resume_job_id}",
    ]

    for p_url in poll_urls:
        try:
            code, resp = await http_request(p_url, method="GET", timeout=5.0)
            if code == 200 and isinstance(resp, dict):
                ss_status = resp.get("status")
                if ss_status == "succeeded" and resp.get("pdfBase64"):
                    import base64
                    pdf_bytes = base64.b64decode(resp["pdfBase64"])
                    meta_str = json.dumps(resp.get("meta", {}))
                    save_job_resume_pdf(
                        job_id=job.id,
                        pdf_bytes=pdf_bytes,
                        filename=resp.get("filename"),
                        resume_job_id=job.resume_job_id,
                        meta=meta_str,
                    )
                    return {"job_id": job_id, "status": "succeeded", "ready": True}
                elif ss_status == "failed":
                    update_job_resume_status(
                        job_id=job.id,
                        resume_status="failed",
                        resume_meta=json.dumps(resp),
                    )
                    return {"job_id": job_id, "status": "failed", "ready": False}
        except Exception:
            pass

    return {
        "job_id": job_id,
        "status": job.resume_status or "none",
        "has_resume": bool(job.resume_path and Path(job.resume_path).exists()),
    }
