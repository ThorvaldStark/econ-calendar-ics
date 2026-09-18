#!/usr/bin/env python3
"""Fetch N weeks of Forex Factory calendar data (this week + future weeks).

ForexFactory's calendar page accepts ?week=mmmDD.YYYY (Sunday start) and embeds
the full event list as window.calendarComponentStates[1] JSON in the HTML.
This converts it to the same shape as the faireconomy mirror dump:
  {"title":..., "country":"USD", "date":"2026-09-27", "time":"4:50pm",
   "impact":"High", "forecast":..., "previous":...}

Usage:
  python3 fetch_ff_weeks.py [--weeks 4] [--out ff_weeks.json]
"""
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
ET = ZoneInfo("America/New_York")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]


def fetch_week(sunday: date):
    param = f"{MONTHS[sunday.month - 1]}{sunday.day}.{sunday.year}"
    url = f"https://www.forexfactory.com/calendar?week={param}"
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=40) as r:
        html = r.read().decode("utf-8", errors="replace")
    data = extract_state(html)
    if not data:
        raise RuntimeError(f"no embedded calendar data for week {param}")
    return data.get("days", [])


def js_string_decode(s):
    """Decode a JS single-quoted string literal body (without the quotes)."""
    mapping = {"'": "'", '"': '"', "\\": "\\", "/": "/",
               "n": "\n", "t": "\t", "r": "\r"}
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "'":
            break
        if ch == "\\" and i + 1 < len(s):
            out.append(mapping.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out), i + (1 if i < len(s) else 0)


def js_literal_to_json(text):
    """Convert a JS object literal to strict JSON: single-quoted strings
    become double-quoted; bare keys get quoted."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            val, adv = js_string_decode(text[i + 1:])
            out.append(json.dumps(val))
            i += 1 + adv
        elif c == '"':
            out.append(c)
            i += 1
            while i < n:
                ch = text[i]
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                i += 1
                if ch == '"':
                    break
        else:
            out.append(c)
            i += 1
    text = "".join(out)
    text = re.sub(r'([{,])\s*([A-Za-z_]\w*)\s*:', r'\1"\2":', text)
    return text


def extract_state(html):
    marker = "window.calendarComponentStates[1] = "
    i = html.find(marker)
    if i < 0:
        return None
    i += len(marker)
    while html[i] in " \t\r\n":
        i += 1
    if html[i] == "'":
        # whole state is a JS string literal holding an object literal
        text, adv = js_string_decode(html[i + 1:])
        text = js_literal_to_json(text)
    else:
        # raw object literal: brace-match it
        if html[i] != "{":
            return None
        depth, instr, esc, j = 0, False, False, i
        while j < len(html):
            c = html[j]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            else:
                if c == '"':
                    instr = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
            j += 1
        text = js_literal_to_json(html[i:j])
    # We only need the "days" array; other keys (e.g. defaultSettings with
    # Object.freeze(...) calls) are not valid JSON, so parse just the array.
    m = re.search(r'"days"\s*:', text)
    if not m:
        return None
    k = m.end()
    while text[k] in " \t\r\n":
        k += 1
    if text[k] != "[":
        return None
    depth, instr, esc, j = 0, False, False, k
    while j < len(text):
        c = text[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    j += 1
                    break
        j += 1
    return {"days": json.loads(text[k:j])}


def convert(days):
    out = []
    for day in days:
        for ev in day.get("events", []):
            cur = (ev.get("currency") or "").upper()
            if not cur:
                # site-wide events (summits etc.) have no currency
                cur = "ALL"
            dl = ev.get("dateline")
            dt_et = (datetime.fromtimestamp(dl, tz=ZoneInfo("UTC"))
                     .astimezone(ET)) if dl else None
            label = (ev.get("timeLabel") or "").strip()
            if dt_et and label and label.lower() not in (
                    "all day", "tentative", "n/a", "no time"):
                time_s = dt_et.strftime("%-I:%M%p").lower()
                date_s = dt_et.strftime("%Y-%m-%d")
            else:
                time_s = label
                # fall back to the day's date shown on the calendar
                m = re.search(r"(\w{3})\s+(\d{1,2}),\s+(\d{4})",
                              ev.get("date", ""))
                date_s = (datetime.strptime(
                    f"{m.group(1)} {m.group(2)} {m.group(3)}",
                    "%b %d %Y").strftime("%Y-%m-%d") if m
                    else (dt_et.strftime("%Y-%m-%d") if dt_et else ""))
            out.append({
                "title": (ev.get("name") or "").strip(),
                "country": cur,
                "date": date_s,
                "time": time_s,
                "impact": (ev.get("impactName") or "").capitalize(),
                "forecast": ev.get("forecast") or "",
                "previous": ev.get("previous") or "",
                "url": ("https://www.forexfactory.com" +
                        (ev.get("url") or "").split("#")[0]),
            })
    return out


def main():
    weeks = 4
    out_path = "ff_weeks.json"
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--weeks" and i + 1 < len(args):
            weeks = int(args[i + 1])
        if a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]
    today = date.today()
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    all_events = []
    for w in range(weeks):
        wk = sunday + timedelta(weeks=w)
        days = fetch_week(wk)
        evs = convert(days)
        print(f"week of {wk}: {len(evs)} events")
        all_events.extend(evs)
    # dedupe by (title, date, time)
    seen, uniq = set(), []
    for e in all_events:
        k = (e["title"].lower(), e["date"], e["time"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    with open(out_path, "w") as f:
        json.dump(uniq, f, indent=1)
    print(f"wrote {out_path} with {len(uniq)} events")


if __name__ == "__main__":
    main()
