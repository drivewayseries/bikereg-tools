#!/usr/bin/env python3
"""Helpers for the bike-shop-poster-mailer skill.

Subcommands:
  geocode ZIP                      -> ZIP centroid (lat, lng, city, state) as JSON
  grid --lat --lng --radius MI     -> search centers covering the radius, as JSON
  build --shops shops.json --config config.json --out labels.csv [--template auto]
                                   -> Click-N-Ship "Import Labels" CSV + review report (JSON on stdout)

The column layout comes from the USPS Click-N-Ship template. By default it is fetched
from this plugin's GitHub repo at run time, so if USPS changes the template, replacing
assets/Label_Template.csv on main updates every user. If GitHub can't be reached, or the
fetched file doesn't look like a label template, the bundled copy is used.
"""
import argparse, csv, io, json, math, re, ssl, sys, urllib.error, urllib.request
from pathlib import Path

BUNDLED_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "Label_Template.csv"
REPO_TEMPLATE = ("https://raw.githubusercontent.com/drivewayseries/bikereg-tools/main/"
                 "plugins/bike-shop-poster-mailer/skills/bike-shop-poster-mailer/assets/Label_Template.csv")
# Columns the builder writes; a template missing any of these is rejected.
REQUIRED_COLUMNS = [
    "Sender First Name", "Sender Last Name", "Sender Address Line 1", "Sender Address Town/City",
    "Sender State", "Sender ZIP Code", "Recipient Company/Org Name", "Recipient Address Line 1",
    "Recipient Address Town/City", "Recipient State", "Recipient ZIP Code",
    "Package Weight (lb)", "Package Weight (oz)", "Length", "Width", "Height",
]
EARTH_MI = 3958.8


# ---------------------------------------------------------------- network
def http_get(url, timeout=20):
    """GET with the system CA store, then certifi's, so it works behind corporate
    proxies (system store) and on Pythons that lack CA certificates (certifi)."""
    contexts = [ssl.create_default_context()]
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "bike-shop-poster-mailer"})
    err = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except urllib.error.URLError as e:
            if not isinstance(getattr(e, "reason", None), ssl.SSLError):
                raise
            err = e
    raise err


def parse_header(text):
    return next(csv.reader(io.StringIO(text.lstrip("\ufeff"))), [])


def load_template(spec="auto"):
    """Return (header, source). spec: auto | bundled | local path | https URL."""
    bundled = lambda why: (parse_header(BUNDLED_TEMPLATE.read_text(encoding="utf-8-sig")), why)
    if spec == "bundled":
        return bundled("bundled")
    if spec not in ("auto",) and not spec.startswith("http"):
        return parse_header(Path(spec).read_text(encoding="utf-8-sig")), f"local: {spec}"
    url = REPO_TEMPLATE if spec == "auto" else spec
    try:
        header = parse_header(http_get(url).decode("utf-8-sig"))
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"missing columns {missing}")
        return header, f"GitHub: {url}"
    except Exception as e:  # network, TLS, 404, or a malformed file
        if spec != "auto":
            sys.exit(f"Couldn't use template {url}: {e}")
        print(f"note: couldn't fetch the template from GitHub ({e}); using the bundled copy.",
              file=sys.stderr)
        return bundled("bundled (GitHub copy unavailable)")


# ---------------------------------------------------------------- geography
def haversine(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(a))


def geocode(zip5):
    zip5 = re.sub(r"\D", "", str(zip5))[:5]
    if len(zip5) != 5:
        sys.exit(f"Not a 5-digit ZIP: {zip5!r}")
    d = json.loads(http_get(f"https://api.zippopotam.us/us/{zip5}"))
    p = d["places"][0]
    return {"zip": zip5, "lat": float(p["latitude"]), "lng": float(p["longitude"]),
            "city": p["place name"], "state": p["state abbreviation"]}


def grid(lat, lng, radius_mi, cell_mi=None):
    """Search centers whose ~cell_mi bias circles overlap to cover the radius.
    Places returns at most 10 results per query, so bigger areas need more centers.
    Cell size grows with the radius so a big search stays around 15 centers or fewer."""
    if cell_mi is None:
        cell_mi = max(8.0, radius_mi / 2.5)
    if radius_mi <= cell_mi:
        return [{"lat": lat, "lng": lng, "bias_m": int(radius_mi * 1609.34) + 1000}]
    step = cell_mi * 1.4
    n = math.ceil(radius_mi / step)
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            dy, dx = i * step, j * step
            if math.hypot(dx, dy) > radius_mi + cell_mi * 0.5:
                continue
            plat = lat + dy / 69.0
            plng = lng + dx / (69.0 * math.cos(math.radians(lat)))
            pts.append({"lat": round(plat, 5), "lng": round(plng, 5),
                        "bias_m": int(cell_mi * 1609.34)})
    return pts


# ---------------------------------------------------------------- addresses
UNIT_RE = re.compile(
    r"\s+((?:Ste|Suite|Unit|Apt|Bldg|Building|Rm|Room|Fl|Floor|Spc|Space|Lot|Trlr)\.?\s*#?\s*[\w-]+"
    r"|#\s*[\w-]+)$",
    re.I)
STATE_ZIP_RE = re.compile(r"^([A-Z]{2})\s+(\d{5})(?:-(\d{4}))?$")


def parse_address(addr):
    """'2709 E 5th St. #130A, Austin, TX 78702, USA' -> dict of USPS fields, or None."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    if parts and parts[-1].upper() in {"USA", "US", "UNITED STATES"}:
        parts.pop()
    if len(parts) < 3:
        return None
    m = STATE_ZIP_RE.match(parts[-1].upper())
    if not m:
        return None
    state, zip5, plus4 = m.groups()
    city = parts[-2]
    street_parts = parts[:-2]
    # Line 1 is the part starting with a house number (or "PO Box"); anything else goes to line 2.
    idx = next((i for i, p in enumerate(street_parts)
                if re.match(r"^(\d|P\.?\s*O\.?\s*Box)", p, re.I)), 0)
    line1 = street_parts[idx]
    extra = [p for i, p in enumerate(street_parts) if i != idx]
    um = UNIT_RE.search(line1)
    if um:
        extra.insert(0, um.group(1).strip())
        line1 = line1[: um.start()].strip()
    return {"line1": line1, "line2": " ".join(extra), "city": city, "state": state,
            "zip": zip5 + (f"-{plus4}" if plus4 else "")}


# ---------------------------------------------------------------- package
def to_oz(weight):
    """'12 oz', '1.5 lb', '1 lb 4 oz', or a bare number (ounces) -> total ounces."""
    s = str(weight).lower().strip()
    lb = re.search(r"([\d.]+)\s*(?:lb|lbs|pound)", s)
    oz = re.search(r"([\d.]+)\s*(?:oz|ounce)", s)
    if not lb and not oz:
        return float(s)
    return (float(lb.group(1)) * 16 if lb else 0) + (float(oz.group(1)) if oz else 0)


def fmt(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else str(round(x, 2))


def package_fields(pkg):
    total_oz = math.ceil(to_oz(pkg["weight"]))  # round up so postage is never under-declared
    f = {"Package Weight (lb)": str(total_oz // 16), "Package Weight (oz)": str(total_oz % 16)}
    if pkg["style"].lower() == "tube":
        d, length = float(pkg["diameter"]), float(pkg["length"])
        f.update({"Length": fmt(length), "Width": fmt(d), "Height": fmt(d),
                  "Girth": fmt(math.ceil(math.pi * d * 10) / 10)})
    else:
        dims = sorted([float(pkg["length"]), float(pkg["width"]), float(pkg["height"])],
                      reverse=True)
        f.update({"Length": fmt(dims[0]), "Width": fmt(dims[1]), "Height": fmt(dims[2])})
    return f


# Click-N-Ship person-name fields accept letters plus ! @ # $ % ^ & * ( ) _ = + ? . ; ' " [ ] { } | < > ~
NAME_BAD = re.compile(r"[^A-Za-z !@#$%^&*()_=+?.;'\"\[\]{}|<>~]")


def clean_name(s):
    return re.sub(r"\s+", " ", NAME_BAD.sub(" ", s or "")).strip()


# ---------------------------------------------------------------- build
def build(shops_path, config_path, out_path, template="auto"):
    shops = json.loads(Path(shops_path).read_text())
    cfg = json.loads(Path(config_path).read_text())
    header, template_source = load_template(template)
    origin, radius = cfg["origin"], float(cfg["radius_mi"])
    s, pkg = cfg["sender"], package_fields(cfg["package"])
    country = cfg.get("country_value", "United States")
    excluded = {n.strip().lower() for n in cfg.get("exclude_names", [])}

    kept, dropped, seen_ids, seen_addr = [], [], set(), set()
    for shop in shops:
        name = (shop.get("name") or "").strip()
        pid = shop.get("place_id")
        a = parse_address(shop.get("address"))
        lat, lng = shop.get("lat"), shop.get("lng")
        has_coords = bool(lat) and bool(lng)
        dist = haversine(origin["lat"], origin["lng"], lat, lng) if has_coords else None
        why = None
        if name.lower() in excluded:
            why = "excluded by user"
        elif pid and pid in seen_ids:
            why = "duplicate"
        elif not a:
            why = "no usable street address"
        elif dist is None:
            why = "no coordinates"
        elif dist > radius:
            why = f"outside radius ({dist:.1f} mi)"
        else:
            key = (a["line1"].lower(), a["line2"].lower(), a["zip"][:5])
            if key in seen_addr:
                why = "duplicate address"
            seen_addr.add(key)
        if pid:
            seen_ids.add(pid)
        if why:
            if why != "duplicate":  # silent for plain repeats across queries
                dropped.append({"name": name, "reason": why})
            continue
        kept.append({"name": name, "addr": a, "dist": round(dist, 1)})

    kept.sort(key=lambda k: k["dist"])
    rows = []
    for k in kept:
        a = k["addr"]
        r = dict.fromkeys(header, "")
        r.update({
            "Reference ID": (cfg.get("reference") or "")[:30],
            "Shipping Date": cfg.get("ship_date", ""),
            "Sender First Name": clean_name(s.get("first_name")),
            "Sender Middle Initial": clean_name(s.get("middle_initial"))[:1],
            "Sender Last Name": clean_name(s.get("last_name")),
            "Sender Company/Org Name": s.get("company", ""),
            "Sender Address Line 1": s["line1"],
            "Sender Address Line 2": s.get("line2", ""),
            "Sender Address Town/City": s["city"],
            "Sender State": s["state"],
            "Sender Country": country,
            "Sender ZIP Code": s["zip"],
            "Sender Email": s.get("email", ""),
            "Sender Cell Phone": s.get("phone", ""),
            "Recipient Country": country,
            "Recipient First Name": clean_name(cfg.get("attn_first", "")),
            "Recipient Last Name": clean_name(cfg.get("attn_last", "")),
            "Recipient Company/Org Name": k["name"],
            "Recipient Address Line 1": a["line1"],
            "Recipient Address Line 2": a["line2"],
            "Recipient Address Town/City": a["city"],
            "Recipient State": a["state"],
            "Recipient ZIP Code": a["zip"],
            "Service Type": cfg.get("service_type", ""),
            "Package Type": cfg.get("package_type", ""),
        })
        r.update(pkg)
        rows.append(r)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    def one_line(a):
        return ", ".join(x for x in [a["line1"], a["line2"], a["city"],
                                     f'{a["state"]} {a["zip"]}'] if x)

    report = {
        "rows": len(rows),
        "csv": str(out_path),
        "template": template_source,
        "kept": [{"name": k["name"], "miles": k["dist"], "address": one_line(k["addr"])}
                 for k in kept],
        "dropped": dropped,
        "shop_names_with_digits_or_symbols": [k["name"] for k in kept if NAME_BAD.search(k["name"])],
        "package": pkg,
    }
    if len(rows) > 1000:
        report["warning"] = "Click-N-Ship imports at most 1,000 labels per file; split the CSV."
    print(json.dumps(report, indent=2))


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("geocode")
    g.add_argument("zip")
    gr = sub.add_parser("grid")
    gr.add_argument("--lat", type=float, required=True)
    gr.add_argument("--lng", type=float, required=True)
    gr.add_argument("--radius", type=float, required=True)
    b = sub.add_parser("build")
    b.add_argument("--shops", required=True)
    b.add_argument("--config", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--template", default="auto",
                   help="auto (GitHub, falling back to bundled) | bundled | path | https URL")
    a = ap.parse_args()
    if a.cmd == "geocode":
        print(json.dumps(geocode(a.zip)))
    elif a.cmd == "grid":
        pts = grid(a.lat, a.lng, a.radius)
        print(json.dumps({"count": len(pts), "centers": pts}, indent=2))
    else:
        build(a.shops, a.config, a.out, a.template)


if __name__ == "__main__":
    main()
