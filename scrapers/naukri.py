from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


class NaukriScraper(BaseScraper):
    name = "naukri"
    login_url = "https://www.naukri.com"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(20000)
        all_jobs = []
        for loc in locations:
            url = f"https://www.naukri.com/{query.replace(' ', '-')}-jobs-in-{loc.replace(' ', '-')}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_selector(
                    "div.srp-jobtuple-wrapper, div.cust-job-tuple, div[class*='jobTuple'], article.jobTuple, a.title",
                    timeout=8000,
                )
            except Exception:
                pass
            await random_delay(1, 2)
            await human_like_scroll(page)
            all_jobs.extend(await self._parse_listing(page))
        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []
        cards = page.locator(
            "div.srp-jobtuple-wrapper, div.cust-job-tuple, div[class*='jobTuple'], article.jobTuple, div.tuple"
        )
        count = await cards.count()
        for i in range(min(count, 30)):
            try:
                card = cards.nth(i)
                title_el = card.locator("a.title, a[class*='title']").first
                if await title_el.count() == 0:
                    continue
                title = await title_el.inner_text()
                url = await title_el.get_attribute("href") or ""
                if url and not url.startswith("http"):
                    url = f"https://www.naukri.com{url if url.startswith('/') else '/' + url}"

                company_el = card.locator(
                    "a.comp-name, a[class*='compName'], a[class*='subTitle'], a[class*='comp-name']"
                ).first
                company = await company_el.inner_text() if await company_el.count() > 0 else "Unknown"

                loc_el = card.locator("span[class*='loc'], li[class*='location'], span[class*='locWdth'], span.loc").first
                location = await loc_el.inner_text() if await loc_el.count() > 0 else "Bangalore/Remote"

                salary_el = card.locator("span[class*='sal'], li[class*='salary'], span[class*='salWdth']").first
                salary = await salary_el.inner_text() if await salary_el.count() > 0 else None

                if title and url:
                    jobs.append({
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": location.strip(),
                        "source": self.name,
                        "source_url": url.strip(),
                        "salary_range": salary.strip() if salary else None,
                    })
            except Exception:
                continue
        return jobs

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description for a given Naukri job URL."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Navigate to a Naukri job page and extract full description along with job details."""
        if not url:
            return {}

        if not url.startswith("http"):
            url = f"https://www.naukri.com{url if url.startswith('/') else '/' + url}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await random_delay(2, 3)

            # Wait for description container if present
            desc_locator = page.locator(
                "section.job-desc, div.job-desc, div.dang-inner-html, [class*='dang-inner-html'], [class*='job-desc']"
            ).first

            try:
                await desc_locator.wait_for(state="attached", timeout=8000)
            except Exception:
                pass

            # Extract full job description & stitch contents
            description = await page.evaluate(r"""
                () => {
                    const selectors = [
                        'div.dang-inner-html',
                        '[class*="styles_JDC__dang-inner-html"]',
                        '[class*="dang-inner-html"]',
                        'section.job-desc',
                        'div.job-desc',
                        'section[class*="job-desc"]',
                        'div[class*="job-desc-container"]',
                        'div[class*="styles_job-desc-container"]'
                    ];

                    let container = null;
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText && el.innerText.trim().length > 20) {
                            container = el;
                            break;
                        }
                    }

                    if (container) {
                        const directChildren = Array.from(container.children);
                        if (directChildren.length > 0) {
                            const stitched = directChildren.map(el => {
                                if (el.tagName === 'UL' || el.tagName === 'OL') {
                                    const items = Array.from(el.querySelectorAll('li'))
                                        .map(li => `• ${li.innerText.trim()}`)
                                        .filter(t => t !== '•');
                                    return items.join('\n');
                                }
                                return el.innerText.trim();
                            }).filter(t => t.length > 0).join('\n\n');

                            if (stitched.trim()) {
                                return stitched.trim();
                            }
                        }

                        if (container.innerText && container.innerText.trim()) {
                            return container.innerText.trim();
                        }
                    }

                    return null;
                }
            """)

            # Title
            title_el = page.locator(
                "h1[class*='header-title'], h1.styles_jd-header-title__rZwM1, h1.title, h1.jd-header-title"
            ).first
            title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else None

            # Company
            company_el = page.locator(
                "div[class*='header-comp-name'] a, a[class*='comp-name'], a.comp-name, div[class*='company-name'] a"
            ).first
            company = (await company_el.inner_text()).strip() if await company_el.count() > 0 else None

            # Location
            loc_el = page.locator(
                "span[class*='location'], span[class*='loc'], span.styles_jph-location___twUQ, span.loc"
            ).first
            location = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else None

            # Salary
            salary_el = page.locator(
                "span[class*='salary'], span[class*='sal'], span.styles_jph-salary___twUQ, span.sal"
            ).first
            salary = (await salary_el.inner_text()).strip() if await salary_el.count() > 0 else None

            # Key skills / tags
            key_skills = await page.evaluate(r"""
                () => {
                    const skillEls = document.querySelectorAll(
                        'div[class*="key-skill"] a, a[class*="chip"], div.styles_key-skill__e_O_u a'
                    );
                    return Array.from(skillEls).map(el => el.innerText.trim()).filter(t => t.length > 0);
                }
            """)

            return {
                "title": title,
                "company": company,
                "location": location,
                "salary_range": salary,
                "key_skills": key_skills if key_skills else [],
                "description": description,
                "source_url": url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": url, "source": self.name, "error": str(e)}
