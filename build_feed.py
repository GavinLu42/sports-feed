#!/usr/bin/env python3
"""Build games.ics and games.json for the teams in teams.json.

Fixtures come from ESPN's public schedule data; extra_games.json holds games
added by hand (or by the scheduled Claude task) for teams ESPN covers poorly.
Times are written in America/New_York. Run: python3 build_feed.py [--offline DIR]
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")
KEEP_PAST_DAYS = 45
HORIZON_DAYS = int(os.environ.get("HORIZON_DAYS", "21"))  # how far ahead the feed looks
UA = {"User-Agent": "Mozilla/5.0 (sports-feed calendar builder)"}

SPORTS = {
    "nba":    {"path": "basketball/nba", "emoji": "🏀", "hours": 2.5, "seasontypes": [1, 2, 3, 5], "label": "NBA"},
    "wnba":   {"path": "basketball/wnba", "emoji": "🏀", "hours": 2.0, "seasontypes": [1, 2, 3], "label": "WNBA"},
    "mbb":    {"path": "basketball/mens-college-basketball", "emoji": "🏀", "hours": 2.0, "seasontypes": [1, 2, 3], "label": "NCAA"},
    "wbb":    {"path": "basketball/womens-college-basketball", "emoji": "🏀", "hours": 2.0, "seasontypes": [1, 2, 3], "label": "NCAAW"},
    "soccer": {"path": "soccer/all", "emoji": "⚽", "hours": 2.0, "seasontypes": None, "label": "Soccer"},
}
SPORTS["soccer-national"] = SPORTS["soccer"]

COMP_NAMES = {
    "fra.1": "Ligue 1", "fra.2": "Ligue 2", "fra.coupe_de_france": "Coupe de France",
    "chn.1": "CSL", "chn.cup": "CFA Cup", "afc.champions": "AFC Champions League",
    "afc.cupchampions": "AFC Champions League Two", "afc.asian.cup": "Asian Cup",
    "fifa.friendly": "Friendly", "fifa.worldq.afc": "WC Qualifier", "afc.u23": "AFC U23 Asian Cup",
    "eng.1": "Premier League", "esp.1": "LaLiga", "ita.1": "Serie A", "ger.1": "Bundesliga",
    "uefa.champions": "Champions League", "uefa.europa": "Europa League",
}


def load(name, default):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def season_for(sport, now):
    # ESPN labels a basketball season by the year it ends (2026-27 -> 2027).
    if sport in ("nba", "mbb", "wbb"):
        return now.year + 1 if now.month >= 8 else now.year
    return now.year


def espn_urls(team, now):
    s = SPORTS[team["sport"]]
    base = f"https://site.api.espn.com/apis/site/v2/sports/{s['path']}/teams/{team['espn_id']}/schedule"
    if team["sport"].startswith("soccer"):
        return [base, base + "?fixture=true"]
    season = season_for(team["sport"], now)
    return [base] + [f"{base}?season={season}&seasontype={t}" for t in s["seasontypes"]]


def fetch_json(url, offline_dir=None):
    if offline_dir:
        key = url.split("/sports/")[1].replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "-")
        p = os.path.join(offline_dir, key + ".json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def comp_name(ev, comp):
    lg = ev.get("league") or comp.get("league") or {}
    slug = lg.get("slug") or lg.get("abbreviation") or ""
    if slug in COMP_NAMES:
        return COMP_NAMES[slug]
    name = lg.get("shortName") or lg.get("name") or lg.get("abbreviation")
    if name:
        return name
    st = (ev.get("seasonType") or {}).get("name")
    return st or ""


def parse_event(ev, team, cfg):
    comps = ev.get("competitions") or [{}]
    comp = comps[0]
    when = comp.get("date") or ev.get("date")
    if not when:
        return None
    start = datetime.fromisoformat(when.replace("Z", "+00:00"))
    time_valid = comp.get("timeValid", ev.get("timeValid", True))
    status = ((comp.get("status") or {}).get("type") or {})
    status_name = status.get("name", "")
    if status.get("state") == "pre" and "TBD" in (status.get("detail") or ""):
        time_valid = False

    me, opp = None, None
    for c in comp.get("competitors") or []:
        if str((c.get("team") or {}).get("id") or c.get("id")) == str(team["espn_id"]):
            me = c
        else:
            opp = c
    if not opp:
        return None
    ot = opp.get("team") or {}
    opp_name = ot.get("shortDisplayName") or ot.get("displayName") or ot.get("name") or "TBD"
    home = (me or {}).get("homeAway", "home") == "home"
    neutral = comp.get("neutralSite", False)
    sep = "vs" if (home or neutral) else "@"
    competition = comp_name(ev, comp) if team["sport"].startswith("soccer") else ""
    note = ""
    for n in comp.get("notes") or []:
        if n.get("headline"):
            note = n["headline"]
            break

    title = f"{cfg['emoji']} {team['short']} {sep} {opp_name}"
    if not team["sport"].startswith("soccer") and str((ev.get("seasonType") or {}).get("type") or (ev.get("seasonType") or {}).get("id")) == "1":
        competition = "Exhibition" if team["sport"] in ("mbb", "wbb") else "Preseason"
    if competition:
        title += f" ({competition})"
    if status_name == "STATUS_POSTPONED":
        title = "[Postponed] " + title
    if not time_valid:
        title += " · time TBD"

    venue = (comp.get("venue") or {})
    addr = venue.get("address") or {}
    location = ", ".join(x for x in [venue.get("fullName"), addr.get("city"), addr.get("state") or addr.get("country")] if x)

    link = ""
    for l in ev.get("links") or []:
        if "summary" in (l.get("rel") or []) or "desktop" in (l.get("rel") or []):
            link = l.get("href", "")
            break

    return {
        "uid": f"espn-{ev.get('id')}",
        "team": team["key"],
        "teamName": team["name"],
        "teamShort": team["short"],
        "sport": team["sport"],
        "title": title,
        "opponent": opp_name,
        "home": home,
        "neutral": bool(neutral),
        "competition": competition or cfg["label"],
        "note": note,
        "start": start.astimezone(ET).isoformat(),
        "allDay": not time_valid,
        "hours": cfg["hours"],
        "status": status_name or "STATUS_SCHEDULED",
        "location": location,
        "url": link,
        "source": "espn",
    }


def manual_games(extra, teams_by_key):
    out = []
    for g in extra:
        t = teams_by_key.get(g.get("team"))
        if not t or not t.get("active", True):
            continue
        cfg = SPORTS.get(t["sport"], SPORTS["soccer"])
        all_day = "date" in g and "start" not in g
        if all_day:
            start = datetime.fromisoformat(g["date"]).replace(tzinfo=ET)
        else:
            start = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET)
        sep = "vs" if g.get("home", True) or g.get("neutral") else "@"
        title = g.get("title") or f"{cfg['emoji']} {t['short']} {sep} {g.get('opponent', 'TBD')}"
        if g.get("competition") and "(" not in title:
            title += f" ({g['competition']})"
        if all_day and "TBD" not in title:
            title += " · time TBD"
        out.append({
            "uid": g.get("id") or f"manual-{t['key']}-{start.date().isoformat()}",
            "team": t["key"], "teamName": t["name"], "teamShort": t["short"], "sport": t["sport"], "title": title,
            "opponent": g.get("opponent", ""), "home": g.get("home", True), "neutral": g.get("neutral", False),
            "competition": g.get("competition", ""), "note": g.get("note", ""),
            "start": start.isoformat(), "allDay": all_day, "hours": g.get("hours", cfg["hours"]),
            "status": g.get("status", "STATUS_SCHEDULED"), "location": g.get("location", ""),
            "url": g.get("url", ""), "source": "manual",
        })
    return out


def esc(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += cb
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""


def to_ics(games):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sports-feed//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:My Teams", "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    lines += VTIMEZONE.split("\n")
    for g in games:
        start = datetime.fromisoformat(g["start"]).astimezone(ET)
        stamp = datetime.fromisoformat(g["start"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{g['uid']}@sports-feed")
        lines.append(f"DTSTAMP:{stamp}")
        if g["allDay"]:
            d = start.date()
            lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}")
            lines.append("TRANSP:TRANSPARENT")
        else:
            end = start + timedelta(hours=g["hours"])
            lines.append(f"DTSTART;TZID=America/New_York:{start.strftime('%Y%m%dT%H%M%S')}")
            lines.append(f"DTEND;TZID=America/New_York:{end.strftime('%Y%m%dT%H%M%S')}")
        lines.append(fold("SUMMARY:" + esc(g["title"])))
        desc = [g["teamName"] + (" (home)" if g["home"] and not g["neutral"] else " (away)" if not g["home"] else " (neutral site)")]
        if g["competition"]:
            desc.append(g["competition"] + (" · " + g["note"] if g["note"] else ""))
        if g["url"]:
            desc.append(g["url"])
        lines.append(fold("DESCRIPTION:" + esc("\n".join(desc))))
        if g["location"]:
            lines.append(fold("LOCATION:" + esc(g["location"])))
        if g["status"] in ("STATUS_CANCELED", "STATUS_CANCELLED"):
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    offline = None
    if "--offline" in sys.argv:
        offline = sys.argv[sys.argv.index("--offline") + 1]
    now = datetime.now(timezone.utc)
    teams = [t for t in load("teams.json", []) if t.get("active", True)]
    by_key = {t["key"]: t for t in load("teams.json", [])}
    prev = load("games.json", {}).get("games", [])
    games, errors = {}, []

    for t in teams:
        if not t.get("espn_id") or t.get("sport") not in SPORTS:
            continue
        cfg = SPORTS[t["sport"]]
        got, ok = 0, False
        for url in espn_urls(t, now):
            try:
                data = fetch_json(url, offline)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{t['key']}: {url.split('/schedule')[1] or 'default'} {type(e).__name__}")
                continue
            if data is None:
                continue
            ok = True
            for ev in data.get("events") or []:
                g = parse_event(ev, t, cfg)
                if g:
                    games.setdefault(g["uid"], g)
                    got += 1
        if not ok:
            # Keep what we had so a bad fetch never empties the calendar.
            for g in prev:
                if g.get("team") == t["key"] and g.get("source") == "espn":
                    games.setdefault(g["uid"], g)
            errors.append(f"{t['key']}: no data fetched, kept previous games")

    for g in manual_games(load("extra_games.json", []), by_key):
        # A manual entry on the same day as an ESPN game for that team is a duplicate.
        day = g["start"][:10]
        if any(x["team"] == g["team"] and x["start"][:10] == day for x in games.values()):
            continue
        games.setdefault(g["uid"], g)

    cutoff = now - timedelta(days=KEEP_PAST_DAYS)
    horizon = now + timedelta(days=HORIZON_DAYS)
    out = sorted((g for g in games.values() if cutoff <= datetime.fromisoformat(g["start"]) <= horizon), key=lambda g: g["start"])
    summary = {}
    for g in out:
        summary.setdefault(g["team"], 0)
        if datetime.fromisoformat(g["start"]) >= now:
            summary[g["team"]] += 1

    with open(os.path.join(ROOT, "games.ics"), "w", encoding="utf-8", newline="") as f:
        f.write(to_ics(out))
    with open(os.path.join(ROOT, "games.json"), "w", encoding="utf-8") as f:
        json.dump({"upcomingByTeam": summary,
                   "errors": errors, "games": out}, f, ensure_ascii=False, indent=1)
    print(f"{len(out)} games written; upcoming by team: {summary}")
    for e in errors:
        print("warn:", e)


if __name__ == "__main__":
    main()
