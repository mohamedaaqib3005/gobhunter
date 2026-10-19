"""Which Indeed JSON field is the posting time? Checked on FRESH jobs.

On a 90-day-old listing pubDate and createDate are 16 days apart and both
read as "30+ days ago", so neither can be identified. fromage=1 returns jobs
posted inside 24 hours, where the correct field must agree with the relative
string and the wrong one will not.

    python probe_indeed4.py
"""

import asyncio
from datetime import datetime, timezone

URLS = [
    ("posted within 24h", "https://in.indeed.com/jobs?q=React+Developer&l=Bangalore&fromage=1&sort=date"),
    ("posted within 3 days", "https://in.indeed.com/jobs?q=Frontend+Developer&l=Bangalore&fromage=3&sort=date"),
]

JS = """
() => {
    const jc = (window.mosaic?.providerData || {})['mosaic-provider-jobcards'];
    const res = jc?.metaData?.mosaicProviderJobCardsModel?.results || [];
    return res.slice(0, 8).map(c => ({
        title: c.title || c.displayTitle || '',
        rel: c.formattedRelativeTime ?? null,
        pub: c.pubDate ?? null,
        crt: c.createDate ?? null,
        sponsored: c.sponsored ?? null,
        expired: c.expired ?? null,
        newJob: c.newJob ?? null,
        remote: c.remoteLocation ?? null,
        showRel: c.showRelativeDate ?? null,
    }));
}
"""


def age(ms, now):
    if ms in (None, 0):
        return "  (absent)", None
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    d = now - dt
    hrs = d.total_seconds() / 3600
    if hrs < 0:
        label = f"{-hrs:.1f}h in the FUTURE"
    elif hrs < 48:
        label = f"{hrs:.1f}h ago"
    else:
        label = f"{d.days}d ago"
    return f"{dt.isoformat(timespec='seconds')}  ({label})", hrs


async def main() -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="en-IN",
        )
        pub_ok = crt_ok = 0
        try:
            for label, url in URLS:
                print("=" * 70)
                print(f"{label}")
                print(f"{url}")
                print("=" * 70)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                    await page.wait_for_timeout(4500)
                    rows = await page.evaluate(JS)
                except Exception as exc:
                    print(f"  failed: {type(exc).__name__}: {exc}\n")
                    continue

                now = datetime.now(timezone.utc)
                cap = 24 if "24h" in label else 72

                if not rows:
                    print("  no JSON results on this page\n")
                    continue

                for r in rows:
                    print(f"\n  {r['title'][:58]}")
                    print(f"    formattedRelativeTime : {r['rel']!r}")
                    p_s, p_h = age(r["pub"], now)
                    c_s, c_h = age(r["crt"], now)
                    print(f"    pubDate               : {p_s}")
                    print(f"    createDate            : {c_s}")
                    flags = (f"sponsored={r['sponsored']} expired={r['expired']} "
                             f"newJob={r['newJob']} remote={r['remote']!r} "
                             f"showRelativeDate={r['showRel']}")
                    print(f"    flags                 : {flags}")
                    # Which field is consistent with the window we asked for?
                    if p_h is not None and 0 <= p_h <= cap:
                        pub_ok += 1
                    if c_h is not None and 0 <= c_h <= cap:
                        crt_ok += 1
                print()
        finally:
            await browser.close()

    print("=" * 70)
    print(f"pubDate    fell inside the requested window : {pub_ok} times")
    print(f"createDate fell inside the requested window : {crt_ok} times")
    print("=" * 70)
    if pub_ok > crt_ok:
        print("VERDICT: use pubDate as the posting time.")
    elif crt_ok > pub_ok:
        print("VERDICT: use createDate as the posting time.")
    elif pub_ok == crt_ok == 0:
        print("VERDICT: neither agrees with the window. Do not trust either;")
        print("         fall back to parsing formattedRelativeTime.")
    else:
        print("VERDICT: both agree equally. Prefer pubDate, keep createDate")
        print("         as the fallback when pubDate is absent or zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
