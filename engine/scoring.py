"""
Apex DDI Engine — core scoring module
Lens League · April 2026

Genres (8 confirmed):
  1. Wildlife       (incl. Flora & Fauna — animals, birds, marine, plants)
  2. Street
  3. Landscape
  4. People
  5. Wedding
  6. Macro
  7. Drone & Aerial
  8. Creative
"""

# ── Genre weights ─────────────────────────────────────────────────────────────
# Keys must match GENRE_LIST ids exactly.
GENRE_WEIGHTS = {
    'Wildlife':      {'dod': 0.25, 'disruption': 0.20, 'dm': 0.25, 'wonder': 0.20, 'aq': 0.10},
    'Landscape':     {'dod': 0.15, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.30},
    'Street':        {'dod': 0.15, 'disruption': 0.25, 'dm': 0.25, 'wonder': 0.15, 'aq': 0.20},
    'Wedding':       {'dod': 0.10, 'disruption': 0.15, 'dm': 0.25, 'wonder': 0.10, 'aq': 0.40},
    'People':        {'dod': 0.10, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.15, 'aq': 0.40},
    'Macro':         {'dod': 0.35, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.10},
    'Creative':      {'dod': 0.20, 'disruption': 0.30, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.15},
    'Drone & Aerial':{'dod': 0.30, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.25, 'aq': 0.10},
}

# ── Genre list (canonical — used by forms, DB, and prize logic) ───────────────
GENRE_LIST = [
    {
        'id':          'Wildlife',
        'label':       'Wildlife',
        'description': 'Wildlife, Flora & Fauna — animals, birds, insects, plants, marine life, ecosystems',
        'aliases':     ['wildlife', 'flora', 'fauna', 'nature', 'animals', 'birds', 'marine', 'underwater'],
    },
    {
        'id':          'Street',
        'label':       'Street',
        'description': 'Street — urban life, candid moments, public spaces, architecture details',
        'aliases':     ['street', 'urban', 'city', 'candid', 'documentary'],
    },
    {
        'id':          'Landscape',
        'label':       'Landscape',
        'description': 'Landscape — natural scenery, seascapes, cityscapes, astrophotography, weather',
        'aliases':     ['landscape', 'landscapes', 'seascape', 'cityscape', 'astro', 'scenery'],
    },
    {
        'id':          'People',
        'label':       'People',
        'description': 'People — portraits, lifestyle, editorial, environmental portraits, cultural',
        'aliases':     ['people', 'portrait', 'portraits', 'lifestyle', 'editorial', 'cultural'],
    },
    {
        'id':          'Wedding',
        'label':       'Wedding',
        'description': 'Wedding — ceremonies, receptions, couples, details, pre-wedding, engagement',
        'aliases':     ['wedding', 'bridal', 'ceremony', 'engagement', 'pre-wedding'],
    },
    {
        'id':          'Macro',
        'label':       'Macro',
        'description': 'Macro — extreme close-up, textures, patterns, insects at macro scale, product',
        'aliases':     ['macro', 'closeup', 'close-up', 'texture', 'pattern', 'product'],
    },
    {
        'id':          'Drone & Aerial',
        'label':       'Drone & Aerial',
        'description': "Drone & Aerial — aerial photography, drone shots, bird's eye view, elevated perspectives",
        'aliases':     ['drone', 'aerial', 'drone & aerial', 'birds eye', "bird's eye", 'uav', 'top view'],
    },
    {
        'id':          'Creative',
        'label':       'Creative',
        'description': 'Creative — conceptual, composite, fine art, abstract, experimental photography',
        'aliases':     ['creative', 'conceptual', 'composite', 'fine art', 'abstract', 'experimental'],
    },
]

# Flat list of genre ids — use for form <select> options and DB validation.
GENRE_IDS = [g['id'] for g in GENRE_LIST]


def normalise_genre(raw: str) -> str:
    """
    Map a raw genre string (from DB, form, or legacy data) to a canonical GENRE_IDS entry.
    Handles legacy renames: 'Landscapes' → 'Landscape', 'Drone' → 'Drone & Aerial'.
    Falls back to 'Wildlife' if no match found.
    """
    if not raw:
        return 'Wildlife'
    clean = raw.strip()
    # Exact match first
    if clean in GENRE_IDS:
        return clean
    # Legacy renames
    legacy = {
        'Landscapes': 'Landscape',
        'Drone':      'Drone & Aerial',
    }
    if clean in legacy:
        return legacy[clean]
    # Alias scan (case-insensitive)
    lower = clean.lower()
    for g in GENRE_LIST:
        if lower in g['aliases']:
            return g['id']
    return 'Wildlife'


# ── Prize structures ──────────────────────────────────────────────────────────

# POTY — ₹50,00,000 total
# 16 competitions: 8 genres × 2 tracks (Camera + Mobile)
# Grand POTY selected by jury from category Gold winners.
#
# Camera per category: Gold ₹1,50,000 / Silver ₹75,000 / Bronze ₹50,000 = ₹2,75,000 × 8 = ₹22L
# Mobile per category: Gold ₹75,000  / Silver ₹50,000  / Bronze ₹25,000 = ₹1,50,000 × 8 = ₹12L
# Grand POTY Camera ₹10L + Grand POTY Mobile ₹6L = ₹16L
# Total: ₹22L + ₹12L + ₹16L = ₹50L ✓
POTY_PRIZES = {
    'Camera': {
        'Gold':   150000,
        'Silver':  75000,
        'Bronze':  50000,
    },
    'Mobile': {
        'Gold':    75000,
        'Silver':  50000,
        'Bronze':  25000,
    },
    'Grand_Camera': 1000000,   # Grand POTY Camera — jury selects from 8 Camera Gold winners
    'Grand_Mobile':  600000,   # Grand POTY Mobile — jury selects from 8 Mobile Gold winners
}

# Open — ₹8,00,000 total
# No track split — Camera and Mobile compete in the same pool.
# One winner per category (no Silver/Bronze). Grand Open = best of 8 category winners, jury selected.
# Entry fee ₹50/image. Opens 3 months before Grand Prix.
#
# 8 × ₹75,000 = ₹6,00,000 + Grand Open ₹2,00,000 = ₹8,00,000 ✓
OPEN_PRIZES = {
    'Category_Winner': 75000,    # × 8 genres = ₹6,00,000
    'Grand_Open':      200000,   # jury selects from 8 category winners
    'Entry_Fee':           50,   # ₹ per image
}

OPEN_SELECTION_METHOD = (
    "Grand Open Winner is selected by jury from the 8 category winners. "
    "Camera and Mobile entries compete in the same pool. "
    "No Silver or Bronze — one winner per category."
)

OPEN_OPENS_BEFORE_GRAND_PRIX_MONTHS = 3


# ── Tier map ──────────────────────────────────────────────────────────────────
def get_tier(score: float) -> str:
    if score <= 5.0:  return 'Apprentice'
    if score <  7.6:  return 'Practitioner'
    if score <  9.0:  return 'Master'
    if score <= 9.6:  return 'Grandmaster'
    return 'Legend'


# ── Core formula ──────────────────────────────────────────────────────────────
def calculate_score(genre, dod, disruption, dm, wonder, aq):
    """
    Returns (final_score, tier, soul_bonus, checks_dict).

    genre      : raw genre string — normalised internally via normalise_genre().
    dod        : Depth of Detail score, float 0–10
    disruption : Disruption score, float 0–10
    dm         : Decisive Moment score, float 0–10
    wonder     : Wonder score, float 0–10
    aq         : Authenticity Quotient score, float 0–10
    """
    canonical = normalise_genre(genre)
    weights   = GENRE_WEIGHTS.get(canonical, GENRE_WEIGHTS['Wildlife'])
    checks    = {}
    notes     = []

    def _raw(aq_val):
        return (
            dod        * weights['dod']        +
            disruption * weights['disruption'] +
            dm         * weights['dm']         +
            wonder     * weights['wonder']     +
            aq_val     * weights['aq']
        )

    raw = _raw(aq)

    # Humanity Check: AQ < 4.0 → -1.5 penalty applied to AQ component
    if aq < 4.0:
        aq -= 1.5
        checks['humanity_check'] = True
        notes.append('Humanity Check triggered: AQ < 4.0, -1.5 applied to AQ')
        raw = _raw(aq)

    # Soul Bonus: AQ >= 8.0 → technical penalties waived
    soul_bonus = aq >= 8.0
    checks['soul_bonus'] = soul_bonus
    if soul_bonus:
        notes.append('Soul Bonus active: AQ >= 8.0, technical penalties removed')

    # Plateau Penalty: technically flawless but unchallenging composition
    if dod >= 9.5 and disruption < 5.0:
        checks['plateau_penalty'] = True
        notes.append('Plateau Penalty: DoD >= 9.5 + Disruption < 5.0, score capped at 7.9')
        raw = min(raw, 7.9)

    # Iconic Wall: scores >= 9.0 require Disruption > 8.5 AND AQ > 8.5
    if raw >= 9.0:
        if disruption <= 8.5 or aq <= 8.5:
            checks['iconic_wall_blocked'] = True
            raw = min(raw, 8.99)
            notes.append('Iconic Wall: score capped at 8.99')
        else:
            checks['iconic_wall_cleared'] = True
            notes.append('Iconic Wall cleared')

    raw = min(raw, 9.9)
    # Round to 2dp to avoid float artefacts pushing scores across tier boundaries
    final_score = round(raw, 2)
    tier        = get_tier(final_score)
    checks['notes'] = notes
    return final_score, tier, soul_bonus, checks


# ── Archetype mapping ─────────────────────────────────────────────────────────
ARCHETYPES = [
    'Sadness / Forlorn',
    'Hope / Joy',
    'Tension / Dread',
    'Wonder / Transcendence',
    'Resilient Forlorn',
    'Sovereign Momentum',
    'Compressed Tension',
    'Joyful Disruption',
    'Forlorn Transcendence',
    'Chromatic Transcendence',
    'Tender Sovereignty',
    'Primal Dread',
]


# ── Calibration stats ─────────────────────────────────────────────────────────
def compute_calibration_stats(images):
    """
    Takes a list of image model instances (with .genre, .score, .dod_score,
    .disruption_score, .dm_score, .wonder_score, .aq_score attributes).
    Returns a dict keyed by canonical genre id.
    """
    from collections import defaultdict
    genre_buckets = defaultdict(list)

    for img in images:
        if img.score is not None:
            key = normalise_genre(img.genre)
            genre_buckets[key].append(img)

    stats = {}
    for genre, imgs in genre_buckets.items():
        n = len(imgs)
        stats[genre] = {
            'count':      n,
            'avg_score':  round(sum(i.score              for i in imgs) / n, 2),
            'avg_dod':    round(sum(i.dod_score          for i in imgs) / n, 2),
            'avg_dis':    round(sum(i.disruption_score   for i in imgs) / n, 2),
            'avg_dm':     round(sum(i.dm_score           for i in imgs) / n, 2),
            'avg_wonder': round(sum(i.wonder_score       for i in imgs) / n, 2),
            'avg_aq':     round(sum(i.aq_score           for i in imgs) / n, 2),
        }
    return stats
