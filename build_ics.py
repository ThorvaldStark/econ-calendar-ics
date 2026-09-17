#!/usr/bin/env python3
"""Build econ.ics — every US economic release as a reference calendar feed.

Sources merged (deduped by stable UID):
  1. ~/workspace/markets-calendar/econ_schedule.json — major releases through Dec 2026
     (fallback/long-horizon backbone).
  2. ff_thisweek.json (optional) — this week's full Forex Factory feed dump
     (all USD events, every impact level). Fetch via browser:
     https://nfs.faireconomy.media/ff_calendar_thisweek.json
     (direct VM fetches are CDN-blocked; the browser route works).

Output: econ.ics in this directory. Events are 15-minute FYI markers in
America/New_York, no alarms. UIDs are stable (sha1 of title+date+time) so
Google Calendar updates in place instead of duplicating on re-subscribe.

Usage:
  python3 build_ics.py [--ff ff_thisweek.json] [--out econ.ics]
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ECON_SCHEDULE = Path.home() / "workspace" / "markets-calendar" / "econ_schedule.json"
ET = ZoneInfo("America/New_York")

CAL_NAME = "Econ Data"


def uid_for(title: str, date: str, time: str) -> str:
    h = hashlib.sha1(f"{title}|{date}|{time}".lower().encode()).hexdigest()[:16]
    return f"{h}@thorvaldstark-econ-ics"


def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                 .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> str:
    # ICS lines must be <= 75 octets; fold longer ones.
    out = []
    while len(line.encode("utf-8")) > 75:
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def parse_ff_time(date_s: str, time_s: str):
    """Return (all_day, datetime_in_ET or date)."""
    t = (time_s or "").strip()
    if not t or t.lower() in ("all day", "tentative", "n/a"):
        return True, datetime.strptime(date_s, "%Y-%m-%d").date()
    m = re.match(r"(\d{1,2}):(\d{2})\s*([ap]m)?", t, re.I)
    if not m:
        return True, datetime.strptime(date_s, "%Y-%m-%d").date()
    hh, mm, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ap == "pm" and hh != 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    return False, datetime.strptime(date_s, "%Y-%m-%d").replace(
        hour=hh, minute=mm, tzinfo=ET)


def collect():
    events = {}  # uid -> dict
    now = datetime.now(timezone.utc)

    # 1) backbone: major releases from econ_schedule.json
    try:
        sched = json.loads(ECON_SCHEDULE.read_text())
        for r in sched.get("releases", []):
            date_s = r.get("date", "")
            time_s = r.get("time_et", "08:30")
            title = r.get("title", "").strip()
            if not date_s or not title:
                continue
            all_day, dt = parse_ff_time(date_s, time_s)
            uid = uid_for(title, date_s, time_s)
            events[uid] = {
                "uid": uid, "title": title, "all_day": all_day, "dt": dt,
                "impact": "High",
                "desc": f"{title}\nSource: {r.get('url', '')}".strip(),
                "stamp": now,
            }
    except FileNotFoundError:
        pass

    # 2) this week's full FF dump (all USD events, any impact)
    ff_path = None
    for i, a in enumerate(sys.argv):
        if a == "--ff" and i + 1 < len(sys.argv):
            ff_path = sys.argv[i + 1]
    if ff_path and Path(ff_path).exists():
        raw = json.loads(Path(ff_path).read_text())
        items = raw if isinstance(raw, list) else raw.get("events", raw.get("data", []))
        for ev in items:
            if not isinstance(ev, dict):
                continue
            country = str(ev.get("country", "")).upper()
            if country not in ("USD", "US", "USA"):
                continue
            title = str(ev.get("title", "")).strip()
            date_s = str(ev.get("date", ""))[:10]
            time_s = str(ev.get("time", ""))
            if not title or not date_s:
                continue
            impact = str(ev.get("impact", "")).capitalize() or "Unknown"
            all_day, dt = parse_ff_time(date_s, time_s)
            uid = uid_for(title, date_s, time_s if not all_day else "allday")
            desc_lines = [title, f"Impact: {impact}"]
            if ev.get("forecast"):
                desc_lines.append(f"Forecast: {ev['forecast']}")
            if ev.get("previous"):
                desc_lines.append(f"Previous: {ev['previous']}")
            desc_lines.append("Source: Forex Factory economic calendar")
            if ev.get("url"):
                desc_lines.append(str(ev["url"]))
            events[uid] = {
                "uid": uid, "title": title, "all_day": all_day, "dt": dt,
                "impact": impact, "desc": "\n".join(desc_lines), "stamp": now,
            }

    return sorted(events.values(),
                  key=lambda e: (e["dt"].isoformat()
                                 if isinstance(e["dt"], datetime)
                                 else e["dt"].isoformat()))


def to_ics(events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             f"PRODID:-//ThorvaldStark//Econ Data//EN",
             f"X-WR-CALNAME:{CAL_NAME}", "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H"]
    for e in events:
        stamp = e["stamp"].strftime("%Y%m%dT%H%M%SZ")
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}",
                  f"DTSTAMP:{stamp}"]
        if e["all_day"]:
            lines.append(f"DTSTART;VALUE=DATE:{e['dt'].strftime('%Y%m%d')}")
        else:
            start = e["dt"].strftime("%Y%m%dT%H%M%S")
            end = (e["dt"] + timedelta(minutes=15)).strftime("%Y%m%dT%H%M%S")
            lines += [f"DTSTART;TZID=America/New_York:{start}",
                      f"DTEND;TZID=America/New_York:{end}"]
        lines += [f"SUMMARY:{esc(e['title'])}",
                  f"DESCRIPTION:{esc(e['desc'])}",
                  "TRANSP:TRANSPARENT", "STATUS:CONFIRMED", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    out = HERE / "econ.ics"
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out = Path(sys.argv[i + 1])
    events = collect()
    out.write_text(to_ics(events))
    print(f"wrote {out} with {len(events)} events")


if __name__ == "__main__":
    main()
