---
name: bike-shop-poster-mailer
description: Finds bike shops within a radius of a ZIP code, gets their street addresses, and writes a USPS Click-N-Ship "Import Labels" CSV (the exact 59-column USPS Label_Template layout) so posters, flyers or other mailers can be bulk-shipped to every shop. Walks the user through the ZIP, radius, package size and weight, and sender name and return address one question at a time. Use this whenever someone wants to mail or ship posters, flyers, race promos or samples to bike shops, build a bike shop mailing list near a ZIP or city, make a USPS bulk upload or Click-N-Ship file for shops, or "send something to every bike shop within X miles", even if they don't say Click-N-Ship or CSV.
---

# Bike Shop Poster Mailer

Produce a CSV that uploads to **USPS Click-N-Ship → Import Labels → File Upload** and creates one label per bike shop in the search area.

`scripts/mailer.py` does the deterministic work:
- geocoding the ZIP
- planning the search grid
- searching OpenStreetMap when Google Places isn't available
- splitting addresses into fields
- the radius filter and deduplication
- writing the CSV

The column layout is USPS's own label template. It's fetched from this plugin's GitHub repo on every run, with the bundled `assets/Label_Template.csv` as the fallback. Claude's job is to walk the user through the questions, run the searches, and judge which results are real bike shops.

## How to ask

**Ask one question per message, in the order below, and wait for the answer before moving on.** Shipping labels involve a lot of small details. One short question at a time is easier to answer on a phone, and it keeps a typo in one answer from getting buried in a long reply.

- Keep each question to a sentence or two, with an example of the expected format.
- **Skip any question the user has already answered.** That includes the first message, such as "posters to shops within 20 miles of 78704" (ZIP and radius both answered), and anything said earlier in the conversation.
- If the user answers several questions at once, accept them all and go on to the next unanswered one.
- If an answer is unclear (a 4-digit ZIP, a weight with no unit), ask about that one answer again before going on.
- For questions with a few fixed choices, use `ask_user_input_v0` buttons where noted. Everything else is free text.

## The questions

### Part A: where to send

**Q1. ZIP code.** "What ZIP code should I search around?"

**Q2. Radius.** "How many miles out from that ZIP?" Offer buttons for 5, 10, 25 and 50 miles. The user can also type a different number.

Then **run the search** (see "Searching" below) and show what was found, before asking about the package:

- a compact table of shop name, city and miles, nearest first
- any borderline results (a big-box store, a shop that may be a rental counter)
- anything found just past the radius

Ask: "Any shops to remove, or any I missed?" Add or remove shops based on the answer, then go on. Showing the list here lets the user judge whether the search worked before typing out the package details.

### Part B: what you're sending

**Q3. Package style.** "What are you mailing them in?" Offer these buttons:
- **Tube**
- **Flat mailer**
- **Box**

Tubes matter because USPS treats them as non-rectangular, so the script adds girth.

**Q4. Size.** Ask according to the answer to Q3:
- Tube: "What's the tube's diameter and length in inches? For example, 3 × 26."
- Flat mailer or box: "What are the length, width and thickness in inches? For example, 19 × 13 × 0.5."

**Q5. Weight.** "How much does one packed piece weigh? For example, 9 oz or 1 lb 2 oz." If the user isn't sure, suggest weighing one finished piece on a kitchen scale. Don't guess a weight, because it sets the postage.

### Part C: who it's from

**Q6. Sender name.** "What name should go on the return address? Add a business name if you want one on the label."

**Q7. Return address.** "And the return address: street, unit if any, city, state, ZIP?" Email and phone are optional, so don't ask for them separately.

### Part D: optional extras

**Q8. Extras.** "Want to add any of these?" Use multi-select buttons:
- **Ship date** (Click-N-Ship allows up to 7 days ahead, and labels mailed after their date can be returned)
- **Label note** (30 characters, printed on each label, such as "Spring Crit posters")
- **Attention line** (such as "Shop Manager")
- **None**

For each option picked, ask a short follow-up, one at a time. Enter the ship date as MM/DD/YYYY.

Then **build** the CSV and deliver it.

## Searching

```bash
cd <skill-dir>
python3 scripts/mailer.py geocode 78704
python3 scripts/mailer.py grid --lat 30.2428 --lng -97.7658 --radius 15
```

`grid` returns search centers, each with a `bias_m`. Each Places query returns at most 10 results, so larger radii get up to about 13 overlapping centers to avoid under-counting a metro area. Above about 75 miles, warn that dense areas will be incomplete, and offer to split the job into several smaller runs.

For **each** center, make one `places_search` call with `location_bias_lat`, `location_bias_lng` and `location_bias_radius` set from that center. Include these queries:
- "bike shop"
- "bicycle store"
- "bicycle repair shop"
- "e-bike shop"

Results come back as a merged list or as per-query summaries. In either form, take each place's **name, place_id, latitude, longitude, and full street address**. In the summary form the address sits in the parenthetical after the rating, for example `4510 Terry-O Ln Unit 126, Austin, TX 78745`. Copy the address exactly, because the script splits it into fields.

### Without `places_search`: OpenStreetMap first, then web search

If `places_search` isn't available, skip `grid` and search OpenStreetMap in one call. Pass the state from `geocode`:

```bash
python3 scripts/mailer.py osm --lat 30.2428 --lng -97.7658 --radius 15 --state TX --out shops.json
```

This writes `shops.json` with each shop's exact coordinates, so the radius filter stays exact. The report on stdout gives `found`, `with_address`, and a `needs_address` list. Then use `web_search` for two jobs:

1. **Finish incomplete addresses.** Each `needs_address` entry has the parts OpenStreetMap knows in `partial_address`, plus a `website` when there is one. Find the full street address, preferably on the shop's own site, and fill in that shop's `address` in `shops.json`. Keep its `lat` and `lng`.
2. **Fill gaps.** OpenStreetMap misses some shops, especially new ones. Run a few searches such as "bike shops near <city>" for the main towns in the radius. Add any shop that isn't already in `shops.json` with `"source": "web"`, and use `geocode` on its ZIP for approximate coordinates. You don't need to check for duplicates yourself: `build` drops repeats by address and treats "Road" and "Rd" as the same.

If `osm` fails (it exits with "fall back to web search", for example when the network blocks the server), build the whole list from `web_search` the same way, with `geocode` coordinates for every shop.

In the review table, mark shops that came from web search. Tell the user how many came from each source, and that distances for web-search shops are approximate (ZIP-level), so shops near the edge of the radius may be off.

**Decide what counts as a bike shop.** The poster goes to a storefront that sells or services bicycles. Keep:
- independent shops
- brand stores (Trek, Specialized, Giant)
- e-bike shops
- repair-only shops
- co-ops with a storefront

Leave out:
- mobile repair services with no address (such as velofix)
- motorcycle or motocross dealers
- spin and cycling studios
- bike-share docks and rental-only kiosks
- clubs and advocacy groups
- big-box retailers (Walmart, Target, Dick's), unless the user wants them

When in doubt, keep the shop and point it out at the review step.

Save to `shops.json`. Include everything that passed the bike-shop judgment, even shops that might fall outside the radius, because the script filters by distance and removes duplicates:

```json
[{"name": "Mellow Johnny's", "place_id": "ChIJ...", "lat": 30.2676, "lng": -97.7550,
  "address": "115 Sandra Muraida Way Ste 102, Austin, TX 78703"}]
```

To show the review table after Q2, run `build` with placeholder sender and package values, then read the `kept` and `dropped` lists from the report. Rebuilding later with the real answers costs nothing.

## Building

Write `config.json` from the answers:

```json
{
  "origin": {"lat": 30.2428, "lng": -97.7658},
  "radius_mi": 15,
  "sender": {"first_name": "Jane", "last_name": "Rider", "company": "Example Racing LLC",
             "line1": "123 Example St", "line2": "", "city": "Austin", "state": "TX",
             "zip": "78704", "email": "", "phone": ""},
  "package": {"style": "tube", "diameter": 3, "length": 26, "weight": "9 oz"},
  "ship_date": "", "reference": "", "attn_first": "", "attn_last": "",
  "service_type": "", "package_type": "",
  "exclude_names": []
}
```

For a flat mailer or box, use `"style": "flat"` or `"box"` with `length`, `width` and `height`. Put shops the user removed at the review step in `exclude_names`.

Then run:

```bash
python3 scripts/mailer.py build --shops shops.json --config config.json \
  --out /mnt/user-data/outputs/bike-shop-labels-<zip>-<radius>mi.csv
```

The script writes the template's columns in order, with one row per shop sorted by distance:

- **Recipient**: the shop name goes in *Recipient Company/Org Name*. First and last name stay blank unless an attention line was given. Suite, unit and # designators go to *Address Line 2*.
- **Package**: weight is split into lb and oz and rounded **up** to a whole ounce, so postage is never under-declared. Length is the longest side. A tube gets width = height = diameter and girth = π × diameter.
- **Service Type and Package Type stay blank.** USPS doesn't publish the exact text its importer accepts, and a wrong value fails every row. The user sets the service once, in bulk, after importing. Fill these only if the user supplies Click-N-Ship's exact wording.
- **Country**: "United States". If the import rejects it, set `"country_value": "US"` and rebuild.
- **Name cleanup**: Click-N-Ship person-name fields accept only letters and a short list of symbols (no digits or hyphens), so sender and attention names are cleaned. Shop names stay as they are. Names containing digits or symbols are listed in the report, so the user knows which rows to check if the import flags them.

The report also says which template was used. "GitHub" and "bundled" are both fine. If the fallback note appears, there's no need to say anything unless the user is expecting a recent template change.

## Delivering

1. Call `present_files` with the CSV.
2. Give a one-line recap of the rows, the package, and the sender city, so the user can spot a wrong answer before uploading.
3. Give the upload steps:
   1. Go to Click-N-Ship → **Import Batch of Labels** → **I have my own file to upload**, and select the CSV.
   2. Name the batch. On **Map Column Headers**, check the mapping (the headers are USPS's own, so it should match), and save it for next time.
   3. In Label Manager, select all labels in the batch. Use **Edit** under *Service and Package* to choose the service (Ground Advantage is the usual choice for posters) and "other type of box or envelope". Add the ship date there if it was skipped. Mark tubes as non-rectangular if the girth didn't carry over.
   4. Review, then **Add All Complete to Cart** and pay.
4. Click-N-Ship takes 1,000 labels per file, and the script warns if that's exceeded. It also checks every address at import, and any rows it flags can be fixed in Label Manager.

Keep the sender's address only in the config file and CSV for this job. Don't repeat it in unrelated output.

## Maintaining

- If USPS changes the template, replace `assets/Label_Template.csv` on `main`. Every user picks it up on their next run.
- The builder refuses a fetched template that's missing a column it writes, and falls back to the bundled copy.
- Run `python3 scripts/test_mailer.py` after any change to the script.
