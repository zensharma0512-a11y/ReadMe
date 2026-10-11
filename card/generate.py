#!/usr/bin/env python3
"""Build the GitHub stats and streak cards shown in README.md.

Writes card/stats-{dark,light}.svg and card/streak-{dark,light}.svg from live
GitHub data. The daily GitHub Action (.github/workflows/card.yml) runs this, so
the cards never depend on a third-party image service.

Usage:
  GITHUB_TOKEN=... python3 card/generate.py        # live data from the GitHub API
  python3 card/generate.py --data sample.json       # offline, data from a JSON file
"""
import argparse
import datetime as dt
import json
import os
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

LOGIN = "zensharma0512-a11y"
NAME = "Aryan"
TIMEZONE = "Asia/Kolkata"

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Helvetica, Arial, sans-serif"
W, H = 495, 195

THEMES = {
    "dark": dict(bg="#0d1117", border="#30363d", title="#58a6ff", text="#c9d1d9",
                 icon="#58a6ff", muted="#8b949e", accent="#fb8c00", track="#21262d"),
    "light": dict(bg="#ffffff", border="#d0d7de", title="#0969da", text="#24292f",
                  icon="#0969da", muted="#57606a", accent="#e36209", track="#eaeef2"),
}


# ---- GitHub data ----------------------------------------------------------------
def _request(url, token, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{LOGIN}-profile-cards")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def _graphql(token, query, variables):
    _, data = _request(f"{API}/graphql", token, {"query": query, "variables": variables})
    if data.get("errors"):
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def fetch_data(token):
    user = _graphql(token, """
    query($login: String!) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
          totalCount
          nodes { name stargazerCount }
        }
        contributionsCollection { contributionCalendar { totalContributions } }
      }
    }""", {"login": LOGIN})["user"]

    commits = 0
    for repo in user["repositories"]["nodes"]:
        commits += _repo_commits(repo["name"], token)

    return {
        "created_at": user["createdAt"],
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "followers": user["followers"]["totalCount"],
        "contributions_year": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "commits": commits,
        "days": _contribution_days(token, user["createdAt"]),
    }


def _repo_commits(repo, token):
    """All-time commits by LOGIN in one of their repos."""
    url = f"{API}/repos/{LOGIN}/{repo}/stats/contributors"
    for _ in range(12):  # GitHub answers 202 while it computes the stats
        status, data = _request(url, token)
        if status == 204:  # empty repo
            return 0
        if status == 200 and isinstance(data, list):
            for entry in data:
                if (entry.get("author") or {}).get("login", "").lower() == LOGIN.lower():
                    return entry["total"]
            return 0
        time.sleep(5)
    raise RuntimeError(f"GitHub did not finish computing stats for {repo}; try again later")


def _contribution_days(token, created_at):
    """{'YYYY-MM-DD': count} for every day since the account was created."""
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar { weeks { contributionDays { date contributionCount } } }
        }
      }
    }"""
    start = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    days = {}
    while start < now:  # the API allows at most one year per query
        end = min(start + dt.timedelta(days=364), now)
        cal = _graphql(token, query, {"login": LOGIN, "from": start.isoformat(), "to": end.isoformat()})
        for week in cal["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
        start = end
    return days


# ---- Streak maths ---------------------------------------------------------------
def streaks(days, today):
    """Total contributions, current streak and longest streak as (length, start, end)."""
    counts = {dt.date.fromisoformat(k): v for k, v in days.items() if dt.date.fromisoformat(k) <= today}
    total = sum(counts.values())
    if not counts:
        return total, (0, today, today), (0, None, None)

    # current streak: a quiet today doesn't break it yet, so start from yesterday then
    last = max(counts)
    day = last if counts[last] else last - dt.timedelta(days=1)
    end, length = day, 0
    while counts.get(day, 0) > 0:
        length, day = length + 1, day - dt.timedelta(days=1)
    current = (length, day + dt.timedelta(days=1), end) if length else (0, last, last)

    best, run_start, run = (0, None, None), None, 0
    for d in sorted(counts):
        if counts[d] > 0:
            run_start = d if run == 0 else run_start
            run += 1
            if run > best[0]:
                best = (run, run_start, d)
        else:
            run = 0
    return total, current, best


def fmt_day(d, today):
    return f"{d:%b} {d.day}" + (f", {d.year}" if d.year != today.year else "")


def fmt_range(a, b, today):
    if a is None:
        return "No streak yet"
    return fmt_day(a, today) if a == b else f"{fmt_day(a, today)} - {fmt_day(b, today)}"


# ---- Icons (16x16, drawn with basic shapes) --------------------------------------
def icon(kind, x, y, color, bg):
    g = f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round">'
    shapes = {
        "star": '<path d="M8 1.5l1.9 4.1 4.4.5-3.3 3 .9 4.4L8 11.3l-3.9 2.2.9-4.4-3.3-3 4.4-.5z"/>',
        "commit": f'<path d="M1 8h14"/><circle cx="8" cy="8" r="3" fill="{bg}"/>',
        "calendar": '<rect x="1.5" y="2.5" width="13" height="12" rx="2"/><path d="M1.5 6.5h13M5 1v3M11 1v3"/>',
        "people": '<circle cx="6" cy="5" r="2.5"/><path d="M1.5 14c0-2.6 2-4.5 4.5-4.5s4.5 1.9 4.5 4.5"/><path d="M10.5 2.8a2.3 2.3 0 0 1 0 4.4M12.5 9.8c1.3.7 2 2.2 2 4.2"/>',
        "repo": '<path d="M3 13.5V3a1.5 1.5 0 0 1 1.5-1.5H13v10H4.5A1.5 1.5 0 0 0 3 13a1.5 1.5 0 0 0 1.5 1.5H13"/>',
    }
    return g + shapes[kind] + "</g>"


def robot(cx, cy, color):
    """Small robot head drawn inside the stats card ring."""
    return (
        f'<g fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M{cx} {cy - 22}v-7"/><circle cx="{cx}" cy="{cy - 31}" r="2.5" fill="{color}"/>'
        f'<rect x="{cx - 17}" y="{cy - 15}" width="34" height="28" rx="7"/>'
        f'<path d="M{cx - 22} {cy - 4}v6M{cx + 22} {cy - 4}v6"/>'
        f'<path d="M{cx - 7} {cy + 6}h14"/></g>'
        f'<circle cx="{cx - 7}" cy="{cy - 3}" r="3" fill="{color}"/><circle cx="{cx + 7}" cy="{cy - 3}" r="3" fill="{color}"/>'
    )


def frame(t, label, body):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" aria-label="{escape(label)}">
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="6" fill="{t['bg']}" stroke="{t['border']}"/>
{body}
</svg>
"""


# ---- Cards ----------------------------------------------------------------------
def stats_card(theme, data):
    t = THEMES[theme]
    rows = [
        ("star", "Total Stars", data["stars"]),
        ("commit", "Total Commits", data["commits"]),
        ("calendar", "Contributions (last year)", data["contributions_year"]),
        ("people", "Followers", data["followers"]),
        ("repo", "Public Repos", data["repos"]),
    ]
    body = [f'<text x="25" y="38" font-size="18" font-weight="600" fill="{t["title"]}">{escape(NAME)}\'s GitHub Stats</text>']
    for i, (kind, label, value) in enumerate(rows):
        y = 70 + i * 25
        body.append(icon(kind, 25, y - 12, t["icon"], t["bg"]))
        body.append(f'<text x="50" y="{y}" font-size="14" font-weight="600" fill="{t["text"]}">{escape(label)}:</text>')
        body.append(f'<text x="255" y="{y}" font-size="14" font-weight="700" fill="{t["text"]}">{value:,}</text>')
    cx, cy = 405, 105
    body.append(f'<circle cx="{cx}" cy="{cy}" r="48" fill="none" stroke="{t["track"]}" stroke-width="6"/>')
    body.append(f'<circle cx="{cx}" cy="{cy}" r="48" fill="none" stroke="{t["icon"]}" stroke-width="6" stroke-opacity="0.85"/>')
    body.append(robot(cx, cy + 4, t["icon"]))
    label = (f"{NAME}'s GitHub stats: {data['stars']} stars, {data['commits']} commits, "
             f"{data['contributions_year']} contributions in the last year, {data['followers']} followers, "
             f"{data['repos']} public repos")
    return frame(t, label, "\n".join(body))


def streak_card(theme, data, today):
    t = THEMES[theme]
    since = dt.datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")).date()
    total, (cur, cur_a, cur_b), (best, best_a, best_b) = streaks(data["days"], today)

    def side(x, number, label, dates):
        return (
            f'<text x="{x}" y="84" text-anchor="middle" font-size="28" font-weight="700" fill="{t["text"]}">{number:,}</text>'
            f'<text x="{x}" y="118" text-anchor="middle" font-size="14" fill="{t["text"]}">{escape(label)}</text>'
            f'<text x="{x}" y="146" text-anchor="middle" font-size="12" fill="{t["muted"]}">{escape(dates)}</text>'
        )

    cx = W / 2
    body = [
        f'<line x1="165" y1="28" x2="165" y2="168" stroke="{t["border"]}"/>',
        f'<line x1="330" y1="28" x2="330" y2="168" stroke="{t["border"]}"/>',
        side(82.5, total, "Total Contributions", f"{fmt_day(since, today)} - Present"),
        side(412.5, best, "Longest Streak", fmt_range(best_a, best_b, today) if best else "No streak yet"),
        # current streak: ring with a flame breaking it at the top
        f'<circle cx="{cx}" cy="71" r="40" fill="none" stroke="{t["accent"]}" stroke-width="5"/>',
        f'<circle cx="{cx}" cy="29" r="13" fill="{t["bg"]}"/>',
        f'<path transform="translate({cx} 29)" fill="{t["accent"]}" d="M0 -12C3 -7 9 -3 8 4C7 9 3 11 0 11C-4 11 -8 8 -8 3C-8 -1 -5 -3 -4 -6C-3 -3 -2 -2 -1 -2C-1 -6 -2 -9 0 -12Z"/>',
        f'<text x="{cx}" y="81" text-anchor="middle" font-size="28" font-weight="700" fill="{t["text"]}">{cur:,}</text>',
        f'<text x="{cx}" y="140" text-anchor="middle" font-size="14" font-weight="700" fill="{t["accent"]}">Current Streak</text>',
        f'<text x="{cx}" y="166" text-anchor="middle" font-size="12" fill="{t["muted"]}">{escape(fmt_range(cur_a, cur_b, today))}</text>',
    ]
    label = (f"{NAME}'s contribution streak: {total} total contributions, current streak {cur} days, "
             f"longest streak {best} days")
    return frame(t, label, "\n".join(body))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, help="read data from this JSON file instead of the API")
    args = ap.parse_args()

    if args.data:
        data = json.loads(args.data.read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("Set GITHUB_TOKEN (or pass --data FILE).")
        data = fetch_data(token)

    today = dt.datetime.now(ZoneInfo(TIMEZONE)).date()
    for theme in THEMES:
        (HERE / f"stats-{theme}.svg").write_text(stats_card(theme, data))
        (HERE / f"streak-{theme}.svg").write_text(streak_card(theme, data, today))
    summary = {k: v for k, v in data.items() if k != "days"}
    summary["streaks"] = [str(x) for x in streaks(data["days"], today)]
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
