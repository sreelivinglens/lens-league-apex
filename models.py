from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id                = db.Column(db.Integer, primary_key=True)
    username          = db.Column(db.String(80),  unique=True, nullable=False)
    email             = db.Column(db.String(120), unique=True, nullable=False)
    password_hash     = db.Column(db.String(256), nullable=False)

    # Security question for password recovery (3-step flow)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer   = db.Column(db.String(255), nullable=True)   # stored lowercase-stripped

    # Member agreement acceptance timestamp
    agreed_at         = db.Column(db.DateTime,    nullable=True)

    is_admin          = db.Column(db.Boolean, default=False, nullable=False)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    images            = db.relationship('Image', backref='author', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'


class Image(db.Model):
    __tablename__ = 'images'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    title           = db.Column(db.String(120), nullable=False)
    category        = db.Column(db.String(60),  nullable=True)
    caption         = db.Column(db.Text,         nullable=True)

    filename        = db.Column(db.String(260), nullable=False)   # stored filename on disk/S3
    original_name   = db.Column(db.String(260), nullable=True)    # original upload filename

    # EXIF authenticity: 'verified' | 'unverified' | 'suspicious'
    exif_status     = db.Column(db.String(20), default='unverified')
    exif_data       = db.Column(db.JSON,        nullable=True)

    # Apex DDI Engine scoring
    score           = db.Column(db.Float,   nullable=True)
    score_breakdown = db.Column(db.JSON,    nullable=True)   # per-dimension scores
    scored_at       = db.Column(db.DateTime, nullable=True)

    # Share page
    share_id        = db.Column(db.String(32), unique=True, nullable=True)

    uploaded_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Image {self.id} – {self.title}>'


class CalibrationLog(db.Model):
    """Stores admin calibration data for score drift monitoring."""
    __tablename__ = 'calibration_logs'

    id          = db.Column(db.Integer, primary_key=True)
    category    = db.Column(db.String(60),  nullable=False)
    note        = db.Column(db.Text,         nullable=True)
    adjustment  = db.Column(db.Float,        nullable=True)   # positive = score increase
    logged_by   = db.Column(db.Integer,  db.ForeignKey('users.id'), nullable=True)
    logged_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CalibrationLog {self.category} {self.adjustment:+.2f}>'


# ---------------------------------------------------------------------------
# Auto-migration helper
# Called from app.py on every startup — safe, uses CREATE TABLE IF NOT EXISTS
# ---------------------------------------------------------------------------

def run_migrations(app):
    """
    Adds new columns to existing tables if they don't already exist.
    Runs on every startup — safe for production (IF NOT EXISTS guard via
    catching duplicate-column errors).
    """
    with app.app_context():
        db.create_all()  # creates any brand-new tables

        # Add new columns to 'users' if they don't exist yet
        _add_column_if_missing(db, 'users', 'security_question', 'VARCHAR(255)')
        _add_column_if_missing(db, 'users', 'security_answer',   'VARCHAR(255)')
        _add_column_if_missing(db, 'users', 'agreed_at',         'TIMESTAMP')


def _add_column_if_missing(db, table, column, col_type):
    """Execute ALTER TABLE … ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+)."""
    sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};"
    try:
        db.session.execute(db.text(sql))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Log but don't crash — column may already exist on older PG versions
        print(f"[migration] {table}.{column}: {e}")
