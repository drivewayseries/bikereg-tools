#!/usr/bin/env python3
"""
Pull public registration lists from BikeReg event pages into CSV.

    python3 bikereg_registrations.py 74062
    python3 bikereg_registrations.py 74062 73918 https://www.bikereg.com/75001
    python3 bikereg_registrations.py 74062 73918 -o ~/Desktop --separate

Up to 20 events per run. Output is ONE CSV with every event appended, with
Event and Event ID columns first so rows stay attributable. --separate adds a
per-event CSV next to it. Standard library only -- no pip install, no browser.

How it works
------------
BikeReg's "Who's Registered" page (/Confirmed/<eventID>) ships every category
as a <table class="categoryName" racerecid="..."> carrying the category name
and its entry count. The riders themselves load per category from

    /Registration/ConfirmedSingleRace.aspx?RaceRecID=<rrid>&EventID=<eid>&...

which returns a plain HTML fragment. So this is two ordinary GETs per event --
one for the page, one per category -- with no JavaScript involved.

Verification is not optional: each category's scraped row count is checked
against the count BikeReg prints on the page, and the total against
"Total Event Registrations". A mismatch exits non-zero rather than writing a
CSV you would have to second-guess.
"""

import argparse
import csv
import html
import http.cookiejar
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://www.bikereg.com"
CONFIRMED_URL = BASE + "/Confirmed/{eid}"
CATEGORY_URL = (
    BASE + "/Registration/ConfirmedSingleRace.aspx"
    "?eid=&team=&RaceRecID={rrid}&EventID={eid}&SearchTerm=&rand={rand}&bogus=false"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

MINIMAL_COLUMNS = ["First Name", "Last Name", "Race Category", "Gender"]
FULL_COLUMNS = MINIMAL_COLUMNS + ["Team", "City", "State", "Reg Date"]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    return opener


def fetch(opener, url, tries=3):
    last = None
    for attempt in range(tries):
        try:
            with opener.open(url, timeout=45) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise SystemExit(
        "Could not fetch {}\n  {}\n\n"
        "If this is a proxy/403 error you are probably running inside a sandbox "
        "whose egress policy blocks bikereg.com. Run this script from a normal "
        "terminal instead.".format(url, last)
    )


# --------------------------------------------------------------------------
# HTML parsing (stdlib)
# --------------------------------------------------------------------------

def clean(text):
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class CategoryParser(HTMLParser):
    """Collect (racerecid, category name, stated entry count) from the event page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.categories = []
        self._depth = 0
        self._attrs = None
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag != "table":
            return
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self._depth == 0 and "categoryName" in classes:
            self._depth = 1
            self._attrs = a
            self._chunks = []
        elif self._depth:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag != "table" or not self._depth:
            return
        self._depth -= 1
        if self._depth == 0:
            self._flush()

    def handle_data(self, data):
        if self._depth:
            self._chunks.append(data)

    def _flush(self):
        text = clean(" ".join(self._chunks))
        count = re.search(r"(\d+)\s+entr(?:y|ies)", text, re.I)
        name = re.sub(r"^\s*\d+\s+entr(?:y|ies)\s*", "", text, flags=re.I)
        name = re.sub(r"^\s*[-+]\s*", "", name).strip()
        rrid = self._attrs.get("racerecid")
        if rrid and name:
            self.categories.append(
                {
                    "racerecid": rrid,
                    "name": name,
                    "stated": int(count.group(1)) if count else None,
                    "waitlist": (self._attrs.get("iswaitlist") or "").lower() == "true",
                }
            )
        self._attrs, self._chunks = None, []


class TableParser(HTMLParser):
    """Return every row of the first registrationTable in a fragment, as cell text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._in_table = False
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and not self._in_table:
            classes = (dict(attrs).get("class") or "").split()
            if "registrationTable" in classes:
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(clean(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_event_title(page):
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"\s+Online Registration\s*$", "", clean(m.group(1)), flags=re.I)


def parse_stated_total(page):
    m = re.search(r"Total Event Registrations:\s*</?[^>]*>?\s*([\d,]+)", page, re.I)
    if not m:
        m = re.search(r"Total Event Registrations:\s*([\d,]+)", page, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def slugify(text, limit=45):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > limit:
        slug = slug[:limit].rsplit("-", 1)[0]  # don't cut mid-word
    return slug.strip("-") or "event"


# --------------------------------------------------------------------------
# Gender
# --------------------------------------------------------------------------

def category_gender(name):
    """BikeReg publishes no gender field -- it comes from the category name."""
    if re.search(r"\bwomen|\bwomens|\bgirls", name, re.I):
        return "F"
    if re.search(r"\bmen|\bmens|\bboys", name, re.I):
        return "M"
    return ""


def rider_key(first, last):
    return re.sub(r"\s+", " ", "{} {}".format(first, last)).strip().lower()


def assign_genders(entries):
    """
    Category name first, then a rider-level correction: someone entered in a
    Women's category who also shows up in a Men/Open field (combined starts are
    common) is F on every row. Returns (entries, unresolved_names).
    """
    female = {rider_key(e["first"], e["last"])
              for e in entries if category_gender(e["category"]) == "F"}
    unresolved = set()
    for e in entries:
        cat_g = category_gender(e["category"])
        if rider_key(e["first"], e["last"]) in female:
            e["gender"] = "F"
        elif cat_g:
            e["gender"] = cat_g
        else:
            e["gender"] = "Unspecified"
            unresolved.add(e["category"])
    return entries, sorted(unresolved)


# --------------------------------------------------------------------------
# Scrape
# --------------------------------------------------------------------------

def scrape_event(opener, eid, delay=0.3, quiet=False):
    def log(msg):
        if not quiet:
            print(msg, file=sys.stderr)

    page = fetch(opener, CONFIRMED_URL.format(eid=eid))
    title = parse_event_title(page)
    stated_total = parse_stated_total(page)

    cp = CategoryParser()
    cp.feed(page)
    categories = cp.categories
    if not categories:
        raise SystemExit(
            "No categories found for event {}. Check the event ID -- "
            "{} should show a 'Who's Registered' list.".format(eid, CONFIRMED_URL.format(eid=eid))
        )

    log("Event {}: {}".format(eid, title or "(untitled)"))
    log("  {} categories, {} stated registrations".format(
        len(categories), stated_total if stated_total is not None else "?"))

    entries, problems = [], []
    for i, cat in enumerate(categories, 1):
        url = CATEGORY_URL.format(
            rrid=cat["racerecid"], eid=eid, rand=random.randint(0, 999)
        )
        fragment = fetch(opener, url)
        tp = TableParser()
        tp.feed(fragment)
        rows = tp.rows
        if not rows:
            problems.append("{}: no table returned".format(cat["name"]))
            continue

        header = [c.lower() for c in rows[0]]
        def col(*names):
            for n in names:
                if n in header:
                    return header.index(n)
            return None

        fi, li = col("first"), col("last")
        ci, si = col("city"), col("st", "state")
        ti, di = col("team"), col("date", "reg date")
        if fi is None or li is None:
            problems.append("{}: unexpected columns {}".format(cat["name"], rows[0]))
            continue

        def cell(row, idx):
            return row[idx] if idx is not None and idx < len(row) else ""

        found = 0
        for row in rows[1:]:
            first, last = cell(row, fi), cell(row, li)
            if not first and not last:
                continue
            entries.append({
                "first": first,
                "last": last,
                "category": cat["name"],
                "team": cell(row, ti),
                "city": cell(row, ci),
                "state": cell(row, si),
                "date": cell(row, di),
            })
            found += 1

        if cat["stated"] is not None and found != cat["stated"]:
            problems.append("{}: page says {} entries, scraped {}".format(
                cat["name"], cat["stated"], found))

        log("  [{}/{}] {} ... {}".format(i, len(categories), cat["name"][:58], found))
        time.sleep(delay)

    if stated_total is not None and len(entries) != stated_total:
        problems.append("event total: page says {}, scraped {}".format(
            stated_total, len(entries)))

    entries, unresolved = assign_genders(entries)
    return {
        "event_id": eid,
        "title": title,
        "entries": entries,
        "categories": len(categories),
        "stated_total": stated_total,
        "problems": problems,
        "unresolved": unresolved,
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def write_csv(path, entries, columns, with_event=False):
    header = (["Event", "Event ID"] if with_event else []) + columns
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for e in entries:
            row = []
            if with_event:
                row += [e.get("event_title", ""), e.get("event_id", "")]
            for c in columns:
                row.append({
                    "First Name": e["first"],
                    "Last Name": e["last"],
                    "Race Category": e["category"],
                    "Gender": e["gender"],
                    "Team": e.get("team", ""),
                    "City": e.get("city", ""),
                    "State": e.get("state", ""),
                    "Reg Date": e.get("date", ""),
                }[c])
            w.writerow(row)


def summarize(result):
    entries = result["entries"]
    counts = {}
    for e in entries:
        counts[e["gender"]] = counts.get(e["gender"], 0) + 1
    unique = len({rider_key(e["first"], e["last"]) for e in entries})
    parts = ["{} entries".format(len(entries)),
             "{} unique riders".format(unique),
             "{} categories".format(result["categories"])]
    gender = " / ".join("{} {}".format(v, k) for k, v in sorted(counts.items()))
    return "  " + ", ".join(parts) + "  (" + gender + ")"


def parse_event_arg(arg):
    m = re.search(r"(\d{4,})", arg)
    if not m:
        raise SystemExit("Could not read an event ID out of: {}".format(arg))
    return m.group(1)


MAX_EVENTS = 20


def output_name(event_ids):
    stamp = time.strftime("%Y-%m-%d")
    if len(event_ids) == 1:
        return "bikereg-{}-registrations-{}.csv".format(event_ids[0], stamp)
    return "bikereg-{}-events-registrations-{}.csv".format(len(event_ids), stamp)


def main():
    ap = argparse.ArgumentParser(
        description="Pull public BikeReg registration lists into one CSV.",
        epilog="Example: python3 %(prog)s 74062 73918 -o ~/Desktop",
    )
    ap.add_argument("events", nargs="+",
                    help="event IDs or bikereg.com event URLs (up to {})".format(MAX_EVENTS))
    ap.add_argument("-o", "--out-dir", default=".",
                    help="where to write the CSV (default: current directory)")
    ap.add_argument("--separate", action="store_true",
                    help="also write one CSV per event alongside the combined file")
    ap.add_argument("--minimal", action="store_true",
                    help="only First Name, Last Name, Race Category, Gender "
                         "(Event and Event ID columns are always included)")
    ap.add_argument("--delay", type=float, default=0.3,
                    help="seconds between category requests (default: 0.3)")
    ap.add_argument("-q", "--quiet", action="store_true", help="suppress progress")
    args = ap.parse_args()

    # de-duplicate while preserving order, then enforce the cap
    event_ids = []
    for arg in args.events:
        eid = parse_event_arg(arg)
        if eid not in event_ids:
            event_ids.append(eid)
    if len(event_ids) > MAX_EVENTS:
        raise SystemExit("{} events requested; the limit is {} per run. "
                         "Split them into batches.".format(len(event_ids), MAX_EVENTS))

    columns = MINIMAL_COLUMNS if args.minimal else FULL_COLUMNS
    out_dir = os.path.expanduser(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    opener = make_opener()
    all_entries, all_problems = [], []

    for eid in event_ids:
        result = scrape_event(opener, eid, delay=args.delay, quiet=args.quiet)
        for e in result["entries"]:
            e["event_title"] = result["title"]
            e["event_id"] = eid
        all_entries += result["entries"]

        print("\n{} ({})".format(result["title"] or "Event", eid))
        print(summarize(result))
        if result["unresolved"]:
            print("  note: no gender in category name for: {}".format(
                ", ".join(result["unresolved"])))
        for p in result["problems"]:
            print("  MISMATCH: {}".format(p))
        all_problems += [(eid, p) for p in result["problems"]]

        if args.separate:
            sep = os.path.join(out_dir, "bikereg-{}-{}-registrations.csv".format(
                eid, slugify(result["title"] or "event")))
            write_csv(sep, result["entries"], columns, with_event=True)
            print("  -> {}".format(sep))

    path = os.path.join(out_dir, output_name(event_ids))
    write_csv(path, all_entries, columns, with_event=True)
    print("\nWrote {} entries from {} event(s) -> {}".format(
        len(all_entries), len(event_ids), path))

    if all_problems:
        print("\n{} verification problem(s) -- the CSV was written, but the "
              "counts do not match what BikeReg reports. Do not trust it "
              "until this is resolved.".format(len(all_problems)), file=sys.stderr)
        return 1
    print("Verified: every category matches BikeReg's own entry counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
