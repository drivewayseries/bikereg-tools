---
name: bikereg-registrations
description: Pulls the public "Who's Registered" list from BikeReg events into one verified CSV (name, race category, gender, team, city, state, reg date). Use when the user gives bikereg.com event IDs or URLs and asks for registrations, entrants, riders, a start list, field sizes, or who's registered. Handles up to 20 events per run and appends them into a single file.
---

# BikeReg registrations → CSV

Turn BikeReg event IDs into one CSV of every registration, verified against BikeReg's own entry counts. The work is done by `scripts/bikereg_registrations.py` (standard library only, no install). Your job is to run it, handle the one environment where it can't run, and check the result before handing it over.

## 1. Collect the event IDs

Accept any of these, mixed freely: bare IDs (`74062`), event URLs (`https://www.bikereg.com/74062`), or confirmed-list URLs (`.../Confirmed/74062`). The script extracts the ID from each.

- Duplicates are fine; the script collapses them.
- **More than 20 unique events**: do not run. Tell the user the limit is 20 per run and ask which batch to do first (or offer to run two batches and deliver two CSVs).
- If the user gives an event *name* instead of an ID, ask for the ID or URL. Do not guess IDs.

## 2. Run the script

The script is in the `scripts/` folder next to this SKILL.md — use the base directory reported when this skill loaded.

```bash
python3 "<skill base directory>/scripts/bikereg_registrations.py" 74062 73918 -o "<output dir>"
```

- Output dir: `/mnt/user-data/outputs` when it exists, otherwise the working directory.
- Add `--minimal` only if the user asks for just names/category/gender.
- Add `--separate` only if the user asks for one file per event as well.
- It takes ~1–3 seconds per event category (a large stage race has 50+ categories), so allow up to a few minutes for 20 events. Do not lower `--delay`.

The script prints, per event, the title, entry count, unique riders, category count, and gender split, then the combined CSV path, and ends with either `Verified: every category matches BikeReg's own entry counts.` (exit 0) or a list of `MISMATCH` lines (exit 1).

## 3. If the network is blocked: fall back to the user's machine

Some organizations block bikereg.com from Claude's sandbox. The script detects this and exits with a message beginning `Could not fetch` that mentions a proxy/403 and suggests a normal terminal. When you see that:

1. Deliver the script itself to the user (send the file) so they have a copy.
2. Give them the exact command to run in their Terminal, with their event IDs filled in and `-o ~/Downloads`:
   ```
   python3 ~/Downloads/bikereg_registrations.py 74062 73918 -o ~/Downloads
   ```
3. Ask them to attach the resulting CSV (and paste the script's printed summary) back here.
4. When it arrives, continue at step 4 using the attached file.

A different failure, `CERTIFICATE_VERIFY_FAILED`, is not a block: the user's Python has no CA certificates (common with python.org Python on macOS). The script prints the fixes; relay them and suggest `/usr/bin/python3` first. Never work around it by disabling TLS verification.

Do not try `curl`, `requests`, a browser, or any other route around the block — the script is the supported path, and the block is policy, not a bug.

## 4. Verify before delivering

Never hand over a CSV you have not checked:

- Exit code 0 and the `Verified:` line present. If there are `MISMATCH` lines, the CSV was still written but is not trustworthy: report the mismatches to the user verbatim and do not present the file as complete. A mismatch usually means BikeReg changed its page markup — say so, and suggest opening an issue on the plugin's repository.
- Re-count the CSV yourself (python `csv` module): row count equals the sum of the per-event entry counts the script printed; the `Event ID` column contains exactly the requested IDs.
- Read the `note:` lines. They list categories with no gender in the name (kids races, open fields) — those rows carry `Unspecified`.

## 5. Deliver

Send the CSV file. In the message, give per event: title, entries, unique riders, categories, gender split; then the combined total and the file name. Keep it short — the file speaks for itself.

Always state these two things, because they are easy to misread:

- **One row per entry, not per rider.** A rider entered in three categories appears three times. Unique-rider counts are in the summary.
- **Gender is derived from the category name**, not from BikeReg profiles (the public list has none). `Women`/`Girls` → F, `Men`/`Boys`/`Men/Open` → M; anything else → Unspecified. A rider who appears in any Women's category is marked F on every row, including a Men/Open entry from a combined start. A woman who *only* entered a Men/Open field will be marked M — flag this caveat so the user can spot-check.

For an upcoming event, note the pull date: the list is a snapshot and grows until registration closes.

## Columns

`Event, Event ID, First Name, Last Name, Race Category, Gender, Team, City, State, Reg Date`

With `--minimal`: `Event, Event ID, First Name, Last Name, Race Category, Gender`.

## How it works (for troubleshooting only)

`bikereg.com/Confirmed/<id>` is a static page listing every category as `<table class="categoryName" racerecid="…">` with its entry count. Each category's riders come from `bikereg.com/Registration/ConfirmedSingleRace.aspx?RaceRecID=<rrid>&EventID=<id>&…`, an HTML fragment. The script does one GET for the page plus one per category, parses with the standard library, and compares every category's row count to the count printed on the page. No login, no JavaScript, no browser.

`scripts/test_bikereg.py` runs offline parser tests against real captured markup. If the user reports a mismatch, run it first: if it passes, BikeReg's live markup has changed and the parsers in the script need updating; if it fails, the script itself was edited.
