from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class IndeedScraper(BaseScraper):
    name = "indeed"
    login_url = "https://in.indeed.com/jobs?q=python&l=Bangalore"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        for loc in locations:
            url = f"https://in.indeed.com/jobs?q={query.replace(' ', '+')}&l={loc.replace(' ', '+')}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                continue
            await random_delay(2, 4)
            await human_like_scroll(page)
            try:
                jobs = await self._parse_listing(page)
                if jobs:
                    return jobs
            except Exception:
                continue
        return []

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []
        cards = page.locator("table.mainContentTable")
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)
                title_el = card.locator("h2.jobTitle a, h3.jobTitle a, a.jcs-JobTitle").first
                title = await title_el.inner_text()
                url = await title_el.get_attribute("href") or ""
                if url and not url.startswith("http"):
                    url = "https://in.indeed.com" + url

                company_el = card.locator("span[data-testid='company-name'], span.companyName").first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                loc_el = card.locator("div[data-testid='text-location'], div[data-testid='job-location'], div.companyLocation").first
                location = await loc_el.inner_text() if await loc_el.count() > 0 else "Bangalore/Remote"

                salary_el = card.locator("div.salary-snippet, span[data-testid='job-salary'], div.css-1f4s1vp").first
                salary = await salary_el.inner_text() if await salary_el.count() > 0 else None

                jobs.append({
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location.strip(),
                    "source": self.name,
                    "source_url": url,
                    "salary_range": salary.strip() if salary else None,
                })
            except Exception:
                continue
        return jobs
