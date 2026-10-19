"""Does Cutshort's `_id` decode to a real posting time?

The scraper reads `_id` straight from Cutshort's JSON, so the decoding has
never been exercised: Cutshort has saved 0 new rows twice, and its stored
`publicUrl` carries a slug rather than an ObjectId, so the backfill script
could not test it either.

This calls the same endpoint the scraper calls and decodes every `_id` it
gets back. It touches no filters, no dedupe and no database, so it reports
what Cutshort actually returns.

    python probe_cutshort.py
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, ".")
from utils.posted import from_object_id, normalise_remote_type, parse_experience

API = "https://cutshort.io/backend-api/webpage/jobs/{slug}"
SLUGS = ["frontend-developer-jobs", "backend-developer-jobs"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://cutshort.io/jobs",
}


def main() -> int:
    now = datetime.now(timezone.utc)
    total = decoded = 0
    ages = []

    for slug in SLUGS:
        url = API.format(slug=slug)
        print("=" * 68)
        print(slug)
        print("=" * 68)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"  request failed: {type(exc).__name__}: {exc}\n")
            continue

        if not (data.get("success") and "data" in data):
            print(f"  unexpected response shape. top-level keys: {list(data)[:10]}\n")
            continue

        jobs = data["data"].get("pageData", {}).get("jobs", [])
        print(f"  {len(jobs)} jobs returned\n")
        if jobs:
            print(f"  keys on job[0]: {sorted(jobs[0])}\n")

        for j in jobs[:8]:
            total += 1
            oid = j.get("_id")
            iso = from_object_id(oid)
            headline = (j.get("headline") or "")[:46]
            print(f"  {headline}")
            print(f"    _id        : {oid!r}")
            if iso:
                decoded += 1
                hrs = (now - datetime.fromisoformat(iso)).total_seconds() / 3600
                ages.append(hrs)
                when = f"{hrs:.1f}h ago" if hrs < 48 else f"{hrs/24:.1f}d ago"
                print(f"    decodes to : {iso}   ({when})")
            else:
                print("    decodes to : NOTHING. Either absent or not an ObjectId.")
            exp = j.get("expRange") or {}
            print(f"    exp        : {parse_experience(exp.get('min'), exp.get('max'))}")
            print(f"    remoteType : {j.get('remoteType')!r} -> "
                  f"{normalise_remote_type(j.get('remoteType'))!r}")
            print(f"    publicUrl  : {(j.get('publicUrl') or '')[:60]}")
            print()

    print("=" * 68)
    print(f"{decoded} of {total} jobs produced a posting date")
    if ages:
        ages.sort()
        print(f"ages: newest {min(ages)/24:.1f}d, median {ages[len(ages)//2]/24:.1f}d, "
              f"oldest {max(ages)/24:.1f}d")
    print("=" * 68)
    if total == 0:
        print("VERDICT: no jobs came back, so nothing was tested.")
    elif decoded == total:
        print("VERDICT: every _id decoded. The Cutshort date path works.")
    elif decoded:
        print("VERDICT: some decoded, some did not. Partial dates expected.")
    else:
        print("VERDICT: nothing decoded. The _id is not an ObjectId; the")
        print("         Cutshort date path does not work and should be")
        print("         reverted to returning None rather than guessing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
