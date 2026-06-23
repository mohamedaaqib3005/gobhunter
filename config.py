import re
from pathlib import Path

from pydantic_settings import BaseSettings


# Built-in exclusion patterns (always applied on top of user exclusions)
_SENIORITY = r"Senior|Sr|Staff|Principal|Lead"
_LEVEL_2UP = r"[2-9]|II|III|IV|V"


def _build_title_patterns(settings: "Settings") -> list[re.Pattern]:
    include_keywords = [kw.strip() for kw in settings.include_keywords.split(",") if kw.strip()]
    exclude_keywords = [kw.strip() for kw in settings.exclude_keywords.split(",") if kw.strip()]

    exclude_parts = [re.escape(kw) for kw in exclude_keywords]
    exclude_parts.extend([_SENIORITY, _LEVEL_2UP])
    exclude_pattern = "|".join(exclude_parts)

    patterns = []
    for inc in include_keywords:
        patterns.append(re.compile(
            rf"(?=.*\b{re.escape(inc)}\b)(?!.*\b(?:{exclude_pattern})\b)",
            re.IGNORECASE,
        ))

    # SDE 1 / SDE I (any level-1 variant)
    patterns.append(re.compile(r"^.*\bSDE\s*[-–—]?\s*(?:1|I)\b.*$", re.IGNORECASE | re.DOTALL))
    # Software Development Engineer 1 / I
    patterns.append(re.compile(
        r"^.*\bSoftware\s+Development\s+Engineer\s+(?:1|I)\b.*$",
        re.IGNORECASE | re.DOTALL,
    ))

    return patterns


def is_relevant_title(title: str) -> bool:
    return any(p.search(title) for p in INCLUDE_TITLE_PATTERNS)


class Settings(BaseSettings):
    resume_path: str = str(Path.home() / "Downloads" / "resume.pdf")
    dashboard_port: int = 8765

    search_query: str = "Python Backend Developer"
    search_locations: list[str] = ["Bangalore", "Bengaluru", "Remote"]

    include_keywords: str = "Python,Backend,Software Engineer"
    exclude_keywords: str = ""

    browser_locale: str = "en-IN"
    browser_timezone: str = "Asia/Kolkata"

    applicant_name: str = ""
    applicant_email: str = ""
    applicant_phone: str = ""
    applicant_linkedin: str = ""
    applicant_portfolio: str = ""
    applicant_cover_letter: str = (
        "Hi, I'm a passionate Python backend developer "
        "looking for opportunities to build scalable systems. "
        "I have experience with Python, FastAPI, Django, and databases."
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
INCLUDE_TITLE_PATTERNS = _build_title_patterns(settings)
