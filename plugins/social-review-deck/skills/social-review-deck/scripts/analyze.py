#!/usr/bin/env python3
"""Analyze Meta (Instagram / Facebook) post-performance CSV exports.

    python3 analyze.py export_2025.csv export_2026.csv -o analysis.json
    python3 analyze.py export.csv --account drivewayseries -o analysis.json
    python3 analyze.py a.csv b.csv --hashtag drivewayseries --mention trekrideclubatx

Each file is one period (usually one year, exported from Meta Business Suite →
Insights → Content → Export). Periods are labelled from the date range in the
file name Meta gives the export (Dec-31-2024_Oct-31-2025_… → 2025), else from
the year most posts were published in. Override with --period LABEL=file.

Focus filters narrow the analysis to one brand or campaign. Several can be
combined; a post matches if it matches any of them:
    --account   posts published by (or collaborating as) these usernames
    --hashtag   posts whose caption uses this hashtag
    --mention   posts whose caption @-mentions this account (sponsors, partners)
    --keyword   posts whose caption contains this text

Writes analysis.json (KPIs, charts, tables, top posts, outliers) for
build_deck.py and prints a summary to check before writing the narrative.
Standard library only.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

# Column aliases, lowercased. First match wins. Instagram exports use the first
# names; Facebook Page exports use some of the later ones.
COLUMNS = {
    "post_id": ["post id"],
    "account": ["account username", "page username", "account name", "page name"],
    "account_name": ["account name", "page name"],
    "caption": ["description", "title", "message", "caption"],
    "duration": ["duration (sec)", "duration"],
    "published": ["publish time", "published", "publish date", "created"],
    "permalink": ["permalink", "post link", "link"],
    "post_type": ["post type", "type"],
    "views": ["views", "impressions", "plays", "video views"],
    "reach": ["reach", "accounts reached"],
    "likes": ["likes", "reactions", "likes and reactions"],
    "comments": ["comments"],
    "shares": ["shares"],
    "saves": ["saves"],
    "follows": ["follows", "new followers"],
}
METRICS = ["views", "reach", "likes", "comments", "shares", "saves", "follows"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HASHTAG = re.compile(r"#([A-Za-z0-9_]*[A-Za-z][A-Za-z0-9_]*)")
MENTION = re.compile(r"@([A-Za-z0-9_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?)")
FILE_RANGE = re.compile(r"([A-Z][a-z]{2})-(\d{1,2})-(\d{4})_([A-Z][a-z]{2})-(\d{1,2})-(\d{4})")
DATE_FORMATS = ("%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y", "%Y-%m-%d")


# --- loading -----------------------------------------------------------------

def detect_columns(headers, overrides):
    low = {h.strip().lower(): h for h in headers}
    out = {}
    for key, names in COLUMNS.items():
        if key in overrides:
            out[key] = overrides[key]
            continue
        for n in names:
            if n in low and low[n] not in out.values():
                out[key] = low[n]
                break
    return out


def parse_time(s):
    s = (s or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def num(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def clean_type(t, permalink):
    t = (t or "").strip()
    t = re.sub(r"^(IG|FB)\s+", "", t, flags=re.I)
    if not t:
        t = "reel" if "/reel/" in (permalink or "") else "post"
    return t[:1].upper() + t[1:].lower()


def platform(row_type, permalink):
    if (row_type or "").upper().startswith("FB") or "facebook.com" in (permalink or ""):
        return "Facebook"
    return "Instagram"


def shortcode(permalink):
    m = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", permalink or "")
    return m.group(1) if m else None


def load(path, overrides):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = detect_columns(reader.fieldnames or [], overrides)
        rows = list(reader)
    missing = [k for k in ("published", "views") if k not in cols]
    if missing:
        sys.exit(f"{path}: couldn't find column(s) for {', '.join(missing)}. "
                 f"Headers: {reader.fieldnames}. Map one with --map views=\"Impressions\".")
    posts, seen, bad = [], set(), 0
    for r in rows:
        g = lambda k: r.get(cols[k], "") if k in cols else ""  # noqa: E731
        t = parse_time(g("published"))
        if not t:
            bad += 1
            continue
        pid = g("post_id") or g("permalink") or f"{path}:{len(posts)}"
        if pid in seen:
            continue
        seen.add(pid)
        cap = (g("caption") or "").strip()
        p = {
            "id": pid,
            "account": (g("account") or "").strip().lstrip("@"),
            "account_name": (g("account_name") or "").strip(),
            "caption": cap,
            "published": t,
            "permalink": (g("permalink") or "").strip(),
            "type": clean_type(g("post_type"), g("permalink")),
            "platform": platform(g("post_type"), g("permalink")),
            "duration": num(g("duration")),
            "hashtags": sorted({h.lower() for h in HASHTAG.findall(cap)}),
            "mentions": sorted({m.lower() for m in MENTION.findall(cap)}),
        }
        for m in METRICS:
            p[m] = num(g(m)) if m in cols else None
        p["engagement"] = sum(p[m] or 0 for m in ("likes", "comments", "shares", "saves"))
        p["er"] = p["engagement"] / p["reach"] if p.get("reach") else None
        p["shortcode"] = shortcode(p["permalink"])
        posts.append(p)
    return posts, cols, bad


def label_for(path, posts):
    m = FILE_RANGE.search(os.path.basename(path))
    if m:
        return m.group(6), f"{m.group(1)} {int(m.group(2))}, {m.group(3)} – {m.group(4)} {int(m.group(5))}, {m.group(6)}"
    years = Counter(p["published"].year for p in posts)
    y = str(years.most_common(1)[0][0]) if years else os.path.splitext(os.path.basename(path))[0]
    return y, None


# --- focus -------------------------------------------------------------------

def focus_filter(a):
    accts = {x.lower().lstrip("@") for x in a.account}
    tags = {x.lower().lstrip("#") for x in a.hashtag}
    ments = {x.lower().lstrip("@") for x in a.mention}
    kws = [x.lower() for x in a.keyword]
    if not (accts or tags or ments or kws):
        return None, None
    parts = [f"@{x}" for x in sorted(accts)] + [f"#{x}" for x in sorted(tags)] + \
            [f"mentions of @{x}" for x in sorted(ments)] + [f"“{x}”" for x in kws]

    def match(p):
        cap = p["caption"].lower()
        return (p["account"].lower() in accts
                or bool(tags & set(p["hashtags"]))
                or bool(ments & set(p["mentions"]))
                or any(k in cap for k in kws))
    return match, " + ".join(parts)


# --- stats -------------------------------------------------------------------

def tot(posts, m):
    return sum(p[m] or 0 for p in posts)


def avg(posts, m):
    vals = [p[m] for p in posts if p[m] is not None]
    return sum(vals) / len(vals) if vals else None


def med(posts, m):
    vals = [p[m] for p in posts if p[m] is not None]
    return statistics.median(vals) if vals else None


def er_of(posts):
    r = tot(posts, "reach")
    return tot(posts, "engagement") / r if r else None


def kpis(posts, has):
    k = {
        "posts": len(posts),
        "views": tot(posts, "views"),
        "avg_views": avg(posts, "views"),
        "median_views": med(posts, "views"),
        "engagement": tot(posts, "engagement"),
        "er": er_of(posts),
        "accounts": len({p["account"] for p in posts if p["account"]}),
        "hashtags_used": len({h for p in posts for h in p["hashtags"]}),
    }
    for m in ("reach", "likes", "comments", "shares", "saves", "follows"):
        k[m] = tot(posts, m) if has.get(m) else None
    k["avg_reach"] = avg(posts, "reach") if has.get("reach") else None
    k["reels_share"] = sum(1 for p in posts if p["type"] == "Reel") / len(posts) if posts else None
    return k


def delta(a, b, unit=None):
    if a is None or b is None:
        return None
    if unit == "pts":
        return {"abs": b - a, "unit": "pts"}
    return {"abs": b - a, "pct": (b - a) / a if a else None}


def r1(v, d=1):
    return None if v is None else round(v, d)


def snippet(cap, n=70):
    cap = re.sub(r"\s+", " ", cap or "").strip()
    return cap if len(cap) <= n else cap[: n - 1].rsplit(" ", 1)[0] + "…"


def post_card(p, rank=None):
    return {
        "rank": rank, "id": p["id"], "shortcode": p["shortcode"], "permalink": p["permalink"],
        "account": p["account"], "type": p["type"], "platform": p["platform"],
        "date": p["published"].strftime("%Y-%m-%d"), "caption": snippet(p["caption"], 110),
        "views": p["views"], "reach": p["reach"], "likes": p["likes"], "comments": p["comments"],
        "shares": p["shares"], "saves": p["saves"], "follows": p["follows"],
        "engagement": p["engagement"], "er": r1(p["er"], 4), "hashtags": p["hashtags"][:8],
    }


def chart(kind, cats, series, **kw):
    out = {"kind": kind, "categories": cats, "series": series}
    out.update({k: v for k, v in kw.items() if v is not None})
    return out


# --- analysis ----------------------------------------------------------------

def analyze(periods, has, focus_label=None, all_posts=None, min_tag_posts=3, top_n=8):
    labels = [p["label"] for p in periods]
    cur, prev = labels[-1], (labels[-2] if len(labels) > 1 else None)
    by = {p["label"]: p["posts"] for p in periods}
    C, P = by[cur], by.get(prev, [])
    multi = prev is not None

    K = {lab: kpis(by[lab], has) for lab in labels}
    kd = {}
    if multi:
        for key in K[cur]:
            if key in ("reels_share", "er"):
                d = delta(K[prev][key], K[cur][key], "pts")
            else:
                d = delta(K[prev][key], K[cur][key])
            if d:
                kd[key] = d

    charts, tables, outliers, facts = {}, {}, [], []

    # Volume and reach by period
    if multi:
        charts["totals_by_period"] = chart("column", ["Posts", "Avg views / post", "Avg reach / post"] if has.get("reach")
                                           else ["Posts", "Avg views / post"],
                                           [{"name": lab, "values": [K[lab]["posts"], r1(K[lab]["avg_views"], 0)]
                                             + ([r1(K[lab]["avg_reach"], 0)] if has.get("reach") else [])}
                                            for lab in labels])
        charts["views_by_period"] = chart("column", labels, [{"name": "Total views", "values": [K[lab]["views"] for lab in labels]}])

    # Monthly cadence and views
    months_present = sorted({p["published"].month for lab in labels for p in by[lab]})
    mcats = [MONTHS[m - 1] for m in months_present]
    charts["posts_by_month"] = chart("line" if multi else "column", mcats, [
        {"name": lab, "values": [sum(1 for p in by[lab] if p["published"].month == m) for m in months_present]}
        for lab in labels])
    charts["views_by_month"] = chart("line" if multi else "column", mcats, [
        {"name": lab, "values": [tot([p for p in by[lab] if p["published"].month == m], "views") for m in months_present]}
        for lab in labels])

    # Post types
    types = [t for t, _ in Counter(p["type"] for lab in labels for p in by[lab]).most_common()]
    charts["type_mix"] = chart("stacked_100", labels, [
        {"name": t, "values": [sum(1 for p in by[lab] if p["type"] == t) for lab in labels]} for t in types])
    charts["type_avg_views"] = chart("column", types, [
        {"name": lab, "values": [r1(avg([p for p in by[lab] if p["type"] == t], "views"), 0) for t in types]}
        for lab in labels])
    if has.get("reach"):
        charts["type_er"] = chart("column", types, [
            {"name": lab, "values": [r1(er_of([p for p in by[lab] if p["type"] == t]), 4) for t in types]}
            for lab in labels], number_format="0.0%")
    trows = []
    for t in types:
        tp = [p for p in C if p["type"] == t]
        if not tp:
            continue
        pp = [p for p in P if p["type"] == t]
        row = [t, len(tp), r1(avg(tp, "views"), 0), r1(er_of(tp), 4)]
        row += [r1(avg(tp, "shares"), 1), r1(avg(tp, "saves"), 1)] if has.get("shares") else []
        if multi:
            a0, a1 = avg(pp, "views"), avg(tp, "views")
            row.append(r1((a1 - a0) / a0, 4) if a0 else None)
        trows.append(row)
    tables["post_types"] = {"columns": ["Post type", "Posts", "Avg views", "Eng. rate"]
                            + (["Avg shares", "Avg saves"] if has.get("shares") else [])
                            + ([f"Avg views % vs {prev}"] if multi else []), "rows": trows}

    # Top posts
    ranked = sorted(C, key=lambda p: -(p["views"] or 0))
    top = [post_card(p, i + 1) for i, p in enumerate(ranked[:max(top_n, 10)])]
    tables["top_posts"] = {"columns": ["Date", "Account", "Type", "Caption", "Views", "Eng. rate"],
                           "rows": [[c["date"][5:], "@" + c["account"] if c["account"] else "—", c["type"],
                                     snippet(c["caption"], 38), c["views"], c["er"]] for c in top[:10]],
                           "widths": [0.08, 0.17, 0.1, 0.41, 0.12, 0.12]}
    bottom = [post_card(p) for p in ranked[-5:]][::-1] if len(ranked) >= 15 else []
    tables["bottom_posts"] = {"columns": ["Date", "Account", "Type", "Caption", "Views", "Eng. rate"],
                              "rows": [[c["date"][5:], "@" + c["account"] if c["account"] else "—", c["type"],
                                        snippet(c["caption"], 38), c["views"], c["er"]] for c in bottom],
                              "widths": [0.08, 0.17, 0.1, 0.41, 0.12, 0.12]}
    charts["top_posts_views"] = chart("bar", [f"{c['date'][5:]} {snippet(c['caption'], 26)}" for c in top[:10]],
                                      [{"name": "Views", "values": [c["views"] for c in top[:10]]}])

    # Best post per metric
    leaders = []
    for m, lab in (("views", "Views"), ("reach", "Reach"), ("likes", "Likes"), ("comments", "Comments"),
                   ("shares", "Shares"), ("saves", "Saves"), ("follows", "Follows")):
        if not has.get(m) or not C:
            continue
        p = max(C, key=lambda x: x[m] or 0)
        if p[m]:
            leaders.append([lab, p[m], p["published"].strftime("%m-%d"), p["type"], snippet(p["caption"], 46)])
    tables["metric_leaders"] = {"columns": ["Most…", "Value", "Date", "Type", "Caption"], "rows": leaders,
                                "widths": [0.12, 0.1, 0.08, 0.1, 0.6]}

    # Hashtags
    tag_stats = {}
    for lab in labels:
        d = defaultdict(list)
        for p in by[lab]:
            for h in p["hashtags"]:
                d[h].append(p)
        tag_stats[lab] = d
    base_avg = avg(C, "views") or 0
    cur_tags = [(h, ps) for h, ps in tag_stats[cur].items() if len(ps) >= min_tag_posts]
    cur_tags.sort(key=lambda x: -(avg(x[1], "views") or 0))
    hrows = []
    for h, ps in cur_tags[:12]:
        row = ["#" + h, len(ps), r1(avg(ps, "views"), 0), r1(er_of(ps), 4),
               r1((avg(ps, "views") - base_avg) / base_avg, 4) if base_avg else None]
        if multi:
            pp = tag_stats[prev].get(h, [])
            row.append(len(pp))
        hrows.append(row)
    tables["top_hashtags"] = {"columns": ["Hashtag", "Posts", "Avg views", "Eng. rate", "% vs avg post"]
                              + ([f"Posts in {prev}"] if multi else []), "rows": hrows}
    charts["hashtag_avg_views"] = chart("bar", ["#" + h for h, _ in cur_tags[:12]],
                                        [{"name": "Avg views", "values": [r1(avg(ps, "views"), 0) for _, ps in cur_tags[:12]]}],
                                        note=f"Hashtags used on {min_tag_posts}+ posts · average post: {base_avg:,.0f} views")
    used = Counter({h: len(ps) for h, ps in tag_stats[cur].items()})
    charts["hashtag_usage"] = chart("bar", ["#" + h for h, _ in used.most_common(12)], [
        {"name": lab, "values": [len(tag_stats[lab].get(h, [])) for h, _ in used.most_common(12)]} for lab in labels])
    with_t = [p for p in C if p["hashtags"]]
    without = [p for p in C if not p["hashtags"]]
    if with_t and without:
        charts["hashtag_vs_none"] = chart("column", ["With hashtags", "No hashtags"],
                                          [{"name": "Avg views", "values": [r1(avg(with_t, "views"), 0), r1(avg(without, "views"), 0)]}])
    if multi:
        yoy = []
        for h in set(tag_stats[cur]) | set(tag_stats[prev]):
            a, b = tag_stats[prev].get(h, []), tag_stats[cur].get(h, [])
            if len(a) + len(b) >= min_tag_posts * 2 - 1:
                yoy.append(["#" + h, len(a), len(b), r1(avg(a, "views"), 0), r1(avg(b, "views"), 0)])
        yoy.sort(key=lambda r: -(r[1] + r[2]))
        tables["hashtag_yoy"] = {"columns": ["Hashtag", f"Posts {prev}", f"Posts {cur}",
                                             f"Avg views {prev}", f"Avg views {cur}"], "rows": yoy[:11]}

    # Mentions (partners / sponsors) and posting accounts
    ment = defaultdict(list)
    for p in C:
        for m in p["mentions"]:
            ment[m].append(p)
    mrows = sorted(((m, ps) for m, ps in ment.items() if len(ps) >= 2), key=lambda x: -len(x[1]))[:11]
    tables["top_mentions"] = {"columns": ["Account mentioned", "Posts", "Total views", "Avg views", "Eng. rate"],
                              "rows": [["@" + m, len(ps), tot(ps, "views"), r1(avg(ps, "views"), 0), r1(er_of(ps), 4)]
                                       for m, ps in mrows]}
    acc = defaultdict(list)
    for p in C:
        acc[p["account"] or "—"].append(p)
    arank = sorted(acc.items(), key=lambda x: -tot(x[1], "views"))
    charts["accounts_views"] = chart("bar", ["@" + a for a, _ in arank[:12]],
                                     [{"name": "Views", "values": [tot(ps, "views") for _, ps in arank[:12]]}])
    tables["accounts"] = {"columns": ["Account", "Posts", "Total views", "Avg views", "Eng. rate"],
                          "rows": [["@" + a, len(ps), tot(ps, "views"), r1(avg(ps, "views"), 0), r1(er_of(ps), 4)]
                                   for a, ps in arank[:11]]}

    # Timing
    charts["weekday_views"] = chart("column", DAYS, [
        {"name": lab, "values": [r1(avg([p for p in by[lab] if p["published"].weekday() == d], "views"), 0) for d in range(7)]}
        for lab in labels])
    buckets = [("Early (<8am)", 0, 8), ("Morning", 8, 12), ("Afternoon", 12, 17), ("Evening", 17, 21), ("Night (9pm+)", 21, 24)]
    charts["time_views"] = chart("column", [b[0] for b in buckets], [
        {"name": lab, "values": [r1(avg([p for p in by[lab] if lo <= p["published"].hour < hi], "views"), 0)
                                 for _, lo, hi in buckets]} for lab in labels],
        note="Times as exported by Meta (account's time zone)")
    charts["weekday_posts"] = chart("column", DAYS, [
        {"name": lab, "values": [sum(1 for p in by[lab] if p["published"].weekday() == d) for d in range(7)]} for lab in labels])

    # Reel length
    reels = [p for p in C if p["type"] == "Reel" and p["duration"]]
    if len(reels) >= 6:
        lb = [("<15s", 0, 15), ("15–30s", 15, 30), ("30–60s", 30, 60), ("60–90s", 60, 90), ("90s+", 90, 1e9)]
        vals = [(n, [p for p in reels if lo <= p["duration"] < hi]) for n, lo, hi in lb]
        vals = [(n, ps) for n, ps in vals if ps]
        charts["reel_length"] = chart("column", [f"{n} ({len(ps)})" for n, ps in vals],
                                      [{"name": "Avg views", "values": [r1(avg(ps, "views"), 0) for _, ps in vals]}],
                                      note="Reels by length (number of reels in brackets)")

    # Engagement mix
    if has.get("shares"):
        mix = [m for m in ("likes", "comments", "shares", "saves") if has.get(m)]
        charts["engagement_mix"] = chart("stacked_100", labels, [
            {"name": m.capitalize(), "values": [tot(by[lab], m) for lab in labels]} for m in mix])

    # Focus vs everything
    focus = None
    if focus_label and all_posts:
        rows = []
        for lab in labels:
            allp = all_posts[lab]
            fp = by[lab]
            rows.append([lab, len(fp), len(allp), r1(len(fp) / len(allp), 4) if allp else None,
                         r1(avg(fp, "views"), 0), r1(avg(allp, "views"), 0)])
        focus = {"label": focus_label, "table": {"columns": ["Period", "Focus posts", "All posts", "Share",
                                                             "Focus avg views", "All avg views"], "rows": rows}}
        charts["focus_vs_all"] = chart("column", labels, [
            {"name": "Focus posts", "values": [r[4] for r in rows]},
            {"name": "All posts", "values": [r[5] for r in rows]}], note="Average views per post")
        tables["focus_share"] = focus["table"]

    # Outliers
    md = med(C, "views") or 0
    for p in ranked[:5]:
        if md and (p["views"] or 0) >= 3 * md:
            outliers.append({"kind": "viral_post", "text":
                             f"{p['published']:%b %-d} {p['type'].lower()} by @{p['account']} drew {p['views']:,.0f} views — "
                             f"{p['views'] / md:.1f}× the median post (“{snippet(p['caption'], 50)}”)."})
    if has.get("follows"):
        fsorted = sorted(C, key=lambda p: -(p["follows"] or 0))
        if fsorted and fsorted[0]["follows"] and fsorted[0]["follows"] >= 5 * max(1, med(C, "follows") or 1):
            p = fsorted[0]
            outliers.append({"kind": "follow_driver", "text":
                             f"One {p['type'].lower()} ({p['published']:%b %-d}) brought {p['follows']:,.0f} new follows — "
                             f"{p['follows'] / max(1, tot(C, 'follows')):.0%} of the period's total."})
    if has.get("shares"):
        ssorted = sorted(C, key=lambda p: -(p["shares"] or 0))
        if ssorted and ssorted[0]["shares"] and ssorted[0]["shares"] >= 10 * max(1, med(C, "shares") or 1):
            p = ssorted[0]
            outliers.append({"kind": "share_spike", "text":
                             f"Most-shared post ({p['published']:%b %-d}, {p['shares']:,.0f} shares) is "
                             f"{p['shares'] / max(1, med(C, 'shares')):.0f}× the median."})
    if multi:
        for t in types:
            a0 = avg([p for p in P if p["type"] == t], "views")
            a1 = avg([p for p in C if p["type"] == t], "views")
            if a0 and a1 and abs(a1 - a0) / a0 >= 0.3:
                outliers.append({"kind": "type_shift", "text":
                                 f"Average {t.lower()} views went {'up' if a1 > a0 else 'down'} "
                                 f"{abs(a1 - a0) / a0:.0%} ({a0:,.0f} → {a1:,.0f})."})
        for m in months_present:
            n0 = sum(1 for p in P if p["published"].month == m)
            n1 = sum(1 for p in C if p["published"].month == m)
            if n0 >= 5 and n1 <= n0 * 0.4:
                outliers.append({"kind": "quiet_month", "text":
                                 f"{MONTHS[m - 1]} went quiet: {n1} posts vs {n0} in {prev}."})
            elif n1 >= 5 and n0 <= n1 * 0.4:
                outliers.append({"kind": "busy_month", "text":
                                 f"{MONTHS[m - 1]} was much busier: {n1} posts vs {n0} in {prev}."})

    # Facts
    k = K[cur]
    facts.append(f"{k['posts']} posts in {cur} drew {k['views']:,.0f} views"
                 + (f" ({kd['views']['pct']:+.0%} vs {prev})" if multi and kd.get('views', {}).get('pct') is not None else "") + ".")
    if k["avg_views"]:
        facts.append(f"Average post: {k['avg_views']:,.0f} views (median {k['median_views']:,.0f})"
                     + (f", vs {K[prev]['avg_views']:,.0f} in {prev}." if multi and K[prev]['avg_views'] else "."))
    if k["er"] is not None:
        facts.append(f"Engagement rate {k['er']:.1%} of reach (likes + comments + shares + saves).")
    if trows:
        best = max(trows, key=lambda r: r[2] or 0)
        facts.append(f"{best[0]}s averaged the most views: {best[2]:,.0f}.")
    if hrows:
        facts.append(f"Top hashtag by average views: {hrows[0][0]} ({hrows[0][2]:,.0f} across {hrows[0][1]} posts).")

    span = lambda ps: (min(p["published"] for p in ps).strftime("%b %-d, %Y"),  # noqa: E731
                       max(p["published"] for p in ps).strftime("%b %-d, %Y")) if ps else (None, None)
    flags = {
        "multi_edition": multi,
        "has_reach": bool(has.get("reach")),
        "has_shares": bool(has.get("shares")),
        "has_follows": bool(has.get("follows")),
        "has_hashtags": bool(hrows),
        "has_mentions": bool(tables["top_mentions"]["rows"]),
        "multi_account": len(acc) > 1,
        "has_reels": any(p["type"] == "Reel" for p in C),
        "has_focus": focus is not None,
    }
    return {
        "schema": 1,
        "kind": "social",
        "current": cur, "previous": prev,
        "editions": [{"label": p["label"], "files": p["files"], "range": p["range"],
                      "first_post": span(by[p["label"]])[0], "last_post": span(by[p["label"]])[1],
                      "platforms": sorted({x["platform"] for x in by[p["label"]]}),
                      "accounts": [a for a, _ in Counter(x["account"] for x in by[p["label"]]).most_common(3)],
                      "event_names": []} for p in periods],
        "focus": focus,
        "kpis": K, "kpi_delta": kd,
        "charts": charts, "tables": tables,
        "top_posts": top[:top_n],
        "outliers": outliers, "facts": facts, "flags": flags,
        "data_quality": {"columns": {p["label"]: p["cols"] for p in periods},
                         "skipped_rows": {p["label"]: p["bad"] for p in periods}},
    }


def summary(a):
    out = []
    for e in a["editions"]:
        k = a["kpis"][e["label"]]
        out.append(f"Period {e['label']}: {k['posts']} posts, {e['first_post']} → {e['last_post']}"
                   f"  ({', '.join(e['files'])}; platforms: {', '.join(e['platforms'])})")
        out.append(f"   views {k['views']:,.0f} · avg {k['avg_views'] or 0:,.0f} · median {k['median_views'] or 0:,.0f}"
                   + (f" · ER {k['er']:.1%}" if k['er'] is not None else "")
                   + f" · {k['accounts']} accounts · top: {', '.join('@' + x for x in e['accounts'] if x)}")
    for lab, cols in a["data_quality"]["columns"].items():
        miss = [m for m in METRICS if m not in cols]
        out.append(f"Columns {lab}: " + ", ".join(f"{k}←{v!r}" for k, v in cols.items())
                   + (f"  (missing: {', '.join(miss)})" if miss else ""))
    for lab, n in a["data_quality"]["skipped_rows"].items():
        if n:
            out.append(f"WARNING {lab}: skipped {n} rows with unreadable publish time")
    if a["focus"]:
        out.append("Focus: " + a["focus"]["label"])
        for r in a["focus"]["table"]["rows"]:
            out.append(f"   {r[0]}: {r[1]} of {r[2]} posts")
    out.append("Top posts (current):")
    for c in a["top_posts"][:5]:
        out.append(f"   {c['rank']}. {c['views']:,.0f} views  {c['date']}  @{c['account']}  {c['type']}  {c['permalink']}")
    th = a["tables"]["top_hashtags"]["rows"][:5]
    if th:
        out.append("Top hashtags: " + ", ".join(f"{r[0]} ({r[1]} posts, {r[2]:,.0f} avg)" for r in th))
    if a["outliers"]:
        out.append("Outliers:")
        out += ["   - " + o["text"] for o in a["outliers"]]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--output", default="analysis.json")
    ap.add_argument("--period", action="append", default=[], help="LABEL=file (override a period label)")
    ap.add_argument("--account", action="append", default=[])
    ap.add_argument("--hashtag", action="append", default=[])
    ap.add_argument("--mention", action="append", default=[])
    ap.add_argument("--keyword", action="append", default=[])
    ap.add_argument("--map", action="append", default=[], help='field="CSV header", e.g. views="Impressions"')
    ap.add_argument("--min-tag-posts", type=int, default=3, help="hashtags need this many posts to be ranked")
    ap.add_argument("--top", type=int, default=8, help="posts in the top-posts collage")
    a = ap.parse_args(argv)

    overrides = dict(m.split("=", 1) for m in a.map)
    forced = {}
    for spec in a.period:
        lab, f = spec.split("=", 1)
        forced[os.path.basename(f)] = lab

    match, focus_label = focus_filter(a)
    periods = {}
    for path in a.files:
        posts, cols, bad = load(path, overrides)
        lab, rng = label_for(path, posts)
        lab = forced.get(os.path.basename(path), lab)
        p = periods.setdefault(lab, {"label": lab, "files": [], "posts": [], "range": rng, "cols": cols, "bad": 0})
        p["files"].append(os.path.basename(path))
        ids = {x["id"] for x in p["posts"]}
        p["posts"] += [x for x in posts if x["id"] not in ids]
        p["bad"] += bad
    periods = sorted(periods.values(), key=lambda p: p["label"])
    if len(periods) > 2:
        print(f"note: {len(periods)} periods; YoY compares the last two ({periods[-2]['label']} → {periods[-1]['label']}).")

    has = {m: all(m in p["cols"] for p in periods) for m in METRICS}
    all_posts = None
    if match:
        all_posts = {p["label"]: list(p["posts"]) for p in periods}
        for p in periods:
            p["posts"] = [x for x in p["posts"] if match(x)]
        empty = [p["label"] for p in periods if not p["posts"]]
        if empty:
            sys.exit(f"Focus {focus_label} matches no posts in {', '.join(empty)}. "
                     "Check spelling, or run without a focus to see the top accounts and hashtags.")

    result = analyze(periods, has, focus_label, all_posts, a.min_tag_posts, a.top)
    with open(a.output, "w") as f:
        json.dump(result, f, indent=1, default=str)
    print(summary(result))
    print(f"\nWrote {a.output}")


if __name__ == "__main__":
    main()
