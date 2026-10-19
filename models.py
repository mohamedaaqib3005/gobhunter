from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel


class JobStatus(str, Enum):
    NEW = "new"
    PREFILLED = "pre-filled"
    APPLIED = "applied"
    REJECTED = "rejected"
    BOOKMARKED = "bookmarked"
    CLOSED = "closed"
    DISMISSED = "dismissed"


class Job(BaseModel):
    id: int | None = None
    title: str
    company: str
    location: str
    source: str
    source_url: str
    description: str | None = None
    salary_range: str | None = None
    # When the employer posted it, as an ISO-8601 UTC string.
    # Cutshort is exact (decoded from its ObjectId), LinkedIn is minute-precise
    # while fresh, Naukri and Indeed are day-precise, and Instahyre publishes
    # nothing at all. None means unknown, never "old".
    posted_date: str | None = None
    # Required experience in years, where the site states it.
    exp_min: int | None = None
    exp_max: int | None = None
    # Work mode as the SITE states it, rather than inferred from the location
    # string. Only Cutshort provides this today.
    remote_mode: str | None = None
    status: JobStatus = JobStatus.NEW
    applied_date: datetime | None = None
    notes: str | None = None
    resume_path: str | None = None
    resume_job_id: str | None = None
    resume_status: str | None = "none"  # none, queued, processing, succeeded, failed
    resume_meta: str | None = None
    resume_updated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def dict(self, *args, **kwargs):
        d = super().model_dump(*args, **kwargs)
        return d


class JobStatusUpdate(BaseModel):
    status: JobStatus
    notes: str | None = None


class JobDescriptionRequest(BaseModel):
    url: str
    platform: str | None = None


class ResumeGenerateRequest(BaseModel):
    template: str | None = "modern"
    force_refresh: bool = False


