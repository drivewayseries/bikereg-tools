---
name: race-review-deck
description: Builds a post-race review slide deck (.pptx) from BikeReg registration CSVs — category, gender, location, team, registration-timing, age, revenue and rider-retention trends, year-over-year when given more than one year, with outliers called out and a takeaway headline on every slide. Asks for a race logo and themes the deck from its colors, on preset photo backgrounds pulled from GitHub. Use whenever a promoter, series director or team wants a race recap, post-event report, sponsor/board deck, season review, "how did the race do", YoY comparison of registrations, or slides from BikeReg data — even if they just say "make slides from these registrations" or attach a registration CSV and ask what changed.
---

# Race review deck

Turn one or more BikeReg registration CSVs plus a logo into a finished, editable PowerPoint deck. Scripts do the deterministic work; your job is to collect inputs, sanity-check what the scripts found, and write the story: a takeaway headline per slide, an executive summary, curated outliers, and recommendations.

```
scripts/palette.py      logo → palette.json (+ swatch PNG to show the user)
scripts/analyze.py      CSVs → analysis.json (KPIs, charts, tables, outliers) + console summary
scripts/build_deck.py   analysis + palette + logo + narrative + slide library → .pptx
slides/deck.json        the preset slide list; slides/backgrounds/*.jpg the photos
```

The slide library is fetched live from `github.com/drivewayseries/bikereg-tools` (same path as the bundled `slides/` folder) so edits there reach everyone; the bundled copy is the fallback. See `references/slide-library.md` only if the user wants to change slides, photos, or point at their own fork.

## 1. Collect inputs

Ask for everything missing in **one** message, in plain conversation (the answers are files and free text, not choices):

> To build the review I need:
> 1. **Registration CSVs** — one per year for a year-over-year comparison (or one file with several years). Either the CSV from the BikeReg registrations plugin or your BikeReg promoter export works.
> 2. **The race logo** — PNG or JPG, ideally with a transparent background. I'll build the deck's colors from it.
> 3. **The race name** as it should appear on the title slide, if it's not obvious from the files.

Uploaded files are usually in `/mnt/user-data/uploads`; in Claude Code the user may give paths. If they only have event IDs and the bikereg-registrations skill is available, offer to pull the CSV with it first.

Don't stall on optional things. No logo → build with a neutral palette and say they can rerun with one. One CSV → no YoY slides; that's fine.

Logo formats: SVG/PDF/AI can't be read directly. Try `rsvg-convert -w 1200 logo.svg -o logo.png` or `python3 -c "import cairosvg; cairosvg.svg2png(url='logo.svg', write_to='logo.png', output_width=1200)"`; if neither exists, ask for a PNG.

## 2. Set up

```bash
python3 -c "import pptx, PIL" 2>/dev/null || pip install python-pptx pillow
```

Work in a scratch folder; write the final deck to `/mnt/user-data/outputs` if it exists, else the working directory. `S="<skill base directory>/scripts"` below.

## 3. Palette from the logo

```bash
python3 "$S/palette.py" logo.png -o palette.json --swatch palette.png
```

Show the user the swatch image and the role assignments in one line ("Primary orange #F26522 for highlights, navy #12345F as second series — look right?"). The deck is dark (photo backgrounds), so the builder automatically lightens brand colors until they read on it; the swatch shows the original brand colors.

Read the `note:` lines and act on them:
- **Monochrome logo** (black/white only): ask if there's a brand accent color; pass it as `--primary "#hex"`.
- **Logo has a white box background**: fine — background is ignored for color, and the builder puts the logo on a white badge.
- **Small logo** (<300 px): mention it will look soft; ask for a larger file if they have one.
- The user can override any role: `--primary`, `--secondary`, `--accent`.

## 4. Analyze

```bash
python3 "$S/analyze.py" race_2023.csv race_2024.csv race_2025.csv -o analysis.json
```

Read the console summary carefully before going on — it's where data problems show up:

- **Editions**: one per year, oldest → newest, the last one is "current". Labels come from a year in the event name, then the file name, then the last registration date. If they're wrong, or one file holds several years, or a multi-day race has one event ID per day, regroup explicitly: `--edition "2024=70011" --edition "2025=74062,74063"` (tokens may be event IDs, event names, or file names). Confirm the grouping with the user when it isn't obvious.
- **Columns** mapped per file. If the category column wasn't found or something is mapped wrong, fix with `--map category="Category Entered"`.
- **Excluded rows**: merchandise/donation rows are dropped automatically. If a real race got excluded (e.g. a category literally named "Kit Grab"), rerun with `--include-nonrace` plus `--exclude-category "<regex>"`.
- **Event dates** default to the last registration date, which is close enough for the pacing chart. If the user gives real dates, pass `--event-date 2025=2025-06-07`.
- **Home state** defaults to the most common rider state; override with `--home-state`.
- **Category lineup changes**: a renamed category ("Men Cat 5" → "Men Beginner") appears as one new + one dropped. Spot these and treat them as a rename in the narrative rather than "we lost a category".

## 5. Plan, then write the narrative

```bash
python3 "$S/build_deck.py" --analysis analysis.json --plan
```

This lists every preset slide and whether it will be built (slides whose data is missing — no prices, single year, no reg dates — are skipped automatically). Then read `analysis.json` (`kpis`, `kpi_delta`, `charts`, `tables`, `outliers`, `facts`) and write `narrative.json`:

```json
{
  "race_name": "Riverside Crit",
  "subtitle": "2025 Race Review",
  "date_line": "June 7, 2025 · Riverside Park",
  "summary": ["4–5 bullets: the most important things that happened, each with a number"],
  "slides": {
    "<slide id>": {
      "headline": "Takeaway sentence with the number, ≤ ~90 chars",
      "bullets": ["optional 2–3 supporting points → shown in a TAKEAWAYS panel"],
      "notes": "optional speaker notes",
      "skip": false
    }
  },
  "outliers": ["curated: 4–7 things that are genuinely surprising, explained"],
  "recommendations": ["3–5 concrete actions for next year, each tied to a finding"],
  "extra_slides": [{"after": "<slide id>", "id": "custom_1", "title": "…", "bullets": ["…"]}]
}
```

How to write it well:

- **Every included chart/table slide gets a headline that states the finding**, not the topic. "Women's entries up 73% to 26 after adding a Beginner field", not "Women's field sizes". The preset title is only a fallback.
- **Lead with what changed and by how much.** Use `kpi_delta` for YoY; compare against the previous edition, and mention longer trends when there are 3+ years.
- **Curate the outliers** instead of copying them: drop artifacts (renames, a "spike" that is just the opening day), merge related ones, and say what each might mean. Registration spikes usually line up with a price increase, an email blast, or a closing deadline — say so as a question or hypothesis, and if the user is around, ask them what happened that day; their answer makes the best slide in the deck.
- **Don't claim causes the data can't show.** "Masters 50+ fell from 27 to 12" is a fact; "because of the date change" is the user's call.
- **Recommendations** should follow from findings (small fields → combine starts; late-registration surge → move the price step; low women's share → women's clinic or free entry), and be specific to this race.
- **Use `skip: true`** for slides that would mislead or add nothing (e.g. a gender chart where 40% is "Unspecified" because the race is mostly kids' fields — say that in a note on another slide instead).
- **No rider names** anywhere in the deck. Team names and places are fine. The analysis output never contains names, emails, or addresses; keep it that way.
- Gender, when inferred from category names, is approximate — `data_notes` says so automatically.

## 6. Build and check

```bash
python3 "$S/build_deck.py" --analysis analysis.json --palette palette.json --logo logo.png \
    --narrative narrative.json -o "<Race> <Year> Race Review.pptx"
```

The script reports which slide library it used (GitHub vs bundled — either is fine), what it built and skipped, and any narrative ids that didn't match a built slide (fix typos and rebuild).

Then look at the deck before handing it over. If you can render it, do: LibreOffice (`soffice --headless --convert-to pdf deck.pptx`, then view pages), or Keynote on a Mac via `osascript` (`export … as slide images`). Check for headlines wrapping past two lines, crowded category labels, and charts that are mostly zeros. If you can't render, at least re-open the file with python-pptx and confirm the slide count and that every chart slide has a chart. Fix by shortening headlines, setting `skip`, or adjusting the analysis flags — not by hand-editing the .pptx.

## 7. Deliver

Send the .pptx. In the message: slide count, the 3–4 headline findings, which slides were skipped and why (e.g. "no revenue slide — only the 2025 export had prices"), and the caveats that apply:

- Counts are **entries**, not riders, unless the slide says riders; riders are matched by first + last name across years.
- **Gender inferred from category names** when the CSV had no gender column.
- **Event date estimated** from the last registration when not given.

Offer the obvious next steps: real event dates, a sponsor-facing version (skip internal slides like revenue), or a different slide order — all of which are one rebuild.

## If GitHub can't be reached

The builder silently falls back to the bundled slide library and prints a `note:`. That's expected in sandboxes with no network or with Python lacking CA certificates (`pip install certifi` fixes the latter). Don't try other routes to GitHub; mention in the delivery message that the bundled slide set was used only if the user is expecting a recent change to the slides.
