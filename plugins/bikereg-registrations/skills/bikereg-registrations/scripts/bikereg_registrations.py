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
BikeReg's "Who's Registered" page (/Confirmed/<eventID>) is a React app that
loads its data from BikeReg's own GraphQL endpoint, /api/supergraph/gql. This
script sends the same two queries the page does:

    AR_GetWhosRegisteredGroups   event name, every category (raceRecId, name)
                                 and the entry count BikeReg shows for each
    AR_GetWhosRegisteredEntries  the riders for a batch of raceRecIds

So it is one POST for the category list plus one per batch of categories,
with no browser and no login.

Verification is not optional: each category's entry count is checked against
the count BikeReg reports for it, and the total against the sum of BikeReg's
group counts. A mismatch exits non-zero so you never get a CSV you would have
to second-guess.
"""

import argparse
import csv
import html
import http.cookiejar
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.bikereg.com"
CONFIRMED_URL = BASE + "/Confirmed/{eid}"
GQL_URL = BASE + "/api/supergraph/gql"
APP_TYPE = "BIKEREG"
CATEGORIES_PER_REQUEST = 10

# Same queries as the Who's Registered page's WhosRegistered.b.js bundle.
GROUPS_QUERY = """
query AR_GetWhosRegisteredGroups($appType: ApplicationType!, $eventID: Int!) {
  athleticEvent(appType: $appType, id: $eventID) {
    name
    presentationGroups(showClosedCategories: true, showTeamCategories: true, showWaitlists: true) {
      groupName
      registrationCount { count }
      categories { raceRecId name registrationCount { count } }
    }
  }
}
"""
ENTRIES_QUERY = """
query AR_GetWhosRegisteredEntries($appType: ApplicationType!, $categoryIds: [Int!]!) {
  AR_EventCategories(appType: $appType, categoryIds: $categoryIds) {
    raceRecId
    eventEntries { id firstName lastName city state teamName entryDate }
  }
}
"""
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

MINIMAL_COLUMNS = ["First Name", "Last Name", "Race Category", "Gender"]
FULL_COLUMNS = MINIMAL_COLUMNS + ["Team", "City", "State", "Reg Date"]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

CERT_HELP = """TLS certificate verification failed: this Python has no CA certificates to
check bikereg.com's certificate against. Verification is never disabled --
give Python a certificate bundle instead. On macOS, any one of these works:

  1. Use the Python that ships with macOS, which trusts the system keychain:
       /usr/bin/python3 {script} {args}

  2. Install the certificates your Python ships with (python.org installs
     include this one-off script; match the version you are running):
       open "/Applications/Python 3.13/Install Certificates.command"

  3. Install certifi -- this script picks it up automatically:
       python3 -m pip install --upgrade certifi
"""


def make_ssl_context():
    """
    A context that verifies certificates, with a fallback for Pythons that
    have no CA store. python.org builds on macOS don't use the system keychain
    and ship empty until "Install Certificates.command" is run; when the store
    is empty and certifi is importable, use that. Verification stays on either
    way -- an empty store is fixed by supplying certificates, never by skipping
    the check.
    """
    ctx = ssl.create_default_context()
    try:
        if ctx.cert_store_stats().get("x509_ca", 0) == 0:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass  # leave the default context; fetch() explains the failure
    return ctx


def make_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=make_ssl_context()),
        urllib.request.HTTPCookieProcessor(jar),
    )
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    return opener


RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class Throttle:
    """
    Paces requests, and slows down permanently when the server pushes back.

    A 429 is the site asking for fewer requests per second, so the fix is not
    only to wait out this one response but to space every later request more
    widely. Each 429 doubles the gap for the rest of the run.
    """

    def __init__(self, base):
        self.delay = max(0.0, base)
        self.slowdowns = 0

    def wait(self):
        if self.delay:
            time.sleep(self.delay + random.uniform(0, 0.2))

    def slow_down(self, cap=6.0):
        self.delay = min(max(self.delay * 2, 1.0), cap)
        self.slowdowns += 1


def retry_after_seconds(exc):
    """Honor a Retry-After header, in either the seconds or HTTP-date form."""
    header = None
    try:
        header = exc.headers.get("Retry-After")
    except Exception:
        return None
    if not header:
        return None
    try:
        return max(0.0, float(header.strip()))
    except ValueError:
        pass
    try:
        import email.utils
        when = email.utils.parsedate_to_datetime(header)
        import datetime
        now = datetime.datetime.now(when.tzinfo) if when.tzinfo else datetime.datetime.now()
        return max(0.0, (when - now).total_seconds())
    except Exception:
        return None


def is_cert_error(exc):
    reason = getattr(exc, "reason", None)
    return (isinstance(reason, ssl.SSLCertVerificationError)
            or isinstance(exc, ssl.SSLCertVerificationError)
            or "CERTIFICATE_VERIFY_FAILED" in str(exc))


def is_policy_error(exc):
    text = str(exc)
    return ("403" in text and "proxy" in text.lower()) or "Tunnel connection failed" in text


def fetch(opener, url, throttle=None, tries=5, quiet=True, data=None, headers=None):
    last = None
    rate_limited = False
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with opener.open(req, timeout=45) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE_STATUS or attempt == tries - 1:
                break
            if exc.code == 429:
                rate_limited = True
                if throttle is not None:
                    throttle.slow_down()
            # Wait what the server asked for, else back off 5, 10, 20, 40s
            pause = retry_after_seconds(exc)
            if pause is None:
                pause = min(5.0 * (2 ** attempt), 60.0)
            pause += random.uniform(0, 1.0)
            if not quiet:
                print("  ...{} from BikeReg, waiting {:.0f}s (attempt {}/{})".format(
                    exc.code, pause, attempt + 1, tries), file=sys.stderr)
            time.sleep(pause)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            # Certificate and policy failures never succeed on retry
            if is_cert_error(exc) or is_policy_error(exc):
                break
            if attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))

    head = "Could not fetch {}\n  {}\n\n".format(url, last)
    if rate_limited or getattr(last, "code", None) == 429:
        raise SystemExit(
            head + "BikeReg rate-limited this run and kept doing so after several "
            "waits. Re-run with a wider gap between requests:\n\n"
            "  --delay 3\n\n"
            "Large events need several requests each. If it "
            "keeps happening, wait a few minutes before trying again, or split the "
            "events across separate runs.")
    if is_cert_error(last):
        raise SystemExit(head + CERT_HELP.format(
            script=os.path.abspath(sys.argv[0]),
            args=" ".join(sys.argv[1:]) or "<event ids>"))
    if is_policy_error(last):
        raise SystemExit(
            head + "The network refused the connection by policy, not by error. You are "
            "probably inside a sandbox whose egress rules block bikereg.com. Run this "
            "script from a normal terminal instead.")
    raise SystemExit(
        head + "Check your network connection and that the event ID is valid. If "
        "bikereg.com loads in your browser but not here, the site may be blocking "
        "automated requests -- try again with --delay 1.")


# --------------------------------------------------------------------------
# HTML parsing (stdlib)
# --------------------------------------------------------------------------

def clean(text):
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def gql(opener, query, variables, throttle=None, quiet=True):
    """POST one GraphQL query and return its "data", failing loudly on errors."""
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    text = fetch(opener, GQL_URL, throttle, quiet=quiet, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        payload = json.loads(text)
    except ValueError:
        raise SystemExit("BikeReg's GraphQL endpoint returned something other than "
                         "JSON:\n  {}".format(text[:300]))
    if payload.get("errors"):
        raise SystemExit("BikeReg's GraphQL endpoint reported an error -- its schema "
                         "may have changed:\n  {}".format(
                             "; ".join(e.get("message", str(e)) for e in payload["errors"])))
    return payload.get("data") or {}


def parse_groups(data):
    """
    (event name, categories, stated total) from an AR_GetWhosRegisteredGroups
    result, or None when the event doesn't exist. Categories are deduplicated
    by raceRecId in page order; the total is the sum of BikeReg's group counts.
    """
    event = data.get("athleticEvent")
    if not event:
        return None
    categories, seen, stated_total = [], set(), 0
    for group in event.get("presentationGroups") or []:
        stated_total += ((group.get("registrationCount") or {}).get("count") or 0)
        for cat in group.get("categories") or []:
            rrid = str(cat.get("raceRecId") or "")
            if not rrid or rrid in seen:
                continue
            seen.add(rrid)
            count = (cat.get("registrationCount") or {}).get("count")
            categories.append({
                "racerecid": rrid,
                "name": clean(cat.get("name") or ""),
                "stated": int(count) if count is not None else None,
                "group": clean(group.get("groupName") or ""),
            })
    return clean(event.get("name") or ""), categories, stated_total


def parse_entries(data):
    """raceRecId -> list of raw entry dicts, from an AR_GetWhosRegisteredEntries result."""
    out = {}
    for cat in data.get("AR_EventCategories") or []:
        out[str(cat.get("raceRecId"))] = cat.get("eventEntries") or []
    return out


def reg_date(value):
    """'2026-08-24T22:18:52.197-04:00' -> '2026-08-24' (BikeReg's own timezone)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else (value or "")


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

def scrape_event(opener, eid, throttle, quiet=False):
    def log(msg):
        if not quiet:
            print(msg, file=sys.stderr)

    parsed = parse_groups(gql(opener, GROUPS_QUERY,
                              {"appType": APP_TYPE, "eventID": int(eid)}, throttle, quiet=quiet))
    if parsed is None:
        raise SystemExit(
            "BikeReg has no event {}. Check the event ID -- {} should show a "
            "'Who's Registered' list.".format(eid, CONFIRMED_URL.format(eid=eid)))
    title, categories, stated_total = parsed
    if not categories:
        raise SystemExit(
            "Event {} ({}) has no categories on its 'Who's Registered' list -- "
            "registration may not be open, or the organizer hides the list. "
            "See {}".format(eid, title or "untitled", CONFIRMED_URL.format(eid=eid)))

    log("Event {}: {}".format(eid, title or "(untitled)"))
    log("  {} categories, {} stated registrations".format(len(categories), stated_total))

    entries, problems = [], []
    done = 0
    for start in range(0, len(categories), CATEGORIES_PER_REQUEST):
        throttle.wait()
        batch = categories[start:start + CATEGORIES_PER_REQUEST]
        by_rrid = parse_entries(gql(
            opener, ENTRIES_QUERY,
            {"appType": APP_TYPE, "categoryIds": [int(c["racerecid"]) for c in batch]},
            throttle, quiet=quiet))

        for cat in batch:
            done += 1
            if cat["racerecid"] not in by_rrid:
                problems.append("{}: BikeReg returned no entry list".format(cat["name"]))
                continue
            found = 0
            for raw in by_rrid[cat["racerecid"]]:
                first, last = clean(raw.get("firstName") or ""), clean(raw.get("lastName") or "")
                if not first and not last:
                    continue
                entries.append({
                    "first": first,
                    "last": last,
                    "category": cat["name"],
                    "team": clean(raw.get("teamName") or ""),
                    "city": clean(raw.get("city") or ""),
                    "state": clean(raw.get("state") or ""),
                    "date": reg_date(raw.get("entryDate")),
                })
                found += 1

            if cat["stated"] is not None and found != cat["stated"]:
                problems.append("{}: BikeReg says {} entries, got {}".format(
                    cat["name"], cat["stated"], found))
            log("  [{}/{}] {} ... {}".format(done, len(categories), cat["name"][:58], found))

    if stated_total is not None and len(entries) != stated_total:
        problems.append("event total: BikeReg says {}, got {}".format(
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
    """One token -> one event ID. A bikereg URL keeps its path ID, not a query value."""
    token = arg.strip().strip(".,;")
    if "bikereg.com" in token.lower():
        m = re.search(r"bikereg\.com/(?:[A-Za-z]+/)?(\d{4,})", token, re.I)
        if m:
            return m.group(1)
    if token.isdigit():
        return token
    m = re.search(r"(\d{4,})", token)
    if not m:
        raise SystemExit("Could not read an event ID out of: {}".format(arg))
    return m.group(1)


def extract_event_ids(args):
    """
    Turn however the events arrived into an ordered, de-duplicated ID list.

    Accepts one ID per argument, but also a single pasted blob: commas,
    newlines, semicolons and spaces all separate. Splitting before matching
    matters -- "74062,73918" as one argument must not silently become one
    event.
    """
    ids = []
    for arg in args:
        for token in re.split(r"[\s,;]+", arg.strip()):
            if not token:
                continue
            eid = parse_event_arg(token)
            if eid not in ids:
                ids.append(eid)
    if not ids:
        raise SystemExit("No event IDs found in: {}".format(" ".join(args)))
    return ids


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
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds between requests (default: 1.0). "
                         "Raise it if BikeReg returns 429; the script also widens "
                         "the gap on its own when that happens.")
    ap.add_argument("-q", "--quiet", action="store_true", help="suppress progress")
    args = ap.parse_args()

    event_ids = extract_event_ids(args.events)
    if len(event_ids) > MAX_EVENTS:
        raise SystemExit("{} events requested; the limit is {} per run. "
                         "Split them into batches.".format(len(event_ids), MAX_EVENTS))

    columns = MINIMAL_COLUMNS if args.minimal else FULL_COLUMNS
    out_dir = os.path.expanduser(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    opener = make_opener()
    throttle = Throttle(args.delay)
    all_entries, all_problems = [], []

    for eid in event_ids:
        result = scrape_event(opener, eid, throttle, quiet=args.quiet)
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
    if throttle.slowdowns:
        print("  (BikeReg rate-limited {} time(s); request spacing widened to "
              "{:.1f}s. Next time start with --delay {:.0f}.)".format(
                  throttle.slowdowns, throttle.delay, throttle.delay))

    if all_problems:
        print("\n{} verification problem(s) -- the CSV was written, but the "
              "counts do not match what BikeReg reports. Do not trust it "
              "until this is resolved.".format(len(all_problems)), file=sys.stderr)
        return 1
    print("Verified: every category matches BikeReg's own entry counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
