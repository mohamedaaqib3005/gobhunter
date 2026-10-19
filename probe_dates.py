"""Report what each job card on a live search page says about posting date.

Rather than guess at CSS class names, this opens one live search page and,
for every card, prints whether it is sponsored, its title, and every bit of
text that reads like a posting age, with the tag and class that held it.

Earlier versions of this script sliced the first three selector matches.
On Indeed those matches are nested inside one another (.cardOutline wraps
slider_item wraps job_seen_beacon wraps td.resultContent), so all three
"cards" were the same job. Each site now has one selector per job and
nested matches are discarded.

    python probe_dates.py indeed
    python probe_dates.py naukri
    python probe_dates.py linkedin
"""

import asyncio
import sys

SITES = {
    "indeed": {
        "url": "https://in.indeed.com/jobs?q=React+Developer&l=Bangalore",
        "card": ".job_seen_beacon",
    },
    "naukri": {
        "url": "https://www.naukri.com/react-developer-jobs-in-bangalore",
        "card": "div.srp-jobtuple-wrapper",
    },
    "linkedin": {
        "url": "https://www.linkedin.com/jobs/search/?keywords=React%20Developer&location=Bangalore",
        "card": "div.base-card",
    },
}

# Anything that reads like a posting age.
DATE_RE = r"\bago\b|just posted|just now|today|yesterday|posted|active\b|hour|minute|\bday\b|\bdays\b|week|month"

JS = """
([cardSel, dateRe]) => {
    let cards = [...document.querySelectorAll(cardSel)];
    if (!cards.length) return {error: 'NO CARDS MATCHED: ' + cardSel, cards: []};

    // Drop any match that sits inside an earlier match. The same job often
    // matches at several nesting levels and would be reported four times.
    cards = cards.filter(c => !cards.some(o => o !== c && o.contains(c)));
    cards = cards.slice(0, 12);

    const re = new RegExp(dateRe, 'i');
    const out = [];

    cards.forEach(card => {
        const outer = card.outerHTML || '';
        const sponsored =
            /sponTapItem|sponsoredJob/i.test(outer) ||
            !!card.querySelector('[data-testid="sponsoredJob"]') ||
            /\\bSponsored\\b/.test(card.innerText || '');

        const titleEl = card.querySelector('h2 a span, h3 a span, [id^="jobTitle"], .base-search-card__title');
        const title = titleEl ? (titleEl.innerText || titleEl.getAttribute('title') || '').trim() : '(no title)';

        // Every element whose own text reads like a date. No leaf-node filter
        // this time, but skip an element if a descendant also matched, so we
        // report the tightest wrapper rather than the whole card.
        const raw = [...card.querySelectorAll('*')].filter(el => {
            const t = (el.innerText || '').trim();
            return t && t.length <= 80 && re.test(t);
        });
        const hits = raw.filter(el => !raw.some(o => o !== el && el.contains(o)));

        out.push({
            sponsored: sponsored,
            title: title,
            hits: hits.map(el => ({
                tag: el.tagName.toLowerCase(),
                cls: typeof el.className === 'string' ? el.className : '',
                testid: el.getAttribute('data-testid') || '',
                dt: el.getAttribute('datetime') || '',
                text: (el.innerText || '').trim(),
            })),
        });
    });

    return {error: null, total: document.querySelectorAll(cardSel).length, cards: out};
}
"""


async def main() -> int:
    site = (sys.argv[1] if len(sys.argv) > 1 else "indeed").lower()
    if site not in SITES:
        print(f"unknown site '{site}'. choose from: {', '.join(SITES)}")
        return 1

    cfg = SITES[site]
    from playwright.async_api import async_playwright

    print(f"opening {cfg['url']}\n")
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN",
        )
        try:
            await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(5000)
            res = await page.evaluate(JS, [cfg["card"], DATE_RE])

            if res["error"]:
                print(res["error"])
                return 1

            cards = res["cards"]
            print(f"{len(cards)} distinct cards (selector matched {res['total']} nodes)\n")

            with_date = 0
            for i, c in enumerate(cards, 1):
                tag = "SPONSORED" if c["sponsored"] else "organic  "
                print(f"--- card {i} [{tag}] {c['title'][:50]}")
                if not c["hits"]:
                    print("      no date-like text on this card")
                    continue
                with_date += 1
                for h in c["hits"]:
                    bits = f"<{h['tag']}>"
                    if h["cls"]:
                        bits += f' class="{h["cls"]}"'
                    if h["testid"]:
                        bits += f' data-testid="{h["testid"]}"'
                    if h["dt"]:
                        bits += f' datetime="{h["dt"]}"'
                    print(f"      {bits}")
                    print(f"        -> {h['text']}")

            org = [c for c in cards if not c["sponsored"]]
            org_with = [c for c in org if c["hits"]]
            print(f"\nsummary: {len(cards)} cards, {len(org)} organic, "
                  f"{len(org_with)} organic cards carry date-like text")
        except Exception as exc:
            print(f"failed: {type(exc).__name__}: {exc}")
            return 1
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
