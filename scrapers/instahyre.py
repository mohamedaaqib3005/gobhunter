import asyncio
from html import unescape
import json
import re
import urllib.parse
import urllib.request

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import random_delay


def _clean_html_description(html_content: str) -> str:
    """Convert Instahyre HTML job description to clean formatted text."""
    if not html_content:
        return ""
    text = re.sub(r"<li[^>]*>", "• ", html_content, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(p|div|h[1-6]|ul|ol|tr)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|ul|ol|tr)>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_job_id(url_or_id: str) -> str | None:
    """Extract numeric job ID from an Instahyre URL or raw ID string."""
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()
    if url_or_id.isdigit():
        return url_or_id
    m = re.search(r"job-(\d+)", url_or_id)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)/?$", url_or_id)
    if m:
        return m.group(1)
    return None


class InstahyreScraper(BaseScraper):
    name = "instahyre"
    login_url = "https://www.instahyre.com/search-jobs/"
    api_base = "https://www.instahyre.com/api/v1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.instahyre.com/search-jobs/",
    }

    async def _http_get_json(self, page: Page | None, url: str) -> dict | None:
        """Fetch JSON data from URL using Playwright request API or urllib."""
        if page and hasattr(page, "request"):
            try:
                response = await page.request.get(url, headers=self.headers, timeout=20000)
                if response.ok:
                    return await response.json()
            except Exception:
                pass

        # Fallback to direct async HTTP request
        try:
            def _fetch():
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
                return None

            return await asyncio.to_thread(_fetch)
        except Exception:
            return None

    # The API rejects a comma-joined query with HTTP 400, so each search term
    # is sent as its own request. Verified against the live endpoint:
    #   skills="React Developer,Frontend Developer,..."  -> 400 Bad Request
    #   skills="React Developer"                         -> 200, 35 jobs
    #
    # It also caps each response at 35 regardless of the `limit` asked for,
    # so volume comes from paging with `offset`, and it ignores `location`
    # entirely: React in Bangalore, in Bengaluru and with no location all
    # return the same total_count of 1634. Looping over locations therefore
    # fired three identical requests; it now loops over search terms instead.
    PAGE_SIZE = 35
    MAX_PAGES = 3

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        """Search jobs using Instahyre's public REST API, one term at a time."""
        all_jobs = []
        seen_urls = set()

        terms = [t.strip() for t in str(query).split(",") if t.strip()]
        if not terms:
            terms = [str(query).strip()]
        loc = locations[0] if locations else "Bangalore"

        requests = [(t, i) for t in terms for i in range(self.MAX_PAGES)]
        exhausted: set[str] = set()

        for term, page_index in requests:
            if term in exhausted:
                continue
            params = {
                "skills": term,
                "location": loc,
                "search": "true",
                "offset": page_index * self.PAGE_SIZE,
                "limit": self.PAGE_SIZE,
            }
            api_url = f"{self.api_base}/job_search?{urllib.parse.urlencode(params)}"
            data = await self._http_get_json(page, api_url)

            # A 400 or an unexpected shape means this term is no good; stop
            # paging it rather than firing the remaining requests.
            if not data or "objects" not in data:
                exhausted.add(term)
                continue
            if not data["objects"]:
                exhausted.add(term)
                continue

            for obj in data.get("objects", []):
                job_id = obj.get("id")
                public_url = obj.get("public_url")
                if not public_url and job_id:
                    public_url = f"https://www.instahyre.com/job-{job_id}/"
                elif public_url and not public_url.startswith("http"):
                    public_url = f"https://www.instahyre.com{public_url}"

                if not public_url or public_url in seen_urls:
                    continue
                seen_urls.add(public_url)

                title = obj.get("title") or obj.get("candidate_title") or ""
                employer = obj.get("employer") or {}
                company = employer.get("company_name") or "Unknown"
                location_str = obj.get("locations") or loc
                key_skills = obj.get("keywords") or []

                all_jobs.append({
                    "title": title,
                    "company": company,
                    "location": location_str,
                    "source": self.name,
                    "source_url": public_url,
                    "key_skills": key_skills,
                })

            await random_delay(0.5, 1.5)

        return all_jobs

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description directly via Instahyre public job API."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Fetch full job details directly using Instahyre API, with DOM fallback."""
        if not url:
            return {}

        job_id = _extract_job_id(url)
        if job_id:
            api_url = f"{self.api_base}/employer_public_jobs/{job_id}"
            data = await self._http_get_json(page, api_url)
            if data and isinstance(data, dict) and data.get("title"):
                title = data.get("title") or data.get("candidate_title")
                company = data.get("hiring_company_name") or data.get("recruiter_company_name")
                raw_locs = data.get("locations")
                if isinstance(raw_locs, list):
                    location = ", ".join(raw_locs)
                else:
                    location = str(raw_locs) if raw_locs else None

                key_skills = data.get("keywords") or []
                raw_description = data.get("description") or ""
                description = _clean_html_description(raw_description)

                workex_min = data.get("workex_min")
                workex_max = data.get("workex_max")
                salary_range = None
                if workex_min is not None or workex_max is not None:
                    salary_range = f"Experience: {workex_min or 0} - {workex_max or 0} yrs"

                return {
                    "title": title,
                    "company": company,
                    "location": location,
                    "salary_range": salary_range,
                    "key_skills": key_skills,
                    "description": description if description else None,
                    "source_url": url,
                    "source": self.name,
                }

        # Fallback to DOM navigation if API extraction fails
        return await self._get_job_details_dom_fallback(page, url)

    async def _get_job_details_dom_fallback(self, page: Page, url: str) -> dict:
        """Fallback DOM-based scraper for edge cases."""
        if not url.startswith("http"):
            url = f"https://www.instahyre.com{url if url.startswith('/') else '/' + url}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await random_delay(1, 2)

            description = await page.evaluate("""
                () => {
                    const selectors = [
                        '.job-description',
                        'div[ng-bind-html*="description"]',
                        '.job-description-content',
                        '#job-description',
                        'div.job-description-block',
                        '.description-content',
                        'div.description'
                    ];

                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText && el.innerText.trim().length > 20) {
                            return el.innerText.trim();
                        }
                    }
                    const bodyEl = document.querySelector('.job-profile-page, .job-details-page, #job-profile');
                    return bodyEl ? bodyEl.innerText.trim() : null;
                }
            """)

            title_el = page.locator("h1.job-title, h1, .employer-job-name, .job-name").first
            title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else None

            company_el = page.locator("span.company-name, a.employer-name, .company-title, h2.employer-name").first
            company = (await company_el.inner_text()).strip() if await company_el.count() > 0 else None

            loc_el = page.locator(".job-locations, .job-location, .location, .employer-locations").first
            location = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else None
            if location:
                location = re.sub(r"^Job available in\s*", "", location, flags=re.IGNORECASE).strip()

            key_skills = await page.evaluate("""
                () => {
                    const skillEls = document.querySelectorAll('ul.tags li, span.tag, .job-skills li, .skills-list li, .skill');
                    return Array.from(skillEls).map(el => el.innerText.trim()).filter(t => t.length > 0);
                }
            """)

            return {
                "title": title,
                "company": company,
                "location": location,
                "salary_range": None,
                "key_skills": key_skills if key_skills else [],
                "description": description,
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}
