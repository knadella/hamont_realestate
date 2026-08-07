# Hamilton Real Estate — Market Dynamics

Monthly-refreshed market-trends dashboard for **Hamilton, ON** (all communities),
built from HouseSigma's public market-trends feed.

**Live dashboard:** https://claude.ai/code/artifact/642d3a46-95b9-47b4-9825-a36b808bc098

## What it tracks

For **all property types** and broken out by **detached / semi-detached / condo apartment**:

- New listings, active listings, homes sold
- Days on market & property days on market
- Median sold price
- **Months of inventory** (active ÷ sold) — the seller/balanced/buyer balance gauge
- **SNLR** (sales-to-new-listings ratio) — the tightest demand-vs-supply gauge

…with year-over-year changes, an annual table, a current-year month-by-month
view, and trend charts.

## Files

| Path | What |
|------|------|
| `scripts/build_hamilton_dashboard.py` | Self-contained builder (Python stdlib only). Mints a HouseSigma token, fetches the 15-year monthly series for each property type, rewrites the CSV, and regenerates the HTML. |
| `scripts/dashboard_template.html` | The dashboard template (labels & narrative are data-driven, so it never goes stale). |
| `hamilton_market_trends.csv` | Full monthly series, all property types (partial current month excluded). |
| `hamilton_dynamics.html` | The rendered dashboard. |

## Rebuild locally

```bash
python3 scripts/build_hamilton_dashboard.py
```

This overwrites `hamilton_market_trends.csv` and `hamilton_dynamics.html` with the
latest data. Hamilton is municipality `10134` in the HouseSigma API; change `MUNI`
in the script to target a different city.

## Automation

A scheduled Claude Code cloud agent runs this on the 6th of each month, commits the
refreshed files here, and republishes the artifact link above.
