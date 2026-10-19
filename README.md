# sports-feed

A calendar feed of games for the teams in `teams.json`, times in US Eastern.

Subscribe in Google Calendar (Other calendars → From URL):

    https://raw.githubusercontent.com/GavinLu42/sports-feed/main/games.ics

- `teams.json`: tracked teams (ESPN team ids). Kept in sync with the Sports Calendar page by a daily scheduled task.
- `extra_games.json`: games added by hand for teams ESPN covers poorly. Each entry: `team` (a key from teams.json), `opponent`, `competition`, and either `start` (ISO 8601 with offset) or `date` (YYYY-MM-DD when the kickoff time is unknown); optional `id`, `home`, `url`, `note`.
- `build_feed.py`: pulls schedules from ESPN and writes `games.ics` and `games.json`.
- `.github/workflows/refresh.yml`: runs the build whenever the biweekly sweep updates `sweep.txt` or the team list changes. The feed covers the next 21 days (HORIZON_DAYS).
