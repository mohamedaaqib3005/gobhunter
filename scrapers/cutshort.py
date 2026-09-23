import asyncio
from html import unescape
import json
import re
import urllib.parse
import urllib.request

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


def _clean_html_description(html_content: str) -> str:
    """Convert Cutshort HTML job description to clean formatted text."""
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


def _extract_job_slug(url_or_slug: str) -> str:
    """Extract the job slug from a Cutshort URL."""
    if not url_or_slug:
        return ""
    url_or_slug = url_or_slug.strip()
    m = re.search(r"/job/([^/?#]+)", url_or_slug)
    if m:
        return m.group(1)
    if not url_or_slug.startswith("http") and "/" not in url_or_slug:
        return url_or_slug
    return url_or_slug.rstrip("/").split("/")[-1]


class CutshortScraper(BaseScraper):
    name = "cutshort"
    login_url = "https://cutshort.io/jobs"
    api_base = "https://cutshort.io/backend-api/webpage"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://cutshort.io/jobs",
    }

    def _get_search_slugs(self, query: str, locations: list[str]) -> list[str]:
        """Generate Cutshort webpage job collection slugs based on query and locations."""
        q = query.lower()
        slugs = []

        # Role-based collection slugs
        if "backend" in q or "python" in q or "django" in q or "node" in q or "java" in q or "golang" in q:
            slugs.append("backend-developer-jobs")
        if "frontend" in q or "react" in q or "vue" in q or "angular" in q or "ui" in q:
            slugs.append("frontend-developer-jobs")
        if "devops" in q or "cloud" in q or "infra" in q or "sre" in q:
            slugs.append("devops-jobs")
        if "android" in q:
            slugs.append("android-developer-jobs")
        if "ios" in q:
            slugs.append("ios-developer-jobs")

        if not slugs:
            slugs.append("backend-developer-jobs")

        # Location-based collection slugs
        for loc in locations:
            loc_l = loc.lower()
            if "bangalore" in loc_l or "bengaluru" in loc_l:
                slugs.append("startup-jobs-in-bangalore-bengaluru")
            elif "pune" in loc_l:
                slugs.append("startup-jobs-in-pune")
            elif "delhi" in loc_l or "ncr" in loc_l or "gurgaon" in loc_l or "noida" in loc_l:
                slugs.append("startup-jobs-in-delhi-ncr-gurgaon-noida")
            elif "hyderabad" in loc_l:
                slugs.append("startup-jobs-in-hyderabad")

        slugs.append("startup-jobs")
        return list(dict.fromkeys(slugs))

    async def _fetch_json(self, page: Page | None, url: str) -> dict | None:
        """Fetch JSON directly from Cutshort backend API or via Playwright request."""
        if page and hasattr(page, "request"):
            try:
                resp = await page.request.get(url, headers=self.headers, timeout=15000)
                if resp.ok:
                    return await resp.json()
            except Exception:
                pass

        loop = asyncio.get_event_loop()
        try:
            def _req():
                r = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(r, timeout=15) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
                return None
            return await loop.run_in_executor(None, _req)
        except Exception:
            return None

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        """Search jobs via Cutshort backend collection APIs."""
        all_jobs = []
        seen_urls = set()
        slugs = self._get_search_slugs(query, locations)

        for slug in slugs:
            api_url = f"{self.api_base}/jobs/{slug}"
            data = await self._fetch_json(page, api_url)
            jobs_list = []
            if data and data.get("success") and "data" in data:
                jobs_list = data["data"].get("pageData", {}).get("jobs", [])

            for j in jobs_list:
                url = j.get("publicUrl")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = j.get("headline", "").strip()
                company_details = j.get("companyDetails") or {}
                company_id = j.get("companyId") or {}
                company = (company_details.get("name") or company_id.get("name") or "Unknown").strip()

                locs = j.get("locations") or []
                loc_str = ", ".join(locs) if isinstance(locs, list) else str(locs)

                salary = j.get("salaryRangeText")
                if not salary and j.get("salaryRange"):
                    sr = j["salaryRange"]
                    if isinstance(sr, dict):
                        if sr.get("min") and sr.get("max") and not sr.get("hideSalary"):
                            curr = sr.get("currency", "INR")
                            salary = f"{curr} {sr['min']} - {sr['max']}"
                    elif isinstance(sr, str):
                        salary = sr

                raw_desc = j.get("description") or j.get("sanitizedComment") or ""
                desc = _clean_html_description(raw_desc) if raw_desc else None

                skills = j.get("allSkills") or []
                if not isinstance(skills, list) and isinstance(j.get("allSkillsObj"), dict):
                    skills = list(j["allSkillsObj"].values())

                all_jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc_str or "Bangalore/Remote",
                    "source": self.name,
                    "source_url": url,
                    "salary_range": salary,
                    "key_skills": skills if isinstance(skills, list) else [],
                    "description": desc,
                })

            await random_delay(0.5, 1.0)
            if len(all_jobs) >= 50:
                break

        return all_jobs

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full job description from Cutshort."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Get complete job details via Cutshort backend API or Next.js state."""
        if not url:
            return {}

        slug = _extract_job_slug(url)

        # 1. Try direct REST backend API
        if slug:
            api_url = f"{self.api_base}/job/{slug}"
            data = await self._fetch_json(page, api_url)
            if data and isinstance(data, dict) and data.get("success") and "data" in data:
                d_obj = data["data"]
                pd = d_obj.get("pageData", {}) if isinstance(d_obj, dict) else {}
                if pd.get("headline"):
                    title = pd.get("headline", "").strip()
                    company_details = pd.get("companyDetails") or {}
                    company_id = pd.get("companyId") or {}
                    company = (company_details.get("name") or company_id.get("name") or "Unknown").strip()

                    locs = pd.get("locations") or []
                    loc_str = ", ".join(locs) if isinstance(locs, list) else str(locs)

                    salary = pd.get("salaryRangeText")
                    if not salary and pd.get("salaryRange"):
                        sr = pd["salaryRange"]
                        if isinstance(sr, dict):
                            if sr.get("min") and sr.get("max") and not sr.get("hideSalary"):
                                curr = sr.get("currency", "INR")
                                salary = f"{curr} {sr['min']} - {sr['max']}"
                        elif isinstance(sr, str):
                            salary = sr

                    raw_desc = pd.get("sanitizedComment") or pd.get("description") or ""
                    desc = _clean_html_description(raw_desc) if raw_desc else None

                    skills = pd.get("allSkills") or []
                    if not isinstance(skills, list) and isinstance(pd.get("allSkillsObj"), dict):
                        skills = list(pd["allSkillsObj"].values())

                    return {
                        "title": title,
                        "company": company,
                        "location": loc_str or "Bangalore/Remote",
                        "salary_range": salary,
                        "key_skills": skills if isinstance(skills, list) else [],
                        "description": desc,
                        "source_url": pd.get("publicUrl") or url,
                        "source": self.name,
                    }

        # 2. Fallback to Browser page evaluation
        return await self._get_job_details_dom_fallback(page, url)

    async def _get_job_details_dom_fallback(self, page: Page, url: str) -> dict:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            job_data = await page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (el) {
                        try {
                            const d = JSON.parse(el.innerText);
                            const queries = d.props?.pageProps?.dehydratedState?.queries || [];
                            for (const q of queries) {
                                const pd = q.state?.data?.data?.pageData;
                                if (pd && pd.headline) {
                                    return {
                                        title: pd.headline,
                                        company: pd.companyDetails?.name || pd.companyId?.name || 'Unknown',
                                        location: Array.isArray(pd.locations) ? pd.locations.join(', ') : (pd.locations || ''),
                                        salary: pd.salaryRangeText || null,
                                        skills: pd.allSkills || [],
                                        description: pd.sanitizedComment || pd.description || null,
                                        source: 'next_data'
                                    };
                                }
                            }
                        } catch(e) {}
                    }

                    // DOM fallback
                    const title = document.querySelector('h1')?.innerText.trim();
                    const company = document.querySelector('a[href*="/company/"], h2')?.innerText.trim();
                    const desc = document.querySelector('div[class*="description"], div[class*="Description"]')?.innerText.trim();
                    return { title, company, description: desc, source: 'dom' };
                }
            """)

            raw_desc = job_data.get("description") or ""
            desc = _clean_html_description(raw_desc) if raw_desc else None

            return {
                "title": job_data.get("title"),
                "company": job_data.get("company") or "Unknown",
                "location": job_data.get("location") or "Bangalore/Remote",
                "salary_range": job_data.get("salary"),
                "key_skills": job_data.get("skills") or [],
                "description": desc,
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}
