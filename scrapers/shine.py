import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class ShineScraper(BaseScraper):
    name = "shine"
    login_url = "https://www.shine.com/job-search/python-backend-developer-jobs-in-bangalore"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            q = query.lower().strip().replace(" ", "-")
            l = loc.lower().strip().replace(" ", "-")
            url = f"https://www.shine.com/job-search/{q}-jobs-in-{l}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                continue
            await random_delay(3, 5)
            await human_like_scroll(page)
            await random_delay(2, 3)
            all_jobs.extend(await self._parse_listing(page))
        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []
        cards = page.locator("div.jdbigCard")
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)

                title_el = card.locator("h3 a").first
                title = await title_el.inner_text() if await title_el.count() > 0 else ""
                url = await title_el.get_attribute("href") or "" if await title_el.count() > 0 else ""

                company_el = card.locator("span[class*='bigCardTopTitleName']").first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                loc_el = card.locator("div[class*='bigCardCenterListLoc'], div[class*='bigCardLocation']").first
                location = "Bangalore/Remote"
                if await loc_el.count() > 0:
                    raw_loc = await loc_el.inner_text()
                    raw_loc = raw_loc.strip().split("\n")[0].split(",")[0].strip()
                    if raw_loc:
                        location = raw_loc

                salary = None
                exp_sal_els = card.locator("div[class*='bigCardExperience']")
                sc = await exp_sal_els.count()
                for j in range(sc):
                    t = await exp_sal_els.nth(j).inner_text()
                    t = t.strip()
                    if t and re.search(r"\d+\s*-\s*\d+\s*L\w*", t, re.IGNORECASE):
                        salary = t
                        break

                if not title or not url:
                    continue

                jobs.append({
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location.strip(),
                    "source": self.name,
                    "source_url": url,
                    "salary_range": salary,
                })
            except Exception:
                continue
        return jobs
