#!/usr/bin/env python3
"""Generate fictional sample inputs for testing the race review pipeline.

    python3 make_sample_data.py <out dir>

Writes three seasons of a made-up race ("Riverside Crit"):
  riverside_2023.csv, riverside_2024.csv — bikereg-registrations format
  riverside_2025_export.csv              — promoter-export style (age, price, zip,
                                           email, merchandise rows, US date format)
  logo.png (transparent), logo_white.jpg (opaque white background)
Every name is randomly generated; no real riders.
"""

import csv
import os
import random
import sys
from datetime import date, datetime, timedelta

FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Jamie", "Avery", "Quinn", "Drew",
         "Reese", "Parker", "Rowan", "Emerson", "Hayden", "Skyler", "Logan", "Blake", "Cameron", "Dakota",
         "Elliot", "Finley", "Harper", "Kendall", "Marlowe", "Noel", "Oakley", "Peyton", "Sawyer"]
LAST = ["Garza", "Nguyen", "Smith", "Patel", "Okafor", "Kowalski", "Reyes", "Lindqvist", "Brennan", "Haddad",
        "Moreau", "Tanaka", "Ferreira", "Novak", "Osei", "Castillo", "Dubois", "Iverson", "Kaur", "Lambert",
        "Mendez", "Nakamura", "Olsen", "Petrov", "Quintero", "Rossi", "Silva", "Thorne", "Usman", "Vance",
        "Walsh", "Yilmaz", "Zamora", "Abbott", "Becker", "Chen", "Dalton", "Ellis", "Fischer", "Grant"]
TEAMS = ["Bayou Velo", "Lone Star Racing", "Crankworks p/b Hill Country Coffee", "Rolling Thunder CC",
         "Big Sky Cycling", "Austin Wheelmen", "Prairie Fire Racing", "", "", "", "Unattached",
         "Peloton Pizza Racing", "Gulf Coast Velo", "Cedar Park Cyclists"]
CITIES = {"TX": ["Austin", "Houston", "Dallas", "San Antonio", "Round Rock", "Waco", "College Station"],
          "OK": ["Tulsa", "Norman"], "LA": ["Baton Rouge", "Lafayette"], "AR": ["Bentonville"],
          "CO": ["Boulder"], "NM": ["Albuquerque"]}
CATS = {
    2023: {"Men Pro/1/2": 38, "Men Cat 3": 45, "Men Cat 4": 52, "Men Cat 5": 30, "Women Pro/1/2/3": 14,
           "Women Cat 4/5": 12, "Masters Men 40+": 40, "Masters Men 50+": 28, "Masters Women 40+": 7,
           "Junior 15-18": 9, "Kids 10 & Under": 14},
    2024: {"Men Pro/1/2": 41, "Men Cat 3": 48, "Men Cat 4": 50, "Men Cat 5": 33, "Women Pro/1/2/3": 16,
           "Women Cat 4/5": 15, "Masters Men 40+": 44, "Masters Men 50+": 27, "Masters Women 40+": 8,
           "Junior 15-18": 11, "Kids 10 & Under": 16},
    2025: {"Men Pro/1/2": 39, "Men Cat 3": 55, "Men Cat 4": 58, "Men Beginner": 41, "Women Pro/1/2/3": 22,
           "Women Cat 4/5": 26, "Women Beginner": 12, "Masters Men 40+": 46, "Masters Men 50+": 12,
           "Masters Women 40+": 11, "Junior 15-18": 4, "Kids 10 & Under": 21},
}
EVENT = {2023: ("Riverside Crit 2023", "61234", date(2023, 6, 10)),
         2024: ("Riverside Crit 2024", "67890", date(2024, 6, 8)),
         2025: ("Riverside Crit 2025", "74321", date(2025, 6, 7))}


def person_pool(rng, n):
    seen, out = set(), []
    while len(out) < n:
        f, l = rng.choice(FIRST), rng.choice(LAST)
        if (f, l) in seen:
            continue
        seen.add((f, l))
        st = rng.choices(list(CITIES), weights=[78, 6, 6, 3, 4, 3])[0]
        out.append({"first": f, "last": l, "team": rng.choice(TEAMS), "state": st,
                    "city": rng.choice(CITIES[st]), "age": rng.randint(9, 68)})
    return out


def reg_dates(rng, n, race_day, spike_day=None):
    out = []
    for _ in range(n):
        # Most riders register in the last 3 weeks; a long tail back to ~10 weeks.
        d = int(min(70, rng.expovariate(1 / 14)))
        out.append(race_day - timedelta(days=d + 1))
    if spike_day:
        for i in rng.sample(range(n), max(8, n // 12)):
            out[i] = spike_day
    return out


def build(out_dir):
    rng = random.Random(42)
    os.makedirs(out_dir, exist_ok=True)
    pool = person_pool(rng, 900)
    used_prev = []
    paths = {}
    for yr in (2023, 2024, 2025):
        name, eid, race_day = EVENT[yr]
        riders = []
        # ~50% of last year's riders come back; the rest are new.
        returning = rng.sample(used_prev, int(len(used_prev) * 0.5)) if used_prev else []
        fresh = [p for p in pool if p not in used_prev and p not in returning]
        rng.shuffle(fresh)
        rows = []
        cursor = 0
        people = returning + fresh
        for cat, n in CATS[yr].items():
            for _ in range(n):
                p = people[cursor % len(people)]
                cursor += 1
                riders.append(p)
                rows.append((p, cat))
        used_prev = list({id(p): p for p in riders}.values())
        spike = race_day - timedelta(days=15) if yr == 2025 else None
        dates = reg_dates(rng, len(rows), race_day, spike)
        if yr < 2025:
            path = os.path.join(out_dir, f"riverside_{yr}.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Event", "Event ID", "First Name", "Last Name", "Race Category", "Gender", "Team",
                            "City", "State", "Reg Date"])
                for (p, cat), d in zip(rows, dates):
                    g = "F" if "Women" in cat else "M" if "Men" in cat else "Unspecified"
                    w.writerow([name, eid, p["first"], p["last"], cat, g, p["team"], p["city"], p["state"],
                                d.isoformat()])
        else:
            path = os.path.join(out_dir, "riverside_2025_export.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["First Name", "Last Name", "Email", "Gender", "Age", "City", "State", "Zip", "Team",
                            "Category Entered / Merchandise Ordered", "Price", "Registration Date"])
                for (p, cat), d in zip(rows, dates):
                    g = "F" if "Women" in cat else "M" if "Men" in cat else rng.choice(["M", "F"])
                    price = 15 if "Kids" in cat else 35 if "Junior" in cat else 55 if d < race_day - timedelta(days=14) else 65
                    t = datetime.combine(d, datetime.min.time()) + timedelta(minutes=rng.randint(0, 1439))
                    w.writerow([p["first"], p["last"], f"{p['first'].lower()}.{p['last'].lower()}@example.com", g,
                                p["age"], p["city"], p["state"], f"7{rng.randint(1000, 9999)}", p["team"], cat,
                                f"${price}.00", t.strftime("%m/%d/%Y %I:%M %p")])
                for _ in range(23):
                    p = rng.choice(riders)
                    w.writerow([p["first"], p["last"], "", "", "", p["city"], p["state"], "", "", "Event T-Shirt",
                                "$25.00", race_day.strftime("%m/%d/%Y") + " 09:00 AM"])
        paths[yr] = path

    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([20, 20, 380, 380], fill=(242, 101, 34, 255))           # orange
        d.rectangle([420, 120, 780, 200], fill=(18, 52, 95, 255))          # navy
        d.rectangle([420, 230, 700, 290], fill=(18, 52, 95, 255))
        d.polygon([(120, 300), (200, 80), (280, 300)], fill=(255, 255, 255, 255))
        im.save(os.path.join(out_dir, "logo.png"))
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        bg.save(os.path.join(out_dir, "logo_white.jpg"), quality=90)
    except ImportError:
        pass
    return paths


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sample"
    for yr, p in build(out).items():
        print(yr, p)
