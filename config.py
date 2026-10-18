import re
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings

# Built-in exclusion patterns (always applied on top of user exclusions)
#
# The digits are gone from _LEVEL_2UP on purpose. They were meant to catch
# "Engineer 2" and "Developer III", but \b[2-9]\b also matches the numbers in
# "Frontend Developer (3-5 yrs)", which is how Naukri titles a large share of
# its postings. One query went from 0 saved to 81 saved without them.
_SENIORITY = r"Senior|Sr|Staff|Principal|Lead"
_LEVEL_2UP = r"II|III|IV|V"

def _build_title_patterns(settings: "Settings") -> list[re.Pattern]:
    include_keywords = [kw.strip() for kw in settings.include_keywords.split(",") if kw.strip()]
    exclude_keywords = [kw.strip() for kw in settings.exclude_keywords.split(",") if kw.strip()]

    # If include_keywords is empty, fall back to terms in search_query
    if not include_keywords and settings.search_query:
        include_keywords = [kw.strip() for kw in settings.search_query.split(",") if kw.strip()]
        if not include_keywords:
            include_keywords = [settings.search_query.strip()]

    exclude_parts = [re.escape(kw) for kw in exclude_keywords]
    exclude_parts.extend([_SENIORITY, _LEVEL_2UP])
    exclude_pattern = "|".join(p for p in exclude_parts if p)

    patterns = []
    for inc in include_keywords:
        patterns.append(re.compile(
            rf"^(?=.*\b{re.escape(inc)}\b)(?!.*\b(?:{exclude_pattern})\b)",
            re.IGNORECASE,
        ))

    return patterns


def is_relevant_title(title: str) -> bool:
    patterns = _build_title_patterns(settings)
    return any(p.search(title) for p in patterns)


class Settings(BaseSettings):
    resume_path: str = str(Path.home() / "Downloads" / "resume.pdf")
    dashboard_port: int = 8765

    search_query: str = "Python Backend Developer"
    search_locations: list[str] | str = ["Bangalore", "Bengaluru", "Remote"]

    @field_validator("search_locations", mode="before")
    @classmethod
    def parse_search_locations(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    import json
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [loc.strip() for loc in v.split(",") if loc.strip()]
        return v

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
        "Hi, I'm a passionate software developer "
        "looking for opportunities to build scalable systems."
    )

    shapeshifter_url: str = "http://localhost:3001"
    shapeshifter_user_id: str = "default"
    shapeshifter_template: str = "modern"
    shapeshifter_callback_url: str = ""
    profile_path: str = "profile.md"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
INCLUDE_TITLE_PATTERNS = _build_title_patterns(settings)
