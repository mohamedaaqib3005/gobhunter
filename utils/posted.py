"""Turning each job site's idea of "when was this posted" into one timestamp.

Every source expresses posting time differently, and two of them do not
express it at all. What each one actually gives, verified against live
responses rather than assumed:

    Cutshort    the `_id` field is a MongoDB ObjectId whose first 4 bytes are
                a Unix timestamp. Exact, to the second, free.
    LinkedIn    a <time> element. Its text says "30 minutes ago" while fresh;
                its datetime attribute is day precision.
    Naukri      relative text only: "Just now", "3 days ago", "30+ days ago".
    Indeed      `createDate` in its job-card JSON, epoch milliseconds, to the
                millisecond. The search page itself prints no date at all (12
                of 12 cards checked), but the JSON behind it carries three
                date fields. Checked against jobs Indeed itself filtered to
                the last 24 and 72 hours:
                  createDate            agreed with Indeed's own relative
                                        label on every listing. USE THIS.
                  pubDate               systematically older, by up to 2 days,
                                        and always rounded to 05:00:00 UTC.
                                        A coarse date field, not a posting
                                        time. Do not use it.
                  formattedRelativeTime "2 days ago". Day precision, kept as
                                        the fallback if createDate vanishes.
    Instahyre   NOTHING. Both its search API and its per-job API were checked
                and neither carries a date. Use `is_active` instead, which
                answers the real question better than age does.

Everything here returns an ISO-8601 UTC string or None. None means "we do not
know", never "it is old". The dashboard falls back to created_at in that case
and labels it honestly.
"""

import re
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Cutshort: MongoDB ObjectId
# ---------------------------------------------------------------------------

_OBJECTID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

# Sanity window. An ObjectId prefix that decodes outside this range is not a
# posting date, it is a coincidence or a different id scheme, so we say so
# rather than inventing a job posted in 1973.
_MIN_PLAUSIBLE = datetime(2015, 1, 1, tzinfo=timezone.utc)


def from_object_id(oid: str | None) -> str | None:
    """Posting time from a MongoDB ObjectId's embedded timestamp.

    >>> from_object_id("6ad2060ef7ba8e021579552f")   # doctest: +ELLIPSIS
    '2026-10-16T11:10:06+00:00'
    """
    if not oid or not _OBJECTID_RE.match(oid.strip()):
        return None
    try:
        seconds = int(oid.strip()[:8], 16)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    # Allow a little clock skew into the future, reject the implausible past.
    if dt < _MIN_PLAUSIBLE or dt > _now() + timedelta(days=2):
        return None
    return _iso(dt)


# ---------------------------------------------------------------------------
# Indeed: epoch milliseconds out of its job-card JSON
# ---------------------------------------------------------------------------


def from_epoch_ms(value) -> str | None:
    """Posting time from a Unix timestamp in milliseconds.

    Indeed's job-card JSON carries `createDate` in epoch milliseconds. It is
    the field that agrees with Indeed's own "2 days ago" label; see the note
    on `pubDate` in the module docstring for why that one is not used.

    Seconds are accepted too, since a 10-digit value can only be seconds and
    treating it as milliseconds would place it in 1970.

    >>> from_epoch_ms(1760943443000)
    '2025-10-20T06:57:23+00:00'
    >>> from_epoch_ms(0) is None
    True
    """
    if value in (None, "", 0):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    # A seconds-based timestamp for any plausible date is 10 digits; a
    # milliseconds one is 13. Anything under this threshold is seconds.
    if num < 1e11:
        num *= 1000
    try:
        dt = datetime.fromtimestamp(num / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if dt < _MIN_PLAUSIBLE or dt > _now() + timedelta(days=2):
        return None
    return _iso(dt)


# ---------------------------------------------------------------------------
# Naukri, Indeed, LinkedIn: relative English text
# ---------------------------------------------------------------------------

_UNIT_SECONDS = {
    "second": 1, "sec": 1,
    "minute": 60, "min": 60,
    "hour": 3600, "hr": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,     # 30 days, good enough at this resolution
    "year": 31536000,
}

# "3 days ago", "30+ days ago", "about 2 hours ago", "1 month+ ago"
_RELATIVE_RE = re.compile(
    r"(?:about\s+|over\s+|more\s+than\s+)?"
    r"(\d+)\s*\+?\s*"
    r"(second|sec|minute|min|hour|hr|day|week|month|year)s?"
    r"\s*(?:ago|old|back)?",
    re.IGNORECASE,
)

# Phrases meaning "essentially now", which carry no number.
_FRESH_PHRASES = (
    "just now", "just posted", "just added", "posted today", "today",
    "few seconds ago", "a few seconds ago", "moments ago", "new",
)

_YESTERDAY_PHRASES = ("yesterday", "1 day ago", "a day ago", "one day ago")


def from_relative_text(text: str | None) -> str | None:
    """Posting time from a phrase like "3 days ago" or "Just posted".

    Returns None for anything unrecognised, so a site redesign degrades to
    "unknown" rather than to a wrong date.
    """
    if not text:
        return None
    low = " ".join(text.strip().lower().split())
    if not low:
        return None

    for phrase in _YESTERDAY_PHRASES:
        if phrase in low:
            return _iso(_now() - timedelta(days=1))

    for phrase in _FRESH_PHRASES:
        if phrase in low:
            return _iso(_now())

    match = _RELATIVE_RE.search(low)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = _UNIT_SECONDS.get(unit)
    if seconds is None:
        return None
    delta = timedelta(seconds=amount * seconds)
    # Guard against a parse like "2026 days ago" from stray page text.
    if delta > timedelta(days=365 * 5):
        return None
    return _iso(_now() - delta)


# ---------------------------------------------------------------------------
# LinkedIn: <time datetime="2026-10-18">30 minutes ago</time>
# ---------------------------------------------------------------------------

def from_linkedin_time(text: str | None, datetime_attr: str | None) -> str | None:
    """Best of LinkedIn's two values.

    The element's TEXT is preferred because it carries minutes and hours while
    a posting is fresh, which is exactly the window that matters. The datetime
    attribute is only day precision, so it is the fallback.
    """
    precise = from_relative_text(text)
    if precise:
        return precise
    return from_iso_date(datetime_attr)


def from_iso_date(value: str | None) -> str | None:
    """A plain "2026-10-18" or a full ISO timestamp."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt < _MIN_PLAUSIBLE or dt > _now() + timedelta(days=2):
        return None
    return _iso(dt)


# ---------------------------------------------------------------------------
# Experience ranges
# ---------------------------------------------------------------------------

def parse_experience(min_value=None, max_value=None) -> tuple[int | None, int | None]:
    """Normalise the experience range fields the sites publish.

    Cutshort gives `expRange: {min, max}`; Instahyre gives `workex_min` and
    `workex_max`. Both are plain integer years.
    """
    def one(v):
        if v is None:
            return None
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            return None
        return n if 0 <= n <= 50 else None

    lo, hi = one(min_value), one(max_value)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


# ---------------------------------------------------------------------------
# Cutshort remoteType -> our work-mode vocabulary
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Experience stated as text
# ---------------------------------------------------------------------------

# Naukri prints "2-5 Yrs" in <span class="expwdth">. Titles across every site
# carry the same idea in looser forms: "(2-3 Years)", "5+ yrs", "3 to 7 years".
#
# A unit word is REQUIRED. Without it "React 18 Developer" and "Angular14+"
# would parse as experience, and a wrong number is worse than a blank, because
# the max-experience filter would silently hide jobs on invented data.
_YEARS = r"(?:yrs?|years?)"
_EXP_RANGE_RE = re.compile(
    rf"(\d{{1,2}})\s*(?:-|–|—|to)\s*(\d{{1,2}})\s*\+?\s*{_YEARS}\b", re.IGNORECASE
)
_EXP_OPEN_RE = re.compile(rf"(\d{{1,2}})\s*\+\s*{_YEARS}\b", re.IGNORECASE)
_EXP_SINGLE_RE = re.compile(
    rf"(?:min(?:imum)?|at\s*least|over)?\s*(\d{{1,2}})\s*{_YEARS}\b", re.IGNORECASE
)

# Nobody advertises 60 years of experience; a match above this is a misread.
_MAX_YEARS = 50


def parse_experience_text(text: str | None) -> tuple[int | None, int | None]:
    """Required experience from a phrase, as (min, max) whole years.

    Returns (None, None) when nothing is confidently readable, which is the
    honest answer for the many titles that state no experience at all.

    >>> parse_experience_text("2-5 Yrs")
    (2, 5)
    >>> parse_experience_text("5+ years")
    (5, None)
    >>> parse_experience_text("React 18 Developer")
    (None, None)
    """
    if not text:
        return (None, None)
    s = str(text).strip()
    if not s:
        return (None, None)

    m = _EXP_RANGE_RE.search(s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        if hi > _MAX_YEARS:
            return (None, None)
        return (lo, hi)

    m = _EXP_OPEN_RE.search(s)
    if m:
        lo = int(m.group(1))
        return (lo, None) if lo <= _MAX_YEARS else (None, None)

    m = _EXP_SINGLE_RE.search(s)
    if m:
        lo = int(m.group(1))
        return (lo, None) if lo <= _MAX_YEARS else (None, None)

    return (None, None)


# A title is short, so any "N years" in it is almost certainly the
# requirement. A job description is long and full of other numbers: company
# age, notice periods, benefits, product versions. So in long text a match is
# only accepted when the word "experience" sits near it.
_EXP_CONTEXT_RE = re.compile(r"experien|\bexp\b", re.IGNORECASE)
_EXP_CANDIDATE_RE = re.compile(
    rf"\d{{1,2}}\s*(?:[-–—]|to)?\s*\d{{0,2}}\s*\+?\s*{_YEARS}\b", re.IGNORECASE
)


def parse_experience_from_description(
    text: str | None, window: int = 60
) -> tuple[int | None, int | None]:
    """Required experience from a full job description.

    Scans for every "N years" style phrase and keeps the first one with
    "experience" or "exp" within `window` characters either side. Returns
    (None, None) when nothing qualifies.

    >>> parse_experience_from_description("We have 25 years of history.")
    (None, None)
    >>> parse_experience_from_description("Must have 3-5 years of experience.")
    (3, 5)
    """
    if not text:
        return (None, None)
    s = str(text)
    for m in _EXP_CANDIDATE_RE.finditer(s):
        lo = max(0, m.start() - window)
        hi = min(len(s), m.end() + window)
        if not _EXP_CONTEXT_RE.search(s[lo:hi]):
            continue
        got = parse_experience_text(m.group(0))
        if got[0] is not None:
            return got
    return (None, None)


_REMOTE_TYPE_MAP = {
    "remote_only": "remote",
    "remote_ok": "remote",
    "fully_remote": "remote",
    "remote": "remote",
    "hybrid": "hybrid",
    "remote_not_okay": "onsite",
    "remote_not_ok": "onsite",
    "onsite": "onsite",
    "office": "onsite",
}


def normalise_remote_type(value: str | None) -> str | None:
    """Cutshort states work mode explicitly, so use it instead of guessing."""
    if not value:
        return None
    return _REMOTE_TYPE_MAP.get(str(value).strip().lower())
