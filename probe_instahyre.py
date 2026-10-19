"""Why does Instahyre return 0 jobs?

The scraper passes the entire SEARCH_QUERY as one `skills` value. That is now
five comma-separated phrases, and the API may simply match nothing. This tries
the current call plus several narrower shapes and reports which return jobs,
so the fix is based on what the API actually does.

    python probe_instahyre.py
"""

import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.instahyre.com/api/v1/job_search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.instahyre.com/search-jobs/",
}

FULL = "React Developer,Frontend Developer,Full Stack Developer,React Native Developer,UI Developer"

CASES = [
    ("exactly what the scraper sends now", {"skills": FULL, "location": "Bangalore",
                                            "search": "true", "offset": 0, "limit": 50}),
    ("one phrase",            {"skills": "React Developer", "location": "Bangalore",
                               "search": "true", "offset": 0, "limit": 50}),
    ("one bare skill",        {"skills": "React", "location": "Bangalore",
                               "search": "true", "offset": 0, "limit": 50}),
    ("lowercase skill",       {"skills": "react", "location": "Bangalore",
                               "search": "true", "offset": 0, "limit": 50}),
    ("no skills at all",      {"location": "Bangalore", "search": "true",
                               "offset": 0, "limit": 50}),
    ("no location",           {"skills": "React", "search": "true",
                               "offset": 0, "limit": 50}),
    ("no params but search",  {"search": "true", "offset": 0, "limit": 50}),
    ("location Bengaluru",    {"skills": "React", "location": "Bengaluru",
                               "search": "true", "offset": 0, "limit": 50}),
    ("q instead of skills",   {"q": "React", "location": "Bangalore",
                               "search": "true", "offset": 0, "limit": 50}),
]


def main() -> int:
    best = None
    for label, params in CASES:
        url = f"{API}?{urllib.parse.urlencode(params)}"
        print(f"\n--- {label}")
        print(f"    {url[:120]}")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code} {e.reason}")
            continue
        except Exception as exc:
            print(f"    failed: {type(exc).__name__}: {exc}")
            continue

        try:
            data = json.loads(body)
        except ValueError:
            print(f"    HTTP {status}, not JSON. First 160 chars:")
            print(f"    {body[:160]!r}")
            continue

        if not isinstance(data, dict):
            print(f"    HTTP {status}, JSON is {type(data).__name__}, not an object")
            continue

        objs = data.get("objects")
        meta = data.get("meta")
        print(f"    HTTP {status}, top-level keys: {sorted(data)}")
        if meta:
            print(f"    meta: {json.dumps(meta)[:140]}")
        if objs is None:
            print("    no 'objects' key, which is what the scraper requires")
            continue
        print(f"    objects: {len(objs)}")
        if objs:
            if best is None:
                best = (label, params, len(objs))
            o = objs[0]
            print(f"    keys on job[0]: {sorted(o)[:18]}")
            print(f"    title   : {o.get('title') or o.get('candidate_title')!r}")
            emp = o.get("employer") or {}
            print(f"    company : {emp.get('company_name')!r}")
            print(f"    location: {o.get('locations')!r}")
            print(f"    public_url: {o.get('public_url')!r}")
            # Anything that looks like a date or experience, for later.
            dateish = [k for k in o if any(w in k.lower()
                       for w in ("date", "time", "created", "posted", "active", "workex", "exp"))]
            print(f"    date/exp-ish keys: {dateish}")
            for k in dateish[:6]:
                print(f"      {k} = {str(o[k])[:60]}")

    print("\n" + "=" * 64)
    if best:
        print(f"WORKS: '{best[0]}' returned {best[2]} jobs")
        print(f"params: {best[1]}")
    else:
        print("NOTHING returned jobs. Either the API changed or it now needs auth.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
