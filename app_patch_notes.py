"""
PATCH for app.py — replace the existing EXIF cheat detection block in the upload() route.

FIND this block (around line 530 in app.py):

    # ── EXIF track cheat detection ────────────────────────────────────────
    # If user is on mobile track but EXIF shows a known camera brand → flag for review
    _CAMERA_BRANDS = ('canon', 'nikon', 'sony', ...
    ...
    if _user_track == 'mobile' and any(b in _exif_cam for b in _CAMERA_BRANDS):
        img.needs_review = True
        ...
        flash('⚠️ Your image was flagged for admin review...', 'warning')

REPLACE WITH the block below.
"""

# ── EXIF league integrity check ───────────────────────────────────────────────
# Mobile League users uploading images with DSLR/mirrorless EXIF → three-strike
# Images must be uploaded AFTER subscription date to count as a strike
# (protects users who joined Mobile League but have old camera images)

_CAMERA_BRANDS = ('canon', 'nikon', 'sony', 'fuji', 'fujifilm', 'olympus',
                  'panasonic', 'leica', 'hasselblad', 'pentax', 'sigma',
                  'ricoh', 'om system', 'om-system')
_user_league = getattr(current_user, 'subscription_track', None) or ''
_exif_cam    = (exif_data.get('camera', '') or '').lower()
_subscribed_at = getattr(current_user, 'subscribed_at', None)

# Only flag images uploaded after the user subscribed to Mobile League
_image_after_subscription = (
    _subscribed_at is None or
    datetime.utcnow() >= _subscribed_at
)

if (_user_league == 'mobile'
        and any(b in _exif_cam for b in _CAMERA_BRANDS)
        and _image_after_subscription):

    strike = current_user.record_mismatch(img.id, exif_data.get('camera', ''), db.session)

    img.needs_review = True
    img.exif_warning = (img.exif_warning or '') + (
        f' [LEAGUE MISMATCH: Camera EXIF "{exif_data.get("camera","")}" '
        f'detected on Mobile League subscription — strike {strike}/3]'
    )
    db.session.commit()
    app.logger.warning(
        f'[league_mismatch] user={current_user.id} image={img.id} '
        f'exif={_exif_cam} strike={strike}'
    )

    if strike == 1:
        flash(
            '⚠️ League check: this image appears to have been taken on a dedicated camera, '
            'but you are in the Mobile League. The image has been held for review. '
            'If this is correct, please switch to the Camera League. '
            'Contact verify@lensleague.com with questions.',
            'warning'
        )
    elif strike == 2:
        flash(
            '⚠️ Second league mismatch detected. This image and your previous mismatch image '
            'are disqualified from this month\'s contests pending admin review. '
            'One more mismatch will suspend your contest access. '
            'Please switch to the Camera League if you are shooting on a dedicated camera.',
            'warning'
        )
        # Void this month's contest entries for this user
        from datetime import datetime as _dt
        _month = _dt.utcnow().strftime('%Y-%m')
        ContestEntry.query.filter_by(
            user_id=current_user.id,
            contest_month=_month
        ).delete()
        db.session.commit()
        flash(
            'Your contest entries for this month have been removed pending review.',
            'error'
        )
    elif strike >= 3:
        flash(
            '🚫 Three league mismatches detected. Your contest access has been suspended. '
            'All current month contest entries have been removed. '
            'Contact verify@lensleague.com to resolve this — '
            'you may need to switch to the Camera League.',
            'error'
        )
        # Void all current month contest entries
        from datetime import datetime as _dt
        _month = _dt.utcnow().strftime('%Y-%m')
        ContestEntry.query.filter_by(
            user_id=current_user.id,
            contest_month=_month
        ).delete()
        db.session.commit()


# ── Also add to the register() route — save country/state/city/declared_camera ──
"""
In the register() route, after collecting existing fields, add:

    country        = request.form.get('country', '').strip()
    state          = request.form.get('state', '').strip()
    city           = request.form.get('city', '').strip()
    camera_brand   = request.form.get('camera_brand', '').strip()
    camera_model   = request.form.get('declared_camera', '').strip()
    declared_camera = f"{camera_brand} {camera_model}".strip() if camera_brand else None

    # Validate location
    if not country or not state or not city:
        flash('Please select your country, state, and city.', 'error')
        return redirect(url_for('register'))

Then in the User() constructor add:
    country=country,
    state=state,
    city=city,
    declared_camera=declared_camera,
"""


# ── Also add to the register() route context for template ─────────────────────
"""
In the render_template('register.html') call, add these context variables:

    from location_data import (
        get_countries, INDIA_STATES_CITIES, WORLD_LOCATIONS,
        CAMERA_BRANDS, PHONE_BRANDS
    )
    import json as _json

    # Build flat location data dict for JS
    location_data = {}
    for country, states in {**{'India': INDIA_STATES_CITIES}, **WORLD_LOCATIONS}.items():
        location_data[country] = states

    camera_data = {**CAMERA_BRANDS, **PHONE_BRANDS}

    return render_template('register.html',
        countries         = get_countries(),
        location_data_json = _json.dumps(location_data),
        camera_data_json   = _json.dumps(camera_data),
        camera_brands      = list(CAMERA_BRANDS.keys()),
        phone_brands       = list(PHONE_BRANDS.keys()),
    )
"""


# ── Migration SQL to add to _migrations list in app.py startup ────────────────
MIGRATION_SQL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS declared_camera VARCHAR(120)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS camera_mismatch_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_reason TEXT",
]
