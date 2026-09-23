import asyncio
import json
import sys
from pathlib import Path

from database import delete_irrelevant_jobs, init_db


COOKIES_DIR = Path(__file__).parent / ".cookies"


def main() -> None:
    init_db()
    COOKIES_DIR.mkdir(exist_ok=True)
    args = sys.argv[1:]
    if not args:
        print("Usage: python main.py [scrape|dashboard|fill <job_id>|description <platform> <url>|cookies|cleanup|deduplicate]")
        return

    command = args[0]
    if command == "scrape":
        asyncio.run(run_scrape())
    elif command == "dashboard":
        run_dashboard()
    elif command == "fill" and len(args) >= 2:
        job_id = int(args[1])
        asyncio.run(run_fill(job_id))
    elif command == "description" and len(args) >= 2:
        if len(args) >= 3:
            platform = args[1].lower()
            url = args[2]
        else:
            arg = args[1]
            if "naukri.com" in arg:
                platform = "naukri"
                url = arg
            elif "indeed.com" in arg:
                platform = "indeed"
                url = arg
            elif "instahyre.com" in arg:
                platform = "instahyre"
                url = arg
            elif "linkedin.com" in arg:
                platform = "linkedin"
                url = arg
            elif "wellfound.com" in arg:
                platform = "wellfound"
                url = arg
            elif "cutshort.io" in arg:
                platform = "cutshort"
                url = arg
            else:
                platform = "naukri"
                url = arg
        asyncio.run(run_description(platform, url))

    elif command == "cookies":
        print_cookie_instructions()

    elif command == "cleanup":
        deleted = delete_irrelevant_jobs()
        print(f"Deleted {deleted} irrelevant jobs")
    elif command == "deduplicate":
        from database import deduplicate_jobs, migrate_source_urls
        migrated = migrate_source_urls()
        print(f"Normalized {migrated} source URLs")
        deleted = deduplicate_jobs()
        print(f"Deleted {deleted} duplicate jobs")
    else:
        print(f"Unknown command: {command}")



SITES = {
    "indeed": {"url": "https://in.indeed.com", "status": "public"},
    "naukri": {"url": "https://www.naukri.com", "status": "public"},
    "instahyre": {"url": "https://www.instahyre.com", "status": "public"},
    "cutshort": {"url": "https://cutshort.io", "status": "public"},
    "linkedin": {"url": "https://www.linkedin.com", "status": "cookies"},
    "wellfound": {"url": "https://wellfound.com", "status": "cookies"},
}


def print_cookie_instructions() -> None:
    print("=" * 60)
    print("How to set up cookies for sites that require login")
    print("=" * 60)
    print()
    print("1. Install 'Cookie-Editor' Chrome extension:")
    print("   https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm")
    print()
    print("2. For each site below:")
    print("   a) Log in with Google in your normal Chrome browser")
    print("   b) Open Cookie-Editor extension")
    print("   c) Click 'Export' (copies cookies as JSON)")
    print("   d) Save the file to: .cookies/{site}.json")
    print()
    print("   Sites (export cookies to enable applying via auto-fill):")
    for name, info in SITES.items():
        path = COOKIES_DIR / f"{name}.json"
        status = "✓ done" if path.exists() else "  not done"
        print(f"     {name:15s} {info['url']:35s} [{status}]")
    print()
    print("3. After saving cookie files, run: python main.py scrape")


async def run_scrape() -> None:
    from config import settings
    from database import deduplicate_jobs, migrate_source_urls

    migrated = migrate_source_urls()
    if migrated:
        print(f"[cleanup] Normalized {migrated} source URLs")
    deleted = deduplicate_jobs()
    if deleted:
        print(f"[cleanup] Deleted {deleted} duplicate jobs")
    from scrapers.indeed import IndeedScraper
    from scrapers.naukri import NaukriScraper
    from scrapers.cutshort import CutshortScraper
    from scrapers.instahyre import InstahyreScraper
    from scrapers.linkedin import LinkedInScraper
    from scrapers.wellfound import WellfoundScraper
    from utils.browser import scrape_with_cookies

    scraper_map = {
        "indeed": IndeedScraper(),
        "naukri": NaukriScraper(),
        "cutshort": CutshortScraper(),
        "instahyre": InstahyreScraper(),
        "linkedin": LinkedInScraper(),
        "wellfound": WellfoundScraper(),
    }

    for name, scraper in scraper_map.items():
        info = SITES[name]
        cookie_file = COOKIES_DIR / f"{name}.json"
        cookies = json.loads(cookie_file.read_text()) if cookie_file.exists() else []

        if info["status"] == "cookies" and not cookies:
            print(f"[{name}] Requires cookies. Run 'python main.py cookies' for setup.")
            continue

        print(f"[{name}] {'Cookies loaded' if cookies else 'Scraping public listings'}...")

        async def search(page):
            return await scraper.search(page, settings.search_query, settings.search_locations)


        try:
            jobs = await scrape_with_cookies(scraper.login_url, search, cookies)
            if jobs is None:
                print(f"[{name}] Skipped (blocked)")
                continue
            print(f"[{name}] Found {len(jobs)} jobs")
            saved = 0
            for job_data in jobs:
                from config import is_relevant_title
                from database import insert_job, job_exists, job_exists_by_content
                from models import Job
                if not is_relevant_title(job_data["title"]):
                    continue
                if not job_exists(job_data["source_url"], job_data["source"]) \
                   and not job_exists_by_content(job_data["title"], job_data["company"], job_data["location"], job_data["source"]):
                    job = Job(**job_data)
                    insert_job(job)
                    saved += 1
            print(f"[{name}] Saved {saved} new jobs")
        except Exception as e:
            print(f"[{name}] Error: {e}")


async def run_fill(job_id: int) -> None:
    from applicator.auto_fill import AutoFill
    from database import get_job
    from utils.browser import scrape_with_cookies

    job = get_job(job_id)
    if not job:
        print(f"Job {job_id} not found")
        return

    cookie_file = COOKIES_DIR / f"{job.source}.json"
    cookies = json.loads(cookie_file.read_text()) if cookie_file.exists() else []

    async def fill(page):
        filler = AutoFill(page)
        await filler.fill_application(job)

    await scrape_with_cookies(job.source_url, fill, cookies, headless=False)
    print("[auto-fill] Browser open for review. Press Ctrl+C when done.")
    try:
        while True:
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        pass


async def run_description(platform: str, url: str) -> None:
    from scrapers.cutshort import CutshortScraper
    from scrapers.indeed import IndeedScraper
    from scrapers.instahyre import InstahyreScraper
    from scrapers.linkedin import LinkedInScraper
    from scrapers.naukri import NaukriScraper
    from scrapers.wellfound import WellfoundScraper
    from utils.browser import scrape_with_cookies

    scraper_map = {
        "indeed": IndeedScraper(),
        "naukri": NaukriScraper(),
        "instahyre": InstahyreScraper(),
        "linkedin": LinkedInScraper(),
        "wellfound": WellfoundScraper(),
        "cutshort": CutshortScraper(),
    }


    if platform not in scraper_map:
        print(f"Unsupported platform: '{platform}'. Supported platforms: {', '.join(scraper_map.keys())}")
        return

    scraper = scraper_map[platform]
    cookie_file = COOKIES_DIR / f"{platform}.json"
    cookies = json.loads(cookie_file.read_text()) if cookie_file.exists() else []

    async def fetch(page):
        return await scraper.get_job_details(page, url)

    print(f"[{platform}] Fetching job details from: {url}")
    details = await scrape_with_cookies(url, fetch, cookies)

    if not details:
        print(f"Failed to fetch job details from {platform}.")
        return

    print("\n" + "=" * 60)
    print(f"JOB DETAILS ({platform.upper()})")
    print("=" * 60)
    if details.get("title"):
        print(f"Title:       {details['title']}")
    if details.get("company"):
        print(f"Company:     {details['company']}")
    if details.get("location"):
        print(f"Location:    {details['location']}")
    if details.get("salary_range"):
        print(f"Salary:      {details['salary_range']}")
    if details.get("key_skills"):
        print(f"Key Skills:  {', '.join(details['key_skills'])}")
    print("-" * 60)
    print("DESCRIPTION:")
    print("-" * 60)
    desc = details.get("description")
    if desc:
        print(desc)
    else:
        print("No description extracted or description element not found.")
    print("=" * 60)



def run_dashboard() -> None:
    import uvicorn
    from config import settings
    from dashboard.app import app
    print(f"Dashboard at http://localhost:{settings.dashboard_port}")
    uvicorn.run(app, host="127.0.0.1", port=settings.dashboard_port)


if __name__ == "__main__":
    main()
