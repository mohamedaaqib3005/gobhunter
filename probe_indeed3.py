"""Does Indeed's internal job-card JSON carry a posting date?

The scraper reads window.mosaic.providerData first and returns early when it
finds results, so the DOM path never runs. The page shows no date text, but
the JSON behind it may still carry one. This dumps the shape of that JSON so
the question is settled by looking rather than guessing.

    python probe_indeed3.py
"""

import asyncio
import json

URL = "https://in.indeed.com/jobs?q=React+Developer&l=Bangalore"

JS = """
() => {
    const out = {mosaic: false, providers: [], count: 0, keys: [], first: null,
                 dateish: [], jsonld: null};
    try {
        const m = window.mosaic;
        if (!m) return out;
        out.mosaic = true;
        out.providers = Object.keys(m.providerData || {});
        const jc = (m.providerData || {})['mosaic-provider-jobcards'];
        if (!jc) return out;
        const res = jc.metaData?.mosaicProviderJobCardsModel?.results || [];
        out.count = res.length;
        if (!res.length) return out;
        const c = res[0];
        out.keys = Object.keys(c).sort();

        // Any key whose NAME or whose primitive VALUE smells like a date.
        const nameRe = /date|time|age|posted|fresh|created|publish|day/i;
        const valRe  = /\\bago\\b|just posted|\\d{4}-\\d{2}-\\d{2}|^\\d{12,13}$/i;
        for (const k of out.keys) {
            const v = c[k];
            const t = typeof v;
            if (t === 'object' || t === 'function') continue;
            const s = String(v);
            if (nameRe.test(k) || valRe.test(s)) {
                out.dateish.push({key: k, type: t, value: s.slice(0, 80)});
            }
        }
        // Shallow copy with big objects dropped, so the dump stays readable.
        const shallow = {};
        for (const k of out.keys) {
            const v = c[k];
            shallow[k] = (v && typeof v === 'object') ? '[' + (Array.isArray(v) ? 'array' : 'object') + ']' : v;
        }
        out.first = shallow;
    } catch (e) { out.error = String(e); }

    // JSON-LD on the list page sometimes carries datePosted per job.
    try {
        const s = [...document.querySelectorAll('script[type="application/ld+json"]')]
            .map(x => x.innerText).join(' ');
        const m2 = s.match(/"datePosted"\\s*:\\s*"[^"]{4,40}"/g);
        if (m2) out.jsonld = m2.slice(0, 5);
    } catch (e) {}

    return out;
}
"""


async def main() -> int:
    from playwright.async_api import async_playwright

    print(f"opening {URL}\n")
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN",
        )
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(5000)
            r = await page.evaluate(JS)
        except Exception as exc:
            print(f"failed: {type(exc).__name__}: {exc}")
            return 1
        finally:
            await browser.close()

    print(f"window.mosaic present : {r['mosaic']}")
    print(f"providers             : {r.get('providers')}")
    print(f"job results in JSON   : {r['count']}")
    if r.get("error"):
        print(f"js error              : {r['error']}")

    if not r["count"]:
        print("\nNo Mosaic results. The scraper is using its DOM fallback,")
        print("which means the page really is the only source and it has no date.")
        return 0

    print(f"\n{len(r['keys'])} keys on the first job card:")
    print("  " + ", ".join(r["keys"]))

    print("\nkeys that look date-related:")
    if not r["dateish"]:
        print("  NONE. The JSON carries no posting date.")
    for d in r["dateish"]:
        print(f"  {d['key']}  ({d['type']})  =  {d['value']}")

    print("\nfull first card, nested objects collapsed:")
    print(json.dumps(r["first"], indent=2, ensure_ascii=False)[:2600])

    print(f"\nJSON-LD datePosted on the list page: {r.get('jsonld')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
