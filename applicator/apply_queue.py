"""Work through a filtered list of jobs, one application at a time.

A deliberately SEMI-automatic queue. For each job it opens the page in a
visible browser, fills what it can and attaches the default resume, then
stops and waits for you. You review, submit, and tell it what happened.

Why not fully automatic: Indeed, Naukri and LinkedIn detect and act on
automated submissions, and an account restriction costs more than the
applications it would have saved. Instahyre is the exception, because its
own applyBulk() is a feature the site provides; that is worth a separate
path and is not what this does.

The filters mirror the dashboard's, so a run covers exactly what you were
looking at.

    python main.py apply --city bangalore --posted-within 24h --limit 20
    python main.py apply --source naukri --search react --max-exp 5
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from config import settings
from database import get_jobs, update_job_status
from models import Job, JobStatus
from utils.browser import scrape_with_cookies

COOKIES_DIR = Path(__file__).parent.parent / ".cookies"

# Sites that punish automated submission. The queue never auto-submits
# anywhere, but these are the ones where even rapid-fire manual submitting
# from one session looks mechanical, so the pause between jobs matters.
SENSITIVE = {"linkedin", "indeed", "naukri"}


def parse_args(argv: list[str]) -> dict:
    """Flags matching the dashboard's filters, so a run covers what you saw."""
    out: dict = {
        "city": None, "source": None, "work_mode": None,
        "posted_within": None, "search": None,
        "max_exp_years": None, "limit": 25,
    }
    flags = {
        "--city": "city", "--source": "source", "--work-mode": "work_mode",
        "--posted-within": "posted_within", "--search": "search",
        "--max-exp": "max_exp_years", "--limit": "limit",
    }
    i = 0
    while i < len(argv):
        key = flags.get(argv[i])
        if key is None:
            print(f"unknown option: {argv[i]}")
            print(__doc__)
            raise SystemExit(2)
        if i + 1 >= len(argv):
            print(f"{argv[i]} needs a value")
            raise SystemExit(2)
        value = argv[i + 1]
        if key in ("max_exp_years", "limit"):
            try:
                value = int(value)
            except ValueError:
                print(f"{argv[i]} needs a number, got {value!r}")
                raise SystemExit(2)
        out[key] = value
        i += 2
    return out


def _prompt(job: Job, index: int, total: int) -> str:
    """Ask what happened. Returns 'applied', 'skip' or 'quit'."""
    print()
    print("  " + "-" * 62)
    print(f"  [{index}/{total}] {job.title}")
    print(f"  {job.company} · {job.location} · {job.source}")
    print("  " + "-" * 62)
    print("  The browser is open with the form filled in as far as it could be.")
    print("  Review it, submit if you want the job, then answer here.")
    print()
    while True:
        try:
            answer = input("  [a]pplied  [s]kip  [q]uit > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"
        if answer in ("a", "applied"):
            return "applied"
        if answer in ("s", "skip", ""):
            return "skip"
        if answer in ("q", "quit"):
            return "quit"
        print("  answer a, s or q")


async def run(opts: dict) -> int:
    resume = Path(settings.resume_path)
    if not resume.exists():
        print(f"Default resume not found at {resume}")
        print("Set RESUME_PATH in .env to the PDF you want attached.")
        return 1

    jobs = get_jobs(
        city=opts["city"],
        source=opts["source"],
        work_mode=opts["work_mode"],
        posted_within=opts["posted_within"],
        search=opts["search"],
        max_exp_years=opts["max_exp_years"],
        limit=opts["limit"],
    )
    # Never re-apply to something already handled. get_jobs already drops
    # dismissed ones; this also drops applied, rejected and the rest.
    jobs = [j for j in jobs if j.status == JobStatus.NEW]

    if not jobs:
        print("No new jobs match those filters. Nothing to do.")
        return 0

    by_source: dict[str, int] = {}
    for j in jobs:
        by_source[j.source] = by_source.get(j.source, 0) + 1

    print(f"\n{len(jobs)} jobs to work through")
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        note = "   (submit at a human pace)" if src in SENSITIVE else ""
        print(f"  {src:<12} {n}{note}")
    print(f"\nResume: {resume}")
    print("Nothing is submitted for you. You click submit on every one.\n")

    try:
        if input("Start? [y/N] > ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0

    from applicator.auto_fill import AutoFill

    applied = skipped = failed = 0
    for index, job in enumerate(jobs, 1):
        cookie_file = COOKIES_DIR / f"{job.source}.json"
        cookies = []
        if cookie_file.exists():
            import json
            try:
                cookies = json.loads(cookie_file.read_text())
            except Exception as exc:
                print(f"  could not read {cookie_file.name}: {exc}")

        decision = "skip"

        async def handler(page, _job=job):
            filler = AutoFill(page)
            await filler.fill_application(_job)
            # Hand control back to the human while the page stays open.
            return _prompt(_job, index, len(jobs))

        try:
            decision = await scrape_with_cookies(
                job.source_url, handler, cookies, headless=False
            )
        except Exception as exc:
            print(f"  [{index}/{len(jobs)}] failed to open {job.title}: "
                  f"{type(exc).__name__}: {exc}")
            failed += 1
            continue

        if decision == "applied":
            update_job_status(job.id, JobStatus.APPLIED,
                              notes="Applied via the gobhunter queue")
            applied += 1
            print(f"  marked applied: {job.title}")
        elif decision == "quit":
            print("\n  stopping here.")
            break
        else:
            skipped += 1

    print()
    print("=" * 64)
    print(f"applied {applied} · skipped {skipped} · failed {failed}")
    print("=" * 64)
    if applied:
        print("Those are marked applied, so a later run will not offer them again.")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
