#!/usr/bin/env python3
"""Analyze BikeReg registration CSVs for a post-race review deck.

Reads one or more CSVs — output of the bikereg-registrations plugin, or a
BikeReg promoter export — groups rows into editions (one per year of the race),
and writes analysis.json: KPIs, chart-ready series, tables, outliers, and data
quality notes. Standard library only.

    python3 analyze.py race_2024.csv race_2025.csv -o analysis.json
    python3 analyze.py all_years.csv --edition "2024=70011" --edition "2025=74062"

Every rider-identifying field (names, email, phone, address) stays inside this
process: the output holds only aggregates, team names, and place names.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

# --- column detection --------------------------------------------------------

# Normalized header (lowercase, alphanumerics only) -> canonical field. Order
# within each list matters only for readability; matching is exact on the
# normalized header, then the first unmatched header that *starts with* an
# alias, so "Category Entered / Merchandise Ordered" still maps to category.
ALIASES = {
    "event": ["event", "eventname", "eventtitle"],
    "event_id": ["eventid", "eventnumber", "eventno"],
    "category": ["racecategory", "category", "categoryentered", "categoryname",
                 "division", "race", "racename", "wave"],
    "gender": ["gender", "sex"],
    "team": ["team", "teamname", "club", "teamclub", "clubteam"],
    "first": ["firstname", "first", "givenname"],
    "last": ["lastname", "last", "surname", "familyname"],
    "name": ["name", "fullname", "ridername", "participant", "participantname"],
    "city": ["city", "town"],
    "state": ["state", "stateprovince", "province", "region", "st"],
    "zip": ["zip", "zipcode", "postalcode", "postcode", "zippostalcode"],
    "country": ["country"],
    "age": ["age", "raceage", "racingage", "ageonraceday"],
    "birthdate": ["birthdate", "dob", "dateofbirth", "birthday"],
    "reg_date": ["regdate", "registrationdate", "dateregistered", "registered",
                 "entrydate", "datesubmitted", "orderdate", "registrationtime",
                 "datetime", "date"],
    "price": ["price", "fee", "entryfee", "amount", "amountpaid", "paid",
              "total", "cost", "regfee"],
}
PREFIX_OK = {"category", "reg_date", "price", "team", "state", "zip"}

# Rows whose category looks like merchandise or add-ons, not a race entry.
NON_RACE = re.compile(
    r"\b(t-?shirts?|jerseys?|socks?|hats?|caps?|donations?|parking|camping|merch(andise)?|"
    r"bottles?|kit|pint glass|meal|lunch|dinner|bbq|insurance|one[- ]day license)\b", re.I)

UNATTACHED = re.compile(r"^(|none|n/?a|unattached|independent|indy|ind\.?|no team|-+)$", re.I)

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def norm_header(h):
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def detect_columns(headers, overrides):
    """Map canonical field -> actual header. Overrides are {field: header}."""
    mapping = {}
    used = set()
    for field, header in overrides.items():
        if header not in headers:
            raise SystemExit(f"--map {field}={header!r}: no such column. Columns are: {', '.join(headers)}")
        mapping[field] = header
        used.add(header)
    normed = {h: norm_header(h) for h in headers}
    for field, aliases in ALIASES.items():
        if field in mapping:
            continue
        for alias in aliases:
            hit = next((h for h in headers if h not in used and normed[h] == alias), None)
            if hit:
                mapping[field] = hit
                used.add(hit)
                break
    for field in PREFIX_OK:
        if field in mapping:
            continue
        for alias in ALIASES[field]:
            if len(alias) < 4:
                continue
            hit = next((h for h in headers if h not in used and normed[h].startswith(alias)), None)
            if hit:
                mapping[field] = hit
                used.add(hit)
                break
    return mapping


# --- value parsing -----------------------------------------------------------

DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
    "%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p", "%m/%d/%y", "%m/%d/%y %H:%M", "%m/%d/%y %I:%M %p",
    "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y",
]


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    s = re.sub(r"\.\d+$", "", s)          # fractional seconds
    s = re.sub(r"(Z|[+-]\d\d:?\d\d)$", "", s)  # timezone suffix
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(s):
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_int(s):
    m = re.match(r"^\s*(\d{1,3})\s*$", s or "")
    return int(m.group(1)) if m else None


def gender_from_value(v):
    v = (v or "").strip().lower()
    if v in ("f", "female", "woman", "women", "w"):
        return "F"
    if v in ("m", "male", "man", "men"):
        return "M"
    if v in ("x", "nonbinary", "non-binary", "nb"):
        return "X"
    return None


def gender_from_category(cat):
    c = cat.lower()
    if re.search(r"\b(women|womens|woman|female|girls?|ladies|wmn|w\d)\b", c):
        return "F"
    if re.search(r"\b(men|mens|male|boys?)\b", c):
        return "M"
    if re.search(r"\b(non-?binary|nb)\b", c):
        return "X"
    return "U"


def category_family(cat):
    """Coarse grouping that survives year-to-year category renames."""
    c = cat.lower()
    if re.search(r"\b(kids?|youth|little|balance|strider|u\d{1,2}|1[0-4] ?& ?under|\d{1,2}-1[0-4])\b", c):
        return "Kids / Youth"
    if re.search(r"\b(junior|juniors|jr|j\d{2}|1[5-8] ?(-|&|to) ?1[5-9])\b", c):
        return "Juniors"
    if re.search(r"\b(masters?|[3-8]\d ?\+|[3-8]\d-[3-9]\d|[3-8]\d ?and over|vet(eran)?s?)\b", c):
        return "Masters"
    if re.search(r"\b(pro|elite|p ?/ ?1|p12|p ?1 ?/ ?2|cat(egory)? ?1( ?/ ?2)?|1 ?/ ?2 ?/ ?3)\b", c):
        return "Pro / Elite"
    if re.search(r"\b(cat(egory)? ?2|2 ?/ ?3|cat(egory)? ?3( ?/ ?4)?|3 ?/ ?4|cat(egory)? ?4|4 ?/ ?5)\b", c):
        return "Amateur (Cat 2–4)"
    if re.search(r"\b(beginner|novice|cat(egory)? ?5|first[- ]timer|intro|citizen|open|fun|rec(reational)?)\b", c):
        return "Beginner / Open"
    return "Other"


def norm_cat(cat):
    c = cat.lower().replace("&", "and")
    c = re.sub(r"[^a-z0-9+/]+", " ", c)
    c = re.sub(r"\s*/\s*", "/", c)
    return re.sub(r"\s+", " ", c).strip()


def norm_person(first, last, full):
    if first or last:
        s = f"{first} {last}"
    else:
        s = full or ""
    s = re.sub(r"[^a-z ]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip() or None


def norm_state(s, country):
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) == 2:
        return s.upper()
    return US_STATES.get(s.lower(), s.title())


def year_in(text):
    m = re.search(r"\b(19[89]\d|20\d\d)\b", text or "")
    return m.group(1) if m else None


# --- loading -----------------------------------------------------------------

def load(paths, overrides, exclude_re, include_nonrace):
    rows = []
    files = []
    excluded = Counter()
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            headers = [h for h in (reader.fieldnames or []) if h is not None]
            mapping = detect_columns(headers, overrides)
            if "category" not in mapping:
                raise SystemExit(
                    f"{path}: couldn't find a race category column. Columns are: {', '.join(headers)}\n"
                    f"Re-run with --map category=\"<column name>\".")
            files.append({"path": path, "name": os.path.basename(path), "columns": mapping,
                          "unmapped": [h for h in headers if h not in mapping.values()]})
            for raw in reader:
                g = lambda k: (raw.get(mapping[k]) or "").strip() if k in mapping else ""
                cat = g("category")
                if not cat:
                    excluded["(blank category)"] += 1
                    continue
                if exclude_re and exclude_re.search(cat):
                    excluded[cat] += 1
                    continue
                if not include_nonrace and NON_RACE.search(cat):
                    excluded[cat] += 1
                    continue
                age = parse_int(g("age"))
                bd = parse_date(g("birthdate"))
                rows.append({
                    "file": os.path.basename(path),
                    "event": g("event"),
                    "event_id": g("event_id"),
                    "category": re.sub(r"\s+", " ", cat),
                    "gender_raw": gender_from_value(g("gender")),
                    "team": g("team"),
                    "person": norm_person(g("first"), g("last"), g("name")),
                    "city": g("city").title() if g("city").isupper() or g("city").islower() else g("city"),
                    "state": norm_state(g("state"), g("country")),
                    "zip": g("zip")[:5],
                    "country": g("country"),
                    "age": age,
                    "birthdate": bd,
                    "reg_date": parse_date(g("reg_date")),
                    "reg_date_raw": g("reg_date"),
                    "price": parse_money(g("price")),
                })
    return rows, files, excluded


# --- editions ----------------------------------------------------------------

def assign_editions(rows, specs):
    """Return {label: [rows]} in chronological order, plus edition metadata."""
    groups = defaultdict(list)
    if specs:
        for r in rows:
            label = None
            for lab, tokens in specs:
                if r["event_id"] in tokens or r["file"] in tokens or r["event"] in tokens:
                    label = lab
                    break
            if label is None:
                raise SystemExit(
                    f"Row from {r['file']} (event {r['event_id'] or r['event'] or '?'}) matches no --edition. "
                    "Every event ID or file must be assigned to an edition.")
            groups[label].append(r)
    else:
        for r in rows:
            key = r["event_id"] or r["event"] or r["file"]
            groups[(r["file"], key)].append(r)
        # Label each group by year; fall back to file name.
        labelled = defaultdict(list)
        for (fname, key), grp in groups.items():
            evname = grp[0]["event"]
            dates = [r["reg_date"] for r in grp if r["reg_date"]]
            yr = year_in(evname) or year_in(fname) or (str(max(dates).year) if dates else None)
            labelled[yr or fname].append(((fname, key), grp))
        groups = {}
        for lab, members in labelled.items():
            if len(members) == 1:
                groups[lab] = members[0][1]
            else:
                for (fname, key), grp in members:
                    groups[f"{lab} · {grp[0]['event'] or key}"] = grp

    meta = []
    for label, grp in groups.items():
        dates = sorted(r["reg_date"] for r in grp if r["reg_date"])
        meta.append({
            "label": label,
            "event_names": sorted({r["event"] for r in grp if r["event"]}),
            "event_ids": sorted({r["event_id"] for r in grp if r["event_id"]}),
            "files": sorted({r["file"] for r in grp}),
            "first_reg": dates[0].isoformat() if dates else None,
            "last_reg": dates[-1].isoformat() if dates else None,
        })
    meta.sort(key=lambda m: (m["last_reg"] or "", m["label"]))
    return {m["label"]: groups[m["label"]] for m in meta}, meta


# --- analysis helpers --------------------------------------------------------

def pct(a, b):
    return None if not b else round((a - b) / b, 4)


def share(a, b):
    return None if not b else round(a / b, 4)


def top_n(counter, n, other_label="All others"):
    items = counter.most_common()
    head = items[:n]
    rest = sum(v for _, v in items[n:])
    if rest:
        head.append((other_label, rest))
    return head


def series_chart(kind, categories, series, number_format="#,##0", **extra):
    return {"kind": kind, "categories": categories,
            "series": [{"name": n, "values": v} for n, v in series],
            "number_format": number_format, **extra}


def resolve_genders(grp):
    """Use the gender column when present; otherwise infer from category name,
    then promote a rider to F if any of their entries is in a women's field."""
    has_col = any(r["gender_raw"] for r in grp)
    if has_col:
        for r in grp:
            r["gender"] = r["gender_raw"] or gender_from_category(r["category"])
        return "column"
    for r in grp:
        r["gender"] = gender_from_category(r["category"])
    women = {r["person"] for r in grp if r["gender"] == "F" and r["person"]}
    for r in grp:
        if r["person"] in women:
            r["gender"] = "F"
    return "category"


def age_of(r, event_date):
    if r["age"] is not None:
        return r["age"]
    if r["birthdate"] and event_date:
        bd = r["birthdate"]
        return event_date.year - bd.year - ((event_date.month, event_date.day) < (bd.month, bd.day))
    return None


AGE_BUCKETS = [("Under 18", 0, 17), ("18–29", 18, 29), ("30–39", 30, 39),
               ("40–49", 40, 49), ("50–59", 50, 59), ("60+", 60, 200)]

CURVE_POINTS = [84, 70, 56, 42, 35, 28, 21, 14, 10, 7, 5, 3, 2, 1, 0]


# --- main analysis -----------------------------------------------------------

def analyze(editions, meta, event_dates, home_state_arg, small_field):
    labels = list(editions)
    cur = labels[-1]
    prev = labels[-2] if len(labels) > 1 else None

    # One home state for every edition, so "local share" compares like with like.
    if not home_state_arg:
        all_states = Counter(r["state"] for grp in editions.values() for r in grp if r["state"])
        home_state_arg = all_states.most_common(1)[0][0] if all_states else None

    per = {}
    for m in meta:
        lab = m["label"]
        grp = editions[lab]
        gsrc = resolve_genders(grp)
        if lab in event_dates:
            ev_date, inferred = event_dates[lab], False
        elif m["last_reg"]:
            ev_date, inferred = date.fromisoformat(m["last_reg"]), True
        else:
            ev_date, inferred = None, True
        m["event_date"] = ev_date.isoformat() if ev_date else None
        m["event_date_inferred"] = inferred
        m["gender_source"] = gsrc

        cats = Counter(norm_cat(r["category"]) for r in grp)
        display = {}
        for r in grp:
            display.setdefault(norm_cat(r["category"]), r["category"])
        people = {r["person"] for r in grp if r["person"]}
        teams = Counter(r["team"].strip() for r in grp if not UNATTACHED.match(r["team"].strip()))
        states = Counter(r["state"] for r in grp if r["state"])
        cities = Counter(f"{r['city']}, {r['state']}" if r["state"] else r["city"]
                         for r in grp if r["city"])
        genders = Counter(r["gender"] for r in grp)
        families = Counter(category_family(r["category"]) for r in grp)
        fam_gender = defaultdict(Counter)
        for r in grp:
            fam_gender[category_family(r["category"])][r["gender"]] += 1
        prices = [r["price"] for r in grp if r["price"] is not None]
        ages = [a for a in (age_of(r, ev_date) for r in grp) if a is not None and 3 <= a <= 100]
        reg = [r["reg_date"] for r in grp if r["reg_date"]]
        days_out = [(ev_date - d).days for d in reg] if ev_date else []

        home = home_state_arg
        per[lab] = {
            "rows": grp, "cats": cats, "display": display, "people": people, "teams": teams,
            "states": states, "cities": cities, "genders": genders, "families": families,
            "fam_gender": fam_gender, "prices": prices, "ages": ages, "reg": reg,
            "days_out": days_out, "event_date": ev_date, "home": home,
        }

    flags = {
        "multi_edition": prev is not None,
        "has_names": all(per[l]["people"] for l in labels),
        "has_team": any(per[l]["teams"] for l in labels),
        "has_location": any(per[l]["states"] for l in labels),
        "has_city": any(per[l]["cities"] for l in labels),
        "has_reg_date": all(per[l]["reg"] for l in labels),
        "has_age": any(per[l]["ages"] for l in labels),
        "has_price": any(sum(per[l]["prices"]) > 0 for l in labels),
        "edition_count": len(labels),
    }
    flags["has_retention"] = flags["multi_edition"] and flags["has_names"]
    # Year-over-year versions of the optional fields need them in at least two editions.
    flags["price_yoy"] = sum(1 for l in labels if sum(per[l]["prices"]) > 0) >= 2
    flags["age_yoy"] = sum(1 for l in labels if per[l]["ages"]) >= 2

    # KPIs per edition
    kpi = {}
    for lab in labels:
        p = per[lab]
        n = len(p["rows"])
        fm = p["genders"]["F"] + p["genders"]["M"]
        in_state = p["states"].get(p["home"], 0) if p["home"] else 0
        located = sum(p["states"].values())
        kpi[lab] = {
            "entries": n,
            "riders": len(p["people"]) if p["people"] else None,
            "entries_per_rider": round(n / len(p["people"]), 2) if p["people"] else None,
            "categories": len(p["cats"]),
            "avg_field": round(n / len(p["cats"]), 1) if p["cats"] else None,
            "teams": len(p["teams"]) if p["teams"] else None,
            "unattached_share": share(n - sum(p["teams"].values()), n) if flags["has_team"] else None,
            "women_entries": p["genders"]["F"],
            "women_share": share(p["genders"]["F"], fm),
            "unspecified_gender": p["genders"]["U"],
            "states": len(p["states"]) if p["states"] else None,
            "home_state": p["home"],
            "in_state_share": share(in_state, located) if located else None,
            "revenue": round(sum(p["prices"]), 2) if p["prices"] else None,
            "avg_price": round(statistics.mean([x for x in p["prices"] if x > 0]), 2)
            if any(x > 0 for x in p["prices"]) else None,
            "median_age": statistics.median(p["ages"]) if p["ages"] else None,
            "median_days_out": statistics.median(p["days_out"]) if p["days_out"] else None,
            "final_week_share": share(sum(1 for d in p["days_out"] if d <= 7), len(p["days_out"]))
            if p["days_out"] else None,
        }

    kpi_delta = {}
    if prev:
        for k, v in kpi[cur].items():
            pv = kpi[prev][k]
            if isinstance(v, (int, float)) and isinstance(pv, (int, float)) and not isinstance(v, bool):
                if k.endswith("_share"):
                    kpi_delta[k] = {"abs": round(v - pv, 4), "unit": "pts"}
                else:
                    kpi_delta[k] = {"abs": round(v - pv, 2), "pct": pct(v, pv)}

    charts, tables, outliers = {}, {}, []
    c = per[cur]

    # Overview
    charts["entries_by_edition"] = series_chart(
        "column", labels,
        [("Entries", [kpi[l]["entries"] for l in labels])] +
        ([("Unique riders", [kpi[l]["riders"] for l in labels])] if flags["has_names"] else []))

    # Categories — current edition, with prior edition alongside
    cat_order = [k for k, _ in c["cats"].most_common()]
    cat_names = [c["display"][k] for k in cat_order]
    cat_series = []
    if prev:
        cat_series.append((prev, [per[prev]["cats"].get(k, 0) for k in cat_order]))
    cat_series.append((cur, [c["cats"][k] for k in cat_order]))
    charts["category_entries"] = series_chart("bar", cat_names, cat_series, top=15)

    fam_order = [f for f, _ in Counter({f: sum(per[l]["families"][f] for l in labels)
                                         for l in labels for f in per[l]["families"]}).most_common()]
    charts["family_by_edition"] = series_chart(
        "stacked_column", labels, [(f, [per[l]["families"][f] for l in labels]) for f in fam_order])
    tables["category_families"] = {
        "columns": ["Family", "Categories (this edition)"],
        "rows": [[f, ", ".join(sorted({c["display"][norm_cat(r["category"])] for r in c["rows"]
                                       if category_family(r["category"]) == f}))]
                 for f in fam_order if c["families"][f]],
    }

    small = [(c["display"][k], v, category_family(c["display"][k])) for k, v in c["cats"].most_common()
             if v < small_field]
    small.sort(key=lambda x: x[1])
    tables["small_fields"] = {"columns": ["Category", "Entries", "Family"],
                              "rows": [[a, b, f] for a, b, f in small]}
    if small:
        outliers.append({"type": "small_fields", "severity": len(small),
                         "text": f"{len(small)} of {len(c['cats'])} categories had fewer than "
                                 f"{small_field} entries in {cur}: "
                                 + ", ".join(f"{a} ({b})" for a, b, _ in small[:8])
                                 + ("…" if len(small) > 8 else "")})

    if prev:
        p = per[prev]
        shared = [k for k in c["cats"] if k in p["cats"]]
        movers = sorted(((c["display"][k], c["cats"][k] - p["cats"][k], c["cats"][k], p["cats"][k])
                         for k in shared), key=lambda x: x[1])
        big = [m for m in movers if m[1] != 0]
        pick = (big[:6] + [m for m in big[-6:] if m not in big[:6]]) if len(big) > 12 else big
        pick.sort(key=lambda x: x[1])
        charts["category_movers"] = series_chart(
            "bar_diverging", [m[0] for m in pick], [(f"Change vs {prev}", [m[1] for m in pick])],
            number_format="+#,##0;-#,##0;0")
        tables["category_yoy"] = {
            "columns": ["Category", prev, cur, "Change", "% change"],
            "rows": [[c["display"][k], p["cats"][k], c["cats"][k], c["cats"][k] - p["cats"][k],
                      pct(c["cats"][k], p["cats"][k])]
                     for k in sorted(shared, key=lambda k: -(c["cats"][k] - p["cats"][k]))],
        }
        new = [c["display"][k] for k in c["cats"] if k not in p["cats"]]
        gone = [p["display"][k] for k in p["cats"] if k not in c["cats"]]
        tables["category_changes"] = {"new": new, "dropped": gone}
        if new or gone:
            outliers.append({"type": "category_lineup", "severity": len(new) + len(gone),
                             "text": f"Category lineup changed: {len(new)} new in {cur}"
                                     f"{' (' + ', '.join(new[:5]) + ')' if new else ''}, "
                                     f"{len(gone)} not offered again"
                                     f"{' (' + ', '.join(gone[:5]) + ')' if gone else ''}. "
                                     "Renamed categories show up as one new + one dropped — check before "
                                     "reading these as real changes."})
        for name, d, cv, pv in movers:
            if pv >= 5 and abs(d) >= max(5, 0.5 * pv):
                outliers.append({"type": "category_swing", "severity": abs(d),
                                 "text": f"{name}: {pv} → {cv} ({'+' if d > 0 else ''}{d}, "
                                         f"{'+' if d > 0 else ''}{round(100 * d / pv)}%)"})
        fam_rows = []
        for f in fam_order:
            a, b = p["families"][f], c["families"][f]
            fam_rows.append([f, a, b, b - a, pct(b, a)])
        tables["family_yoy"] = {"columns": ["Family", prev, cur, "Change", "% change"], "rows": fam_rows}

    # Gender
    gkeys = [g for g in ("F", "M", "X", "U") if any(per[l]["genders"][g] for l in labels)]
    gname = {"F": "Women", "M": "Men", "X": "Non-binary", "U": "Unspecified"}
    charts["gender_by_edition"] = series_chart(
        "stacked_100", labels, [(gname[g], [per[l]["genders"][g] for l in labels]) for g in gkeys],
        number_format="0%")
    charts["women_share_trend"] = series_chart(
        "line", labels, [("Women's share of entries", [kpi[l]["women_share"] for l in labels])],
        number_format="0%")
    fam_with_women = [f for f in fam_order if c["fam_gender"][f]["F"] or c["fam_gender"][f]["M"]]
    charts["gender_by_family"] = series_chart(
        "stacked_bar", fam_with_women,
        [("Women", [c["fam_gender"][f]["F"] for f in fam_with_women]),
         ("Men", [c["fam_gender"][f]["M"] for f in fam_with_women])])
    women_cats = [(c["display"][k], v) for k, v in c["cats"].most_common()
                  if gender_from_category(c["display"][k]) == "F"]
    tables["women_fields"] = {"columns": ["Women's category", cur] + ([prev] if prev else []),
                              "rows": [[n, v] + ([per[prev]["cats"].get(norm_cat(n), 0)] if prev else [])
                                       for n, v in women_cats]}
    if c["genders"]["U"]:
        tables["unspecified_gender_categories"] = sorted(
            {r["category"] for r in c["rows"] if r["gender"] == "U"})

    # Location
    if flags["has_location"]:
        st = top_n(c["states"], 10)
        st_names = [s for s, _ in st]
        ser = []
        if prev:
            ps = per[prev]["states"]
            ser.append((prev, [ps.get(s, 0) if s != "All others" else
                               sum(v for k, v in ps.items() if k not in st_names) for s in st_names]))
        ser.append((cur, [v for _, v in st]))
        charts["top_states"] = series_chart("bar", st_names, ser)
        home_lab = c["home"]
        charts["in_state_by_edition"] = series_chart(
            "stacked_100", labels,
            [(f"From {home_lab}", [per[l]["states"].get(per[l]["home"], 0) for l in labels]),
             ("Travelling in", [sum(per[l]["states"].values()) - per[l]["states"].get(per[l]["home"], 0)
                                for l in labels])],
            number_format="0%")
        if prev:
            ps = per[prev]["states"]
            new_states = sorted(s for s in c["states"] if s not in ps)
            tables["state_changes"] = {
                "new": new_states,
                "lost": sorted(s for s in ps if s not in c["states"]),
                "rows": sorted(([s, ps.get(s, 0), c["states"].get(s, 0), c["states"].get(s, 0) - ps.get(s, 0)]
                                for s in set(ps) | set(c["states"])), key=lambda r: -abs(r[3]))[:12],
                "columns": ["State", prev, cur, "Change"],
            }
            for s, a, b, d in tables["state_changes"]["rows"][:5]:
                if a >= 5 and abs(d) >= max(5, 0.4 * a) and s != c["home"]:
                    outliers.append({"type": "state_swing", "severity": abs(d),
                                     "text": f"Riders from {s}: {a} → {b} ({'+' if d > 0 else ''}{d})"})
    if flags["has_city"]:
        tables["top_cities"] = {"columns": ["City", cur] + ([prev] if prev else []),
                                "rows": [[k, v] + ([per[prev]["cities"].get(k, 0)] if prev else [])
                                         for k, v in c["cities"].most_common(12)]}

    # Teams
    if flags["has_team"]:
        tt = c["teams"].most_common(12)
        ser = []
        if prev:
            ser.append((prev, [per[prev]["teams"].get(t, 0) for t, _ in tt]))
        ser.append((cur, [v for _, v in tt]))
        charts["top_teams"] = series_chart("bar", [t for t, _ in tt], ser)
        n = len(c["rows"])
        for t, v in tt[:3]:
            if v / n >= 0.05 and v >= 8:
                outliers.append({"type": "team_concentration", "severity": v,
                                 "text": f"{t} brought {v} entries — {round(100 * v / n)}% of the {cur} field"})
        if prev:
            pt = per[prev]["teams"]
            swings = sorted(((t, pt.get(t, 0), c["teams"].get(t, 0)) for t in set(pt) | set(c["teams"])),
                            key=lambda x: -abs(x[2] - x[1]))
            tables["team_changes"] = {"columns": ["Team", prev, cur, "Change"],
                                      "rows": [[t, a, b, b - a] for t, a, b in swings[:10] if a != b]}
            for t, a, b in swings[:4]:
                if a >= 6 and b <= a / 3:
                    outliers.append({"type": "team_dropoff", "severity": a - b,
                                     "text": f"{t} went from {a} entries to {b}"})

    # Registration timing
    if flags["has_reg_date"]:
        curve_series = []
        for l in labels:
            d = per[l]["days_out"]
            curve_series.append((l, [round(sum(1 for x in d if x >= pt) / len(d), 4) if d else None
                                     for pt in CURVE_POINTS]))
        charts["reg_curve"] = series_chart(
            "line", [("Race day" if pt == 0 else f"{pt}d") for pt in CURVE_POINTS], curve_series,
            number_format="0%", x_title="Days before the event")

        daily = Counter(c["reg"])
        start, end = min(c["reg"]), max(c["reg"])
        span = max((end - start).days, 0)
        window_start = max(start, end - timedelta(days=120))
        days = [window_start + timedelta(days=i) for i in range((end - window_start).days + 1)]
        weekly = span > 120
        charts["daily_regs"] = series_chart(
            "column", [d.strftime("%b %-d") for d in days], [(f"Entries per day ({cur})", [daily.get(d, 0) for d in days])],
            sparse_labels=True)
        vals = [daily.get(start + timedelta(days=i), 0) for i in range(span + 1)]
        if len(vals) >= 14:
            med = statistics.median(vals)
            mean = statistics.mean(vals)
            sd = statistics.pstdev(vals)
            thresh = max(mean + 3 * sd, 4 * max(med, 1), 5)
            spikes = sorted(((d, n) for d, n in daily.items() if n >= thresh), key=lambda x: -x[1])
            tables["reg_spikes"] = {
                "columns": ["Date", "Entries", "Days before event", "Typical day"],
                "rows": [[d.isoformat(), n, (c["event_date"] - d).days if c["event_date"] else None, med]
                         for d, n in spikes[:8]]}
            for d, n in spikes[:5]:
                dout = (c["event_date"] - d).days if c["event_date"] else None
                outliers.append({"type": "reg_spike", "severity": n,
                                 "text": f"{d.strftime('%a %b %-d')}: {n} entries in one day"
                                         + (f" ({dout} days out)" if dout is not None else "")
                                         + f" vs a typical {med:g}/day — price change, email, or deadline?"})
        by_wd = Counter(d.strftime("%a") for d in c["reg"])
        wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        charts["reg_weekday"] = series_chart("column", wd, [(cur, [by_wd[w] for w in wd])])
        if prev:
            fw = kpi[cur]["final_week_share"]
            pfw = kpi[prev]["final_week_share"]
            if fw is not None and pfw is not None and abs(fw - pfw) >= 0.1:
                outliers.append({"type": "late_registration", "severity": abs(fw - pfw) * 100,
                                 "text": f"Final-week registrations were {round(fw * 100)}% of entries in {cur} "
                                         f"vs {round(pfw * 100)}% in {prev}"})
        if weekly:
            charts["daily_regs"]["note"] = "last 120 days of registration shown"

    # Age
    if flags["has_age"]:
        ser = []
        for l in [l for l in labels if per[l]["ages"]][-3:]:
            a = per[l]["ages"]
            ser.append((l, [round(sum(1 for x in a if lo <= x <= hi) / len(a), 4) if a else None
                            for _, lo, hi in AGE_BUCKETS]))
        charts["age_distribution"] = series_chart("column", [b for b, _, _ in AGE_BUCKETS], ser,
                                                  number_format="0%")

    # Revenue
    if flags["has_price"]:
        priced = [l for l in labels if kpi[l]["revenue"]]
        charts["revenue_by_edition"] = series_chart(
            "column", priced, [("Registration revenue", [kpi[l]["revenue"] for l in priced])],
            number_format="$#,##0")
        rev_cat = Counter()
        for r in c["rows"]:
            if r["price"]:
                rev_cat[r["category"]] += r["price"]
        charts["revenue_by_category"] = series_chart(
            "bar", [k for k, _ in rev_cat.most_common(12)],
            [(cur, [round(v, 2) for _, v in rev_cat.most_common(12)])], number_format="$#,##0")

    # Retention
    if flags["has_retention"]:
        pp, cp = per[prev]["people"], per[cur]["people"]
        returning = len(pp & cp)
        ret = {"previous_riders": len(pp), "returning": returning, "new": len(cp - pp),
               "lapsed": len(pp - cp), "retention_rate": share(returning, len(pp)),
               "returning_share_of_current": share(returning, len(cp))}
        if len(labels) >= 3:
            ever = set()
            for l in labels[:-1]:
                ever |= per[l]["people"]
            ret["first_timers_ever"] = len(cp - ever)
            ret["every_edition"] = len(set.intersection(*(per[l]["people"] for l in labels)))
        tables["retention"] = ret
        charts["retention_split"] = series_chart(
            "doughnut", ["Returning", "New"], [(cur, [returning, len(cp - pp)])], number_format="#,##0")
        if len(labels) >= 3:
            rates = []
            for a, b in zip(labels, labels[1:]):
                pa, pb = per[a]["people"], per[b]["people"]
                rates.append(share(len(pa & pb), len(pa)))
            charts["retention_trend"] = series_chart(
                "line", [f"{a}→{b}" for a, b in zip(labels, labels[1:])],
                [("Riders who came back", rates)], number_format="0%")
        # Retention by category family: of prev riders in each family, how many returned (any category)
        fam_ret = []
        for f in fam_order:
            ppl = {r["person"] for r in per[prev]["rows"] if r["person"] and category_family(r["category"]) == f}
            if len(ppl) >= 10:
                fam_ret.append((f, share(len(ppl & cp), len(ppl))))
        if fam_ret:
            charts["retention_by_family"] = series_chart(
                "bar", [f for f, _ in fam_ret], [("Came back", [v for _, v in fam_ret])], number_format="0%")

    if prev and abs(kpi_delta.get("entries", {}).get("pct") or 0) >= 0.2:
        d = kpi_delta["entries"]
        outliers.append({"type": "headline_swing", "severity": 1000,
                         "text": f"Total entries {'up' if d['abs'] > 0 else 'down'} "
                                 f"{abs(round(d['pct'] * 100))}% ({kpi[prev]['entries']} → {kpi[cur]['entries']})"})

    outliers.sort(key=lambda o: -o["severity"])
    return labels, cur, prev, flags, kpi, kpi_delta, charts, tables, outliers, per


def facts(labels, cur, prev, flags, kpi, kpi_delta, tables, meta):
    """Plain-English one-liners the deck can fall back on when no narrative is given."""
    k = kpi[cur]
    out = []

    def d(key):
        x = kpi_delta.get(key)
        if not x:
            return ""
        if x.get("unit") == "pts":
            return f" ({'+' if x['abs'] >= 0 else ''}{round(x['abs'] * 100, 1)} pts vs {prev})"
        if x.get("pct") is None:
            return ""
        return f" ({'+' if x['pct'] >= 0 else ''}{round(x['pct'] * 100)}% vs {prev})"

    out.append(f"{k['entries']:,} entries across {k['categories']} categories{d('entries')}")
    if k["riders"]:
        out.append(f"{k['riders']:,} unique riders{d('riders')}, {k['entries_per_rider']} entries per rider")
    if k["women_share"] is not None:
        out.append(f"Women were {round(k['women_share'] * 100)}% of gendered entries{d('women_share')}")
    if k["states"]:
        out.append(f"Riders came from {k['states']} states; {round((k['in_state_share'] or 0) * 100)}% from "
                   f"{k['home_state']}{d('in_state_share')}")
    if k["revenue"]:
        out.append(f"${k['revenue']:,.0f} in registration revenue{d('revenue')}")
    if k["final_week_share"] is not None:
        out.append(f"{round(k['final_week_share'] * 100)}% registered in the final week{d('final_week_share')}")
    if "retention" in tables:
        r = tables["retention"]
        out.append(f"{round((r['retention_rate'] or 0) * 100)}% of {prev} riders came back; "
                   f"{r['new']:,} riders were new")
    return out


def parse_edition_specs(specs):
    out = []
    for s in specs or []:
        if "=" not in s:
            raise SystemExit(f"--edition {s!r}: expected LABEL=id,id or LABEL=file.csv")
        lab, toks = s.split("=", 1)
        out.append((lab.strip(), {t.strip() for t in re.split(r"[,\s]+", toks) if t.strip()}))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+", help="registration CSV files")
    ap.add_argument("-o", "--output", default="analysis.json")
    ap.add_argument("--edition", action="append",
                    help='group rows into an edition: "2025=74062,74063" (event IDs, event names, or file names)')
    ap.add_argument("--event-date", action="append", default=[],
                    help="LABEL=YYYY-MM-DD; otherwise the last registration date is used")
    ap.add_argument("--map", action="append", default=[],
                    help='force a column: field=Header, e.g. category="Category Entered"')
    ap.add_argument("--home-state", help="two-letter home state (default: most common state)")
    ap.add_argument("--exclude-category", help="regex; matching categories are dropped")
    ap.add_argument("--include-nonrace", action="store_true",
                    help="keep rows that look like merchandise/donations")
    ap.add_argument("--small-field", type=int, default=5, help="flag categories below this many entries")
    a = ap.parse_args(argv)

    overrides = {}
    for m in a.map:
        if "=" not in m:
            raise SystemExit(f"--map {m!r}: expected field=Header")
        f, h = m.split("=", 1)
        if f not in ALIASES:
            raise SystemExit(f"--map: unknown field {f!r}; fields are {', '.join(ALIASES)}")
        overrides[f] = h

    rows, files, excluded = load(a.csv, overrides,
                                 re.compile(a.exclude_category, re.I) if a.exclude_category else None,
                                 a.include_nonrace)
    if not rows:
        raise SystemExit("No race entries found in the CSV(s).")
    editions, meta = assign_editions(rows, parse_edition_specs(a.edition))
    ev_dates = {}
    for s in a.event_date:
        lab, ds = s.split("=", 1)
        ev_dates[lab.strip()] = date.fromisoformat(ds.strip())
    unknown = set(ev_dates) - set(editions)
    if unknown:
        raise SystemExit(f"--event-date for unknown edition(s) {sorted(unknown)}; editions are {list(editions)}")

    labels, cur, prev, flags, kpi, kpi_delta, charts, tables, outliers, per = analyze(
        editions, meta, ev_dates, a.home_state.upper() if a.home_state else None, a.small_field)

    unparsed = sum(1 for r in rows if r["reg_date_raw"] and not r["reg_date"])
    dupes = sum(v - 1 for v in Counter((r["file"], r["event_id"], r["person"], norm_cat(r["category"]))
                                       for r in rows if r["person"]).values() if v > 1)
    dq = {
        "files": files,
        "excluded_rows": dict(excluded.most_common()),
        "unparsed_reg_dates": unparsed,
        "duplicate_entries": dupes,
        "gender_source": {m["label"]: m["gender_source"] for m in meta},
        "event_date_inferred": [m["label"] for m in meta if m["event_date_inferred"]],
    }

    out = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "editions": meta,
        "current": cur,
        "previous": prev,
        "flags": flags,
        "kpis": kpi,
        "kpi_delta": kpi_delta,
        "charts": charts,
        "tables": tables,
        "outliers": outliers,
        "facts": facts(labels, cur, prev, flags, kpi, kpi_delta, tables, meta),
        "data_quality": dq,
    }
    with open(a.output, "w") as f:
        json.dump(out, f, indent=1, default=str)

    # Console summary — what Claude reads first.
    print(f"Editions ({len(labels)}): " + "; ".join(
        f"{m['label']} = {', '.join(m['event_names'] or m['files'])}"
        f" [{len(editions[m['label']])} entries, event date {m['event_date']}"
        f"{' (inferred from last reg)' if m['event_date_inferred'] else ''}]" for m in meta))
    for fi in files:
        print(f"Columns in {fi['name']}: " + ", ".join(f"{k}←{v!r}" for k, v in fi["columns"].items()))
    print("Available: " + ", ".join(k for k, v in flags.items() if v is True))
    print("Missing:   " + (", ".join(k for k, v in flags.items() if v is False) or "nothing"))
    if excluded:
        print(f"Excluded {sum(excluded.values())} non-race rows: " +
              ", ".join(f"{k} ({v})" for k, v in excluded.most_common(10)))
    if unparsed:
        print(f"WARNING: {unparsed} registration dates could not be parsed "
              f"(e.g. {next(r['reg_date_raw'] for r in rows if r['reg_date_raw'] and not r['reg_date'])!r})")
    if dupes:
        print(f"note: {dupes} duplicate rows (same rider, same category, same event)")
    print("\nFacts:")
    for f_ in out["facts"]:
        print("  - " + f_)
    print(f"\nOutliers ({len(outliers)}):")
    for o in outliers[:12]:
        print(f"  - [{o['type']}] {o['text']}")
    print(f"\nWrote {a.output}")


if __name__ == "__main__":
    main()
