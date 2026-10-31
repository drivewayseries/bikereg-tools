# The slide library

`slides/deck.json` defines which slides every social review contains, in what order, and which photos go behind them. `build_deck.py` fetches it from GitHub at run time:

```
https://raw.githubusercontent.com/drivewayseries/bikereg-tools/main/plugins/social-review-deck/skills/social-review-deck/slides/deck.json
```

**Photos are shared with race-review-deck.** `"backgrounds_from"` in `deck.json` points at race-review-deck's `slides/` folder, so replacing a photo there changes both decks. `slides/backgrounds/` here is the offline fallback copy. Refresh it when the shared photos change.

`--slides` accepts `auto` (default: GitHub, falling back to bundled), `bundled`, a local folder or `deck.json`, a raw URL, or `owner/repo[@ref][:path]` for a fork. A local or bundled library uses its own `backgrounds/` folder.

## deck.json

The format is the race-review-deck format (see that plugin's `references/slide-library.md`) with these differences:

- Template variables: `{name}`, `{current}`, `{previous}`, `{editions}`, `{focus}`.
- Extra layout **`collage`**: grid of top posts from `analysis.top_posts`. Fields `cols` (default 4) and `count` (default 8; analyze.py's `--top` sets how many exist). Each tile shows the post image from `--images` (cropped to fit) or a text tile, a rank badge, views, account, date and engagement rate, and links to the post. Speaker notes list every post link.
- KPI formats add `pct1` (one decimal, e.g. 7.8%) and `compact` (1.2M, 70.9k).
- Tables may carry `widths` (relative column widths). analyze.py sets them for tables with captions.
- `backgrounds` may have a `collage` pool.

`requires` flags: `multi_edition`, `has_reach`, `has_shares`, `has_follows`, `has_hashtags`, `has_mentions`, `multi_account`, `has_reels`, `has_focus`, or dotted paths like `charts.reel_length`.

### Available charts and tables

Charts: `totals_by_period`, `views_by_period`, `posts_by_month`, `views_by_month`, `type_mix`, `type_avg_views`, `type_er`, `top_posts_views`, `hashtag_avg_views`, `hashtag_usage`, `hashtag_vs_none`, `accounts_views`, `weekday_views`, `weekday_posts`, `time_views`, `reel_length`, `engagement_mix`, `focus_vs_all`.

Tables: `post_types`, `top_posts`, `bottom_posts`, `metric_leaders`, `top_hashtags`, `hashtag_yoy`, `top_mentions`, `accounts`, `focus_share`.

## Changing the slides safely

1. Edit `deck.json` in a branch.
2. Run `python3 scripts/test_social_review.py`. It validates the library and builds a deck from fictional data.
3. Merge to `main`. Every user picks it up on their next run.
