# bikereg-tools

Claude plugins for cycling race promoters, teams, and anyone who works with [BikeReg](https://www.bikereg.com) event data, plus a tool for mailing race posters to local bike shops.

## Plugins

### bikereg-registrations

Paste up to 20 BikeReg event IDs into Claude and get back **one CSV** of every public registration, all events appended together:

```
Event, Event ID, First Name, Last Name, Race Category, Gender, Team, City, State, Reg Date
```

Every category's row count is verified against the entry count BikeReg prints on the page, so a partial scrape can't pass silently. No login needed — it reads the same "Who's Registered" list anyone can see, so it works for events you don't promote.

### race-review-deck

Attach registration CSVs (one per year for year-over-year) and your race logo, and get an editable **PowerPoint post-race review**:

- **Colors from your logo.** Brand colors are pulled out of the logo and used for highlights and chart series, lightened as needed to read on the dark photo backgrounds.
- **Preset slides from this repo.** The slide list and background photos are fetched from GitHub on every run, so changing them here changes every future deck.
- **The analysis:** category trends and biggest movers, small fields, gender split, where riders came from (in-state vs. travelling), biggest teams, registration pace and spike days, age, revenue, and how many riders came back. Outliers are called out.
- **A takeaway headline on every slide**, plus an executive summary and recommendations that Claude writes from the numbers.

Works with the CSV from **bikereg-registrations** or with BikeReg's promoter export (which adds age, price, and ZIP, so you get the age and revenue slides too). Slides whose data isn't in your files drop out automatically.

### bike-shop-poster-mailer

Tell Claude a ZIP code and a radius, and get a **USPS Click-N-Ship bulk-label CSV** with one label for every bike shop in that area, ready to mail posters or flyers.

- **Finds the shops.** Claude searches the area and leaves out mobile repair vans, motorcycle dealers and spin studios. It shows you the list, with distances, before anything is written.
- **One question at a time.** It asks for the ZIP, radius, package (tube, flat mailer or box, plus size and weight), and your return address in order.
- **USPS's own template.** The column layout is the Click-N-Ship "Import Labels" template, fetched from this repo on every run. If USPS changes it, replacing one file here updates everyone.

## Install

**Claude (desktop app / Cowork):** Customize → Plugins → **+** → Add marketplace → *Add from a repository* → paste this repo's URL. Then install **bikereg-registrations**, **race-review-deck** and/or **bike-shop-poster-mailer** from the list.

**Claude Code:**

```
/plugin marketplace add drivewayseries/bikereg-tools
/plugin install bikereg-registrations@bikereg-tools
/plugin install race-review-deck@bikereg-tools
/plugin install bike-shop-poster-mailer@bikereg-tools
```

## Use

You don't need IDs ready. Just ask:

> pull BikeReg registrations

Claude asks which events, and you paste them however you have them — one per line, comma-separated, IDs or full URLs, mixed:

```
74062, 73918
https://www.bikereg.com/75001
```

Or say it in one go if you already know them:

> registrations for 74062 and 73918

Claude confirms the list, runs the script, checks the result against BikeReg's own counts, and sends the CSV.

**Finding an event ID:** open the event on bikereg.com — the number in the address bar is the ID (`bikereg.com/74062` → `74062`). The skill has no event search; it works from IDs you supply.

### If your organization blocks bikereg.com from Claude's sandbox

Some Team/Enterprise workspaces restrict outbound network access. Claude will notice, give you the script and a one-line Terminal command, and pick up from the CSV you attach back. The script is standard-library Python 3 — nothing to install.

## Standalone use (no Claude)

The script works on its own:

```
python3 plugins/bikereg-registrations/skills/bikereg-registrations/scripts/bikereg_registrations.py 74062 73918 -o ~/Downloads
```

Options: `--separate` (also one CSV per event), `--minimal` (name/category/gender only), `--delay` (seconds between requests, default 1.0).

### If BikeReg rate-limits you

Each category is one request, and a big stage race has 50+. If BikeReg answers `429 Too Many Requests`, the script waits (honoring `Retry-After`), widens the gap between every later request, and retries up to 5 times. If it still can't get through it stops and tells you to re-run with `--delay 3`. Nothing partial is written.

### If you see a certificate error

`CERTIFICATE_VERIFY_FAILED` means your Python has no CA certificates — common with python.org Python on macOS, which doesn't use the system keychain. Easiest fix is to run macOS's own Python instead: `/usr/bin/python3 <script> …`. Or run the `Install Certificates.command` that came with your Python, or `pip3 install certifi` (the script picks it up automatically). The script prints these options when it hits the error.

## Notes on the data

- **One row per entry.** A rider in three categories appears three times. Unique-rider counts are printed in the summary.
- **Gender is inferred from the category name** — BikeReg's public list has no gender field. `Women`/`Girls` → F, `Men`/`Boys`/`Men/Open` → M, anything else (kids races, open fields) → Unspecified. A rider found in any Women's category is F on all rows, which handles combined starts; a woman who only entered a Men/Open field will show as M.
- Upcoming events are a snapshot; the list grows until registration closes.

## How it works

BikeReg's Who's Registered page (`bikereg.com/Confirmed/<id>`) is a React app backed by a GraphQL endpoint, `bikereg.com/api/supergraph/gql`. The script sends the page's own two queries: `AR_GetWhosRegisteredGroups` returns every category's `raceRecId`, name and entry count, and `AR_GetWhosRegisteredEntries` returns the riders, 10 categories per request. It then reconciles each category's entry count against BikeReg's. Politeness delay between requests defaults to 1 s.

If BikeReg changes its API, the script fails loudly, either on a GraphQL error or on a count mismatch. Run `scripts/test_bikereg.py` (offline, uses captured responses) to tell an API change from a script edit, and open an issue.

## Race review deck

### Use

> make a race review deck from these

…with your CSVs and logo attached. Claude shows you the palette it pulled from the logo, confirms which file is which year, writes the takeaways, and sends the .pptx. Tell it about anything the data can't know, like "we raised prices on May 23" or "the date moved this year", and that context ends up in the headlines.

### Changing the preset slides

Everything lives in [`plugins/race-review-deck/skills/race-review-deck/slides/`](plugins/race-review-deck/skills/race-review-deck/slides/):

- **`deck.json`** holds the slide order, titles, and which chart or table each slide shows, plus which photos rotate behind which slide types.
- **`backgrounds/`** holds the photos: 1920×1080, already darkened, since slide text is white.

Commit to `main`, and the next deck anyone builds uses the new slides. No plugin update is needed. Field reference, the available charts, and a test checklist are in [`references/slide-library.md`](plugins/race-review-deck/skills/race-review-deck/references/slide-library.md).

### Standalone use (no Claude)

```
cd plugins/race-review-deck/skills/race-review-deck/scripts
pip install python-pptx pillow
python3 palette.py logo.png -o palette.json
python3 analyze.py race_2024.csv race_2025.csv -o analysis.json
python3 build_deck.py --analysis analysis.json --palette palette.json --logo logo.png -o review.pptx
```

Without a narrative file, slides use the preset titles, and the summary falls back to auto-generated facts. To try it on fictional data, run `python3 make_sample_data.py sample`.

### Privacy

A promoter export includes rider emails, phones, and addresses. The analysis keeps only counts, team names, and places, so no rider names or contact details reach the deck. `*.csv` and `*.pptx` are git-ignored here, so registration data and decks don't get committed by accident.

## Bike shop poster mailer

### Use

> mail posters to every bike shop within 20 miles of 78704

Claude picks up whatever you've already said (here, the ZIP and radius), searches, and shows the shops it found. You can drop any you don't want. Then it asks one question at a time:

1. Tube, flat mailer, or box?
2. Size in inches
3. Weight of one packed piece
4. Return name, plus a business name if you want one
5. Return address
6. Optional extras: ship date, a note printed on each label, an attention line

You get a CSV named like `bike-shop-labels-78704-20mi.csv`.

### Uploading to USPS

1. In [Click-N-Ship](https://cnsb.usps.com/), choose **Import Batch of Labels** → **I have my own file to upload**, and select the CSV.
2. Name the batch, check the column mapping (it should match, since the headers are USPS's own), and save the mapping for next time.
3. In Label Manager, select all the labels, then use **Edit** under *Service and Package* to pick the service (Ground Advantage for posters) and packaging, all in one step.
4. **Add All Complete to Cart** and pay.

Service and package type are left blank in the CSV on purpose. USPS doesn't publish the exact values its importer accepts, and a wrong value would reject every row, so it's safer to set them in one bulk edit.

### Updating the USPS template

The template is [`plugins/bike-shop-poster-mailer/skills/bike-shop-poster-mailer/assets/Label_Template.csv`](plugins/bike-shop-poster-mailer/skills/bike-shop-poster-mailer/assets/Label_Template.csv). If USPS changes it:

1. Download the new one from Click-N-Ship (Import Labels → File Upload → Download CSV Template).
2. Replace that file, then run `python3 scripts/test_mailer.py`.
3. Commit to `main`. The next run anywhere picks it up.

A fetched template missing a column the builder writes is ignored in favor of the bundled copy, so a bad edit can't break a run. `*.csv` is git-ignored in this repo, with an exception for this one file.

### Standalone use (no Claude)

```
cd plugins/bike-shop-poster-mailer/skills/bike-shop-poster-mailer
python3 scripts/mailer.py geocode 78704
python3 scripts/mailer.py build --shops shops.json --config config.json --out labels.csv
```

`shops.json` is a list of `{name, place_id, lat, lng, address}`, and `config.json` holds the sender and package. Both formats are documented in the skill's `SKILL.md`. No extra Python packages are needed.

## License

MIT
