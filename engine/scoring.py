"""
Apex DDI Engine — core scoring module
Shutter League · May 2026

Genres (10 confirmed):
  1. Wildlife       — Animals in natural behaviour
  2. Nature         — Plants, fungi, ecosystems, weather, natural phenomena
  3. Landscape      — Land, sea, sky as the primary subject
  4. Street         — Human life in public spaces
  5. People         — Portraits, faces, human expression
  6. Wedding        — Ceremonies and celebrations
  7. Macro          — Extreme close-up — any subject
  8. Drone          — Aerial photography
  9. Creative       — Technique-driven, abstract, artistic intent
 10. Documentary    — Witnessed events, conditions, and stories
"""

# ── Genre weights ─────────────────────────────────────────────────────────────
# Keys must match GENRE_LIST ids exactly.
GENRE_WEIGHTS = {
    'Wildlife':    {'dod': 0.25, 'disruption': 0.15, 'dm': 0.30, 'wonder': 0.20, 'aq': 0.10},
    'Nature':      {'dod': 0.20, 'disruption': 0.15, 'dm': 0.20, 'wonder': 0.30, 'aq': 0.15},
    'Landscape':   {'dod': 0.20, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.25, 'aq': 0.20},
    'Street':      {'dod': 0.15, 'disruption': 0.25, 'dm': 0.25, 'wonder': 0.15, 'aq': 0.20},
    'Wedding':     {'dod': 0.10, 'disruption': 0.15, 'dm': 0.25, 'wonder': 0.10, 'aq': 0.40},
    'People':      {'dod': 0.10, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.15, 'aq': 0.40},
    'Macro':       {'dod': 0.35, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.10},
    'Creative':    {'dod': 0.20, 'disruption': 0.30, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.15},
    'Drone':       {'dod': 0.30, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.25, 'aq': 0.10},
    'Documentary': {'dod': 0.20, 'disruption': 0.20, 'dm': 0.25, 'wonder': 0.25, 'aq': 0.10},
    # Legacy key — kept for backward compat with existing DB rows
    'Drone & Aerial': {'dod': 0.30, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.25, 'aq': 0.10},
}

# ── Genre list (canonical — used by forms, DB, and prize logic) ───────────────
GENRE_LIST = [
    {
        'id':          'Wildlife',
        'label':       'Wildlife',
        'description': 'Animals in natural behaviour — birds, mammals, reptiles, insects, marine life',
        'aliases':     ['wildlife', 'fauna', 'animals', 'birds', 'marine', 'underwater'],
    },
    {
        'id':          'Nature',
        'label':       'Nature',
        'description': 'Plants, fungi, ecosystems, weather, rivers, night sky, coral — the living natural world',
        'aliases':     ['nature', 'flora', 'botanical', 'plants', 'fungi', 'weather', 'ecosystem', 'astro'],
    },
    {
        'id':          'Landscape',
        'label':       'Landscape',
        'description': 'Land, sea, sky — place as the primary subject. Seascapes, cityscapes, long exposure',
        'aliases':     ['landscape', 'landscapes', 'seascape', 'cityscape', 'scenery'],
    },
    {
        'id':          'Street',
        'label':       'Street',
        'description': 'Human life in public spaces — candid moments, urban energy, decisive moment',
        'aliases':     ['street', 'urban', 'city', 'candid'],
    },
    {
        'id':          'People',
        'label':       'People',
        'description': 'Portraits, faces, human expression — emotional connection is the primary signal',
        'aliases':     ['people', 'portrait', 'portraits', 'lifestyle', 'editorial', 'cultural'],
    },
    {
        'id':          'Wedding',
        'label':       'Wedding',
        'description': 'Ceremonies, receptions, couples, candid moments — genuine emotion scores highest',
        'aliases':     ['wedding', 'bridal', 'ceremony', 'engagement', 'pre-wedding'],
    },
    {
        'id':          'Macro',
        'label':       'Macro',
        'description': 'Extreme close-up — any subject. Pen nibs, fabric, insects, water droplets, crystals',
        'aliases':     ['macro', 'closeup', 'close-up', 'texture', 'pattern'],
    },
    {
        'id':          'Drone',
        'label':       'Drone',
        'description': 'Aerial photography — patterns from altitude, perspectives impossible from ground',
        'aliases':     ['drone', 'aerial', 'drone & aerial', 'birds eye', "bird's eye", 'uav', 'top view'],
    },
    {
        'id':          'Creative',
        'label':       'Creative',
        'description': 'Technique-driven or artistic intent — ICM, long exposure, abstract, experimental',
        'aliases':     ['creative', 'conceptual', 'composite', 'fine art', 'abstract', 'experimental'],
    },
    {
        'id':          'Documentary',
        'label':       'Documentary',
        'description': 'Witnessed events and conditions — health, birth, environment, social issues, crisis',
        'aliases':     ['documentary', 'doc', 'photojournalism', 'reportage', 'social'],
    },
]

# Flat list of genre ids — use for form <select> options and DB validation.
GENRE_IDS = [g['id'] for g in GENRE_LIST]

# Display labels keyed by id — use in templates: {{ genre_labels[img.genre] }}
GENRE_LABELS = {g['id']: g['label'] for g in GENRE_LIST}
# Legacy label compat
GENRE_LABELS['Drone & Aerial'] = 'Drone'
GENRE_LABELS['Landscapes']     = 'Landscape'

# List of (id, label) tuples — use for <select> dropdowns that need both
GENRE_CHOICES = [(g['id'], g['label']) for g in GENRE_LIST]


# ── Sub-genre definitions ──────────────────────────────────────────────────────
# Only genres listed here will show a secondary dropdown on the upload form.
# sub_types: list of (id, label) tuples — id stored in images.sub_genre column.
SUBGENRE_MAP = {
    'Wildlife': [
        # ── Birds ──────────────────────────────────────────────────────────────
        ('bird_in_flight',         'Bird – In Flight'),
        ('bird_behaviour',         'Bird – Predation / Behaviour'),
        ('bird_family',            'Bird – Family / Juvenile'),
        ('bird_migration',         'Bird – Migration / Murmuration'),
        # ── Mammals ────────────────────────────────────────────────────────────
        ('mammal_behaviour',       'Mammal – Behaviour / Conflict'),
        ('mammal_family',          'Mammal – Family / Juvenile'),
        ('mammal_migration',       'Mammal – Migration / Herd'),
        ('primate_behaviour',      'Primate – Social / Behaviour'),
        ('bat_behaviour',          'Bat – Behaviour / Emergence'),
        # ── Aquatic / Marine ───────────────────────────────────────────────────
        ('dolphin_behaviour',      'Dolphin / Cetacean – Behaviour'),
        ('marine',                 'Marine / Underwater'),
        ('marine_migration',       'Marine – Migration / Shoaling'),
        # ── Reptiles & Amphibians ──────────────────────────────────────────────
        ('reptile_amphibian',      'Reptile / Amphibian – Behaviour'),
        # ── Invertebrates ──────────────────────────────────────────────────────
        ('butterfly_behaviour',    'Butterfly / Insect – Behaviour'),
        ('invertebrate_behaviour', 'Invertebrate – Behaviour'),
        # ── Environmental / Contextual ─────────────────────────────────────────
        ('animals_in_environment', 'Animal in Habitat / Environment'),
        ('urban_wildlife',         'Urban Wildlife'),
        ('animal_portrait',        'Animal Portrait'),
        ('macro_wildlife',         'Macro Wildlife'),
    ],
    'Nature': [
        ('nature_flora',       'Flowers and Plants'),
        ('nature_fungi',       'Fungi and Mosses'),
        ('nature_ecosystem',   'Forests and Ecosystems'),
        ('nature_weather',     'Weather – Storms, Lightning, Fog'),
        ('nature_water',       'Rivers, Waterfalls and Water'),
        ('nature_astro',       'Night Sky and Astronomy'),
        ('nature_underwater',  'Underwater and Coral'),
        ('nature_seasons',     'Seasons and Natural Change'),
    ],
    'Landscape': [
        ('landscape_mountain', 'Mountains and Highlands'),
        ('landscape_coast',    'Coastline and Seascape'),
        ('landscape_desert',   'Desert and Arid'),
        ('landscape_urban',    'Urban Skyline'),
        ('landscape_rural',    'Rural and Agricultural'),
        ('landscape_longexp',  'Long Exposure'),
        ('landscape_minimal',  'Minimalist'),
    ],
    'Street': [
        ('street_candid_single', 'Single Candid Subject'),
        ('street_crowd',         'Crowd and Urban Energy'),
        ('street_night',         'Night Street'),
        ('street_architecture',  'Architecture Detail'),
        ('street_market',        'Market and Commerce'),
        ('street_transport',     'Transport and Movement'),
    ],
    'People': [
        ('portrait_posed',    'Portrait – Posed / Studio'),
        ('portrait_cultural', 'Portrait – Cultural / Documentary'),
        ('portrait_candid',   'Portrait – Candid / Street'),
        ('lifestyle',         'Lifestyle / Editorial'),
        ('event_ceremony',    'Event / Ceremony'),
        ('people_children',   'Children'),
    ],
    'Wedding': [
        ('wedding_ceremony',   'Ceremony'),
        ('wedding_couple',     'Couple Portrait'),
        ('wedding_reception',  'Reception and Celebration'),
        ('wedding_candid',     'Candid Moments'),
    ],
    'Macro': [
        ('macro_living',   'Living Subjects – Insects, Eyes, Skin'),
        ('macro_natural',  'Natural Objects – Flowers, Seeds, Crystals'),
        ('macro_manmade',  'Man-made Objects – Pen Nibs, Fabric, Circuits'),
        ('macro_water',    'Water – Droplets, Splashes, Bubbles'),
        ('macro_texture',  'Texture and Surface'),
        ('macro_optical',  'Light and Optical Phenomena'),
    ],
    'Drone': [
        ('drone_landscape', 'Landscape from Above'),
        ('drone_urban',     'Urban and Architecture'),
        ('drone_pattern',   'Patterns and Geometry'),
        ('drone_coastal',   'Coastal and Water'),
        ('drone_wildlife',  'Wildlife from Above'),
    ],
    'Creative': [
        ('creative_icm',        'ICM and Intentional Blur'),
        ('creative_longexp',    'Long Exposure and Light Trails'),
        ('creative_multiexp',   'Multiple Exposure'),
        ('creative_abstract',   'Abstract and Pattern'),
        ('creative_astro',      'Astrophotography'),
        ('creative_silhouette', 'Silhouette and Shadow'),
    ],
    'Documentary': [
        ('doc_environment', 'Environment and Climate'),
        ('doc_urban',       'City Systems and Urban Life'),
        ('doc_health',      'Health and Medicine'),
        ('doc_birth',       'Birth and New Life'),
        ('doc_social',      'Social Issues – Poverty, Hunger, Displacement'),
        ('doc_community',   'Community and Culture'),
        ('doc_crisis',      'Crisis and Emergency'),
    ],
}

# Flat validation set — all valid sub_genre values across all genres.
VALID_SUBGENRES = {sg_id for sgs in SUBGENRE_MAP.values() for sg_id, _ in sgs}


def get_subgenres(genre: str) -> list:
    """
    Returns list of (id, label) tuples for a genre, or [] if none defined.
    Use to populate the conditional sub-genre <select> on upload.html.
    """
    return SUBGENRE_MAP.get(genre, [])


def normalise_genre(raw: str) -> str:
    """
    Map a raw genre string (from DB, form, or legacy data) to a canonical GENRE_IDS entry.
    Handles legacy renames and aliases.
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
        'Landscapes':    'Landscape',
        'Drone & Aerial': 'Drone',
        'Drone':         'Drone',
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
# 20 competitions: 10 genres × 2 tracks (Camera + Mobile)
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
    if score <  4.0:  return 'Rookie'
    if score <  5.0:  return 'Shooter'
    if score <  6.0:  return 'Contender'
    if score <  7.0:  return 'Craftsman'
    if score <  8.0:  return 'Maverick'
    if score <  9.0:  return 'Master'
    if score <  9.7:  return 'Grandmaster'
    return 'Legend'


# ── Core formula ──────────────────────────────────────────────────────────────
def calculate_score(genre, dod, disruption, dm, wonder, aq):
    """
    Returns (final_score, tier, soul_bonus, checks_dict).

    genre      : raw genre string — normalised internally via normalise_genre().
    dod        : Depth of Difficulty score, float 0–10
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


# ── Global Percentile Engine ──────────────────────────────────────────────────
def compute_percentile(score: float, genre: str = None) -> dict:
    """
    Returns percentile position and comparison benchmarks for a scored image.

    Queries the DB at call time — import is deferred to avoid circular imports.
    Returns {} (empty dict) on any failure; template silently skips the block.

    Keys returned:
        top_pct         : int   — e.g. 12  means "Top 12%"
        platform_avg    : float — mean score across ALL scored images
        master_avg      : float — mean score for Master tier images
        grandmaster_avg : float — mean score for Grandmaster tier images
        top10_in_genre  : float — avg of top-10 scores in same genre (or None)
        genre           : str   — canonical genre used for genre query
        context         : str   — one-line adaptive sentence for display
        total_scored    : int   — total scored images on platform
    """
    try:
        from models import Image as ImageModel   # deferred — avoids circular import

        scored = ImageModel.query.filter(
            ImageModel.status == 'scored',
            ImageModel.score.isnot(None),
            ImageModel.is_flagged.isnot(True),
            ImageModel.needs_review.isnot(True),
        ).with_entities(ImageModel.score, ImageModel.genre).all()

        if not scored:
            return {}

        all_scores = [float(r.score) for r in scored]
        total = len(all_scores)

        # How many images score BELOW this one → percentile rank
        below = sum(1 for s in all_scores if s < score)
        top_pct = max(1, round((1 - below / total) * 100))
        rank = total - below  # 1 = best

        platform_avg = round(sum(all_scores) / total, 2)

        master_scores = [s for s in all_scores if 8.0 <= s < 9.0]
        master_avg = round(sum(master_scores) / len(master_scores), 2) if master_scores else None

        gm_scores = [s for s in all_scores if s >= 9.0]
        grandmaster_avg = round(sum(gm_scores) / len(gm_scores), 2) if gm_scores else None

        # Top-10 in same genre
        canonical = normalise_genre(genre) if genre else None
        genre_scores = sorted(
            [float(r.score) for r in scored if normalise_genre(r.genre) == canonical],
            reverse=True
        ) if canonical else []
        top10_in_genre = round(sum(genre_scores[:10]) / len(genre_scores[:10]), 2) if len(genre_scores) >= 3 else None

        # Adaptive context sentence — no pool size mention
        if top_pct <= 5:
            context = "Elite territory — your score puts you among the highest rated on this platform."
        elif top_pct <= 15:
            context = "You're scoring at a high level — well above the platform average."
        elif top_pct <= 35:
            context = "Above average — keep refining your craft to close the gap to Master tier."
        else:
            context = "Every rescore is a chance to move up — focus on Disruption and AQ to climb."

        return {
            'top_pct':         top_pct,
            'rank':            rank,
            'platform_avg':    platform_avg,
            'master_avg':      master_avg,
            'grandmaster_avg': grandmaster_avg,
            'top10_in_genre':  top10_in_genre,
            'genre':           canonical,
            'context':         context,
            'total_images':    total,
            'genre_images':    len(genre_scores),
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[compute_percentile] {e}')
        return {}
