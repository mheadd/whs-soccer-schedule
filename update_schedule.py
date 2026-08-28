#!/usr/bin/env python3
"""Fetch a high-school team schedule from ArbiterLive and export it to an .ics file.

Designed to be run periodically (e.g. from cron) throughout the season so that
schedule changes are captured. Calendar events use the site's stable game IDs as
their UIDs, so re-importing the generated .ics into Google Calendar updates the
existing events instead of creating duplicates.

Usage:
    python update_schedule.py                # use built-in defaults
    python update_schedule.py --url <URL>    # override the schedule URL
    python update_schedule.py --quiet        # suppress the change summary

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

DEFAULT_URL = "https://www.arbiterlive.com/Teams/Schedule/5046751?activeEntityId=25499"
DEFAULT_ICS = Path(__file__).with_name("whs-boys-varsity-soccer.ics")
DEFAULT_SNAPSHOT = Path(__file__).with_name(".schedule-snapshot.json")
# Copy served by GitHub Pages; committed and pushed after each run.
DEFAULT_DOCS_ICS = Path(__file__).with_name("docs") / "whs-boys-varsity-soccer.ics"

CALENDAR_NAME = "Westhill Boys Varsity Soccer"
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


def build_ics(games: list[Game], generated_at: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WHS Soccer Schedule//update_schedule.py//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(CALENDAR_NAME)}",
        "X-WR-TIMEZONE:America/New_York",
    ]
    stamp = generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    for game in games:
        side = "vs" if game.home else "@"
        home_away = "Home" if game.home else "Away"
        summary = f"Soccer: Westhill {side} {game.opponent} ({home_away})"
        description = f"Boys Varsity Soccer. {home_away} game vs {game.opponent}."
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
    parser = argparse.ArgumentParser(description="Export an ArbiterLive schedule to an .ics file.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Schedule page URL.")
    parser.add_argument("--ics", type=Path, default=DEFAULT_ICS, help="Output .ics path.")
    parser.add_argument(
        "--docs-ics",
        type=Path,
        default=DEFAULT_DOCS_ICS,
        help="Copy of the .ics served by GitHub Pages. Use 'none' to skip.",
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="Change-tracking JSON path.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the change summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        html = fetch_html(args.url)
    except requests.RequestException as error:
        print(f"Error fetching schedule: {error}", file=sys.stderr)
        return 1

    games = parse_games(html)
    if not games:
        print("No games found. The page layout may have changed.", file=sys.stderr)
        return 1
    resolve_years(games)

    old_snapshot = load_snapshot(args.snapshot)
    new_snapshot = snapshot_from_games(games)

    ics = build_ics(games, datetime.now(tz=UTC))
    args.ics.write_text(ics, encoding="utf-8")
    args.snapshot.write_text(json.dumps(new_snapshot, indent=2), encoding="utf-8")

    docs_ics = args.docs_ics
    if docs_ics is not None and str(docs_ics).lower() != "none":
        docs_ics.parent.mkdir(parents=True, exist_ok=True)
        docs_ics.write_text(ics, encoding="utf-8")

    if not args.quiet:
        print(f"Wrote {len(games)} games to {args.ics}")
        if docs_ics is not None and str(docs_ics).lower() != "none":
            print(f"Copied calendar to {docs_ics}")
        changes = summarize_changes(old_snapshot, new_snapshot)
        if not old_snapshot:
            print("First run: no previous snapshot to compare against.")
        elif changes:
            print("Schedule changes since last run:")
            print("\n".join(changes))
        else:
            print("No schedule changes since last run.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
