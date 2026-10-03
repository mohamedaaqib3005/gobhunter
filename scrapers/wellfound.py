import asyncio
from html import unescape
import json
import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


def _clean_description(text_or_html: str) -> str:
    """Clean and normalize job description text."""
    if not text_or_html:
        return ""
    if "<" in text_or_html and ">" in text_or_html:
        text = re.sub(r"<li[^>]*>", "• ", text_or_html, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<(p|div|h[1-6]|ul|ol|tr)[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</(p|div|h[1-6]|ul|ol|tr)>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
    else:
        text = text_or_html
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class WellfoundScraper(BaseScraper):
    name = "wellfound"
    login_url = "https://wellfound.com/jobs"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        """Search jobs on Wellfound by intercepting GraphQL responses and Next.js Apollo cache."""
        page.set_default_timeout(30000)
        all_jobs = []
        seen_urls = set()

        # Intercept GraphQL JobSearchResultsX responses
        captured_results = []

        async def on_response(response):
            if "graphql" in response.url:
                try:
                    data = await response.json()
                    talent = data.get("data", {}).get("talent", {})
                    if "jobSearchResults" in talent:
                        captured_results.append(talent["jobSearchResults"])
                except Exception:
                    pass

        page.on("response", on_response)

        for loc in locations:
            url = f"https://wellfound.com/jobs?q={query.replace(' ', '+')}&l={loc.replace(' ', '+')}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    continue

            await random_delay(1, 2)
            await human_like_scroll(page)
            await random_delay(1, 2)

            # 1. Parse captured GraphQL results
            for search_res in captured_results:
                edges = search_res.get("startups", {}).get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    startup = node.get("promotedStartup") or node.get("startup") or node
                    s_name = startup.get("name") or "Unknown"
                    s_slug = startup.get("slug") or ""
                    listings = startup.get("highlightedJobListings", []) or startup.get("jobListings", [])

                    for l in listings:
                        j_id = l.get("id")
                        j_slug = l.get("slug")
                        if s_slug and j_slug:
                            j_url = f"https://wellfound.com/company/{s_slug}/jobs/{j_id}-{j_slug}"
                        elif j_slug:
                            j_url = f"https://wellfound.com/jobs/{j_id}-{j_slug}"
                        elif j_id:
                            j_url = f"https://wellfound.com/jobs/{j_id}"
                        else:
                            continue

                        if j_url in seen_urls:
                            continue
                        seen_urls.add(j_url)

                        locs = l.get("locationNames") or [loc]
                        loc_str = ", ".join(locs) if isinstance(locs, list) else str(locs)
                        raw_desc = l.get("description") or ""

                        all_jobs.append({
                            "title": l.get("title", "").strip(),
                            "company": s_name.strip(),
                            "location": loc_str.strip() or "Remote",
                            "source": self.name,
                            "source_url": j_url,
                            "salary_range": l.get("compensation"),
                            "description": _clean_description(raw_desc) if raw_desc else None,
                        })

            # 2. Fallback to DOM / Next Data if GraphQL didn't yield
            if not all_jobs:
                dom_jobs = await self._parse_listing_fallback(page)
                for j in dom_jobs:
                    u = j.get("source_url")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        all_jobs.append(j)

        return all_jobs

    async def _parse_listing_fallback(self, page: Page) -> list[dict]:
        """Fallback parser extracting from Next.js state or DOM."""
        jobs_data = await page.evaluate("""
            () => {
                const results = [];
                // 1. Try __NEXT_DATA__
                const nextEl = document.getElementById('__NEXT_DATA__');
                if (nextEl) {
                    try {
                        const d = JSON.parse(nextEl.innerText);
                        const apollo = d.props?.pageProps?.apolloState?.data || {};
                        const listings = Object.keys(apollo).filter(k => apollo[k]?.__typename === 'JobListing').map(k => apollo[k]);
                        for (const l of listings) {
                            let company = 'Unknown';
                            if (l.startup?.__ref && apollo[l.startup.__ref]) {
                                company = apollo[l.startup.__ref].name || 'Unknown';
                            }
                            results.push({
                                title: l.title || '',
                                company: company,
                                location: (l.locationNames || []).join(', ') || 'Remote',
                                url: l.slug ? `https://wellfound.com/jobs/${l.id}-${l.slug}` : `https://wellfound.com/jobs/${l.id}`,
                                salary: l.compensation || null,
                                description: l.description || null
                            });
                        }
                    } catch(e) {}
                }

                // 2. Try DOM cards if needed
                if (results.length === 0) {
                    const cards = document.querySelectorAll('div[data-test="StartupResult"], div[class*="styles__startup"], div[class*="styles__jobListing"]');
                    for (const card of cards) {
                        const titleEl = card.querySelector('a[href*="/jobs/"], h3, h4');
                        const companyEl = card.querySelector('h2, a[href*="/company/"]');
                        const locEl = card.querySelector('span[class*="location"]');
                        const salaryEl = card.querySelector('span[class*="compensation"], span[class*="salary"]');
                        const linkEl = card.querySelector('a[href*="/jobs/"]');

                        if (titleEl && linkEl) {
                            let url = linkEl.getAttribute('href') || '';
                            if (url && !url.startsWith('http')) url = 'https://wellfound.com' + url;
                            results.push({
                                title: titleEl.innerText.trim(),
                                company: companyEl ? companyEl.innerText.trim() : 'Unknown',
                                location: locEl ? locEl.innerText.trim() : 'Remote',
                                url: url,
                                salary: salaryEl ? salaryEl.innerText.trim() : null,
                                description: null
                            });
                        }
                    }
                }
                return results;
            }
        """)

        return [
            {
                "title": item["title"].strip(),
                "company": item["company"].strip(),
                "location": item["location"].strip(),
                "source": self.name,
                "source_url": item["url"],
                "salary_range": item.get("salary"),
                "description": _clean_description(item.get("description", "")) if item.get("description") else None,
            }
            for item in jobs_data
            if item.get("title") and item.get("url")
        ]

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description for a given Wellfound job URL."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Extract full details and description from a Wellfound job page."""
        if not url:
            return {}

        if not url.startswith("http"):
            url = f"https://wellfound.com{url if url.startswith('/') else '/' + url}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            # Extract from __NEXT_DATA__ Apollo cache
            job_data = await page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (el) {
                        try {
                            const d = JSON.parse(el.innerText);
                            const apollo = d.props?.pageProps?.apolloState?.data || {};

                            const listings = Object.keys(apollo)
                                .filter(k => apollo[k]?.__typename === 'JobListing' && (apollo[k]?.description || apollo[k]?.descriptionHtml))
                                .map(k => apollo[k]);

                            let primaryJob = listings[0];
                            const m = window.location.pathname.match(/\\b(\\d{6,})\\b/);
                            if (m) {
                                const matched = listings.find(l => String(l.id) === m[1]);
                                if (matched) primaryJob = matched;
                            }

                            if (primaryJob) {
                                let startup = null;
                                if (primaryJob.startup?.__ref && apollo[primaryJob.startup.__ref]) {
                                    startup = apollo[primaryJob.startup.__ref];
                                } else {
                                    const startups = Object.keys(apollo).filter(k => apollo[k]?.__typename === 'Startup').map(k => apollo[k]);
                                    if (startups.length > 0) startup = startups[0];
                                }

                                const skills = (primaryJob.skills || []).map(s => {
                                    if (s?.__ref && apollo[s.__ref]) return apollo[s.__ref].name;
                                    return s.name || s;
                                }).filter(Boolean);

                                return {
                                    title: primaryJob.title,
                                    company: startup ? startup.name : null,
                                    location: (primaryJob.locationNames || []).join(', '),
                                    salary: primaryJob.compensation,
                                    skills: skills,
                                    description: primaryJob.description || primaryJob.descriptionHtml,
                                    source: 'next_data'
                                };
                            }
                        } catch(e) {}
                    }

                    // Fallback to DOM elements
                    const titleEl = document.querySelector('h1, h2.title, [class*="jobTitle"]');
                    const companyEl = document.querySelector('a[href*="/company/"], [class*="companyName"]');
                    const locEl = document.querySelector('[class*="location"], [class*="Location"]');
                    const descEl = document.querySelector('div[class*="description"], div[class*="Description"], #job-description');

                    return {
                        title: titleEl ? titleEl.innerText.trim() : null,
                        company: companyEl ? companyEl.innerText.trim() : 'Unknown',
                        location: locEl ? locEl.innerText.trim() : 'Remote',
                        salary: null,
                        skills: [],
                        description: descEl ? descEl.innerText.trim() : null,
                        source: 'dom'
                    };
                }
            """)

            raw_desc = job_data.get("description") or ""
            description = _clean_description(raw_desc) if raw_desc else None

            return {
                "title": job_data.get("title"),
                "company": job_data.get("company") or "Unknown",
                "location": job_data.get("location") or "Remote",
                "salary_range": job_data.get("salary"),
                "key_skills": job_data.get("skills") or [],
                "description": description,
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}
