#!/usr/bin/env python3
"""Offline tests for the social review pipeline, run on fictional Meta exports.

    python3 test_social_review.py

Needs python-pptx + Pillow. Never touches the network (slides come from the
bundled library).
"""
import csv
import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze  # noqa: E402
import build_deck  # noqa: E402

FAIL = []
HEADERS = ["Post ID", "Account ID", "Account username", "Account name", "Description", "Duration (sec)",
           "Publish time", "Permalink", "Post type", "Data comment", "Date", "Views", "Reach", "Likes",
           "Shares", "Follows", "Comments", "Saves"]


def check(label, got, want):
    if got != want:
        FAIL.append("{}\n    got:  {!r}\n    want: {!r}".format(label, got, want))


def run(*args):
    return subprocess.run([sys.executable] + list(args), capture_output=True, text=True)


def sample(path, year, n, seed):
    """A fictional Instagram export in Meta's column layout."""
    rnd = random.Random(seed)
    accounts = ["riversidecrit"] * 6 + ["clubrouleur", "photo_by_sam", "fastcoffee"]
    captions = ["Race day recap! #riversidecrit #critracing", "Registration is open @fastcoffee",
                "Podium shots from the Pro race 📸 @photo_by_sam #cycling", "Course preview — 1.1 km, 6 corners",
                "Kids race was the highlight #riversidecrit", "Thanks to our sponsors @fastcoffee @clubrouleur", ""]
    start = datetime(year - 1, 12, 31)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for i in range(n):
            t = start + timedelta(days=rnd.randint(1, 300), hours=rnd.randint(6, 22))
            kind = rnd.choice(["IG carousel", "IG carousel", "IG image", "IG reel"])
            code = f"C{year}{i:04d}x"
            views = int(rnd.lognormvariate(8.3, 0.6)) * (3 if kind == "IG reel" else 1)
            reach = int(views * rnd.uniform(0.3, 0.6))
            w.writerow([f"{year}{i:05d}", "1", rnd.choice(accounts), "Fictional", rnd.choice(captions),
                        rnd.randint(10, 100) if kind == "IG reel" else 0, t.strftime("%m/%d/%Y %H:%M"),
                        f"https://www.instagram.com/{'reel' if kind == 'IG reel' else 'p'}/{code}/", kind, "",
                        "Lifetime", views, reach, int(reach * 0.06), rnd.randint(0, 40), rnd.randint(0, 6),
                        rnd.randint(0, 9), rnd.randint(0, 4)])
    return path


tmp = tempfile.mkdtemp()
f1 = sample(os.path.join(tmp, "Dec-31-2024_Oct-31-2025_111.csv"), 2025, 120, 1)
f2 = sample(os.path.join(tmp, "Dec-31-2025_Oct-31-2026_222.csv"), 2026, 140, 2)

# ---- helpers -------------------------------------------------------------
check("hashtags need a letter", analyze.HASHTAG.findall("#1 #3rd #critracing #2026"), ["3rd", "critracing"])
check("mentions strip trailing dot", analyze.MENTION.findall("thanks @fast.coffee. and @club_r!"),
      ["fast.coffee", "club_r"])
check("shortcode", analyze.shortcode("https://www.instagram.com/reel/DanmavQuJH1/"), "DanmavQuJH1")
check("type", analyze.clean_type("IG carousel", ""), "Carousel")
check("period from Meta file name", analyze.label_for(f1, [])[0], "2025")
check("compact format", [build_deck.fmt_metric(v, "compact") for v in (950, 12400, 1312610)],
      ["950", "12.4k", "1.3M"])

# ---- full analysis -------------------------------------------------------
out = os.path.join(tmp, "analysis.json")
r = run(os.path.join(HERE, "analyze.py"), f1, f2, "-o", out)
check("analyze exit", r.returncode, 0)
a = json.load(open(out))
check("periods", [e["label"] for e in a["editions"]], ["2025", "2026"])
check("post counts", (a["kpis"]["2025"]["posts"], a["kpis"]["2026"]["posts"]), (120, 140))
check("top posts sorted", [p["views"] for p in a["top_posts"]] == sorted([p["views"] for p in a["top_posts"]],
                                                                         reverse=True), True)
check("8 posts for the collage", len(a["top_posts"]), 8)
check("hashtags found", a["flags"]["has_hashtags"], True)
check("mentions found", a["flags"]["has_mentions"], True)
check("no focus", a["flags"]["has_focus"], False)

# ---- focus ---------------------------------------------------------------
fo = os.path.join(tmp, "focus.json")
r = run(os.path.join(HERE, "analyze.py"), f1, f2, "--mention", "fastcoffee", "-o", fo)
check("focus exit", r.returncode, 0)
fa = json.load(open(fo))
check("focus flag", fa["flags"]["has_focus"], True)
check("focus smaller", fa["kpis"]["2026"]["posts"] < a["kpis"]["2026"]["posts"], True)
r = run(os.path.join(HERE, "analyze.py"), f1, "--hashtag", "nosuchtag", "-o", os.path.join(tmp, "x.json"))
check("empty focus fails loudly", r.returncode != 0 and "matches no posts" in r.stderr, True)

# ---- library + build -----------------------------------------------------
lib = json.load(open(os.path.join(os.path.dirname(HERE), "slides", "deck.json")))
check("library valid", build_deck.validate(lib), [])
for s in lib["slides"]:
    if s.get("chart") and s["chart"] not in a["charts"] and s["chart"] not in fa["charts"]:
        FAIL.append(f"slide {s['id']}: chart {s['chart']!r} not produced by analyze.py")
    if s.get("table") and s["table"] not in a["tables"]:
        FAIL.append(f"slide {s['id']}: table {s['table']!r} not produced by analyze.py")
for pool in lib["backgrounds"].values():
    for name in pool:
        if not os.path.exists(os.path.join(os.path.dirname(HERE), "slides", "backgrounds", name)):
            FAIL.append(f"background {name} missing from bundled slides/backgrounds")

imgs = os.path.join(tmp, "imgs")
os.makedirs(imgs)
from PIL import Image  # noqa: E402
Image.new("RGB", (1080, 1350), (200, 60, 60)).save(os.path.join(imgs, "1.jpg"))
Image.new("RGB", (1080, 1920), (60, 200, 60)).save(os.path.join(imgs, a["top_posts"][1]["shortcode"] + ".png"))
check("image matching", sorted(build_deck.find_images(imgs, a["top_posts"])), [1, 2])

for label, an in (("full", out), ("focus", fo)):
    deck = os.path.join(tmp, f"{label}.pptx")
    r = run(os.path.join(HERE, "build_deck.py"), "--analysis", an, "--slides", "bundled", "--images", imgs,
            "-o", deck)
    check(f"build {label} exit", (r.returncode, r.stderr[-300:]), (0, ""))
    if r.returncode == 0:
        from pptx import Presentation
        prs = Presentation(deck)
        W, H = prs.slide_width, prs.slide_height
        for i, s in enumerate(prs.slides, 1):
            for sh in s.shapes:
                if sh.left + sh.width > W + 10 or sh.top + sh.height > H + 10 or sh.left < 0 or sh.top < 0:
                    FAIL.append(f"{label} slide {i}: shape {sh.name} off the slide")
        if label == "full":  # the focus deck has different top posts, so only 1.jpg matches there
            check("collage has 2 pictures + background",
                  any(sum(1 for sh in s.shapes if sh.shape_type == 13) == 3 for s in prs.slides), True)

if FAIL:
    print("FAILED:\n  " + "\n  ".join(FAIL))
    sys.exit(1)
print("all social review tests passed")
