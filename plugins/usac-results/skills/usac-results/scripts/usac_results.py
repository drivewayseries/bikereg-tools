#!/usr/bin/env python3
"""USA Cycling (Sport80) event results -> one CSV.

Usage:
    python3 usac_results.py "<event results URL>" [more URLs...] [-o OUTPUT_DIR]

Paste any results URL for the event, e.g.
    https://usacycling.sport80.com/pub/results/events/30723/d/crit/2026-06-07
The script finds every day/discipline of that event from it, then every race
in each, and writes one row per result (finishers, DNF, DNS, DQ...).

Standard library only. How it works: each results page embeds its data as JSON
in a `data-page` attribute (an Inertia.js app). That JSON lists the event's
days/disciplines and each race's id. Each race's full result list comes from
POST /pub/results/races/<race_id>/datatable?data=1. Gender comes from the
page's own Male/Female/Mixed filters, not from guessing at category names.
"""

import argparse
import csv
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = "https://usacycling.sport80.com"
USER_AGENT = "usac-results-csv/1.0 (python-urllib)"
MAX_EVENTS = 20
GENDERS = [("M", "M"), ("F", "F"), ("N", "Mixed")]
COLUMNS = ["Event", "Event ID", "Date", "Discipline", "Race Category", "Gender",
           "Place", "Name", "City", "State", "Team", "USAC #", "Bib", "Time", "Points"]
URL_RE = re.compile(r"/pub/results/events/(\d+)/d/([^/?#]+)/(\d{4}-\d{2}-\d{2})")
EXAMPLE_URL = "https://usacycling.sport80.com/pub/results/events/30723/d/crit/2026-06-07"

CERT_HELP = """\
Your Python has no CA certificates, so it can't verify usacycling.sport80.com.
This is common with python.org Python on macOS. Any one of these fixes it:
  1. Use macOS's own Python:  /usr/bin/python3 usac_results.py ...
  2. Run "Install Certificates.command" in /Applications/Python 3.x/
  3. pip3 install certifi   (this script uses it automatically)"""


class FetchError(Exception):
    pass


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def parse_page_html(text):
    """Return the Inertia props embedded in a Sport80 page, or None."""
    m = re.search(r'data-page="([^"]*)"', text)
    if not m:
        return None
    return json.loads(html.unescape(m.group(1))).get("props")


class Client:
    def __init__(self, delay):
        self.delay = delay
        self._last = 0.0
        self._ctx = _ssl_context()

    def _request(self, url, data=None, headers=None):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=hdrs,
                                     method="POST" if data is not None else "GET")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30, context=self._ctx) as resp:
                    self._last = time.time()
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                self._last = time.time()
                if e.code == 429 and attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise FetchError(f"{url}\n  HTTP Error {e.code}: {e.reason}") from e
            except urllib.error.URLError as e:
                raise FetchError(f"{url}\n  {e.reason}") from e
        raise FetchError(f"{url}\n  HTTP Error 429: rate limited after retries")

    def page(self, path):
        """GET a results page and return its embedded Inertia props."""
        props = parse_page_html(self._request(BASE + path))
        if props is None:
            raise FetchError(f"{BASE + path}\n  no data-page JSON found (Sport80 may have changed its pages)")
        return props

    def race(self, race_id):
        text = self._request(f"{BASE}/pub/results/races/{race_id}/datatable?data=1",
                             data=b"{}", headers={"Content-Type": "application/json"})
        return json.loads(text)


def unwrap(v):
    """Sport80 cells are plain values or {type: unset|hyperlink|..., value/text}."""
    if isinstance(v, dict):
        if v.get("type") == "unset":
            return ""
        for k in ("value", "text"):
            if k in v:
                return unwrap(v[k])
        return ""
    return "" if v is None else str(v).strip()


def split_location(loc):
    if "," in loc:
        city, state = loc.rsplit(",", 1)
        return city.strip(), state.strip()
    return loc, ""


def parse_targets(inputs):
    """URLs (any mix of args / lines) -> ([(event_id, discipline, date)], bad_tokens).

    Splits on whitespace only: Sport80 URLs often carry commas in ?text=.
    One URL per event is enough, so repeats of the same event collapse.
    """
    targets, seen, bad = [], set(), []
    for raw in inputs:
        for tok in raw.split():
            found = [m.groups() for m in URL_RE.finditer(tok)]
            if not found:
                bad.append(tok)
            for p in found:
                if p[0] not in seen:
                    seen.add(p[0])
                    targets.append(p)
    return targets, bad


def to_row(entry, name, event_id, date, discipline, category, gender):
    city, state = split_location(unwrap(entry.get("athlete_location")))
    return {
        "Event": name, "Event ID": event_id, "Date": date,
        "Discipline": discipline, "Race Category": category, "Gender": gender,
        "Place": unwrap(entry.get("place")), "Name": unwrap(entry.get("athlete_name")),
        "City": city, "State": state, "Team": unwrap(entry.get("team")),
        "USAC #": unwrap(entry.get("licence")), "Bib": unwrap(entry.get("bib")),
        "Time": unwrap(entry.get("time")), "Points": unwrap(entry.get("points")),
    }


def fetch_event(client, event_id, disc, date, log=print):
    """Return (event name, rows, problems, notes) for every day of one event."""
    props = client.page(f"/pub/results/events/{event_id}/d/{disc}/{date}")
    erp = props["event_results_page"]
    name = (erp.get("event_name") or props.get("title") or f"Event {event_id}").strip()
    days = []
    for f in erp.get("discipline_filters") or []:
        q = f.get("query_param") or {}
        if q.get("discipline") and q.get("race_date"):
            days.append((q["discipline"], q["race_date"], f.get("text") or q["discipline"]))
    if not days:
        days = [(disc, date, erp.get("discipline_name") or disc)]

    log(f"\n{name} (#{event_id}) - {erp.get('event_location', '')}")
    rows, problems, notes = [], [], []
    for d_disc, d_date, d_label in days:
        path = f"/pub/results/events/{event_id}/d/{d_disc}/{d_date}"
        day_props = props if (d_disc, d_date) == (disc, date) else client.page(path)
        races = day_props["event_results_page"].get("race_results_datatables") or []
        gender_of = {}
        for code, label in GENDERS:
            gp = client.page(f"{path}?gender={code}")
            for r in gp["event_results_page"].get("race_results_datatables") or []:
                gender_of[r["race_id"]] = label
        day_count = 0
        for r in races:
            rid, title = r["race_id"], (r.get("title") or "").strip()
            gender = gender_of.get(rid, "Unspecified")
            if gender == "Unspecified":
                notes.append(f"{d_date} {title}: not under any gender filter -> Unspecified")
            data = client.race(rid)
            entries = data.get("data") or []
            total = data.get("total")
            if total is None or int(total) != len(entries):
                problems.append(f"MISMATCH {d_date} {title} (race {rid}): "
                                f"Sport80 says {total}, got {len(entries)}")
            rows.extend(to_row(e, name, event_id, d_date, d_label, title, gender) for e in entries)
            day_count += len(entries)
        log(f"  {d_date} {d_label}: {len(races)} races, {day_count} results")
    return name, rows, problems, notes


def summarize(rows):
    placed = sum(1 for r in rows if r["Place"].isdigit())
    other, genders = {}, {}
    for r in rows:
        if not r["Place"].isdigit():
            k = r["Place"] or "(blank)"
            other[k] = other.get(k, 0) + 1
        genders[r["Gender"]] = genders.get(r["Gender"], 0) + 1
    riders = {r["USAC #"] or "name:" + r["Name"].lower() for r in rows}
    return {"results": len(rows), "riders": len(riders), "placed": placed,
            "other": other, "genders": genders}


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+", help="Sport80 event results URL(s)")
    ap.add_argument("-o", "--output-dir", default=".")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    args = ap.parse_args(argv)

    targets, bad = parse_targets(args.urls)
    if bad:
        for tok in bad:
            print(f"Can't read an event results URL from: {tok}", file=sys.stderr)
        print(f"Expected something like {EXAMPLE_URL}", file=sys.stderr)
        return 2
    if len(targets) > MAX_EVENTS:
        print(f"{len(targets)} events given; the limit is {MAX_EVENTS} per run.", file=sys.stderr)
        return 2

    client = Client(args.delay)
    all_rows, all_problems = [], []
    for event_id, disc, date in targets:
        try:
            name, rows, problems, notes = fetch_event(client, event_id, disc, date)
        except FetchError as e:
            msg = str(e)
            print(f"\nCould not fetch {msg}", file=sys.stderr)
            if "CERTIFICATE_VERIFY_FAILED" in msg:
                print(CERT_HELP, file=sys.stderr)
            elif "403" in msg:
                print("Sport80 refused the request (403), possibly a proxy or network block. "
                      "If the page opens in your browser, run this script from a normal Terminal.",
                      file=sys.stderr)
            elif "429" in msg:
                print("Sport80 is rate limiting. Re-run with --delay 3.", file=sys.stderr)
            print("Nothing was written.", file=sys.stderr)
            return 1
        s = summarize(rows)
        extra = "".join(f", {v} {k}" for k, v in sorted(s["other"].items()))
        print(f"  Total: {s['results']} results, {s['riders']} unique riders, {s['placed']} placed{extra}")
        print("  Gender: " + ", ".join(f"{k} {v}" for k, v in sorted(s["genders"].items())))
        for n in notes:
            print(f"  note: {n}")
        all_rows.extend(rows)
        all_problems.extend(problems)

    os.makedirs(args.output_dir, exist_ok=True)
    out = os.path.join(args.output_dir, "usac_results_" + "_".join(t[0] for t in targets) + ".csv")
    write_csv(all_rows, out)
    print(f"\nWrote {len(all_rows)} rows to {out}")
    if all_problems:
        for p in all_problems:
            print(p)
        return 1
    print("Verified: every race's row count matches Sport80's own total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
