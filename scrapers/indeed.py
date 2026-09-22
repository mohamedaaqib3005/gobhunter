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

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description for a given Indeed job URL."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Navigate to an Indeed job page and extract full description along with job details."""
        if not url:
            return {}

        if not url.startswith("http"):
            url = f"https://in.indeed.com{url if url.startswith('/') else '/' + url}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await random_delay(1, 2)

            # Wait for description container if present
            desc_locator = page.locator(
                ".simple-job-description-html, [class*='simple-job-description-html'], #jobDescriptionText"
            ).first

            description = None
            try:
                await desc_locator.wait_for(state="attached", timeout=8000)
            except Exception:
                pass

            # Extract and stitch all contents inside .simple-job-description-html child elements
            description = await page.evaluate("""
                () => {
                    const container = document.querySelector('.simple-job-description-html, [class*="simple-job-description-html"]');
                    if (container) {
                        const directChildren = Array.from(container.children);
                        if (directChildren.length > 0) {
                            const stitched = directChildren.map(el => {
                                if (el.tagName === 'UL' || el.tagName === 'OL') {
                                    const items = Array.from(el.querySelectorAll('li'))
                                        .map(li => `• ${li.innerText.trim()}`)
                                        .filter(t => t !== '•');
                                    return items.join('\\n');
                                }
                                return el.innerText.trim();
                            }).filter(t => t.length > 0).join('\\n\\n');

                            if (stitched.trim()) {
                                return stitched.trim();
                            }
                        }

                        if (container.innerText && container.innerText.trim()) {
                            return container.innerText.trim();
                        }
                    }

                    // Fallback to standard selector if simple-job-description-html is not present
                    const fallbackEl = document.querySelector('#jobDescriptionText, [data-testid="jobDescriptionText"], .jobsearch-jobDescriptionText, .jobsearch-JobComponent-description');
                    return fallbackEl ? fallbackEl.innerText.trim() : null;
                }
            """)

            # Title
            title_el = page.locator("h1[data-testid='jobsearch-JobInfoHeader-title'], h1.jobsearch-JobInfoHeader-title, h1.jobTitle").first
            title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else None

            # Company
            company_el = page.locator("div[data-testid='inlineHeader-companyName'], div.jobsearch-CompanyInfoContainer, span.companyName").first
            company = (await company_el.inner_text()).strip() if await company_el.count() > 0 else None

            # Location
            loc_el = page.locator("div[data-testid='inlineHeader-companyLocation'], div[data-testid='job-location'], div.companyLocation").first
            location = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else None

            # Salary / Job Type
            salary_el = page.locator("#salaryInfoAndJobType, div[data-testid='jobsearch-OtherJobDetailsContainer'], div#jobDetailsSection").first
            salary = (await salary_el.inner_text()).strip() if await salary_el.count() > 0 else None

            return {
                "title": title,
                "company": company,
                "location": location,
                "salary_range": salary,
                "description": description,
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}

