---
name: social-review-deck
description: Builds a social media performance review slide deck (.pptx) for a bike race, series or team from Meta (Instagram / Facebook) post-export CSVs — year-over-year comparison when given two exports, top posts with a collage, best post types, hashtag and partner performance, best days and times to post, outliers, and a takeaway headline on every slide. Asks whether to focus on one brand, account, sponsor or hashtag, themes the deck from the logo's colors, and uses the same preset photo backgrounds as race-review-deck, pulled from GitHub. Use whenever someone wants an Instagram or Facebook recap, social media report, sponsor social stats, "how did our posts do", YoY social comparison, or slides from a Meta Business Suite export, even if they just attach a Meta CSV and ask what's working.
---

# Social media review deck

Turn one or two Meta post exports plus a logo into a finished, editable PowerPoint deck. Scripts do the deterministic work. Your job is to collect inputs, ask about focus, sanity-check what the scripts found, and write the story: a takeaway headline per slide, an executive summary, curated outliers, and recommendations.

```
scripts/analyze.py      Meta CSVs (+ optional focus) → analysis.json + console summary
scripts/palette.py      logo → palette.json (+ swatch PNG to show the user)
scripts/build_deck.py   analysis + palette + logo + narrative + top-post images + slide library → .pptx
slides/deck.json        the preset slide list. Photos are shared with race-review-deck.
```

The slide list is fetched live from `github.com/drivewayseries/bikereg-tools`, and the photos from race-review-deck's `slides/backgrounds/` in the same repo. Edits on `main` reach everyone. The bundled copies are the fallback. See `references/slide-library.md` only if the user wants to change slides or photos.

## 1. Collect inputs

Ask for everything missing in **one** plain message:

> To build the review I need:
> 1. **Meta post exports (CSV)**: one per year for a year-over-year comparison, or just one. In Meta Business Suite: Insights → Content → set the date range → Export data → CSV. Export the same date window each year (e.g. Jan 1 – Oct 31) so the comparison is fair.
> 2. **Your logo**: PNG or JPG. I'll build the deck colors from it.
> 3. **The name** for the title slide (race, series or team).
> 4. *Optional:* **images of your top posts** for the collage. I'll tell you which posts once I've run the numbers.

Uploaded files are usually in `/mnt/user-data/uploads`. In Claude Code the user may give paths. Don't stall on optional things. No logo → neutral palette. One CSV → no YoY slides.

## 2. Set up

```bash
python3 -c "import pptx, PIL" 2>/dev/null || pip install python-pptx pillow
```

Work in a scratch folder. Write the final deck to `/mnt/user-data/outputs` if it exists, else the working directory. `S="<skill base directory>/scripts"` below.

## 3. First pass, then ask about focus

Run the analysis on everything first:

```bash
python3 "$S/analyze.py" export_2025.csv export_2026.csv -o analysis.json
```

Read the summary. Meta exports often mix the user's own account with **collaborator posts** (other accounts that tagged the race as a collaborator), so a "drivewayseries" export can hold 25+ posting accounts. Then **ask the focus question**, with the AskUserQuestion tool if you have it, else in one short message. Build the options from the summary:

- **Everything in the export** (the default)
- **Just @<main account>**: the account with the most posts
- **A hashtag**: the race's own tag if one shows up (e.g. `#drivewayseries`)
- **A sponsor or partner**: posts that @-mention them. Name the top mentioned account.

The user can name anything else: another account, a campaign hashtag, a keyword. Rerun with the matching flags. Several flags combine, and a post matches if it matches any of them:

```bash
python3 "$S/analyze.py" a.csv b.csv --account drivewayseries -o analysis.json
python3 "$S/analyze.py" a.csv b.csv --hashtag drivewayseries --mention trekrideclubatx -o analysis.json
python3 "$S/analyze.py" a.csv b.csv --keyword "gold sprint" -o analysis.json
```

With a focus, the deck adds a "focus vs all posts" slide. Pass a nicer label in the narrative (`"focus_name": "Trek Ride Club posts"`).

Check in the summary:
- **Periods**: labelled from Meta's file name (`Dec-31-2024_Oct-31-2025_…` → 2025), else the year most posts fall in. Fix with `--period 2025=file.csv`. If the two windows differ in length, compare per-post averages, not totals, and say so.
- **Columns**: if a metric shows as missing (Facebook exports name things differently), map it: `--map views="Impressions"`. Slides needing a missing metric drop out.
- **Focus matched nothing** → the script stops. Check the spelling against the summary's accounts and hashtags.

## 4. Top-post images for the collage (optional)

The summary lists the top posts with their links. Instagram doesn't allow downloading post images without logging in, so **don't try to fetch or scrape them**. Ask the user instead:

> Want real images in the top-posts collage? Screenshot or save these 8 posts and send them back, named 1–8 in this order (or with the post code in the name, e.g. `DanmavQuJH1.jpg`): <list rank, date, account, link>. Otherwise I'll use styled text tiles. Every tile links to its post either way.

Put the images in one folder and pass `--images folder/`. Partial sets are fine.

## 5. Palette from the logo

```bash
python3 "$S/palette.py" logo.png -o palette.json --swatch palette.png
```

Show the swatch and the role assignments in one line. Act on its `note:` lines: monochrome logo → ask for an accent color (`--primary "#hex"`). Small logo → mention it'll look soft.

## 6. Plan, then write the narrative

```bash
python3 "$S/build_deck.py" --analysis analysis.json --plan
```

Read `analysis.json` (`kpis`, `kpi_delta`, `charts`, `tables`, `top_posts`, `outliers`, `facts`) and write `narrative.json`:

```json
{
  "name": "Driveway Series",
  "subtitle": "2026 Social Media Review",
  "date_line": "Instagram · Jan 1 – Oct 31, 2026 vs 2025",
  "focus_name": "optional label for the focus slide",
  "summary": ["4–5 bullets, each with a number"],
  "slides": {
    "<slide id>": {"headline": "Takeaway with the number, ≤ ~90 chars", "bullets": ["optional 2–3 points"], "notes": "", "skip": false}
  },
  "outliers": ["4–7 curated, explained"],
  "recommendations": ["3–5 concrete actions, each tied to a finding"],
  "extra_slides": [{"after": "<slide id>", "id": "custom_1", "title": "…", "bullets": ["…"]}]
}
```

How to read social data well:

- **Headlines state the finding, not the topic.** "Reels averaged 9.4k views, 2× carousels, but were only 16% of posts", not "Views by post type".
- **Lead with per-post performance, not totals.** Total views mostly track how many posts went out. Average and **median** views per post show whether the content got better. When one viral post skews the average, say so and use the median.
- **Lifetime metrics favor older posts.** Posts from the last few weeks before the export haven't finished collecting views. Don't call a recent month "weak" without saying that.
- **Collaborator posts are a story.** If partner accounts (a club, a photographer, a sponsor) produced the biggest posts, say so. It's a reason to keep collaborating. Don't credit their reach to the race's own account.
- **Hashtags are usually sparse.** If few posts use hashtags, or the "top hashtag" has only 3 posts, say the evidence is thin rather than recommending a tag. With no hashtag slides, put one line about it in the summary or data notes.
- **Engagement rate** here is (likes + comments + shares + saves) ÷ reach. Shares and saves signal stronger interest than likes. Follows show which posts grew the audience.
- **Timing slides are averages over few posts per bucket.** Treat a best day/time as a hint unless the gap is large and the buckets have 10+ posts. The chart doesn't show counts, so check `weekday_posts`.
- **Curate the outliers.** Merge related ones (three viral carousels from the same partner are one story). Ask the user what happened around a spike: race day, a giveaway, a reposted reel. Their answer makes the best slide.
- **Don't claim causes the data can't show.** "Views per post fell 15%" is a fact. "Because the algorithm changed" isn't.
- **Recommendations** follow from findings: more of the post type that over-performs, collaborate again with the accounts that drove reach, post race-day recaps within 24 hours if those led, drop hashtags that didn't move anything, fill months that went quiet.
- **Use `skip: true`** for slides that mislead or add nothing (a bottom-posts slide that's just the newest posts, a hashtag YoY table with two rows).
- **No personal data beyond public handles.** Account handles and captions are public post content. Don't add anything else about individuals.

## 7. Build and check

```bash
python3 "$S/build_deck.py" --analysis analysis.json --palette palette.json --logo logo.png \
    --narrative narrative.json --images top_posts/ -o "<Name> <Year> Social Media Review.pptx"
```

The script reports the slide library used (GitHub or bundled, either is fine), slides built and skipped, which collage tiles had no image, and narrative ids that didn't match.

Look at the deck before handing it over. If you can render it (LibreOffice `soffice --headless --convert-to pdf`, or Keynote via `osascript`), check for headlines past two lines, long captions crowding table rows, and charts that are mostly empty. If you can't render, re-open with python-pptx and confirm the slide count and that every chart/table slide has its chart or table. Fix by shortening headlines, `skip`, or analysis flags, not by hand-editing the .pptx.

## 8. Deliver

Send the .pptx. In the message: slide count, the 3–4 headline findings, focus used (if any), slides skipped and why, and the caveats that apply:

- Lifetime metrics as of export date, so recent posts are undercounted.
- Collaborator posts included (or filtered out by the focus).
- Collage tiles without images: the user can send images and you'll rebuild.

Offer next steps: a sponsor-facing version focused on their mentions, a different focus, or adding real images to the collage. Each is one rebuild.

## If GitHub can't be reached

The builder falls back to the bundled slide list and photos and prints a `note:`. That's expected in sandboxes without network access. Don't try other routes.
