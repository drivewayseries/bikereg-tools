#!/usr/bin/env python3
"""Offline tests for bikereg_registrations.py using real markup captured from BikeReg."""
import sys, os, tempfile, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bikereg_registrations as br

FAIL = []
def check(label, got, want):
    if got != want:
        FAIL.append("{}\n    got:  {!r}\n    want: {!r}".format(label, got, want))

# ---- real category markup from /Confirmed/74062 -------------------------
EVENT_PAGE = """
<html><head><title>THE METEOR Pace Bend Weekend Online Registration</title></head>
<body>
<div>Total Event Registrations: 1003</div>
<div class="categoryHeader">
<table class="mobiletable categoryName no-result-hide" racerecid="929043" iswaitlist="False" isvirtual="False">
  <thead><tr class="day"><th class="catName">
    <div><span>15 entries</span><a href="#" onclick="return false">-</a></div>
    <div class="notranslate">Omnium Registration - Moontower Racing's Men Open Cat 3/4</div>
  </th></tr></thead>
</table>
<div class="categoryEntries"></div>
</div>
<div class="categoryHeader">
<table class="mobiletable categoryName no-result-hide" racerecid="929044" iswaitlist="False" isvirtual="False">
  <thead><tr class="day"><th class="catName">
    <div><span>1 entry</span><a href="#" onclick="return false">+</a></div>
    <div class="notranslate">Saturday Road Race - Girls Under 15 - Saturday</div>
  </th></tr></thead>
</table>
</div>
</body></html>
"""

cp = br.CategoryParser(); cp.feed(EVENT_PAGE)
check("category count", len(cp.categories), 2)
check("racerecid", cp.categories[0]["racerecid"], "929043")
check("stated count", cp.categories[0]["stated"], 15)
check("category name", cp.categories[0]["name"],
      "Omnium Registration - Moontower Racing's Men Open Cat 3/4")
check("singular 'entry'", cp.categories[1]["stated"], 1)
check("name 2", cp.categories[1]["name"], "Saturday Road Race - Girls Under 15 - Saturday")
check("title", br.parse_event_title(EVENT_PAGE), "THE METEOR Pace Bend Weekend")
check("stated total", br.parse_stated_total(EVENT_PAGE), 1003)

# ---- real fragment markup from ConfirmedSingleRace.aspx ------------------
FRAGMENT = """
<div class="categoryEntries ">
<table class="registrationTable tablesorter mobiletable no-result-hide tablesorter-default" role="grid">
 <thead><tr class="header event-participant-header tablesorter-headerRow" role="row">
   <th class="header">FIRST</th><th>LAST</th><th>City</th><th>St</th><th>TEAM</th><th>DATE</th>
 </tr></thead>
 <tbody>
  <tr class="event-participant"><td>Nate</td><td>Beaver</td><td>Columbus</td><td>OH</td><td>Fount Cycling Guild</td><td>2/02</td></tr>
  <tr class="event-participant"><td>Miguel A</td><td>M&amp;Garay</td><td>Austin</td><td>TX</td><td>Team, Inc.</td><td>1/04</td></tr>
  <tr><td colspan="6"></td></tr>
 </tbody>
</table></div>
"""
tp = br.TableParser(); tp.feed(FRAGMENT)
check("row count (header + 2)", len(tp.rows), 3)
check("header row", [c.lower() for c in tp.rows[0]],
      ["first", "last", "city", "st", "team", "date"])
check("data row", tp.rows[1], ["Nate", "Beaver", "Columbus", "OH", "Fount Cycling Guild", "2/02"])
check("entity unescape", tp.rows[2][1], "M&Garay")
check("comma in team preserved", tp.rows[2][4], "Team, Inc.")

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
         "gender": "F", "team": "A, B & C", "city": "Austin", "state": "TX", "date": "2/02"}]
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "t.csv")
    br.write_csv(p, rows, br.FULL_COLUMNS)
    got = list(csv.reader(open(p)))
    check("csv header", got[0], br.FULL_COLUMNS)
    check("csv quoting round-trip", got[1],
          ['Ann "AJ"', "O'Neill, Jr", "Women Cat 3/4", "F", "A, B & C", "Austin", "TX", "2/02"])

    rows2 = [dict(rows[0], event_title="Pace Bend", event_id="74062")]
    p2 = os.path.join(d, "t2.csv")
    br.write_csv(p2, rows2, br.MINIMAL_COLUMNS, with_event=True)
    got2 = list(csv.reader(open(p2)))
    check("combined header", got2[0], ["Event", "Event ID"] + br.MINIMAL_COLUMNS)
    check("combined row", got2[1][:3], ["Pace Bend", "74062", 'Ann "AJ"'])

# ---- arg parsing / slug -------------------------------------------------
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
