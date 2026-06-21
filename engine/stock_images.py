"""
Pixabay reference-image fallback for Mission lesson cards.

Root cause this exists to fix: the /mission route's "benchmark" query picks
a real ShutterLeague user's high-scoring public photo to illustrate today's
lesson, filtered by mission_dimension. When no genre-matched community photo
exists for that dimension, the OLD fallback dropped the dimension filter too
and showed literally the highest-scoring public photo on the whole platform
— any genre, any dimension — which is how a Wildlife lesson once showed a
street protest photo. The real fix is a genre filter on that query (done in
app.py). This module is what fills the gap when, even with the genre filter,
there simply isn't a community submission yet for that genre+dimension
combo — instead of falling through to "show anything", it searches Pixabay
for something genuinely relevant.

Pixabay API terms (https://pixabay.com/api/docs/) this code follows:
  - Results must be cached 24h minimum. This caches per (genre, dimension)
    combo until manually refreshed (max_age_days, default 30) — there are
    only 55 possible combos (11 genres x 5 dimensions), so this is well
    within the requirement and avoids ever re-querying for the same combo
    on every page load.
  - Permanent hotlinking of pixabay.com/cdn.pixabay.com URLs is not
    allowed. Images are downloaded once and re-served from R2 — never
    linked to directly.
  - The Pixabay License does not require attribution, so none is shown in
    the UI. Contributor info is still stored in the cache table in case it's
    ever needed (moderation, future credit line, etc).

Env: PIXABAY_API_KEY must be set in the environment. If it isn't, or
anything in the fetch pipeline fails, get_or_fetch_reference_image()
returns None — it never raises, since it sits in a fallback path that
itself sits behind a fallback. The caller (app.py /mission route) should
treat None exactly like "no benchmark image" and fall through to its
existing placeholder.
"""
import os
import uuid
import tempfile
import urllib.request
import urllib.parse
import urllib.error
import json as _json
from sqlalchemy import text as _sql_text

import storage as r2


# ── Query construction ──────────────────────────────────────────────────────
# Genre + dimension keywords combined into a short Pixabay search query —
# kept to 2-4 words, specific enough to bias toward relevant subjects
# without over-constraining Pixabay's index to the point of empty results.

_GENRE_TERMS = {
    'Wildlife':        'wildlife animal',
    'Street':          'street photography',
    'Landscape':       'landscape scenic',
    'People':          'portrait person',
    'Wedding':         'wedding couple',
    'Macro':           'macro closeup',
    'Drone & Aerial':  'aerial drone',
    'Creative':        'abstract creative',
    'Nature':          'nature outdoor',
    'Documentary':     'documentary candid',
    'Fashion':         'fashion model',
}

_DIMENSION_TERMS = {
    'dod':         'extreme weather',
    'dm':          'action motion',
    'aq':          'dramatic light',
    'wonder':      'abstract texture',
    'disruption':  'unconventional angle',
}


def _build_query(genre: str, dimension: str) -> str:
    """
    e.g. ('Wildlife', 'dm') -> 'wildlife animal action motion'
         ('Street', 'aq')   -> 'street photography dramatic light'
    Unknown genre/dimension values degrade gracefully rather than failing —
    genre falls back to its own lowercased name, dimension is just omitted.
    """
    genre_term = _GENRE_TERMS.get(genre, genre.lower())
    dim_term   = _DIMENSION_TERMS.get(dimension, '')
    return f"{genre_term} {dim_term}".strip()


# ── Pixabay API call ─────────────────────────────────────────────────────────

def _pixabay_search(query: str, api_key: str, timeout: int = 10) -> list:
    """
    Raw search call against the Pixabay images endpoint. Returns the `hits`
    list, or [] on any error (network failure, bad key, rate limit, no
    results) — this must never raise.
    """
    params = {
        'key':         api_key,
        'q':           query,
        'image_type':  'photo',
        'orientation': 'horizontal',
        'safesearch':  'true',
        'order':       'popular',
        'min_width':   '1280',
        'per_page':    '20',
    }
    url = 'https://pixabay.com/api/?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ShutterLeague/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        return data.get('hits', []) or []
    except urllib.error.HTTPError as e:
        print(f'[stock_images] pixabay search HTTP {e.code}: {e.reason}')
        return []
    except Exception as e:
        print(f'[stock_images] pixabay search failed: {e}')
        return []


def _pick_best_hit(hits: list):
    """
    Pixabay's default order=popular already ranks results reasonably, so
    this takes the first hit that has the fields we actually need rather
    than re-deriving a quality score Pixabay has already computed.
    Returns None if hits is empty or nothing usable is in it.
    """
    for hit in hits:
        if hit.get('id') and hit.get('largeImageURL'):
            return hit
    return None


def _download_to_temp(url: str, timeout: int = 15):
    """Downloads an image to a local temp file. Returns the local path, or None on failure."""
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        req = urllib.request.Request(url, headers={'User-Agent': 'ShutterLeague/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
        with open(path, 'wb') as f:
            f.write(content)
        return path
    except Exception as e:
        print(f'[stock_images] download failed: {e}')
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        return None


def _r2_upload_reference_image(local_path: str, cache_key: str):
    """
    Uploads a downloaded Pixabay image to R2 under a dedicated reference/
    prefix. Never hotlinks pixabay.com/cdn.pixabay.com URLs directly —
    this is the one-time download the API's hotlinking terms require.
    """
    key = f'reference/{cache_key}.jpg'
    try:
        result = r2.upload_file(local_path, key, content_type='image/jpeg')
        if not result:
            print(f'[stock_images] R2 upload returned None for key={key}')
        return result
    except Exception as e:
        print(f'[stock_images] R2 upload exception: {e}')
        return None


# ── Main entry point ─────────────────────────────────────────────────────────

def get_or_fetch_reference_image(db_session, genre: str, dimension: str,
                                  max_age_days: int = 30):
    """
    Call this when no community benchmark photo exists for a given
    genre+dimension combo. Returns an R2-hosted image URL, or None if
    Pixabay has nothing usable / PIXABAY_API_KEY isn't set / anything in
    the pipeline failed — never raises. Callers should treat None exactly
    like "no benchmark image" and fall through to their existing
    placeholder.

    Caches the pick per (genre, dimension) in pixabay_reference_cache so
    the same combo isn't re-fetched from Pixabay on every page load —
    there are only 55 possible combos, so in practice this means Pixabay
    gets hit at most 55 times per max_age_days window, total, regardless
    of traffic volume.
    """
    try:
        cached = db_session.execute(
            _sql_text("""
                SELECT image_url FROM pixabay_reference_cache
                WHERE genre = :genre AND dimension = :dimension
                  AND fetched_at >= NOW() - (:days || ' days')::INTERVAL
            """),
            {'genre': genre, 'dimension': dimension, 'days': max_age_days}
        ).fetchone()
        if cached:
            return cached.image_url
    except Exception as e:
        print(f'[stock_images] cache read failed (non-fatal): {e}')

    api_key = os.getenv('PIXABAY_API_KEY', '')
    if not api_key:
        return None

    query = _build_query(genre, dimension)
    hits  = _pixabay_search(query, api_key)
    hit   = _pick_best_hit(hits)
    if not hit:
        return None

    local_path = _download_to_temp(hit['largeImageURL'])
    if not local_path:
        return None

    _safe_genre = genre.lower().replace(' ', '-').replace('&', 'and')
    cache_key   = f"{_safe_genre}-{dimension}-{uuid.uuid4().hex[:8]}"
    image_url   = _r2_upload_reference_image(local_path, cache_key)

    try:
        if os.path.exists(local_path):
            os.remove(local_path)
    except Exception:
        pass

    if not image_url:
        return None

    try:
        db_session.execute(
            _sql_text("""
                INSERT INTO pixabay_reference_cache
                    (genre, dimension, pixabay_id, image_url, photographer_credit, fetched_at)
                VALUES (:genre, :dimension, :pid, :url, :credit, NOW())
                ON CONFLICT (genre, dimension) DO UPDATE SET
                    pixabay_id          = EXCLUDED.pixabay_id,
                    image_url           = EXCLUDED.image_url,
                    photographer_credit = EXCLUDED.photographer_credit,
                    fetched_at          = NOW()
            """),
            {
                'genre':     genre,
                'dimension': dimension,
                'pid':       str(hit.get('id', '')),
                'url':       image_url,
                'credit':    hit.get('user', ''),
            }
        )
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        print(f'[stock_images] cache write failed (non-fatal): {e}')

    return image_url
