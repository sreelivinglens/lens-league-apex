# ─────────────────────────────────────────────────────────────────────────────
# ADD THIS FUNCTION TO engine/scoring.py
# Place it after compute_calibration_stats() at the bottom of the file.
# ─────────────────────────────────────────────────────────────────────────────

def compute_percentile(score: float, genre: str = None, db_session=None, ImageModel=None) -> dict:
    """
    Given a DDI score, compute where it sits in the live distribution of all
    scored images on the platform. Optionally filter by genre for genre-specific
    percentile.

    Returns a dict:
    {
        'percentile':       int,        # e.g. 82 → "Top 18%"
        'top_pct':          int,        # e.g. 18  → shown as "Top 18%"
        'platform_avg':     float,      # mean score across all images
        'genre_avg':        float,      # mean score in this genre (or None)
        'master_avg':       float,      # mean score of Master-tier images
        'grandmaster_avg':  float,      # mean score of Grandmaster-tier images
        'top10_in_genre':   float,      # 90th-percentile score in this genre
        'total_images':     int,        # total scored images on platform
        'genre_images':     int,        # scored images in this genre
        'label':            str,        # human-readable label e.g. "Top 18%"
        'context':          str,        # one-line context sentence
    }

    Falls back gracefully to empty dict if DB is unavailable.
    """
    if db_session is None or ImageModel is None:
        try:
            from models import Image as ImageModel, db
            db_session = db.session
        except Exception:
            return {}

    try:
        # ── All scored public images ──────────────────────────────────────────
        base_q = db_session.query(ImageModel.score).filter(
            ImageModel.status == 'scored',
            ImageModel.score != None,
            ImageModel.score > 0,
            ImageModel.is_public == True,
            ImageModel.is_flagged == False,
        )

        all_scores = [row[0] for row in base_q.all()]
        if not all_scores:
            return {}

        total_images = len(all_scores)
        all_scores_sorted = sorted(all_scores)

        # Percentile rank: what % of images score BELOW this score
        below = sum(1 for s in all_scores if s < score)
        percentile = int(round(below / total_images * 100))
        top_pct = max(1, 100 - percentile)   # "Top X%" — never show "Top 0%"

        platform_avg = round(sum(all_scores) / total_images, 2)

        # ── Genre-specific stats ──────────────────────────────────────────────
        genre_avg = None
        genre_images = 0
        top10_in_genre = None

        if genre:
            canonical = normalise_genre(genre)
            genre_q = db_session.query(ImageModel.score).filter(
                ImageModel.status == 'scored',
                ImageModel.score != None,
                ImageModel.score > 0,
                ImageModel.is_public == True,
                ImageModel.is_flagged == False,
                ImageModel.genre == canonical,
            )
            genre_scores = [row[0] for row in genre_q.all()]
            genre_images = len(genre_scores)
            if genre_scores:
                genre_avg = round(sum(genre_scores) / genre_images, 2)
                # 90th percentile score in genre = approximate "Top 10" threshold
                genre_sorted = sorted(genre_scores)
                idx_90 = max(0, int(len(genre_sorted) * 0.90) - 1)
                top10_in_genre = round(genre_sorted[idx_90], 2)

        # ── Tier averages ─────────────────────────────────────────────────────
        master_scores = db_session.query(ImageModel.score).filter(
            ImageModel.status == 'scored',
            ImageModel.tier == 'Master',
            ImageModel.score != None,
            ImageModel.is_public == True,
            ImageModel.is_flagged == False,
        ).all()
        master_avg = round(
            sum(r[0] for r in master_scores) / len(master_scores), 2
        ) if master_scores else 7.8

        gm_scores = db_session.query(ImageModel.score).filter(
            ImageModel.status == 'scored',
            ImageModel.tier == 'Grandmaster',
            ImageModel.score != None,
            ImageModel.is_public == True,
            ImageModel.is_flagged == False,
        ).all()
        grandmaster_avg = round(
            sum(r[0] for r in gm_scores) / len(gm_scores), 2
        ) if gm_scores else 9.1

        # ── Human-readable label ──────────────────────────────────────────────
        if top_pct <= 5:
            label = f"Top {top_pct}% — Elite"
        elif top_pct <= 15:
            label = f"Top {top_pct}%"
        elif top_pct <= 30:
            label = f"Top {top_pct}%"
        else:
            label = f"Top {top_pct}%"

        # ── Context sentence ──────────────────────────────────────────────────
        if top10_in_genre and genre_images >= 5:
            canonical_display = normalise_genre(genre)
            if score >= top10_in_genre:
                context = f"You are in the top 10 scorers in {canonical_display} this platform."
            else:
                gap = round(top10_in_genre - score, 1)
                context = (
                    f"Top 10 in {canonical_display} are scoring {top10_in_genre}+. "
                    f"You are {gap} points away."
                )
        elif score >= grandmaster_avg:
            context = "Your score is above the average Grandmaster on this platform."
        elif score >= master_avg:
            context = "Your score is above the average Master on this platform."
        else:
            gap = round(master_avg - score, 1)
            context = f"Master-tier average is {master_avg}. You are {gap} points away."

        return {
            'percentile':       percentile,
            'top_pct':          top_pct,
            'platform_avg':     platform_avg,
            'genre_avg':        genre_avg,
            'master_avg':       master_avg,
            'grandmaster_avg':  grandmaster_avg,
            'top10_in_genre':   top10_in_genre,
            'total_images':     total_images,
            'genre_images':     genre_images,
            'label':            label,
            'context':          context,
        }

    except Exception as e:
        print(f'[compute_percentile] {e}')
        return {}
