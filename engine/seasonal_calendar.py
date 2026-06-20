"""
Sprint 1 — Seasonal Calendar
=============================
1. DB migration: CREATE TABLE seasonal_calendar
2. Seed data: Bangalore · Wildlife (initial seed — expandable)
3. Helper: build_seasonal_context() — called in app.py before auto_score()

INTEGRATION POINT in app.py:
  Before each auto_score() call, call:
    seasonal_ctx = build_seasonal_context(
        db, user_city=current_user.city, primary_genre=primary_genre, current_month=datetime.utcnow().month
    )
  Then pass seasonal_ctx into auto_score() as seasonal_context= parameter.

TABLE DESIGN:
  Each row = one shooting window at one location for one genre near one city.
  month_start / month_end are inclusive (e.g. 6, 8 = June through August).
  distance_hours is driving time from base_city.
  subject is the specific subject that makes it exciting (e.g. "Black leopard").
  why_it_moves_score links to the dimension the platform wants to grow
  (always tied to the user's weakest dimension — injected at query time).
"""

import json
from datetime import datetime
from sqlalchemy import text as _sql_text

# ── City alias map ─────────────────────────────────────────────────────────
# Users type city names inconsistently (Bengaluru vs Bangalore, Bombay vs
# Mumbai, Calcutta vs Kolkata, etc). seasonal_calendar.base_city is seeded
# with one canonical spelling per city. This map normalises common variants
# to the seeded spelling at query time — no data migration needed, and it
# self-heals for every existing and future user immediately.
CITY_ALIASES = {
    "bengaluru":  "Bangalore",
    "bangalore":  "Bangalore",
    "bombay":     "Mumbai",
    "mumbai":     "Mumbai",
    "calcutta":   "Kolkata",
    "kolkata":    "Kolkata",
    "madras":     "Chennai",
    "chennai":    "Chennai",
    "mysore":     "Mysuru",
    "mysuru":     "Mysuru",
    "gurgaon":    "Gurugram",
    "gurugram":   "Gurugram",
    "trivandrum": "Thiruvananthapuram",
    "cochin":     "Kochi",
    "kochi":      "Kochi",
}


def normalize_city(city: str) -> str:
    """
    Normalise a user-entered city name to the canonical spelling used in
    seasonal_calendar.base_city. Falls back to the original (title-cased)
    string if no alias is found — so new cities work as soon as seed rows
    are added for them, no code change required.
    """
    if not city:
        return ""
    key = city.strip().lower()
    return CITY_ALIASES.get(key, city.strip())

# ── Migration SQL ──────────────────────────────────────────────────────────────
# Add to your existing migrations block in app.py's startup section.
# Pattern matches your existing ALTER TABLE / CREATE TABLE IF NOT EXISTS style.

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS seasonal_calendar (
    id              SERIAL PRIMARY KEY,
    base_city       VARCHAR(80)  NOT NULL,
    genre           VARCHAR(40)  NOT NULL,
    location_name   VARCHAR(120) NOT NULL,
    state_country   VARCHAR(80)  NOT NULL,
    distance_hours  FLOAT        NOT NULL,
    month_start     INTEGER      NOT NULL,
    month_end       INTEGER      NOT NULL,
    subject         TEXT         NOT NULL,
    what_is_happening TEXT       NOT NULL,
    why_it_matters  TEXT         NOT NULL,
    best_light_time VARCHAR(80),
    access_notes    TEXT,
    date_start      DATE,
    date_end        DATE,
    created_at      TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seasonal_city_genre
    ON seasonal_calendar (base_city, genre, month_start, month_end);
"""

# ── Item D — discovery_queue migration ──────────────────────────────────────
# (city, genre) combos awaiting auto-discovery. priority=TRUE for
# newly-detected/changed cities (item B feed) — processed before the general
# weekly sweep.

DISCOVERY_QUEUE_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS discovery_queue (
    id           SERIAL PRIMARY KEY,
    city         VARCHAR(80)  NOT NULL,
    genre        VARCHAR(40)  NOT NULL,
    priority     BOOLEAN      NOT NULL DEFAULT FALSE,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_discovery_queue_status
    ON discovery_queue (status, priority, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_discovery_queue_pending_unique
    ON discovery_queue (city, genre) WHERE status = 'pending';
"""

# ── Item C — seasonal_shown_log migration ───────────────────────────────────
# Tracks which seasonal_calendar rows have been shown to which users, so
# build_seasonal_context() can rotate through ALL matching locations instead
# of always returning the same nearest-2 (LIMIT 2) every time.

SHOWN_LOG_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS seasonal_shown_log (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    calendar_id  INTEGER NOT NULL,
    shown_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seasonal_shown_user
    ON seasonal_shown_log (user_id, shown_at);
"""

# ── Seed data ──────────────────────────────────────────────────────────────────
# Bangalore · Wildlife — initial set.
# Expand with: other cities, other genres, other months.

SEED_DATA = [
    # ── KABINI · Wildlife · June–August ──────────────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Wildlife",
        "location_name":   "Kabini Wildlife Reserve",
        "state_country":   "Karnataka, India",
        "distance_hours":  4.0,
        "month_start":     6,
        "month_end":       8,
        "subject":         "Black leopard",
        "what_is_happening": (
            "The black leopard at Kabini has been active this season. "
            "Sightings are clustering at the waterhole before 7am. "
            "The reserve is open through August."
        ),
        "why_it_matters": (
            "One of the rarest melanistic leopard subjects in India. "
            "Dawn light through the forest canopy, unpredictable movement, "
            "restricted access — precisely the combination that pushes "
            "how difficult it was higher. Your timing is your strongest "
            "dimension. This is where your next big score comes from."
        ),
        "best_light_time": "Before 7am — dawn canopy light",
        "access_notes":    "Book safari in advance. October–November also strong for leopard.",
    },
    # ── KABINI · Wildlife · November–March ────────────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Wildlife",
        "location_name":   "Kabini Wildlife Reserve",
        "state_country":   "Karnataka, India",
        "distance_hours":  4.0,
        "month_start":     11,
        "month_end":       3,
        "subject":         "Leopard and tiger",
        "what_is_happening": (
            "Leopard and tiger activity peaks November through March. "
            "Waterhole concentrates animals in the dry season — "
            "subjects come to you. Reserve is fully open."
        ),
        "why_it_matters": (
            "Dry season means animals are at the waterhole predictably. "
            "This is the window for close proximity in difficult light — "
            "exactly the situation that moves the difficulty score. "
            "Your eye is ready for it."
        ),
        "best_light_time": "Dawn and dusk — golden hour at the waterhole",
        "access_notes":    "Peak season — book early. Full-day safaris available.",
    },
    # ── RANGANATHITTU · Wildlife · October–February ───────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Wildlife",
        "location_name":   "Ranganathittu Bird Sanctuary",
        "state_country":   "Karnataka, India",
        "distance_hours":  3.0,
        "month_start":     10,
        "month_end":       2,
        "subject":         "Painted storks nesting",
        "what_is_happening": (
            "Winter migrants arrive October. Painted storks, open-billed storks, "
            "and spoonbills nesting at close range in open water light. "
            "Boat access puts you at eye level with the colony."
        ),
        "why_it_matters": (
            "Nesting behaviour at close range — chicks, feeding, courtship displays. "
            "High access, demanding timing, open water light with no harsh shadows. "
            "The combination that lifts the difficulty score while keeping "
            "your timing strength fully in play."
        ),
        "best_light_time": "Early morning — flat water light, no harsh shadows",
        "access_notes":    "Boat safari required. 2–3 hours is enough. Very close subject access.",
    },
    # ── BR HILLS · Wildlife · June–September ─────────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Wildlife",
        "location_name":   "BR Hills (Biligirirangana Hills)",
        "state_country":   "Karnataka, India",
        "distance_hours":  3.5,
        "month_start":     6,
        "month_end":       9,
        "subject":         "Elephants and sloth bears",
        "what_is_happening": (
            "Elephant herds move through the reserve in the wet season. "
            "Sloth bear sightings increase as fruiting trees come into season. "
            "Less visited than Kabini — more genuine access difficulty."
        ),
        "why_it_matters": (
            "Less visited means less habituated animals — more challenging, "
            "more unpredictable, higher genuine difficulty. "
            "Elephant herds in wet season forest light score exceptionally "
            "on the difficulty dimension. This is the less obvious choice "
            "that separates portfolios."
        ),
        "best_light_time": "Full day — wet season overcast diffuses the light",
        "access_notes":    "Book through Jungle Lodges. Less crowded than Kabini.",
    },
    # ── NAGARHOLE · Wildlife · October–May ────────────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Wildlife",
        "location_name":   "Nagarhole National Park",
        "state_country":   "Karnataka, India",
        "distance_hours":  4.5,
        "month_start":     10,
        "month_end":       5,
        "subject":         "Tiger and wild dog (Dholes)",
        "what_is_happening": (
            "Dholes — Indian wild dogs — are active in packs through the dry season. "
            "Tiger sightings consistent. Nagarhole has less tourist pressure "
            "than Kabini and better forest canopy for light quality."
        ),
        "why_it_matters": (
            "Dhole pack behaviour is one of the rarest wildlife subjects in India — "
            "coordinated hunting, pack dynamics, subject interaction. "
            "Genuinely difficult to find and photograph. "
            "The kind of access that makes a portfolio."
        ),
        "best_light_time": "Dawn and late afternoon",
        "access_notes":    "Kabini and Nagarhole share the Rajiv Gandhi National Park buffer.",
    },
    # ── STREET / DOCUMENTARY — KR MARKET · June ──────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Street",
        "location_name":   "KR Market (Krishna Rajendra Market)",
        "state_country":   "Bangalore, Karnataka, India",
        "distance_hours":  0.0,
        "month_start":     5,
        "month_end":       8,
        "subject":         "Pre-monsoon flower market",
        "what_is_happening": (
            "The pre-monsoon season brings peak flower supply to KR Market. "
            "Before 7am the market is at full activity — vendors, colour, "
            "overcast diffused light with no harsh shadows. "
            "This is the window where street light is at its most forgiving."
        ),
        "why_it_matters": (
            "Overcast pre-monsoon light removes the harshness that kills street photographs. "
            "The market is dense, layered, culturally specific. "
            "Photographs in this kind of light consistently come alive — "
            "your timing scores run higher here. One frame before breakfast."
        ),
        "best_light_time": "Before 7am — overcast, diffused, no hard shadows",
        "access_notes":    "Open from 4am. Full activity before 8am. Parking on Arcot Road.",
    },
    # ── DOCUMENTARY — DASARA · Mysuru · October ───────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Documentary",
        "location_name":   "Mysuru Dasara Procession",
        "state_country":   "Mysuru, Karnataka, India",
        "distance_hours":  3.0,
        "month_start":     10,
        "month_end":       10,
        "subject":         "Dasara elephant procession",
        "what_is_happening": (
            "The Dasara procession on Vijayadashami is one of the great photographic "
            "events in India. The decorated elephant carrying the golden howdah, "
            "torchlight procession at night, 100,000 spectators. "
            "One night only, one chance."
        ),
        "why_it_matters": (
            "Cultural access at scale — the procession requires positioning "
            "and local knowledge to photograph well. "
            "The difficulty is the access, the crowd management, the night light. "
            "Photographs from inside the crowd score higher than those from the barriers."
        ),
        "best_light_time": "Evening — torchlight and floodlit elephant",
        "access_notes":    "Vijayadashami — check Mysuru dates each year. Book accommodation early.",
    },
    # ── LANDSCAPE · Coorg · June–August ──────────────────────────────────────
    {
        "base_city":       "Bangalore",
        "genre":           "Landscape",
        "location_name":   "Coorg (Kodagu) — Abbey Falls and Raja's Seat",
        "state_country":   "Kodagu, Karnataka, India",
        "distance_hours":  4.0,
        "month_start":     6,
        "month_end":       8,
        "subject":         "Monsoon waterfalls and mist",
        "what_is_happening": (
            "Monsoon season transforms Coorg — Abbey Falls is at maximum volume, "
            "mist rolls through the coffee estates at dawn, the valley light "
            "is soft and layered. Raja's Seat gives a full valley view "
            "at first light with mist below."
        ),
        "why_it_matters": (
            "Monsoon landscape light is completely different to dry season — "
            "overcast, muted, dramatic when the clouds break. "
            "This is the window for long-exposure waterfall work and "
            "mist-in-valley photographs that don't come from a tourist brochure."
        ),
        "best_light_time": "Dawn — mist fills the valley before 8am",
        "access_notes":    "Madikeri is the base. Abbey Falls 5km. Raja's Seat in town.",
    },
]


def build_seasonal_context(db_session, user_city: str, primary_genre: str, current_month: int,
                            user_id: int | None = None) -> tuple[str, list[int]]:
    """
    Query seasonal_calendar for the user's city, primary genre, and current month.
    Returns (context_string, calendar_ids_used) — context_string is formatted
    for injection into the auto_score() prompt; calendar_ids_used should be
    passed to log_seasonal_shown() AFTER successful scoring (item C).

    Called in app.py before auto_score() on every image upload.

    Rotation (item C): instead of always returning the same nearest 2 rows
    (old LIMIT 2 behaviour — caused repeat advice like "black leopard at
    Kabini" on every upload in the same window), this queries ALL matching
    rows and prefers rows NOT shown to this user in the last 14 days. If
    fewer than 2 unseen rows exist, falls back to the least-recently-shown
    rows to fill the remainder.

    Args:
        db_session:     SQLAlchemy db.session
        user_city:      user.city — e.g. "Bangalore" (or GPS travel city)
        primary_genre:  user's primary genre interest — e.g. "Wildlife"
        current_month:  datetime.utcnow().month
        user_id:        user.id — required for rotation; if None, falls back
                         to the old nearest-2 behaviour (no rotation, no log)

    Returns:
        (formatted_string, calendar_ids) — formatted_string is "" if no
        matches; calendar_ids is [] if no matches or user_id is None.
    """
    if not user_city or not primary_genre:
        return "", []

    # Normalise city spelling (Bengaluru -> Bangalore, etc) before matching
    _normalized_city = normalize_city(user_city)

    try:
        rows = db_session.execute(
            _sql_text("""
            SELECT id, location_name, state_country, distance_hours,
                   subject, what_is_happening, why_it_matters,
                   best_light_time, access_notes, date_start, date_end
            FROM seasonal_calendar
            WHERE LOWER(base_city) = LOWER(:city)
              AND LOWER(genre)     = LOWER(:genre)
              AND (
                    -- Date-bound one-off event takes precedence when present —
                    -- governed ONLY by its actual dates, never by month_start/
                    -- month_end (which is NOT NULL in the schema and carries a
                    -- placeholder value even on date-bound rows, e.g. Photo
                    -- Today Expo: month_start=6/month_end=6 alongside
                    -- date_end=2026-06-14 — without this exclusivity, the
                    -- month check alone keeps matching all of June even after
                    -- the actual 3-day event has expired).
                    (date_start IS NOT NULL AND date_end IS NOT NULL
                     AND date_end >= CURRENT_DATE)
                    OR
                    -- Recurring window — only applies to rows that are NOT
                    -- date-bound.
                    (date_start IS NULL
                     AND month_start <= :month AND month_end >= :month)
                  )
            ORDER BY
                -- Prefer date-bound (one-off, time-sensitive) events first,
                -- then nearest by distance.
                (date_start IS NOT NULL AND date_end IS NOT NULL) DESC,
                distance_hours ASC
            """),
            {"city": _normalized_city, "genre": primary_genre, "month": current_month}
        ).fetchall()
    except Exception as e:
        print(f"[build_seasonal_context] DB error: {e}")
        return "", []

    if not rows:
        return "", []

    if user_id is None:
        # No rotation context available — old behaviour, nearest 2.
        chosen = list(rows[:2])
    else:
        # ── Item C rotation ──────────────────────────────────────────────
        try:
            shown_rows = db_session.execute(
                _sql_text("""
                SELECT calendar_id, MAX(shown_at) AS last_shown
                FROM seasonal_shown_log
                WHERE user_id = :uid
                  AND shown_at >= NOW() - INTERVAL '14 days'
                GROUP BY calendar_id
                """),
                {"uid": user_id}
            ).fetchall()
            shown_recently = {r.calendar_id: r.last_shown for r in shown_rows}
        except Exception as e:
            print(f"[build_seasonal_context] shown_log read error: {e}")
            shown_recently = {}

        unseen = [r for r in rows if r.id not in shown_recently]
        seen   = [r for r in rows if r.id in shown_recently]
        # Among seen rows, prefer the ones shown longest ago (oldest first)
        seen.sort(key=lambda r: shown_recently[r.id])

        chosen = unseen[:2]
        if len(chosen) < 2:
            chosen += seen[:2 - len(chosen)]

    if not chosen:
        return "", []

    lines = [
        f"\nSEASONAL INTELLIGENCE — {primary_genre.upper()} NEAR {user_city.upper()}:",
        "Use the following location intelligence in the mentor_location_1 and mentor_location_2 fields.",
        "This is specific to the photographer's city, genre, and current month.",
        "Write in the Sherpa voice — warm, specific, like a friend who knows the location.\n",
    ]

    for i, row in enumerate(chosen, 1):
        lines.append(f"Location {i}: {row.location_name} ({row.state_country})")
        lines.append(f"  Distance: {row.distance_hours} hours from {user_city}")
        lines.append(f"  Subject:  {row.subject}")
        lines.append(f"  Now:      {row.what_is_happening}")
        lines.append(f"  Why:      {row.why_it_matters}")
        if getattr(row, 'date_start', None) and getattr(row, 'date_end', None):
            lines.append(f"  Dates:    {row.date_start} to {row.date_end} — one-off event, mention urgency")
        if row.best_light_time:
            lines.append(f"  Light:    {row.best_light_time}")
        if row.access_notes:
            lines.append(f"  Access:   {row.access_notes}")
        lines.append("")

    lines.append(
        f"Attribution footer: "
        f"\"Based on your location ({user_city}) · Genre ({primary_genre}) · "
        f"Your growth opportunity (how difficult it was)\""
    )

    return "\n".join(lines), [row.id for row in chosen]


def log_seasonal_shown(db_session, user_id: int, calendar_ids: list[int]):
    """
    Item C — record that these seasonal_calendar rows were shown to this
    user. Call ONLY after scoring succeeds (not on failed/retried attempts —
    a failed attempt shouldn't burn a rotation slot).

    Safe to call with an empty calendar_ids list (no-op).
    """
    if not calendar_ids:
        return
    try:
        for cid in calendar_ids:
            db_session.execute(
                _sql_text(
                    "INSERT INTO seasonal_shown_log (user_id, calendar_id, shown_at) "
                    "VALUES (:uid, :cid, NOW())"
                ),
                {"uid": user_id, "cid": cid}
            )
        db_session.commit()
    except Exception as e:
        print(f"[log_seasonal_shown] error: {e}")
        db_session.rollback()


def get_location_links(db_session, calendar_ids: list[int]) -> list[dict]:
    """
    Given the seasonal_calendar IDs that were actually used for an image's
    advisory text (stored on Image.seasonal_calendar_ids_shown at scoring
    time — NOT re-derived from city/genre/month at render time, since
    rotation logic and month boundaries could select a different row than
    what the advisory paragraph actually describes), return a "go here"
    link for each.

    Prefers source_url (the real event/location page, when the discovery
    web search captured one) and falls back to an auto-generated Google
    Maps search link built from location_name + state_country, which is
    always available since every row has those fields. This means every
    advisory gets a usable link today, even before source_url is populated
    for any existing rows.

    Returns a list of {'location_name': str, 'url': str} dicts, in the same
    order as calendar_ids, so index 0 corresponds to mentor_location_1 and
    index 1 to mentor_location_2. Safe to call with an empty list (no-op).
    """
    if not calendar_ids:
        return []
    try:
        placeholders = ",".join(f":id{i}" for i in range(len(calendar_ids)))
        params = {f"id{i}": cid for i, cid in enumerate(calendar_ids)}
        rows = db_session.execute(
            _sql_text(
                f"SELECT id, location_name, state_country, source_url "
                f"FROM seasonal_calendar WHERE id IN ({placeholders})"
            ),
            params
        ).fetchall()
    except Exception as e:
        print(f"[get_location_links] lookup error: {e}")
        return []

    by_id = {r.id: r for r in rows}
    links = []
    for cid in calendar_ids:
        row = by_id.get(cid)
        if not row:
            continue
        if row.source_url:
            url = row.source_url
        else:
            from urllib.parse import quote_plus
            query = quote_plus(f"{row.location_name}, {row.state_country or ''}".strip(", "))
            url = f"https://www.google.com/maps/search/?api=1&query={query}"
        links.append({"location_name": row.location_name, "url": url})
    return links


def prune_seasonal_shown_log(db_session, days: int = 60):
    """
    Item C — delete seasonal_shown_log entries older than `days` (default 60).
    Safe to run repeatedly (idempotent). Call from a daily/weekly cron job.

    Returns the number of rows deleted, or -1 on error.
    """
    try:
        result = db_session.execute(
            _sql_text(
                "DELETE FROM seasonal_shown_log "
                "WHERE shown_at < NOW() - INTERVAL '1 day' * :days"
            ),
            {"days": days}
        )
        db_session.commit()
        return result.rowcount
    except Exception as e:
        print(f"[prune_seasonal_shown_log] error: {e}")
        db_session.rollback()
        return -1


def get_primary_genre(user) -> str:
    """
    Extract the user's primary genre from genre_interests JSON column.
    Falls back to the image's own genre if not set.

    Args:
        user: User model instance

    Returns:
        Primary genre string, e.g. "Wildlife"
    """
    genre_interests_raw = getattr(user, 'genre_interests', None)
    if genre_interests_raw:
        try:
            genres = json.loads(genre_interests_raw)
            if genres and isinstance(genres, list):
                return genres[0]
        except (json.JSONDecodeError, IndexError):
            pass
    return ""


def seed_seasonal_calendar(db_session):
    """
    Seed the seasonal_calendar table with initial data.
    Safe to run multiple times — checks for existing rows first.
    Call once from admin or migration route.
    """
    existing = db_session.execute(
        _sql_text("SELECT COUNT(*) FROM seasonal_calendar")
    ).scalar()

    if existing > 0:
        print(f"[seed_seasonal_calendar] Table already has {existing} rows — skipping seed")
        return existing

    for row in SEED_DATA:
        db_session.execute(
            _sql_text("""
            INSERT INTO seasonal_calendar
                (base_city, genre, location_name, state_country, distance_hours,
                 month_start, month_end, subject, what_is_happening,
                 why_it_matters, best_light_time, access_notes)
            VALUES
                (:base_city, :genre, :location_name, :state_country, :distance_hours,
                 :month_start, :month_end, :subject, :what_is_happening,
                 :why_it_matters, :best_light_time, :access_notes)
            """),
            row
        )

    db_session.commit()
    print(f"[seed_seasonal_calendar] Seeded {len(SEED_DATA)} rows")
    return len(SEED_DATA)


# ── Item D — date-bound event seed (proof-of-shape) ─────────────────────────
# "Photo Today Expo, Bangalore" — currently running, ends Sunday 2026-06-14
# per Session 73 handoff. Inserted independently of seed_seasonal_calendar()
# (which only runs on an empty table) since this is time-sensitive and added
# after the initial seed. Validates the date_start/date_end schema before the
# discovery job (item D v1) writes its first auto-discovered row.

DATE_BOUND_SEED_DATA = [
    {
        "base_city":       "Bangalore",
        "genre":           "Street",
        "location_name":   "Photo Today Expo",
        "state_country":   "Bangalore, Karnataka, India",
        "distance_hours":  0.0,
        "month_start":     6,
        "month_end":       6,
        "subject":         "Photography exhibition — gear, prints, talks",
        "what_is_happening": (
            "Photo Today Expo is currently running in Bangalore, with "
            "exhibitor booths, print displays, and photographer talks — "
            "ending this Sunday."
        ),
        "why_it_matters": (
            "A short window to see other photographers' work printed at "
            "scale, talk to working professionals, and get a feel for how "
            "your own images would look as prints. Worth an afternoon if "
            "you're free before it closes."
        ),
        "best_light_time": None,
        "access_notes":    "Check the expo's official page for venue, hours, and ticketing.",
        "date_start":      "2026-06-12",
        "date_end":        "2026-06-14",
    },
]


def seed_date_bound_events(db_session):
    """
    Insert DATE_BOUND_SEED_DATA rows that don't already exist (matched by
    location_name + date_end, so re-running is safe and won't duplicate).
    Returns the number of rows inserted.
    """
    inserted = 0
    for row in DATE_BOUND_SEED_DATA:
        existing = db_session.execute(
            _sql_text(
                "SELECT COUNT(*) FROM seasonal_calendar "
                "WHERE location_name = :location_name AND date_end = :date_end"
            ),
            {"location_name": row["location_name"], "date_end": row["date_end"]}
        ).scalar()
        if existing > 0:
            continue
        db_session.execute(
            _sql_text("""
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
            """),
            row
        )
        inserted += 1

    db_session.commit()
    print(f"[seed_date_bound_events] Inserted {inserted} date-bound row(s)")
    return inserted
