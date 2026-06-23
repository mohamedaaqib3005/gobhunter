from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class NaukriScraper(BaseScraper):
    name = "naukri"
    login_url = "https://www.naukri.com/python-backend-developer-jobs-in-bangalore"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            url = f"https://www.naukri.com/{query.replace(' ', '-')}-jobs-in-{loc.replace(' ', '-')}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                continue
            await random_delay(2, 4)
            await human_like_scroll(page)
            all_jobs.extend(await self._parse_listing(page))
        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []
        cards = page.locator("div.srp-jobtuple-wrapper")
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)
                title_el = card.locator("a.title").first
                title = await title_el.inner_text()
                url = await title_el.get_attribute("href") or ""

                company_el = card.locator("a.comp-name, a[class*='compName'], a[class*='subTitle']").first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                loc_el = card.locator("span[class*='loc'], li[class*='location']").first
                location = await loc_el.inner_text() if await loc_el.count() > 0 else "Bangalore/Remote"

                salary_el = card.locator("span[class*='sal'], li[class*='salary']").first
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
