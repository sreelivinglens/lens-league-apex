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
    "bengaluru":  "Bengaluru",
    "bangalore":  "Bengaluru",
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


# ── Genre fallback map (Session 98) ─────────────────────────────────────────
# Not every genre has a standalone "go shoot here" location concept:
#   - Wedding/Fashion are commissioned, private events — there is no public
#     "wedding location" to suggest. Both genres exist to hone the same
#     underlying skill (light, expression, working with a human subject),
#     so they ALWAYS redirect straight to the People pool — never query
#     themselves, never burn a discovery cycle on a search that can't
#     structurally succeed.
#   - Macro and Nature sit between two other genres rather than owning a
#     dedicated place of their own. They try their own genre first (real
#     Macro/Nature rows always win when they exist), and only widen to the
#     fallback genres when nothing dedicated has been found yet.
#   - Creative is a technique, not a subject — multi-exposure, light
#     painting, long exposure apply equally well to a leopard at a
#     reserve or a flower market. It never filters by genre at all.
#
# mode 'replace'    -> always query the fallback genres instead of this one
# mode 'supplement' -> query this genre first; widen to fallback if empty
# mode 'any'        -> no genre filter at all, match every genre in the city
GENRE_FALLBACK = {
    "Wedding":  ("replace",    ["People"]),
    "Fashion":  ("replace",    ["People"]),
    "Macro":    ("supplement", ["Wildlife", "Landscape"]),
    "Nature":   ("supplement", ["Wildlife", "Landscape"]),
    "Creative": ("any",        []),
}

# Genres whose location pool is nationwide rather than city-day-trip-bound —
# wildlife photography is inherently a travel genre, and a leopard reserve
# four states away is still more useful than nothing.
NATIONWIDE_GENRES = {"Wildlife"}


def _genre_query_plan(primary_genre: str):
    """
    Returns an ordered list of genre "attempts" to run against
    seasonal_calendar — each attempt is either a list of genre strings
    (matched with genre IN (...)) or None (no genre filter at all).
    The caller tries each attempt in order and stops at the first one that
    returns rows, so a genre with real dedicated data always wins over its
    fallback, and a genre with no standalone concept (Wedding, Fashion)
    never wastes a query attempt on itself.
    """
    rule = GENRE_FALLBACK.get(primary_genre)
    if not rule:
        return [[primary_genre]]
    mode, fallback_genres = rule
    if mode == "any":
        return [None]
    if mode == "replace":
        return [fallback_genres]
    if mode == "supplement":
        return [[primary_genre], fallback_genres]
    return [[primary_genre]]


def _query_calendar_rows(db_session, city, genres, current_month, country=None):
    """
    Core seasonal_calendar lookup, shared by build_seasonal_context() and
    get_dashboard_advisory(). Pass exactly one of `city` (normal local
    match) or `country` (Wildlife's nationwide widening, Session 98) —
    `genres=None` means no genre filter at all (Creative).

    Returns raw SQLAlchemy result rows (with .id, .base_city,
    .location_name, .state_country, .distance_hours, .subject,
    .what_is_happening, .why_it_matters, .best_light_time, .access_notes,
    .date_start, .date_end), ordered date-bound-first then nearest.
    Returns [] on any DB error rather than raising — a bad lookup should
    never break scoring.
    """
    where = [
        """(
            (date_start IS NOT NULL AND date_end IS NOT NULL AND date_end >= CURRENT_DATE)
            OR (date_start IS NULL AND month_start <= :month AND month_end >= :month)
        )"""
    ]
    params = {"month": current_month}

    if city:
        where.append("LOWER(base_city) = LOWER(:city)")
        params["city"] = city
    elif country:
        # state_country is stored as "[City,] State, Country" — country is
        # always the last comma-separated segment regardless of how many
        # precede it, so this is reliable without a dedicated schema column.
        where.append("LOWER(SPLIT_PART(state_country, ',', -1)) = LOWER(:country)")
        params["country"] = country.strip()

    if genres:
        placeholders = ",".join(f":g{i}" for i in range(len(genres)))
        where.append(f"LOWER(genre) IN ({placeholders})")
        for i, g in enumerate(genres):
            params[f"g{i}"] = g.lower()

    sql = f"""
        SELECT id, base_city, location_name, state_country, distance_hours,
               subject, what_is_happening, why_it_matters, best_light_time,
               access_notes, date_start, date_end
        FROM seasonal_calendar
        WHERE {' AND '.join(where)}
        ORDER BY
            (date_start IS NOT NULL AND date_end IS NOT NULL) DESC,
            distance_hours ASC
    """
    try:
        return db_session.execute(_sql_text(sql), params).fetchall()
    except Exception as e:
        print(f"[seasonal_calendar] query error: {e}")
        return []

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
    # ── DRONE · Nandi Hills sunrise · June–September (monsoon clouds) ────────
    # Session 98: Drone is city-proximate like Street/Landscape, but the
    # subject matter is weather-phenomena-led (clouds, light, river bends)
    # rather than landmark-led, and every Drone row's access_notes MUST
    # carry a regulation-verification reminder — see discover_one() in
    # seasonal_discovery.py for the same rule applied to auto-discovered
    # Drone rows.
    {
        "base_city":       "Bangalore",
        "genre":           "Drone",
        "location_name":   "Nandi Hills",
        "state_country":   "Karnataka, India",
        "distance_hours":  1.5,
        "month_start":     6,
        "month_end":       9,
        "subject":         "Sunrise above the cloud line, monsoon cloud formations",
        "what_is_happening": (
            "Monsoon cloud cover sits below the hilltop at sunrise through "
            "September, with the surrounding valley and reservoir visible "
            "between cloud breaks — a genuine above-the-clouds vantage less "
            "than two hours out, not a remote expedition."
        ),
        "why_it_matters": (
            "Aerial cloud-layer light is rare without altitude, and Nandi Hills "
            "gives it from a short, ordinary drive-out — geometric cloud "
            "patterns and shifting valley light reward an early start."
        ),
        "best_light_time": "Sunrise, before the cloud layer burns off — arrive in the dark",
        "access_notes": (
            "Open public hill station, no special permit for the location "
            "itself. VERIFY CURRENT LOCAL DRONE REGULATIONS AND CONFIRM "
            "NON-RESTRICTED AIRSPACE before flying — rules change and vary "
            "by state; this note does not constitute clearance to fly."
        ),
    },
]


def _distance_phrase(hours: float, place: str) -> str:
    """
    Convert a raw distance_hours float + reference city into a natural
    language distance description for the LLM prompt.

    Feeding the model a clean phrase here — rather than the raw float —
    means it doesn't have to interpret a number on its own. That's what
    produced "is 0.0 hours from you right now" in the generated copy when
    distance_hours was 0.0: the prompt said "Distance: 0.0 hours from
    {city}" and the model transcribed it almost verbatim instead of writing
    something like "zero travel time".
    """
    if hours <= 0.05:
        return f"zero — the photographer is already there, right in {place}, no travel needed"
    if hours < 1:
        minutes = round(hours * 60)
        return f"about {minutes} minutes from {place}"
    if hours == int(hours):
        n = int(hours)
        return f"about {n} hour{'s' if n != 1 else ''} from {place}"
    return f"about {hours:g} hours from {place}"


def build_seasonal_context(db_session, user_city: str, primary_genre: str, current_month: int,
                            user_id: int | None = None, user_country: str = "") -> tuple[str, list[int]]:
    """
    Query seasonal_calendar for the user's city, primary genre, and current month.
    Returns (context_string, calendar_ids_used) — context_string is formatted
    for injection into the auto_score() prompt; calendar_ids_used should be
    passed to log_seasonal_shown() AFTER successful scoring (item C).

    Called in app.py before auto_score() on every image upload.

    Session 98 — genre fallback, nationwide Wildlife, event-cluster display:
      - Genres with no standalone "go shoot here" concept (Wedding, Fashion)
        query their fallback genre directly instead of themselves. Genres
        that sit between two others (Macro, Nature) try their own genre
        first, then widen to the fallback genres if nothing dedicated
        exists yet. Creative has no genre filter at all. See
        GENRE_FALLBACK / _genre_query_plan() above.
      - Wildlife additionally widens to the user's whole country (via
        user_country) when their own city has no rows — wildlife
        photography is inherently a travel genre. Cross-city matches are
        captioned against their OWN base_city, not the user's, since
        distance_hours is only meaningful relative to the row's seed city.
      - Display count: normally surfaces exactly ONE location. Only widens
        to up to THREE when genuinely concurrent date-bound events exist
        this week — a real cluster, not the routine recurring-season case
        — so a quiet week gets one strong recommendation and a busy week
        isn't throttled down to one when three things are expiring.

    Rotation (item C): for the normal single-location case, prefers rows
    NOT shown to this user in the last 14 days, falling back to the
    least-recently-shown row if everything available has been seen
    recently. Rotation is skipped for a genuine date-bound event cluster —
    urgency overrides repeat-avoidance; an expiring event shouldn't be
    hidden just because it was mentioned a few days ago.

    Args:
        db_session:     SQLAlchemy db.session
        user_city:      user.city — e.g. "Bangalore" (or GPS travel city)
        primary_genre:  user's primary genre interest — e.g. "Wildlife"
        current_month:  datetime.utcnow().month
        user_id:        user.id — required for rotation; if None, falls back
                         to the old nearest-1 behaviour (no rotation, no log)
        user_country:   user.country — only used to widen Wildlife search
                         nationwide when the user's own city has no rows.
                         Optional; Wildlife simply stays city-scoped if omitted.

    Returns:
        (formatted_string, calendar_ids) — formatted_string is "" if no
        matches; calendar_ids is [] if no matches or user_id is None.
    """
    if not user_city or not primary_genre:
        return "", []

    # Normalise city spelling (Bangalore -> Bengaluru, etc) before matching
    _normalized_city = normalize_city(user_city)

    rows = []
    for _genre_attempt in _genre_query_plan(primary_genre):
        rows = _query_calendar_rows(db_session, _normalized_city, _genre_attempt, current_month)
        if rows:
            break

    # ── Wildlife: widen nationwide if the user's own city has nothing ──────
    _is_cross_city = False
    if not rows and primary_genre in NATIONWIDE_GENRES and user_country:
        rows = _query_calendar_rows(db_session, None, [primary_genre], current_month,
                                     country=user_country)
        _is_cross_city = True

    if not rows:
        return "", []

    # ── Split into date-bound (one-off, expiring) vs recurring windows ──────
    date_bound = [r for r in rows if getattr(r, 'date_start', None) and getattr(r, 'date_end', None)]
    recurring  = [r for r in rows if not (getattr(r, 'date_start', None) and getattr(r, 'date_end', None))]

    if len(date_bound) >= 2:
        # A genuine cluster of concurrent time-sensitive events — show all
        # of them (capped at 3), nearest first. No rotation suppression
        # here: an expiring event shouldn't be hidden for having been
        # shown recently.
        chosen = sorted(date_bound, key=lambda r: r.distance_hours)[:3]
    else:
        # Normal case — exactly one location. Prefer a live date-bound
        # event over a recurring window if both exist, otherwise rotate
        # through recurring rows so the same spot doesn't repeat every
        # upload.
        pool = date_bound + recurring
        if user_id is None:
            chosen = pool[:1]
        else:
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

            unseen = [r for r in pool if r.id not in shown_recently]
            seen   = [r for r in pool if r.id in shown_recently]
            # Among seen rows, prefer the ones shown longest ago (oldest first)
            seen.sort(key=lambda r: shown_recently[r.id])
            chosen = (unseen + seen)[:1]

    if not chosen:
        return "", []

    _location_field_note = (
        "mentor_location_1, mentor_location_2, and mentor_location_3 fields "
        "(mentor_location_3 only if THREE locations are listed below)"
        if len(chosen) > 1 else
        "mentor_location_1 field only — leave mentor_location_2 and "
        "mentor_location_3 as null, there is only one location this time"
    )

    lines = [
        f"\nSEASONAL INTELLIGENCE — {primary_genre.upper()} NEAR {user_city.upper()}:",
        f"Use the following location intelligence in the {_location_field_note}.",
        "This is specific to the photographer's city, genre, and current month.",
        "Write in the Sherpa voice — warm, specific, like a friend who knows the location.\n",
    ]

    for i, row in enumerate(chosen, 1):
        lines.append(f"Location {i}: {row.location_name} ({row.state_country})")
        if _is_cross_city or row.base_city.lower() != _normalized_city.lower():
            lines.append(
                f"  Distance: {_distance_phrase(row.distance_hours, row.base_city)} "
                f"— this is a trip from {user_city}, not a local outing; say so"
            )
        else:
            lines.append(f"  Distance: {_distance_phrase(row.distance_hours, user_city)}")
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


def get_dashboard_advisory(db_session, user_city: str, primary_genre: str, current_month: int) -> dict | None:
    """
    Lightweight version of build_seasonal_context() for the dashboard's
    "Shooting near you" widget — returns the single nearest match as plain
    display fields instead of an AI-prompt string. No rotation/dedup logic
    (unlike build_seasonal_context, which avoids repeating the same advice
    across uploads) since this is just a glanceable sidebar widget, not the
    image scorecard, and isn't logged to seasonal_shown_log.

    Session 98: uses the same genre fallback plan as build_seasonal_context()
    (Wedding/Fashion -> People, Macro/Nature -> Wildlife/Landscape, Creative
    -> any genre) so the dashboard widget never goes empty for a genre with
    no standalone location concept. Does not widen Wildlife nationwide —
    this widget stays city-local by design.

    Returns None if no match (city/genre have no calendar rows this month) —
    the dashboard template falls back to its existing generic placeholder.
    """
    if not user_city or not primary_genre:
        return None
    _normalized_city = normalize_city(user_city)

    rows = []
    for _genre_attempt in _genre_query_plan(primary_genre):
        rows = _query_calendar_rows(db_session, _normalized_city, _genre_attempt, current_month)
        if rows:
            break
    if not rows:
        return None
    row = rows[0]

    from urllib.parse import quote_plus
    _q = quote_plus(f"{row.location_name}, {row.state_country or ''}".strip(", "))
    return {
        'location_name':     row.location_name,
        'state_country':     row.state_country,
        'distance_hours':    row.distance_hours,
        'genre':             row.genre,
        'what_is_happening': row.what_is_happening,
        'url':               f"https://www.google.com/maps/search/?api=1&query={_q}",
    }



# ── Sherpa advisory cache (in-process, per user, 6-hour TTL) ─────────────────
import threading as _threading
import time as _time
_advisory_cache = {}
_advisory_cache_lock = _threading.Lock()
_ADVISORY_TTL = 6 * 3600  # 6 hours


def get_personalised_advisory(
    db_session,
    user_city: str,
    primary_genre: str,
    current_month: int,
    progress_data: dict | None = None,
    user_id: int | None = None,
) -> dict | None:
    """
    Sherpa-voiced location advisory personalised to the user's DDI profile.

    Wraps get_dashboard_advisory() with a single Claude call that rewrites
    what_is_happening and why_it_matters in the Sherpa voice, targeting:

      1. The GAP SHOT   — directly addresses the user's weakest DDI dimension
                          at this specific location. Unconventional, exact.
      2. The STRETCH SHOT — a technique that elevates a dimension they're
                          already decent at. Slow shutter, ND filter, bokeh,
                          etc. Something requiring deliberate craft.
      3. THE PROGRESSION LINE — one sentence connecting this location to
                          their upload history. "You got slow shutter right
                          at Chidambaram — 7.6. Here's how this gets to Master."

    Falls back to the unmodified get_dashboard_advisory() result if:
      - progress_data is None (< 5 images, no profile yet)
      - Claude call fails for any reason
      - Cached result exists and is < 6 hours old

    The template dict shape is identical to get_dashboard_advisory() —
    no template changes needed.
    """
    # ── Base advisory from DB ─────────────────────────────────────────────
    base = get_dashboard_advisory(db_session, user_city, primary_genre, current_month)
    if not base:
        return None

    # ── No profile yet — return base advisory unchanged ───────────────────
    if not progress_data:
        return base

    # ── Cache check ───────────────────────────────────────────────────────
    _cache_key = f"{user_id}:{user_city}:{primary_genre}:{current_month}"
    with _advisory_cache_lock:
        _cached = _advisory_cache.get(_cache_key)
        if _cached and (_time.time() - _cached['ts']) < _ADVISORY_TTL:
            return _cached['data']

    # ── Build DDI profile string ──────────────────────────────────────────
    _dim_labels = {
        'dod': 'Depth of Difficulty',
        'disruption': 'Disruption',
        'dm': 'Decisive Moment',
        'wonder': 'Wonder',
        'aq': 'Affective Quotient',
    }
    _weakest  = progress_data.get('weakest', '')
    _strongest = progress_data.get('strongest', '')
    _avgs     = progress_data.get('dim_avgs') or progress_data.get('avgs') or {}
    _count    = progress_data.get('count', 0)
    _avg_tier = progress_data.get('avg_tier', '')
    _top_genre = progress_data.get('top_genre', primary_genre)

    _dim_profile = '\n'.join([
        f"  {_dim_labels.get(d, d)}: {v:.2f}"
        for d, v in sorted(_avgs.items(), key=lambda x: x[1])
    ]) if _avgs else "  No dimension data available"

    # ── Recent upload context for progression line ────────────────────────
    _trend = progress_data.get('trend', [])
    _recent_context = ""
    if _trend and len(_trend) >= 2:
        _last = _trend[-1]
        _prev = _trend[-2]
        _recent_context = (
            f"Their last scored image: {_last.get('tier','')} {_last.get('score','')}. "
            f"Previous: {_prev.get('tier','')} {_prev.get('score','')}."
        )

    # ── Sherpa prompt ─────────────────────────────────────────────────────
    _system = """You are the Sherpa — the coaching voice of Shutter League, a photography evolution platform.

Your job: write a personalised location advisory for a specific photographer at a specific location.
The advisory has THREE parts, written as flowing prose (not bullet points, not headers):

PART 1 — THE GAP SHOT
Target the photographer's WEAKEST DDI dimension at this exact location.
Be specific to the location. Name the exact vantage point, the exact moment, the exact angle.
This is not generic advice — it is what THIS photographer needs to fix at THIS location.
Never say "try to" or "you might want to" — say what to do and where to stand.

PART 2 — THE STRETCH SHOT  
Suggest one technique challenge that elevates a dimension they are already decent at.
Think: slow shutter on moving subjects, ND filter in harsh light, bokeh on ambient light sources,
silhouette against a bright background, reflections, shadow play.
Be specific to what is physically present at this location right now.
Name the technique, the subject, and what the resulting image should feel like.

PART 3 — THE PROGRESSION LINE
One sentence only. Connect this location/event to their history and trajectory.
If the event is more than 30 days away: make this a preparation arc —
what they should be practising between now and then to be ready.
Example: "Holi in Mathura is 11 weeks away — your Disruption needs to move
from 7.2 to 8.0 before you walk into that crowd, and the next 8 weeks of
street practice in your city is how you get there."
If the event is immediate: connect it to their recent scores.
Example: "You got slow shutter right at Chidambaram — 7.6. Bada Danda gets that to Master."
Sound like a coach who has been watching them for months — because the platform has.

TONE: Quiet. Confident. Honest. Never encouraging for its own sake.
Never use: "wonderful", "amazing", "great opportunity", "beautiful", "stunning".
Never hedge. Never say "consider" or "perhaps" or "you might".
Write in second person ("you", "your").
Total length: 120–160 words maximum. Dense. Every word earns its place."""

    _user_prompt = f"""Photographer profile:
- Current standing: {_avg_tier} ({_count} images evaluated)
- Primary genre: {_top_genre}
- Dimension scores (lowest to highest):
{_dim_profile}
- Weakest dimension: {_dim_labels.get(_weakest, _weakest)}
- Strongest dimension: {_dim_labels.get(_strongest, _strongest)}
- {_recent_context}

Location: {base.get('location_name', '')}, {base.get('state_country', '')}
What is happening: {base.get('what_is_happening', '')}
Genre context: {primary_genre}

Write the three-part Sherpa advisory for this photographer at this location.
Return ONLY the advisory text — no labels, no headers, no preamble."""

    try:
        import os
        import json
        import httpx as _httpx

        _resp = _httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 400,
                "system":     _system,
                "messages":   [{"role": "user", "content": _user_prompt}],
            },
            timeout=20,
        )
        _resp.raise_for_status()
        _sherpa_text = _resp.json()["content"][0]["text"].strip()

        # Split into what_is_happening (gap + stretch) and why_it_matters (progression)
        # Split on last sentence (progression line is always the last sentence)
        _sentences = [s.strip() for s in _sherpa_text.replace('\n', ' ').split('.') if s.strip()]
        if len(_sentences) >= 2:
            _progression = _sentences[-1] + '.'
            _main = '. '.join(_sentences[:-1]) + '.'
        else:
            _main = _sherpa_text
            _progression = ''

        _result = {
            **base,
            'what_is_happening': _main,
            'why_it_matters':    _progression,
            'sherpa':            True,
        }

        # Cache it
        with _advisory_cache_lock:
            _advisory_cache[_cache_key] = {'data': _result, 'ts': _time.time()}

        return _result

    except Exception as _e:
        print(f"[personalised_advisory] Claude call failed ({user_city}, {primary_genre}): {_e}")
        # Fall back to base advisory — never break the dashboard
        return base


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
