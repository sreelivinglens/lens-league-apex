"""
Item D — Seasonal Calendar Auto-Discovery Engine
==================================================

Replaces manual per-city seed data (Chennai/Mumbai/Navi Mumbai/Paris etc.)
with an engine-generated, worldwide-scalable, self-refreshing pipeline:

  1. enqueue_missing_combos() — for every (city, genre) combo that an active
     user actually has (city from user.city — populated via items A/B, or
     the Active Location toggle; genre from user.genre_interests, up to 3
     per user), check seasonal_calendar:
       - No rows yet           -> enqueue (general sweep).
       - Newest row older than
         refresh_after_days     -> enqueue for re-discovery, so newly
         (default 30)              announced exhibitions/festivals get
                                    picked up over time — a combo is never
                                    "covered forever" after its first run.
       - Fresh enough           -> skip.

  2. run_seasonal_discovery() — weekly cron entry point. Processes priority
     queue items first (new/changed cities from item B / Active Location),
     then a bounded batch of general items (cost control). For each, calls
     discover_one().

  3. discover_one(city, genre) — the core unit:
       - web_search for recurring wildlife/nature seasons AND any one-off
         photography exhibitions/expos/festivals currently running or
         upcoming near `city`, relevant to `genre`.
       - LLM-extract the results into 1-2 seasonal_calendar rows (same shape
         as SEED_DATA in seasonal_calendar.py — including optional
         date_start/date_end for one-off events).
       - Prune this combo's EXPIRED one-off events (date_end < today) before
         inserting fresh discoveries — prevents unbounded accumulation of
         stale dated rows across repeated refresh cycles. Recurring-season
         rows (no dates) are left alone.
       - Insert the row(s), mark the discovery_queue item 'done' (or 'error').

COST NOTE: each discover_one() call is 1 web_search + 1 LLM extraction call.
run_seasonal_discovery()'s batch_size controls how many general items run per
week — keep this small while validating, raise as active-city count grows.
With the staleness refresh, every active (city, genre) combo will be
re-checked roughly every `refresh_after_days`, spread across weekly batches.
"""

import os
import json
import urllib.request
from datetime import datetime, date
from sqlalchemy import text as _sql_text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _anthropic_call(messages, tools=None, max_tokens=1500, model="claude-haiku-4-5-20251001"):
    """
    Minimal direct call to the Anthropic Messages API — same pattern as the
    watermark check in app.py (urllib, no SDK dependency). Returns the parsed
    response dict, or raises on error.
    """
    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY not set')

    payload = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': messages,
    }
    if tools:
        payload['tools'] = tools

    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _extract_text_blocks(response):
    """Concatenate all text blocks in an Anthropic API response."""
    return '\n'.join(
        block.get('text', '')
        for block in response.get('content', [])
        if block.get('type') == 'text'
    )


def get_active_city_genre_combos(db_session):
    """
    Returns a sorted list of distinct (city, genre) tuples across all users
    with a populated city and at least one genre interest.

    Uses up to 3 genres from genre_interests (the handoff flagged that only
    genre_interests[0] was being used elsewhere — this uses all of them,
    since a user's seasonal advice should cover all their stated interests).
    Falls back to no genre (skipped) if genre_interests is empty/invalid.
    """
    combos = set()
    try:
        rows = db_session.execute(_sql_text(
            "SELECT city, genre_interests FROM users "
            "WHERE city IS NOT NULL AND city != ''"
        )).fetchall()
    except Exception as e:
        print(f"[seasonal_discovery] get_active_city_genre_combos error: {e}")
        return []

    for row in rows:
        city = (row.city or '').strip()
        if not city:
            continue
        try:
            genres = json.loads(row.genre_interests) if row.genre_interests else []
        except (json.JSONDecodeError, TypeError):
            genres = []
        for genre in genres[:3]:
            genre = (genre or '').strip()
            if genre:
                combos.add((city, genre))

    return sorted(combos)


def enqueue_missing_combos(db_session, refresh_after_days: int = 30):
    """
    For each active (city, genre) combo, check whether seasonal_calendar
    has data, AND whether that data is still fresh.

    - No rows at all          -> enqueue (general sweep).
    - Newest row older than
      `refresh_after_days`     -> enqueue (general sweep) for re-discovery,
                                   so new one-off exhibitions/festivals get
                                   picked up over time rather than the combo
                                   being "covered forever" after its first
                                   discovery run.
    - Newest row fresh enough -> skip.

    Safe to run repeatedly: the partial unique index on
    discovery_queue(city, genre) WHERE status='pending' prevents duplicates,
    and discover_one() prunes stale rows for the combo before inserting new
    ones (see discover_one).

    Returns the number of new queue entries created.
    """
    from .seasonal_calendar import normalize_city, GENRE_FALLBACK

    combos = get_active_city_genre_combos(db_session)
    enqueued = 0

    for city, genre in combos:
        # Session 98: genres that always redirect to a fallback genre
        # (Wedding, Fashion -> People) never need their own discovery —
        # build_seasonal_context() never even reaches an empty result for
        # them, so queuing a search that can structurally never succeed
        # just burns API cost for nothing.
        _rule = GENRE_FALLBACK.get(genre)
        if _rule and _rule[0] == "replace":
            continue

        normalized = normalize_city(city)
        try:
            newest = db_session.execute(_sql_text(
                "SELECT MAX(created_at) FROM seasonal_calendar "
                "WHERE LOWER(base_city) = LOWER(:city) AND LOWER(genre) = LOWER(:genre)"
            ), {"city": normalized, "genre": genre}).scalar()

            if newest is not None:
                age_days = (datetime.utcnow() - newest).days
                if age_days < refresh_after_days:
                    continue  # fresh enough — skip

            db_session.execute(_sql_text(
                "INSERT INTO discovery_queue (city, genre, priority, status) "
                "VALUES (:city, :genre, FALSE, 'pending') "
                "ON CONFLICT (city, genre) WHERE status = 'pending' DO NOTHING"
            ), {"city": normalized, "genre": genre})
            enqueued += 1
        except Exception as e:
            print(f"[seasonal_discovery] enqueue error for ({city}, {genre}): {e}")
            db_session.rollback()
            continue

    db_session.commit()
    print(f"[seasonal_discovery] Enqueued {enqueued} (city, genre) combo(s) for discovery/refresh")
    return enqueued


def enqueue_priority_combo(db_session, city: str, genre: str):
    """
    Item B hook — call when a user's GPS-detected city has been flagged
    (pending_location_update set, or confirmed via /location-update/confirm)
    and that city has no seasonal_calendar data yet. Inserts a
    priority=TRUE discovery_queue row so it's processed before the next
    general sweep, rather than waiting for the weekly batch.
    """
    from .seasonal_calendar import normalize_city
    normalized = normalize_city(city)

    try:
        existing = db_session.execute(_sql_text(
            "SELECT COUNT(*) FROM seasonal_calendar "
            "WHERE LOWER(base_city) = LOWER(:city) AND LOWER(genre) = LOWER(:genre)"
        ), {"city": normalized, "genre": genre}).scalar()

        if existing > 0:
            return False  # already have data — nothing to queue

        db_session.execute(_sql_text(
            "INSERT INTO discovery_queue (city, genre, priority, status) "
            "VALUES (:city, :genre, TRUE, 'pending') "
            "ON CONFLICT (city, genre) WHERE status = 'pending' "
            "DO UPDATE SET priority = TRUE"
        ), {"city": normalized, "genre": genre})
        db_session.commit()
        print(f"[seasonal_discovery] Priority-queued ({normalized}, {genre})")
        return True
    except Exception as e:
        print(f"[seasonal_discovery] enqueue_priority_combo error: {e}")
        db_session.rollback()
        return False


# ── Discovery extraction prompt ─────────────────────────────────────────────

_EXTRACTION_SYSTEM = """You are a research assistant for a photography platform. \
Given web search results about a city and photography genre, extract 1-2 \
shooting opportunities as a JSON array. Each item must have this exact shape:

{
  "location_name": "<specific place name>",
  "state_country": "<state/region, country>",
  "distance_hours": <float, driving hours from the base city; 0.0 if within the city>,
  "subject": "<short phrase — the specific subject/scene that makes it worth shooting>",
  "what_is_happening": "<2-3 sentences, present tense, what's happening now/seasonally there>",
  "why_it_matters": "<2-3 sentences — why this is a worthwhile photographic opportunity for this genre>",
  "best_light_time": "<short phrase or null>",
  "access_notes": "<practical access info, or null>",
  "month_start": <integer 1-12 — for RECURRING seasonal windows, the start month>,
  "month_end": <integer 1-12 — for RECURRING seasonal windows, the end month>,
  "date_start": "<YYYY-MM-DD or null — ONLY for one-off dated events (exhibitions, festivals with specific dates)>",
  "date_end": "<YYYY-MM-DD or null — ONLY for one-off dated events>"
}

RULES:
- If the opportunity is a RECURRING SEASONAL pattern (e.g. a bird migration, a wildlife season), \
set month_start/month_end to the typical window and set date_start/date_end to null.
- If the opportunity is a ONE-OFF DATED EVENT (e.g. a specific exhibition or festival with known \
dates), set date_start/date_end to the actual dates (YYYY-MM-DD) and set month_start/month_end \
to the month of the event (both equal to that month).
- Only include opportunities you have reasonable confidence in based on the search results — \
do not invent specific dates or locations not supported by the results.
- If nothing relevant is found, return an empty JSON array: []
- Respond with ONLY the JSON array — no markdown formatting, no commentary, no code fences.
"""


def discover_one(db_session, city: str, genre: str, current_month: int | None = None):
    """
    Run discovery for a single (city, genre) combo:
      1. Web search for recurring seasons + current/upcoming exhibitions.
      2. LLM-extract into seasonal_calendar row(s).
      3. Insert the row(s).

    current_month: if provided (1-12), the search and extraction are scoped to
    what is happening NOW — the extracted rows are guaranteed to cover this month.
    Pass datetime.utcnow().month from the scoring thread for on-demand discovery.

    Session 98:
      - Wedding/Fashion always return 0 immediately — they never have a
        standalone location concept (see GENRE_FALLBACK in
        seasonal_calendar.py), so a search for "wedding locations near
        {city}" would just waste a web-search + LLM-extraction call on a
        query that can't structurally succeed. This is a defensive
        backstop; enqueue_missing_combos() already keeps them out of the
        weekly queue, but discover_one() can also be called directly
        (e.g. on-demand discovery from the scoring thread).
      - Documentary's search additionally covers breaking/current civic
        events (protests, demonstrations, newsworthy gatherings), not just
        scheduled exhibitions and recurring seasons.
      - Drone's search explicitly excludes restricted/no-fly airspace, and
        its extraction is required to append a regulation-verification
        reminder to access_notes — drone law varies by country and
        changes over time, so a suggested spot is never asserted as
        cleared to fly.

    Returns the number of rows inserted (0 on no results or error — never
    raises, so a single bad combo doesn't break the batch).
    """
    from .seasonal_calendar import normalize_city, GENRE_FALLBACK
    import calendar as _cal

    _rule = GENRE_FALLBACK.get(genre)
    if _rule and _rule[0] == "replace":
        print(f"[seasonal_discovery] Skipping discovery for '{genre}' — "
              f"no standalone location concept, always falls back to {_rule[1]}")
        return 0

    normalized_city = normalize_city(city)
    _month_name = _cal.month_name[current_month] if current_month else ''
    _genre_lower = genre.lower()

    try:
        # ── Step 1: web search ────────────────────────────────────────────
        _month_clause = (
            f"currently happening in {_month_name} near "
            if _month_name else
            "recurring wildlife/nature photography seasons near "
        )
        _extra_scope = ""
        if _genre_lower == "documentary":
            _extra_scope = (
                " Also search for any significant current civic events, protests, "
                "demonstrations, or newsworthy public gatherings happening in or near "
                f"{normalized_city} right now — these are valid Documentary subjects, "
                "not just scheduled exhibitions."
            )
        elif _genre_lower == "drone":
            _extra_scope = (
                " IMPORTANT: only suggest locations that are clearly outside "
                "restricted or no-fly airspace (airports, military installations, "
                "government buildings, international borders) — do not suggest a "
                "specific restricted zone even if it would be photogenic."
            )
        search_resp = _anthropic_call(
            messages=[{
                'role': 'user',
                'content': (
                    f"Search for: {_month_clause}"
                    f"{normalized_city}, AND any photography exhibitions, expos, or "
                    f"festivals currently running or upcoming in {normalized_city}, "
                    f"relevant to {genre} photography."
                    f"{_extra_scope}"
                )
            }],
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            max_tokens=2000,
        )
        search_summary = _extract_text_blocks(search_resp)
        if not search_summary.strip():
            print(f"[seasonal_discovery] No search summary for ({normalized_city}, {genre}) — skipping")
            return 0

        # ── Step 2: LLM extraction into seasonal_calendar row shape ───────
        _month_rule = (
            f"\nCRITICAL: This discovery is for month {current_month} ({_month_name}). "
            f"Every extracted row MUST have month_start <= {current_month} AND month_end >= {current_month} "
            f"so it is immediately visible to users shooting this month. "
            f"If a season runs June–September, set month_start=6, month_end=9. "
            f"Do not set month_start to a future month."
            if current_month else ''
        )
        _drone_extraction_rule = (
            "\nDRONE-SPECIFIC RULE: every extracted item's access_notes MUST end "
            "with a reminder to verify current local drone regulations and confirm "
            "the specific spot is NOT in restricted/no-fly airspace before flying — "
            "drone law varies by country and changes over time, never assert a "
            "location is cleared to fly."
            if _genre_lower == "drone" else ''
        )
        extraction_resp = _anthropic_call(
            messages=[{
                'role': 'user',
                'content': (
                    f"{_EXTRACTION_SYSTEM}{_month_rule}{_drone_extraction_rule}\n\n"
                    f"Base city: {normalized_city}\n"
                    f"Genre: {genre}\n"
                    f"Current month: {_month_name} (month {current_month})\n" if current_month else
                    f"{_EXTRACTION_SYSTEM}{_drone_extraction_rule}\n\n"
                    f"Base city: {normalized_city}\n"
                    f"Genre: {genre}\n"
                )
                + f"Current date: {date.today().isoformat()}\n\n"
                + f"Search results:\n{search_summary[:6000]}"
            }],
            max_tokens=1500,
        )
        extraction_text = _extract_text_blocks(extraction_resp).strip()
        extraction_text = extraction_text.lstrip('`').lstrip('json').strip('`').strip()

        try:
            items = json.loads(extraction_text)
        except json.JSONDecodeError as e:
            print(f"[seasonal_discovery] JSON parse error for ({normalized_city}, {genre}): {e}")
            print(f"[seasonal_discovery] Raw extraction: {extraction_text[:500]}")
            return 0

        if not isinstance(items, list) or not items:
            print(f"[seasonal_discovery] No items extracted for ({normalized_city}, {genre})")
            return 0

        # ── Step 2.5: prune expired one-off events for this combo ─────────
        # Re-discovery runs would otherwise accumulate stale dated rows
        # (e.g. last quarter's exhibition) forever. Recurring-season rows
        # (date_start/date_end NULL) are left alone — they're evergreen.
        try:
            db_session.execute(_sql_text("""
                DELETE FROM seasonal_calendar
                WHERE LOWER(base_city) = LOWER(:city) AND LOWER(genre) = LOWER(:genre)
                  AND date_start IS NOT NULL AND date_end IS NOT NULL
                  AND date_end < CURRENT_DATE
            """), {"city": normalized_city, "genre": genre})
        except Exception as prune_err:
            print(f"[seasonal_discovery] prune error for ({normalized_city}, {genre}): {prune_err}")

        # ── Step 3: insert rows ────────────────────────────────────────────
        inserted = 0
        for item in items[:2]:  # cap at 2 rows per combo
            try:
                db_session.execute(_sql_text("""
                    INSERT INTO seasonal_calendar
                        (base_city, genre, location_name, state_country, distance_hours,
                         month_start, month_end, subject, what_is_happening,
                         why_it_matters, best_light_time, access_notes,
                         date_start, date_end)
                    VALUES
                        (:base_city, :genre, :location_name, :state_country, :distance_hours,
                         :month_start, :month_end, :subject, :what_is_happening,
                         :why_it_matters, :best_light_time, :access_notes,
                         :date_start, :date_end)
                """), {
                    "base_city":         normalized_city,
                    "genre":             genre,
                    "location_name":     item.get("location_name", "")[:120],
                    "state_country":     item.get("state_country", "")[:80],
                    "distance_hours":    float(item.get("distance_hours", 0.0) or 0.0),
                    "month_start":       int(item.get("month_start", 1) or 1),
                    "month_end":         int(item.get("month_end", 12) or 12),
                    "subject":           item.get("subject", ""),
                    "what_is_happening": item.get("what_is_happening", ""),
                    "why_it_matters":    item.get("why_it_matters", ""),
                    "best_light_time":   item.get("best_light_time") or None,
                    "access_notes":      item.get("access_notes") or None,
                    "date_start":        item.get("date_start") or None,
                    "date_end":          item.get("date_end") or None,
                })
                inserted += 1
            except Exception as item_err:
                print(f"[seasonal_discovery] row insert error for ({normalized_city}, {genre}): {item_err}")
                continue

        db_session.commit()
        print(f"[seasonal_discovery] Discovered {inserted} row(s) for ({normalized_city}, {genre})")
        return inserted

    except Exception as e:
        print(f"[seasonal_discovery] discover_one error for ({city}, {genre}): {e}")
        db_session.rollback()
        return 0


def run_seasonal_discovery(db_session, batch_size: int = 5):
    """
    Weekly cron entry point.

      1. enqueue_missing_combos() — refresh the queue with any newly active
         (city, genre) combos that don't have seasonal data yet.
      2. Process ALL pending priority items (item B — new/changed cities;
         normally very few per week).
      3. Process up to `batch_size` pending general items.

    Each processed item is marked 'done' (rows inserted, even if 0 — a
    confirmed "nothing found" still counts as processed so it doesn't get
    re-queued every week) or 'error' (exception — eligible for retry next
    week since it stays out of 'pending'... actually marked 'error' so it
    won't auto-retry; re-enqueue manually if needed).

    Returns a summary dict.
    """
    enqueue_missing_combos(db_session)

    summary = {"priority_processed": 0, "general_processed": 0, "rows_inserted": 0, "errors": 0}

    def _process(row):
        nonlocal summary
        try:
            n = discover_one(db_session, row.city, row.genre, current_month=datetime.utcnow().month)
            status = 'done'
            summary["rows_inserted"] += n
        except Exception as e:
            print(f"[seasonal_discovery] unexpected error processing queue id={row.id}: {e}")
            status = 'error'
            summary["errors"] += 1

        try:
            db_session.execute(_sql_text(
                "UPDATE discovery_queue SET status = :status, processed_at = NOW() "
                "WHERE id = :id"
            ), {"status": status, "id": row.id})
            db_session.commit()
        except Exception as e:
            print(f"[seasonal_discovery] failed to update queue id={row.id}: {e}")
            db_session.rollback()

    # Priority items — all of them
    try:
        priority_rows = db_session.execute(_sql_text(
            "SELECT id, city, genre FROM discovery_queue "
            "WHERE status = 'pending' AND priority = TRUE "
            "ORDER BY created_at ASC"
        )).fetchall()
    except Exception as e:
        print(f"[seasonal_discovery] priority queue read error: {e}")
        priority_rows = []

    for row in priority_rows:
        _process(row)
        summary["priority_processed"] += 1

    # General items — bounded batch
    try:
        general_rows = db_session.execute(_sql_text(
            "SELECT id, city, genre FROM discovery_queue "
            "WHERE status = 'pending' AND priority = FALSE "
            "ORDER BY created_at ASC LIMIT :limit"
        ), {"limit": batch_size}).fetchall()
    except Exception as e:
        print(f"[seasonal_discovery] general queue read error: {e}")
        general_rows = []

    for row in general_rows:
        _process(row)
        summary["general_processed"] += 1

    print(f"[seasonal_discovery] Run complete: {summary}")
    return summary
