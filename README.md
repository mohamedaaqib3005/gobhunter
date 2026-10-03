# gobhunter

Automated job scraper, tracker, and application auto-filler for Indian job portals.

Scrapes job listings from multiple sites, stores them in a local database, provides a web dashboard to browse and manage them, and can auto-fill application forms via browser automation.

## Features

- **Scrape** — collects jobs from Indeed, Naukri, Cutshort, Instahyre, LinkedIn, and Wellfound
- **Filter** — keeps only relevant titles based on configurable keywords (include/exclude)
- **Deduplicate** — merges identical listings across sources
- **Track** — web dashboard at `localhost:8765` to browse, filter, and update job status (new / applied / rejected / bookmarked / dismissed)
- **Auto-fill** — opens a job's application page and pre-fills your name, email, phone, cover letter, and resume via Playwright
- **Cookies** — supports logged-in scraping for sites that require authentication

## Prerequisites

- Python 3.10+
- Firefox browser (for Playwright automation)
- Git

## Quick Start

```bash
# Clone the repository
git clone git@github.com:bit-by-bit-school/gobhunter.git
cd gobhunter

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
# .venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright's Firefox browser
playwright install firefox

# Create your config from the template
cp .env.example .env
# Edit .env with your search criteria and personal info (see Configuration below)
```

Run a scrape:

```bash
python main.py scrape
```

Open the dashboard:

```bash
python main.py dashboard
```

## Configuration

All configuration is done through the `.env` file (copy from `.env.example`).

### Search Settings

| Variable           | Default                      | Description                         |
| ------------------ | ---------------------------- | ----------------------------------- |
| `SEARCH_QUERY`     | `Python Backend Developer`   | Job search query sent to each site  |
| `SEARCH_LOCATIONS` | `Bangalore,Bengaluru,Remote` | Comma-separated cities to search in |

### Title Relevance Filters

Jobs whose titles don't match your include criteria are automatically skipped during scraping and can be cleaned up later with `python main.py cleanup`.

| Variable           | Default                            | Description                                                                                       |
| ------------------ | ---------------------------------- | ------------------------------------------------------------------------------------------------- |
| `INCLUDE_KEYWORDS` | `Python,Backend,Software Engineer` | Comma-separated keywords — a title is relevant if it contains **any** of these (case-insensitive) |
| `EXCLUDE_KEYWORDS` | _(empty)_                          | Comma-separated keywords to exclude (in addition to built-in excludes below)                      |

**Built-in excludes** (always applied): `Senior`, `Sr`, `Staff`, `Principal`, `Lead`, and level indicators `2`-`9`, `II`, `III`, `IV`, `V`.

**How it works:** A title like "Senior Python Developer" would match the include keyword `Python` but also matches the exclude `Senior`, so it's filtered out. "Python Developer" (no seniority) passes through.

### Auto-Fill Personal Info

| Variable                 | Description                      |
| ------------------------ | -------------------------------- |
| `APPLICANT_NAME`         | Your full name                   |
| `APPLICANT_EMAIL`        | Your email address               |
| `APPLICANT_PHONE`        | Your phone number                |
| `APPLICANT_LINKEDIN`     | LinkedIn profile URL             |
| `APPLICANT_PORTFOLIO`    | Portfolio or website URL         |
| `APPLICANT_COVER_LETTER` | Cover letter text                |
| `RESUME_PATH`            | Absolute path to your resume PDF |

### Browser & Dashboard

| Variable           | Default        | Description                 |
| ------------------ | -------------- | --------------------------- |
| `BROWSER_LOCALE`   | `en-IN`        | Playwright browser locale   |
| `BROWSER_TIMEZONE` | `Asia/Kolkata` | Playwright browser timezone |
| `DASHBOARD_PORT`   | `8765`         | Web dashboard port          |

## Usage

```bash
python main.py scrape        # Scrape all configured job sites
python main.py dashboard     # Start the web dashboard
python main.py fill <job_id> # Open a job's application and pre-fill forms
python main.py cookies       # Show instructions for setting up login cookies
python main.py cleanup       # Remove jobs that don't match your filters
python main.py deduplicate   # Remove duplicate entries
```

### Dashboard

Run `python main.py dashboard` and open `http://localhost:8765` in your browser.

- Browse jobs with filters for source, status, and relevance
- Click a job title to see details and change its status
- Use the "Pre-fill Application" button to auto-fill the application form for a job

### Cookie Setup

Some sites (Cutshort, Instahyre, LinkedIn, Wellfound) require being logged in to view job listings.

1. Install the [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) Chrome extension
2. Log in to the site in your regular Chrome browser
3. Open Cookie-Editor, click **Export** (copies cookies as JSON)
4. Save the file to `.cookies/{site}.json` (e.g., `.cookies/linkedin.json`)
5. Run `python main.py scrape` — cookies will be loaded automatically

Run `python main.py cookies` to see which cookies are already set up.

## Customizing Title Filters

The simplest way to customize what jobs you see is to edit `INCLUDE_KEYWORDS` and `EXCLUDE_KEYWORDS` in your `.env` file.

**Examples:**

```env
# Only Python backend roles
INCLUDE_KEYWORDS=Python,Backend

# Python or Frontend roles, but no internships
INCLUDE_KEYWORDS=Python,Frontend
EXCLUDE_KEYWORDS=Intern,Trainee,Fresher

# Data science / ML roles
INCLUDE_KEYWORDS=Data Scientist,Machine Learning,ML Engineer
```

For more advanced filtering (e.g., requiring specific combinations), edit the `INCLUDE_TITLE_PATTERNS` list in `config.py` directly.

## Project Structure

```
gobhunter/
  main.py              CLI entry point
  config.py            Settings from .env + title filter builder
  models.py            Job / JobStatus Pydantic models
  database.py          SQLite CRUD and deduplication
  scrapers/            Site-specific scrapers
    base.py            Abstract BaseScraper
    indeed.py
    naukri.py
    cutshort.py
    instahyre.py
    linkedin.py
    wellfound.py
  applicator/
    auto_fill.py       Application form auto-filler
  dashboard/
    app.py             FastAPI web server
    templates/         Jinja2 HTML templates
  utils/
    browser.py         Playwright browser management
  .env.example         Configuration template
```

## Adding a New Scraper

1. Create `scrapers/yoursite.py` with a class inheriting from `BaseScraper`
2. Implement `async def search(self, page, query, locations) -> list[dict]`
3. Add an entry to `SITES` in `main.py`
4. Register the scraper in `scraper_map` in `run_scrape()`

Each job dict should have: `title`, `company`, `location`, `source`, `source_url`, and optionally `salary_range` and `description`.

## Disclaimer

- This tool is for **educational and personal use** only
- Respect each job site's terms of service and robots.txt
- Scraping too aggressively may get your IP rate-limited or blocked
- Some sites require login cookies (see Cookie Setup); use responsibly
- The authors are not responsible for any misuse or violations of third-party terms

## License

MIT
