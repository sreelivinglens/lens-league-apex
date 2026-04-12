"""
Apex DDI Engine — core scoring module
Lens League · April 2026
"""

# ── Genre weights ─────────────────────────────────────────────────────────────
GENRE_WEIGHTS = {
    'Wildlife':   {'dod': 0.25, 'disruption': 0.20, 'dm': 0.25, 'wonder': 0.20, 'aq': 0.10},
    'Landscapes': {'dod': 0.15, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.30},
    'Street':     {'dod': 0.15, 'disruption': 0.25, 'dm': 0.25, 'wonder': 0.15, 'aq': 0.20},
    'Wedding':    {'dod': 0.10, 'disruption': 0.15, 'dm': 0.25, 'wonder': 0.10, 'aq': 0.40},
    'People':     {'dod': 0.10, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.15, 'aq': 0.40},
    'Macro':      {'dod': 0.35, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.10},
    'Creative':   {'dod': 0.20, 'disruption': 0.30, 'dm': 0.15, 'wonder': 0.20, 'aq': 0.15},
    'Drone':      {'dod': 0.30, 'disruption': 0.20, 'dm': 0.15, 'wonder': 0.25, 'aq': 0.10},
}

# ── Tier map ──────────────────────────────────────────────────────────────────
def get_tier(score):
    if score <= 5.0:  return 'Apprentice'
    if score <= 7.5:  return 'Practitioner'
    if score <= 8.9:  return 'Master'
    if score <= 9.6:  return 'Grandmaster'
    return 'Legend'

# ── Core formula ──────────────────────────────────────────────────────────────
def calculate_score(genre, dod, disruption, dm, wonder, aq):
    weights   = GENRE_WEIGHTS.get(genre, GENRE_WEIGHTS['Wildlife'])
    checks    = {}
    notes     = []

    raw = (
        dod        * weights['dod']        +
        disruption * weights['disruption'] +
        dm         * weights['dm']         +
        wonder     * weights['wonder']     +
        aq         * weights['aq']
    )

    if aq < 4.0:
        aq -= 1.5
        checks['humanity_check'] = True
        notes.append('Humanity Check triggered: AQ < 4.0, −1.5 applied to AQ')
        raw = (
            dod        * weights['dod']        +
            disruption * weights['disruption'] +
            dm         * weights['dm']         +
            wonder     * weights['wonder']     +
            aq         * weights['aq']
        )

    soul_bonus = aq >= 8.0
    checks['soul_bonus'] = soul_bonus
    if soul_bonus:
        notes.append('Soul Bonus active: AQ >= 8.0, technical penalties removed')

    if dod >= 9.5 and disruption < 5.0:
        checks['plateau_penalty'] = True
        notes.append('Plateau Penalty: DoD >= 9.5 + Disruption < 5.0, score capped at 7.9')
        raw = min(raw, 7.9)

    if raw >= 9.0:
        if disruption <= 8.5 or aq <= 8.5:
            checks['iconic_wall_blocked'] = True
            raw = min(raw, 8.99)
            notes.append('Iconic Wall: score capped at 8.99')
        else:
            checks['iconic_wall_cleared'] = True
            notes.append('Iconic Wall cleared')

    raw = min(raw, 9.9)
    final_score = round(raw, 1)
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
    from collections import defaultdict
    genre_buckets = defaultdict(list)

    for img in images:
        if img.score is not None:
            genre_buckets[img.genre].append(img)

    stats = {}
    for genre, imgs in genre_buckets.items():
        n = len(imgs)
        stats[genre] = {
            'count':      n,
            'avg_score':  round(sum(i.score           for i in imgs) / n, 2),
            'avg_dod':    round(sum(i.dod_score        for i in imgs) / n, 2),
            'avg_dis':    round(sum(i.disruption_score for i in imgs) / n, 2),
            'avg_dm':     round(sum(i.dm_score         for i in imgs) / n, 2),
            'avg_wonder': round(sum(i.wonder_score     for i in imgs) / n, 2),
            'avg_aq':     round(sum(i.aq_score         for i in imgs) / n, 2),
        }
    return stats
