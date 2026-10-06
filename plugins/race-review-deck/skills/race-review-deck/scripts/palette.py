#!/usr/bin/env python3
"""Derive a deck color palette from a race logo.

    python3 palette.py logo.png -o palette.json --swatch palette.png
    python3 palette.py logo.png --primary "#0B5FFF"     # override one role

Finds the logo's dominant brand colors (ignoring transparency, the background,
and near-white/near-black), assigns roles (primary, secondary, accent), and
derives everything a deck needs: chart series colors that hold up on white,
readable text colors on the primary, tints for panels, and a neutral for prior
years. Also writes a PNG copy of the logo that PowerPoint can embed (for
JPG/WebP/GIF inputs) and an optional swatch image to show the user.

Requires Pillow.
"""

import argparse
import colorsys
import json
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: pip install pillow")


# --- color math --------------------------------------------------------------

def hex_of(rgb):
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in rgb))


def rgb_of(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a hex color: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hls(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def from_hls(h, l, s):
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s))))


def mix(a, b, t):
    """t=0 -> a, t=1 -> b"""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def dist(a, b):
    # Weighted RGB distance ("redmean") — cheap and good enough for merging swatches.
    rm = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def hue_gap(a, b):
    d = abs(hls(a)[0] - hls(b)[0])
    return min(d, 1 - d) * 360


def is_neutral(rgb):
    _, l, s = hls(rgb)
    return s < 0.15 or l > 0.94 or l < 0.08


def darken_until(rgb, bg, ratio):
    """Darken (keeping hue) until contrast against bg reaches ratio."""
    h, l, s = hls(rgb)
    out = rgb
    while contrast(out, bg) < ratio and l > 0.05:
        l -= 0.02
        out = from_hls(h, l, s)
    return out


def lighten_until(rgb, bg, ratio):
    """Lighten (keeping hue) until contrast against a dark bg reaches ratio."""
    h, l, s = hls(rgb)
    out = rgb
    while contrast(out, bg) < ratio and l < 0.95:
        l += 0.02
        out = from_hls(h, l, s)
    return out


WHITE = (255, 255, 255)
INK = (31, 35, 40)


def for_background(pal, bg_hex):
    """Theme colors for drawing on bg_hex. Brand colors keep their hue but are
    pushed lighter (dark bg) or darker (light bg) until they read clearly."""
    bg = rgb_of(bg_hex)
    dark = luminance(bg) < 0.2
    fit = (lambda c, r: lighten_until(c, bg, r)) if dark else (lambda c, r: darken_until(c, bg, r))
    brand = rgb_of(pal["primary"])
    if dark:
        t = {"text": "#F2F3F5", "muted": "#A3AAB5", "gridline": "#343842", "prior": "#6B7280",
             "prior_2": "#4A505A", "positive": "#56D364", "negative": "#FF7B72",
             "panel": bg_hex, "row_alt": hex_of(mix(bg, WHITE, 0.06))}
    else:
        t = {"text": pal["ink"], "muted": pal["muted"], "gridline": pal["gridline"], "prior": pal["prior"],
             "prior_2": pal["prior_2"], "positive": pal["positive"], "negative": pal["negative"],
             "panel": pal["panel"], "row_alt": hex_of(mix(rgb_of(pal["panel"]), WHITE, 0.5))}
    if pal.get("monochrome"):
        ramp = [(236, 238, 241), (170, 176, 185), (120, 127, 137), (205, 209, 215), (95, 101, 110)] if dark \
            else [rgb_of(c) for c in pal["chart"]]
        t["chart"] = [hex_of(c) for c in ramp]
        t["highlight"] = hex_of(ramp[0])
    else:
        seen = []
        for c in pal["chart"]:
            c2 = fit(rgb_of(c), 3.0)
            if all(dist(c2, s) > 35 for s in seen):
                seen.append(c2)
        t["chart"] = [hex_of(c) for c in seen]
        t["highlight"] = hex_of(fit(brand, 4.5))
    # A solid brand fill for bars/headers, with whichever text color reads on it.
    t["band"] = pal["band"]
    t["on_band"] = pal["on_band"]
    return t


# --- extraction --------------------------------------------------------------

def load_logo(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".svg", ".svgz"):
        sys.exit("SVG logos need converting to PNG first (rsvg-convert, cairosvg, or Inkscape), "
                 "or ask the user for a PNG/JPG version.")
    if ext in (".pdf", ".ai", ".eps"):
        sys.exit(f"{ext} logos can't be read directly — ask the user for a PNG or JPG export.")
    im = Image.open(path)
    im.load()
    return im


def pixel_list(im):
    # Pillow 12 deprecates getdata() in favour of get_flattened_data().
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def border_color(im):
    """Most common color along the image edge, or None when the edge is transparent."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    edge = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)] + \
           [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    opaque = [p[:3] for p in edge if p[3] > 200]
    if len(opaque) < len(edge) * 0.6:
        return None
    buckets = {}
    for p in opaque:
        k = tuple(c // 16 for c in p)
        buckets.setdefault(k, []).append(p)
    best = max(buckets.values(), key=len)
    if len(best) < len(edge) * 0.5:
        return None
    return tuple(sum(c) // len(best) for c in zip(*best))


def extract(im, n=10):
    """Return [(rgb, share)] of the logo's colors, background removed, most common first."""
    bg = border_color(im)
    rgba = im.convert("RGBA")
    rgba.thumbnail((300, 300))
    pixels = [p[:3] for p in pixel_list(rgba) if p[3] >= 128]
    if bg is not None:
        pixels = [p for p in pixels if dist(p, bg) > 60]
    if not pixels:
        return [], bg
    strip = Image.new("RGB", (len(pixels), 1))
    strip.putdata(pixels)
    q = strip.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    found = [((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), c / total) for c, i in counts]
    merged = []
    for rgb, sh in found:
        for m in merged:
            if dist(m[0], rgb) < 45:
                m[1] += sh
                break
        else:
            merged.append([rgb, sh])
    merged.sort(key=lambda m: -m[1])
    return [(tuple(m[0]), round(m[1], 4)) for m in merged if m[1] >= 0.01], bg


def build_palette(colors, overrides):
    chromatic = [(c, s) for c, s in colors if not is_neutral(c)]
    neutrals = [(c, s) for c, s in colors if is_neutral(c)]
    notes = []

    # Prefer area, but nudge toward saturated colors — a thin red stripe is more
    # "the brand" than a large muddy fill.
    ranked = sorted(chromatic, key=lambda cs: -(cs[1] * (0.5 + hls(cs[0])[2])))
    primary = ranked[0][0] if ranked else None
    secondary = next((c for c, _ in ranked[1:] if hue_gap(c, primary) >= 25), None) if primary else None
    accent = next((c for c, _ in ranked[1:] if c != secondary and
                   hue_gap(c, primary) >= 25 and (secondary is None or hue_gap(c, secondary) >= 25)), None) \
        if primary else None

    dark_neutral = next((c for c, _ in neutrals if hls(c)[1] < 0.35), None)
    monochrome = primary is None
    if monochrome:
        primary = dark_neutral or INK
        notes.append("Logo has no brand color (black/white/grey only). Primary is the logo's dark tone; "
                     "charts use a grey ramp. Ask the user for an accent color if they want one.")

    for role in ("primary", "secondary", "accent"):
        if overrides.get(role):
            val = rgb_of(overrides[role])
            if role == "primary":
                primary = val
                monochrome = False
            elif role == "secondary":
                secondary = val
            else:
                accent = val
            notes.append(f"{role} set by user to {hex_of(val)}")

    h, l, s = hls(primary)
    if secondary is None and not monochrome:
        # One-color logo: derive a companion by shifting hue and lightness rather
        # than inventing an unrelated color.
        secondary = from_hls(h + 0.08, min(0.7, l + 0.18), s * 0.85)
        notes.append("Only one brand color in the logo; secondary is a lighter analogous shade.")
    if accent is None and not monochrome:
        accent = from_hls(h - 0.08, max(0.25, l - 0.12), min(1, s * 1.05))

    # Chart colors need >= 3:1 against white (WCAG non-text contrast).
    chart = []
    if monochrome:
        chart = [primary, (110, 117, 125), (160, 166, 173), (198, 203, 209), (80, 86, 94)]
    else:
        for c in (primary, secondary, accent):
            chart.append(darken_until(c, WHITE, 3.0))
        # Fill out to 8 series with tints/shades of the brand colors.
        for base, t in ((primary, 0.45), (secondary, 0.45), (primary, -0.35), (accent, 0.45), (secondary, -0.35)):
            if t > 0:
                c = mix(base, WHITE, t)
            else:
                c = mix(base, (0, 0, 0), -t)
            chart.append(c)
    # Drop near-duplicates but keep at least 5.
    uniq = []
    for c in chart:
        if all(dist(c, u) > 40 for u in uniq):
            uniq.append(c)
    chart = uniq if len(uniq) >= 5 else chart

    on_primary = WHITE if contrast(WHITE, primary) >= 4.5 else INK
    if on_primary == INK and contrast(INK, primary) < 4.5:
        notes.append("Primary is mid-tone; titles on it may be hard to read — section slides darken it.")
    primary_dark = darken_until(primary, WHITE, 7.0)
    band = primary if contrast(on_primary, primary) >= 4.5 else primary_dark
    ink = mix(INK, primary_dark, 0.15)
    title_text = darken_until(primary, WHITE, 4.5)

    out = {
        "primary": hex_of(primary),
        "secondary": hex_of(secondary) if secondary else None,
        "accent": hex_of(accent) if accent else None,
        "band": hex_of(band),
        "on_band": hex_of(WHITE if contrast(WHITE, band) >= contrast(INK, band) else INK),
        "title_text": hex_of(title_text),
        "ink": hex_of(ink),
        "muted": "#6B7280",
        "gridline": "#E3E6EA",
        "panel": hex_of(mix(primary, WHITE, 0.92)),
        "prior": "#B8BEC6",
        "prior_2": "#D5D9DE",
        "positive": "#1A7F37",
        "negative": "#C2361F",
        "chart": [hex_of(c) for c in chart],
        "monochrome": monochrome,
        "logo_colors": [{"hex": hex_of(c), "share": s} for c, s in colors],
        "notes": notes,
    }
    return out


def swatch(pal, path):
    roles = [("primary", pal["primary"]), ("secondary", pal["secondary"]), ("accent", pal["accent"]),
             ("band", pal["band"]), ("ink", pal["ink"]), ("panel", pal["panel"]), ("prior", pal["prior"])]
    roles = [(n, c) for n, c in roles if c]
    chart = pal["chart"]
    w = 120
    im = Image.new("RGB", (w * max(len(roles), len(chart)), 260), "white")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for i, (name, c) in enumerate(roles):
        d.rectangle([i * w + 6, 6, (i + 1) * w - 6, 96], fill=c, outline="#DDDDDD")
        d.text((i * w + 8, 102), f"{name}\n{c}", fill="#222222", font=font)
    for i, c in enumerate(chart):
        d.rectangle([i * w + 6, 150, (i + 1) * w - 6, 220], fill=c)
        d.text((i * w + 8, 226), f"chart {i + 1}\n{c}", fill="#222222", font=font)
    im.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logo")
    ap.add_argument("-o", "--output", default="palette.json")
    ap.add_argument("--swatch", help="write a PNG preview of the palette here")
    ap.add_argument("--logo-png", help="write a PNG copy of the logo here (for embedding)")
    ap.add_argument("--primary")
    ap.add_argument("--secondary")
    ap.add_argument("--accent")
    a = ap.parse_args(argv)

    im = load_logo(a.logo)
    colors, bg = extract(im)
    pal = build_palette(colors, {"primary": a.primary, "secondary": a.secondary, "accent": a.accent})
    pal["logo_background"] = hex_of(bg) if bg else "transparent"
    pal["logo_size"] = list(im.size)

    if a.logo_png:
        conv = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA", "PA") else im.convert("RGB")
        conv.save(a.logo_png, "PNG")
        pal["logo_png"] = os.path.abspath(a.logo_png)

    with open(a.output, "w") as f:
        json.dump(pal, f, indent=1)
    if a.swatch:
        swatch(pal, a.swatch)

    print("Logo colors: " + ", ".join(f"{c['hex']} ({round(c['share'] * 100)}%)" for c in pal["logo_colors"]))
    print(f"Logo background: {pal['logo_background']}")
    for role in ("primary", "secondary", "accent", "band", "title_text", "ink"):
        print(f"  {role:<10} {pal[role]}")
    print("  chart      " + " ".join(pal["chart"]))
    for n in pal["notes"]:
        print("note: " + n)
    if min(im.size) < 300:
        print(f"note: logo is only {im.size[0]}×{im.size[1]}px and will look soft on a title slide; "
              "ask for a larger version if one exists.")
    print(f"Wrote {a.output}" + (f" and {a.swatch}" if a.swatch else ""))


if __name__ == "__main__":
    main()
