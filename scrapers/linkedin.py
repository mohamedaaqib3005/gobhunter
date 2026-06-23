import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


CITIES = {
    "Bengaluru", "Bangalore", "Mumbai", "Pune", "Delhi", "Gurgaon",
    "Gurugram", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad",
    "Noida", "Jaipur", "Kochi", "Cochin", "Coimbatore", "Indore",
    "Chandigarh", "Bhubaneswar", "Nashik", "Remote",
}


class LinkedInScraper(BaseScraper):
    name = "linkedin"
    login_url = "https://www.linkedin.com/jobs/search/?keywords=python+backend&location=Bangalore"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            url = f"https://www.linkedin.com/jobs/search/?keywords={query.replace(' ', '+')}&location={loc.replace(' ', '+')}&geoId=&distance=25"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                continue
            await page.wait_for_timeout(4000)
            await human_like_scroll(page)
            await random_delay(2, 3)
            all_jobs.extend(await self._parse_listing(page))
        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []

        result = await page.evaluate("""
            () => {
                const results = [];

                // Try multiple known LinkedIn card selectors
                const selectors = [
                    'li.jobs-search-results__list-item',
                    'li[class*="jobs-search-results"]',
                    'div[class*="job-card-container"]',
                    'a[class*="job-card-list"]',
                ];

                let cards = [];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        cards = Array.from(els);
                        break;
                    }
                }

                // Fallback: find job-related links
                if (cards.length === 0) {
                    const links = document.querySelectorAll('a[href*="/jobs/view/"]');
                    for (const a of links) {
                        const parentCard = a.closest('li, div[class]');
                        if (parentCard) cards.push(parentCard);
                    }
                    if (cards.length === 0) cards = Array.from(links);
                }

                for (let i = 0; i < Math.min(cards.length, 30); i++) {
                    const card = cards[i];
                    const html = card.innerHTML || card.outerHTML || '';

                    // Title
                    let title = '';
                    const titleEl = card.querySelector('a[class*="job-card-list__title"], a[class*="job-title"], a[class*="job-card"], strong a, a strong, h3 a, a[href*="/jobs/view/"]');
                    if (titleEl) {
                        title = titleEl.textContent.trim();
                    }
                    if (!title) {
                        const allLinks = card.querySelectorAll('a');
                        for (const a of allLinks) {
                            const t = a.textContent.trim();
                            if (t && t.length > 5 && t.length < 100) {
                                title = t;
                                break;
                            }
                        }
                    }

                    // URL
                    let url = '';
                    const urlEl = card.querySelector('a[href*="/jobs/view/"]') || card.querySelector('a[class*="job-card"]');
                    if (urlEl) {
                        url = urlEl.getAttribute('href') || '';
                        if (url && !url.startsWith('http')) {
                            url = 'https://www.linkedin.com' + url;
                        }
                        // Clean LinkedIn tracking params
                        const qIndex = url.indexOf('?');
                        if (qIndex > 0) url = url.substring(0, qIndex);
                    }

                    // Company
                    let company = 'Unknown';
                    const companyEl = card.querySelector('a[class*="company-name"], span[class*="company-name"], span[class*="company"], img[alt]');
                    if (companyEl) {
                        if (companyEl.tagName === 'IMG') {
                            company = companyEl.getAttribute('alt') || 'Unknown';
                        } else {
                            company = companyEl.textContent.trim();
                        }
                    }

                    // Location
                    let location = 'Bangalore/Remote';
                    const locEl = card.querySelector('li[class*="metadata-item"], span[class*="location"], div[class*="location"]');
                    if (locEl) {
                        location = locEl.textContent.trim();
                    }
                    if (!location || location === 'Bangalore/Remote') {
                        for (const city of ["Bengaluru", "Bangalore", "Remote", "Mumbai", "Pune", "Delhi", "Hyderabad", "Chennai", "Gurgaon", "Noida"]) {
                            if (html.includes(city)) {
                                location = city;
                                break;
                            }
                        }
                    }

                    // Salary
                    let salary = null;
                    const salaryMatch = html.match(/[₹$Rs][\\s]*[\\d,]+[KkLl]?\\s*(?:-\\s*[₹$Rs][\\s]*[\\d,]+[KkLl]?)?/);
                    if (salaryMatch) salary = salaryMatch[0].trim();

                    if (title && url) {
                        results.push({ title, company, location, url, salary });
                    }
                }
                return results;
            }
        """)

        for item in result:
            jobs.append({
                "title": item["title"].strip(),
                "company": item["company"].strip() if item["company"] else "Unknown",
                "location": item["location"].strip() if item["location"] else "Bangalore/Remote",
                "source": self.name,
                "source_url": item["url"],
                "salary_range": item["salary"],
            })

        return jobs
