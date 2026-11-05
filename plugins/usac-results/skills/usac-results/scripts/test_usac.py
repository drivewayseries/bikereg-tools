#!/usr/bin/env python3
"""Offline tests for usac_results.py using real responses captured from Sport80
(Saint Francis Tulsa Tough 2026, event 30723), trimmed to a few rows."""
import csv
import html
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usac_results as ur

FAIL = []


def check(label, got, want):
    if got != want:
        FAIL.append("{}\n    got:  {!r}\n    want: {!r}".format(label, got, want))


# ---- real event_results_page props (trimmed) --------------------------------
def day_filter(date, active):
    return {"active": active, "subtext": "Road", "text": "Criterium",
            "query_param": {"discipline": "crit", "race_date": date},
            "url": f"/pub/results/events/30723/d/crit/{date}?text=Saint%20Francis"}


FILTERS = [day_filter("2026-06-06", False), day_filter("2026-06-07", True)]
RACES = {
    "2026-06-06": [{"race_id": 664305, "title": "Pro/1/2 F", "url": "/pub/results/races/664305/datatable"}],
    "2026-06-07": [{"race_id": 664319, "title": "Cat 3 M", "url": "/pub/results/races/664319/datatable"},
                   {"race_id": 664328, "title": "Cat3/4/5 Junior 15-18", "url": "/pub/results/races/664328/datatable"},
                   {"race_id": 664399, "title": "Ride with Mayor", "url": "/pub/results/races/664399/datatable"}],
}
GENDER_OF = {664305: "F", 664319: "M", 664328: "N"}  # 664399 is under no filter


def props_for(date, gender=None):
    races = [r for r in RACES[date] if gender is None or GENDER_OF.get(r["race_id"]) == gender]
    return {"title": "Saint Francis Tulsa Tough", "event_results_page": {
        "discipline_filters": FILTERS, "discipline_name": "Criterium",
        "event_location": "Tulsa, Oklahoma", "event_name": "Saint Francis Tulsa Tough",
        "race_results_datatables": races}}


# ---- real datatable rows (trimmed; totals set to the trimmed length) ---------
CAT3 = {"total": 4, "page": None, "items_per_page": None, "data": [
    {"id": 8409011, "race_id": 664319, "athlete_id": 302359, "licence": 794134,
     "athlete_name": {"type": "hyperlink", "url": "/pub/athletes/794134/profile", "value": "Nathanael Hamilton"},
     "athlete_location": "Fort Worth, Texas", "bib": "448", "team": "Paragon Racing",
     "place": {"text": "1", "type": "gold"}, "time": "0", "splits": {"type": "unset"}, "points": "274.91"},
    {"id": 8409021, "race_id": 664319, "athlete_id": {"type": "unset"}, "licence": {"type": "unset"},
     "athlete_name": "Ahmad CHERINGTON", "athlete_location": {"type": "unset"}, "bib": "421", "team": "",
     "place": {"text": "11", "type": "result"}, "time": "0", "splits": {"type": "unset"},
     "points": {"type": "unset"}},
    {"id": 8409038, "race_id": 664319, "athlete_id": {"type": "unset"}, "licence": "10082204248",
     "athlete_name": "Daniel RAMOS", "athlete_location": {"type": "unset"}, "bib": "489",
     "team": "�pticas Deluxe", "place": {"text": "28", "type": "result"}, "time": "0",
     "splits": {"type": "unset"}, "points": {"type": "unset"}},
    {"id": 8409034, "race_id": 664319, "athlete_id": 297915, "licence": 779882,
     "athlete_name": {"type": "hyperlink", "url": "/pub/athletes/779882/profile", "value": "Marcelo Mendoza"},
     "athlete_location": "Monterrey, Nuevo Leon", "bib": "477", "team": "The Parks Law Firm All-Stars",
     "place": {"text": "DNS", "type": "result"}, "time": "0", "splits": {"type": "unset"}, "points": "367.89"},
]}
ONE = lambda rid, place, lic: {"total": 1, "data": [
    {"id": 1, "race_id": rid, "licence": lic, "athlete_name": {"type": "hyperlink", "value": "Rider " + str(lic)},
     "athlete_location": "Tulsa, Oklahoma", "bib": "1", "team": "Speakeasy",
     "place": {"text": place, "type": "result"}, "time": "0", "points": "300.00"}]}
DATATABLES = {664319: CAT3, 664328: ONE(664328, "DNF", 493783),
              664399: ONE(664399, "1", 794134), 664305: ONE(664305, "1", 600001)}


class FakeClient:
    def __init__(self, tables):
        self.tables, self.pages = tables, []

    def page(self, path):
        self.pages.append(path)
        base, _, q = path.partition("?gender=")
        return props_for(base.rsplit("/", 1)[1], q or None)

    def race(self, rid):
        return self.tables[rid]


# ---- cell unwrapping and location split -----------------------------------
check("unset", ur.unwrap({"type": "unset"}), "")
check("hyperlink", ur.unwrap(CAT3["data"][0]["athlete_name"]), "Nathanael Hamilton")
check("place medal", ur.unwrap({"text": "1", "type": "gold"}), "1")
check("int licence", ur.unwrap(794134), "794134")
check("None", ur.unwrap(None), "")
check("location", ur.split_location("MADISON, Wisconsin"), ("MADISON", "Wisconsin"))
check("foreign location", ur.split_location("Monterrey, Nuevo Leon"), ("Monterrey", "Nuevo Leon"))
check("no comma", ur.split_location("Tulsa"), ("Tulsa", ""))

# ---- URL parsing: the real pasted URL has a comma inside ?text= -------------
PASTED = ("https://usacycling.sport80.com/pub/results/events/30723/d/crit/2026-06-07"
          "?text=Saint%20Francis%20Tulsa%20Tough%20%E2%80%93%20Jun%205,%202026%20%28%2330723%29")
t, bad = ur.parse_targets([PASTED])
check("pasted url", (t, bad), ([("30723", "crit", "2026-06-07")], []))
t, bad = ur.parse_targets([PASTED + "\n" + ur.EXAMPLE_URL.replace("2026-06-07", "2026-06-05")
                           + " https://usacycling.sport80.com/pub/results/events/31000/d/road/2026-07-01"])
check("dedupe by event + multiple", [x[0] for x in t], ["30723", "31000"])
check("bad token", ur.parse_targets(["https://www.bikereg.com/74062"])[1], ["https://www.bikereg.com/74062"])

# ---- data-page HTML parsing -------------------------------------------------
page_json = json.dumps({"component": "Public/ResultsAndRankings/EventResultsPage",
                        "props": props_for("2026-06-07")})
html_text = '<div id="app" data-page="{}"></div>'.format(html.escape(page_json, quote=True))
check("data-page parsed", ur.parse_page_html(html_text)["event_results_page"]["event_name"],
      "Saint Francis Tulsa Tough")
check("no data-page", ur.parse_page_html("<html>Just a moment...</html>"), None)

# ---- full event: every day found, gender from filters, rows mapped ----------
fc = FakeClient(DATATABLES)
name, rows, problems, notes = ur.fetch_event(fc, "30723", "crit", "2026-06-07", log=lambda *a: None)
check("event name", name, "Saint Francis Tulsa Tough")
check("row count", len(rows), 7)
check("both days", sorted({r["Date"] for r in rows}), ["2026-06-06", "2026-06-07"])
check("no problems", problems, [])
check("unspecified note", len(notes), 1)
check("start page fetched once", fc.pages.count("/pub/results/events/30723/d/crit/2026-06-07"), 1)
check("gender filters fetched", sum("?gender=" in p for p in fc.pages), 6)
g = {r["Race Category"]: r["Gender"] for r in rows}
check("gender M", g["Cat 3 M"], "M")
check("gender F", g["Pro/1/2 F"], "F")
check("gender mixed juniors", g["Cat3/4/5 Junior 15-18"], "Mixed")
check("gender unspecified", g["Ride with Mayor"], "Unspecified")
first = rows[1]  # day 1 (06-06) comes first
check("row mapping", first, {
    "Event": "Saint Francis Tulsa Tough", "Event ID": "30723", "Date": "2026-06-07",
    "Discipline": "Criterium", "Race Category": "Cat 3 M", "Gender": "M", "Place": "1",
    "Name": "Nathanael Hamilton", "City": "Fort Worth", "State": "Texas", "Team": "Paragon Racing",
    "USAC #": "794134", "Bib": "448", "Time": "0", "Points": "274.91"})
unlicensed = [r for r in rows if r["Name"] == "Ahmad CHERINGTON"][0]
check("unlicensed rider", (unlicensed["USAC #"], unlicensed["City"], unlicensed["Points"]), ("", "", ""))

s = ur.summarize(rows)
check("summary placed", s["placed"], 5)
check("summary other", s["other"], {"DNS": 1, "DNF": 1})
check("unique riders (licence 794134 twice)", s["riders"], 6)

# ---- count mismatch is reported ---------------------------------------------
short = {**DATATABLES, 664319: dict(CAT3, total=5)}
_, _, problems, _ = ur.fetch_event(FakeClient(short), "30723", "crit", "2026-06-07", log=lambda *a: None)
check("mismatch reported", len(problems), 1)
check("mismatch text", problems[0].startswith("MISMATCH 2026-06-07 Cat 3 M (race 664319)"), True)

# ---- CSV ---------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "out.csv")
    ur.write_csv(rows, p)
    with open(p, encoding="utf-8-sig") as f:
        back = list(csv.DictReader(f))
    check("csv header", list(back[0].keys()), ur.COLUMNS)
    check("csv rows", len(back), 7)

if FAIL:
    print("FAILED {}:\n  ".format(len(FAIL)) + "\n  ".join(FAIL))
    sys.exit(1)
print("All tests passed.")
