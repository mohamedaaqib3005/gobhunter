"""Remove rows scraped before posting dates and experience were captured.

Those rows carry neither, cannot gain either without being re-scraped, and
sink to the bottom of every view. Deleting them lets the next scrape bring
them back properly, because dedupe would otherwise skip them forever.

What is NEVER deleted:
  - anything you have touched (applied, bookmarked, dismissed, and so on)
  - anything that already has a posting date or an experience figure
  - anything from a source that cannot publish a date, Instahyre above all,
    since those rows are undated by nature rather than by age

Read-only by default. Pass --write to apply.

    python purge_stale.py
    python purge_stale.py --write
"""

import shutil
import sys
from datetime import datetime

from database import DB_PATH, get_conn

# Sources that publish no posting date at all. Rows from these are undated
# for ever, so "has no date" says nothing about how stale they are.
DATELESS_SOURCES = ("instahyre", "wellfound")

WHERE = (
    " WHERE (posted_date IS NULL OR posted_date = '')"
    " AND exp_min IS NULL"
    " AND status = 'new'"
    f" AND source NOT IN ({','.join('?' * len(DATELESS_SOURCES))})"
)


def main() -> int:
    write = "--write" in sys.argv
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    doomed = conn.execute(
        "SELECT COUNT(*) FROM jobs" + WHERE, DATELESS_SOURCES
    ).fetchone()[0]

    print(f"{total} jobs, {doomed} would be removed\n")
    print("by source:")
    for row in conn.execute(
        "SELECT source, COUNT(*) n,"
        " SUM(CASE WHEN (posted_date IS NULL OR posted_date = '')"
        "   AND exp_min IS NULL AND status = 'new' THEN 1 ELSE 0 END) stale"
        " FROM jobs GROUP BY source ORDER BY n DESC"
    ):
        note = "  (protected, publishes no date)" if row["source"] in DATELESS_SOURCES else ""
        keep = row["n"] - (0 if row["source"] in DATELESS_SOURCES else row["stale"])
        print(f"  {row['source']:<12} {row['n']:>5} rows -> {keep:>5} kept{note}")

    kept_touched = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status != 'new'"
    ).fetchone()[0]
    print(f"\n{kept_touched} rows you have touched are protected regardless.")

    if not write:
        print("\nDry run. Nothing deleted. Re-run with --write to apply.")
        conn.close()
        return 0
    if not doomed:
        print("\nNothing to delete.")
        conn.close()
        return 0

    backup = DB_PATH.with_suffix(f".db.backup-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(DB_PATH, backup)
    print(f"\nBacked up to {backup.name}")

    conn.execute("DELETE FROM jobs" + WHERE, DATELESS_SOURCES)
    conn.commit()
    conn.execute("VACUUM")
    left = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    print(f"Deleted {doomed} rows. {left} remain.")
    print("Now re-scrape to bring them back with dates and experience.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
