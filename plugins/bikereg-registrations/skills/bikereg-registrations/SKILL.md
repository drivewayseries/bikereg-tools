---
name: bikereg-registrations
description: Pulls the public "Who's Registered" list from BikeReg events into one verified CSV (name, race category, gender, team, city, state, reg date). Use whenever the user wants BikeReg registrations, entrants, riders, a start list, field sizes, or who's registered — whether or not they have event IDs ready; the skill asks for them. Takes IDs or URLs, up to 20 events per run, appended into a single file.
---

# BikeReg registrations → CSV

Turn BikeReg event IDs into one CSV of every registration, verified against BikeReg's own entry counts. The work is done by `scripts/bikereg_registrations.py` (standard library only, no install). Your job is to get the event list from the user, run the script, handle the environments where it can't run, and check the result before handing it over.

## 1. Ask which events

**If the user has not given any event IDs, ask before doing anything else.** Most people reach this skill knowing they want registrations but without having pasted IDs yet. Ask in plain conversation — not with a multiple-choice question, since the answer is a free-form list:

> Which events? Paste BikeReg event IDs or URLs — one per line, comma-separated, however you have them. Up to 20 at a time.

Then wait. Do not run anything, guess an ID, or offer a sample event.

### Reading what they paste

Accept whatever shape it arrives in and never make them reformat: bare IDs (`74062`), event URLs (`https://www.bikereg.com/74062`), confirmed-list URLs (`.../Confirmed/74062`), a comma-separated line, one per line, a bulleted list, or a mix. Pass the whole thing through to the script, which splits on commas, newlines, semicolons and spaces, pulls the ID out of each token, and collapses duplicates.

### Confirm before a long run

Echo the parsed list back and say how long it will take, then run. A 50-category event is about a minute, so:

> That's 6 events — 74062, 73918, 75001, 75002, 75010, 75011. Should take around 5 minutes. Starting now.

For one or two events just run; the confirmation matters when the wait is long enough that a wrong ID wastes real time.

### Edge cases

- **More than 20 unique events**: do not run. Say the limit is 20 per run, and offer to do it in batches — first 20 now, the rest after, then one merged CSV if they want it.
- **An event name instead of an ID** ("the Oatmeal Classic"): do not guess, and do not search — this skill has no event lookup. Ask for the ID or URL, and tell them where it is: open the event on bikereg.com and the number in the address bar is the ID (`bikereg.com/74062` → `74062`).
- **Something that isn't a BikeReg ID** (a RunReg/SkiReg URL, a bare word, a 3-digit number): say which token you couldn't read and ask for that one again. Don't drop it silently.
- **Nothing pasted / they change their mind**: just stop. Don't re-prompt repeatedly.

## 2. Run the script

The script is in the `scripts/` folder next to this SKILL.md — use the base directory reported when this skill loaded.

```bash
python3 "<skill base directory>/scripts/bikereg_registrations.py" 74062 73918 -o "<output dir>"
```

- Output dir: `/mnt/user-data/outputs` when it exists, otherwise the working directory.
- Add `--minimal` only if the user asks for just names/category/gender.
- Add `--separate` only if the user asks for one file per event as well.
- Each category is one request and the default gap is 1 s, so a 50-category event takes about a minute; allow real time for 20 events. Never lower `--delay` — raise it to 3 if the script reports rate limiting.

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

### If BikeReg rate-limits the run

A `429` exit means BikeReg throttled the requests and the built-in waits weren't enough. Re-run the same command with `--delay 3`. If that also fails, wait a few minutes, then split the events into smaller batches. Do not present partial results — the script writes nothing on this failure.

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
