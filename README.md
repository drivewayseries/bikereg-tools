# bikereg-tools

Claude plugins for cycling race promoters, teams, and anyone who works with [BikeReg](https://www.bikereg.com) event data.

## Plugins

### bikereg-registrations

Paste up to 20 BikeReg event IDs into Claude and get back **one CSV** of every public registration, all events appended together:

```
Event, Event ID, First Name, Last Name, Race Category, Gender, Team, City, State, Reg Date
```

Every category's row count is verified against the entry count BikeReg prints on the page, so a partial scrape can't pass silently. No login needed — it reads the same "Who's Registered" list anyone can see, so it works for events you don't promote.

## Install

**Claude (desktop app / Cowork):** Customize → Plugins → **+** → Add marketplace → *Add from a repository* → paste this repo's URL. Then install **bikereg-registrations** from the list.

**Claude Code:**

```
/plugin marketplace add drivewayseries/bikereg-tools
/plugin install bikereg-registrations@bikereg-tools
```

## Use

Just tell Claude what you want, with the IDs or URLs:

> registrations for 74062 and 73918

> pull the entry lists for https://www.bikereg.com/75001 and https://www.bikereg.com/75002 as one CSV

Claude runs the script, checks the result, and sends the CSV.

### If your organization blocks bikereg.com from Claude's sandbox

Some Team/Enterprise workspaces restrict outbound network access. Claude will notice, give you the script and a one-line Terminal command, and pick up from the CSV you attach back. The script is standard-library Python 3 — nothing to install.

## Standalone use (no Claude)

The script works on its own:

```
python3 plugins/bikereg-registrations/skills/bikereg-registrations/scripts/bikereg_registrations.py 74062 73918 -o ~/Downloads
```

Options: `--separate` (also one CSV per event), `--minimal` (name/category/gender only), `--delay` (seconds between requests, default 0.3).

### If you see a certificate error

`CERTIFICATE_VERIFY_FAILED` means your Python has no CA certificates — common with python.org Python on macOS, which doesn't use the system keychain. Easiest fix is to run macOS's own Python instead: `/usr/bin/python3 <script> …`. Or run the `Install Certificates.command` that came with your Python, or `pip3 install certifi` (the script picks it up automatically). The script prints these options when it hits the error.

## Notes on the data

- **One row per entry.** A rider in three categories appears three times. Unique-rider counts are printed in the summary.
- **Gender is inferred from the category name** — BikeReg's public list has no gender field. `Women`/`Girls` → F, `Men`/`Boys`/`Men/Open` → M, anything else (kids races, open fields) → Unspecified. A rider found in any Women's category is F on all rows, which handles combined starts; a woman who only entered a Men/Open field will show as M.
- Upcoming events are a snapshot; the list grows until registration closes.

## How it works

`bikereg.com/Confirmed/<id>` lists every category with a `racerecid` and its entry count. Each category's riders come from `ConfirmedSingleRace.aspx?RaceRecID=…&EventID=…` as an HTML fragment. The script fetches the page plus one fragment per category, parses with `html.parser`, and reconciles counts. Politeness delay between requests defaults to 0.3 s.

If BikeReg changes its markup, the verification will fail loudly. Run `scripts/test_bikereg.py` (offline, uses captured markup) to tell a markup change from a script edit, and open an issue.

## License

MIT
