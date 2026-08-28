# WHS Soccer Schedule → Google Calendar

Fetches the Westhill High School Boys Varsity Soccer schedule from
[ArbiterLive](https://www.arbiterlive.com/Teams/Schedule/5046751?activeEntityId=25499)
and exports it to an `.ics` calendar file you can import into Google Calendar
(or any calendar app). It's designed to be re-run throughout the season so
schedule changes are picked up automatically.

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
- A snapshot of the last run is saved to `.schedule-snapshot.json`, and each run
  prints a summary of any games that were added, removed, or changed.

## Files

| File | Purpose |
|:------|:---------|
| `update_schedule.py` | The scraper / `.ics` generator. |
| `requirements.txt` | Python dependencies. |
| `whs-boys-varsity-soccer.ics` | Generated calendar file (import this). |
| `docs/index.html` | Landing page served via GitHub Pages. |
| `docs/whs-boys-varsity-soccer.ics` | Copy of the calendar served via GitHub Pages. |
| `.schedule-snapshot.json` | Change-tracking state (auto-generated, git-ignored). |

## Setup

Requires Python 3.9+.

```bash
cd /path/to/whs-soccer-schedule
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Usage

Run the script to (re)generate the `.ics` file:

```bash
.venv/bin/python update_schedule.py
```

Example output:

```text
Wrote 16 games to /path/to/whs-soccer-schedule/whs-boys-varsity-soccer.ics
Schedule changes since last run:
  ~ Changed: Tue Sep 8 @ Skaneateles Central Schools
      time_text: '6:30 PM' -> '7:00 PM'
```

### Options

| Flag | Description |
|------|-------------|
| `--url <URL>` | Use a different schedule page (e.g. another team or season). |
| `--ics <PATH>` | Write the calendar to a different location. |
| `--docs-ics <PATH>` | Where to copy the calendar for GitHub Pages (`none` to skip). |
| `--snapshot <PATH>` | Use a different change-tracking file. |
| `--quiet` | Suppress the change summary (useful for cron). |

Each run also copies the calendar to `docs/whs-boys-varsity-soccer.ics` so it can
be served via GitHub Pages (see below).

## Importing into Google Calendar

1. Go to [calendar.google.com](https://calendar.google.com) → gear icon → **Settings**.
2. In the left sidebar, choose **Import & export**.
3. Under **Import**, select `whs-boys-varsity-soccer.ics`.
4. Pick the calendar to add the events to, then click **Import**.

Because events use stable IDs, you can re-import the updated file after any run
and Google Calendar will update the matching events in place.

> **Tip:** For hands-off syncing, host the `.ics` at a public URL and add it in
> Google Calendar via **Other calendars → From URL**. Google then re-fetches it
> periodically on its own.

## Hosting with GitHub Pages

The `docs/` folder is set up to be served by GitHub Pages, giving you a public
landing page and a stable URL for the `.ics` file that calendar apps can
subscribe to.

**One-time setup:**

1. Push this repository to GitHub.
2. In the repository, go to **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to *Deploy from a branch*,
   choose your default branch (e.g. `main`) and the **`/docs`** folder, then
   **Save**.
4. After a minute, your page is live at
   `https://<username>.github.io/<repository>/`, and the calendar is at
   `https://<username>.github.io/<repository>/whs-boys-varsity-soccer.ics`.

Give that `.ics` URL to anyone who wants to subscribe. Because the events use
stable IDs, subscribers' calendars update automatically as the schedule changes.

## Weekly update workflow

Once Pages is set up, keeping everyone current is a matter of re-running the
script and pushing the result each week:

```bash
cd /path/to/whs-soccer-schedule
.venv/bin/python update_schedule.py
git add whs-boys-varsity-soccer.ics docs/whs-boys-varsity-soccer.ics
git commit -m "chore: update schedule"
git push
```

The script prints a summary of any games that changed, so you can see what was
updated before pushing.

## Running periodically

To refresh the schedule automatically (for example, every Monday at 6 AM), add a
cron entry with `crontab -e`:

```cron
0 6 * * 1 cd /path/to/whs-soccer-schedule && .venv/bin/python update_schedule.py --quiet >> update.log 2>&1
```

To also publish updates automatically, append the git commands to the cron job
(this commits and pushes only when the calendar actually changed):

```cron
0 6 * * 1 cd /path/to/whs-soccer-schedule && .venv/bin/python update_schedule.py --quiet && git add whs-boys-varsity-soccer.ics docs/whs-boys-varsity-soccer.ics && git diff --cached --quiet || git commit -m "chore: update schedule" && git push >> update.log 2>&1
```

## Notes

- Game duration defaults to 2 hours (`DEFAULT_DURATION` in `update_schedule.py`),
  since the site lists only start times. Adjust it there if needed.
- If a game's time is listed as TBD, it is exported as an all-day event so it
  still appears on the calendar.
- If the script reports "No games found," the site's page layout may have
  changed and the parser in `update_schedule.py` will need updating.
