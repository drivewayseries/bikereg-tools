#!/usr/bin/env python3
"""Offline tests for mailer.py. Run: python3 scripts/test_mailer.py"""
import csv, json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mailer  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


# Addresses as Google Places returns them
cases = {
    "4510 Terry-O Ln Unit 126, Austin, TX 78745": ("4510 Terry-O Ln", "Unit 126", "Austin", "TX", "78745"),
    "2709 E 5th St. #130A, Austin, TX 78702": ("2709 E 5th St.", "#130A", "Austin", "TX", "78702"),
    "209 E Ben White Blvd Ste 204A, Austin, TX 78704, USA": ("209 E Ben White Blvd", "Ste 204A", "Austin", "TX", "78704"),
    "5701 W Slaughter Ln A-110, Austin, TX 78749": ("5701 W Slaughter Ln A-110", "", "Austin", "TX", "78749"),
    "Suite 5, 123 Main St, Round Rock, TX 78664-1234": ("123 Main St", "Suite 5", "Round Rock", "TX", "78664-1234"),
    "PO Box 44, Wimberley, TX 78676": ("PO Box 44", "", "Wimberley", "TX", "78676"),
}
for raw, want in cases.items():
    a = mailer.parse_address(raw)
    check(f"address: {raw}", a and (a["line1"], a["line2"], a["city"], a["state"], a["zip"]), want)
check("address without street is rejected", mailer.parse_address("Austin, TX"), None)

# Package math
check("tube: 9.2 oz rounds up, girth = pi*d",
      mailer.package_fields({"style": "tube", "diameter": 3, "length": 26, "weight": "9.2 oz"}),
      {"Package Weight (lb)": "0", "Package Weight (oz)": "10", "Length": "26", "Width": "3",
       "Height": "3", "Girth": "9.5"})
check("flat: dims sorted longest first, 1 lb 3 oz",
      mailer.package_fields({"style": "flat", "length": 12, "width": 19, "height": 0.5,
                             "weight": "1 lb 3 oz"}),
      {"Package Weight (lb)": "1", "Package Weight (oz)": "3", "Length": "19", "Width": "12",
       "Height": "0.5"})
check("weight in pounds", mailer.to_oz("1.5 lb"), 24.0)
check("name cleanup drops digits and hyphens", mailer.clean_name("Mary-Jo O'Neil 3rd"), "Mary Jo O'Neil rd")

# Geocode goes through http_get (and its CA fallback), not a bare urlopen
real_get, seen = mailer.http_get, []
mailer.http_get = lambda url, **kw: seen.append(url) or json.dumps({"places": [
    {"latitude": "30.2428", "longitude": "-97.7658", "place name": "Austin",
     "state abbreviation": "TX"}]}).encode()
check("geocode uses http_get", (mailer.geocode("78704-1234"), seen),
      ({"zip": "78704", "lat": 30.2428, "lng": -97.7658, "city": "Austin", "state": "TX"},
       ["https://api.zippopotam.us/us/78704"]))
mailer.http_get = real_get

# End-to-end build against the bundled template
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    shops = [
        {"name": "Near Shop", "place_id": "a", "lat": 30.25, "lng": -97.76,
         "address": "100 Main St Ste 2, Austin, TX 78704"},
        {"name": "Near Shop", "place_id": "a", "lat": 30.25, "lng": -97.76,
         "address": "100 Main St Ste 2, Austin, TX 78704"},
        {"name": "Far Shop", "place_id": "b", "lat": 31.0, "lng": -97.76,
         "address": "1 Far Rd, Temple, TX 76501"},
        {"name": "Mobile Repair", "place_id": "c", "lat": 0, "lng": 0, "address": ""},
        {"name": "Skip Me", "place_id": "d", "lat": 30.25, "lng": -97.76,
         "address": "200 Main St, Austin, TX 78704"},
    ]
    cfg = {"origin": {"lat": 30.2428, "lng": -97.7658}, "radius_mi": 10,
           "sender": {"first_name": "Jane", "last_name": "Rider", "line1": "1 Test Ave",
                      "city": "Austin", "state": "TX", "zip": "78704"},
           "package": {"style": "tube", "diameter": 3, "length": 26, "weight": "9 oz"},
           "exclude_names": ["skip me"]}
    (d / "shops.json").write_text(json.dumps(shops))
    (d / "config.json").write_text(json.dumps(cfg))
    out = d / "labels.csv"
    res = subprocess.run([sys.executable, str(HERE / "mailer.py"), "build", "--shops",
                          str(d / "shops.json"), "--config", str(d / "config.json"),
                          "--out", str(out), "--template", "bundled"],
                         capture_output=True, text=True)
    report = json.loads(res.stdout)
    rows = list(csv.reader(out.open()))
    template = next(csv.reader(mailer.BUNDLED_TEMPLATE.open(encoding="utf-8-sig")))
    check("header matches the USPS template exactly", rows[0], template)
    check("one row kept (dupe, far, no-address, excluded dropped)", report["rows"], 1)
    check("drop reasons", sorted(x["reason"].split(" (")[0] for x in report["dropped"]),
          ["excluded by user", "no usable street address", "outside radius"])
    r = dict(zip(rows[0], rows[1]))
    check("suite on line 2", (r["Recipient Address Line 1"], r["Recipient Address Line 2"]),
          ("100 Main St", "Ste 2"))
    check("service type left blank by default", r["Service Type"], "")
    check("bundled template has every required column",
          [c for c in mailer.REQUIRED_COLUMNS if c not in template], [])

print(f"\n{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
