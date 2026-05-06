"""
models.py — Lens League Apex
v30: Added jury system + RAW verification models
  - Image: 9 new columns for jury scoring and RAW verification
  - New: Judge, JudgeCategoryAssignment, ContestJudgeConfig,
         JudgeAssignment, JudgeScore, RawSubmission
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
    camera_mismatch_count   = db.Column(db.Integer, default=0)
    league_suspended        = db.Column(db.Boolean, default=False)
    league_suspended_at     = db.Column(db.DateTime, nullable=True)
    league_suspended_reason = db.Column(db.Text, nullable=True)

    role              = db.Column(db.String(20), default='member', nullable=False)
    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    last_login        = db.Column(db.DateTime, nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    security_question    = db.Column(db.String(255), nullable=True)
    security_answer      = db.Column(db.String(255), nullable=True)
    email_verify_token   = db.Column(db.String(64),  nullable=True)  # cleared after verification

    agreed_at         = db.Column(db.DateTime, nullable=True)

    # v52 — legal consent tracking
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    terms_version     = db.Column(db.String(20), nullable=True)
    signup_ip         = db.Column(db.String(45), nullable=True)

    # v53 — POTY welcome banner
    poty_banner_dismissed = db.Column(db.Boolean, default=False)

    is_subscribed        = db.Column(db.Boolean, default=False)
    subscription_track   = db.Column(db.String(20), nullable=True)
    subscription_plan    = db.Column(db.String(20), nullable=True)
    subscribed_at        = db.Column(db.DateTime, nullable=True)
    monthly_uploads_used = db.Column(db.Integer, default=0)
    monthly_reset_date   = db.Column(db.Date, nullable=True)

    # Peer rating credits
    rating_credits         = db.Column(db.Integer, default=0)
    credits_reset_date     = db.Column(db.Date, nullable=True)
    lifetime_ratings_given = db.Column(db.Integer, default=0)
    peer_pool_unlocks      = db.Column(db.Integer, default=0)
    rating_bias_flag       = db.Column(db.Boolean, default=False)
    rating_bias_note       = db.Column(db.Text, nullable=True)
    razorpay_sub_id        = db.Column(db.String(64), nullable=True)

    # v33 — Points / Loyalty Engine
    points_balance         = db.Column(db.Float,   default=0.0,  nullable=False)
    points_lifetime_earned = db.Column(db.Float,   default=0.0,  nullable=False)
    points_last_expiry     = db.Column(db.Date,    nullable=True)
    # 6-6-12 residency clock — increments monthly while subscribed or dormant
    residency_months       = db.Column(db.Integer, default=0,    nullable=False)
    residency_started_at   = db.Column(db.DateTime, nullable=True)
    # Tier jump tracking — last tier seen, used to detect tier-up on each score
    tier_jump_last_tier    = db.Column(db.String(60), nullable=True)
    tier_jump_last_checked_at = db.Column(db.DateTime, nullable=True)

    images = db.relationship('Image', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

    @property
    def display_league(self):
        if self.subscription_track == 'camera': return 'Camera League'
        if self.subscription_track == 'mobile': return 'Mobile League'
        return None

    @property
    def league_icon(self):
        if self.subscription_track == 'camera': return '📷'
        if self.subscription_track == 'mobile': return '📱'
        return ''

    @property
    def location_display(self):
        parts = [p for p in [self.city, self.state, self.country] if p]
        return ', '.join(parts) if parts else None

    def record_mismatch(self, image_id, exif_camera, db_session):
        self.camera_mismatch_count = (self.camera_mismatch_count or 0) + 1
        strike = self.camera_mismatch_count
        if strike >= 3:
            self.league_suspended        = True
            self.league_suspended_at     = datetime.utcnow()
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
        if not self.lifetime_ratings_given: return 5
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
    is_public           = db.Column(db.Boolean, default=True, nullable=False)

    legal_declaration   = db.Column(db.Boolean, default=False)

    exif_status         = db.Column(db.String(20),  default='unverified')
    exif_camera         = db.Column(db.String(120), nullable=True)
    exif_lens           = db.Column(db.String(180), nullable=True)
    exif_date_taken     = db.Column(db.String(60),  nullable=True)
    exif_settings       = db.Column(db.String(180), nullable=True)
    exif_warning        = db.Column(db.Text,        nullable=True)
    # v30: EXIF capture metadata for RAW comparison
    exif_original_width    = db.Column(db.Integer,     nullable=True)
    exif_original_height   = db.Column(db.Integer,     nullable=True)
    exif_capture_datetime  = db.Column(db.String(40),  nullable=True)

    dod_score           = db.Column(db.Float, nullable=True)
    disruption_score    = db.Column(db.Float, nullable=True)
    dm_score            = db.Column(db.Float, nullable=True)
    wonder_score        = db.Column(db.Float, nullable=True)
    aq_score            = db.Column(db.Float, nullable=True)
    score               = db.Column(db.Float, nullable=True)
    tier                = db.Column(db.String(60),  nullable=True)
    archetype           = db.Column(db.String(120), nullable=True)
    soul_bonus          = db.Column(db.Boolean, default=False)

    is_in_peer_pool      = db.Column(db.Boolean, default=False)
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

    ai_suspicion        = db.Column(db.Float,   default=0.0,  nullable=True)
    ai_suspicion_reason = db.Column(db.Text,                  nullable=True)
    needs_review        = db.Column(db.Boolean, default=False, nullable=False)
    is_flagged          = db.Column(db.Boolean, default=False, nullable=False)
    flagged_reason      = db.Column(db.Text,                  nullable=True)
    flagged_at          = db.Column(db.DateTime,              nullable=True)

    # v30: RAW verification columns
    raw_verification_required = db.Column(db.Boolean, default=False, nullable=False)
    raw_verified              = db.Column(db.Boolean, default=False, nullable=False)
    raw_disqualified          = db.Column(db.Boolean, default=False, nullable=False)
    scoring_flash             = db.Column(db.Text,    nullable=True)   # v34 points flash

    # v30: Jury scoring columns
    in_judge_pool         = db.Column(db.Boolean, default=False, nullable=False)
    judge_score           = db.Column(db.Float,   nullable=True)
    judge_final_score     = db.Column(db.Float,   nullable=True)
    judge_flagged         = db.Column(db.Boolean, default=False, nullable=False)
    judge_flag_type       = db.Column(db.String(40), nullable=True)
    # contest_result_status: null | provisional | published
    contest_result_status = db.Column(db.String(20), nullable=True)

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
        Zone 1 — delta within ±1.5   : blend (80% DDI + 20% peer). Silent.
        Zone 2 — delta ±1.5 to ±3.0  : blend + peer_review_pending flag.
        Zone 3 — delta > ±3.0        : DDI protected. needs_review + judge_referral.
        Fewer than 5 peer ratings     : DDI unchanged.
        POTY always uses img.score (pure DDI). Jury cannot affect POTY for Zone 3.
        """
        if (self.peer_rating_count and self.peer_rating_count >= 5
                and self.peer_avg_score is not None and self.score is not None):
            delta = abs(self.peer_avg_score - self.score)
            if delta <= 1.5:
                self.blended_score = round(self.score * 0.80 + self.peer_avg_score * 0.20, 2)
            elif delta <= 3.0:
                self.blended_score       = round(self.score * 0.80 + self.peer_avg_score * 0.20, 2)
                self.peer_review_pending = True
            else:
                # Zone 3 — DDI protected
                self.blended_score  = self.score
                self.needs_review   = True
                self.judge_referral = True
        else:
            self.blended_score = self.score

    def __repr__(self):
        return f'<Image {self.id} – {self.asset_name} ({self.score})>'


# ── Existing models — unchanged ───────────────────────────────────────────────

class RatingAssignment(db.Model):
    __tablename__ = 'rating_assignments'
    id                 = db.Column(db.Integer, primary_key=True)
    rater_id           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id           = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    assigned_at        = db.Column(db.DateTime, default=datetime.utcnow)
    started_at         = db.Column(db.DateTime, nullable=True)
    submitted_at       = db.Column(db.DateTime, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    status             = db.Column(db.String(20), default='assigned')
    dod          = db.Column(db.Float); disruption = db.Column(db.Float)
    dm           = db.Column(db.Float); wonder     = db.Column(db.Float)
    aq           = db.Column(db.Float); peer_ll_score = db.Column(db.Float)
    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='rating_assignments', lazy=True)
    image  = db.relationship('Image', foreign_keys=[image_id],  backref='rating_assignments', lazy=True)
    __table_args__ = (db.UniqueConstraint('rater_id', 'image_id', name='uq_rating_assignment'),)


class PeerRating(db.Model):
    __tablename__ = 'peer_ratings'
    id                 = db.Column(db.Integer, primary_key=True)
    rater_id           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id           = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre              = db.Column(db.String(60), nullable=False)
    dod                = db.Column(db.Float, nullable=False)
    disruption         = db.Column(db.Float, nullable=False)
    dm                 = db.Column(db.Float, nullable=False)
    wonder             = db.Column(db.Float, nullable=False)
    aq                 = db.Column(db.Float, nullable=False)
    peer_ll_score      = db.Column(db.Float, nullable=False)
    delta_from_ddi     = db.Column(db.Float, nullable=True)
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    rated_at           = db.Column(db.DateTime, default=datetime.utcnow)
    rater  = db.relationship('User',  foreign_keys=[rater_id],  backref='peer_ratings_given',    lazy=True)
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
    genre         = db.Column(db.String(60), nullable=False)
    track         = db.Column(db.String(20), nullable=False)
    contest_month = db.Column(db.String(7),  nullable=False)
    contest_type  = db.Column(db.String(20), default='monthly')
    entered_at    = db.Column(db.DateTime,   default=datetime.utcnow)
    user  = db.relationship('User',  foreign_keys=[user_id],  backref='contest_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='contest_entries', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'genre', 'track', 'contest_month', 'contest_type', name='uq_contest_entry'),)


class BowSubmission(db.Model):
    """
    Body of Work submission.
    Entry window: 1 Dec – 31 Dec each year.
    Subscribers select from existing images (free); non-subscribers pay Rs. 1,000.
    status flow: draft → submitted → under_review → qualified | rejected | winner
    """
    __tablename__ = 'bow_submissions'
    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    platform_year      = db.Column(db.Integer, nullable=False)

    # Submission content
    series_title       = db.Column(db.String(180), nullable=False)
    thematic_statement = db.Column(db.Text, nullable=False)   # brief description
    location           = db.Column(db.String(180), nullable=True)
    period_of_work     = db.Column(db.String(120), nullable=True)  # e.g. "Jan 2025 – Mar 2026"
    significance       = db.Column(db.String(300), nullable=True)  # single line
    other_details      = db.Column(db.Text, nullable=True)
    image_ids_json     = db.Column(db.Text, nullable=False)   # JSON list of image IDs (6–10)
    image_count        = db.Column(db.Integer, nullable=False)
    images_agreed      = db.Column(db.Boolean, default=False, nullable=False)  # consent checkbox

    # Payment — only for non-subscribers
    is_subscriber      = db.Column(db.Boolean, default=False, nullable=False)
    amount_paise       = db.Column(db.Integer, default=0)     # 100000 = Rs. 1,000
    payment_ref        = db.Column(db.String(120), nullable=True)
    payment_status     = db.Column(db.String(20), default='free')  # free | pending | paid

    # Status
    # status: draft | submitted | under_review | qualified | rejected | winner
    status             = db.Column(db.String(20), default='submitted')
    qualifier_emailed  = db.Column(db.Boolean, default=False)
    submitted_at       = db.Column(db.DateTime, default=datetime.utcnow)
    notes              = db.Column(db.Text, nullable=True)   # admin notes

    user = db.relationship('User', foreign_keys=[user_id], backref='bow_submissions', lazy=True)

    def get_image_ids(self):
        try: return json.loads(self.image_ids_json)
        except: return []

    def set_image_ids(self, ids):
        self.image_ids_json = json.dumps(ids)
        self.image_count    = len(ids)


class OpenContestEntry(db.Model):
    """
    Open contest entry — any user, any image, no theme.
    Pricing: first image free per user per year; Rs. 200 per additional image.
    status flow: pending_payment → confirmed | disqualified
    Results: top 10 qualifier email in Jan cooling period, winners announced 1 Feb.
    """
    __tablename__ = 'open_contest_entries'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id      = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    genre         = db.Column(db.String(60), nullable=False)
    platform_year = db.Column(db.Integer,   nullable=False)
    is_free_slot  = db.Column(db.Boolean,   default=False, nullable=False)  # True for first image
    amount_paise  = db.Column(db.Integer,   default=0)    # 0 if free slot, 20000 = Rs. 200
    payment_ref   = db.Column(db.String(120), nullable=True)
    # status: pending_payment | confirmed | disqualified
    status           = db.Column(db.String(20), default='confirmed')
    qualifier_emailed= db.Column(db.Boolean, default=False)
    entered_at    = db.Column(db.DateTime,  default=datetime.utcnow)
    user  = db.relationship('User',  foreign_keys=[user_id],  backref='open_contest_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='open_contest_entries', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'image_id', 'platform_year', name='uq_open_contest_entry'),)


class CalibrationNote(db.Model):
    __tablename__ = 'calibration_notes'
    id              = db.Column(db.Integer, primary_key=True)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    admin_id        = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    genre           = db.Column(db.String(60), nullable=False)
    module          = db.Column(db.String(20), nullable=False)
    original_score  = db.Column(db.Float, nullable=True)
    corrected_score = db.Column(db.Float, nullable=True)
    reason          = db.Column(db.Text, nullable=False)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    image = db.relationship('Image', foreign_keys=[image_id], backref='calibration_notes',       lazy=True)
    admin = db.relationship('User',  foreign_keys=[admin_id], backref='admin_calibration_notes', lazy=True)


class CalibrationLog(db.Model):
    __tablename__ = 'calibration_logs'
    id          = db.Column(db.Integer, primary_key=True)
    genre       = db.Column(db.String(60), nullable=False)
    image_count = db.Column(db.Integer,   nullable=True)
    avg_score   = db.Column(db.Float,     nullable=True)
    avg_dod     = db.Column(db.Float,     nullable=True)
    avg_dis     = db.Column(db.Float,     nullable=True)
    avg_dm      = db.Column(db.Float,     nullable=True)
    avg_wonder  = db.Column(db.Float,     nullable=True)
    avg_aq      = db.Column(db.Float,     nullable=True)
    note        = db.Column(db.Text,      nullable=True)
    logged_by   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    logged_at   = db.Column(db.DateTime, default=datetime.utcnow)


class ImageReport(db.Model):
    __tablename__ = 'image_reports'
    id          = db.Column(db.Integer, primary_key=True)
    image_id    = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    reason      = db.Column(db.String(40), nullable=False)
    detail      = db.Column(db.Text,       nullable=True)
    reported_at = db.Column(db.DateTime,   default=datetime.utcnow)
    status      = db.Column(db.String(20), default='open')
    image    = db.relationship('Image', backref=db.backref('reports',       lazy='dynamic'))
    reporter = db.relationship('User',  backref=db.backref('filed_reports', lazy='dynamic'))


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
    is_active          = db.Column(db.Boolean, default=True)
    results_published  = db.Column(db.Boolean, default=False)
    results_hold_until = db.Column(db.DateTime, nullable=True)
    created_by         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
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
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'),   nullable=False)
    image_id     = db.Column(db.Integer, db.ForeignKey('images.id'),  nullable=False)
    is_subscriber= db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    result_rank  = db.Column(db.Integer, nullable=True)
    result_note  = db.Column(db.Text,    nullable=True)
    user  = db.relationship('User',  foreign_keys=[user_id],  backref='weekly_submissions', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='weekly_submissions', lazy=True)
    __table_args__ = (db.UniqueConstraint('challenge_id', 'image_id', name='uq_weekly_sub_image'),)


class ChallengeTopup(db.Model):
    __tablename__ = 'challenge_topups'
    id                  = db.Column(db.Integer, primary_key=True)
    challenge_id        = db.Column(db.Integer, db.ForeignKey('weekly_challenges.id'), nullable=False)
    user_id             = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    quantity            = db.Column(db.Integer, nullable=False)
    amount_paise        = db.Column(db.Integer, nullable=False)
    razorpay_order_id   = db.Column(db.String(64), nullable=True)
    razorpay_payment_id = db.Column(db.String(64), nullable=True)
    status              = db.Column(db.String(20), default='pending')
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    user      = db.relationship('User',            foreign_keys=[user_id],      backref='challenge_topups', lazy=True)
    challenge = db.relationship('WeeklyChallenge', foreign_keys=[challenge_id], backref='topups',           lazy=True)


# ── v30: Jury System + RAW Verification models ────────────────────────────────

class Judge(db.Model):
    """
    A judge may or may not have a platform User account.
    user_id is nullable — external judges invited by email alone are valid.
    status flow: invited → pending_approval → approved | suspended
    """
    __tablename__ = 'judges'

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    status            = db.Column(db.String(20), default='invited', nullable=False)
    invite_token      = db.Column(db.String(64), unique=True, nullable=True)
    invite_sent_at    = db.Column(db.DateTime, nullable=True)
    invite_expires_at = db.Column(db.DateTime, nullable=True)

    # Profile — submitted by judge during onboarding
    name              = db.Column(db.String(120), nullable=True)
    email             = db.Column(db.String(120), unique=True, nullable=False)
    phone             = db.Column(db.String(40),  nullable=True)
    address           = db.Column(db.Text,        nullable=True)
    city              = db.Column(db.String(80),  nullable=True)
    country           = db.Column(db.String(80),  nullable=True)
    photo_key         = db.Column(db.String(512), nullable=True)   # R2 key
    years_experience  = db.Column(db.Integer,     nullable=True)
    judged_before     = db.Column(db.Boolean,     default=False)
    bio               = db.Column(db.Text,        nullable=True)   # 300 words max enforced in form
    agreed_terms      = db.Column(db.Boolean,     default=False)
    agreed_at         = db.Column(db.DateTime,    nullable=True)

    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at       = db.Column(db.DateTime, nullable=True)
    approved_by       = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    platform_user     = db.relationship('User', foreign_keys=[user_id],    backref='judge_profile', lazy=True)
    approver          = db.relationship('User', foreign_keys=[approved_by], backref='judges_approved', lazy=True)
    category_assignments = db.relationship('JudgeCategoryAssignment', backref='owning_judge', lazy='dynamic',
                                           cascade='all, delete-orphan')
    assignments       = db.relationship('JudgeAssignment', backref='assigned_judge', lazy='dynamic',
                                        cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Judge {self.name} ({self.status})>'

    @property
    def active_categories(self):
        return [a.category for a in self.category_assignments.filter_by(active=True).all()]


class JudgeCategoryAssignment(db.Model):
    """Which genres/categories a judge is assigned to, and for which contest types."""
    __tablename__ = 'judge_category_assignments'

    id           = db.Column(db.Integer, primary_key=True)
    judge_id     = db.Column(db.Integer, db.ForeignKey('judges.id', ondelete='CASCADE'), nullable=False)
    category     = db.Column(db.String(60), nullable=False)   # must match GENRE_IDS
    # contest_type: 'all' | 'weekly' | 'open' | 'poty'
    contest_type = db.Column(db.String(20), default='all', nullable=False)
    assigned_by  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at  = db.Column(db.DateTime, default=datetime.utcnow)
    active       = db.Column(db.Boolean, default=True, nullable=False)

    assigner = db.relationship('User', foreign_keys=[assigned_by], backref='judge_category_assignments_made', lazy=True)


class ContestJudgeConfig(db.Model):
    """
    Per-contest configuration for judge pool threshold, scoring weight,
    and cooling period before leaderboard publication.
    One row per (contest_ref, contest_type) pair.
    """
    __tablename__ = 'contest_judge_configs'

    id                      = db.Column(db.Integer, primary_key=True)
    contest_ref             = db.Column(db.String(40), nullable=False)
    contest_type            = db.Column(db.String(20), nullable=False)
    score_threshold         = db.Column(db.Float,   default=8.0,          nullable=False)
    # weighting_mode: 'tiebreaker' | 'weighted'
    weighting_mode          = db.Column(db.String(20), default='tiebreaker', nullable=False)
    ddi_weight              = db.Column(db.Integer, default=100,           nullable=False)
    judge_weight            = db.Column(db.Integer, default=0,             nullable=False)
    cooling_period_hours    = db.Column(db.Integer, default=48,            nullable=False)
    pool_populated_at       = db.Column(db.DateTime, nullable=True)
    results_emailed_at      = db.Column(db.DateTime, nullable=True)
    leaderboard_published_at= db.Column(db.DateTime, nullable=True)
    created_by              = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at              = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by], backref='judge_configs_created', lazy=True)
    __table_args__ = (db.UniqueConstraint('contest_ref', 'contest_type', name='uq_contest_judge_config'),)


class JudgeAssignment(db.Model):
    """
    One row per judge-image pairing in the judging pipeline.
    status flow: pending → scored | flagged | skipped
    SLA reminders tracked via reminder_48_sent / reminder_24_sent.
    """
    __tablename__ = 'judge_assignments'

    id               = db.Column(db.Integer, primary_key=True)
    judge_id         = db.Column(db.Integer, db.ForeignKey('judges.id', ondelete='CASCADE'),  nullable=False)
    image_id         = db.Column(db.Integer, db.ForeignKey('images.id', ondelete='CASCADE'),  nullable=False)
    contest_ref      = db.Column(db.String(40), nullable=True)
    contest_type     = db.Column(db.String(20), nullable=True)
    assigned_at      = db.Column(db.DateTime, default=datetime.utcnow)
    deadline         = db.Column(db.DateTime, nullable=True)
    status           = db.Column(db.String(20), default='pending', nullable=False)
    reminder_48_sent = db.Column(db.Boolean, default=False, nullable=False)
    reminder_24_sent = db.Column(db.Boolean, default=False, nullable=False)

    image  = db.relationship('Image', foreign_keys=[image_id], backref='judge_assignments', lazy=True)
    score  = db.relationship('JudgeScore', backref='assignment', uselist=False,
                             cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('judge_id', 'image_id', name='uq_judge_assignment'),)

    def __repr__(self):
        return f'<JudgeAssignment judge={self.judge_id} image={self.image_id} status={self.status}>'


class JudgeScore(db.Model):
    """
    Score or flag submitted by a judge for one assignment.
    One row per assignment (UNIQUE on judge_assignment_id).
    flag_type set means the judge flagged instead of scoring — mutually exclusive.
    """
    __tablename__ = 'judge_scores'

    id                  = db.Column(db.Integer, primary_key=True)
    judge_assignment_id = db.Column(db.Integer, db.ForeignKey('judge_assignments.id', ondelete='CASCADE'),
                                    nullable=False, unique=True)
    judge_id            = db.Column(db.Integer, db.ForeignKey('judges.id', ondelete='CASCADE'),  nullable=False)
    image_id            = db.Column(db.Integer, db.ForeignKey('images.id', ondelete='CASCADE'),  nullable=False)

    # Blind DDI scores — same 5 dimensions, no DDI values shown to judge
    dod_score           = db.Column(db.Float, nullable=True)
    disruption_score    = db.Column(db.Float, nullable=True)
    dm_score            = db.Column(db.Float, nullable=True)
    wonder_score        = db.Column(db.Float, nullable=True)
    aq_score            = db.Column(db.Float, nullable=True)
    judge_total         = db.Column(db.Float, nullable=True)   # avg of 5 dimensions

    submitted_at        = db.Column(db.DateTime, default=datetime.utcnow)

    # Flag — set when judge flags instead of scoring
    # flag_type: 'ai_generated' | 'stolen' | 'technically_impossible' | 'other'
    flag_type           = db.Column(db.String(40), nullable=True)
    flag_notes          = db.Column(db.Text,       nullable=True)

    judge = db.relationship('Judge', foreign_keys=[judge_id], backref='scores_given', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='judge_scores',  lazy=True)

    def __repr__(self):
        return f'<JudgeScore assignment={self.judge_assignment_id} total={self.judge_total} flag={self.flag_type}>'


class RawSubmission(db.Model):
    """
    RAW file submission for contest winner verification.
    Triggered for all contest types (Weekly, Open, POTY) when a winner is notified.
    Analysis runs in two phases: metadata (EXIF/crop) then Claude vision.
    admin_decision: null → awaiting | 'approved' | 'rejected' | 'resubmit_requested'
    """
    __tablename__ = 'raw_submissions'

    id                  = db.Column(db.Integer, primary_key=True)
    image_id            = db.Column(db.Integer, db.ForeignKey('images.id', ondelete='CASCADE'), nullable=False)
    user_id             = db.Column(db.Integer, db.ForeignKey('users.id',  ondelete='CASCADE'), nullable=False)
    contest_ref         = db.Column(db.String(40), nullable=True)
    contest_type        = db.Column(db.String(20), nullable=True)

    # Submission
    # submission_method: 'upload' | 'link'
    submission_method   = db.Column(db.String(20), default='upload')
    raw_file_key        = db.Column(db.String(512), nullable=True)   # R2 key if uploaded
    raw_link            = db.Column(db.Text,        nullable=True)   # external link fallback
    submitted_at        = db.Column(db.DateTime,    nullable=True)
    deadline            = db.Column(db.DateTime,    nullable=True)
    reminder_48_sent    = db.Column(db.Boolean, default=False, nullable=False)
    reminder_24_sent    = db.Column(db.Boolean, default=False, nullable=False)

    # Analysis
    # analysis_status: 'awaiting' | 'pending' | 'running' | 'complete' | 'failed'
    analysis_status     = db.Column(db.String(20), default='awaiting', nullable=False)
    analysis_run_at     = db.Column(db.DateTime, nullable=True)

    # Metadata phase results
    exif_match          = db.Column(db.Boolean, nullable=True)
    crop_percentage     = db.Column(db.Float,   nullable=True)   # 0.0–1.0
    crop_flagged        = db.Column(db.Boolean, default=False)
    dimension_match     = db.Column(db.Boolean, nullable=True)
    raw_original_width  = db.Column(db.Integer, nullable=True)
    raw_original_height = db.Column(db.Integer, nullable=True)

    # Vision phase results
    vision_ai_detected     = db.Column(db.Boolean, nullable=True)
    vision_objects_removed = db.Column(db.Boolean, nullable=True)
    vision_objects_added   = db.Column(db.Boolean, nullable=True)
    vision_logo_trademark  = db.Column(db.Boolean, nullable=True)
    vision_meaning_changed = db.Column(db.Boolean, nullable=True)
    vision_painterly       = db.Column(db.Boolean, nullable=True)
    vision_crop_consistent = db.Column(db.Boolean, nullable=True)
    vision_notes           = db.Column(db.Text,    nullable=True)

    # Resolution
    overall_flag        = db.Column(db.Boolean, default=False, nullable=False)
    flag_reasons        = db.Column(db.Text,    nullable=True)
    admin_decision      = db.Column(db.String(20), nullable=True)
    admin_notes         = db.Column(db.Text,       nullable=True)
    admin_decided_by    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    admin_decided_at    = db.Column(db.DateTime, nullable=True)
    disqualified        = db.Column(db.Boolean, default=False, nullable=False)
    notified_at         = db.Column(db.DateTime, nullable=True)

    # Relationships
    image         = db.relationship('Image', foreign_keys=[image_id], backref='raw_submissions', lazy=True)
    photographer  = db.relationship('User',  foreign_keys=[user_id],  backref='raw_submissions', lazy=True)
    admin_decider = db.relationship('User',  foreign_keys=[admin_decided_by],
                                    backref='raw_decisions_made', lazy=True)

    __table_args__ = (db.UniqueConstraint('image_id', 'contest_ref', 'contest_type',
                                          name='uq_raw_submission'),)

    def __repr__(self):
        return f'<RawSubmission image={self.image_id} status={self.analysis_status} decision={self.admin_decision}>'

    @property
    def any_vision_flag(self):
        return any([
            self.vision_ai_detected, self.vision_objects_removed,
            self.vision_objects_added, self.vision_logo_trademark,
            self.vision_meaning_changed, self.vision_painterly,
        ])


# ── v53: Contest Framework ────────────────────────────────────────────────────

class ContestPeriod(db.Model):
    """
    Master record for each annual contest cycle.
    One row per year covers POTY + BOW + Open windows for that year.
    status: upcoming | active | results_pending | closed
    """
    __tablename__ = 'contest_periods'

    id                    = db.Column(db.Integer, primary_key=True)
    platform_year         = db.Column(db.Integer, unique=True, nullable=False)

    # POTY window
    poty_opens_at         = db.Column(db.DateTime, nullable=True)   # 1 Jun 2026 / 1 Jan onwards
    poty_closes_at        = db.Column(db.DateTime, nullable=True)   # 31 Dec
    poty_status           = db.Column(db.String(20), default='upcoming')  # upcoming|active|results_pending|closed

    # BOW window
    bow_entry_opens_at    = db.Column(db.DateTime, nullable=True)   # 1 Dec
    bow_entry_closes_at   = db.Column(db.DateTime, nullable=True)   # 31 Dec
    bow_judging_ends_at   = db.Column(db.DateTime, nullable=True)   # ~3 weeks after close
    bow_status            = db.Column(db.String(20), default='upcoming')

    # Open contest window (runs alongside POTY)
    open_opens_at         = db.Column(db.DateTime, nullable=True)
    open_closes_at        = db.Column(db.DateTime, nullable=True)
    open_cooling_ends_at  = db.Column(db.DateTime, nullable=True)   # 15 Jan following year
    open_status           = db.Column(db.String(20), default='upcoming')

    # Announcement date — all winners announced together
    winners_announced_at  = db.Column(db.DateTime, nullable=True)   # 1 Feb following year

    # Announcement banner text (shown on dashboard)
    announcement_banner   = db.Column(db.Text, nullable=True)
    banner_active         = db.Column(db.Boolean, default=False)

    created_by            = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by], backref='contest_periods_created', lazy=True)

    def __repr__(self):
        return f'<ContestPeriod year={self.platform_year}>'


class BrandContest(db.Model):
    """
    Brand-sponsored contest — subscribers only, free entry.
    Admin creates one row per brand contest. Multiple can run per year.
    status: draft | active | judging | results_published | closed
    """
    __tablename__ = 'brand_contests'

    id              = db.Column(db.Integer, primary_key=True)
    title           = db.Column(db.String(180), nullable=False)
    brand_name      = db.Column(db.String(120), nullable=False)
    brief           = db.Column(db.Text, nullable=False)        # what the brand wants
    prize_desc      = db.Column(db.Text, nullable=False)        # prize description
    prize_value     = db.Column(db.String(80), nullable=True)   # e.g. "Rs. 50,000 + trophy"
    opens_at        = db.Column(db.DateTime, nullable=False)
    closes_at       = db.Column(db.DateTime, nullable=False)
    max_entries_per_user = db.Column(db.Integer, default=3)
    # status: draft | active | judging | results_published | closed
    status          = db.Column(db.String(20), default='draft', nullable=False)
    results_published_at = db.Column(db.DateTime, nullable=True)
    announcement_sent_at = db.Column(db.DateTime, nullable=True)
    created_by      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    entries  = db.relationship('BrandEntry', backref='contest', lazy='dynamic', cascade='all, delete-orphan')
    creator  = db.relationship('User', foreign_keys=[created_by], backref='brand_contests_created', lazy=True)

    @property
    def is_open(self):
        now = datetime.utcnow()
        return self.status == 'active' and self.opens_at <= now <= self.closes_at

    @property
    def entry_count(self):
        return self.entries.count()

    def __repr__(self):
        return f'<BrandContest {self.brand_name}: {self.title} ({self.status})>'


class BrandEntry(db.Model):
    """
    A subscriber's entry into a brand contest.
    One row per user-image-contest combination.
    result_rank: 1 = winner, 2 = runner-up, etc. NULL = not yet ranked.
    """
    __tablename__ = 'brand_entries'

    id              = db.Column(db.Integer, primary_key=True)
    contest_id      = db.Column(db.Integer, db.ForeignKey('brand_contests.id', ondelete='CASCADE'), nullable=False)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('images.id'), nullable=False)
    entered_at      = db.Column(db.DateTime, default=datetime.utcnow)
    result_rank     = db.Column(db.Integer, nullable=True)
    result_note     = db.Column(db.Text, nullable=True)
    result_emailed  = db.Column(db.Boolean, default=False)

    user  = db.relationship('User',  foreign_keys=[user_id],  backref='brand_entries', lazy=True)
    image = db.relationship('Image', foreign_keys=[image_id], backref='brand_entries', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('contest_id', 'user_id', 'image_id', name='uq_brand_entry'),
    )

    def __repr__(self):
        return f'<BrandEntry contest={self.contest_id} user={self.user_id} image={self.image_id}>'


class ContestAnnouncement(db.Model):
    """
    Dashboard announcement banners and emailer triggers for all contest types.
    type: poty | bow | open | brand
    audience: all | subscribers | non_subscribers
    delivery: banner | email | both
    status: draft | scheduled | sent
    """
    __tablename__ = 'contest_announcements'

    id              = db.Column(db.Integer, primary_key=True)
    contest_type    = db.Column(db.String(20), nullable=False)   # poty|bow|open|brand
    contest_ref     = db.Column(db.String(40), nullable=True)    # e.g. '2026' or brand_contest id
    title           = db.Column(db.String(180), nullable=False)
    body            = db.Column(db.Text, nullable=False)
    cta_label       = db.Column(db.String(80), nullable=True)    # button text
    cta_url         = db.Column(db.String(255), nullable=True)   # button link
    audience        = db.Column(db.String(20), default='all')    # all|subscribers|non_subscribers
    delivery        = db.Column(db.String(20), default='both')   # banner|email|both
    # status: draft | scheduled | sent
    status          = db.Column(db.String(20), default='draft')
    send_at         = db.Column(db.DateTime, nullable=True)      # scheduled send time
    sent_at         = db.Column(db.DateTime, nullable=True)
    banner_active   = db.Column(db.Boolean, default=False)       # show on dashboard right now
    banner_expires_at = db.Column(db.DateTime, nullable=True)
    created_by      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by], backref='contest_announcements_created', lazy=True)

    def __repr__(self):
        return f'<ContestAnnouncement {self.contest_type} {self.title[:40]} ({self.status})>'


# ── Migration SQL note ────────────────────────────────────────────────────────
# All new columns and tables for v30 are handled in app.py startup migrations.
# This file defines the ORM layer that maps to those DB structures.
# No migration SQL lives here — app.py is the single source for migration SQL.


# ── Peer rating helpers — unchanged from v27 ──────────────────────────────────

def get_or_assign_next_image(rater_id: int):
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    stale  = RatingAssignment.query.filter(
        RatingAssignment.rater_id   == rater_id,
        RatingAssignment.status     == 'assigned',
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
            Image.status      == 'scored',
            Image.is_public   == True,
            Image.is_flagged  == False,
            Image.needs_review== False,
            Image.score       != None,
            Image.user_id     != rater_id,
            User.is_subscribed== True,
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
    image    = assignment.image
    genre    = normalise_genre(image.genre)
    peer_ll, _, _, _ = calculate_score(genre, dod, disruption, dm, wonder, aq)
    delta    = round(peer_ll - (image.score or 0), 2)

    rating = PeerRating(
        rater_id=assignment.rater_id, image_id=assignment.image_id,
        genre=genre, dod=dod, disruption=disruption, dm=dm, wonder=wonder, aq=aq,
        peer_ll_score=peer_ll, delta_from_ddi=delta, time_spent_seconds=time_spent,
    )
    db.session.add(rating)

    assignment.status             = 'submitted'
    assignment.submitted_at       = datetime.utcnow()
    assignment.time_spent_seconds = time_spent
    assignment.dod        = dod;  assignment.disruption = disruption
    assignment.dm         = dm;   assignment.wonder     = wonder
    assignment.aq         = aq;   assignment.peer_ll_score = peer_ll

    all_ratings = PeerRating.query.filter_by(image_id=image.id).all()
    all_scores  = [r.peer_ll_score for r in all_ratings] + [peer_ll]
    all_dod     = [r.dod        for r in all_ratings] + [dod]
    all_dis     = [r.disruption for r in all_ratings] + [disruption]
    all_dm_v    = [r.dm         for r in all_ratings] + [dm]
    all_won     = [r.wonder     for r in all_ratings] + [wonder]
    all_aq_v    = [r.aq         for r in all_ratings] + [aq]
    n = len(all_scores)

    image.peer_rating_count   = n
    image.peer_avg_score      = round(sum(all_scores) / n, 2)
    image.peer_avg_dod        = round(sum(all_dod)    / n, 2)
    image.peer_avg_disruption = round(sum(all_dis)    / n, 2)
    image.peer_avg_dm         = round(sum(all_dm_v)   / n, 2)
    image.peer_avg_wonder     = round(sum(all_won)    / n, 2)
    image.peer_avg_aq         = round(sum(all_aq_v)   / n, 2)
    image.update_blended_score()

    rater = assignment.rater
    rater.reset_credits_if_needed()
    rater.rating_credits         = (rater.rating_credits         or 0) + 1
    rater.lifetime_ratings_given = (rater.lifetime_ratings_given or 0) + 1

    db.session.commit()

    _check_rater_bias(assignment.rater_id)
    return rating


class FlaggedPhash(db.Model):
    """
    Blocklist of perceptual hashes for confirmed AI-generated images.
    Populated automatically when admin flags an image as AI.
    Checked at upload — matching images are silently rejected.
    """
    __tablename__ = 'flagged_phashes'

    id         = db.Column(db.Integer,  primary_key=True)
    phash      = db.Column(db.String(64), nullable=False, index=True)
    image_id   = db.Column(db.Integer,  nullable=True)   # source image for reference
    flagged_by = db.Column(db.Integer,  nullable=True)   # admin user_id
    flagged_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    note       = db.Column(db.Text,     nullable=True)


def _check_rater_bias(rater_id):
    MIN_RATINGS = 20; THRESHOLD = 2.5; ZONE3_DELTA = 3.0

    ratings = PeerRating.query.filter_by(rater_id=rater_id).all()
    rater   = User.query.get(rater_id)
    if not rater:
        return

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
