#!/usr/bin/env python3
"""
NBA Wins Pool 2026-27 - data fetcher.

Runs daily in GitHub Actions (.github/workflows/update.yml). No API keys,
no Google Sheet. Writes:
  games.json  - every counted regular-season final (the source of truth cache)
  data.json   - everything index.html displays

HOW RESULTS ARE SOURCED
  1. Primary: the NBA's public season schedule file (cdn.nba.com). One request
     returns every game of the season with final scores.
  2. Fallback: ESPN's public scoreboard, one request per day of the season.
  3. If both fail, the script exits with an error and changes nothing, so the
     site keeps showing the last good data and the Actions run shows a red X.

WHICH GAMES COUNT
  Regular-season finals between SEASON_START and SEASON_END. Preseason,
  play-in and playoff games are excluded. The NBA Cup championship game is
  excluded because it does not count in the official standings. Every other
  NBA Cup game (group stage, quarterfinals, semifinals) counts.

MONTHLY PRIZES
  Built from game-level results, not standings snapshots: each game counts in
  the month of its scheduled date (US Eastern). Re-running is always safe; a
  missed day is backfilled automatically on the next run.

SEASON ROLLOVER: update SEASON_*, CUP_FINAL_DATE, MONTHS and DRAFT below.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SEASON_LABEL = "2026-27"
SEASON_START = "2026-10-20"
SEASON_END = "2027-04-11"
CUP_FINAL_DATE = "2026-12-11"   # NBA Cup championship: does not count
CHAMP_PRIZE = 250

# Manual overrides, only if the feed ever mislabels a game (use NBA game IDs).
EXCLUDE_GAME_IDS = []

MONTHS = [
    {"key": "m1", "label": "Month 1", "short": "Oct-Nov", "start": "2026-10-20", "end": "2026-11-30", "prize": 50},
    {"key": "m2", "label": "Month 2", "short": "Dec",     "start": "2026-12-01", "end": "2026-12-31", "prize": 50},
    {"key": "m3", "label": "Month 3", "short": "Jan",     "start": "2027-01-01", "end": "2027-01-31", "prize": 50},
    {"key": "m4", "label": "Month 4", "short": "Feb",     "start": "2027-02-01", "end": "2027-02-28", "prize": 50},
    {"key": "m5", "label": "Month 5", "short": "Mar-Apr", "start": "2027-03-01", "end": "2027-04-11", "prize": 50},
]

TEAMS = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers", "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves", "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

# ESPN uses a few different abbreviations
ESPN_TO_NBA = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}

# pick, owner, team, 2025-26 wins, 2026-27 Vegas win total (FanDuel). Source: Draft Board tab.
DRAFT = [
    (1, "JOLLZ", "OKC", 64, 60.5), (2, "BAGS", "SAS", 62, 60.5), (3, "KEV", "NYK", 53, 51.5),
    (4, "KARDIAN", "PHI", 45, 50.5), (5, "ADAM B", "DET", 60, 49.5), (6, "ANT", "BOS", 56, 49.5),
    (7, "MARZ", "DEN", 54, 48.5), (8, "DOM", "MIN", 49, 48.5), (9, "FUR", "HOU", 52, 46.5),
    (10, "PHIL", "CLE", 52, 47.5), (11, "DOM", "ATL", 46, 44.5), (12, "BAGS", "MIA", 43, 45.5),
    (13, "FUR", "TOR", 46, 45.5), (14, "KEV", "LAL", 53, 45.5), (15, "ADAM B", "IND", 19, 43.5),
    (16, "KARDIAN", "ORL", 45, 44.5), (17, "PHIL", "POR", 42, 43.5), (18, "ANT", "PHX", 45, 39.5),
    (19, "MARZ", "CHA", 44, 37.5), (20, "JOLLZ", "GSW", 37, 39.5), (21, "PHIL", "DAL", 26, 35.5),
    (22, "MARZ", "UTA", 22, 36.5), (23, "ANT", "WAS", 17, 35.5), (24, "FUR", "MEM", 25, 28.5),
    (25, "ADAM B", "CHI", 31, 29.5), (26, "DOM", "NOP", 26, 28.5), (27, "KARDIAN", "LAC", 42, 28.5),
    (28, "JOLLZ", "MIL", 32, 24.5), (29, "KEV", "BKN", 20, 24.5), (30, "BAGS", "SAC", 22, 21.5),
]
# Balanced draft order from the Rules tab: slot -> round 1/2/3 pick numbers
DRAFT_SLOTS = [(1, 1, 20, 28), (2, 2, 12, 30), (3, 3, 14, 29), (4, 4, 16, 27), (5, 5, 15, 25),
               (6, 6, 18, 23), (7, 7, 19, 22), (8, 8, 11, 26), (9, 9, 13, 24), (10, 10, 17, 21)]

NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}&limit=100"
GAMES_FILE = "games.json"
DATA_FILE = "data.json"


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def eastern_now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.utcnow() - dt.timedelta(hours=5)


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def in_season(d):
    return SEASON_START <= d <= SEASON_END


def month_of(d):
    for m in MONTHS:
        if m["start"] <= d <= m["end"]:
            return m["key"]
    return None


# ─────────────────────────────────────────────
# SOURCE 1: NBA schedule file
# ─────────────────────────────────────────────
def fetch_from_nba():
    raw = fetch_json(NBA_SCHEDULE_URL)
    games, cup_final_day = [], []
    for day in raw["leagueSchedule"]["gameDates"]:
        for g in day.get("games", []):
            gid = str(g.get("gameId", ""))
            date = (g.get("gameDateEst") or "")[:10]
            if not date:
                m, d_, y = day["gameDate"].split(" ")[0].split("/")
                date = f"{y}-{int(m):02d}-{int(d_):02d}"
            if not in_season(date):
                continue
            # 002 = regular season, 006 = NBA Cup knockout games. Skip preseason/play-in/playoffs.
            if gid[:3] not in ("002", "006"):
                continue
            labels = " ".join(str(g.get(k, "")) for k in ("gameLabel", "gameSubLabel", "gameSubtype")).lower()
            if date == CUP_FINAL_DATE:
                cup_final_day.append(f"{gid} {g['awayTeam'].get('teamTricode')}@{g['homeTeam'].get('teamTricode')} [{labels.strip()}]")
            is_cup_final = "championship" in labels or (date == CUP_FINAL_DATE and gid.startswith("006"))
            if is_cup_final or gid in EXCLUDE_GAME_IDS:
                continue
            if g.get("gameStatus") != 3:      # 3 = final
                continue
            h, a = g["homeTeam"], g["awayTeam"]
            if h.get("teamTricode") not in TEAMS or a.get("teamTricode") not in TEAMS:
                continue
            games.append({"id": gid, "date": date, "home": h["teamTricode"], "away": a["teamTricode"],
                          "hs": int(h["score"]), "as": int(a["score"])})
    if cup_final_day:
        print("  Games on NBA Cup final date (only the final should be excluded):")
        for line in cup_final_day:
            print("   ", line)
    return games


# ─────────────────────────────────────────────
# SOURCE 2: ESPN scoreboard (fallback)
# ─────────────────────────────────────────────
def fetch_from_espn(today):
    games = []
    d = dt.date.fromisoformat(SEASON_START)
    end = min(today, dt.date.fromisoformat(SEASON_END))
    while d <= end:
        raw = fetch_json(ESPN_SCOREBOARD_URL.format(d.strftime("%Y%m%d")))
        for ev in raw.get("events", []):
            if ev.get("season", {}).get("type") != 2:          # 2 = regular season
                continue
            comp = ev["competitions"][0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            notes = " ".join(n.get("headline", "") for n in comp.get("notes", [])).lower()
            if "championship" in notes or (d.isoformat() == CUP_FINAL_DATE and "cup" in notes):
                continue
            side = {}
            for c in comp["competitors"]:
                ab = c["team"]["abbreviation"]
                side[c["homeAway"]] = (ESPN_TO_NBA.get(ab, ab), int(float(c.get("score", 0))))
            if "home" not in side or side["home"][0] not in TEAMS or side["away"][0] not in TEAMS:
                continue
            games.append({"id": "espn-" + str(ev["id"]), "date": d.isoformat(),
                          "home": side["home"][0], "away": side["away"][0],
                          "hs": side["home"][1], "as": side["away"][1]})
        d += dt.timedelta(days=1)
    return games


# ─────────────────────────────────────────────
# COMPUTE
# ─────────────────────────────────────────────
def compute(games, today, updated):
    """games: [{date, home, away, hs, as}] counted finals only. Returns the data.json payload."""
    games = sorted(games, key=lambda g: (g["date"], g.get("id", "")))
    blank = lambda: {"w": 0, "l": 0, "pf": 0, "pa": 0}
    team = {t: {"tot": blank(), "mo": {m["key"]: blank() for m in MONTHS}, "log": []} for t in TEAMS}
    for g in games:
        mk = month_of(g["date"])
        for me, op, ms, os_ in ((g["home"], g["away"], g["hs"], g["as"]), (g["away"], g["home"], g["as"], g["hs"])):
            win = ms > os_
            buckets = [team[me]["tot"]] + ([team[me]["mo"][mk]] if mk else [])
            for b in buckets:
                b["w" if win else "l"] += 1
                b["pf"] += ms
                b["pa"] += os_
            team[me]["log"].append({"d": g["date"], "o": op, "r": "W" if win else "L",
                                    "s": f"{ms}-{os_}", "h": me == g["home"]})

    def finish(b):
        gp = b["w"] + b["l"]
        return {"w": b["w"], "l": b["l"], "gp": gp, "pd": b["pf"] - b["pa"],
                "pct": round(b["w"] / gp, 4) if gp else None}

    def streak(log):
        if not log:
            return ""
        r, n = log[-1]["r"], 0
        for x in reversed(log):
            if x["r"] != r:
                break
            n += 1
        return f"{r}{n}"

    # Team rows
    teams = []
    for pick, owner, ab, w25, vegas in DRAFT:
        t = team[ab]
        tot = finish(t["tot"])
        last10 = t["log"][-10:]
        pace = round(tot["pct"] * 82, 1) if tot["pct"] is not None else None
        teams.append({
            "pick": pick, "owner": owner, "abbr": ab, "name": TEAMS[ab],
            "w2025": w25, "vegas": vegas, "exp_pct": round(vegas / 82, 4), **tot,
            "pace": pace, "vs_vegas": round(pace - vegas, 1) if pace is not None else None,
            "streak": streak(t["log"]),
            "last10": f"{sum(x['r'] == 'W' for x in last10)}-{sum(x['r'] == 'L' for x in last10)}",
            "recent": t["log"][-5:],
            "monthly": {k: finish(v) for k, v in t["mo"].items()},
        })

    # Best and worst picks (MLB method): actual win % vs the Nth-best win % in the league at pick N
    ranked = sorted([t["pct"] for t in teams if t["pct"] is not None], reverse=True)
    draft_value = []
    for t in teams:
        opt = ranked[t["pick"] - 1] if t["pick"] <= len(ranked) else None
        val = round(t["pct"] - opt, 4) if (t["pct"] is not None and opt is not None) else None
        draft_value.append({"pick": t["pick"], "owner": t["owner"], "abbr": t["abbr"], "name": t["name"],
                            "actual_pct": t["pct"], "optimal_pct": opt, "value": val})

    owners_order = list(dict.fromkeys(d[1] for d in DRAFT))

    def owner_row(o, key=None):
        b = blank()
        for tr in [d for d in DRAFT if d[1] == o]:
            src = team[tr[2]]["tot"] if key is None else team[tr[2]]["mo"][key]
            for f in b:
                b[f] += src[f]
        r = finish(b)
        r["owner"] = o
        r["teams"] = [d[2] for d in DRAFT if d[1] == o]
        return r

    def rank(rows):
        # Win %, then point differential (league tiebreaker). Still tied = shared rank, prize split.
        rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else -1, r["pd"]), reverse=True)
        lead, prev = rows[0], None
        for i, r in enumerate(rows):
            same = prev is not None and r["pct"] == prev["pct"] and r["pd"] == prev["pd"]
            r["rank"] = prev["rank"] if same else i + 1
            r["gb"] = round(((lead["w"] - lead["l"]) - (r["w"] - r["l"])) / 2, 1)
            prev = r
        return rows

    standings = rank([owner_row(o) for o in owners_order])
    tstr = today.isoformat()
    months = []
    for m in MONTHS:
        status = "final" if tstr > m["end"] else ("live" if tstr >= m["start"] else "upcoming")
        rows = rank([owner_row(o, m["key"]) for o in owners_order]) if status != "upcoming" else []
        leaders = [r["owner"] for r in rows if r["rank"] == 1 and r["gp"]]
        months.append({**m, "status": status, "rows": rows, "leaders": leaders})

    # Weekly cumulative win % for the season race chart (each Sunday plus today)
    points, d = [], dt.date.fromisoformat(SEASON_START)
    while d <= today and d.isoformat() <= SEASON_END:
        if d.weekday() == 6 or d == today:
            points.append(d.isoformat())
        d += dt.timedelta(days=1)
    race = {o: [] for o in owners_order}
    for p in points:
        for o in owners_order:
            w = l = 0
            for tr in [x for x in DRAFT if x[1] == o]:
                for g in team[tr[2]]["log"]:
                    if g["d"] <= p:
                        w += g["r"] == "W"
                        l += g["r"] == "L"
            race[o].append(round(w / (w + l), 4) if w + l else None)

    return {
        "updated": updated, "season": SEASON_LABEL, "today": tstr,
        "season_start": SEASON_START, "season_end": SEASON_END, "champ_prize": CHAMP_PRIZE,
        "data_through": games[-1]["date"] if games else None, "games_counted": len(games),
        "owners": owners_order, "standings": standings, "months": months,
        "teams": teams, "draft_value": draft_value,
        "race": {"dates": points, "series": race},
        "draft_slots": [{"slot": s, "r1": a, "r2": b, "r3": c} for s, a, b, c in DRAFT_SLOTS],
    }


def sanity_check(games):
    per_team = {t: 0 for t in TEAMS}
    seen = set()
    for g in games:
        key = (g["date"], g["home"], g["away"])
        if key in seen:
            raise ValueError(f"Duplicate game {key}")
        seen.add(key)
        per_team[g["home"]] += 1
        per_team[g["away"]] += 1
    over = {t: n for t, n in per_team.items() if n > 82}
    if over:
        raise ValueError(f"Teams over 82 games: {over}")
    print(f"  Games per team: min {min(per_team.values())}, max {max(per_team.values())}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    now = eastern_now()
    today = now.date()
    print(f"NBA Wins Pool fetch at {now:%Y-%m-%d %H:%M} ET")

    games, source = None, None
    try:
        print("Fetching NBA schedule feed...")
        games, source = fetch_from_nba(), "NBA"
    except Exception as e:
        print(f"  NBA feed failed: {e}")
    if games is None:
        try:
            print("Falling back to ESPN scoreboard...")
            games, source = fetch_from_espn(today), "ESPN"
        except Exception as e:
            print(f"  ESPN fallback failed: {e}")
    if games is None:
        print("ERROR: no data source worked. Leaving data.json unchanged.")
        sys.exit(1)

    # Never replace a good cache with an obviously incomplete pull
    if os.path.exists(GAMES_FILE):
        with open(GAMES_FILE) as f:
            old = json.load(f)
        if len(games) < len(old.get("games", [])) - 5:
            print(f"ERROR: {source} returned {len(games)} games, cache has {len(old['games'])}. Not overwriting.")
            sys.exit(1)

    sanity_check(games)
    print(f"  {source}: {len(games)} counted regular-season finals")

    with open(GAMES_FILE, "w") as f:
        json.dump({"source": source, "fetched": now.isoformat(timespec="minutes"), "games": games}, f, indent=0)

    data = compute(games, today, now.strftime("%b %-d, %Y %-I:%M %p ET"))
    data["source"] = source
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))

    lead = data["standings"][0]
    print(f"Wrote {DATA_FILE}. Leader: {lead['owner']} {lead['w']}-{lead['l']}. Data through {data['data_through']}.")


if __name__ == "__main__":
    main()
