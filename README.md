# NBA Wins Pool 2026-27

Live at **https://nbawins.redplanetanalytics.com**

## How it works

- `fetch_data.py` runs daily in GitHub Actions. It downloads every final
  regular-season game from ESPN's public scoreboard (the NBA's schedule file is
  the fallback, since it usually blocks GitHub), then writes `games.json` and
  `data.json`.
- `index.html` reads `data.json`. No Google Sheet is involved.
- Monthly prizes are computed from game-level results, so a missed run is
  backfilled automatically the next day.
- The NBA Cup championship game is excluded (it does not count in the
  standings). All other NBA Cup games count.

## Files

| File | Purpose |
|---|---|
| `index.html` | The site |
| `fetch_data.py` | Data pull and all calculations |
| `data.json` | Generated each day (starts as a pre-season placeholder) |
| `games.json` | Generated each day: every counted game |
| `CNAME` | Custom domain |
| `.github/workflows/update.yml` | Daily at 7:37 AM EDT / 6:37 AM EST, backup run at 9:07 AM EDT / 8:07 AM EST |

## Setup (one time)

1. Create a public repo named `nba-wins-pool` under `smarz1223`.
2. Drag and drop `index.html`, `fetch_data.py`, `data.json`, `games.json`,
   `CNAME` and `README.md` into the repo root. Commit.
3. Workflow file (GitHub hides the `.github` folder on drag and drop):
   - Add file > Create new file. In the name box type
     `.github/workflows/placeholder.txt`, type any character in the body, commit.
   - Open the new `.github/workflows` folder, Add file > Upload files, drop
     `update.yml`, commit. Then delete `placeholder.txt`.
4. Settings > Pages: Source = Deploy from a branch, Branch = `main` / root.
   Custom domain = `nbawins.redplanetanalytics.com`.
5. Cloudflare DNS: add CNAME `nbawins` pointing to `smarz1223.github.io`,
   proxy status DNS only (grey cloud).
6. Actions tab > "Update NBA Wins data" > Run workflow. Check the log for
   "Wrote data.json" and the games-per-team line.
7. Once HTTPS is available in Settings > Pages, tick Enforce HTTPS.

## Season rollover checklist

In `fetch_data.py`: `SEASON_LABEL`, `SEASON_START`, `SEASON_END`,
`CUP_FINAL_DATE`, `MONTHS`, `DRAFT`, `DRAFT_SLOTS`. Update the owner colors
(`OC`) in `index.html` if owners change. Reset `games.json` to
`{"games": []}`.

## If something looks wrong

- Red X on the Actions run: both data sources failed. The site keeps the last
  good data. Re-run from the Actions tab later.
- A game counted that should not be (or the reverse): add its NBA game ID to
  `EXCLUDE_GAME_IDS` in `fetch_data.py`. The Actions log prints every game on
  the NBA Cup final date for checking.
