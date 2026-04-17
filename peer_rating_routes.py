# ============================================================================
# PEER RATING ROUTES — paste into app.py
# Add these imports at the top of app.py:
#   from models import ... RatingAssignment, PeerRating, get_or_assign_next_image, submit_peer_rating
# ============================================================================

@app.route('/rate')
@login_required
def rate():
    """Blind peer rating queue page."""
    from models import get_or_assign_next_image, RatingAssignment, PeerRating
    from datetime import date as _date

    user = current_user
    user.reset_credits_if_needed()
    db.session.commit()

    is_subscriber = getattr(user, 'is_subscribed', False)
    credits       = user.rating_credits or 0
    lifetime      = user.lifetime_ratings_given or 0

    # Count ratings given this calendar month
    from sqlalchemy import extract
    now = datetime.utcnow()
    month_given = PeerRating.query.filter(
        PeerRating.rater_id == user.id,
        extract('month', PeerRating.rated_at) == now.month,
        extract('year',  PeerRating.rated_at) == now.year,
    ).count()

    assignment = None
    image      = None
    queue_remaining = 0

    if is_subscriber and credits > 0:
        assignment = get_or_assign_next_image(user.id)
        if assignment:
            # Mark as started if not already
            if assignment.status == 'assigned':
                assignment.status     = 'started'
                assignment.started_at = datetime.utcnow()
                db.session.commit()
            image = assignment.image

        # Rough queue count — eligible images not yet rated by this user
        from sqlalchemy import func as sqlfunc
        already = db.session.query(RatingAssignment.image_id).filter(
            RatingAssignment.rater_id == user.id,
        ).subquery()
        queue_remaining = (
            Image.query
            .join(User, Image.user_id == User.id)
            .filter(
                Image.status == 'scored', Image.is_public == True,
                Image.is_flagged == False, Image.needs_review == False,
                Image.score != None, Image.user_id != user.id,
                User.is_subscribed == True,
                Image.id.notin_(already),
            ).count()
        )

    # Next reset date
    from datetime import timedelta
    today = _date.today()
    if today.month == 12:
        next_reset = _date(today.year + 1, 1, 1)
    else:
        next_reset = _date(today.year, today.month + 1, 1)

    return render_template('rate.html',
        is_subscriber   = is_subscriber,
        credits         = credits,
        lifetime_given  = lifetime,
        month_given     = month_given,
        assignment      = assignment,
        image           = image,
        queue_remaining = queue_remaining,
        next_reset      = next_reset.strftime('%-d %B'),
        bias_flag       = getattr(user, 'rating_bias_flag', False),
    )


@app.route('/rate/submit', methods=['POST'])
@login_required
def submit_rating():
    """Submit a completed peer rating."""
    from models import RatingAssignment, submit_peer_rating

    assignment_id = request.form.get('assignment_id', type=int)
    if not assignment_id:
        flash('Invalid submission.', 'error')
        return redirect(url_for('rate'))

    assignment = RatingAssignment.query.get(assignment_id)
    if not assignment or assignment.rater_id != current_user.id:
        flash('Rating assignment not found.', 'error')
        return redirect(url_for('rate'))

    if assignment.status == 'submitted':
        flash('You have already submitted this rating.', 'info')
        return redirect(url_for('rate'))

    # Validate credits
    current_user.reset_credits_if_needed()
    if (current_user.rating_credits or 0) <= 0:
        flash('No rating credits remaining this month.', 'warning')
        return redirect(url_for('rate'))

    # Server-side time check — must be ≥ 13s (2s tolerance for network)
    client_start = request.form.get('client_start_ts', type=int)
    time_spent   = request.form.get('time_spent', type=int) or 0
    if client_start:
        server_elapsed = int((datetime.utcnow().timestamp() * 1000 - client_start) / 1000)
        if server_elapsed < 13:
            flash('Please spend more time viewing the image before rating.', 'warning')
            return redirect(url_for('rate'))

    # Parse module scores
    try:
        dod        = float(request.form.get('dod', 5))
        disruption = float(request.form.get('disruption', 5))
        dm         = float(request.form.get('dm', 5))
        wonder     = float(request.form.get('wonder', 5))
        aq         = float(request.form.get('aq', 5))
    except (ValueError, TypeError):
        flash('Invalid scores submitted.', 'error')
        return redirect(url_for('rate'))

    # Clamp all values 1–10
    def clamp(v): return max(1.0, min(10.0, round(v * 2) / 2))
    dod        = clamp(dod)
    disruption = clamp(disruption)
    dm         = clamp(dm)
    wonder     = clamp(wonder)
    aq         = clamp(aq)

    try:
        rating = submit_peer_rating(
            assignment = assignment,
            dod        = dod,
            disruption = disruption,
            dm         = dm,
            wonder     = wonder,
            aq         = aq,
            time_spent = time_spent,
        )
        flash(f'Rating submitted! Peer LL-Score: {rating.peer_ll_score} · +1 credit earned.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[submit_rating] {e}')
        flash('Submission failed. Please try again.', 'error')

    return redirect(url_for('rate'))


@app.route('/rate/skip', methods=['POST'])
@login_required
def skip_rating():
    """Skip a rating assignment — expires it, no credit cost."""
    from models import RatingAssignment
    assignment_id = request.form.get('assignment_id', type=int)
    if assignment_id:
        a = RatingAssignment.query.get(assignment_id)
        if a and a.rater_id == current_user.id and a.status != 'submitted':
            a.status = 'expired'
            db.session.commit()
    return redirect(url_for('rate'))


# ============================================================================
# ADMIN RATING AUDIT ROUTES
# ============================================================================

@app.route('/admin/ratings')
@login_required
@admin_required
def admin_ratings():
    from models import PeerRating, RatingAssignment
    from engine.scoring import GENRE_IDS

    page          = request.args.get('page', 1, type=int)
    rater_filter  = request.args.get('rater_id', '').strip()
    genre_filter  = request.args.get('genre', '').strip()
    outliers_only = request.args.get('outliers', '') == '1'

    q = PeerRating.query

    if rater_filter:
        q = q.filter(PeerRating.rater_id == int(rater_filter))
    if genre_filter:
        q = q.filter(PeerRating.genre == genre_filter)
    if outliers_only:
        q = q.filter(
            db.or_(PeerRating.delta_from_ddi > 2, PeerRating.delta_from_ddi < -2)
        )

    q = q.order_by(PeerRating.rated_at.desc())
    per_page   = 50
    total      = q.count()
    pages      = max(1, (total + per_page - 1) // per_page)
    ratings    = q.offset((page - 1) * per_page).limit(per_page).all()

    # Stats
    total_ratings    = PeerRating.query.count()
    total_raters     = db.session.query(PeerRating.rater_id).distinct().count()
    images_with_peer = db.session.query(PeerRating.image_id).distinct().count()
    biased_raters    = User.query.filter_by(rating_bias_flag=True).count()
    biased_users     = User.query.filter_by(rating_bias_flag=True).all()

    all_raters = (
        User.query
        .filter(User.role != 'admin', User.is_subscribed == True)
        .order_by(User.full_name)
        .all()
    )

    return render_template('admin_ratings.html',
        ratings         = ratings,
        page            = page,
        pages           = pages,
        total_ratings   = total_ratings,
        total_raters    = total_raters,
        images_with_peer= images_with_peer,
        biased_raters   = biased_raters,
        biased_users    = biased_users,
        all_raters      = all_raters,
        all_genres      = GENRE_IDS,
        rater_filter    = rater_filter,
        genre_filter    = genre_filter,
        outliers_only   = outliers_only,
    )


@app.route('/admin/ratings/export-csv')
@login_required
@admin_required
def admin_export_ratings_csv():
    """Export full peer rating audit as CSV."""
    from models import PeerRating
    import io, csv
    from flask import Response

    ratings = PeerRating.query.order_by(PeerRating.rated_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'rated_at', 'rater_username', 'rater_name',
        'image_id', 'image_title', 'photographer', 'genre',
        'time_spent_seconds',
        'peer_dod', 'peer_disruption', 'peer_dm', 'peer_wonder', 'peer_aq',
        'peer_ll_score', 'ddi_score', 'delta_from_ddi',
        'rater_bias_flag',
    ])
    for r in ratings:
        img     = r.image
        rater   = r.rater
        writer.writerow([
            r.rated_at.strftime('%Y-%m-%d %H:%M:%S') if r.rated_at else '',
            rater.username  if rater else '',
            rater.full_name if rater else '',
            r.image_id,
            img.asset_name  if img else '',
            img.photographer_name if img else '',
            r.genre,
            r.time_spent_seconds or '',
            r.dod, r.disruption, r.dm, r.wonder, r.aq,
            r.peer_ll_score,
            img.score if img else '',
            r.delta_from_ddi if r.delta_from_ddi is not None else '',
            '1' if (rater and rater.rating_bias_flag) else '0',
        ])

    from datetime import date
    filename = f'lens_league_peer_ratings_{date.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.route('/admin/user/<int:user_id>/clear-bias-flag', methods=['POST'])
@login_required
@admin_required
def admin_clear_bias_flag(user_id):
    user = User.query.get_or_404(user_id)
    user.rating_bias_flag = False
    user.rating_bias_note = None
    db.session.commit()
    flash(f'Bias flag cleared for {user.full_name or user.username}.', 'success')
    return redirect(url_for('admin_ratings'))
