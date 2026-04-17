import json
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from flask_login import UserMixin

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id                = db.Column(db.Integer, primary_key=True)
    username          = db.Column(db.String(80),  unique=True, nullable=False)
    email             = db.Column(db.String(120), unique=True, nullable=False)
    password_hash     = db.Column(db.String(256), nullable=False)
    full_name         = db.Column(db.String(120), nullable=True)

    role              = db.Column(db.String(20), default='member', nullable=False)
    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    last_login        = db.Column(db.DateTime, nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    security_question = db.Column(db.String(255), nullable=True)
    security_answer   = db.Column(db.String(255), nullable=True)

    agreed_at         = db.Column(db.DateTime, nullable=True)

    is_subscribed        = db.Column(db.Boolean, default=False)
    subscription_track   = db.Column(db.String(20), nullable=True)   # 'camera' | 'mobile'
    subscription_plan    = db.Column(db.String(20), nullable=True)   # 'monthly' | 'annual' | 'beta'
    subscribed_at        = db.Column(db.DateTime, nullable=True)
    monthly_uploads_used = db.Column(db.Integer, default=0)
    monthly_reset_date   = db.Column(db.Date, nullable=True)

    # Peer rating credits
    rating_credits       = db.Column(db.Integer, default=20)
    credits_reset_date   = db.Column(db.Date, nullable=True)
    lifetime_ratings_given = db.Column(db.Integer, default=0)
    # Bias detection flag set by admin or auto-detection
    rating_bias_flag     = db.Column(db.Boolean, default=False)
    rating_bias_note     = db.Column(db.Text, nullable=True)

    images            = db.relationship('Image', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

    def reset_credits_if_needed(self):
        """Reset rating credits to 20 at start of each month."""
        today = date.today()
        if self.credits_reset_date is None or self.credits_reset_date.month != today.month or self.credits_reset_date.year != today.year:
            self.rating_credits = 20
            self.credits_reset_date = today
            return True
        return False


class Image(db.Model):
    __tablename__ = 'images'

    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    original_filename   = db.Column(db.String(260), nullable=True)
    stored_filename     = db.Column(db.String(260), nullable=True)
    phash               = db.Column(db.String(64),  nullable=True, index=True)
    thumb_path          = db.Column(db.String(512), nullable=True)
    thumb_url           = db.Column(db.String(512), nullable=True)
    card_path           = db.Column(db.String(512), nullable=True)
    card_url            = db.Column(db.String(512), nullable=True)
    file_size_kb        = db.Column(db.Integer,  nullable=True)
    width               = db.Column(db.Integer,  nullable=True)
    height              = db.Column(db.Integer,  nullable=True)
    format              = db.Column(db.String(10), nullable=True)

    asset_name          = db.Column(db.String(180), nullable=True)
    genre               = db.Column(db.String(60),  nullable=True)
    subject             = db.Column(db.String(180), nullable=True)
    location            = db.Column(db.String(180), nullable=True)
    conditions          = db.Column(db.String(180), nullable=True)
    photographer_name   = db.Column(db.String(120), nullable=True)

    # Competition track: 'camera' | 'mobile' | None (free users)
    camera_track        = db.Column(db.String(20), nullable=True)

    legal_declaration   = db.Column(db.Boolean, default=False)

    exif_status         = db.Column(db.String(20),  default='unverified')
    exif_camera         = db.Column(db.String(120), nullable=True)
    exif_date_taken     = db.Column(db.String(60),  nullable=True)
    exif_settings       = db.Column(db.String(180), nullable=True)
    exif_warning        = db.Column(db.Text,         nullable=True)

    dod_score           = db.Column(db.Float, nullable=True)
    disruption_score    = db.Column(db.Float, nullable=True)
    dm_score            = db.Column(db.Float, nullable=True)
    wonder_score        = db.Column(db.Float, nullable=True)
    aq_score            = db.Column(db.Float, nullable=True)
    score               = db.Column(db.Float, nullable=True)
    tier                = db.Column(db.String(60),  nullable=True)
    archetype           = db.Column(db.String(120), nullable=True)
    soul_bonus          = db.Column(db.Boolean, default=False)

    # Peer rating aggregates
    peer_avg_score      = db.Column(db.Float, nullable=True)
    peer_rating_count   = db.Column(db.Integer, default=0)
    blended_score       = db.Column(db.Float, nullable=True)   # 80% DDI + 20% peer (≥5 ratings)

    # Peer module averages
    peer_avg_dod        = db.Column(db.Float, nullable=True)
    peer_avg_disruption = db.Column(db.Float, nullable=True)
    peer_avg_dm         = db.Column(db.Float, nullable=True)
    peer_avg_wonder     = db.Column(db.Float, nullable=True)
    peer_avg_aq         = db.Column(db.Float, nullable=True)

    is_calibration_example = db.Column(db.Boolean, default=False, nullable=False)
    judge_referral         = db.Column(db.Boolean, default=False, nullable=False)
    is_public              = db.Column(db.Boolean, default=True,  nullable=False)

    # AI generation detection
    ai_suspicion           = db.Column(db.Float,   default=0.0,   nullable=True)
    ai_suspicion_reason    = db.Column(db.Text,                    nullable=True)
    needs_review           = db.Column(db.Boolean, default=False,  nullable=False)
    is_flagged             = db.Column(db.Boolean, default=False,  nullable=False)
    flagged_reason         = db.Column(db.Text,                    nullable=True)
    flagged_at             = db.Column(db.DateTime,                nullable=True)

    status              = db.Column(db.String(20), default='pending')
    scored_at           = db.Column(db.DateTime,  nullable=True)
    created_at          = db.Column(db.DateTime,  default=datetime.utcnow)

    _audit_json         = db.Column('audit_json', db.Text, nullable=True)

    def set_audit(self, data: dict):
        self._audit_json = json.dumps(data)

    def get_audit(self) -> dict:
        if self._audit_json:
            try:
                return json.loads(self._audit_json)
            except Exception:
                return {}
        return {}

    def update_blended_score(self):
        """Recalculate blended score after a new peer rating is submitted."""
        if self.peer_rating_count and self.peer_rating_count >= 5 and self.peer_avg_score and self.score:
            self.blended_score = round(self.score * 0.80 + self.peer_avg_score * 0.20, 2)
        else:
            self.blended_score = self.score

    def __repr__(self):
        return f'<Image {self.id} – {self.asset_name} ({self.score})>'


class RatingAssignment(db.Model):
    """
    Queue-based peer rating assignment.
    One record per rater-image pairing. Tracks the full lifecycle:
    assigned → started (image viewed) → submitted | expired.
    """
    __tablename__ = 'rating_assignments'

    id              = db.Column(db.Integer, primary_key=True)
    rater_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    assigned_at     = db.Column(db.DateTime, default=datetime.utcnow)
    started_at      = db.Column(db.DateTime, nullable=True)   # set when /rate page loads the image
    submitted_at    = db.Column(db.DateTime, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    status          = db.Column(db.String(20), default='assigned')  # assigned|started|submitted|expired

    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='rating_assignments', lazy=True)
    image  = db.relationship('Image', foreign_keys=[image_id],  backref='rating_assignments', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('rater_id', 'image_id', name='uq_rating_assignment'),
    )

    def __repr__(self):
        return f'<RatingAssignment rater={self.rater_id} image={self.image_id} status={self.status}>'


class PeerRating(db.Model):
    """
    Completed peer rating record. One per rater per image.
    All 5 DDI modules scored individually; peer_ll_score computed
    using the same genre-weighted formula as DDI.
    delta_from_ddi = peer_ll_score - image.score (signed).
    """
    __tablename__ = 'peer_ratings'

    id              = db.Column(db.Integer, primary_key=True)
    rater_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre           = db.Column(db.String(60), nullable=False)

    # Module scores — same scale as DDI (0.0–10.0)
    dod             = db.Column(db.Float, nullable=False)
    disruption      = db.Column(db.Float, nullable=False)
    dm              = db.Column(db.Float, nullable=False)
    wonder          = db.Column(db.Float, nullable=False)
    aq              = db.Column(db.Float, nullable=False)

    peer_ll_score   = db.Column(db.Float, nullable=False)   # genre-weighted, same formula as DDI
    delta_from_ddi  = db.Column(db.Float, nullable=True)    # signed: positive = rated higher than DDI

    time_spent_seconds = db.Column(db.Integer, nullable=True)
    rated_at        = db.Column(db.DateTime, default=datetime.utcnow)

    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='peer_ratings_given', lazy=True)
    image  = db.relationship('Image', foreign_keys=[image_id],  backref='peer_ratings_received', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('rater_id', 'image_id', name='uq_peer_rating'),
    )

    def __repr__(self):
        return f'<PeerRating rater={self.rater_id} image={self.image_id} score={self.peer_ll_score} delta={self.delta_from_ddi}>'


class ContestEntry(db.Model):
    __tablename__ = 'contest_entries'

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id      = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre         = db.Column(db.String(60),  nullable=False)
    track         = db.Column(db.String(20),  nullable=False)
    contest_month = db.Column(db.String(7),   nullable=False)
    contest_type  = db.Column(db.String(20),  default='monthly')
    entered_at    = db.Column(db.DateTime,    default=datetime.utcnow)

    user  = db.relationship('User',  foreign_keys=[user_id],  backref='contest_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='contest_entries', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'genre', 'track', 'contest_month', 'contest_type',
                            name='uq_contest_entry'),
    )


class BowSubmission(db.Model):
    __tablename__ = 'bow_submissions'

    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    series_title       = db.Column(db.String(180), nullable=False)
    thematic_statement = db.Column(db.Text, nullable=False)
    image_ids_json     = db.Column(db.Text, nullable=False)
    image_count        = db.Column(db.Integer, nullable=False)
    status             = db.Column(db.String(20), default='submitted')
    platform_year      = db.Column(db.Integer, nullable=False)
    submitted_at       = db.Column(db.DateTime, default=datetime.utcnow)
    notes              = db.Column(db.Text, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref='bow_submissions', lazy=True)

    def get_image_ids(self):
        try:
            return json.loads(self.image_ids_json)
        except Exception:
            return []

    def set_image_ids(self, ids: list):
        self.image_ids_json = json.dumps(ids)


class OpenContestEntry(db.Model):
    __tablename__ = 'open_contest_entries'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id     = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre        = db.Column(db.String(60), nullable=False)
    platform_year= db.Column(db.Integer,   nullable=False)
    amount_paise = db.Column(db.Integer,   default=5000)
    payment_ref  = db.Column(db.String(120), nullable=True)
    status       = db.Column(db.String(20), default='confirmed')
    entered_at   = db.Column(db.DateTime,  default=datetime.utcnow)

    user  = db.relationship('User',  foreign_keys=[user_id],  backref='open_contest_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='open_contest_entries', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'genre', 'platform_year', name='uq_open_contest_entry'),
    )


class CalibrationNote(db.Model):
    __tablename__ = 'calibration_notes'

    id              = db.Column(db.Integer, primary_key=True)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    admin_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    genre           = db.Column(db.String(60), nullable=False)
    module          = db.Column(db.String(20), nullable=False)
    original_score  = db.Column(db.Float, nullable=True)
    corrected_score = db.Column(db.Float, nullable=True)
    reason          = db.Column(db.Text, nullable=False)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    image = db.relationship('Image', foreign_keys=[image_id], backref='calibration_notes', lazy=True)
    admin = db.relationship('User',  foreign_keys=[admin_id], backref='admin_calibration_notes', lazy=True)


class CalibrationLog(db.Model):
    __tablename__ = 'calibration_logs'

    id          = db.Column(db.Integer, primary_key=True)
    genre       = db.Column(db.String(60),  nullable=False)
    image_count = db.Column(db.Integer,     nullable=True)
    avg_score   = db.Column(db.Float,       nullable=True)
    avg_dod     = db.Column(db.Float,       nullable=True)
    avg_dis     = db.Column(db.Float,       nullable=True)
    avg_dm      = db.Column(db.Float,       nullable=True)
    avg_wonder  = db.Column(db.Float,       nullable=True)
    avg_aq      = db.Column(db.Float,       nullable=True)
    note        = db.Column(db.Text,         nullable=True)
    logged_by   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    logged_at   = db.Column(db.DateTime, default=datetime.utcnow)


class ImageReport(db.Model):
    __tablename__ = 'image_reports'

    id          = db.Column(db.Integer, primary_key=True)
    image_id    = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    reason      = db.Column(db.String(40),  nullable=False)
    detail      = db.Column(db.Text,        nullable=True)
    reported_at = db.Column(db.DateTime,    default=datetime.utcnow)
    status      = db.Column(db.String(20),  default='open')

    image    = db.relationship('Image', backref=db.backref('reports', lazy='dynamic'))
    reporter = db.relationship('User',  backref=db.backref('filed_reports', lazy='dynamic'))


# ---------------------------------------------------------------------------
# Peer Rating helpers — standalone functions used in app.py
# ---------------------------------------------------------------------------

def get_or_assign_next_image(rater_id: int):
    """
    Return the next RatingAssignment for this rater.
    Priority: images with fewest peer ratings among subscriber-owned,
    public, scored images the rater has not yet rated.
    Expires old assignments (>30 min, not submitted) before selecting.
    Returns RatingAssignment or None if pool is empty.
    """
    from datetime import timedelta
    from sqlalchemy import func

    # Expire stale assigned-but-not-started assignments older than 30 min
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    stale = RatingAssignment.query.filter(
        RatingAssignment.rater_id == rater_id,
        RatingAssignment.status == 'assigned',
        RatingAssignment.assigned_at < cutoff,
    ).all()
    for s in stale:
        s.status = 'expired'
    if stale:
        db.session.commit()

    # Check for an in-progress assignment (started but not submitted)
    in_progress = RatingAssignment.query.filter_by(
        rater_id=rater_id, status='started'
    ).first()
    if in_progress:
        return in_progress

    # Check for a fresh assigned (not yet started)
    fresh = RatingAssignment.query.filter_by(
        rater_id=rater_id, status='assigned'
    ).first()
    if fresh:
        return fresh

    # Find the rater's user_id to exclude their own images
    rater = User.query.get(rater_id)
    if not rater:
        return None

    # IDs already rated or assigned by this rater
    already_seen = db.session.query(RatingAssignment.image_id).filter(
        RatingAssignment.rater_id == rater_id,
        RatingAssignment.status.in_(['assigned', 'started', 'submitted']),
    ).subquery()

    # Eligible pool — subscriber images only, public, scored, not own
    eligible = (
        Image.query
        .join(User, Image.user_id == User.id)
        .filter(
            Image.status == 'scored',
            Image.is_public == True,
            Image.is_flagged == False,
            Image.needs_review == False,
            Image.score != None,
            Image.user_id != rater_id,
            User.is_subscribed == True,
            Image.id.notin_(already_seen),
        )
        .order_by(
            Image.peer_rating_count.asc().nullsfirst(),
            Image.scored_at.asc(),
        )
        .first()
    )

    if not eligible:
        return None

    assignment = RatingAssignment(
        rater_id   = rater_id,
        image_id   = eligible.id,
        status     = 'assigned',
    )
    db.session.add(assignment)
    db.session.commit()
    return assignment


def submit_peer_rating(assignment: RatingAssignment, dod: float, disruption: float,
                       dm: float, wonder: float, aq: float,
                       time_spent: int) -> PeerRating:
    """
    Complete a rating assignment, create PeerRating record,
    update image aggregates and rater credits.
    Returns the created PeerRating.
    """
    from engine.scoring import calculate_score, normalise_genre

    image = assignment.image
    genre = normalise_genre(image.genre)

    # Compute peer_ll_score using the same weighted formula as DDI
    peer_ll, _, _, _ = calculate_score(genre, dod, disruption, dm, wonder, aq)

    delta = round(peer_ll - (image.score or 0), 2)

    rating = PeerRating(
        rater_id           = assignment.rater_id,
        image_id           = assignment.image_id,
        genre              = genre,
        dod                = dod,
        disruption         = disruption,
        dm                 = dm,
        wonder             = wonder,
        aq                 = aq,
        peer_ll_score      = peer_ll,
        delta_from_ddi     = delta,
        time_spent_seconds = time_spent,
    )
    db.session.add(rating)

    # Update assignment
    assignment.status             = 'submitted'
    assignment.submitted_at       = datetime.utcnow()
    assignment.time_spent_seconds = time_spent
    assignment.dod        = dod
    assignment.disruption = disruption
    assignment.dm         = dm
    assignment.wonder     = wonder
    assignment.aq         = aq
    assignment.peer_ll_score = peer_ll

    # Update image aggregates
    all_ratings = PeerRating.query.filter_by(image_id=image.id).all()
    # Include the one we're about to add
    all_scores      = [r.peer_ll_score for r in all_ratings] + [peer_ll]
    all_dod         = [r.dod for r in all_ratings] + [dod]
    all_disruption  = [r.disruption for r in all_ratings] + [disruption]
    all_dm          = [r.dm for r in all_ratings] + [dm]
    all_wonder      = [r.wonder for r in all_ratings] + [wonder]
    all_aq          = [r.aq for r in all_ratings] + [aq]
    n = len(all_scores)

    image.peer_rating_count   = n
    image.peer_avg_score      = round(sum(all_scores) / n, 2)
    image.peer_avg_dod        = round(sum(all_dod) / n, 2)
    image.peer_avg_disruption = round(sum(all_disruption) / n, 2)
    image.peer_avg_dm         = round(sum(all_dm) / n, 2)
    image.peer_avg_wonder     = round(sum(all_wonder) / n, 2)
    image.peer_avg_aq         = round(sum(all_aq) / n, 2)
    image.update_blended_score()

    # Credit the rater: +1 credit, cap at 40
    rater = assignment.rater
    rater.reset_credits_if_needed()
    rater.rating_credits = min(40, (rater.rating_credits or 0) + 1)
    rater.lifetime_ratings_given = (rater.lifetime_ratings_given or 0) + 1

    db.session.commit()

    # Check for bias after every 20 ratings
    _check_rater_bias(assignment.rater_id)

    return rating


def _check_rater_bias(rater_id: int):
    """
    After 20+ completed ratings, compute per-module avg delta.
    If any module avg delta magnitude > 2.5 → flag rater.
    """
    MIN_RATINGS = 20
    THRESHOLD   = 2.5

    ratings = PeerRating.query.filter_by(rater_id=rater_id).all()
    if len(ratings) < MIN_RATINGS:
        return

    rater = User.query.get(rater_id)
    if not rater:
        return

    # Compare per-module peer scores vs DDI scores on the same images
    module_deltas = {'dod': [], 'disruption': [], 'dm': [], 'wonder': [], 'aq': []}
    for r in ratings:
        img = r.image
        if img.dod_score:        module_deltas['dod'].append(r.dod - img.dod_score)
        if img.disruption_score: module_deltas['disruption'].append(r.disruption - img.disruption_score)
        if img.dm_score:         module_deltas['dm'].append(r.dm - img.dm_score)
        if img.wonder_score:     module_deltas['wonder'].append(r.wonder - img.wonder_score)
        if img.aq_score:         module_deltas['aq'].append(r.aq - img.aq_score)

    bias_modules = []
    for mod, deltas in module_deltas.items():
        if deltas:
            avg_delta = sum(deltas) / len(deltas)
            if abs(avg_delta) > THRESHOLD:
                direction = 'over' if avg_delta > 0 else 'under'
                bias_modules.append(f'{mod.upper()} ({direction}-scores by avg {abs(avg_delta):.1f})')

    if bias_modules:
        rater.rating_bias_flag = True
        rater.rating_bias_note = 'Auto-detected: ' + ', '.join(bias_modules)
        db.session.commit()


def run_migrations(app):
    with app.app_context():
        try:
            db.session.rollback()
        except Exception:
            pass

        db.create_all()

        _col('users', 'full_name',            'VARCHAR(120)')
        _col('users', 'role',                 "VARCHAR(20) DEFAULT 'member'")
        _col('users', 'is_active',            'BOOLEAN DEFAULT TRUE')
        _col('users', 'last_login',           'TIMESTAMP')
        _col('users', 'security_question',    'VARCHAR(255)')
        _col('users', 'security_answer',      'VARCHAR(255)')
        _col('users', 'agreed_at',            'TIMESTAMP')
        _col('users', 'is_subscribed',        'BOOLEAN DEFAULT FALSE')
        _col('users', 'subscription_track',   'VARCHAR(20)')
        _col('users', 'subscription_plan',    'VARCHAR(20)')
        _col('users', 'subscribed_at',        'TIMESTAMP')
        _col('users', 'monthly_uploads_used', 'INTEGER DEFAULT 0')
        _col('users', 'monthly_reset_date',   'DATE')
        _col('users', 'rating_credits',       'INTEGER DEFAULT 20')
        _col('users', 'credits_reset_date',   'DATE')
        _col('users', 'lifetime_ratings_given', 'INTEGER DEFAULT 0')
        _col('users', 'rating_bias_flag',     'BOOLEAN DEFAULT FALSE')
        _col('users', 'rating_bias_note',     'TEXT')

        _col('images', 'card_path',               'VARCHAR(512)')
        _col('images', 'card_url',                'VARCHAR(512)')
        _col('images', 'thumb_url',               'VARCHAR(512)')
        _col('images', 'legal_declaration',       'BOOLEAN DEFAULT FALSE')
        _col('images', 'exif_camera',             'VARCHAR(120)')
        _col('images', 'exif_date_taken',         'VARCHAR(60)')
        _col('images', 'exif_settings',           'VARCHAR(180)')
        _col('images', 'exif_warning',            'TEXT')
        _col('images', 'soul_bonus',              'BOOLEAN DEFAULT FALSE')
        _col('images', 'audit_json',              'TEXT')
        _col('images', 'conditions',              'VARCHAR(180)')
        _col('images', 'photographer_name',       'VARCHAR(120)')
        _col('images', 'phash',                   'VARCHAR(64)')
        _col('images', 'is_calibration_example', 'BOOLEAN DEFAULT FALSE')
        _col('images', 'judge_referral',          'BOOLEAN DEFAULT FALSE')
        _col('images', 'camera_track',            'VARCHAR(20)')
        _col('images', 'is_public',               'BOOLEAN DEFAULT TRUE')
        _col('images', 'peer_avg_score',          'FLOAT')
        _col('images', 'peer_rating_count',       'INTEGER DEFAULT 0')
        _col('images', 'blended_score',           'FLOAT')
        _col('images', 'peer_avg_dod',            'FLOAT')
        _col('images', 'peer_avg_disruption',     'FLOAT')
        _col('images', 'peer_avg_dm',             'FLOAT')
        _col('images', 'peer_avg_wonder',         'FLOAT')
        _col('images', 'peer_avg_aq',             'FLOAT')

        # rating_assignments table
        try:
            db.session.execute(db.text('''
                CREATE TABLE IF NOT EXISTS rating_assignments (
                    id SERIAL PRIMARY KEY,
                    rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    assigned_at TIMESTAMP DEFAULT NOW(),
                    started_at TIMESTAMP,
                    submitted_at TIMESTAMP,
                    time_spent_seconds INTEGER,
                    dod FLOAT,
                    disruption FLOAT,
                    dm FLOAT,
                    wonder FLOAT,
                    aq FLOAT,
                    peer_ll_score FLOAT,
                    status VARCHAR(20) DEFAULT \'assigned\',
                    UNIQUE(rater_id, image_id)
                )
            '''))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[migration] rating_assignments: {e}')

        # peer_ratings table
        try:
            db.session.execute(db.text('''
                CREATE TABLE IF NOT EXISTS peer_ratings (
                    id SERIAL PRIMARY KEY,
                    rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    genre VARCHAR(60) NOT NULL,
                    dod FLOAT NOT NULL,
                    disruption FLOAT NOT NULL,
                    dm FLOAT NOT NULL,
                    wonder FLOAT NOT NULL,
                    aq FLOAT NOT NULL,
                    peer_ll_score FLOAT NOT NULL,
                    delta_from_ddi FLOAT,
                    time_spent_seconds INTEGER,
                    rated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(rater_id, image_id)
                )
            '''))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[migration] peer_ratings: {e}')


def _col(table, column, col_type):
    sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};"
    try:
        db.session.execute(db.text(sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[migration] {table}.{column}: {e}")
