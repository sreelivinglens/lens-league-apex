# ============================================================================
# REPLACE the existing /leaderboard route in app.py with this version.
# Key changes:
#   - Top Photographers now grouped by user_id (not photographer_name)
#   - Sorted by avg_score DESC (was best_score)
#   - Includes peer rating count per photographer
#   - display_name + username both available in template
# ============================================================================

@app.route('/leaderboard')
def leaderboard():
    genre  = request.args.get('genre', 'all')
    tier   = request.args.get('tier', 'all')
    period = request.args.get('period', 'all')
    track  = request.args.get('track', 'all')
    tab    = request.args.get('tab', 'images')

    now = datetime.utcnow()
    if period == 'week':
        since = now - timedelta(days=7)
    elif period == 'month':
        since = now - timedelta(days=30)
    else:
        since = None

    def apply_filters(q):
        q = q.filter(
            Image.score.isnot(None),
            Image.score > 0,
            Image.status == 'scored',
            Image.is_public == True,
            db.or_(Image.is_flagged == False, Image.is_flagged == None),
            db.or_(Image.needs_review == False, Image.needs_review == None)
        )
        if since:
            q = q.filter(Image.created_at >= since)
        if genre != 'all':
            q = q.filter(Image.genre == genre)
        if tier != 'all':
            q = q.filter(Image.tier == tier)
        if track == 'camera':
            q = q.filter(db.or_(
                db.text("camera_track = 'camera'"),
                db.text("camera_track IS NULL"),
            ))
        elif track == 'mobile':
            q = q.filter(db.text("camera_track = 'mobile'"))
        return q

    top_images = (apply_filters(Image.query)
                  .order_by(desc(Image.score))
                  .limit(20)
                  .all())

    # ── Top Photographers — grouped by user_id ────────────────────────────
    # Join to User so we can show display_name and username
    # Sort by avg_score DESC (changed from best_score)
    pg_base = (
        db.session.query(
            Image.user_id,
            User.username,
            User.full_name,
            func.avg(Image.score).label('avg_score'),
            func.max(Image.score).label('best_score'),
            func.count(Image.id).label('image_count'),
            func.sum(Image.peer_rating_count).label('total_peer_ratings'),
        )
        .join(User, Image.user_id == User.id)
    )
    pg_base = apply_filters(pg_base)
    pg_rows = (
        pg_base
        .group_by(Image.user_id, User.username, User.full_name)
        .order_by(desc('avg_score'))
        .limit(20)
        .all()
    )

    # Build photographer_stats as list of dicts for the template
    photographer_stats = []
    for row in pg_rows:
        photographer_stats.append({
            'user_id':            row.user_id,
            'username':           row.username,
            'display_name':       row.full_name or row.username,
            'avg_score':          round(float(row.avg_score), 2) if row.avg_score else 0,
            'best_score':         float(row.best_score) if row.best_score else 0,
            'image_count':        row.image_count,
            'total_peer_ratings': int(row.total_peer_ratings or 0),
        })

    all_tiers = ['Apprentice', 'Practitioner', 'Master', 'Grandmaster', 'Legend']

    return render_template('leaderboard.html',
        top_images          = top_images,
        photographer_stats  = photographer_stats,
        all_genres          = GENRE_IDS,
        all_tiers           = all_tiers,
        genre               = genre,
        tier                = tier,
        period              = period,
        track               = track,
        tab                 = tab,
    )
