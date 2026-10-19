"""Settle two questions about Indeed posting dates in one run.

1. Does the `fromage` URL parameter actually narrow results by posting age?
   If it does, a scrape can tag jobs with an age bucket for no extra
   requests, since the list page carries no date text of its own.

2. Does an individual job page carry a posting date? If it does, a
   per-job request is a viable (if slow) route to an exact time.

    python probe_indeed2.py
"""

import asyncio
import re

BASE = "https://in.indeed.com/jobs?q=React+Developer&l=Bangalore"
CARD = ".job_seen_beacon"
DATE_RE = re.compile(
    r"\bago\b|just posted|just now|today|yesterday|posted|hiring ongoing"
    r"|active\b|hour|minute|\bday\b|\bdays\b|week|month",
    re.I,
)

COUNT_JS = """
(sel) => {
    let c = [...document.querySelectorAll(sel)];
    c = c.filter(x => !c.some(o => o !== x && o.contains(x)));
    const jks = c.map(card => {
        const a = card.querySelector('a[data-jk]');
        return a ? a.getAttribute('data-jk') : null;
    }).filter(Boolean);
    return {cards: c.length, jks: jks};
}
"""

# Every short text node on the detail page, for us to regex in Python.
TEXT_JS = """
() => [...document.querySelectorAll('*')]
    .filter(el => el.children.length === 0)
    .map(el => ({
        tag: el.tagName.toLowerCase(),
        cls: typeof el.className === 'string' ? el.className : '',
        testid: el.getAttribute('data-testid') || '',
        text: (el.innerText || '').trim(),
    }))
    .filter(o => o.text && o.text.length <= 80);
"""


async def load(page, url, label):
    print(f"\n### {label}")
    print(f"    {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)
    except Exception as exc:
        print(f"    failed: {type(exc).__name__}: {exc}")
        return None
    res = await page.evaluate(COUNT_JS, CARD)
    print(f"    {res['cards']} cards, {len(res['jks'])} with a job id")
    return res


async def main() -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN",
        )
        try:
            print("=" * 64)
            print("PART 1: does `fromage` narrow the result set?")
            print("=" * 64)

            baseline = await load(page, BASE, "no filter")
            d1 = await load(page, BASE + "&fromage=1&sort=date", "fromage=1 (last 24h), newest first")
            d3 = await load(page, BASE + "&fromage=3&sort=date", "fromage=3 (last 3 days), newest first")
            d7 = await load(page, BASE + "&fromage=7&sort=date", "fromage=7 (last 7 days), newest first")

            counts = {k: (v["cards"] if v else None) for k, v in
                      [("none", baseline), ("1", d1), ("3", d3), ("7", d7)]}
            print(f"\n    card counts by fromage: {counts}")
            vals = [counts["1"], counts["3"], counts["7"], counts["none"]]
            if None in vals:
                print("    VERDICT: a page failed to load, cannot tell")
            elif counts["1"] == counts["3"] == counts["7"] == counts["none"]:
                print("    VERDICT: identical counts. fromage is being IGNORED.")
            elif counts["1"] <= counts["3"] <= counts["7"]:
                print("    VERDICT: counts rise with the window. fromage WORKS,")
                print("             so age buckets are available for free.")
            else:
                print("    VERDICT: counts differ but not in age order. Page 1")
                print("             is capped at ~15, so this is inconclusive;")
                print("             judge by whether the titles differ instead.")

            print("\n" + "=" * 64)
            print("PART 2: does an individual job page carry a posting date?")
            print("=" * 64)

            jk = None
            for res in (baseline, d1, d3):
                if res and res["jks"]:
                    jk = res["jks"][0]
                    break
            if not jk:
                print("    no job id found on any card, cannot check a detail page")
            else:
                url = f"https://in.indeed.com/viewjob?jk={jk}"
                print(f"    opening {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(4000)
                nodes = await page.evaluate(TEXT_JS)
                hits = [n for n in nodes if DATE_RE.search(n["text"])]
                print(f"    {len(nodes)} short text nodes, {len(hits)} look like a date\n")
                if not hits:
                    print("    VERDICT: no date on the detail page either.")
                    print("             A per-job request would buy nothing.")
                for n in hits[:15]:
                    bits = f"<{n['tag']}>"
                    if n["cls"]:
                        bits += f' class="{n["cls"]}"'
                    if n["testid"]:
                        bits += f' data-testid="{n["testid"]}"'
                    print(f"      {bits}")
                    print(f"        -> {n['text']}")
                if hits:
                    print("\n    VERDICT: the detail page DOES carry a date (above).")
                    print("             A per-job request is viable but slow.")
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
