from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username      = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(255))
    role          = db.Column(db.String(20), default='member')   # member | admin
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)

    images = db.relationship('Image', backref='photographer', lazy='dynamic',
                             cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.username}>'


class Image(db.Model):
    __tablename__ = 'images'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # File info
    original_filename = db.Column(db.String(255))
    stored_filename   = db.Column(db.String(255))        # UUID-based storage name
    thumb_path        = db.Column(db.String(255))        # compressed JPG path
    card_path         = db.Column(db.String(255))        # rating card JPG path
    file_size_kb      = db.Column(db.Integer)

    # Authenticity / EXIF
    legal_declaration = db.Column(db.Boolean, default=False)
    exif_status       = db.Column(db.String(20), default='unknown')  # verified|unverified|suspicious
    exif_camera       = db.Column(db.String(255))
    exif_date_taken   = db.Column(db.String(100))
    exif_settings     = db.Column(db.String(255))  # focal/aperture/iso summary
    exif_warning      = db.Column(db.Text)
    width             = db.Column(db.Integer)
    height            = db.Column(db.Integer)
    format            = db.Column(db.String(20))         # JPEG, RAW, PNG etc.

    # Metadata supplied by photographer
    asset_name        = db.Column(db.String(255))
    genre             = db.Column(db.String(50))         # Wildlife, Landscape, Street etc.
    subject           = db.Column(db.String(255))
    location          = db.Column(db.String(255))
    conditions        = db.Column(db.String(255))
    photographer_name = db.Column(db.String(255))

    # Scoring
    score             = db.Column(db.Float)
    tier              = db.Column(db.String(30))
    dod_score         = db.Column(db.Float)
    disruption_score  = db.Column(db.Float)
    dm_score          = db.Column(db.Float)
    wonder_score      = db.Column(db.Float)
    aq_score          = db.Column(db.Float)
    archetype         = db.Column(db.String(100))
    soul_bonus        = db.Column(db.Boolean, default=False)

    # Full audit data stored as JSON
    audit_data        = db.Column(db.Text)   # JSON blob — all rows, bylines, badges

    # Status
    status            = db.Column(db.String(20), default='pending')  # pending|scored|failed
    scored_at         = db.Column(db.DateTime)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def get_audit(self):
        if self.audit_data:
            return json.loads(self.audit_data)
        return {}

    def set_audit(self, data):
        self.audit_data = json.dumps(data)

    def __repr__(self):
        return f'<Image {self.asset_name} score={self.score}>'


class CalibrationLog(db.Model):
    """Records each recalibration event for the learning layer."""
    __tablename__ = 'calibration_log'

    id              = db.Column(db.Integer, primary_key=True)
    genre           = db.Column(db.String(50))
    image_count     = db.Column(db.Integer)
    avg_score       = db.Column(db.Float)
    avg_dod         = db.Column(db.Float)
    avg_disruption  = db.Column(db.Float)
    avg_dm          = db.Column(db.Float)
    avg_wonder      = db.Column(db.Float)
    avg_aq          = db.Column(db.Float)
    notes           = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
