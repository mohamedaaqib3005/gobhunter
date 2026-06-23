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


class CutshortScraper(BaseScraper):
    name = "cutshort"
    login_url = "https://cutshort.io/jobs"

    def _candidate_urls(self, query: str, location: str) -> list[str]:
        q = query.lower().strip()
        loc = location.lower().replace(" ", "-")

        # Extract meaningful terms from the search query
        words = q.replace(",", "").split()
        candidates = []

        # Full query as-is
        candidates.append(f"https://cutshort.io/jobs/{'-'.join(words)}-jobs")
        candidates.append(f"https://cutshort.io/jobs/{'-'.join(words)}-jobs-in-{loc}")

        # Try without common filler words
        keywords = [w for w in words if w not in {"the", "a", "an", "in", "for", "and", "or"}]

        # Try keyword combinations: "python" + "developer" -> python-developer
        for w in keywords:
            candidates.append(f"https://cutshort.io/jobs/{w}-jobs")
            candidates.append(f"https://cutshort.io/jobs/{w}-jobs-in-{loc}")

        # Try pairing a tech word with "developer"
        tech_words = {"python", "java", "backend", "frontend", "fullstack",
                      "full-stack", "devops", "data", "software", "ios",
                      "android", "machine-learning", "ml", "ai",
                      "react", "angular", "node", "nodejs"}
        for w in keywords:
            if w in tech_words:
                candidates.append(f"https://cutshort.io/jobs/{w}-developer-jobs")
                candidates.append(f"https://cutshort.io/jobs/{w}-developer-jobs-in-{loc}")

        # Last resort: "developer-jobs"
        candidates.append("https://cutshort.io/jobs/developer-jobs")

        return candidates

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        page.set_default_timeout(30000)
        all_jobs = []
        seen_urls = set()

        for loc in locations:
            urls = self._candidate_urls(query, loc)
            for url in urls:
                if len(all_jobs) > 0 and seen_urls:
                    break
                try:
                    await page.goto(url, wait_until="networkidle", timeout=20000)
                except Exception:
                    continue
                await random_delay(3, 5)
                await human_like_scroll(page)
                await random_delay(2, 3)
                jobs = await self._parse_listing(page)
                if jobs:
                    for j in jobs:
                        if j["source_url"] not in seen_urls:
                            seen_urls.add(j["source_url"])
                            all_jobs.append(j)
                    break

        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        jobs = []
        links = page.locator("a[href*='/job/']")
        count = await links.count()

        for i in range(min(count, 50)):
            try:
                link_el = links.nth(i)
                title = await link_el.inner_text()
                url = await link_el.get_attribute("href") or ""
                if url and not url.startswith("http"):
                    url = "https://cutshort.io" + url

                # Walk up 6 ancestor divs from the <a> to reach the card
                # container that has all details (location, salary, skills).
                card = link_el.locator("xpath=ancestor::div[6]")
                if await card.count() == 0:
                    continue
                text = await card.first.inner_text()

                company = "Unknown"
                lines = text.split("\n")
                # Pattern 1: "at CompanyName"
                m = re.search(r"\bat\s+(.+?)(?:\n|$)", text)
                if m:
                    company = m.group(1).strip()
                else:
                    # Pattern 2: line before "Agency jobvia"
                    for idx, line in enumerate(lines):
                        if "Agency jobvia" in line and idx > 0:
                            prev = lines[idx - 1].strip()
                            if prev and prev != title.strip():
                                company = prev
                                break
                    # Pattern 3: extract from URL
                    if company == "Unknown":
                        url_parts = url.rstrip("/").split("-")
                        for part in reversed(url_parts):
                            if part not in ("jobs", "job") and len(part) > 3 and not any(c.isdigit() for c in part[-6:]):
                                try:
                                    int(part[-6:], 36)
                                except (ValueError, IndexError):
                                    company = part.replace("+", " ").title() if "-" not in part else part
                                    break

                location = "Bangalore/Remote"
                for city in CITIES:
                    if city.lower() in text.lower():
                        for line in text.split("\n"):
                            if city.lower() in line.lower():
                                location = line.strip()
                                break
                        break

                salary = None
                m = re.search(r"[₹][\d,]+[LkK]?\s*(?:-\s*[₹][\d,]+[LkK]?)?\s*/?\s*\w*", text)
                if m:
                    salary = m.group(0).strip()

                jobs.append({
                    "title": title.strip(),
                    "company": company,
                    "location": location,
                    "source": self.name,
                    "source_url": url,
                    "salary_range": salary,
                })
            except Exception:
                continue

        return jobs
