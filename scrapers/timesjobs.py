import re

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class TimesJobsScraper(BaseScraper):
    name = "timesjobs"
    login_url = "https://www.timesjobs.com/candidate/job-search.html?txtKeywords=python+backend&txtLocation=Bangalore"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        for loc in locations:
            q = query.strip().replace(" ", "+")
            l = loc.strip().replace(" ", "+")
            url = f"https://www.timesjobs.com/candidate/job-search.html?searchType=home&searchType2=By&txtKeywords={q}&txtLocation={l}"
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
        cards = page.locator("div.srp-card")
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)

                title_el = card.locator("h2").first
                title = await title_el.inner_text() if await title_el.count() > 0 else ""

                company_el = card.locator("span.inline-block.whitespace-nowrap").first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                link_el = card.locator("a[href*='/job-detail/']").first
                url = await link_el.get_attribute("href") or ""
                if url and not url.startswith("http"):
                    url = "https://www.timesjobs.com" + url

                location = "Bangalore/Remote"
                loc_el = card.locator("span.float-left").first
                if await loc_el.count() > 0:
                    loc_text = await loc_el.inner_text()
                    loc_text = loc_text.strip().rstrip(",")
                    parts = loc_text.split(",")
                    loc_text = parts[0].strip()
                    if loc_text:
                        location = loc_text

                salary = None
                text = await card.inner_text()
                m = re.search(r"₹\s*[\d,]+[Kk]?\s*(?:-\s*₹\s*[\d,]+[Kk]?)?|[\d]+\s*-\s*[\d]+\s*(?:Lakh|LPA|Lacs|Lac)", text, re.IGNORECASE)
                if m:
                    salary = m.group(0).strip()
                else:
                    salary_spans = card.locator("span.float-left")
                    sc = await salary_spans.count()
                    for j in range(sc):
                        t = (await salary_spans.nth(j).inner_text()).strip()
                        if t.lower() not in ("not disclosed", "") and "yr" not in t.lower() and not any(c in t.lower() for c in ["bengaluru", "bangalore", "mumbai", "pune", "delhi", "hyderabad", "chennai"]):
                            salary = t
                            break

                if not title or not url:
                    continue

                jobs.append({
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location,
                    "source": self.name,
                    "source_url": url,
                    "salary_range": salary,
                })
            except Exception:
                continue
        return jobs
