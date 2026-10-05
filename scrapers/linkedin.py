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
    """Convert HTML job description to clean formatted text."""
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


def _clean_job_url(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://www.linkedin.com" + url
    q_idx = url.find("?")
    if q_idx > 0:
        url = url[:q_idx]
    return url


def _extract_job_id(url: str) -> str | None:
    if not url:
        return None
    url = str(url).strip()
    if url.isdigit():
        return url
    m = re.search(r"(\d{8,})", url)
    if m:
        return m.group(1)
    return None


class LinkedInScraper(BaseScraper):
    name = "linkedin"
    login_url = "https://www.linkedin.com/jobs"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        all_jobs = []
        seen_urls = set()

        for loc in locations:
            url = f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote_plus(query)}&location={urllib.parse.quote_plus(loc)}&geoId=&distance=25"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                await human_like_scroll(page)
                await random_delay(1, 2)
            except Exception:
                pass

            parsed = await self._parse_listing(page)
            for j in parsed:
                u = j.get("source_url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_jobs.append(j)

        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        cards_data = await page.evaluate("""
            () => {
                const results = [];
                const cards = document.querySelectorAll(
                    'div.base-card, li.jobs-search-results__list-item, div.job-card-container, div[data-job-id]'
                );

                for (const card of cards) {
                    // Title
                    let title = '';
                    const titleEl = card.querySelector(
                        'h3.base-search-card__title, a.job-card-list__title, a.job-card-container__link, .job-card-list__title--link, h3, a[href*="/jobs/view/"]'
                    );
                    if (titleEl) {
                        title = titleEl.innerText.trim();
                    }

                    // Link
                    let url = '';
                    const linkEl = card.querySelector(
                        'a.base-card__full-link, a.job-card-list__title, a.job-card-container__link, a[href*="/jobs/view/"]'
                    );
                    if (linkEl) {
                        url = linkEl.getAttribute('href') || '';
                        if (url && !url.startsWith('http')) {
                            url = 'https://www.linkedin.com' + url;
                        }
                        const qIndex = url.indexOf('?');
                        if (qIndex > 0) {
                            url = url.substring(0, qIndex);
                        }
                    }

                    // Company
                    let company = 'Unknown';
                    const companyEl = card.querySelector(
                        'h4.base-search-card__subtitle, a.job-card-container__company-name, span.job-card-container__primary-description, .job-card-container__company-name, [data-tracking-control-name*="subtitle"]'
                    );
                    if (companyEl) {
                        company = companyEl.innerText.trim();
                    } else if (url) {
                        const m = url.match(/-at-([a-zA-Z0-9-]+)-\d+/);
                        if (m) {
                            company = m[1].replace(/-/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                        }
                    }

                    // Location
                    let location = 'Bangalore/Remote';
                    const locEl = card.querySelector(
                        'span.job-search-card__location, ul.job-card-container__metadata-wrapper li, .job-card-container__metadata-item'
                    );
                    if (locEl) {
                        location = locEl.innerText.trim();
                    }

                    // Salary / metadata
                    let salary = null;
                    const salaryEl = card.querySelector('.job-search-card__salary-info, .job-card-container__metadata-item--salary');
                    if (salaryEl) {
                        salary = salaryEl.innerText.trim();
                    }

                    if (title && url) {
                        results.push({ title, company, location, url, salary });
                    }
                }
                return results;
            }
        """)

        jobs = []
        for item in cards_data:
            jobs.append({
                "title": item["title"].strip(),
                "company": item["company"].strip() if item["company"] else "Unknown",
                "location": item["location"].strip() if item["location"] else "Bangalore/Remote",
                "source": self.name,
                "source_url": _clean_job_url(item["url"]),
                "salary_range": item.get("salary"),
            })
        return jobs

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description for a LinkedIn job posting."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Fetch full job details from LinkedIn via guest endpoint or DOM scraping."""
        if not url:
            return {}

        clean_url = _clean_job_url(url)
        job_id = _extract_job_id(clean_url)

        # 1. Try fast guest jobPosting endpoint
        if job_id:
            api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
            try:
                def _fetch():
                    req = urllib.request.Request(api_url, headers=self.headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status == 200:
                            return resp.read().decode("utf-8")
                    return None

                html = await asyncio.to_thread(_fetch)
                if html:
                    t_match = re.search(r'<h[12][^>]*class=[\"\'][^\"\']*(?:top-card-layout__title|topcard__title)[^\"\']*[\"\'][^>]*>(.*?)</h[12]>', html, re.DOTALL)
                    title = re.sub(r'<[^>]+>', '', t_match.group(1)).strip() if t_match else None

                    c_match = re.search(r'<a[^>]*class=[\"\'][^\"\']*(?:topcard__org-name-link|topcard__flavor--black-link)[^\"\']*[\"\'][^>]*>(.*?)</a>', html, re.DOTALL)
                    company = re.sub(r'<[^>]+>', '', c_match.group(1)).strip() if c_match else None

                    l_match = re.search(r'<span[^>]*class=[\"\'][^\"\']*topcard__flavor--bullet[^\"\']*[\"\'][^>]*>(.*?)</span>', html, re.DOTALL)
                    location = re.sub(r'<[^>]+>', '', l_match.group(1)).strip() if l_match else None

                    desc_match = re.search(r'<div[^>]*class=[\"\'][^\"\']*(?:show-more-less-html__markup|description__text)[^\"\']*[\"\'][^>]*>(.*?)</div>', html, re.DOTALL)
                    raw_desc = desc_match.group(1) if desc_match else None
                    description = _clean_html_description(raw_desc) if raw_desc else None

                    if title and description:
                        return {
                            "title": title,
                            "company": company or "Unknown",
                            "location": location or "Bangalore/Remote",
                            "salary_range": None,
                            "key_skills": [],
                            "description": description,
                            "source_url": clean_url,
                            "source": self.name,
                        }
            except Exception:
                pass

        # 2. Fallback to Browser DOM scraping with class selector matching & stitching
        return await self._get_job_details_dom(page, clean_url)

    async def _get_job_details_dom(self, page: Page, url: str) -> dict:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            # Click 'Show more' button if present
            show_more = page.locator("button[aria-label*='more'], button.show-more-less-html__button, button.show-more-less-button").first
            if await show_more.count() > 0 and await show_more.is_visible():
                try:
                    await show_more.click()
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

            data = await page.evaluate("""
                () => {
                    // Title
                    const titleSelectors = [
                        'h1.top-card-layout__title',
                        'h1.topcard__title',
                        'h1.job-details-jobs-unified-top-card__job-title',
                        '.jobs-unified-top-card__job-title',
                        'h1'
                    ];
                    let title = null;
                    for (const sel of titleSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim()) {
                            title = el.innerText.trim();
                            break;
                        }
                    }

                    // Company
                    const compSelectors = [
                        'a.topcard__flavor--black-link',
                        'a.topcard__org-name-link',
                        '.job-details-jobs-unified-top-card__company-name a',
                        '.job-details-jobs-unified-top-card__company-name',
                        '.jobs-unified-top-card__company-name a',
                        '.jobs-unified-top-card__company-name',
                        'a[data-tracking-control-name*="company_name"]'
                    ];
                    let company = null;
                    for (const sel of compSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim()) {
                            company = el.innerText.trim();
                            break;
                        }
                    }

                    // Location
                    const locSelectors = [
                        'span.topcard__flavor--bullet',
                        'span.topcard__flavor:not(.topcard__flavor--black-link)',
                        '.job-details-jobs-unified-top-card__bullet',
                        '.jobs-unified-top-card__bullet',
                        '.job-details-jobs-unified-top-card__workplace-type'
                    ];
                    let location = null;
                    for (const sel of locSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim()) {
                            location = el.innerText.trim();
                            break;
                        }
                    }

                    // Description stitching
                    const descSelectors = [
                        '.show-more-less-html__markup',
                        '#job-details',
                        '.jobs-description__content',
                        '.jobs-box__html-content',
                        '.jobs-description-content__text',
                        'article.jobs-description__container',
                        '.description__text'
                    ];

                    let descContainer = null;
                    for (const sel of descSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim().length > 30) {
                            descContainer = el;
                            break;
                        }
                    }

                    let description = null;
                    if (descContainer) {
                        const lines = [];
                        const directChildren = Array.from(descContainer.children);
                        if (directChildren.length > 0) {
                            for (const child of directChildren) {
                                if (child.tagName === 'UL' || child.tagName === 'OL') {
                                    const lis = child.querySelectorAll('li');
                                    for (const li of lis) {
                                        const liText = li.innerText.trim();
                                        if (liText) lines.push('• ' + liText);
                                    }
                                } else {
                                    const t = child.innerText.trim();
                                    if (t) lines.push(t);
                                }
                            }
                            description = lines.join('\\n\\n');
                        }
                        if (!description || description.trim().length < 20) {
                            description = descContainer.innerText.trim();
                        }
                    }

                    return { title, company, location, description };
                }
            """)

            return {
                "title": data.get("title"),
                "company": data.get("company") or "Unknown",
                "location": data.get("location") or "Bangalore/Remote",
                "salary_range": None,
                "key_skills": [],
                "description": data.get("description"),
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}
