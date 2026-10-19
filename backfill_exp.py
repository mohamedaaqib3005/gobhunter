"""Recover required experience from the titles of jobs already stored.

Naukri states experience in a dedicated element, which the scraper now reads,
but that only helps jobs scraped from here on. Many titles already in the
database state it too: "Java Full Stack Developer (2-3 Years)", "React
Developer 5+ yrs". This reads those without re-scraping anything.

Indeed states experience nowhere on its cards, so Indeed rows can only ever
be recovered from their titles, which is exactly what this does.

Read-only by default. Pass --write to apply.

    python backfill_exp.py
    python backfill_exp.py --write
"""

import sys

from database import get_conn
from utils.posted import parse_experience_text


def main() -> int:
    write = "--write" in sys.argv
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    missing = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE exp_min IS NULL"
    ).fetchone()[0]
    print(f"{total} jobs, {missing} with no experience recorded\n")

    print("by source:")
    for row in conn.execute(
        "SELECT source, COUNT(*) n,"
        " SUM(CASE WHEN exp_min IS NULL THEN 1 ELSE 0 END) blank"
        " FROM jobs GROUP BY source ORDER BY n DESC"
    ):
        print(f"  {row['source']:<12} {row['n']:>5} rows, {row['blank']:>5} without experience")

    rows = conn.execute(
        "SELECT id, source, title FROM jobs WHERE exp_min IS NULL"
    ).fetchall()

    found: list[tuple[int, int | None, int]] = []
    by_source: dict[str, int] = {}
    for r in rows:
        lo, hi = parse_experience_text(r["title"])
        if lo is None:
            continue
        found.append((lo, hi, r["id"]))
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1

    print(f"\nrecoverable from the title: {len(found)} of {len(rows)}")
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {src:<12} {n}")

    if found:
        print("\n  a sample of what would be written:")
        seen = set()
        for lo, hi, jid in found:
            if (lo, hi) in seen:
                continue
            seen.add((lo, hi))
            t = conn.execute("SELECT title FROM jobs WHERE id=?", (jid,)).fetchone()["title"]
            span = f"{lo}-{hi} yrs" if hi is not None else f"{lo}+ yrs"
            print(f"    {span:<12} <- {t[:58]}")
            if len(seen) >= 8:
                break

    if not write:
        print("\nDry run. Nothing written. Re-run with --write to apply.")
        conn.close()
        return 0
    if not found:
        print("\nNothing to write.")
        conn.close()
        return 0

    conn.executemany(
        "UPDATE jobs SET exp_min = ?, exp_max = ? WHERE id = ?",
        [(lo, hi, jid) for lo, hi, jid in found],
    )
    conn.commit()
    print(f"\nWrote experience to {len(found)} rows.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
