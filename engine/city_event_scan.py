"""
engine/city_event_scan.py
==========================
Daily live event scanner — discovers time-bound photography-relevant events
(exhibitions, festivals, sporting events, cultural gatherings) for every city
with active uploads in the last 7 days, and writes them as event_type='live'
rows into seasonal_calendar with date_start / date_end.

ARCHITECTURE
────────────
- Runs daily via APScheduler at 20:30 UTC (02:00 IST)
- One Claude API call per active city (not per city+genre — events are
  city-wide, not genre-specific; the dashboard shows them alongside the
  genre-based seasonal advisory)
- Priority order: cities sorted by upload count in last 7 days DESC
- Cities with zero uploads in last 7 days are skipped (not scanned daily —
  they still get the weekly seasonal discovery sweep)
- Cities with a recent scan (< 20 hours ago) are skipped (idempotent)
- MAX_SCANS_PER_RUN = 1000 safety backstop — never a real constraint at
  current scale, just prevents runaway if something goes wrong
- Results written to seasonal_calendar with event_type='live', date_end set —
  rows auto-expire (suppressed at query time once date_end < today)
- Dedup: if a row with the same location_name + date_end already exists for
  the city, it is NOT inserted again (safe to re-run)

DB DEPENDENCY
─────────────
Requires the event_type column migration in app.py startup:
  ALTER TABLE seasonal_calendar ADD COLUMN IF NOT EXISTS
      event_type VARCHAR(20) DEFAULT 'seasonal';

And a city_event_scan_log table (created in app.py startup):
  CREATE TABLE IF NOT EXISTS city_event_scan_log (
      id         SERIAL PRIMARY KEY,
      city       VARCHAR(80) NOT NULL,
      scanned_at TIMESTAMP   NOT NULL DEFAULT NOW(),
      events_found INTEGER   NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_city_event_scan_log_city_at
      ON city_event_scan_log (city, scanned_at);

DASHBOARD INTEGRATION
─────────────────────
get_live_event_advisory(db_session, user_city) is called in the dashboard
route and passed as `dash_live_event` to dashboard.html.
It returns the single most imminent (earliest date_end) live event for the
city, or None if none exist. The dashboard template renders it above the
seasonal advisory when present.
"""

import os
import json
import anthropic
from datetime import datetime, timedelta, date
from sqlalchemy import text as _sql

# ── Config ────────────────────────────────────────────────────────────────────
MAX_SCANS_PER_RUN  = 1000   # safety backstop only
RESCAN_HOURS       = 20     # skip city if scanned within this window
ACTIVE_DAYS        = 7      # "active city" = upload in last N days
EVENTS_PER_CITY    = 3      # max events to write per city per scan
MODEL              = "claude-sonnet-4-6"

# ── Prompt ────────────────────────────────────────────────────────────────────
_SYSTEM = """You are a photography opportunity researcher for Shutter League,
a photography evolution platform based in India.

Your job: find current, time-bound, photography-relevant events happening
in or very near a given city in the next 30 days.

Events of interest:
- Festivals (religious, cultural, harvest) with strong visual subjects
- Photography exhibitions or photo walks
- Sporting events with spectator access
- Art exhibitions, heritage events, markets
- Natural phenomena (migrations, blooms, astronomical)

Do NOT include:
- Ongoing permanent attractions (museums, landmarks that are always there)
- Events with no public spectator access
- Events further than 2 hours drive from the city

Return ONLY a JSON array. No preamble, no markdown fences. Example shape:
[
  {
    "location_name": "Rath Yatra Procession, Puri",
    "state_country": "Puri, Odisha, India",
    "distance_hours": 0.0,
    "genre": "Street",
    "subject": "Grand chariot procession — 45-foot chariots pulled through main street",
    "what_is_happening": "Rath Yatra 2026 begins on 26 June. The three giant chariots of Jagannath, Balabhadra, and Subhadra are pulled by devotees from Jagannath Temple to Gundicha Temple — one of the world's largest religious processions.",
    "why_it_matters": "The scale, colour, and crowd density create once-a-year conditions for street and documentary photography. The pre-dawn chariot decoration and the main procession both offer distinct shooting windows.",
    "best_light_time": "Pre-dawn for chariot decoration; morning for the main pull",
    "access_notes": "Main road Bada Danda. Station yourself on a rooftop or side street for elevation. Free public access along the entire route.",
    "date_start": "2026-07-11",
    "date_end": "2026-07-20",
    "source_url": "https://www.puri.nic.in/rath-yatra"
  }
]

If there are no relevant events, return an empty array: []
Dates must be ISO format YYYY-MM-DD. Be accurate — do not invent events.
Today's date is {today}.
"""


def _get_active_cities(db_session):
    """
    Return list of (city, upload_count) tuples for cities with at least one
    upload in the last ACTIVE_DAYS days, ordered by upload_count DESC.
    Excludes NULL/empty cities.
    """
    cutoff = datetime.utcnow() - timedelta(days=ACTIVE_DAYS)
    try:
        rows = db_session.execute(_sql("""
            SELECT u.city, COUNT(i.id) AS uploads
            FROM images i
            JOIN users u ON u.id = i.user_id
            WHERE i.created_at >= :cutoff
              AND u.city IS NOT NULL
              AND TRIM(u.city) != ''
            GROUP BY u.city
            ORDER BY uploads DESC
        """), {"cutoff": cutoff}).fetchall()
        return [(r.city, r.uploads) for r in rows]
    except Exception as e:
        print(f"[city_event_scan] _get_active_cities error: {e}")
        return []


def _recently_scanned(db_session, city):
    """
    Returns True if this city was scanned within RESCAN_HOURS — prevents
    duplicate API calls when the daily cron overlaps with a manual trigger.
    """
    cutoff = datetime.utcnow() - timedelta(hours=RESCAN_HOURS)
    try:
        row = db_session.execute(_sql("""
            SELECT id FROM city_event_scan_log
            WHERE LOWER(city) = LOWER(:city)
              AND scanned_at  >= :cutoff
            LIMIT 1
        """), {"city": city, "cutoff": cutoff}).fetchone()
        return row is not None
    except Exception:
        return False


def _log_scan(db_session, city, events_found):
    try:
        db_session.execute(_sql("""
            INSERT INTO city_event_scan_log (city, scanned_at, events_found)
            VALUES (:city, NOW(), :events_found)
        """), {"city": city, "events_found": events_found})
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        print(f"[city_event_scan] _log_scan error: {e}")


def _already_exists(db_session, city, location_name, date_end):
    """Dedup check — skip insert if same location+date_end exists for this city."""
    try:
        row = db_session.execute(_sql("""
            SELECT id FROM seasonal_calendar
            WHERE LOWER(base_city)      = LOWER(:city)
              AND LOWER(location_name)  = LOWER(:location_name)
              AND date_end              = :date_end
            LIMIT 1
        """), {"city": city, "location_name": location_name, "date_end": date_end}).fetchone()
        return row is not None
    except Exception:
        return False


def _write_event(db_session, city, event):
    """
    Write one discovered event to seasonal_calendar as event_type='live'.
    Returns True on success.
    """
    try:
        # Resolve genre — default to Street for city-wide events
        genre = event.get("genre") or "Street"

        # Parse dates — must be valid ISO strings
        date_start_raw = event.get("date_start")
        date_end_raw   = event.get("date_end")
        if not date_end_raw:
            return False  # date_end is required for live events
        date_start = date_start_raw  # store as string; Postgres casts to DATE
        date_end   = date_end_raw

        # Dedup
        location_name = (event.get("location_name") or "").strip()
        if not location_name:
            return False
        if _already_exists(db_session, city, location_name, date_end):
            print(f"[city_event_scan] skip duplicate: {city} / {location_name} / {date_end}")
            return False

        db_session.execute(_sql("""
            INSERT INTO seasonal_calendar
                (base_city, genre, location_name, state_country,
                 distance_hours, month_start, month_end,
                 subject, what_is_happening, why_it_matters,
                 best_light_time, access_notes,
                 date_start, date_end, source_url, event_type)
            VALUES
                (:base_city, :genre, :location_name, :state_country,
                 :distance_hours, :month_start, :month_end,
                 :subject, :what_is_happening, :why_it_matters,
                 :best_light_time, :access_notes,
                 :date_start, :date_end, :source_url, 'live')
        """), {
            "base_city":         city,
            "genre":             genre,
            "location_name":     location_name,
            "state_country":     (event.get("state_country") or city).strip(),
            "distance_hours":    float(event.get("distance_hours") or 0.0),
            "month_start":       1,   # live events use date_start/date_end; month
            "month_end":         12,  # columns set wide so the WHERE clause
                                      # date-bound path always wins
            "subject":           (event.get("subject")           or "").strip(),
            "what_is_happening": (event.get("what_is_happening") or "").strip(),
            "why_it_matters":    (event.get("why_it_matters")    or "").strip(),
            "best_light_time":   (event.get("best_light_time")   or None),
            "access_notes":      (event.get("access_notes")      or None),
            "date_start":        date_start,
            "date_end":          date_end,
            "source_url":        (event.get("source_url")        or None),
        })
        db_session.commit()
        print(f"[city_event_scan] wrote: {city} / {location_name} / {date_end}")
        return True

    except Exception as e:
        db_session.rollback()
        print(f"[city_event_scan] _write_event error ({city}): {e}")
        return False


def scan_city(db_session, city):
    """
    Run one city scan: call Claude API, parse events, write to DB.
    Returns the number of events written.
    """
    today_str = date.today().isoformat()
    prompt = (
        f"Find photography-relevant events happening in or near {city} "
        f"in the next 30 days (from {today_str}). "
        f"Focus on events with strong visual subjects accessible to the public."
    )
    system = _SYSTEM.replace("{today}", today_str)

    try:
        client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from env
        response = client.messages.create(
            model      = MODEL,
            max_tokens = 1000,
            system     = system,
            messages   = [{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown fences if model adds them despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        events = json.loads(raw)
        if not isinstance(events, list):
            print(f"[city_event_scan] {city}: non-list response — skipping")
            return 0

    except json.JSONDecodeError as e:
        print(f"[city_event_scan] {city}: JSON parse error — {e}")
        return 0
    except Exception as e:
        print(f"[city_event_scan] {city}: API error — {e}")
        return 0

    written = 0
    for event in events[:EVENTS_PER_CITY]:
        if _write_event(db_session, city, event):
            written += 1

    _log_scan(db_session, city, written)
    print(f"[city_event_scan] {city}: {written} event(s) written")
    return written


def run_city_event_scan(db_session):
    """
    Main entry point — called by the daily APScheduler cron wrapper in app.py.
    Scans all active cities ordered by recent upload activity.
    Returns a summary dict.
    """
    active_cities = _get_active_cities(db_session)
    if not active_cities:
        print("[city_event_scan] no active cities — nothing to scan")
        return {"cities_scanned": 0, "total_events": 0}

    scanned      = 0
    total_events = 0

    for city, _upload_count in active_cities[:MAX_SCANS_PER_RUN]:
        if _recently_scanned(db_session, city):
            print(f"[city_event_scan] skip {city} — scanned within {RESCAN_HOURS}h")
            continue
        total_events += scan_city(db_session, city)
        scanned += 1

    summary = {"cities_scanned": scanned, "total_events": total_events}
    print(f"[city_event_scan] run complete: {summary}")
    return summary


# ── Dashboard helper ──────────────────────────────────────────────────────────

def get_live_event_advisory(db_session, user_city):
    """
    Called from app.py dashboard route. Returns the single most imminent
    live event for the user's city (earliest date_end that hasn't passed),
    or None if no live events exist.

    The dashboard template renders this ABOVE the seasonal advisory so the
    more urgent, time-bound signal is seen first.
    """
    if not user_city:
        return None

    from engine.seasonal_calendar import normalize_city
    city = normalize_city(user_city)

    try:
        row = db_session.execute(_sql("""
            SELECT location_name, state_country, distance_hours,
                   subject, what_is_happening, why_it_matters,
                   best_light_time, access_notes, date_start, date_end,
                   source_url, genre
            FROM seasonal_calendar
            WHERE LOWER(base_city) = LOWER(:city)
              AND event_type       = 'live'
              AND date_end        >= CURRENT_DATE
            ORDER BY date_end ASC
            LIMIT 1
        """), {"city": city}).fetchone()

        if not row:
            return None

        # Build a human-readable deadline string
        _today    = date.today()
        _end      = row.date_end
        _days_left = (_end - _today).days if _end else None
        if _days_left is not None:
            if _days_left == 0:
                deadline_label = "Ends today"
            elif _days_left == 1:
                deadline_label = "Ends tomorrow"
            elif _days_left <= 7:
                deadline_label = f"Until {_end.strftime('%d %b')}"
            else:
                deadline_label = f"Until {_end.strftime('%d %b')}"
        else:
            deadline_label = None

        from urllib.parse import quote_plus
        _q = quote_plus(f"{row.location_name}, {row.state_country or ''}".strip(", "))

        return {
            "location_name":     row.location_name,
            "state_country":     row.state_country,
            "distance_hours":    row.distance_hours,
            "subject":           row.subject,
            "what_is_happening": row.what_is_happening,
            "why_it_matters":    row.why_it_matters,
            "best_light_time":   row.best_light_time,
            "access_notes":      row.access_notes,
            "date_start":        row.date_start,
            "date_end":          row.date_end,
            "deadline_label":    deadline_label,
            "source_url":        row.source_url,
            "genre":             row.genre,
            "url":               f"https://www.google.com/maps/search/?api=1&query={_q}",
        }

    except Exception as e:
        print(f"[city_event_scan] get_live_event_advisory error: {e}")
        return None
