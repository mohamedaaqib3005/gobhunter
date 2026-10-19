"""Where does each site state required experience?

Only Cutshort currently captures it, via expRange in its JSON. This opens
Naukri's live cards and Indeed's job-card JSON to find the real field or
element, so the selectors are written from fact rather than guessed.

    python probe_exp.py
"""

import asyncio
import json
import re

NAUKRI = "https://www.naukri.com/react-developer-jobs-in-bangalore"
INDEED = "https://in.indeed.com/jobs?q=React+Developer&l=Bangalore"

EXP_RE = re.compile(r"\byr?s?\b|\byears?\b|experience|exp\b", re.I)

NAUKRI_JS = """
([dateRe]) => {
    let cards = [...document.querySelectorAll('div.srp-jobtuple-wrapper')];
    cards = cards.filter(c => !cards.some(o => o !== c && o.contains(c)));
    if (!cards.length) return {error: 'no naukri cards matched', cards: []};
    const re = new RegExp(dateRe, 'i');
    return {error: null, cards: cards.slice(0, 6).map(card => {
        const t = card.querySelector('a.title, a[class*="title"]');
        const raw = [...card.querySelectorAll('*')].filter(el => {
            const s = (el.innerText || '').trim();
            return s && s.length <= 40 && re.test(s);
        });
        const hits = raw.filter(el => !raw.some(o => o !== el && el.contains(o)));
        return {
            title: t ? (t.innerText || '').trim().slice(0, 48) : '(no title)',
            hits: hits.map(el => ({
                tag: el.tagName.toLowerCase(),
                cls: typeof el.className === 'string' ? el.className : '',
                title_attr: el.getAttribute('title') || '',
                text: (el.innerText || '').trim(),
            })),
        };
    })};
}
"""

INDEED_JS = """
() => {
    const jc = (window.mosaic?.providerData || {})['mosaic-provider-jobcards'];
    const res = jc?.metaData?.mosaicProviderJobCardsModel?.results || [];
    return res.slice(0, 6).map(c => ({
        title: c.title || '',
        requirements: c.jobCardRequirementsModel ?? null,
        taxo: (c.taxonomyAttributes || []).map(t => ({
            label: t.label ?? null, attrs: (t.attributes || []).map(a => a.label ?? a.suid ?? null)
        })),
        enriched: c.enhancedAttributesModel ?? null,
    }));
}
"""


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
            print("=" * 68)
            print("NAUKRI cards: any element mentioning years / experience")
            print("=" * 68)
            try:
                await page.goto(NAUKRI, wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(5000)
                r = await page.evaluate(NAUKRI_JS, [EXP_RE.pattern])
                if r["error"]:
                    print(f"  {r['error']}")
                for c in r["cards"]:
                    print(f"\n  {c['title']}")
                    if not c["hits"]:
                        print("    nothing experience-like on this card")
                    for h in c["hits"]:
                        bits = f"<{h['tag']}>"
                        if h["cls"]: bits += f' class="{h["cls"]}"'
                        if h["title_attr"]: bits += f' title="{h["title_attr"]}"'
                        print(f"    {bits}")
                        print(f"      -> {h['text']}")
            except Exception as exc:
                print(f"  failed: {type(exc).__name__}: {exc}")

            print("\n" + "=" * 68)
            print("INDEED job-card JSON: requirements / taxonomy fields")
            print("=" * 68)
            try:
                await page.goto(INDEED, wait_until="domcontentloaded", timeout=40000)
                await page.wait_for_timeout(5000)
                rows = await page.evaluate(INDEED_JS)
                if not rows:
                    print("  no JSON results")
                for c in rows:
                    print(f"\n  {c['title'][:50]}")
                    print(f"    jobCardRequirementsModel: "
                          f"{json.dumps(c['requirements'], ensure_ascii=False)[:300]}")
                    if c["taxo"]:
                        print(f"    taxonomyAttributes: "
                              f"{json.dumps(c['taxo'], ensure_ascii=False)[:260]}")
                    if c["enriched"]:
                        print(f"    enhancedAttributesModel: "
                              f"{json.dumps(c['enriched'], ensure_ascii=False)[:260]}")
            except Exception as exc:
                print(f"  failed: {type(exc).__name__}: {exc}")
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
