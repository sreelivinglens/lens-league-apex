"""
models.py — Lens League Apex
Added in this version:
  - User: country, state, city, declared_camera, camera_mismatch_count, league_suspended
  - Migration SQL at bottom of app.py startup handles new columns safely
"""

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
    password_hash     = db.Column(db.String(256), nullable=True)   # nullable — Google OAuth users have no password
    google_id         = db.Column(db.String(128), unique=True, nullable=True, index=True)
    onboarding_complete = db.Column(db.Boolean, default=False, nullable=False)
    full_name         = db.Column(db.String(120), nullable=True)

    # Location — collected at registration, used for city rankings
    country           = db.Column(db.String(80),  nullable=True)
    state             = db.Column(db.String(80),  nullable=True)
    city              = db.Column(db.String(80),  nullable=True)

    # Self-declared camera/phone — brand data for sponsors
    # EXIF supersedes this for all rankings and leaderboard filters
    declared_camera   = db.Column(db.String(120), nullable=True)

    # League integrity — camera/phone mismatch tracking
    # Incremented each time EXIF contradicts declared league (mobile user, camera EXIF)
    camera_mismatch_count = db.Column(db.Integer, default=0)
    # Set True on strike 3 — suspends contest entries until admin review
    league_suspended  = db.Column(db.Boolean, default=False)
    league_suspended_at = db.Column(db.DateTime, nullable=True)
    league_suspended_reason = db.Column(db.Text, nullable=True)

    role              = db.Column(db.String(20), default='member', nullable=False)
    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    last_login        = db.Column(db.DateTime, nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    security_question = db.Column(db.String(255), nullable=True)
    security_answer   = db.Column(db.String(255), nullable=True)

    agreed_at         = db.Column(db.DateTime, nullable=True)

    is_subscribed        = db.Column(db.Boolean, default=False)
    subscription_track   = db.Column(db.String(20), nullable=True)   # 'camera' | 'mobile'
    subscription_plan    = db.Column(db.String(20), nullable=True)   # 'monthly' | 'annual'
    subscribed_at        = db.Column(db.DateTime, nullable=True)
    monthly_uploads_used = db.Column(db.Integer, default=0)
    monthly_reset_date   = db.Column(db.Date, nullable=True)

    # Peer rating credits
    rating_credits       = db.Column(db.Integer, default=0)
    credits_reset_date   = db.Column(db.Date, nullable=True)
    lifetime_ratings_given = db.Column(db.Integer, default=0)
    peer_pool_unlocks    = db.Column(db.Integer, default=0)
    rating_bias_flag     = db.Column(db.Boolean, default=False)
    rating_bias_note     = db.Column(db.Text, nullable=True)
    razorpay_sub_id      = db.Column(db.String(64), nullable=True)

    images            = db.relationship('Image', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

    @property
    def display_league(self):
        """Human-readable league name for UI"""
        if self.subscription_track == 'camera':
            return 'Camera League'
        if self.subscription_track == 'mobile':
            return 'Mobile League'
        return None

    @property
    def league_icon(self):
        if self.subscription_track == 'camera':
            return '📷'
        if self.subscription_track == 'mobile':
            return '📱'
        return ''

    @property
    def location_display(self):
        """e.g. 'Bengaluru, Karnataka, India' or 'London, England, UK'"""
        parts = [p for p in [self.city, self.state, self.country] if p]
        return ', '.join(parts) if parts else None

    def record_mismatch(self, image_id, exif_camera, db_session):
        """
        Called when EXIF camera contradicts declared league.
        Returns strike number (1, 2, or 3).
        Strike 3 sets league_suspended = True.
        """
        self.camera_mismatch_count = (self.camera_mismatch_count or 0) + 1
        strike = self.camera_mismatch_count

        if strike >= 3:
            self.league_suspended = True
            self.league_suspended_at = datetime.utcnow()
            self.league_suspended_reason = (
                f'Three or more images uploaded with EXIF camera data '
                f'inconsistent with your declared league. '
                f'Latest: image #{image_id}, camera: {exif_camera}. '
                f'Contact verify@lensleague.com to resolve.'
            )

        db_session.commit()
        return strike

    def reset_credits_if_needed(self):
        today = date.today()
        if self.credits_reset_date is None:
            self.credits_reset_date = today
            return True
        return False

    @property
    def credits_to_next_unlock(self):
        if not self.lifetime_ratings_given:
            return 5
        return 5 - (self.lifetime_ratings_given % 5)

    @property
    def total_unlocks_earned(self):
        return (self.lifetime_ratings_given or 0) // 5


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

    camera_track        = db.Column(db.String(20), nullable=True)
    is_public           = db.Column(db.Boolean, default=True,  nullable=False)

    legal_declaration   = db.Column(db.Boolean, default=False)

    exif_status         = db.Column(db.String(20),  default='unverified')
    exif_camera         = db.Column(db.String(120), nullable=True)
    exif_lens           = db.Column(db.String(180), nullable=True)
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

    is_in_peer_pool     = db.Column(db.Boolean, default=False)
    pool_entry_chosen_at = db.Column(db.DateTime, nullable=True)

    peer_avg_score      = db.Column(db.Float, nullable=True)
    peer_rating_count   = db.Column(db.Integer, default=0)
    blended_score       = db.Column(db.Float, nullable=True)
    peer_avg_dod        = db.Column(db.Float, nullable=True)
    peer_avg_disruption = db.Column(db.Float, nullable=True)
    peer_avg_dm         = db.Column(db.Float, nullable=True)
    peer_avg_wonder     = db.Column(db.Float, nullable=True)
    peer_avg_aq         = db.Column(db.Float, nullable=True)

    is_calibration_example = db.Column(db.Boolean, default=False, nullable=False)
    judge_referral         = db.Column(db.Boolean, default=False, nullable=False)
    peer_review_pending    = db.Column(db.Boolean, default=False, nullable=False)

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
        """
        Zone 1 — delta within ±1.5   : blend applies (80% DDI + 20% peer) → used for POTY
        Zone 2 — delta ±1.5 to ±3.0  : blend applies + peer_review_flag set → admin visibility
        Zone 3 — delta > ±3.0        : DDI score protected → needs_review + judge_referral triggered
        Fewer than 5 peer ratings     : DDI score used unchanged
        """
        if self.peer_rating_count and self.peer_rating_count >= 5                 and self.peer_avg_score is not None and self.score is not None:
            delta = abs(self.peer_avg_score - self.score)
            if delta <= 1.5:
                # Zone 1 — peers agree, blend applies
                self.blended_score = round(self.score * 0.80 + self.peer_avg_score * 0.20, 2)
            elif delta <= 3.0:
                # Zone 2 — moderate divergence, blend applies but flag for admin visibility
                self.blended_score = round(self.score * 0.80 + self.peer_avg_score * 0.20, 2)
                self.peer_review_pending = True
            else:
                # Zone 3 — large divergence, DDI protected, trigger jury + admin review
                self.blended_score = self.score
                self.needs_review   = True
                self.judge_referral = True
        else:
            self.blended_score = self.score

    def __repr__(self):
        return f'<Image {self.id} – {self.asset_name} ({self.score})>'


# ── All other models unchanged — RatingAssignment, PeerRating, PeerPoolEntry,
#    ContestEntry, BowSubmission, OpenContestEntry, CalibrationNote,
#    CalibrationLog, ImageReport stay exactly as before ──────────────────────

class RatingAssignment(db.Model):
    __tablename__ = 'rating_assignments'
    id              = db.Column(db.Integer, primary_key=True)
    rater_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    assigned_at     = db.Column(db.DateTime, default=datetime.utcnow)
    started_at      = db.Column(db.DateTime, nullable=True)
    submitted_at    = db.Column(db.DateTime, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    status          = db.Column(db.String(20), default='assigned')
    dod        = db.Column(db.Float); disruption = db.Column(db.Float)
    dm         = db.Column(db.Float); wonder     = db.Column(db.Float)
    aq         = db.Column(db.Float); peer_ll_score = db.Column(db.Float)
    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='rating_assignments', lazy=True)
    image  = db.relationship('Image', foreign_keys=[image_id],  backref='rating_assignments', lazy=True)
    __table_args__ = (db.UniqueConstraint('rater_id', 'image_id', name='uq_rating_assignment'),)


class PeerRating(db.Model):
    __tablename__ = 'peer_ratings'
    id              = db.Column(db.Integer, primary_key=True)
    rater_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre           = db.Column(db.String(60), nullable=False)
    dod             = db.Column(db.Float, nullable=False)
    disruption      = db.Column(db.Float, nullable=False)
    dm              = db.Column(db.Float, nullable=False)
    wonder          = db.Column(db.Float, nullable=False)
    aq              = db.Column(db.Float, nullable=False)
    peer_ll_score   = db.Column(db.Float, nullable=False)
    delta_from_ddi  = db.Column(db.Float, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    rated_at        = db.Column(db.DateTime, default=datetime.utcnow)
    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='peer_ratings_given', lazy=True)
    image  = db.relationship('Image', foreign_keys=[image_id],  backref='peer_ratings_received', lazy=True)
    __table_args__ = (db.UniqueConstraint('rater_id', 'image_id', name='uq_peer_rating'),)


class PeerPoolEntry(db.Model):
    __tablename__ = 'peer_pool_entries'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id      = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    unlock_number = db.Column(db.Integer, nullable=False)
    chosen_at     = db.Column(db.DateTime, default=datetime.utcnow)
    status        = db.Column(db.String(20), default='active')
    user  = db.relationship('User',  foreign_keys=[user_id],  backref='pool_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='pool_entries', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'unlock_number', name='uq_pool_entry_unlock'),)


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
    __table_args__ = (db.UniqueConstraint('user_id', 'genre', 'track', 'contest_month', 'contest_type', name='uq_contest_entry'),)


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
        try: return json.loads(self.image_ids_json)
        except: return []
    def set_image_ids(self, ids): self.image_ids_json = json.dumps(ids)


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
    __table_args__ = (db.UniqueConstraint('user_id', 'genre', 'platform_year', name='uq_open_contest_entry'),)


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


# ── NEW MIGRATION SQL to add to app.py startup block ──────────────────────────
NEW_MIGRATION_SQL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(80)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS declared_camera VARCHAR(120)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS camera_mismatch_count INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_reason TEXT",
]
# Add these to the _migrations list in app.py startup


# ── Peer rating helpers (unchanged from v27) ───────────────────────────────────

def get_or_assign_next_image(rater_id: int):
    from datetime import timedelta
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

    in_progress = RatingAssignment.query.filter_by(rater_id=rater_id, status='started').first()
    if in_progress:
        return in_progress
    fresh = RatingAssignment.query.filter_by(rater_id=rater_id, status='assigned').first()
    if fresh:
        return fresh

    rater = User.query.get(rater_id)
    if not rater:
        return None

    already_seen = db.session.query(RatingAssignment.image_id).filter(
        RatingAssignment.rater_id == rater_id,
        RatingAssignment.status.in_(['assigned', 'started', 'submitted']),
    ).subquery()

    eligible = (
        Image.query
        .join(User, Image.user_id == User.id)
        .filter(
            Image.status == 'scored', Image.is_public == True,
            Image.is_flagged == False, Image.needs_review == False,
            Image.score != None, Image.user_id != rater_id,
            User.is_subscribed == True,
            Image.id.notin_(already_seen),
        )
        .order_by(Image.peer_rating_count.asc().nullsfirst(), Image.scored_at.asc())
        .first()
    )

    if not eligible:
        return None

    assignment = RatingAssignment(rater_id=rater_id, image_id=eligible.id, status='assigned')
    db.session.add(assignment)
    db.session.commit()
    return assignment


def submit_peer_rating(assignment, dod, disruption, dm, wonder, aq, time_spent):
    from engine.scoring import calculate_score, normalise_genre
    image = assignment.image
    genre = normalise_genre(image.genre)
    peer_ll, _, _, _ = calculate_score(genre, dod, disruption, dm, wonder, aq)
    delta = round(peer_ll - (image.score or 0), 2)

    rating = PeerRating(
        rater_id=assignment.rater_id, image_id=assignment.image_id,
        genre=genre, dod=dod, disruption=disruption, dm=dm, wonder=wonder, aq=aq,
        peer_ll_score=peer_ll, delta_from_ddi=delta, time_spent_seconds=time_spent,
    )
    db.session.add(rating)

    assignment.status = 'submitted'
    assignment.submitted_at = datetime.utcnow()
    assignment.time_spent_seconds = time_spent
    assignment.dod = dod; assignment.disruption = disruption
    assignment.dm = dm; assignment.wonder = wonder; assignment.aq = aq
    assignment.peer_ll_score = peer_ll

    all_ratings = PeerRating.query.filter_by(image_id=image.id).all()
    all_scores = [r.peer_ll_score for r in all_ratings] + [peer_ll]
    all_dod = [r.dod for r in all_ratings] + [dod]
    all_dis = [r.disruption for r in all_ratings] + [disruption]
    all_dm  = [r.dm for r in all_ratings] + [dm]
    all_won = [r.wonder for r in all_ratings] + [wonder]
    all_aq  = [r.aq for r in all_ratings] + [aq]
    n = len(all_scores)

    image.peer_rating_count   = n
    image.peer_avg_score      = round(sum(all_scores)/n, 2)
    image.peer_avg_dod        = round(sum(all_dod)/n, 2)
    image.peer_avg_disruption = round(sum(all_dis)/n, 2)
    image.peer_avg_dm         = round(sum(all_dm)/n, 2)
    image.peer_avg_wonder     = round(sum(all_won)/n, 2)
    image.peer_avg_aq         = round(sum(all_aq)/n, 2)
    image.update_blended_score()

    rater = assignment.rater
    rater.reset_credits_if_needed()
    rater.rating_credits = (rater.rating_credits or 0) + 1
    rater.lifetime_ratings_given = (rater.lifetime_ratings_given or 0) + 1

    db.session.commit()
    _check_rater_bias(assignment.rater_id)
    return rating


def _check_rater_bias(rater_id):
    """
    Runs after every rating submission.
    1. Checks rater pattern bias (needs 20+ ratings, threshold 2.5 avg delta per dimension)
    2. Checks if this specific rating pushed any image into Zone 3 (delta > 3.0)
       — if so, sets needs_review + judge_referral on the image automatically
    """
    MIN_RATINGS = 20; THRESHOLD = 2.5; ZONE3_DELTA = 3.0

    ratings = PeerRating.query.filter_by(rater_id=rater_id).all()
    rater = User.query.get(rater_id)
    if not rater:
        return

    # ── Rater pattern bias check (requires 20+ ratings) ──────────────────────
    if len(ratings) >= MIN_RATINGS:
        module_deltas = {'dod': [], 'disruption': [], 'dm': [], 'wonder': [], 'aq': []}
        for r in ratings:
            img = r.image
            if img and img.dod_score:        module_deltas['dod'].append(r.dod - img.dod_score)
            if img and img.disruption_score: module_deltas['disruption'].append(r.disruption - img.disruption_score)
            if img and img.dm_score:         module_deltas['dm'].append(r.dm - img.dm_score)
            if img and img.wonder_score:     module_deltas['wonder'].append(r.wonder - img.wonder_score)
            if img and img.aq_score:         module_deltas['aq'].append(r.aq - img.aq_score)
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

    # ── Per-image Zone 3 check — runs on every rating regardless of count ─────
    # For each image this rater has rated, check if the current peer avg
    # has crossed Zone 3 threshold and trigger review if so
    for r in ratings:
        img = r.image
        if not img or not img.score or img.peer_rating_count < 5:
            continue
        if img.peer_avg_score is None:
            continue
        delta = abs(img.peer_avg_score - img.score)
        if delta > ZONE3_DELTA and not img.needs_review:
            img.needs_review   = True
            img.judge_referral = True

    db.session.commit()


# ── Weekly Challenge ──────────────────────────────────────────────────────────

class WeeklyChallenge(db.Model):
    __tablename__ = 'weekly_challenges'

    id                = db.Column(db.Integer, primary_key=True)
    week_ref          = db.Column(db.String(10), unique=True, nullable=False, index=True)
    prompt_title      = db.Column(db.String(120), nullable=False)
    prompt_body       = db.Column(db.Text, nullable=True)
    opens_at          = db.Column(db.DateTime, nullable=False)
    closes_at         = db.Column(db.DateTime, nullable=False)
    results_at        = db.Column(db.DateTime, nullable=True)
    sponsor_name      = db.Column(db.String(120), nullable=True)
    sponsor_prize     = db.Column(db.Text, nullable=True)
    is_active         = db.Column(db.Boolean, default=True)
    results_published = db.Column(db.Boolean, default=False)
    created_by        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship('WeeklySubmission', backref='challenge', lazy='dynamic')

    @property
    def is_open(self):
        now = datetime.utcnow()
        return self.opens_at <= now <= self.closes_at

    @property
    def is_closed(self):
        return datetime.utcnow() > self.closes_at

    @property
    def submission_count(self):
        return self.submissions.count()

    def user_submission_count(self, user_id):
        return self.submissions.filter_by(user_id=user_id).count()


class WeeklySubmission(db.Model):
    __tablename__ = 'weekly_submissions'

    id           = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('weekly_challenges.id'), nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id     = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    is_subscriber= db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    result_rank  = db.Column(db.Integer, nullable=True)
    result_note  = db.Column(db.Text, nullable=True)

    user  = db.relationship('User',  foreign_keys=[user_id],  backref='weekly_submissions', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='weekly_submissions', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('challenge_id', 'image_id', name='uq_weekly_sub_image'),
    )


class ChallengeTopup(db.Model):
    """
    One row per extra image purchase for weekly challenge.
    Allows users who have used their base images to buy more at Rs.49 each.
    Max total: 6 for subscribed, 4 for free.
    """
    __tablename__ = 'challenge_topups'

    id           = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('weekly_challenges.id'), nullable=False)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    quantity     = db.Column(db.Integer, nullable=False)          # images purchased
    amount_paise = db.Column(db.Integer, nullable=False)          # 4900 per image
    razorpay_order_id   = db.Column(db.String(64), nullable=True)
    razorpay_payment_id = db.Column(db.String(64), nullable=True)
    status       = db.Column(db.String(20), default='pending')    # pending | paid | failed
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user      = db.relationship('User',            foreign_keys=[user_id],      backref='challenge_topups', lazy=True)
    challenge = db.relationship('WeeklyChallenge', foreign_keys=[challenge_id], backref='topups',           lazy=True)
