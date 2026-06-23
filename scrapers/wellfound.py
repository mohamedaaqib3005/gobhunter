import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class WellfoundScraper(BaseScraper):
    name = "wellfound"
    login_url = "https://wellfound.com/jobs"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            url = f"https://wellfound.com/jobs?q={query.replace(' ', '+')}&l={loc.replace(' ', '+')}"
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                continue
            await random_delay(3, 5)
            await human_like_scroll(page)
            await random_delay(2, 3)
            all_jobs.extend(await self._parse_listing(page))
        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []

        # Try multiple possible card selectors
        cards = page.locator(
            "a[class*='job'], "
            "div[class*='job-card'], "
            "div[class*='JobCard'], "
            "a[href*='/jobs/']:has(span), "
            "div[class*='styles__card'], "
            "div[class*='card']"
        )
        count = await cards.count()

        if count == 0:
            return jobs

        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)

                title_el = card.locator("span[class*='title'], h3, h4, a[class*='title']").first
                title = await title_el.inner_text() if await title_el.count() > 0 else ""

                if not title:
                    continue

                url = ""
                tag = await card.get_attribute("href") or ""
                if tag:
                    url = tag
                else:
                    link = card.locator("a[href*='/job/']").first
                    url = await link.get_attribute("href") or ""
                if url and not url.startswith("http"):
                    url = "https://wellfound.com" + url

                company_el = card.locator("span[class*='company'], div[class*='company']").first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                loc_el = card.locator("span[class*='location'], div[class*='location']").first
                location = await loc_el.inner_text() if await loc_el.count() > 0 else "Bangalore/Remote"

                jobs.append({
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location.strip(),
                    "source": self.name,
                    "source_url": url,
                })
            except Exception:
                continue

        return jobs
