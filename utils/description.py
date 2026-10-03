import json
from pathlib import Path
from typing import Any

from scrapers.cutshort import CutshortScraper
from scrapers.indeed import IndeedScraper
from scrapers.instahyre import InstahyreScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.naukri import NaukriScraper
from scrapers.wellfound import WellfoundScraper
from utils.browser import scrape_with_cookies

import re

COOKIES_DIR = Path(__file__).parent.parent / ".cookies"

SCRAPER_MAP = {
    "indeed": IndeedScraper,
    "naukri": NaukriScraper,
    "instahyre": InstahyreScraper,
    "linkedin": LinkedInScraper,
    "wellfound": WellfoundScraper,
    "cutshort": CutshortScraper,
}


def clean_url(url: str) -> str:
    """Clean and unescape shell backslashes or quotation marks from URL."""
    if not url:
        return ""
    cleaned = str(url).strip().strip("'\"")
    cleaned = re.sub(r"\\([?&=/])", r"\1", cleaned)
    return cleaned.strip()


def detect_platform(url: str, platform: str | None = None) -> str | None:
    """Detect or validate platform name from input or URL."""
    url = clean_url(url)
    if platform and platform.strip():
        p = platform.strip().lower()
        if p in SCRAPER_MAP:
            return p
    url_lower = url.lower()
    if "naukri.com" in url_lower:
        return "naukri"
    elif "indeed.com" in url_lower:
        return "indeed"
    elif "instahyre.com" in url_lower:
        return "instahyre"
    elif "linkedin.com" in url_lower:
        return "linkedin"
    elif "wellfound.com" in url_lower:
        return "wellfound"
    elif "cutshort.io" in url_lower:
        return "cutshort"
    return platform.strip().lower() if platform else None



def format_job_details(platform: str, details: dict[str, Any]) -> str:
    """Format job details dictionary into the standard text output format."""
    lines = [
        "=" * 60,
        f"JOB DETAILS ({platform.upper()})",
        "=" * 60,
    ]
    if details.get("title"):
        lines.append(f"Title:       {details['title']}")
    if details.get("company"):
        lines.append(f"Company:     {details['company']}")
    if details.get("location"):
        lines.append(f"Location:    {details['location']}")
    if details.get("salary_range"):
        lines.append(f"Salary:      {details['salary_range']}")
    if details.get("key_skills"):
        lines.append(f"Key Skills:  {', '.join(details['key_skills'])}")
    lines.append("-" * 60)
    lines.append("DESCRIPTION:")
    lines.append("-" * 60)
    desc = details.get("description")
    if desc:
        lines.append(desc)
    else:
        lines.append("No description extracted or description element not found.")
    lines.append("=" * 60)
    return "\n".join(lines)


async def fetch_job_details(platform: str, url: str) -> dict[str, Any] | None:
    """Scrape details dictionary for a job URL and platform."""
    url = clean_url(url)
    platform_key = detect_platform(url, platform)
    if not platform_key or platform_key not in SCRAPER_MAP:
        supported = ", ".join(SCRAPER_MAP.keys())
        raise ValueError(f"Unsupported platform: '{platform}'. Supported platforms: {supported}")

    scraper = SCRAPER_MAP[platform_key]()
    cookie_file = COOKIES_DIR / f"{platform_key}.json"
    cookies = json.loads(cookie_file.read_text()) if cookie_file.exists() else []

    async def fetch(page):
        return await scraper.get_job_details(page, url)

    return await scrape_with_cookies(url, fetch, cookies)


async def get_job_description_formatted(url: str, platform: str | None = None) -> str:
    """Fetch and format job details as standard text output."""
    url = clean_url(url)
    platform_key = detect_platform(url, platform)
    if not platform_key or platform_key not in SCRAPER_MAP:
        supported = ", ".join(SCRAPER_MAP.keys())
        raise ValueError(f"Unsupported platform: '{platform}'. Supported platforms: {supported}")

    details = await fetch_job_details(platform_key, url)
    if not details:
        raise RuntimeError(f"Failed to fetch job details from {platform_key}.")

    return format_job_details(platform_key, details)

