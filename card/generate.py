#!/usr/bin/env python3
"""Build the terminal-style profile card shown in README.md.

Writes card/dark.svg and card/light.svg. GitHub stats and uptime are fetched
live, so a daily GitHub Action (.github/workflows/card.yml) keeps them current.

Usage:
  GITHUB_TOKEN=... python3 card/generate.py        # live stats from the GitHub API
  python3 card/generate.py --stats sample.json      # offline, stats from a JSON file
"""
import argparse
import calendar
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

# ---- Edit these to change what the card says -------------------------------
LOGIN = "zensharma0512-a11y"
HEADER = "aryan@sharma"
PROFILE = [
    ("OS", "Windows"),
    ("Uptime", "{uptime}"),
    ("Host", "Manipal University Jaipur"),
    ("Kernel", "Robotics & AI Student"),
]
CONTACT = [
    ("GitHub", LOGIN),
]
TIMEZONE = "Asia/Kolkata"
# -----------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
WIDTH = 56            # characters per line in the info column
LEFT_HALF = 28        # width of the left stat in "Repos: 1 | Stars: 0" rows
CHAR_W, LINE_H = 9.7, 20
PAD_X, PAD_Y, GAP = 20, 34, 34

THEMES = {
    "dark": dict(bg="#161b22", border="#30363d", text="#c9d1d9", key="#ffa657",
                 value="#a5d6ff", cc="#616e7f", add="#3fb950", dele="#f85149"),
    "light": dict(bg="#f6f8fa", border="#d0d7de", text="#24292f", key="#953800",
                  value="#0a3069", cc="#8c959f", add="#1a7f37", dele="#cf222e"),
}

API = "https://api.github.com"


# ---- GitHub data -------------------------------------------------------------
def _request(url, token, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{LOGIN}-profile-card")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def fetch_stats(token):
    query = """
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
    }"""
    _, data = _request(f"{API}/graphql", token, {"query": query, "variables": {"login": LOGIN}})
    if data.get("errors"):
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    user = data["data"]["user"]
    repos = user["repositories"]

    commits = additions = deletions = 0
    for repo in repos["nodes"]:
        c, a, d = _repo_contributions(repo["name"], token)
        commits, additions, deletions = commits + c, additions + a, deletions + d

    return {
        "created_at": user["createdAt"],
        "repos": repos["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos["nodes"]),
        "followers": user["followers"]["totalCount"],
        "contributions": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "commits": commits,
        "additions": additions,
        "deletions": deletions,
    }


def _repo_contributions(repo, token):
    """Commits, lines added and lines deleted by LOGIN in one repo (all time)."""
    url = f"{API}/repos/{LOGIN}/{repo}/stats/contributors"
    for _ in range(12):  # GitHub answers 202 while it computes the stats
        status, data = _request(url, token)
        if status == 204:  # empty repo
            return 0, 0, 0
        if status == 200 and isinstance(data, list):
            for entry in data:
                if (entry.get("author") or {}).get("login", "").lower() == LOGIN.lower():
                    weeks = entry.get("weeks", [])
                    return entry["total"], sum(w["a"] for w in weeks), sum(w["d"] for w in weeks)
            return 0, 0, 0
        time.sleep(5)
    raise RuntimeError(f"GitHub did not finish computing stats for {repo}; try again later")


def uptime(since, today):
    """Elapsed time as 'X years, Y months, Z days'."""
    total_months = (today.year - since.year) * 12 + today.month - since.month
    if today.day < since.day:
        total_months -= 1
    year, month = divmod(since.month - 1 + total_months, 12)
    year, month = since.year + year, month + 1
    anchor = dt.date(year, month, min(since.day, calendar.monthrange(year, month)[1]))
    days = (today - anchor).days
    years, months = divmod(total_months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' * (years != 1)}")
    if years or months:
        parts.append(f"{months} month{'s' * (months != 1)}")
    parts.append(f"{days} day{'s' * (days != 1)}")
    return ", ".join(parts)


# ---- Layout --------------------------------------------------------------------
# A line is a list of (text, css_class) spans; css_class None means plain text.
def _len(spans):
    return sum(len(t) for t, _ in spans)


def kv(key, value, width=WIDTH, lead=". "):
    """'. Key: ........ value', padded with dots to exactly `width` characters."""
    if isinstance(value, str):
        value = [(value, "value")]
    head = [(lead, "cc"), (key, "key"), (":", None), (" ", None)]
    tail = [(" ", None)] + value
    dots = max(1, width - _len(head) - _len(tail))
    return head + [("." * dots, "cc")] + tail


def pair(k1, v1, k2, v2):
    right = WIDTH - LEFT_HALF - 3
    return kv(k1, v1, LEFT_HALF) + [(" | ", None)] + kv(k2, v2, right, lead="")


def rule(title):
    return [(title, None), (" " + "-" * (WIDTH - len(title) - 1), None)]


def info_lines(stats, today):
    since = dt.datetime.fromisoformat(stats["created_at"].replace("Z", "+00:00")).date()
    up = uptime(since, today)
    n = lambda x: f"{x:,}"
    lines = [rule(HEADER)]
    lines += [kv(k, v.format(uptime=up)) for k, v in PROFILE]
    lines += [[(".", "cc")], rule("- Contact")]
    lines += [kv(k, v) for k, v in CONTACT]
    lines += [[(".", "cc")], rule("- GitHub Stats")]
    lines += [
        pair("Repos", n(stats["repos"]), "Stars", n(stats["stars"])),
        pair("Commits", n(stats["commits"]), "Followers", n(stats["followers"])),
        kv("Contributions (past year)", n(stats["contributions"])),
        kv("Lines of Code", [
            (n(stats["additions"] - stats["deletions"]), "value"), (" ( ", None),
            (n(stats["additions"]) + "++", "add"), (", ", None),
            (n(stats["deletions"]) + "--", "dele"), (" )", None),
        ]),
    ]
    return lines


def render(theme, art, lines):
    t = THEMES[theme]
    art_w = max(len(a) for a in art)
    info_x = PAD_X + art_w * CHAR_W + GAP
    width = round(info_x + WIDTH * CHAR_W + PAD_X)
    rows = max(len(art), len(lines))
    height = round(PAD_Y * 2 + (rows - 1) * LINE_H + 6)

    def top(count):  # vertically centre the shorter column
        return PAD_Y + (rows - count) * LINE_H / 2

    def line(x, y, spans):
        inner = "".join(
            f'<tspan class="{c}">{escape(s)}</tspan>' if c else escape(s) for s, c in spans
        )
        return f'<tspan x="{x:g}" y="{y:g}">{inner}</tspan>'

    art_y, info_y = top(len(art)), top(len(lines))
    art_svg = "".join(line(PAD_X, art_y + i * LINE_H, [(a, None)]) for i, a in enumerate(art))
    info_svg = "".join(line(info_x, info_y + i * LINE_H, s) for i, s in enumerate(lines))
    alt = "Aryan Sharma: " + ", ".join(f"{k} {v}" for k, v in PROFILE if "{" not in v)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="ConsolasFallback, Consolas, Menlo, 'DejaVu Sans Mono', 'Courier New', monospace" font-size="16px" role="img" aria-label="{escape(alt)}">
<style>
@font-face {{ src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }}
text {{ white-space: pre; }}
.key {{ fill: {t['key']}; }} .value {{ fill: {t['value']}; }} .cc {{ fill: {t['cc']}; }}
.add {{ fill: {t['add']}; }} .dele {{ fill: {t['dele']}; }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="14" fill="{t['bg']}" stroke="{t['border']}"/>
<text xml:space="preserve" fill="{t['text']}">{art_svg}</text>
<text xml:space="preserve" fill="{t['text']}">{info_svg}</text>
</svg>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", type=Path, help="read stats from this JSON file instead of the API")
    args = ap.parse_args()

    if args.stats:
        stats = json.loads(args.stats.read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("Set GITHUB_TOKEN (or pass --stats FILE).")
        stats = fetch_stats(token)

    today = dt.datetime.now(ZoneInfo(TIMEZONE)).date()
    art = (HERE / "art.txt").read_text().strip("\n").split("\n")
    lines = info_lines(stats, today)
    for theme in THEMES:
        (HERE / f"{theme}.svg").write_text(render(theme, art, lines))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
