#!/usr/bin/env python3
"""Fetch Westhill soccer schedules from ArbiterLive and export them to .ics files.

Generates one calendar file per team so people can subscribe to whichever teams
they care about. Designed to be run periodically (e.g. from cron) throughout the
season so schedule changes are captured. Calendar events use the site's stable
game IDs as their UIDs, so re-importing a file updates existing events instead of
creating duplicates.

Usage:
    python update_schedule.py                    # all teams
    python update_schedule.py --team boys-varsity  # one team (repeatable)
    python update_schedule.py --quiet            # suppress the change summary

Requires: requests, beautifulsoup4 (see requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# --- Configuration -----------------------------------------------------------


@dataclass(frozen=True)
class Team:
    slug: str  # CLI selector and snapshot key
    name: str  # calendar (X-WR-CALNAME) name
    label: str  # short prefix used in event summaries
    url: str
    ics_name: str  # output filename served by GitHub Pages


TEAMS = [
    Team(
        slug="boys-varsity",
        name="Westhill Boys Varsity Soccer",
        label="Boys Varsity",
        url="https://www.arbiterlive.com/Teams/Schedule/5046751?activeEntityId=25499",
        ics_name="whs-boys-varsity-soccer.ics",
    ),
    Team(
        slug="boys-jv",
        name="Westhill Boys JV Soccer",
        label="Boys JV",
        url="https://www.arbiterlive.com/Teams/Schedule/5118052?activeEntityId=25499",
        ics_name="whs-boys-jv-soccer.ics",
    ),
    Team(
        slug="boys-7-8",
        name="Westhill Boys 7th & 8th Grade Soccer",
        label="Boys 7/8",
        url="https://www.arbiterlive.com/Teams/Schedule/7674869?activeEntityId=25499",
        ics_name="whs-boys-7-8-soccer.ics",
    ),
    Team(
        slug="girls-varsity",
        name="Westhill Girls Varsity Soccer",
        label="Girls Varsity",
        url="https://www.arbiterlive.com/Teams/Schedule/4535412?activeEntityId=25499",
        ics_name="whs-girls-varsity-soccer.ics",
    ),
    Team(
        slug="girls-jv",
        name="Westhill Girls JV Soccer",
        label="Girls JV",
        url="https://www.arbiterlive.com/Teams/Schedule/7604162?activeEntityId=25499",
        ics_name="whs-girls-jv-soccer.ics",
    ),
    Team(
        slug="girls-7-8",
        name="Westhill Girls 7th & 8th Grade Soccer",
        label="Girls 7/8",
        url="https://www.arbiterlive.com/Teams/Schedule/7674870?activeEntityId=25499",
        ics_name="whs-girls-7-8-soccer.ics",
    ),
]

DOCS_DIR = Path(__file__).with_name("docs")
DEFAULT_SNAPSHOT = Path(__file__).with_name(".schedule-snapshot.json")

LOCAL_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DEFAULT_DURATION = timedelta(hours=2)
REQUEST_TIMEOUT = 30

WEEKDAYS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


@dataclass
class Game:
    game_id: str
    weekday: str
    month: int
    day: int
    time_text: str | None  # e.g. "5:00 PM", or None if TBD
    home: bool
    opponent: str
    location: str
    game_type: str
    year: int = 0  # filled in by resolve_years()

    @property
    def start(self) -> datetime | None:
        """Timezone-aware local start datetime, or None if the time is TBD."""
        if not self.time_text:
            return None
        parsed = datetime.strptime(self.time_text, "%I:%M %p")
        return datetime(
            self.year, self.month, self.day, parsed.hour, parsed.minute, tzinfo=LOCAL_TZ
        )


# --- Fetch & parse -----------------------------------------------------------


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_games(html: str) -> list[Game]:
    soup = BeautifulSoup(html, "html.parser")
    games: list[Game] = []

    for row in soup.select("tr[data-isgame='true']"):
        game_id = row.get("data-gameid", "").strip()
        cells = row.find_all("td", recursive=False)
        if not game_id or len(cells) < 4:
            continue

        weekday, month, day, time_text = _parse_datetime_cell(cells[0])
        if month is None:
            continue

        home = cells[1].get_text(strip=True).lower().startswith("vs")
        opponent = cells[2].get_text(" ", strip=True)
        location = cells[3].get_text(" ", strip=True)
        game_type = _parse_type(cells)

        games.append(
            Game(
                game_id=game_id,
                weekday=weekday,
                month=month,
                day=day,
                time_text=time_text,
                home=home,
                opponent=opponent,
                location=location,
                game_type=game_type,
            )
        )

    return games


def _parse_datetime_cell(cell) -> tuple[str, int | None, int | None, str | None]:
    text = cell.get_text(" ", strip=True)
    date_match = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})", text)
    time_match = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)", text, re.IGNORECASE)
    if not date_match:
        return "", None, None, None
    weekday = date_match.group(1)
    month = MONTHS.get(date_match.group(2))
    day = int(date_match.group(3))
    time_text = re.sub(r"\s+", " ", time_match.group(1)).upper() if time_match else None
    return weekday, month, day, time_text


def _parse_type(cells) -> str:
    for cell in cells:
        abbr = cell.find("abbr")
        if abbr and abbr.get("title"):
            return abbr["title"].strip()
    return ""


def resolve_years(games: list[Game], today: date | None = None) -> None:
    """Assign a calendar year to each game.

    The site only shows weekday/month/day, so the year is inferred: the first
    game's year is chosen so its weekday matches and it falls closest to today,
    then the year is rolled forward whenever the date sequence wraps (e.g. Dec to
    Jan).
    """
    if not games:
        return
    today = today or date.today()

    first = games[0]
    best_year = today.year
    best_delta = None
    for candidate in range(today.year - 1, today.year + 2):
        try:
            candidate_date = date(candidate, first.month, first.day)
        except ValueError:
            continue
        if candidate_date.strftime("%a") != first.weekday:
            continue
        delta = abs((candidate_date - today).days)
        if best_delta is None or delta < best_delta:
            best_delta, best_year = delta, candidate

    year = best_year
    prev = None
    for game in games:
        current = date(year, game.month, game.day)
        if prev is not None and current < prev:
            year += 1
            current = date(year, game.month, game.day)
        game.year = year
        prev = current


# --- ICS generation ----------------------------------------------------------


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold long lines to 75 octets per RFC 5545."""
    if len(line.encode("utf-8")) <= 75:
        return line
    folded, chunk = [], ""
    for char in line:
        if len((chunk + char).encode("utf-8")) > 75:
            folded.append(chunk)
            chunk = " " + char
        else:
            chunk += char
    folded.append(chunk)
    return "\r\n".join(folded)


def build_ics(team: Team, games: list[Game], generated_at: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WHS Soccer Schedule//update_schedule.py//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(team.name)}",
        "X-WR-TIMEZONE:America/New_York",
    ]
    stamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    for game in games:
        side = "vs" if game.home else "@"
        home_away = "Home" if game.home else "Away"
        summary = f"{team.label} Soccer: Westhill {side} {game.opponent} ({home_away})"
        description = f"{team.label} Soccer. {home_away} game vs {game.opponent}."
        if game.game_type:
            description += f" Type: {game.game_type}."

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:arbiterlive-game-{game.game_id}@arbiterlive.com")
        lines.append(f"DTSTAMP:{stamp}")

        start = game.start
        if start is None:
            # Time is TBD: emit an all-day event so the game still appears.
            day = date(game.year, game.month, game.day)
            lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}")
        else:
            end = start + DEFAULT_DURATION
            lines.append(f"DTSTART:{start.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}")
            lines.append(f"DTEND:{end.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}")

        lines.append(f"SUMMARY:{_ics_escape(summary)}")
        if game.location:
            lines.append(f"LOCATION:{_ics_escape(game.location)}")
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# --- Change detection --------------------------------------------------------


def load_snapshot(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def snapshot_from_games(games: list[Game]) -> dict[str, dict]:
    return {game.game_id: asdict(game) for game in games}


def summarize_changes(old: dict[str, dict], new: dict[str, dict]) -> list[str]:
    messages: list[str] = []
    tracked = ("year", "month", "day", "time_text", "home", "opponent", "location", "game_type")

    for game_id, game in new.items():
        if game_id not in old:
            messages.append(f"  + Added: {_describe(game)}")

    for game_id, game in old.items():
        if game_id not in new:
            messages.append(f"  - Removed: {_describe(game)}")

    for game_id, game in new.items():
        if game_id not in old:
            continue
        diffs = [
            f"{field}: {old[game_id].get(field)!r} -> {game.get(field)!r}"
            for field in tracked
            if old[game_id].get(field) != game.get(field)
        ]
        if diffs:
            messages.append(f"  ~ Changed: {_describe(game)}")
            messages.extend(f"      {diff}" for diff in diffs)

    return messages


def _describe(game: dict) -> str:
    side = "vs" if game.get("home") else "@"
    return f"{game.get('weekday')} {game.get('month')}/{game.get('day')} {side} {game.get('opponent')}"


# --- Entry point -------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Westhill soccer schedules to .ics files.")
    parser.add_argument(
        "--team",
        action="append",
        choices=[team.slug for team in TEAMS],
        metavar="SLUG",
        help="Limit to specific team(s). Repeatable. Default: all teams.",
    )
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR, help="Directory for the generated .ics files.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="Change-tracking JSON path.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the change summary.")
    return parser.parse_args(argv)


def select_teams(slugs: list[str] | None) -> list[Team]:
    if not slugs:
        return list(TEAMS)
    wanted = set(slugs)
    return [team for team in TEAMS if team.slug in wanted]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    teams = select_teams(args.team)

    args.docs_dir.mkdir(parents=True, exist_ok=True)
    old_snapshot = load_snapshot(args.snapshot)
    new_snapshot: dict[str, dict] = dict(old_snapshot)  # preserve teams not run this time
    generated_at = datetime.now(tz=UTC)
    exit_code = 0

    for team in teams:
        try:
            html = fetch_html(team.url)
        except requests.RequestException as error:
            print(f"[{team.slug}] Error fetching schedule: {error}", file=sys.stderr)
            exit_code = 1
            continue

        games = parse_games(html)
        if not games:
            print(f"[{team.slug}] No games found. The page layout may have changed.", file=sys.stderr)
            exit_code = 1
            continue
        resolve_years(games)

        ics = build_ics(team, games, generated_at)
        output_path = args.docs_dir / team.ics_name
        output_path.write_text(ics, encoding="utf-8")

        team_snapshot = snapshot_from_games(games)
        previous = old_snapshot.get(team.slug, {})
        new_snapshot[team.slug] = team_snapshot

        if not args.quiet:
            print(f"[{team.slug}] Wrote {len(games)} games to {output_path}")
            changes = summarize_changes(previous, team_snapshot)
            if not previous:
                print(f"[{team.slug}] First run: no previous snapshot to compare against.")
            elif changes:
                print(f"[{team.slug}] Schedule changes since last run:")
                print("\n".join(changes))
            else:
                print(f"[{team.slug}] No schedule changes since last run.")

    args.snapshot.write_text(json.dumps(new_snapshot, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
