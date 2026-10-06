#!/usr/bin/env python3
"""Offline tests for bikereg_registrations.py using real responses captured from BikeReg."""
import sys, os, tempfile, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bikereg_registrations as br

FAIL = []
def check(label, got, want):
    if got != want:
        FAIL.append("{}\n    got:  {!r}\n    want: {!r}".format(label, got, want))

# ---- real AR_GetWhosRegisteredGroups response (event 75223, trimmed) -----
GROUPS = {"athleticEvent": {
    "name": "Oatmeal Classic - State Championship Road Races",
    "presentationGroups": [
        {"groupName": "Wave 1", "registrationCount": {"count": 74},
         "categories": [
             {"raceRecId": "943776", "name": "Men's Pro/1/2", "registrationCount": {"count": 48}},
             {"raceRecId": "943785", "name": "Masters Men's 1/2/3/4 - 50+", "registrationCount": {"count": 26}}]},
        {"groupName": "Wave 2", "registrationCount": {"count": 1},
         "categories": [
             {"raceRecId": "943790", "name": "Women  Cat 3/4 &amp; Juniors", "registrationCount": {"count": 1}},
             # the same category listed under a second group must not be fetched twice
             {"raceRecId": "943776", "name": "Men's Pro/1/2", "registrationCount": {"count": 48}}]},
    ]}}

title, cats, total = br.parse_groups(GROUPS)
check("title", title, "Oatmeal Classic - State Championship Road Races")
check("category count (deduped)", len(cats), 3)
check("racerecid", cats[0]["racerecid"], "943776")
check("stated count", cats[0]["stated"], 48)
check("category name", cats[1]["name"], "Masters Men's 1/2/3/4 - 50+")
check("name whitespace/entities cleaned", cats[2]["name"], "Women Cat 3/4 & Juniors")
check("group kept", cats[2]["group"], "Wave 2")
check("stated total is sum of groups", total, 75)
check("unknown event", br.parse_groups({"athleticEvent": None}), None)
check("integer raceRecId", br.parse_groups({"athleticEvent": {"name": "x", "presentationGroups": [
    {"registrationCount": {"count": 1}, "categories": [
        {"raceRecId": 5, "name": "A", "registrationCount": {"count": 1}}]}]}})[1][0]["racerecid"], "5")

# ---- real AR_GetWhosRegisteredEntries response (trimmed) ------------------
ENTRIES = {"AR_EventCategories": [
    {"raceRecId": "943776", "eventEntries": [
        {"id": "13348940", "firstName": "James", "lastName": "Kennedy", "city": "Dallas",
         "state": "TX", "teamName": "United Cycling", "entryDate": "2026-08-24T22:18:52.197-04:00"},
        {"id": "13358668", "firstName": "Scott", "lastName": "Veggeberg", "city": "Austin",
         "state": "TX", "teamName": None, "entryDate": "2026-08-28T09:36:09.513-04:00"}]},
    {"raceRecId": "943785", "eventEntries": []},
]}
by = br.parse_entries(ENTRIES)
check("entries keyed by raceRecId", sorted(by), ["943776", "943785"])
check("entry count", len(by["943776"]), 2)
check("empty category kept", by["943785"], [])
check("reg date", br.reg_date("2026-08-24T22:18:52.197-04:00"), "2026-08-24")
check("reg date missing", br.reg_date(None), "")

# ---- scrape_event end to end against canned GraphQL responses -------------
class Resp:
    def __init__(self, payload):
        import json
        self.raw = json.dumps(payload).encode()
        self.headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()
    def read(self): return self.raw
    def __enter__(self): return self
    def __exit__(self, *a): return False

class Opener:
    def __init__(self, groups, entries):
        self.groups, self.entries, self.requests = groups, entries, []
    def open(self, req, timeout=None):
        import json
        v = json.loads(req.data)["variables"]
        self.requests.append(v)
        check("POSTs JSON", req.get_header("Content-type"), "application/json")
        return Resp({"data": self.groups if "eventID" in v else self.entries})

GOOD = {"athleticEvent": {"name": "Test Event", "presentationGroups": [
    {"groupName": "W1", "registrationCount": {"count": 2}, "categories": [
        {"raceRecId": "943776", "name": "Men's Pro/1/2", "registrationCount": {"count": 2}},
        {"raceRecId": "943785", "name": "Kids Race", "registrationCount": {"count": 0}}]}]}}
op = Opener(GOOD, ENTRIES)
res = br.scrape_event(op, "75223", br.Throttle(0), quiet=True)
check("scrape: no problems", res["problems"], [])
check("scrape: entries", [(e["first"], e["gender"], e["date"]) for e in res["entries"]],
      [("James", "M", "2026-08-24"), ("Scott", "M", "2026-08-28")])
check("scrape: null team becomes blank", res["entries"][1]["team"], "")
check("scrape: event id sent as int", op.requests[0], {"appType": "BIKEREG", "eventID": 75223})
check("scrape: categories batched", op.requests[1], {"appType": "BIKEREG", "categoryIds": [943776, 943785]})

BAD = {"athleticEvent": {"name": "Test Event", "presentationGroups": [
    {"groupName": "W1", "registrationCount": {"count": 3}, "categories": [
        {"raceRecId": "943776", "name": "Men's Pro/1/2", "registrationCount": {"count": 3}},
        {"raceRecId": "999999", "name": "Missing", "registrationCount": {"count": 0}}]}]}}
res = br.scrape_event(Opener(BAD, ENTRIES), "75223", br.Throttle(0), quiet=True)
check("scrape: mismatches reported", res["problems"], [
    "Men's Pro/1/2: BikeReg says 3 entries, got 2",
    "Missing: BikeReg returned no entry list",
    "event total: BikeReg says 3, got 2"])

big = {"athleticEvent": {"name": "Big", "presentationGroups": [
    {"groupName": "G", "registrationCount": {"count": 0}, "categories": [
        {"raceRecId": str(i), "name": "C%d" % i, "registrationCount": {"count": 0}} for i in range(1, 24)]}]}}
op = Opener(big, {"AR_EventCategories": [{"raceRecId": str(i), "eventEntries": []} for i in range(1, 24)]})
br.scrape_event(op, "1", br.Throttle(0), quiet=True)
check("23 categories -> 3 entry requests", [len(r["categoryIds"]) for r in op.requests[1:]], [10, 10, 3])

for payload, label in [({"athleticEvent": None}, "unknown event exits"),
                       ({"athleticEvent": {"name": "x", "presentationGroups": []}}, "no categories exits")]:
    try:
        br.scrape_event(Opener(payload, {}), "1", br.Throttle(0), quiet=True)
        check(label, "no raise", "SystemExit")
    except SystemExit:
        pass

class ErrOpener(Opener):
    def open(self, req, timeout=None):
        return Resp({"errors": [{"message": "Cannot query field \"name\""}]})
try:
    br.gql(ErrOpener(None, None), "q", {}); check("graphql errors exit", "no raise", "SystemExit")
except SystemExit as exc:
    check("graphql error surfaced", "Cannot query field" in str(exc), True)

# ---- gender rules -------------------------------------------------------
check("women", br.category_gender("Omnium Registration - Women Cat 3/4"), "F")
check("men/open", br.category_gender("Saturday Road Race - Men/Open Pro/1/2 - Saturday"), "M")
check("girls", br.category_gender("Girls Under 15"), "F")
check("boys/open", br.category_gender("Boys/Open Under 15"), "M")
check("kids race", br.category_gender("Kids Race p/b Woom Bikes - Saturday"), "")
check("womens possessive", br.category_gender("Womens Cat 4"), "F")

# the real La Primavera case: 6 women entered in the Sunday Men/Open Pro field
entries = [
    {"first": "Grace", "last": "Arlandson", "category": "Women Pro/1/2/3"},
    {"first": "Grace", "last": "Arlandson", "category": "Men/Open Pro/1/2 - Sunday"},
    {"first": "Chris", "last": "Tolley", "category": "Men/Open Pro/1/2 - Sunday"},
    {"first": "Zoe", "last": "Kegel", "category": "Kids Race p/b Woom Bikes"},
]
entries, unresolved = br.assign_genders(entries)
check("combined-field woman stays F", [e["gender"] for e in entries], ["F", "F", "M", "Unspecified"])
check("unresolved categories", unresolved, ["Kids Race p/b Woom Bikes"])

# ---- CSV writing --------------------------------------------------------
rows = [{"first": 'Ann "AJ"', "last": "O'Neill, Jr", "category": "Women Cat 3/4",
         "gender": "F", "team": "A, B & C", "city": "Austin", "state": "TX", "date": "2026-02-02"}]
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "t.csv")
    br.write_csv(p, rows, br.FULL_COLUMNS)
    got = list(csv.reader(open(p)))
    check("csv header", got[0], br.FULL_COLUMNS)
    check("csv quoting round-trip", got[1],
          ['Ann "AJ"', "O'Neill, Jr", "Women Cat 3/4", "F", "A, B & C", "Austin", "TX", "2026-02-02"])

    rows2 = [dict(rows[0], event_title="Pace Bend", event_id="74062")]
    p2 = os.path.join(d, "t2.csv")
    br.write_csv(p2, rows2, br.MINIMAL_COLUMNS, with_event=True)
    got2 = list(csv.reader(open(p2)))
    check("combined header", got2[0], ["Event", "Event ID"] + br.MINIMAL_COLUMNS)
    check("combined row", got2[1][:3], ["Pace Bend", "74062", 'Ann "AJ"'])

# ---- arg parsing / slug -------------------------------------------------
check("pasted comma list", br.extract_event_ids(["74062,73918"]), ["74062", "73918"])
check("pasted newline list", br.extract_event_ids(["74062\n73918\n75001"]), ["74062", "73918", "75001"])
check("pasted mixed separators", br.extract_event_ids(["74062, 73918; 75001"]), ["74062", "73918", "75001"])
check("mixed urls and ids in one blob",
      br.extract_event_ids(["74062 https://www.bikereg.com/73918"]), ["74062", "73918"])
check("separate args still work", br.extract_event_ids(["74062", "73918"]), ["74062", "73918"])
check("dupes collapse across forms",
      br.extract_event_ids(["74062", "https://www.bikereg.com/74062", "74062"]), ["74062"])
check("trailing punctuation", br.extract_event_ids(["74062, 73918."]), ["74062", "73918"])
check("url with query keeps path id",
      br.parse_event_arg("https://www.bikereg.com/Confirmed/74062?rand=999"), "74062")
try:
    br.extract_event_ids(["none here"]); check("no ids raises", "no raise", "SystemExit")
except SystemExit:
    pass

check("bare id", br.parse_event_arg("74062"), "74062")
check("url", br.parse_event_arg("https://www.bikereg.com/73918"), "73918")
check("confirmed url", br.parse_event_arg("https://www.bikereg.com/Confirmed/74062"), "74062")
check("slug", br.slugify("THE METEOR Mercedes Benz of South Austin's PACE BEND WEEKEND"),
      "the-meteor-mercedes-benz-of-south-austin-s")
check("short slug untouched", br.slugify("La Primavera at Lago Vista"), "la-primavera-at-lago-vista")

# ---- TLS handling -------------------------------------------------------
import ssl, urllib.error
ctx = br.make_ssl_context()
check("ssl context verifies", ctx.verify_mode, ssl.CERT_REQUIRED)
check("hostname checking on", ctx.check_hostname, True)
check("opener builds", hasattr(br.make_opener(), "open"), True)

cert_exc = urllib.error.URLError(ssl.SSLCertVerificationError(
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
    "unable to get local issuer certificate (_ssl.c:1028)"))
check("cert error detected", br.is_cert_error(cert_exc), True)
check("cert error is not policy", br.is_policy_error(cert_exc), False)

policy_exc = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
check("policy error detected", br.is_policy_error(policy_exc), True)
check("policy error is not cert", br.is_cert_error(policy_exc), False)

plain_exc = urllib.error.URLError("timed out")
check("plain error is neither", (br.is_cert_error(plain_exc), br.is_policy_error(plain_exc)), (False, False))

# ---- throttle / rate limiting -------------------------------------------
t = br.Throttle(1.0)
check("throttle starts at base", t.delay, 1.0)
t.slow_down(); check("429 doubles the gap", t.delay, 2.0)
t.slow_down(); check("and again", t.delay, 4.0)
for _ in range(5): t.slow_down()
check("capped", t.delay, 6.0)
check("slowdowns counted", t.slowdowns, 7)
t0 = br.Throttle(0.0); t0.slow_down()
check("zero base still backs off", t0.delay, 1.0)
check("429 is retryable", 429 in br.RETRYABLE_STATUS, True)
check("404 is not retryable", 404 in br.RETRYABLE_STATUS, False)

class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, retry_after=None):
        hdrs = {} if retry_after is None else {"Retry-After": retry_after}
        super().__init__("http://x", code, "err", hdrs, None)

check("Retry-After seconds", br.retry_after_seconds(FakeHTTPError(429, "30")), 30.0)
check("Retry-After absent", br.retry_after_seconds(FakeHTTPError(429)), None)
check("Retry-After garbage", br.retry_after_seconds(FakeHTTPError(429, "soon")), None)
check("Retry-After on plain error", br.retry_after_seconds(urllib.error.URLError("x")), None)

# a 429 must not be misread as a policy block or a cert problem
check("429 not policy", br.is_policy_error(FakeHTTPError(429)), False)
check("429 not cert", br.is_cert_error(FakeHTTPError(429)), False)

# ---- output naming and event cap ----------------------------------------
check("single-event name", br.output_name(["74062"]).startswith("bikereg-74062-registrations-"), True)
check("multi-event name", br.output_name(["1", "2", "3"]).startswith("bikereg-3-events-registrations-"), True)
check("max events constant", br.MAX_EVENTS, 20)

# the CLI should refuse 21 events before touching the network
import subprocess
too_many = [str(70000 + i) for i in range(21)]
proc = subprocess.run([sys.executable, br.__file__] + too_many, capture_output=True, text=True)
check("21 events rejected", proc.returncode != 0 and "limit is 20" in proc.stderr, True)

# duplicates collapse (20 unique IDs passed twice must NOT trip the cap)
dupes = [str(70000 + i) for i in range(20)] * 2
proc = subprocess.run([sys.executable, br.__file__] + dupes + ["--help"], capture_output=True, text=True)
check("--help still works with 40 args", proc.returncode, 0)

if FAIL:
    print("FAILED ({}):\n".format(len(FAIL)) + "\n\n".join(FAIL))
    sys.exit(1)
print("all offline tests passed")
