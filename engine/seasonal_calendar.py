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
    created_at      TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seasonal_city_genre
    ON seasonal_calendar (base_city, genre, month_start, month_end);
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


def build_seasonal_context(db_session, user_city: str, primary_genre: str, current_month: int) -> str:
    """
    Query seasonal_calendar for the user's city, primary genre, and current month.
    Returns a formatted string to inject into the auto_score() prompt.

    Called in app.py before auto_score() on every image upload.

    Args:
        db_session:     SQLAlchemy db.session
        user_city:      user.city — e.g. "Bangalore"
        primary_genre:  user's primary genre interest — e.g. "Wildlife"
        current_month:  datetime.utcnow().month

    Returns:
        Formatted string for injection into SCORE_PROMPT, or "" if no matches.
    """
    if not user_city or not primary_genre:
        return ""

    try:
        rows = db_session.execute(
            """
            SELECT location_name, state_country, distance_hours,
                   subject, what_is_happening, why_it_matters,
                   best_light_time, access_notes
            FROM seasonal_calendar
            WHERE LOWER(base_city) = LOWER(:city)
              AND LOWER(genre)     = LOWER(:genre)
              AND month_start     <= :month
              AND month_end       >= :month
            ORDER BY distance_hours ASC
            LIMIT 2
            """,
            {"city": user_city, "genre": primary_genre, "month": current_month}
        ).fetchall()
    except Exception as e:
        print(f"[build_seasonal_context] DB error: {e}")
        return ""

    if not rows:
        return ""

    lines = [
        f"\nSEASONAL INTELLIGENCE — {primary_genre.upper()} NEAR {user_city.upper()}:",
        "Use the following location intelligence in the mentor_location_1 and mentor_location_2 fields.",
        "This is specific to the photographer's city, genre, and current month.",
        "Write in the Sherpa voice — warm, specific, like a friend who knows the location.\n",
    ]

    for i, row in enumerate(rows, 1):
        lines.append(f"Location {i}: {row.location_name} ({row.state_country})")
        lines.append(f"  Distance: {row.distance_hours} hours from {user_city}")
        lines.append(f"  Subject:  {row.subject}")
        lines.append(f"  Now:      {row.what_is_happening}")
        lines.append(f"  Why:      {row.why_it_matters}")
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

    return "\n".join(lines)


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
        "SELECT COUNT(*) FROM seasonal_calendar"
    ).scalar()

    if existing > 0:
        print(f"[seed_seasonal_calendar] Table already has {existing} rows — skipping seed")
        return existing

    for row in SEED_DATA:
        db_session.execute(
            """
            INSERT INTO seasonal_calendar
                (base_city, genre, location_name, state_country, distance_hours,
                 month_start, month_end, subject, what_is_happening,
                 why_it_matters, best_light_time, access_notes)
            VALUES
                (:base_city, :genre, :location_name, :state_country, :distance_hours,
                 :month_start, :month_end, :subject, :what_is_happening,
                 :why_it_matters, :best_light_time, :access_notes)
            """,
            row
        )

    db_session.commit()
    print(f"[seed_seasonal_calendar] Seeded {len(SEED_DATA)} rows")
    return len(SEED_DATA)
