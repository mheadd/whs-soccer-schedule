# WHS Soccer Schedules → Google Calendar

Fetches the Westhill High School soccer schedules from
[ArbiterLive](https://www.arbiterlive.com/) and exports each team to its own
`.ics` calendar file you can import into Google Calendar (or any calendar app).
It's designed to be re-run throughout the season so schedule changes are picked
up automatically.

Teams covered:

| Team | Calendar file |
|------|---------------|
| Boys Varsity | `docs/whs-boys-varsity-soccer.ics` |
| Boys JV | `docs/whs-boys-jv-soccer.ics` |
| Boys 7th & 8th Grade | `docs/whs-boys-7-8-soccer.ics` |
| Girls Varsity | `docs/whs-girls-varsity-soccer.ics` |
| Girls JV | `docs/whs-girls-jv-soccer.ics` |
| Girls 7th & 8th Grade | `docs/whs-girls-7-8-soccer.ics` |

Team definitions (names, URLs, filenames) live in the `TEAMS` list at the top of
`update_schedule.py`.

## How it works

- The schedule page is server-rendered HTML, so the script reads it directly
  with `requests` + `beautifulsoup4` — no browser or JavaScript engine required.
- Each calendar event uses the site's stable game ID as its `UID`. This means
  **re-importing the file updates existing events instead of creating
  duplicates**, even if a game's date, time, or location changes.
- Times are converted from Eastern (`America/New_York`) to UTC using Python's
  `zoneinfo`, so daylight saving time is handled correctly.
- The year is inferred from the weekday labels shown on the page and rolls over
  correctly if a season spans from December into January.
- A snapshot of the last run is saved to `.schedule-snapshot.json` (keyed by
  team), and each run prints a per-team summary of any games that were added,
  removed, or changed.

## Files

| File | Purpose |
|:------|:---------|
| `update_schedule.py` | The scraper / `.ics` generator (teams defined in `TEAMS`). |
| `requirements.txt` | Python dependencies. |
| `docs/index.html` | Landing page served via GitHub Pages. |
| `docs/whs-*-soccer.ics` | Generated calendar files (one per team). |
| `docs/westhill-logo.jpg` | Logo used on the landing page. |
| `.schedule-snapshot.json` | Change-tracking state (auto-generated, git-ignored). |

## Setup

Requires Python 3.9+.

```bash
cd /path/to/whs-soccer-schedule
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Usage

Run the script to (re)generate every team's `.ics` file into `docs/`:

```bash
.venv/bin/python update_schedule.py
```

Generate a single team (repeat `--team` for more than one):

```bash
.venv/bin/python update_schedule.py --team boys-varsity --team girls-varsity
```

Example output:

```text
[boys-varsity] Wrote 16 games to docs/whs-boys-varsity-soccer.ics
[boys-varsity] Schedule changes since last run:
  ~ Changed: Tue Sep 8 @ Skaneateles Central Schools
      time_text: '6:30 PM' -> '7:00 PM'
```

### Options

| Flag | Description |
|------|-------------|
| `--team <SLUG>` | Limit to specific team(s). Repeatable. Default: all teams. |
| `--docs-dir <PATH>` | Directory for the generated `.ics` files (default: `docs/`). |
| `--snapshot <PATH>` | Use a different change-tracking file. |
| `--quiet` | Suppress the change summary (useful for cron). |

Valid team slugs: `boys-varsity`, `boys-jv`, `boys-7-8`, `girls-varsity`,
`girls-jv`, `girls-7-8`.

## Importing into Google Calendar

1. Go to [calendar.google.com](https://calendar.google.com) → gear icon → **Settings**.
2. In the left sidebar, choose **Import & export**.
3. Under **Import**, select the team's `.ics` file from `docs/`.
4. Pick the calendar to add the events to, then click **Import**.

Because events use stable IDs, you can re-import the updated file after any run
and Google Calendar will update the matching events in place.

> **Tip:** For hands-off syncing, host the `.ics` at a public URL and add it in
> Google Calendar via **Other calendars → From URL**. Google then re-fetches it
> periodically on its own.

## Hosting with GitHub Pages

The `docs/` folder is set up to be served by GitHub Pages, giving you a public
landing page and stable URLs for the `.ics` files that calendar apps can
subscribe to.

**One-time setup:**

1. Push this repository to GitHub.
2. In the repository, go to **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to *Deploy from a branch*,
   choose your default branch (e.g. `main`) and the **`/docs`** folder, then
   **Save**.
4. After a minute, your landing page is live at
   `https://<username>.github.io/<repository>/`, and each calendar is at
   `https://<username>.github.io/<repository>/<team-file>.ics`
   (e.g. `.../whs-girls-varsity-soccer.ics`).

Share the landing page and let people pick their team. Because the events use
stable IDs, subscribers' calendars update automatically as schedules change.

## Weekly update workflow

Once Pages is set up, keeping everyone current is a matter of re-running the
script and pushing the result each week:

```bash
cd /path/to/whs-soccer-schedule
.venv/bin/python update_schedule.py
git add docs/*.ics
git commit -m "chore: update schedules"
git push
```

The script prints a per-team summary of any games that changed, so you can see
what was updated before pushing.

## Running periodically

To refresh the schedules automatically (for example, every Monday at 6 AM), add a
cron entry with `crontab -e`:

```cron
0 6 * * 1 cd /path/to/whs-soccer-schedule && .venv/bin/python update_schedule.py --quiet >> update.log 2>&1
```

To also publish updates automatically, append the git commands to the cron job
(this commits and pushes only when a calendar actually changed):

```cron
0 6 * * 1 cd /path/to/whs-soccer-schedule && .venv/bin/python update_schedule.py --quiet && git add docs/*.ics && git diff --cached --quiet || git commit -m "chore: update schedules" && git push >> update.log 2>&1
```

## Notes

- Game duration defaults to 2 hours (`DEFAULT_DURATION` in `update_schedule.py`),
  since the site lists only start times. Adjust it there if needed.
- If a game's time is listed as TBD, it is exported as an all-day event so it
  still appears on the calendar.
- If the script reports "No games found," the site's page layout may have
  changed and the parser in `update_schedule.py` will need updating.
