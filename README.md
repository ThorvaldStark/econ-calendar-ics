# Econ Data — all US economic releases as a calendar feed

`econ.ics` is an auto-generated ICS feed of **every** US economic data release
(jobs data, CPI, FOMC, retail sales, jobless claims, housing, sentiment — all
impact levels, not just the market-moving ones).

## Subscribe (Google Calendar)

Add calendar → From URL:

```
https://thorvaldstark.github.io/econ-calendar-ics/econ.ics
```

It refreshes on its own — no maintenance needed. No alarms; it's a quiet
reference layer. Pair it with a high-signal calendar for the events that
actually move markets.

## How it's built

- `build_ics.py` merges a long-horizon backbone of major releases with the
  weekly Forex Factory feed dump (all USD events, every impact level).
- Event UIDs are stable, so re-subscribes update in place instead of
  duplicating.
- Regenerated weekly by an automated job.
