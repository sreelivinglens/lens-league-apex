import json
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id                = db.Column(db.Integer, primary_key=True)
    username          = db.Column(db.String(80),  unique=True, nullable=False)
    email             = db.Column(db.String(120), unique=True, nullable=False)
    password_hash     = db.Column(db.String(256), nullable=False)
    full_name         = db.Column(db.String(120), nullable=True)

    # Role-based access: 'member' | 'admin'
    role              = db.Column(db.String(20), default='member', nullable=False)

    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    last_login        = db.Column(db.DateTime, nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    # Security question for password recovery (3-step flow)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer   = db.Column(db.String(255), nullable=True)  # stored lowercase

    # Member agreement acceptance timestamp
    agreed_at         = db.Column(db.DateTime, nullable=True)

    # Subscription
    is_subscribed       = db.Column(db.Boolean, default=False)
    subscription_track  = db.Column(db.String(20), nullable=True)   # 'camera' | 'mobile'
    subscription_plan   = db.Column(db.String(20), nullable=True)   # 'monthly' | 'annual' | 'beta'
    subscribed_at       = db.Column(db.DateTime, nullable=True)
    monthly_uploads_used = db.Column(db.Integer, default=0)
    monthly_reset_date  = db.Column(db.Date, nullable=True)

    images            = db.relationship('Image', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Image(db.Model):
    __tablename__ = 'images'

    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # File info
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

    # Metadata entered at upload
    asset_name          = db.Column(db.String(180), nullable=True)
    genre               = db.Column(db.String(60),  nullable=True)
    subject             = db.Column(db.String(180), nullable=True)
    location            = db.Column(db.String(180), nullable=True)
    conditions          = db.Column(db.String(180), nullable=True)
    photographer_name   = db.Column(db.String(120), nullable=True)

    # Competition track: 'camera' | 'mobile' | None (free users)
    camera_track        = db.Column(db.String(20), nullable=True)

    # Legal
    legal_declaration   = db.Column(db.Boolean, default=False)

    # EXIF authenticity: 'verified' | 'unverified' | 'suspicious'
    exif_status         = db.Column(db.String(20),  default='unverified')
    exif_camera         = db.Column(db.String(120), nullable=True)
    exif_date_taken     = db.Column(db.String(60),  nullable=True)
    exif_settings       = db.Column(db.String(180), nullable=True)
    exif_warning        = db.Column(db.Text,         nullable=True)

    # Apex DDI Engine scores
    dod_score           = db.Column(db.Float, nullable=True)
    disruption_score    = db.Column(db.Float, nullable=True)
    dm_score            = db.Column(db.Float, nullable=True)
    wonder_score        = db.Column(db.Float, nullable=True)
    aq_score            = db.Column(db.Float, nullable=True)
    score               = db.Column(db.Float, nullable=True)
    tier                = db.Column(db.String(60),  nullable=True)
    archetype           = db.Column(db.String(120), nullable=True)
    soul_bonus          = db.Column(db.Boolean, default=False)

    # Calibration example flag
    is_calibration_example = db.Column(db.Boolean, default=False, nullable=False)

    # Judge referral flag
    judge_referral         = db.Column(db.Boolean, default=False, nullable=False)

    # Workflow status: 'pending' | 'scored'
    status              = db.Column(db.String(20), default='pending')
    scored_at           = db.Column(db.DateTime,  nullable=True)
    created_at          = db.Column(db.DateTime,  default=datetime.utcnow)

    # Audit JSON blob (scoring breakdown)
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

    def __repr__(self):
        return f'<Image {self.id} – {self.asset_name} ({self.score})>'


class BowSubmission(db.Model):
    """Body of Work annual submission — 6 to 12 curated images as a unified series."""
    __tablename__ = 'bow_submissions'

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    series_title      = db.Column(db.String(180), nullable=False)
    thematic_statement= db.Column(db.Text, nullable=False)
    image_ids_json    = db.Column(db.Text, nullable=False)   # JSON list of image IDs
    image_count       = db.Column(db.Integer, nullable=False)
    status            = db.Column(db.String(20), default='submitted')  # submitted | under_review | awarded
    platform_year     = db.Column(db.Integer, nullable=False)          # e.g. 2026
    submitted_at      = db.Column(db.DateTime, default=datetime.utcnow)
    notes             = db.Column(db.Text, nullable=True)              # admin/jury notes

    user              = db.relationship('User', foreign_keys=[user_id], backref='bow_submissions', lazy=True)

    def get_image_ids(self):
        try:
            return json.loads(self.image_ids_json)
        except Exception:
            return []

    def set_image_ids(self, ids: list):
        self.image_ids_json = json.dumps(ids)

    def __repr__(self):
        return f'<BowSubmission {self.id} user={self.user_id} images={self.image_count} year={self.platform_year}>'


class CalibrationNote(db.Model):
    """Admin feedback on individual scored images — feeds back into engine prompt."""
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

    image           = db.relationship('Image', foreign_keys=[image_id], backref='calibration_notes', lazy=True)
    admin           = db.relationship('User', foreign_keys=[admin_id], backref='admin_calibration_notes', lazy=True)

    def __repr__(self):
        return f'<CalibrationNote image={self.image_id} module={self.module} {self.original_score}→{self.corrected_score}>'


class CalibrationLog(db.Model):
    """Stores admin calibration snapshots for score drift monitoring."""
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

    def __repr__(self):
        return f'<CalibrationLog {self.genre} avg={self.avg_score}>'


# ---------------------------------------------------------------------------
# Auto-migration — runs on every startup, safe for production
# ---------------------------------------------------------------------------

def run_migrations(app):
    with app.app_context():
        db.create_all()

        # users table
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

        # images table
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
        _col('images', 'camera_track',            'VARCHAR(20)')  # 'camera' | 'mobile' | NULL

        # bow_submissions table
        db.session.execute(db.text('''
            CREATE TABLE IF NOT EXISTS bow_submissions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                series_title VARCHAR(180) NOT NULL,
                thematic_statement TEXT NOT NULL,
                image_ids_json TEXT NOT NULL,
                image_count INTEGER NOT NULL,
                status VARCHAR(20) DEFAULT 'submitted',
                platform_year INTEGER NOT NULL,
                submitted_at TIMESTAMP DEFAULT NOW(),
                notes TEXT
            )
        '''))
        db.session.commit()
        db.session.execute(db.text('''
            CREATE TABLE IF NOT EXISTS calibration_notes (
                id SERIAL PRIMARY KEY,
                image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                admin_id INTEGER REFERENCES users(id),
                genre VARCHAR(60) NOT NULL,
                module VARCHAR(20) NOT NULL,
                original_score FLOAT,
                corrected_score FLOAT,
                reason TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        '''))
        db.session.commit()


def _col(table, column, col_type):
    """ALTER TABLE … ADD COLUMN IF NOT EXISTS — PostgreSQL 9.6+."""
    sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};"
    try:
        db.session.execute(db.text(sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[migration] {table}.{column}: {e}")
