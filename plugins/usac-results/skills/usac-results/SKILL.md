---
name: usac-results
description: Pulls USA Cycling race results from the Sport80 results site (usacycling.sport80.com) into one verified CSV — every day, discipline and category of an event, with place (including DNF/DNS/DQ), name, city, state, team, USAC license #, bib, time, points and gender. Use whenever the user wants USAC results, finishers, podiums, field sizes from results, who raced or started, or a Sport80 results export, or pastes a usacycling.sport80.com results link — whether or not they have the URL ready; the skill asks for it. Up to 20 events per run, appended into a single file.
---

# USA Cycling results → CSV

Turn Sport80 event results URLs into one CSV of every result, verified against Sport80's own per-race totals. The work is done by `scripts/usac_results.py` (standard library only, no install). Your job is to get the URLs from the user, run the script, and check the result before handing it over.

## 1. Ask which events

**If the user has not given a results URL, ask before doing anything else**, in plain conversation:

> Which events? Paste a USA Cycling results link for each — any day or race of the event is fine. Up to 20 at a time.

Then wait. Do not guess or search for an event.

**Where the URL comes from:** on usacycling.sport80.com → Results, open the event and pick any day. The address looks like `https://usacycling.sport80.com/pub/results/events/30723/d/crit/2026-06-07?text=...`. One URL per event is enough: the script finds every other day and discipline from it.

### Reading what they paste

Pass URLs through unchanged. Sport80 URLs often contain commas and spaces inside `?text=`, so **quote each URL** on the command line, and don't split them on commas yourself. The script splits on whitespace only and collapses several URLs for the same event into one.

### Edge cases

- **A bare event number or an event name** ("Tulsa Tough"): the script needs the full results URL (it has no event search, and the page path needs a discipline and a date). Ask for the link and tell them where to find it.
- **A BikeReg link, a USAC page that isn't a results page, or a registration link**: say which one you couldn't read. For BikeReg registrations, point them to the bikereg-registrations skill.
- **More than 20 events**: do not run. Offer batches of 20.
- **Results not posted yet**: Sport80 only has an event after the officials upload results. An upcoming race has nothing to pull.

## 2. Run the script

```bash
python3 "<skill base directory>/scripts/usac_results.py" "<url 1>" "<url 2>" -o "<output dir>"
```

- Output dir: `/mnt/user-data/outputs` when it exists, otherwise the working directory.
- Per event-day it makes 4 page requests (the day plus its Male/Female/Mixed filters) and one per race, 1 s apart. A 3-day event with 30 races takes about a minute. Never lower `--delay`; raise it to 3 if the script reports rate limiting.

The script prints per event the name, each day's race and result counts, the total with unique riders and the placed/DNF/DNS/DQ split, the gender split and any `note:` lines, then the CSV path. It ends with `Verified: every race's row count matches Sport80's own total.` (exit 0), or `MISMATCH` lines (exit 1).

## 3. If it can't fetch

- **`CERTIFICATE_VERIFY_FAILED`**: the user's Python has no CA certificates (common with python.org Python on macOS). Re-run with `/usr/bin/python3`. The script prints the other fixes. Never disable TLS verification.
- **403 / proxy / network block**: deliver the script to the user and give them the command to run in their own Terminal, with `-o ~/Downloads` and their URLs filled in. Ask them to attach the CSV and paste the printed summary, then continue at step 4.
- **429**: re-run with `--delay 3`; if that also fails, wait a few minutes and split into smaller batches.

Don't route around a block with `curl`, a browser, or other tools. The script writes nothing when a fetch fails, so there are never partial results to present.

## 4. Verify before delivering

- Exit code 0 and the `Verified:` line present. On `MISMATCH`, report the lines verbatim and don't present the file as complete. It usually means Sport80 changed its pages; run `scripts/test_usac.py` (offline). If it passes, the live site changed and the script needs updating.
- Re-count the CSV yourself (python `csv` module): the row count equals the printed totals summed, and `Event ID` has exactly the requested events.
- Read the `note:` lines: races under none of Sport80's gender filters get `Unspecified`.

## 5. Deliver

Send the CSV. In the message give per event: name, location, each day's races and results, the total, unique riders, placed/DNF/DNS/DQ and the gender split, then the file name. Keep it short.

Always state these, because they are easy to misread:

- **One row per race result, not per rider.** A rider who raced three days appears three times. Unique riders are counted by USAC license #, or by name when there's no license.
- **DNS rows are riders who were entered but didn't start.** So the file is closer to the entry list than a finishers list, but it isn't registrations: there's no registration date, and riders who withdrew before results were posted aren't there. For registrations, use bikereg-registrations.
- **Gender comes from Sport80's own Male/Female/Mixed filters**, not from category names. Junior or open races are usually `Mixed`.
- Riders without a USAC license (international, one-day) have blank USAC #, City/State and Points.
- Time is often `0` in crits, where officials post places only.

## Columns

`Event, Event ID, Date, Discipline, Race Category, Gender, Place, Name, City, State, Team, USAC #, Bib, Time, Points`

`Date` is `YYYY-MM-DD`, the day of that race. `Place` is a number or `DNF`, `DNS`, `DQ` and so on. `Name` is kept as Sport80 shows it (it isn't split, since some are `First LAST`).

## How it works (for troubleshooting only)

The results site is an Inertia.js app. Each page (`/pub/results/events/<event>/d/<discipline>/<date>`) embeds its data as JSON in the `data-page` attribute of `<div id="app">`: `event_results_page.discipline_filters` lists every day and discipline, and `race_results_datatables` lists each race's `race_id` and title. The same page with `?gender=M|F|N` lists only that gender's races. Each race's results come from `POST /pub/results/races/<race_id>/datatable?data=1` (body `{}`), which returns `{total, data: [...]}`. Cells are either plain values or `{type: "unset"}`, `{type: "hyperlink", value}` or `{text, type}`. The script compares each race's row count to `total`.
