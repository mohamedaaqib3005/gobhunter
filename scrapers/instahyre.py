import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class InstahyreScraper(BaseScraper):
    name = "instahyre"
    login_url = "https://www.instahyre.com/search-jobs/"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            url = f"https://www.instahyre.com/search-jobs?q={query.replace(' ', '+')}&l={loc.replace(' ', '+')}"
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
        cards = page.locator(".opp-list-container > div.employer-block")
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)
                link_el = card.locator("a.row.text-link").first
                url = await link_el.get_attribute("href") or ""
                if not url.startswith("http"):
                    url = "https://www.instahyre.com" + url

                job_name_el = card.locator(".employer-job-name").first
                title_attr = await job_name_el.get_attribute("title") or ""

                parts = title_attr.split(" - ", 1)
                company = parts[0].strip() if len(parts) > 1 else "Unknown"
                title = parts[1].strip() if len(parts) > 1 else title_attr.strip()

                loc_el = card.locator(".employer-locations .info")
                location = "Bangalore/Remote"
                if await loc_el.count() > 0:
                    loc_text = await loc_el.first.inner_text()
                    m = re.search(r"Job available in (.+)", loc_text)
                    if m:
                        location = m.group(1).strip()

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "source": self.name,
                    "source_url": url,
                })
            except Exception:
                continue
        return jobs
