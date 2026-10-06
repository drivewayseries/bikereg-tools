# The slide library

`slides/deck.json` + `slides/backgrounds/` define which slides every race review contains, in what order, and on which photos. `build_deck.py` fetches them from GitHub at run time:

```
https://raw.githubusercontent.com/drivewayseries/bikereg-tools/main/plugins/race-review-deck/skills/race-review-deck/slides/deck.json
                                                                                                         …/slides/backgrounds/<name>.jpg
```

So editing these files on `main` changes every future deck without a plugin release. If the fetch fails, or the fetched `deck.json` uses a layout or schema this builder doesn't know, the bundled copy is used.

## Pointing at a different library

`--slides` accepts:

| value | meaning |
|---|---|
| `auto` (default) | GitHub main, falling back to bundled |
| `bundled` | only the copy shipped in the plugin |
| `path/to/folder` or `path/to/deck.json` | local library (backgrounds relative to it) |
| `https://…/deck.json` | any raw URL; backgrounds fetched from `…/backgrounds/` |
| `owner/repo[@ref][:path]` | a fork, e.g. `myclub/race-decks@main:slides` |

## deck.json

```json
{
  "schema": 1,
  "theme": {"heading_font": "Arial", "body_font": "Arial", "mode": "dark",
            "background_color": "#131419", "content_panel_opacity": 0.82},
  "footer": "{race_name} · {current} race review",
  "backgrounds": {"title": ["D16.jpg"], "section": ["D11.jpg", "…"], "content": ["…"], "closing": ["…"]},
  "slides": [ … ]
}
```

- `backgrounds` — pools per layout; each new slide of that layout takes the next photo in rotation. A slide can pin one with `"background": "D12.jpg"`. Photos should be 1920×1080 JPGs, already darkened (text is white). Keep each under ~150 KB — the builder downloads them every run.
- `background_color` — solid fill behind the photo, and the color charts are contrast-checked against. If you switch to light photos, change this to a light color and the builder will darken brand colors instead of lightening them.
- Template variables in titles/labels/footer: `{race_name}`, `{current}`, `{previous}`, `{editions}`.

### Slide entries

Every slide has a unique `id` (the narrative refers to it), a `layout`, and a fallback `title`.

| layout | fields |
|---|---|
| `title` | `title`, `subtitle` — logo, race name, subtitle, date line |
| `section` | `title`, optional `subtitle` — numbered divider |
| `chart` | `chart`: key in `analysis.charts`; optional `max_items` |
| `table` | `table`: key in `analysis.tables` (must have `columns`/`rows`); `max_rows` (≤ 11 fit) |
| `kpis` | `metrics`: `[{key, label, format}]` (format `int`/`pct`/`money`/`decimal`); optional `source` (default: current edition's `kpis`; e.g. `tables.retention`). Up to 6 tiles; metrics with no value are dropped |
| `bullets` | `items`: list of sources tried in order — `narrative.summary`, `narrative.outliers`, `narrative.recommendations`, `facts`, `outliers`, `data_notes`; `max_items`; `small` |
| `closing` | `title`, `subtitle` |

`requires` — a list; the slide is skipped unless every entry is truthy / non-empty. Entries are analysis flags (`multi_edition`, `has_names`, `has_team`, `has_location`, `has_city`, `has_reg_date`, `has_age`, `has_price`, `has_retention`, `price_yoy`, `age_yoy`) or dotted paths (`charts.category_movers`, `tables.small_fields.rows`, `narrative.recommendations`).

### Available charts and tables

Charts (`analysis.charts`): `entries_by_edition`, `category_entries`, `category_movers`, `family_by_edition`, `gender_by_edition`, `women_share_trend`, `gender_by_family`, `top_states`, `in_state_by_edition`, `top_teams`, `reg_curve`, `daily_regs`, `reg_weekday`, `age_distribution`, `revenue_by_edition`, `revenue_by_category`, `retention_split`, `retention_trend`, `retention_by_family`.

Tables (`analysis.tables`): `small_fields`, `category_yoy`, `family_yoy`, `category_families`, `women_fields`, `top_cities`, `state_changes`, `team_changes`, `reg_spikes`.

Not every key exists for every dataset (YoY ones need two editions, etc.) — use `requires` so the slide drops out cleanly.

## Changing the slides safely

1. Edit `deck.json` (and add photos) in a branch.
2. Run `python3 scripts/test_race_review.py` — it validates the library, checks every chart/table key exists in a full sample analysis, and that every listed background is present.
3. Build a sample deck: `python3 scripts/make_sample_data.py /tmp/s && python3 scripts/analyze.py /tmp/s/*.csv -o /tmp/a.json && python3 scripts/build_deck.py --analysis /tmp/a.json --logo /tmp/s/logo.png --slides bundled -o /tmp/test.pptx` and look at it.
4. Merge to `main`. Every user picks it up on their next run.

New layouts need a builder change (and bumping `schema` in both `deck.json` and `BUILDER_SCHEMA` if old builders must not try to render the new file — they'll fall back to their bundled copy).
