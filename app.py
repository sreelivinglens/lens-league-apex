import os
import uuid
import json
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, jsonify, abort, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, desc
from dotenv import load_dotenv

from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from models import (db, User, Image, CalibrationLog, ContestEntry, OpenContestEntry, ImageReport,
                    RatingAssignment, PeerRating, PeerPoolEntry,
                    WeeklyChallenge, WeeklySubmission,
                    get_or_assign_next_image, submit_peer_rating)
from engine.scoring import (calculate_score, get_tier, GENRE_WEIGHTS, GENRE_IDS,
                              normalise_genre, ARCHETYPES, compute_calibration_stats,
                              OPEN_PRIZES, GENRE_LABELS, GENRE_CHOICES)
from engine.processor import ingest_image, allowed_file
import storage as r2
from location_data import (
    get_countries, INDIA_STATES_CITIES, WORLD_LOCATIONS,
    CAMERA_BRANDS, PHONE_BRANDS
)

load_dotenv()

# ---------------------------------------------------------------------------
# Email utility — Gmail SMTP
# Env vars: MAIL_USERNAME, MAIL_PASSWORD
# Falls back silently if not configured — never crashes the app
# ---------------------------------------------------------------------------

def send_email(to_addresses, subject, html_body, text_body=None):
    """
    Send email via Brevo (HTTP API).
    Env var: BREVO_API_KEY
    to_addresses: str (single) or list of str.
    Returns True on success, False on failure.
    """
    import json as _json

    api_key = os.getenv('BREVO_API_KEY', '')
    if not api_key:
        app.logger.warning('[email] BREVO_API_KEY not set — skipping send')
        return False

    if isinstance(to_addresses, str):
        to_addresses = [to_addresses]

    sender_email = os.getenv('MAIL_USERNAME', 'sreeks@gmail.com')

    payload = {
        'sender':     {'name': 'Lens League Apex', 'email': sender_email},
        'to':         [{'email': addr} for addr in to_addresses],
        'subject':    subject,
        'htmlContent': html_body,
    }
    if text_body:
        payload['textContent'] = text_body

    try:
        import requests as _req
        resp = _req.post(
            'https://api.brevo.com/v3/smtp/email',
            json=payload,
            headers={
                'accept':   'application/json',
                'api-key':  api_key,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            app.logger.info(f'[email] Sent "{subject}" to {to_addresses}')
            return True
        else:
            app.logger.error(f'[email] Brevo returned {resp.status_code}: {resp.text}')
            return False
    except ImportError:
        # requests not installed — fall back to urllib
        import urllib.request, urllib.error, ssl
        data = _json.dumps(payload).encode('utf-8')
        req  = urllib.request.Request(
            'https://api.brevo.com/v3/smtp/email',
            data=data,
            headers={
                'accept':        'application/json',
                'content-type':  'application/json',
                'api-key':       api_key,
            },
            method='POST',
        )
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                if r.status in (200, 201):
                    app.logger.info(f'[email] Sent "{subject}" to {to_addresses}')
                    return True
                app.logger.error(f'[email] Brevo returned {r.status}')
                return False
        except Exception as e2:
            app.logger.error(f'[email] Failed (urllib): {type(e2).__name__}: {e2}')
            return False
    except Exception as e:
        app.logger.error(f'[email] Failed to send "{subject}": {type(e).__name__}: {e}')
        return False


def send_challenge_notification(challenge):
    """
    Send weekly challenge notification to all active users.
    Called from admin when a new challenge is created.
    """
    users = User.query.filter_by(is_active=True).filter(
        User.email != None, User.email != ''
    ).all()

    if not users:
        return 0

    site_url = os.getenv('SITE_URL', 'https://lensleagueapex.com')
    challenge_url = f"{site_url}/challenge"

    sponsor_line = ''
    if challenge.sponsor_name:
        prize_text = f' — Prize: {challenge.sponsor_prize}' if challenge.sponsor_prize else ''
        sponsor_line = f'<p style="margin:0 0 16px; color:#8a8070; font-size:15px;">Sponsored by <strong style="color:#C8A84B;">{challenge.sponsor_name}</strong>{prize_text}</p>'

    sent = 0
    for user in users:
        is_sub = getattr(user, 'is_subscribed', False)
        slot_text = '3 images this week' if is_sub else '1 image this week (subscribe for 3)'
        cta_text  = 'Submit your image →' if is_sub else 'Enter the challenge →'

        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F0E8;padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;overflow:hidden;max-width:560px;width:100%;">

      <!-- Header -->
      <tr><td style="background:#1a1a18;padding:24px 32px;">
        <p style="margin:0;font-family:'Courier New',monospace;font-size:13px;font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">LENS LEAGUE APEX</p>
      </td></tr>

      <!-- Challenge banner -->
      <tr><td style="background:#1a1a18;padding:0 32px 28px;">
        <p style="margin:0 0 6px;font-family:'Courier New',monospace;font-size:11px;letter-spacing:2px;color:#6a6458;text-transform:uppercase;">Weekly Challenge · {challenge.week_ref}</p>
        <h1 style="margin:0;font-size:36px;font-style:italic;color:#C8A84B;line-height:1.1;">{challenge.prompt_title}</h1>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:28px 32px;">
        <p style="margin:0 0 14px;font-size:16px;color:#4A4840;line-height:1.6;">Get your photo rated for it to be in the reckoning to qualify for <strong style="color:#1a1a18;">Photographer of the Year</strong></p>
        {'<p style="margin:0 0 20px;font-size:16px;color:#6a6458;line-height:1.7;">' + challenge.prompt_body + '</p>' if challenge.prompt_body else ''}
        {sponsor_line}
        <p style="margin:0 0 8px;font-size:15px;color:#8a8070;">
          <strong style="color:#1a1a18;">You have:</strong> {slot_text}
        </p>
        <p style="margin:0 0 24px;font-size:14px;color:#8a8070;">
          Closes {challenge.closes_at.strftime('%A %d %B, %H:%M UTC')}
        </p>
        <a href="{challenge_url}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:'Courier New',monospace;font-size:14px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;">{cta_text}</a>
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding:20px 32px;border-top:1px solid #E0D8C8;">
        <p style="margin:0;font-size:13px;color:#8a8070;line-height:1.6;">
          You're receiving this because you have an account on Lens League Apex.<br>
          <a href="{site_url}" style="color:#C8A84B;">lensleagueapex.com</a>
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

        text_body = f"""LENS LEAGUE APEX — Weekly Challenge

This week: {challenge.prompt_title}
{challenge.week_ref}

{'Brief: ' + challenge.prompt_body if challenge.prompt_body else ''}

You have: {slot_text}
Closes: {challenge.closes_at.strftime('%A %d %B, %H:%M UTC')}

Enter here: {challenge_url}

— Lens League Apex"""

        if send_email(user.email, f"This week's challenge: {challenge.prompt_title}", html_body, text_body):
            sent += 1

    return sent


FREE_IMAGE_LIMIT_MONTH1 = 6  # Free images in first calendar month after registration
FREE_IMAGE_LIMIT_DEFAULT = 3  # Free images per month from month 2 onwards

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config['SECRET_KEY']          = os.getenv('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///lensleague.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']       = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH']  = int(os.getenv('MAX_CONTENT_LENGTH', 20971520))

# Session cookie settings — required for mobile Safari (iOS ITP)
# SameSite=Lax allows cookies to be sent with same-site XHR requests
# Secure=True ensures cookie is sent over HTTPS (Railway is always HTTPS)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE']   = True

uri = app.config['SQLALCHEMY_DATABASE_URI']
if uri and uri.startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = uri.replace('postgres://', 'postgresql://', 1)

db.init_app(app)

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.unauthorized_handler
def unauthorized():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': True, 'message': 'Session expired. Please log in again.', 'redirect': url_for('login')}), 401
    return redirect(url_for('login', next=request.url))

os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'thumbs'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'cards'),  exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'raw'),    exist_ok=True)

with app.app_context():
    try:
        db.create_all()
        with db.engine.connect() as conn:
            _migrations = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'member'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS security_question VARCHAR(255)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS security_answer VARCHAR(255)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS agreed_at TIMESTAMP",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS card_path VARCHAR(512)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS card_url VARCHAR(512)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS thumb_url VARCHAR(512)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS legal_declaration BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_camera VARCHAR(120)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_lens VARCHAR(180)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_date_taken VARCHAR(60)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_settings VARCHAR(180)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_warning TEXT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS soul_bonus BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS audit_json TEXT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS conditions VARCHAR(180)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS photographer_name VARCHAR(120)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS phash VARCHAR(64)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS is_calibration_example BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS judge_referral BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS camera_track VARCHAR(20) DEFAULT 'camera'",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT TRUE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_subscribed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_track VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscribed_at TIMESTAMP",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_uploads_used INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_reset_date DATE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_suspicion FLOAT DEFAULT 0.0",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS ai_suspicion_reason TEXT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS flagged_reason TEXT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS flagged_at TIMESTAMP",
                "CREATE TABLE IF NOT EXISTS image_reports (id SERIAL PRIMARY KEY, image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE, reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, reason VARCHAR(40) NOT NULL, detail TEXT, reported_at TIMESTAMP DEFAULT NOW(), status VARCHAR(20) DEFAULT 'open', UNIQUE(image_id, reporter_id))",
                # v27 peer rating columns — updated
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_credits INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_reset_date DATE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS lifetime_ratings_given INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_bias_flag BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_bias_note TEXT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_score FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_rating_count INTEGER DEFAULT 0",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS blended_score FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_dod FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_disruption FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_dm FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_wonder FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_aq FLOAT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS peer_pool_unlocks INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS razorpay_sub_id VARCHAR(64)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS is_in_peer_pool BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS pool_entry_chosen_at TIMESTAMP",
                # v28 — location + league integrity
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(80)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(80)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(80)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS declared_camera VARCHAR(120)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS camera_mismatch_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_at TIMESTAMP",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS league_suspended_reason TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(128)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_complete BOOLEAN DEFAULT TRUE",
                # v29 — weekly challenge
                "CREATE TABLE IF NOT EXISTS weekly_challenges (id SERIAL PRIMARY KEY, week_ref VARCHAR(10) UNIQUE NOT NULL, prompt_title VARCHAR(120) NOT NULL, prompt_body TEXT, opens_at TIMESTAMP NOT NULL, closes_at TIMESTAMP NOT NULL, results_at TIMESTAMP, sponsor_name VARCHAR(120), sponsor_prize TEXT, is_active BOOLEAN DEFAULT TRUE, created_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT NOW())",
                "CREATE TABLE IF NOT EXISTS weekly_submissions (id SERIAL PRIMARY KEY, challenge_id INTEGER NOT NULL REFERENCES weekly_challenges(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE, is_subscriber BOOLEAN DEFAULT FALSE, submitted_at TIMESTAMP DEFAULT NOW(), result_rank INTEGER, result_note TEXT, CONSTRAINT uq_weekly_sub_image UNIQUE(challenge_id, image_id))",
                "CREATE INDEX IF NOT EXISTS ix_weekly_challenges_week_ref ON weekly_challenges(week_ref)",
            ]
            for sql in _migrations:
                try:
                    conn.execute(db.text(sql))
                except Exception as _e:
                    print(f'[migration] {_e}')
            conn.commit()

        # Fix calibration_logs — force correct schema on every startup
        try:
            with db.engine.connect() as conn2:
                conn2.execute(db.text("""
                    DO $$
                    BEGIN
                      IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='calibration_logs' AND column_name='category'
                      ) THEN
                        DROP TABLE IF EXISTS calibration_logs CASCADE;
                      END IF;
                    END $$;
                """))
                conn2.execute(db.text("""
                    CREATE TABLE IF NOT EXISTS calibration_logs (
                        id SERIAL PRIMARY KEY,
                        genre VARCHAR(60) NOT NULL,
                        image_count INTEGER,
                        avg_score FLOAT,
                        avg_dod FLOAT,
                        avg_dis FLOAT,
                        avg_dm FLOAT,
                        avg_wonder FLOAT,
                        avg_aq FLOAT,
                        note TEXT,
                        logged_by INTEGER,
                        logged_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn2.commit()
            print('calibration_logs schema OK.')
        except Exception as ce:
            print(f'calibration_logs migration warning: {ce}')

        # contest_entries table
        try:
            with db.engine.connect() as conn3:
                conn3.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS contest_entries (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                        genre VARCHAR(60) NOT NULL,
                        track VARCHAR(20) NOT NULL,
                        contest_month VARCHAR(7) NOT NULL,
                        contest_type VARCHAR(20) DEFAULT \'monthly\',
                        entered_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(user_id, genre, track, contest_month, contest_type)
                    )
                '''))
                conn3.commit()
            print('contest_entries schema OK.')
        except Exception as ce:
            print(f'contest_entries migration warning: {ce}')

        # open_contest_entries table
        try:
            with db.engine.connect() as conn4:
                conn4.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS open_contest_entries (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                        genre VARCHAR(60) NOT NULL,
                        platform_year INTEGER NOT NULL,
                        amount_paise INTEGER DEFAULT 5000,
                        payment_ref VARCHAR(120),
                        status VARCHAR(20) DEFAULT 'confirmed',
                        entered_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(user_id, genre, platform_year)
                    )
                '''))
                conn4.commit()
            print('open_contest_entries schema OK.')
        except Exception as ce:
            print(f'open_contest_entries migration warning: {ce}')

        # v27 — peer rating tables
        try:
            with db.engine.connect() as conn5:
                conn5.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS rating_assignments (
                        id SERIAL PRIMARY KEY,
                        rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                        assigned_at TIMESTAMP DEFAULT NOW(),
                        started_at TIMESTAMP,
                        submitted_at TIMESTAMP,
                        time_spent_seconds INTEGER,
                        dod FLOAT, disruption FLOAT, dm FLOAT, wonder FLOAT, aq FLOAT,
                        peer_ll_score FLOAT,
                        status VARCHAR(20) DEFAULT \'assigned\',
                        UNIQUE(rater_id, image_id)
                    )
                '''))
                conn5.commit()
            print('rating_assignments schema OK.')
        except Exception as ce:
            print(f'rating_assignments migration warning: {ce}')

        try:
            with db.engine.connect() as conn6:
                conn6.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS peer_ratings (
                        id SERIAL PRIMARY KEY,
                        rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                        genre VARCHAR(60) NOT NULL,
                        dod FLOAT NOT NULL, disruption FLOAT NOT NULL,
                        dm FLOAT NOT NULL, wonder FLOAT NOT NULL, aq FLOAT NOT NULL,
                        peer_ll_score FLOAT NOT NULL,
                        delta_from_ddi FLOAT,
                        time_spent_seconds INTEGER,
                        rated_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(rater_id, image_id)
                    )
                '''))
                conn6.commit()
            print('peer_ratings schema OK.')
        except Exception as ce:
            print(f'peer_ratings migration warning: {ce}')

        print('Columns migrated OK.')
    except Exception as e:
        print(f'Migration warning: {e}')

    try:
        with db.engine.connect() as conn:
            exists = conn.execute(db.text("SELECT id FROM users WHERE email='admin@lenslague.com'")).fetchone()
            if not exists:
                new_hash = generate_password_hash('LensAdmin2026!')
                conn.execute(db.text(
                    "INSERT INTO users (email, username, password_hash, full_name, role, is_active, created_at) "
                    "VALUES ('admin@lenslague.com','admin',:h,'Admin','admin',true,NOW())"
                ), {'h': new_hash})
                conn.commit()
                print('Admin account created.')
        print('Database ready.')
    except Exception as e:
        print(f'Admin init warning: {e}')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helper — open contest active flag
# ---------------------------------------------------------------------------

def is_open_contest_active() -> bool:
    return os.getenv('OPEN_CONTEST_ACTIVE', '0') == '1'


def is_bow_active() -> bool:
    return os.getenv('BOW_ACTIVE', '0') == '1'


# ---------------------------------------------------------------------------
# Helper — upload both thumb and card to R2, return public URLs
# ---------------------------------------------------------------------------

def _r2_upload_thumb(local_path: str, uid: str) -> str | None:
    ext = os.path.splitext(local_path)[1].lower() or '.jpg'
    key = f'thumbs/{uid}{ext}'
    return r2.upload_file(local_path, key, content_type='image/jpeg')

def _r2_upload_card(local_path: str, uid: str) -> str | None:
    key = f'cards/{uid}.jpg'
    return r2.upload_file(local_path, key, content_type='image/jpeg')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def auto_title(filename, genre=None, archetype=None, location=None, subject=None):
    """Generate a meaningful title for bulk-uploaded images."""
    import re
    if subject and subject.strip():
        return subject.strip()[:60]
    if genre and location:
        city = location.split(',')[0].strip()
        if city:
            return f"{city} {genre}"[:60]
    if genre and archetype:
        word = archetype.split()[0] if archetype.split() else ''
        if word:
            return f"{word} {genre}"[:60]
    if genre:
        return f"{genre} Photography"
    name = os.path.splitext(filename)[0]
    name = re.sub(r'(?i)screenshot[\s_]*[\d._atATPM-]+', '', name)
    name = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(?i)IMG_\d+', 'Image', name)
    name = re.sub(r'(?i)DSC_?\d+', 'Shot', name)
    name = re.sub(r'[_\-]+', ' ', name).strip()
    name = re.sub(r'\s+', ' ', name).strip()
    if name and len(name) > 2:
        return name.title()[:60]
    return 'Untitled'


@app.route('/')
def index():
    try:
        # Recent 4 public scored images for proof-of-activity strip
        recent_images = (Image.query
                         .filter(Image.status=='scored', Image.score!=None,
                                 Image.is_public==True, Image.is_flagged==False)
                         .order_by(Image.scored_at.desc())
                         .limit(4).all())
        # Current contest month label e.g. "April 2026 Monthly Contest"
        contest_month_label = datetime.utcnow().strftime('%B %Y') + ' Monthly Contest'
    except Exception:
        recent_images = []
        contest_month_label = 'Monthly Contest'
    return render_template('index.html',
                           recent_images=recent_images,
                           contest_month_label=contest_month_label,
                           now=datetime.utcnow())


@app.route('/register')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/auth/google')
def auth_google():
    redirect_uri = url_for('auth_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri, prompt='select_account')


@app.route('/auth/google/callback')
def auth_google_callback():
    token = google.authorize_access_token()
    userinfo = token.get('userinfo') or google.userinfo()
    google_id = userinfo.get('sub')
    email     = userinfo.get('email', '').lower().strip()
    name      = userinfo.get('name', '')

    if not google_id or not email:
        flash('Google sign-in failed — no email returned. Please try again.', 'error')
        return redirect(url_for('login'))

    # Find existing user by google_id or email
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    if user:
        # Existing user — update google_id if not set
        if not user.google_id:
            user.google_id = google_id
        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user)
        if not getattr(user, 'onboarding_complete', True):
            return redirect(url_for('onboarding'))
        return redirect(url_for('dashboard'))
    else:
        # New user — create account, send to onboarding
        import re
        base_username = re.sub(r'[^a-zA-Z0-9_]', '', name.replace(' ', '_').lower()) or 'photographer'
        username = base_username
        suffix = 1
        while User.query.filter_by(username=username).first():
            username = f'{base_username}{suffix}'
            suffix += 1

        user = User(
            email=email,
            username=username,
            full_name=name,
            google_id=google_id,
            onboarding_complete=False,
            agreed_at=datetime.utcnow(),
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('onboarding'))


@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if getattr(current_user, 'onboarding_complete', True):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        country = request.form.get('country', '').strip()
        state   = request.form.get('state', '').strip()
        city    = request.form.get('city', '').strip()
        agreed  = request.form.get('agreed')

        if not country or not state or not city:
            flash('Please select your country, state/province, and city.', 'error')
            return redirect(url_for('onboarding'))
        if not agreed:
            flash('Please accept the Member Agreement to continue.', 'error')
            return redirect(url_for('onboarding'))

        current_user.country             = country
        current_user.state               = state
        current_user.city                = city
        current_user.agreed_at           = datetime.utcnow()
        current_user.onboarding_complete = True
        db.session.commit()
        flash('Welcome to Lens League! Your account is ready.', 'success')
        return redirect(url_for('dashboard'))

    _loc = {}
    for _s, _c in INDIA_STATES_CITIES.items():
        _loc.setdefault('India', {})[_s] = _c
    for _country, _states in WORLD_LOCATIONS.items():
        _loc[_country] = _states

    return render_template('onboarding.html',
        countries          = get_countries(),
        location_data_json = json.dumps(_loc),
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter your email and password.', 'error')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()

        if not user or not user.password_hash:
            flash('Invalid email or password.', 'error')
            return render_template('login.html')

        if not check_password_hash(user.password_hash, password):
            flash('Invalid email or password.', 'error')
            return render_template('login.html')

        if not user.is_active:
            flash('This account has been deactivated.', 'error')
            return render_template('login.html')

        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user)

        next_url = request.args.get('next')
        if next_url:
            return redirect(next_url)
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        step  = int(request.form.get('step', 1))
        email = request.form.get('email', '').strip().lower()
        if step == 1:
            user = User.query.filter_by(email=email).first()
            if not user:
                flash('No account found with that email address.', 'error')
                return render_template('forgot_password.html', step=1)
            if not user.security_question:
                flash('This account has no security question set. Please contact support.', 'error')
                return render_template('forgot_password.html', step=1)
            return render_template('forgot_password.html', step=2, email=email,
                                   security_question=user.security_question)
        elif step == 2:
            user   = User.query.filter_by(email=email).first()
            answer = request.form.get('security_answer', '').strip().lower()
            if not user or user.security_answer != answer:
                flash('Incorrect answer. Please try again.', 'error')
                return render_template('forgot_password.html', step=2, email=email,
                                       security_question=user.security_question if user else '')
            return render_template('forgot_password.html', step=3, email=email)
        elif step == 3:
            new_pw  = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')
            user    = User.query.filter_by(email=email).first()
            if not user:
                flash('Session expired. Please start again.', 'error')
                return redirect(url_for('forgot_password'))
            if len(new_pw) < 8:
                flash('Password must be at least 8 characters.', 'error')
                return render_template('forgot_password.html', step=3, email=email)
            if new_pw != confirm:
                flash('Passwords do not match.', 'error')
                return render_template('forgot_password.html', step=3, email=email)
            user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password reset successfully. Please log in with your new password.', 'success')
            return redirect(url_for('login'))
    return render_template('forgot_password.html', step=1)


@app.route('/dashboard')
@login_required
def dashboard():
    page  = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    if current_user.role == 'admin':
        images_q = Image.query
    else:
        images_q = Image.query.filter_by(user_id=current_user.id)
    total_images = images_q.count()
    if query and total_images >= 20:
        images_q = images_q.filter(
            db.or_(
                Image.asset_name.ilike(f'%{query}%'),
                Image.genre.ilike(f'%{query}%'),
                Image.subject.ilike(f'%{query}%'),
                Image.location.ilike(f'%{query}%'),
                Image.photographer_name.ilike(f'%{query}%'),
            )
        )
    images = (images_q.order_by(Image.created_at.desc())
              .paginate(page=page, per_page=12, error_out=False))
    user_filter = {} if current_user.role == 'admin' else {'user_id': current_user.id}
    stats = {
        'total': total_images,
        'scored': Image.query.filter_by(status='scored', **user_filter).count(),
        'avg_score': db.session.query(db.func.avg(Image.score))
                       .filter(Image.user_id==current_user.id, Image.score!=None).scalar() or 0,
        'best_score': db.session.query(db.func.max(Image.score))
                        .filter(Image.user_id==current_user.id).scalar() or 0,
    }
    # Peer rating widget data
    rating_widget = None
    if current_user.role != 'admin' and getattr(current_user, 'is_subscribed', False):
        credits          = current_user.rating_credits or 0
        lifetime_given   = current_user.lifetime_ratings_given or 0
        unlocks_earned   = lifetime_given // 5
        unlocks_used     = PeerPoolEntry.query.filter_by(user_id=current_user.id).count()
        unlocks_pending  = unlocks_earned - unlocks_used  # earned but not yet assigned to an image
        credits_to_next  = 5 - (lifetime_given % 5) if lifetime_given % 5 != 0 else (0 if lifetime_given > 0 else 5)
        images_in_pool   = Image.query.filter_by(user_id=current_user.id, is_in_peer_pool=True).count()
        images_with_peer = Image.query.filter(
            Image.user_id == current_user.id,
            Image.peer_rating_count > 0
        ).count()
        # Best candidate for pool entry (highest DDI, not already in pool, scored)
        pool_candidate = None
        if unlocks_pending > 0:
            pool_candidate = (Image.query
                .filter_by(user_id=current_user.id, status='scored', is_in_peer_pool=False)
                .filter(Image.score != None, Image.is_flagged == False, Image.needs_review == False)
                .order_by(Image.score.desc())
                .first())
        rating_widget = {
            'credits':          credits,
            'lifetime_given':   lifetime_given,
            'unlocks_earned':   unlocks_earned,
            'unlocks_pending':  unlocks_pending,
            'credits_to_next':  credits_to_next,
            'images_in_pool':   images_in_pool,
            'images_with_peer': images_with_peer,
            'pool_candidate':   pool_candidate,
        }

    # Free tier context for upgrade nudge
    free_tier = None
    if current_user.role != 'admin' and not getattr(current_user, 'is_subscribed', False):
        from datetime import date as _date
        today      = _date.today()
        reg_date   = current_user.created_at.date() if current_user.created_at else today
        in_month1  = (today.year == reg_date.year and today.month == reg_date.month)
        free_limit = FREE_IMAGE_LIMIT_MONTH1 if in_month1 else FREE_IMAGE_LIMIT_DEFAULT
        month_start = datetime(today.year, today.month, 1)
        month_count = Image.query.filter(
            Image.user_id == current_user.id,
            Image.created_at >= month_start,
        ).count()
        free_tier = {
            'used':      month_count,
            'limit':     free_limit,
            'remaining': max(0, free_limit - month_count),
            'in_month1': in_month1,
        }

    # ── POTY top-6 tracker ──────────────────────────────────────────────────
    # Live top-6 average per genre for the current user.
    # Deleted images intentionally not excluded — per contest rules, deletions
    # do not improve POTY standing. Calculated from all scored images.
    poty_tracker = None
    if current_user.role != 'admin' and getattr(current_user, 'is_subscribed', False):
        scored_images = (Image.query
            .filter_by(user_id=current_user.id, status='scored')
            .filter(Image.score != None)
            .order_by(Image.genre, Image.score.desc())
            .all())

        # Group by normalised genre
        from engine.scoring import normalise_genre
        genre_data = {}
        for img in scored_images:
            g = normalise_genre(img.genre) if img.genre else 'Other'
            if g not in genre_data:
                genre_data[g] = []
            genre_data[g].append(img)

        # Build per-genre summary: top-6 avg, count, top-6 images
        # Rules:
        # - Legacy beta scores <= 10.0 are multiplied x10 to convert to 0-100 scale
        # - Minimum 6 scored images in a genre before avg is displayed
        # - Minimum 24 images to qualify for POTY prizes
        POTY_MIN_IMAGES  = 24
        POTY_MIN_FOR_AVG = 6
        from decimal import Decimal, ROUND_HALF_UP

        def _norm(s):
            if s is None: return None
            return round(s * 10, 2) if s <= 10.0 else s

        genre_rows = []
        for genre, imgs in sorted(genre_data.items()):
            for img in imgs:
                img._ns = _norm(img.score)
            imgs_desc     = sorted(imgs, key=lambda x: x._ns or 0, reverse=True)
            top6          = imgs_desc[:6]
            has_enough    = len(imgs) >= POTY_MIN_FOR_AVG
            if has_enough and top6:
                _raw      = sum(i._ns for i in top6) / len(top6)
                top6_avg  = float(Decimal(str(_raw)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
            else:
                top6_avg  = None
            genre_rows.append({
                'genre':         genre,
                'count':         len(imgs),
                'top6_avg':      top6_avg,
                'top6_images':   top6,
                'has_enough':    has_enough,
                'qualifies':     len(imgs) >= POTY_MIN_IMAGES,
                'bar_pct':       min(100, int((top6_avg / 100) * 100)) if top6_avg else 0,
                'images_needed': max(0, POTY_MIN_FOR_AVG - len(imgs)),
            })

        # Genres with avg first (desc), then by count
        genre_rows.sort(key=lambda x: (x['top6_avg'] is not None, x['top6_avg'] or 0, x['count']), reverse=True)

        best_avg      = next((r['top6_avg'] for r in genre_rows if r['top6_avg'] is not None), None)
        active_genres = len([r for r in genre_rows if r['count'] > 0])
        total_scored  = sum(r['count'] for r in genre_rows)

        poty_tracker = {
            'genre_rows':     genre_rows,
            'best_avg':       best_avg,
            'active_genres':  active_genres,
            'total_scored':   total_scored,
            'min_images':     POTY_MIN_IMAGES,
        }

    # Weekly challenge banner
    active_challenge = _get_active_challenge()

    return render_template('dashboard.html', images=images, stats=stats,
                           query=query, search_enabled=(total_images >= 20),
                           rating_widget=rating_widget, free_tier=free_tier,
                           poty_tracker=poty_tracker,
                           active_challenge=active_challenge)


# ---------------------------------------------------------------------------
# Profile — edit name/username + change password (combined page)
# ---------------------------------------------------------------------------

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    images_used = Image.query.filter_by(user_id=current_user.id).count()

    if request.method == 'POST':
        action = request.form.get('action')

        # ── Update profile details ────────────────────────────────────────
        if action == 'update_profile':
            new_username  = request.form.get('username', '').strip()
            new_full_name = request.form.get('full_name', '').strip()

            if not new_username:
                flash('Username cannot be empty.', 'error')
                return redirect(url_for('profile'))

            existing = User.query.filter_by(username=new_username).first()
            if existing and existing.id != current_user.id:
                flash('That username is already taken.', 'error')
                return redirect(url_for('profile'))

            current_user.username  = new_username
            current_user.full_name = new_full_name
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('profile'))

        # ── Change password ───────────────────────────────────────────────
        elif action == 'change_password':
            current_pw = request.form.get('current_password', '')
            new_pw     = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')

            if not check_password_hash(current_user.password_hash, current_pw):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('profile'))
            if len(new_pw) < 8:
                flash('New password must be at least 8 characters.', 'error')
                return redirect(url_for('profile'))
            if new_pw != confirm_pw:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('profile'))

            current_user.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password updated. Please log in again with your new password.', 'success')
            logout_user()
            return redirect(url_for('login'))

    return render_template('profile.html', images_used=images_used)


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('image')
        if not file or file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('File type not supported.', 'error')
            return redirect(request.url)

        # ── Free quota check (6 in month 1, 3/month thereafter) ──────────
        if current_user.role != 'admin' and not getattr(current_user, 'is_subscribed', False):
            from datetime import date as _date
            today      = _date.today()
            reg_date   = current_user.created_at.date() if current_user.created_at else today
            in_month1  = (today.year == reg_date.year and today.month == reg_date.month)
            free_limit = FREE_IMAGE_LIMIT_MONTH1 if in_month1 else FREE_IMAGE_LIMIT_DEFAULT
            month_start = datetime(today.year, today.month, 1)
            month_count = Image.query.filter(
                Image.user_id == current_user.id,
                Image.created_at >= month_start,
            ).count()
            if month_count >= free_limit:
                msg = (
                    f'You have used all {free_limit} free scored images for this month. '
                    'Upgrade to Camera or Mobile track for unlimited uploads and contest entry.'
                )
                flash(msg, 'error')
                return redirect(url_for('pricing'))

        uid       = str(uuid.uuid4())
        filename  = secure_filename(file.filename)
        raw_path  = os.path.join(app.config['UPLOAD_FOLDER'], 'raw', f"{uid}_{filename}")
        file.save(raw_path)

        try:
            thumb_path, w, h, fmt, phash = ingest_image(raw_path, app.config['UPLOAD_FOLDER'])
        except Exception as e:
            flash(f'Image processing failed: {e}', 'error')
            if os.path.exists(raw_path): os.remove(raw_path)
            return redirect(request.url)
        # Extract EXIF from original file BEFORE deletion — raw_path still has full metadata
        from engine.exif_check import extract_exif
        exif_status, exif_data, exif_warning = extract_exif(raw_path)
        exif_settings = '  ·  '.join(filter(None, [
            exif_data.get('focal_length',''), exif_data.get('aperture',''),
            exif_data.get('iso',''), exif_data.get('shutter',''),
        ]))

        if os.path.exists(raw_path): os.remove(raw_path)

        from engine.processor import hash_similarity_pct
        existing = Image.query.filter(Image.phash.isnot(None)).all()
        for ex in existing:
            sim = hash_similarity_pct(phash, ex.phash)
            if sim >= 90.0:
                if os.path.exists(thumb_path): os.remove(thumb_path)
                if ex.user_id == current_user.id:
                    return jsonify({'error': True, 'message':
                        f'⚠️ This image appears identical to one you already uploaded (\"{ ex.asset_name or ex.original_filename }\"). Please upload a different photograph.'
                    }), 409
                else:
                    return jsonify({'error': True, 'message':
                        '🚫 This image has already been submitted to Lens League by another member. ' +
                        'Submitting images that belong to another photographer violates our Member Agreement ' +
                        'and may have legal implications. Only submit your own original photographs.'
                    }), 409

        thumb_url = _r2_upload_thumb(thumb_path, uid)
        if not thumb_url:
            flash('Storage upload failed. Please try again.', 'error')
            return redirect(request.url)

        raw_genre = request.form.get('genre', 'Wildlife')
        genre     = normalise_genre(raw_genre)

        img = Image(
            user_id           = current_user.id,
            original_filename = filename,
            stored_filename   = os.path.basename(thumb_path),
            thumb_path        = thumb_path,
            thumb_url         = thumb_url,
            file_size_kb      = int(os.path.getsize(thumb_path) / 1024),
            width=w, height=h, format=fmt,
            asset_name        = (request.form.get('asset_name') or '').strip() or
                                  os.path.splitext(filename)[0].replace('_',' ').replace('-',' ').title(),
            genre             = genre,
            subject           = request.form.get('subject', ''),
            location          = request.form.get('location', ''),
            conditions        = request.form.get('conditions', ''),
            photographer_name = request.form.get('photographer_name',
                                                  current_user.full_name or current_user.username),
            camera_track      = request.form.get('camera_track') or getattr(current_user, 'subscription_track', None),
            phash             = phash,
            status            = 'pending',
            legal_declaration = bool(request.form.get('legal_declaration')),
            is_public         = (request.form.get('is_public', '1') == '1'),
            exif_status=exif_status, exif_camera=exif_data.get('camera', ''),
            exif_lens=exif_data.get('lens', ''),
            exif_date_taken=exif_data.get('date_taken', ''),
            exif_settings=exif_settings, exif_warning=exif_warning,
        )
        db.session.add(img)
        db.session.commit()

        # ── League integrity check (three-strike system) ──────────────────
        # Mobile League users uploading camera EXIF images get graduated penalties.
        # Only flags images uploaded AFTER subscription date (protects legacy images).
        _CAMERA_BRANDS_EXIF = ('canon', 'nikon', 'sony', 'fuji', 'fujifilm', 'olympus',
                               'panasonic', 'leica', 'hasselblad', 'pentax', 'sigma',
                               'ricoh', 'om system', 'om-system')
        _user_league    = getattr(current_user, 'subscription_track', None) or ''
        _exif_cam_lower = (exif_data.get('camera', '') or '').lower()
        _subscribed_at  = getattr(current_user, 'subscribed_at', None)
        _after_sub      = (_subscribed_at is None or datetime.utcnow() >= _subscribed_at)

        if (_user_league == 'mobile'
                and any(b in _exif_cam_lower for b in _CAMERA_BRANDS_EXIF)
                and _after_sub):

            strike = current_user.record_mismatch(img.id, exif_data.get('camera', ''), db.session)

            img.needs_review = True
            img.exif_warning = (img.exif_warning or '') + (
                f' [LEAGUE MISMATCH: Camera EXIF "{exif_data.get("camera","")}" '
                f'detected on Mobile League subscription — strike {strike}/3]'
            )
            db.session.commit()
            app.logger.warning(
                f'[league_mismatch] user={current_user.id} image={img.id} '
                f'exif={_exif_cam_lower} strike={strike}'
            )

            if strike == 1:
                flash(
                    '⚠️ League check: this image appears to have been taken on a dedicated camera, '
                    'but you are in the Mobile League. The image has been held for review. '
                    'If you shoot on a camera, please switch to the Camera League. '
                    'Contact sreeks@gmail.com with questions.',
                    'warning'
                )
            elif strike == 2:
                flash(
                    '⚠️ Second league mismatch. This image has been held for review and '
                    'your contest entries for this month have been removed pending admin review. '
                    'One more mismatch will suspend your contest access.',
                    'warning'
                )
                _month = datetime.utcnow().strftime('%Y-%m')
                ContestEntry.query.filter_by(user_id=current_user.id, contest_month=_month).delete()
                db.session.commit()
            elif strike >= 3:
                flash(
                    '🚫 Three league mismatches detected. Your contest access has been suspended '
                    'and this month\'s contest entries have been removed. '
                    'Contact sreeks@gmail.com to resolve.',
                    'error'
                )
                _month = datetime.utcnow().strftime('%Y-%m')
                ContestEntry.query.filter_by(user_id=current_user.id, contest_month=_month).delete()
                db.session.commit()

        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if api_key:
            try:
                import traceback
                from engine.auto_score import auto_score, build_audit_data
                from engine.compositor import build_card1
                result = auto_score(image_path=img.thumb_path, genre=img.genre,
                                    title=img.asset_name, photographer=img.photographer_name,
                                    subject=img.subject, location=img.location)

                # ── AI suspicion check ────────────────────────────────────
                ai_suspicion = float(result.get('ai_suspicion', 0.0))
                img.ai_suspicion        = ai_suspicion
                img.ai_suspicion_reason = result.get('ai_suspicion_reason') or None
                img.needs_review        = bool(result.get('needs_review', False))

                if ai_suspicion >= 0.7:
                    # TIER 3 — Auto-flagged: almost certainly AI-generated
                    img.score            = 0.0
                    img.tier             = 'Apprentice'
                    img.dod_score        = 0.0
                    img.disruption_score = 0.0
                    img.dm_score         = 0.0
                    img.wonder_score     = 0.0
                    img.aq_score         = 0.0
                    img.archetype        = ''
                    img.soul_bonus       = False
                    img.status           = 'scored'
                    img.scored_at        = datetime.utcnow()
                    img.is_flagged       = True
                    img.needs_review     = True
                    img.is_public        = False
                    img.flagged_reason   = f'AI generation detected (suspicion: {ai_suspicion:.2f}). {img.ai_suspicion_reason or ""}'.strip()
                    img.flagged_at       = datetime.utcnow()
                    db.session.commit()
                    flash(
                        '🚫 This image has been flagged as potentially AI-generated and cannot be submitted. '
                        'Only original photographs taken by you are accepted. '
                        'If you believe this is an error, contact sreeks@gmail.com.',
                        'error'
                    )
                else:
                    # Score normally
                    img.dod_score        = float(result.get('dod',0))
                    img.disruption_score = float(result.get('disruption',0))
                    img.dm_score         = float(result.get('dm',0))
                    img.wonder_score     = float(result.get('wonder',0))
                    img.aq_score         = float(result.get('aq',0))
                    img.score            = float(result.get('score',0))
                    img.tier             = get_tier(float(result.get('score',0)))
                    img.archetype        = result.get('archetype','')
                    img.soul_bonus       = result.get('soul_bonus',False)
                    img.status           = 'scored'
                    img.scored_at        = datetime.utcnow()
                    audit = build_audit_data(result, img)
                    img.set_audit(audit)

                    # TIER 2 — Needs human review:
                    # (a) AI suspicion in amber zone 0.4–0.69, OR
                    # (b) Grandmaster score (9.0+) — always requires RAW verification
                    if ai_suspicion >= 0.4 or img.score >= 9.0:
                        img.needs_review    = True
                        img.is_public       = False   # held from public until admin clears
                        review_reason_parts = []
                        if ai_suspicion >= 0.4:
                            review_reason_parts.append(f'AI suspicion score {ai_suspicion:.2f} (amber zone)')
                        if img.score >= 9.0:
                            review_reason_parts.append(f'Grandmaster score {img.score} requires RAW verification')
                        img.flagged_reason  = ' · '.join(review_reason_parts)

                    db.session.commit()

                    try:
                        card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                                      f"{secure_filename((img.photographer_name or 'unknown').replace(' ',''))}_"
                                      f"{img.genre}_{img.score}.jpg")
                        card_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
                        build_card1(img.thumb_path, audit, card_path)
                        img.card_path = card_path
                        card_url = _r2_upload_card(card_path, uid + '_card')
                        if card_url:
                            img.card_url = card_url
                        db.session.commit()
                    except Exception as card_err:
                        app.logger.error(f'[upload card build error] {traceback.format_exc()}')

                    flash(f'Auto-scored! LL-Score: {img.score} — {img.tier}', 'success')
                    if getattr(img, 'needs_review', False):
                        if img.score >= 9.0 and ai_suspicion < 0.4:
                            flash(
                                f'🏆 Grandmaster score! Your image has been submitted for RAW verification. '
                                f'Email your original RAW file to sreeks@gmail.com within 7 days.',
                                'warning'
                            )
                        else:
                            flash(
                                f'⚠️ Your image has been flagged for human review before going public. '
                                f'This is usually resolved within 24–48 hours. '
                                f'Contact sreeks@gmail.com if you have questions.',
                                'warning'
                            )
            except Exception as e:
                app.logger.error(f'[upload scoring error] {traceback.format_exc()}')
                db.session.commit()
                err_str = str(e)
                if '529' in err_str or 'overloaded' in err_str.lower():
                    flash('Image uploaded ✅ — AI servers are currently busy (peak hours). '
                          'Your image has been saved. Please score it from the dashboard '
                          'during off-peak hours: 6am–11am IST or 11pm–5am IST.', 'warning')
                else:
                    flash(f'Uploaded. Auto-scoring failed: {e}.', 'warning')
        else:
            flash('Image uploaded! Add scores below.', 'success')

        # XHR (upload.html) gets JSON so JS controls the redirect
        # Standard form POST (fallback) gets the normal redirect
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if getattr(img, 'is_flagged', False):
                return jsonify({
                    'status': 'flagged',
                    'image_id': img.id,
                    'message': '🚫 This image has been flagged as potentially AI-generated and cannot be submitted. Only original photographs taken by you are accepted. If you believe this is an error, contact sreeks@gmail.com.',
                    'redirect': url_for('dashboard')
                })
            if getattr(img, 'needs_review', False):
                if img.score >= 9.0:
                    msg = (f'🏆 Grandmaster score ({img.score})! Your image has been held for RAW verification. '
                           f'Email your original RAW file to sreeks@gmail.com within 7 days.')
                else:
                    msg = ('⚠️ Your image has been held for human review before going public. '
                           'Usually resolved within 24–48 hours.')
                return jsonify({
                    'status': 'needs_review',
                    'image_id': img.id,
                    'score': img.score,
                    'tier': img.tier,
                    'message': msg,
                    'redirect': url_for('image_detail', image_id=img.id)
                })
            return jsonify({
                'status': 'ok',
                'image_id': img.id,
                'score': img.score,
                'tier': img.tier,
                'redirect': url_for('image_detail', image_id=img.id)
            })
        return redirect(url_for('image_detail', image_id=img.id))

    return render_template('upload.html', genres=GENRE_IDS, genre_choices=GENRE_CHOICES)


@app.route('/image/<int:image_id>/retry-score', methods=['POST'])
@login_required
def retry_score(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)
    if img.status == 'scored':
        flash('This image has already been scored.', 'info')
        return redirect(url_for('image_detail', image_id=image_id))
    if not img.thumb_path or not os.path.exists(img.thumb_path):
        if not img.thumb_url:
            flash('Image file not found. Please contact support.', 'error')
            return redirect(url_for('image_detail', image_id=image_id))

    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        flash('Scoring service not available. Please try again later.', 'error')
        return redirect(url_for('image_detail', image_id=image_id))

    try:
        import traceback, tempfile
        from engine.auto_score import auto_score, build_audit_data
        from engine.compositor import build_card1

        thumb_path = img.thumb_path
        temp_file  = None
        if not thumb_path or not os.path.exists(thumb_path):
            try:
                from storage import get_client, BUCKET
                tf = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                get_client().download_fileobj(
                    BUCKET, 'thumbs/' + img.thumb_url.split('/thumbs/')[-1], tf
                )
                tf.close()
                thumb_path = temp_file = tf.name
            except Exception as e:
                flash(f'Could not retrieve image for scoring: {e}', 'error')
                return redirect(url_for('image_detail', image_id=image_id))

        result = auto_score(
            image_path   = thumb_path,
            genre        = img.genre,
            title        = img.asset_name,
            photographer = img.photographer_name,
            subject      = img.subject,
            location     = img.location,
        )

        img.dod_score        = float(result.get('dod', 0))
        img.disruption_score = float(result.get('disruption', 0))
        img.dm_score         = float(result.get('dm', 0))
        img.wonder_score     = float(result.get('wonder', 0))
        img.aq_score         = float(result.get('aq', 0))
        img.score            = float(result.get('score', 0))
        img.tier             = get_tier(float(result.get('score', 0)))
        img.archetype        = result.get('archetype', '')
        img.soul_bonus       = result.get('soul_bonus', False)
        img.status           = 'scored'
        img.scored_at        = datetime.utcnow()
        audit = build_audit_data(result, img)
        img.set_audit(audit)
        db.session.commit()

        try:
            uid       = str(uuid.uuid4())
            card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                          f"{secure_filename((img.photographer_name or 'unknown').replace(' ',''))}_"
                          f"{img.genre}_{img.score}.jpg")
            card_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
            build_card1(thumb_path, audit, card_path)
            img.card_path = card_path
            card_url = _r2_upload_card(card_path, uid + '_card')
            if card_url:
                img.card_url = card_url
            db.session.commit()
        except Exception:
            app.logger.error(f'[retry_score card error] {traceback.format_exc()}')

        if temp_file:
            try: os.unlink(temp_file)
            except: pass

        flash(f'Scored! LL-Score: {img.score} — {img.tier}', 'success')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[retry_score] {traceback.format_exc()}')
        err = str(e)
        if '529' in err or 'overloaded' in err.lower():
            flash('AI engine is busy right now. Try again during off-peak hours: 6am–11am IST or 11pm–5am IST.', 'warning')
        else:
            flash(f'Scoring failed: {err[:120]}', 'error')

    return redirect(url_for('image_detail', image_id=image_id))


@app.route('/image/<int:image_id>')
@login_required
def image_detail(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    percentile_data = {}
    if img.status == 'scored' and img.score and not getattr(img, 'is_flagged', False):
        try:
            from engine.scoring import compute_percentile
            percentile_data = compute_percentile(float(img.score), genre=img.genre)
        except Exception as e:
            app.logger.warning(f'[percentile] {e}')
    return render_template('image_detail.html', image=img, archetypes=ARCHETYPES, percentile=percentile_data)


@app.route('/image/<int:image_id>/score', methods=['POST'])
@login_required
def score_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    try:
        dod=float(request.form.get('dod',0))
        disruption=float(request.form.get('disruption',0))
        dm=float(request.form.get('dm',0))
        wonder=float(request.form.get('wonder',0))
        aq=float(request.form.get('aq',0))
        archetype=request.form.get('archetype','Sovereign Momentum')
        byline_1=request.form.get('byline_1','')
        byline_2=request.form.get('byline_2','')
        iucn_tag=request.form.get('iucn_tag','')
        final_score, tier, soul_bonus, checks = calculate_score(img.genre, dod, disruption, dm, wonder, aq)
        img.dod_score=dod; img.disruption_score=disruption; img.dm_score=dm
        img.wonder_score=wonder; img.aq_score=aq; img.score=final_score
        img.tier=tier; img.archetype=archetype; img.soul_bonus=soul_bonus
        img.status='scored'; img.scored_at=datetime.utcnow()
        audit = {
            'asset': img.asset_name,
            'meta': f"{img.genre}  ·  {img.format}  ·  {img.subject}  ·  {img.location}",
            'score': str(final_score), 'tier': tier, 'dec': archetype,
            'credit': img.photographer_name,
            'genre_tag': f"{img.genre.upper()}  ·  {img.format}",
            'soul_bonus': soul_bonus, 'iucn_tag': iucn_tag or None,
            'modules': [('DoD',dod),('Disruption',disruption),('DM',dm),('Wonder',wonder),('AQ',aq)],
            'rows': [
                ('Technical\nIntegrity', request.form.get('row_technical','')),
                ('Geometric\nHarmony',   request.form.get('row_geometric','')),
                ('Decisive\nMoment',     request.form.get('row_dm','')),
                ('Wonder\nFactor',       request.form.get('row_wonder','')),
                ('AQ — Soul',            request.form.get('row_aq','')),
            ],
            'byline_1': byline_1, 'byline_2_body': byline_2,
            'badges_g': request.form.get('badges_g','').splitlines(),
            'badges_w': request.form.get('badges_w','').splitlines(),
        }
        img.set_audit(audit)

        from engine.compositor import build_card1 as build_card
        uid = str(uuid.uuid4())
        card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                      f"{secure_filename((img.photographer_name or 'unknown').replace(' ',''))}_"
                      f"{img.genre}_{final_score}.jpg")
        card_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
        build_card(img.thumb_path, audit, card_path)
        img.card_path = card_path

        card_url = _r2_upload_card(card_path, uid + '_card')
        if card_url:
            img.card_url = card_url

        db.session.commit()
        flash(f'Scored! LL-Score: {final_score} — {tier}', 'success')
    except Exception as e:
        flash(f'Scoring error: {e}', 'error')
    return redirect(url_for('image_detail', image_id=image_id))


@app.route('/image/<int:image_id>/download')
def download_card(image_id):
    img = Image.query.get_or_404(image_id)
    if not img.score:
        return "This image has not been scored yet.", 404

    import io, tempfile, os as _os
    from engine.compositor import build_card1, build_card2

    audit = img.get_audit() or {}
    app.logger.info(f'[download] img={image_id} audit_keys={list(audit.keys())}')
    modules = [(n,v) for n,v in [
        ('DoD',        img.dod_score),
        ('Disruption', img.disruption_score),
        ('DM',         img.dm_score),
        ('Wonder',     img.wonder_score),
        ('AQ',         img.aq_score),
    ] if v and float(v) > 0]

    card_data = {
        'score':         img.score,
        'tier':          img.tier or '',
        'asset':         img.asset_name or img.original_filename or 'Untitled',
        'meta':          '  ·  '.join(filter(None,[img.genre,img.format,img.location])),
        'dec':           img.archetype or '',
        'credit':        img.photographer_name or '',
        'soul_bonus':    bool(img.soul_bonus),
        'iucn_tag':      audit.get('iucn_tag',''),
        'modules':       modules,
        'rows':          audit.get('rows',[]),
        'byline_1':      audit.get('byline_1',''),
        'byline_2_body': audit.get('byline_2_body','') or audit.get('byline_2',''),
        'badges_g':      audit.get('badges_g',[]),
        'badges_w':      audit.get('badges_w',[]),
    }

    photo_tmp  = None
    photo_path = img.thumb_path if (img.thumb_path and _os.path.exists(img.thumb_path)) else None
    if not photo_path and img.thumb_url:
        try:
            from storage import get_client, BUCKET
            tf = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            get_client().download_fileobj(BUCKET, 'thumbs/'+img.thumb_url.split('/thumbs/')[-1], tf)
            tf.close()
            photo_path = photo_tmp = tf.name
        except Exception as e:
            app.logger.warning(f'Thumb fetch failed: {e}')

    try:
        t1 = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        t2 = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        t1.close(); t2.close()

        build_card1(photo_path, card_data, t1.name)
        build_card2(card_data, t2.name)

        import re as _re
        raw = img.asset_name or 'card'
        clean = _re.sub(r'(?i)screenshot[\d._\-atATPM ]+','',raw).strip('_- ') or 'RatingCard'
        clean = clean[:40].replace(' ','_')

        # Build 2-page PDF (page 1 = score card, page 2 = analysis)
        from PIL import Image as _PILImg
        pg1 = _PILImg.open(t1.name).convert('RGB')
        pg2 = _PILImg.open(t2.name).convert('RGB')
        pdf_buf = io.BytesIO()
        pg1.save(pdf_buf, format='PDF', save_all=True, append_images=[pg2], resolution=150)
        pdf_bytes = pdf_buf.getvalue()

    finally:
        for p in [t1.name if t1 else None, t2.name if t2 else None, photo_tmp]:
            try:
                if p: _os.unlink(p)
            except: pass

    from flask import Response
    return Response(
        pdf_bytes,
        headers={
            'Content-Type':        'application/pdf',
            'Content-Disposition': f'inline; filename="LensLeague_{clean}_RatingCard.pdf"',
            'Content-Length':      str(len(pdf_bytes)),
            'Cache-Control':       'no-store, no-cache, must-revalidate',
            'Pragma':              'no-cache',
            'X-Content-Type-Options': 'nosniff',
        }
    )


@app.route('/image/<int:image_id>/thumb')
@login_required
def serve_thumb(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    if img.thumb_url:
        return redirect(img.thumb_url)
    if img.thumb_path and os.path.exists(img.thumb_path):
        return send_file(img.thumb_path, mimetype='image/jpeg')
    abort(404)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    # Redirect to the new unified profile page
    return redirect(url_for('profile'))


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@app.route('/leaderboard')
def leaderboard():
    genre  = request.args.get('genre', 'all')
    tier   = request.args.get('tier', 'all')
    period = request.args.get('period', 'all')
    track  = request.args.get('track', 'all')
    tab    = request.args.get('tab', 'images')
    city   = request.args.get('city', 'all')

    now = datetime.utcnow()
    if period == 'week':
        since = now - timedelta(days=7)
    elif period == 'month':
        since = now - timedelta(days=30)
    else:
        since = None

    def apply_filters(q, user_already_joined=False):
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
        if city != 'all':
            if not user_already_joined:
                q = q.join(User, Image.user_id == User.id)
            q = q.filter(User.city == city)
        return q

    top_images = (apply_filters(Image.query, user_already_joined=False)
                  .order_by(desc(Image.score))
                  .limit(20)
                  .all())

    # Top Photographers — grouped by user_id, sorted by avg_score DESC
    pg_base = (
        db.session.query(
            Image.user_id,
            User.username,
            User.full_name,
            User.city,
            User.state,
            func.avg(Image.score).label('avg_score'),
            func.max(Image.score).label('best_score'),
            func.count(Image.id).label('image_count'),
            func.sum(Image.peer_rating_count).label('total_peer_ratings'),
        )
        .join(User, Image.user_id == User.id)
    )
    pg_base = apply_filters(pg_base, user_already_joined=True)
    pg_rows = (
        pg_base
        .group_by(Image.user_id, User.username, User.full_name, User.city, User.state)
        .order_by(desc('avg_score'))
        .limit(20)
        .all()
    )
    photographer_stats = []
    for row in pg_rows:
        photographer_stats.append({
            'user_id':            row.user_id,
            'username':           row.username,
            'display_name':       row.full_name or row.username,
            'city':               row.city,
            'state':              row.state,
            'avg_score':          round(float(row.avg_score), 2) if row.avg_score else 0,
            'best_score':         float(row.best_score) if row.best_score else 0,
            'image_count':        row.image_count,
            'total_peer_ratings': int(row.total_peer_ratings or 0),
        })

    # Cities for filter dropdown
    cities = [c[0] for c in (
        db.session.query(User.city)
        .join(Image, Image.user_id == User.id)
        .filter(User.city != None, Image.status == 'scored', Image.is_public == True)
        .distinct().order_by(User.city).all()
    ) if c[0]]

    all_tiers = ['Apprentice', 'Practitioner', 'Master', 'Grandmaster', 'Legend']

    # ── Camera rankings (lazy — only computed for Cameras tab) ───────────────
    camera_rankings = []
    if tab == 'cameras':
        from collections import defaultdict
        _cam_q = Image.query.filter(
            Image.status == 'scored',
            Image.score != None,
            Image.score > 0,
            Image.is_public == True,
            db.or_(Image.is_flagged == False, Image.is_flagged == None),
            db.or_(Image.needs_review == False, Image.needs_review == None),
            Image.exif_camera != None,
            Image.exif_camera != '',
        )
        if since:
            _cam_q = _cam_q.filter(Image.created_at >= since)
        if track == 'camera':
            _cam_q = _cam_q.filter(db.or_(
                db.text("camera_track = 'camera'"),
                db.text("camera_track IS NULL"),
            ))
        elif track == 'mobile':
            _cam_q = _cam_q.filter(db.text("camera_track = 'mobile'"))

        _cam_buckets = defaultdict(list)
        for img in _cam_q.all():
            cam = (img.exif_camera or '').strip()
            if cam:
                _cam_buckets[cam].append({
                    'score': img.score,
                    'track': img.camera_track or 'camera',
                })
        for model, entries in _cam_buckets.items():
            scores = [e['score'] for e in entries]
            tracks = [e['track'] for e in entries]
            dominant = 'mobile' if tracks.count('mobile') > tracks.count('camera') else 'camera'
            camera_rankings.append({
                'model':      model,
                'track':      dominant,
                'count':      len(scores),
                'avg_score':  round(sum(scores) / len(scores), 2),
                'best_score': round(max(scores), 2),
            })
        camera_rankings.sort(key=lambda x: x['avg_score'], reverse=True)
        camera_rankings = camera_rankings[:30]

    # ── Lens rankings (lazy — only computed for Lenses tab) ──────────────────
    # Uses exif_lens where available, falls back to exif_camera for existing images
    lens_rankings = []
    if tab == 'lenses':
        try:
            from collections import defaultdict
            _lens_q = Image.query.filter(
                Image.status == 'scored',
                Image.score != None,
                Image.score > 0,
                Image.is_public == True,
                db.or_(Image.is_flagged == False, Image.is_flagged == None),
                db.or_(Image.needs_review == False, Image.needs_review == None),
                db.or_(
                    db.and_(Image.exif_lens != None, Image.exif_lens != ''),
                    db.and_(Image.exif_camera != None, Image.exif_camera != ''),
                ),
                db.or_(
                    db.text("camera_track = 'camera'"),
                    db.text("camera_track IS NULL"),
                ),
            )
            if since:
                _lens_q = _lens_q.filter(Image.created_at >= since)

            _lens_buckets = defaultdict(list)
            for img in _lens_q.all():
                lens = (img.exif_lens or '').strip() or (img.exif_camera or '').strip()
                if lens:
                    _lens_buckets[lens].append(img.score)
            for model, scores in _lens_buckets.items():
                lens_rankings.append({
                    'model':      model,
                    'count':      len(scores),
                    'avg_score':  round(sum(scores) / len(scores), 2),
                    'best_score': round(max(scores), 2),
                })
            lens_rankings.sort(key=lambda x: x['avg_score'], reverse=True)
            lens_rankings = lens_rankings[:30]
        except Exception:
            lens_rankings = []

    return render_template('leaderboard.html',
        top_images         = top_images,
        photographer_stats = photographer_stats,
        camera_rankings    = camera_rankings,
        lens_rankings      = lens_rankings,
        all_genres         = GENRE_IDS,
        all_tiers          = all_tiers,
        cities             = cities,
        genre              = genre,
        tier               = tier,
        period             = period,
        track              = track,
        tab                = tab,
        city               = city,
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users  = User.query.count()
    total_images = Image.query.count()
    scored       = Image.query.filter_by(status='scored').count()
    pending      = Image.query.filter_by(status='pending').count()
    recent       = Image.query.order_by(Image.created_at.desc()).limit(20).all()
    cal_stats    = compute_calibration_stats(Image.query.filter_by(status='scored').all())

    cal_trend = {}
    try:
        recent_logs = (CalibrationLog.query
                       .order_by(CalibrationLog.logged_at.desc())
                       .limit(40).all())
        batches = []
        current_batch = []
        last_time = None
        for log in recent_logs:
            if last_time is None or (last_time - log.logged_at).total_seconds() < 60:
                current_batch.append(log)
            else:
                batches.append(current_batch)
                current_batch = [log]
                if len(batches) >= 2:
                    break
            last_time = log.logged_at
        if current_batch:
            batches.append(current_batch)

        if len(batches) >= 2:
            current_snap  = {l.genre: l for l in batches[0]}
            previous_snap = {l.genre: l for l in batches[1]}
            for genre_key in current_snap:
                curr = current_snap[genre_key]
                prev = previous_snap.get(genre_key)
                cal_trend[genre_key] = {
                    'current':  curr,
                    'previous': prev,
                    'score_delta':  round(curr.avg_score  - prev.avg_score,  2) if prev else None,
                    'dod_delta':    round(curr.avg_dod    - prev.avg_dod,    2) if prev else None,
                    'dis_delta':    round(curr.avg_dis    - prev.avg_dis,    2) if prev else None,
                    'dm_delta':     round(curr.avg_dm     - prev.avg_dm,     2) if prev else None,
                    'wonder_delta': round(curr.avg_wonder - prev.avg_wonder, 2) if prev else None,
                    'aq_delta':     round(curr.avg_aq     - prev.avg_aq,     2) if prev else None,
                }
        elif len(batches) == 1:
            for log in batches[0]:
                cal_trend[log.genre] = {'current': log, 'previous': None, 'score_delta': None}
    except Exception as e:
        print(f'[cal trend] {e}')

    drift_alerts = []
    for genre_key, s in cal_stats.items():
        if s['avg_score'] < 5.0:
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg score {s["avg_score"]} — possible under-scoring'})
        elif s['avg_score'] > 8.5:
            drift_alerts.append({'genre': genre_key, 'type': 'high', 'msg': f'Avg score {s["avg_score"]} — possible over-scoring'})
        if s['avg_dod'] < 3.0:
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg DoD {s["avg_dod"]} — engine may be under-valuing difficulty'})
        if s['avg_aq'] < 4.0:
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg AQ {s["avg_aq"]} — low emotional resonance scores across genre'})

    all_users = User.query.filter(User.role != 'admin').order_by(User.created_at.desc()).all()

    open_reports_count = ImageReport.query.filter_by(status='open').count()

    # League integrity summary
    suspended_users = User.query.filter_by(league_suspended=True).all()
    mismatch_users  = User.query.filter(
        User.camera_mismatch_count >= 1,
        db.or_(User.league_suspended == False, User.league_suspended == None)
    ).all()

    # Subscription stats for export panel
    stats_sub = {
        'subscribers':  User.query.filter_by(is_subscribed=True).count(),
        'camera_subs':  User.query.filter_by(is_subscribed=True, subscription_track='camera').count(),
        'mobile_subs':  User.query.filter_by(is_subscribed=True, subscription_track='mobile').count(),
        'free_users':   User.query.filter(
                            User.role != 'admin',
                            db.or_(User.is_subscribed == False, User.is_subscribed == None)
                        ).count(),
    }

    return render_template('admin.html', total_users=total_users, total_images=total_images,
                           scored=scored, pending=pending, recent=recent,
                           cal_stats=cal_stats, cal_trend=cal_trend, drift_alerts=drift_alerts,
                           all_users=all_users, open_reports_count=open_reports_count,
                           suspended_users=suspended_users, mismatch_users=mismatch_users,
                           stats=stats_sub)


@app.route('/admin/user/<int:user_id>/clear-suspension', methods=['POST'])
@login_required
@admin_required
def admin_clear_suspension(user_id):
    """Clear league suspension and reset mismatch count for a user."""
    user = User.query.get_or_404(user_id)
    user.league_suspended        = False
    user.league_suspended_at     = None
    user.league_suspended_reason = None
    user.camera_mismatch_count   = 0
    db.session.commit()
    flash(f'League suspension cleared for {user.full_name or user.username}.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/calibrate', methods=['POST'])
@login_required
@admin_required
def run_calibration():
    images = Image.query.filter_by(status='scored').all()
    stats  = compute_calibration_stats(images)
    for genre_key, s in stats.items():
        log = CalibrationLog(genre=genre_key, image_count=s['count'], avg_score=s['avg_score'],
                             avg_dod=s['avg_dod'], avg_dis=s['avg_dis'], avg_dm=s['avg_dm'],
                             avg_wonder=s['avg_wonder'], avg_aq=s['avg_aq'])
        db.session.add(log)
    db.session.commit()
    flash(f'Calibration logged for {len(stats)} genres.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.thumb_url:
        try:
            key = img.thumb_url.split(r2.R2_PUBLIC_URL + '/')[-1]
            r2.delete_file(key)
        except Exception:
            pass
    if img.card_url:
        try:
            key = img.card_url.split(r2.R2_PUBLIC_URL + '/')[-1]
            r2.delete_file(key)
        except Exception:
            pass
    # Delete all related records first to avoid NOT NULL FK violations
    try:
        from models import CalibrationNote
        CalibrationNote.query.filter_by(image_id=image_id).delete()
    except Exception:
        pass
    try:
        ImageReport.query.filter_by(image_id=image_id).delete()
    except Exception:
        pass
    try:
        RatingAssignment.query.filter_by(image_id=image_id).delete()
        PeerRating.query.filter_by(image_id=image_id).delete()
        PeerPoolEntry.query.filter_by(image_id=image_id).delete()
    except Exception:
        pass
    db.session.delete(img)
    db.session.commit()
    flash(f'Image deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/cleanup', methods=['POST'])
@login_required
@admin_required
def admin_cleanup():
    count = db.session.execute(db.text("SELECT COUNT(*) FROM images WHERE thumb_url IS NULL")).scalar()
    db.session.execute(db.text("DELETE FROM images WHERE thumb_url IS NULL"))
    db.session.commit()
    flash(f'Deleted {count} broken images with no thumbnail.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/bulk-delete', methods=['POST'])
@login_required
@admin_required
def admin_bulk_delete():
    image_ids = request.form.getlist('image_ids')
    if not image_ids:
        flash('No images selected.', 'warning')
        return redirect(url_for('admin_dashboard'))
    deleted = 0
    for image_id in image_ids:
        try:
            img = Image.query.get(int(image_id))
            if not img:
                continue
            if img.thumb_url:
                try:
                    key = img.thumb_url.replace(r2.R2_PUBLIC_URL + '/', '')
                    r2.delete_file(key)
                except Exception:
                    pass
            if img.card_url:
                try:
                    key = img.card_url.replace(r2.R2_PUBLIC_URL + '/', '')
                    r2.delete_file(key)
                except Exception:
                    pass
            # Delete all related records first to avoid NOT NULL FK violations
            try:
                from models import CalibrationNote
                CalibrationNote.query.filter_by(image_id=img.id).delete()
            except Exception:
                pass
            try:
                ImageReport.query.filter_by(image_id=img.id).delete()
            except Exception:
                pass
            try:
                RatingAssignment.query.filter_by(image_id=img.id).delete()
                PeerRating.query.filter_by(image_id=img.id).delete()
                PeerPoolEntry.query.filter_by(image_id=img.id).delete()
            except Exception:
                pass
            db.session.delete(img)
            deleted += 1
        except Exception as e:
            db.session.rollback()
            print(f'[bulk delete] image {image_id}: {e}')
    db.session.commit()
    flash(f'Deleted {deleted} image(s).', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/toggle-example', methods=['POST'])
@login_required
@admin_required
def toggle_calibration_example(image_id):
    img = Image.query.get_or_404(image_id)
    img.is_calibration_example = not img.is_calibration_example
    db.session.commit()
    status = 'set as calibration example' if img.is_calibration_example else 'removed from calibration examples'
    flash(f'"{img.asset_name}" {status}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.filter(User.role != 'admin').order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/user/<int:user_id>/toggle-subscription', methods=['POST'])
@login_required
@admin_required
def admin_toggle_subscription(user_id):
    user = User.query.get_or_404(user_id)
    user.is_subscribed = not getattr(user, 'is_subscribed', False)
    if user.is_subscribed:
        user.subscription_track = request.form.get('track', 'camera')
        user.subscription_plan  = request.form.get('plan', 'monthly')
        user.subscribed_at      = datetime.utcnow()
    else:
        user.subscription_track = None
        user.subscription_plan  = None
    db.session.commit()
    status = 'activated' if user.is_subscribed else 'deactivated'
    flash(f'Subscription {status} for {user.full_name or user.username}.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot delete an admin account.', 'error')
        return redirect(url_for('admin_users'))

    username = user.full_name or user.username

    try:
        # 1. CalibrationNotes by this user (as admin) and on their images
        try:
            from models import CalibrationNote
            CalibrationNote.query.filter_by(admin_id=user_id).delete()
            image_ids = [img.id for img in user.images]
            if image_ids:
                CalibrationNote.query.filter(CalibrationNote.image_id.in_(image_ids)).delete(synchronize_session=False)
        except Exception as e:
            app.logger.warning(f'[delete_user] calibration notes: {e}')

        # 2. ImageReports filed by this user + reports on their images
        try:
            ImageReport.query.filter_by(reporter_id=user_id).delete()
            if image_ids:
                ImageReport.query.filter(ImageReport.image_id.in_(image_ids)).delete(synchronize_session=False)
        except Exception as e:
            app.logger.warning(f'[delete_user] image reports: {e}')

        # 3. Peer ratings given by this user + received on their images
        try:
            PeerRating.query.filter_by(rater_id=user_id).delete()
            if image_ids:
                PeerRating.query.filter(PeerRating.image_id.in_(image_ids)).delete(synchronize_session=False)
        except Exception as e:
            app.logger.warning(f'[delete_user] peer ratings: {e}')

        # 4. Rating assignments
        try:
            RatingAssignment.query.filter_by(rater_id=user_id).delete()
            if image_ids:
                RatingAssignment.query.filter(RatingAssignment.image_id.in_(image_ids)).delete(synchronize_session=False)
        except Exception as e:
            app.logger.warning(f'[delete_user] rating assignments: {e}')

        # 5. Peer pool entries
        try:
            PeerPoolEntry.query.filter_by(user_id=user_id).delete()
            if image_ids:
                PeerPoolEntry.query.filter(PeerPoolEntry.image_id.in_(image_ids)).delete(synchronize_session=False)
        except Exception as e:
            app.logger.warning(f'[delete_user] peer pool: {e}')

        # 6. Contest entries
        try:
            ContestEntry.query.filter_by(user_id=user_id).delete()
        except Exception as e:
            app.logger.warning(f'[delete_user] contest entries: {e}')

        # 7. Open contest entries
        try:
            OpenContestEntry.query.filter_by(user_id=user_id).delete()
        except Exception as e:
            app.logger.warning(f'[delete_user] open contest entries: {e}')

        # 8. BOW submissions
        try:
            from models import BowSubmission
            BowSubmission.query.filter_by(user_id=user_id).delete()
        except Exception as e:
            app.logger.warning(f'[delete_user] bow submissions: {e}')

        # 9. Delete images + R2 cleanup
        for img in list(user.images):
            if img.thumb_url:
                try:
                    key = img.thumb_url.split(r2.R2_PUBLIC_URL + '/')[-1]
                    r2.delete_file(key)
                except Exception:
                    pass
            if img.card_url:
                try:
                    key = img.card_url.split(r2.R2_PUBLIC_URL + '/')[-1]
                    r2.delete_file(key)
                except Exception:
                    pass
            db.session.delete(img)

        # 10. Delete the user
        db.session.delete(user)
        db.session.commit()
        flash(f'User "{username}" and all associated data permanently deleted.', 'success')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[admin_delete_user] failed for user {user_id}: {e}')
        flash(f'Delete failed: {str(e)[:120]}', 'error')

    return redirect(url_for('admin_users'))


@app.route('/admin/fix-beta-plans', methods=['POST'])
@login_required
@admin_required
def admin_fix_beta_plans():
    """One-time fix: update all beta plan users to monthly."""
    users = User.query.filter_by(is_subscribed=True, subscription_plan='beta').all()
    for u in users:
        u.subscription_plan = 'monthly'
    db.session.commit()
    flash(f'Updated {len(users)} beta users to monthly plan.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/backfill-hashes', methods=['POST'])
@login_required
@admin_required
def backfill_hashes():
    from engine.processor import compute_phash
    from PIL import Image as PILImage
    import httpx, io
    updated = 0
    failed  = 0
    images  = Image.query.filter(Image.phash.is_(None)).all()
    for img in images:
        try:
            if img.thumb_url:
                resp = httpx.get(img.thumb_url, timeout=10, follow_redirects=True)
                pil  = PILImage.open(io.BytesIO(resp.content)).convert('RGB')
            elif img.thumb_path and os.path.exists(img.thumb_path):
                pil  = PILImage.open(img.thumb_path).convert('RGB')
            else:
                failed += 1
                continue
            img.phash = compute_phash(pil)
            updated += 1
        except Exception as e:
            print(f'[backfill] image {img.id}: {e}')
            failed += 1
    db.session.commit()
    flash(f'Backfilled {updated} image hashes. {failed} failed (no file).', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/feedback', methods=['POST'])
@login_required
@admin_required
def admin_feedback(image_id):
    from models import CalibrationNote
    img     = Image.query.get_or_404(image_id)
    module  = request.form.get('module', 'overall').strip()
    reason  = request.form.get('reason', '').strip()
    orig    = request.form.get('original_score', '')
    corr    = request.form.get('corrected_score', '')

    if not reason:
        flash('Please provide a reason for the correction.', 'error')
        return redirect(url_for('image_detail', image_id=image_id))

    note = CalibrationNote(
        image_id        = image_id,
        admin_id        = current_user.id,
        genre           = img.genre or 'Wildlife',
        module          = module,
        original_score  = float(orig) if orig else None,
        corrected_score = float(corr) if corr else None,
        reason          = reason,
    )
    db.session.add(note)

    if corr and module == 'overall':
        img.score = float(corr)
        img.status = 'scored'
        img.is_calibration_example = True
        flash(f'Correction saved. Image score updated to {corr} and marked as REF example.', 'success')
    else:
        flash(f'Calibration correction saved for {module.upper()}. Will influence future {img.genre} scoring.', 'success')

    db.session.commit()
    return redirect(url_for('image_detail', image_id=image_id))


@app.route('/image/score-single', methods=['POST'])
@login_required
def score_single_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No file'}), 400

    file         = request.files['image']
    raw_genre    = request.form.get('genre', 'Wildlife')
    genre        = normalise_genre(raw_genre)
    photographer = request.form.get('photographer_name', '').strip() or \
                   current_user.full_name or current_user.username

    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file'}), 400

    try:
        uid       = str(uuid.uuid4())
        filename  = secure_filename(file.filename)
        raw_path  = os.path.join(app.config['UPLOAD_FOLDER'], 'raw', f'{uid}_{filename}')
        file.save(raw_path)
        thumb_path, w, h, fmt, phash = ingest_image(raw_path, app.config['UPLOAD_FOLDER'])
        if os.path.exists(raw_path): os.remove(raw_path)

        from engine.processor import hash_similarity_pct
        for ex in Image.query.filter(Image.phash.isnot(None)).all():
            if hash_similarity_pct(phash, ex.phash) >= 90.0:
                return jsonify({
                    'status': 'duplicate',
                    'message': f'Already uploaded as "{ex.asset_name or ex.original_filename}"'
                })

        thumb_url = _r2_upload_thumb(thumb_path, uid)

        img = Image(
            user_id=current_user.id,
            original_filename=filename,
            stored_filename=os.path.basename(thumb_path),
            thumb_path=thumb_path, thumb_url=thumb_url,
            file_size_kb=int(os.path.getsize(thumb_path)/1024),
            width=w, height=h, format=fmt,
            asset_name=auto_title(filename, genre),
            phash=phash, genre=genre,
            photographer_name=photographer,
            camera_track=getattr(current_user, 'subscription_track', None),
            status='pending',
        )
        db.session.add(img)
        db.session.flush()

        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if api_key:
            try:
                from engine.auto_score import auto_score, build_audit_data
                scored = auto_score(image_path=img.thumb_path, genre=genre,
                                    title=img.asset_name, photographer=photographer)
                img.dod_score        = float(scored.get('dod', 0))
                img.disruption_score = float(scored.get('disruption', 0))
                img.dm_score         = float(scored.get('dm', 0))
                img.wonder_score     = float(scored.get('wonder', 0))
                img.aq_score         = float(scored.get('aq', 0))
                img.score            = float(scored.get('score', 0))
                img.tier             = get_tier(float(scored.get('score', 0)))
                img.archetype        = scored.get('archetype', '')
                img.soul_bonus       = scored.get('soul_bonus', False)
                img.status           = 'scored'
                img.scored_at        = datetime.utcnow()
                img.asset_name = auto_title(filename, genre, archetype=scored.get('archetype', ''))
                audit = build_audit_data(scored, img)
                img.set_audit(audit)
                db.session.commit()
                return jsonify({
                    'status': 'scored',
                    'filename': filename,
                    'score': img.score,
                    'tier': img.tier,
                    'image_id': img.id,
                    'asset_name': img.asset_name,
                })
            except ValueError as api_err:
                if '529' in str(api_err) or 'overloaded' in str(api_err).lower():
                    img.status = 'pending'
                    db.session.commit()
                    return jsonify({
                        'status': 'saved',
                        'filename': filename,
                        'message': 'API busy — saved for later scoring'
                    })
                raise
        else:
            img.status = 'pending'
            db.session.commit()
            return jsonify({'status': 'saved', 'filename': filename})

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'score_single_image error: {e}')
        return jsonify({'error': str(e)[:100]}), 500


@app.route('/admin/health-check')
@login_required
@admin_required
def admin_health_check():
    images = Image.query.filter_by(status='scored').all()
    issues = []
    healthy = 0

    for img in images:
        audit = img.get_audit() or {}
        img_issues = []

        if not audit:
            img_issues.append('no audit JSON')
        else:
            if not audit.get('rows'):
                img_issues.append('missing rows')
            if not audit.get('byline_1') and not audit.get('byline_2') and not audit.get('byline_2_body'):
                img_issues.append('missing byline')
            if not audit.get('byline_2') and not audit.get('byline_2_body'):
                img_issues.append('missing improvement text')
            rows = audit.get('rows', [])
            if rows and len(rows) < 5:
                img_issues.append(f'only {len(rows)}/5 analysis rows')

        if not img.score:
            img_issues.append('no score')
        if not img.tier:
            img_issues.append('no tier')
        if not img.thumb_url:
            img_issues.append('no thumb_url')

        if img_issues:
            issues.append({
                'id': img.id,
                'name': img.asset_name or img.original_filename,
                'genre': img.genre,
                'score': img.score,
                'issues': img_issues,
                'audit_keys': list(audit.keys()) if audit else []
            })
        else:
            healthy += 1

    return jsonify({
        'total_scored': len(images),
        'healthy': healthy,
        'issues_count': len(issues),
        'images_with_issues': issues
    })


@app.route('/admin/rescore-all', methods=['POST'])
@login_required
@admin_required
def admin_rescore_all():
    images = Image.query.filter_by(status='scored').all()
    results = {'rescored': 0, 'skipped': 0, 'errors': []}
    api_key = os.getenv('ANTHROPIC_API_KEY', '')

    if not api_key:
        return jsonify({'error': 'No API key configured'}), 500

    for img in images:
        audit = img.get_audit() or {}
        needs_rescore = (
            not audit.get('byline_2_body') and
            not audit.get('byline_2') and
            img.thumb_path and os.path.exists(img.thumb_path)
        )
        if not needs_rescore:
            results['skipped'] += 1
            continue

        try:
            from engine.auto_score import auto_score, build_audit_data
            scored = auto_score(
                image_path=img.thumb_path,
                genre=img.genre or 'Wildlife',
                title=img.asset_name,
                photographer=img.photographer_name
            )
            audit = build_audit_data(scored, img)
            img.set_audit(audit)
            img.dod_score        = float(scored.get('dod', img.dod_score or 0))
            img.disruption_score = float(scored.get('disruption', img.disruption_score or 0))
            img.dm_score         = float(scored.get('dm', img.dm_score or 0))
            img.wonder_score     = float(scored.get('wonder', img.wonder_score or 0))
            img.aq_score         = float(scored.get('aq', img.aq_score or 0))
            img.score            = float(scored.get('score', img.score or 0))
            img.tier             = get_tier(float(scored.get('score', img.score or 0)))
            img.archetype        = scored.get('archetype', img.archetype)
            db.session.commit()
            results['rescored'] += 1
        except Exception as e:
            db.session.rollback()
            results['errors'].append({'id': img.id, 'error': str(e)[:100]})

    return jsonify(results)


@app.route('/admin/transfer-images', methods=['POST'])
@login_required
@admin_required
def admin_transfer_images():
    photographer = request.form.get('photographer_name', '').strip()
    if not photographer:
        flash('Please enter a photographer name.', 'error')
        return redirect(url_for('admin_dashboard'))

    target_user = User.query.filter(
        db.or_(
            User.full_name.ilike(photographer),
            User.username.ilike(photographer)
        )
    ).first()

    if not target_user:
        flash(f'No registered user found matching "{photographer}". They need to register first.', 'warning')
        return redirect(url_for('admin_dashboard'))

    images = Image.query.filter(
        Image.photographer_name.ilike(photographer),
        Image.user_id != target_user.id
    ).all()

    if not images:
        flash(f'No images to transfer — all images credited to "{photographer}" already belong to their account.', 'info')
        return redirect(url_for('admin_dashboard'))

    for img in images:
        img.user_id = target_user.id
    db.session.commit()

    flash(f'✅ Transferred {len(images)} image{"s" if len(images)>1 else ""} to {target_user.full_name or target_user.username}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/flag', methods=['POST'])
@login_required
@admin_required
def admin_flag_image(image_id):
    """Flag an image as AI-generated — hides from public, keeps in DB for ML."""
    img    = Image.query.get_or_404(image_id)
    reason = request.form.get('reason', 'Manually flagged as AI-generated by admin').strip()
    img.is_flagged     = True
    img.needs_review   = True
    img.is_public      = False
    img.flagged_reason = reason
    img.flagged_at     = datetime.utcnow()
    img.score          = 0.0
    img.tier           = 'Apprentice'
    db.session.commit()
    flash(f'Image "{img.asset_name}" flagged and hidden from public view.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/unflag', methods=['POST'])
@login_required
@admin_required
def admin_unflag_image(image_id):
    """Unflag an image — returns it to normal visibility."""
    img = Image.query.get_or_404(image_id)
    img.is_flagged     = False
    img.needs_review   = False
    img.is_public      = True
    img.flagged_reason = None
    img.flagged_at     = None
    db.session.commit()
    flash(f'Image "{img.asset_name}" unflagged and restored to public view.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/approve-review', methods=['POST'])
@login_required
@admin_required
def admin_approve_review(image_id):
    """Clear the needs_review flag — approves image for public display."""
    img = Image.query.get_or_404(image_id)
    img.needs_review   = False
    img.is_public      = True
    img.flagged_reason = None
    db.session.commit()
    flash(f'Image "{img.asset_name}" approved — now visible to public.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))



# ── Community Report Routes ───────────────────────────────────────────────────

@app.route('/image/<int:image_id>/report', methods=['POST'])
@login_required
def report_image(image_id):
    """Submit a community report on a scored image."""
    img = Image.query.get_or_404(image_id)

    # Determine safe redirect — reporter may not own the image so image_detail would 403
    back_url = url_for('share_image', image_id=image_id)

    # Anti-abuse: reporter must have at least 3 scored images
    reporter_scored = Image.query.filter_by(
        user_id=current_user.id, status='scored'
    ).count()
    if reporter_scored < 3:
        flash('You need at least 3 scored images to submit a report.', 'warning')
        return redirect(back_url)

    # One report per image per user (enforced by DB UNIQUE constraint too)
    existing = ImageReport.query.filter_by(
        image_id=image_id, reporter_id=current_user.id
    ).first()
    if existing:
        flash('You have already submitted a report for this image.', 'info')
        return redirect(back_url)

    reason = request.form.get('reason', '').strip()
    detail = request.form.get('detail', '').strip()[:500]
    valid_reasons = ['AI-generated', 'Stolen', 'Duplicate', 'Other']
    if reason not in valid_reasons:
        flash('Invalid report reason.', 'danger')
        return redirect(back_url)

    report = ImageReport(
        image_id=image_id,
        reporter_id=current_user.id,
        reason=reason,
        detail=detail or None,
    )
    db.session.add(report)
    db.session.commit()
    flash('Report submitted. Our team will review it.', 'success')
    return redirect(back_url)


@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    """Admin view of all open community reports."""
    reports = (ImageReport.query
               .filter_by(status='open')
               .order_by(ImageReport.reported_at.desc())
               .all())
    return render_template('admin_reports.html', reports=reports)


@app.route('/admin/report/<int:report_id>/dismiss', methods=['POST'])
@login_required
@admin_required
def admin_dismiss_report(report_id):
    rpt = ImageReport.query.get_or_404(report_id)
    rpt.status = 'dismissed'
    db.session.commit()
    flash('Report dismissed.', 'success')
    return redirect(url_for('admin_reports'))


@app.route('/admin/report/<int:report_id>/request-raw', methods=['POST'])
@login_required
@admin_required
def admin_report_request_raw(report_id):
    rpt = ImageReport.query.get_or_404(report_id)
    img = rpt.image
    img.judge_referral = True
    img.needs_review   = True
    rpt.status         = 'actioned'
    db.session.commit()
    flash(f'RAW requested for "{img.asset_name}" — image held for review.', 'success')
    return redirect(url_for('admin_reports'))


@app.route('/admin/fix-tiers', methods=['POST'])
@login_required
@admin_required
def fix_tiers():
    images = Image.query.filter(Image.score.isnot(None), Image.score > 0).all()
    fixed = 0
    for img in images:
        correct_tier = get_tier(float(img.score))
        if img.tier != correct_tier:
            img.tier = correct_tier
            fixed += 1
    db.session.commit()
    flash(f'Fixed {fixed} image(s) with incorrect tier assignments.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/fix-photographer-names', methods=['POST'])
@login_required
@admin_required
def fix_photographer_names():
    old_name = request.form.get('old_name', '').strip()
    new_name = request.form.get('new_name', '').strip()
    if not old_name or not new_name:
        flash('Both old and new name required.', 'error')
        return redirect(url_for('admin_dashboard'))
    updated = Image.query.filter(Image.photographer_name == old_name).all()
    for img in updated:
        img.photographer_name = new_name
    db.session.commit()
    flash(f'Updated {len(updated)} image(s) from "{old_name}" to "{new_name}".', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/fix-calibration-table', methods=['POST'])
@login_required
@admin_required
def fix_calibration_table():
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text('DROP TABLE IF EXISTS calibration_logs CASCADE'))
            conn.execute(db.text('''
                CREATE TABLE calibration_logs (
                    id SERIAL PRIMARY KEY,
                    genre VARCHAR(60) NOT NULL,
                    image_count INTEGER,
                    avg_score FLOAT,
                    avg_dod FLOAT,
                    avg_dis FLOAT,
                    avg_dm FLOAT,
                    avg_wonder FLOAT,
                    avg_aq FLOAT,
                    note TEXT,
                    logged_by INTEGER,
                    logged_at TIMESTAMP DEFAULT NOW()
                )
            '''))
            conn.commit()
        flash('calibration_logs table rebuilt successfully.', 'success')
    except Exception as e:
        flash(f'Fix failed: {e}', 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/calibration-notes')
@login_required
@admin_required
def admin_calibration_notes():
    from models import CalibrationNote
    notes = CalibrationNote.query.order_by(CalibrationNote.created_at.desc()).all()
    return render_template('calibration_notes.html', notes=notes)


@app.route('/admin/calibration-notes/<int:note_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_calibration_note(note_id):
    from models import CalibrationNote
    note = CalibrationNote.query.get_or_404(note_id)
    note.is_active = not note.is_active
    db.session.commit()
    status = 'activated' if note.is_active else 'deactivated'
    flash(f'Calibration note {status}.', 'success')
    return redirect(url_for('admin_calibration_notes'))


@app.route('/admin/calibration-notes/<int:note_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_calibration_note(note_id):
    from models import CalibrationNote
    note = CalibrationNote.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    flash('Calibration note deleted.', 'success')
    return redirect(url_for('admin_calibration_notes'))


@app.route('/admin/debug-images')
@login_required
@admin_required
def debug_images():
    images = Image.query.order_by(Image.created_at.desc()).limit(20).all()
    rows = []
    for img in images:
        rows.append({
            'id': img.id,
            'asset_name': img.asset_name,
            'genre': img.genre,
            'status': img.status,
            'user_id': img.user_id,
            'photographer': img.photographer_name,
            'created_at': str(img.created_at),
            'score': img.score,
            'thumb_url': img.thumb_url,
        })
    return jsonify({'count': len(rows), 'images': rows})


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------

@app.route('/u/<username>')
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    images = (Image.query
              .filter_by(user_id=user.id, status='scored', is_public=True)
              .filter(Image.score != None)
              .filter(db.or_(Image.is_flagged == False, Image.is_flagged == None))
              .filter(db.or_(Image.needs_review == False, Image.needs_review == None))
              .order_by(Image.score.desc())
              .limit(24).all())

    total_images = len(images)
    avg_score    = round(sum(i.score for i in images) / total_images, 1) if total_images else 0
    best_score   = images[0].score if images else 0
    best_image   = images[0] if images else None

    # Top tier across all scored images
    tier_order = ['Legend', 'Grandmaster', 'Master', 'Practitioner', 'Apprentice']
    all_tiers  = [i.tier for i in images if i.tier]
    top_tier   = next((t for t in tier_order if t in all_tiers), None)

    # Genre list sorted by frequency
    from collections import Counter
    genre_counts = Counter(i.genre for i in images if i.genre)
    genre_list   = [g for g, _ in genre_counts.most_common()]
    genres_count = len(genre_list)

    return render_template('profile_public.html',
        user         = user,
        images       = images,
        total_images = total_images,
        avg_score    = avg_score,
        best_score   = best_score,
        best_image   = best_image,
        top_tier     = top_tier,
        genre_list   = genre_list,
        genres_count = genres_count,
    )


@app.route('/how-it-works')
def how_it_works():
    return render_template('how-it-works.html')

@app.route('/example-score')
def example_score():
    example_image = (Image.query
                     .filter(Image.status=='scored', Image.score != None, Image.is_public == True)
                     .order_by(db.func.random())
                     .first())
    return render_template('example-score.html', example_image=example_image)

@app.route('/stats')
def stats_page():
    from engine.scoring import compute_calibration_stats
    total_images  = Image.query.filter_by(status='scored').count()
    total_members = User.query.filter(User.role != 'admin').count()
    avg_score     = db.session.query(db.func.avg(Image.score)).filter(Image.score != None).scalar() or 0
    stats = {'total_images': total_images, 'total_members': total_members, 'avg_score': avg_score}
    genre_stats = compute_calibration_stats(Image.query.filter_by(status='scored').all())
    return render_template('stats.html', stats=stats, genre_stats=genre_stats)

@app.route('/science')
def science():
    return render_template('science.html')

@app.route('/sree-admin', methods=['GET', 'POST'])
def sree_admin_login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter your email and password.', 'error')
            return render_template('sree_admin_login.html')

        user = User.query.filter_by(email=email).first()

        if not user or not user.password_hash or user.role != 'admin':
            flash('Invalid credentials.', 'error')
            return render_template('sree_admin_login.html')

        if not check_password_hash(user.password_hash, password):
            flash('Invalid credentials.', 'error')
            return render_template('sree_admin_login.html')

        if not user.is_active:
            flash('Account deactivated.', 'error')
            return render_template('sree_admin_login.html')

        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user)
        return redirect(url_for('admin_dashboard'))

    return render_template('sree_admin_login.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/contest-rules')
def contest_rules():
    return render_template('contest_rules.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html', open_contest_active=is_open_contest_active())


# ---------------------------------------------------------------------------
# Contests
# ---------------------------------------------------------------------------

@app.route('/contests')
def contests():
    now         = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month  = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left   = (next_month - now).days

    monthly_top = {}
    for genre in GENRE_IDS:
        base = (Image.query
                .filter(
                    Image.status == 'scored',
                    Image.score != None,
                    Image.created_at >= month_start,
                    Image.genre == genre,
                ))
        camera_top = (base
                      .filter(db.or_(
                          db.text("camera_track = 'camera'"),
                          db.text("camera_track IS NULL"),
                      ))
                      .order_by(Image.score.desc())
                      .limit(3).all())
        mobile_top = (base
                      .filter(db.text("camera_track = 'mobile'"))
                      .order_by(Image.score.desc())
                      .limit(3).all())
        if camera_top or mobile_top:
            monthly_top[genre] = {
                'camera': camera_top,
                'mobile': mobile_top,
            }

    return render_template('contests.html',
        monthly_top        = monthly_top,
        days_left          = days_left,
        month_name         = now.strftime('%B %Y'),
        genres             = GENRE_IDS,
        genre_labels       = GENRE_LABELS,
        open_contest_active= is_open_contest_active(),
        bow_active         = is_bow_active(),
    )


# ---------------------------------------------------------------------------
# Body of Work submission
# ---------------------------------------------------------------------------
# Body of Work info page
# ---------------------------------------------------------------------------

@app.route('/bow')
def bow_info():
    return render_template('bow.html')

# ---------------------------------------------------------------------------

@app.route('/bow/submit', methods=['GET', 'POST'])
@login_required
def bow_submit():
    from models import BowSubmission

    if not getattr(current_user, 'is_subscribed', False):
        flash('An active Camera or Mobile subscription is required to submit a Body of Work.', 'error')
        return redirect(url_for('pricing'))

    current_year = datetime.utcnow().year
    existing = BowSubmission.query.filter_by(
        user_id=current_user.id,
        platform_year=current_year
    ).first()

    scored_images = (Image.query
                     .filter_by(user_id=current_user.id, status='scored')
                     .filter(Image.score != None)
                     .order_by(Image.score.desc())
                     .all())

    if request.method == 'POST':
        series_title       = request.form.get('series_title', '').strip()
        thematic_statement = request.form.get('thematic_statement', '').strip()
        selected_ids       = request.form.getlist('image_ids')

        errors = []
        if not series_title:
            errors.append('Series title is required.')
        if not thematic_statement or len(thematic_statement) < 50:
            errors.append('Thematic statement must be at least 50 characters.')
        if len(selected_ids) < 6:
            errors.append(f'Select at least 6 images. You selected {len(selected_ids)}.')
        if len(selected_ids) > 12:
            errors.append(f'Maximum 12 images allowed. You selected {len(selected_ids)}.')
        if existing:
            errors.append('You have already submitted a Body of Work for this platform year.')

        valid_ids = {str(img.id) for img in scored_images}
        invalid = [i for i in selected_ids if i not in valid_ids]
        if invalid:
            errors.append('Some selected images are invalid or not scored.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('bow_submit.html',
                scored_images=scored_images,
                existing=existing,
                selected_ids=selected_ids,
                series_title=series_title,
                thematic_statement=thematic_statement,
                min_images=6, max_images=12,
            )

        sub = BowSubmission(
            user_id            = current_user.id,
            series_title       = series_title,
            thematic_statement = thematic_statement,
            image_count        = len(selected_ids),
            platform_year      = current_year,
            status             = 'submitted',
        )
        sub.set_image_ids([int(i) for i in selected_ids])
        db.session.add(sub)
        db.session.commit()

        flash(f'✅ Your Body of Work "{series_title}" has been submitted successfully — {len(selected_ids)} images. Jury evaluation will begin after Month 11 submissions close.', 'success')
        return redirect(url_for('bow_submit'))

    return render_template('bow_submit.html',
        scored_images      = scored_images,
        existing           = existing,
        selected_ids       = [],
        series_title       = '',
        thematic_statement = '',
        min_images         = 6,
        max_images         = 12,
    )


# ---------------------------------------------------------------------------
# Monthly Contest Entry
# ---------------------------------------------------------------------------

@app.route('/contest/enter/monthly/<genre>', methods=['GET', 'POST'])
@login_required
def contest_enter_monthly(genre):
    from datetime import date as _date

    if not getattr(current_user, 'is_subscribed', False):
        flash('An active subscription is required to enter contests.', 'error')
        return redirect(url_for('pricing'))

    if getattr(current_user, 'league_suspended', False):
        flash('🚫 Your contest access is suspended due to league mismatches. Contact sreeks@gmail.com to resolve.', 'error')
        return redirect(url_for('contests'))

    genre = normalise_genre(genre)
    now   = datetime.utcnow()
    month = now.strftime('%Y-%m')
    track = getattr(current_user, 'subscription_track', 'camera') or 'camera'

    existing = ContestEntry.query.filter_by(
        user_id      = current_user.id,
        genre        = genre,
        track        = track,
        contest_month= month,
        contest_type = 'monthly',
    ).first()

    eligible = (Image.query
                .filter_by(user_id=current_user.id, status='scored', genre=genre)
                .filter(Image.score != None)
                .filter(db.or_(
                    Image.camera_track == track,
                    Image.camera_track == None,
                ))
                .order_by(Image.score.desc())
                .all())

    if request.method == 'POST':
        image_id = request.form.get('image_id', type=int)
        if not image_id:
            flash('Please select an image to enter.', 'error')
            return redirect(request.url)

        img = Image.query.get(image_id)
        if not img or img.user_id != current_user.id or img.status != 'scored':
            flash('Invalid image selection.', 'error')
            return redirect(request.url)

        if existing:
            existing.image_id   = image_id
            existing.entered_at = datetime.utcnow()
            db.session.commit()
            flash(f'Your {GENRE_LABELS.get(genre, genre)} entry has been updated to "{img.asset_name}".', 'success')
        else:
            entry = ContestEntry(
                user_id       = current_user.id,
                image_id      = image_id,
                genre         = genre,
                track         = track,
                contest_month = month,
                contest_type  = 'monthly',
            )
            db.session.add(entry)
            db.session.commit()
            flash(f'"{img.asset_name}" entered into {GENRE_LABELS.get(genre, genre)} — {track.title()} Track · {now.strftime("%B %Y")}.', 'success')

        return redirect(url_for('contests'))

    genre_label = GENRE_LABELS.get(genre, genre)
    return render_template('contest_enter.html',
        genre        = genre,
        genre_label  = genre_label,
        track        = track,
        month_name   = now.strftime('%B %Y'),
        eligible     = eligible,
        existing     = existing,
        genre_labels = GENRE_LABELS,
    )


@app.route('/contest/my-entries')
@login_required
def my_contest_entries():
    now     = datetime.utcnow()
    month   = now.strftime('%Y-%m')
    entries = (ContestEntry.query
               .filter_by(user_id=current_user.id, contest_type='monthly')
               .order_by(ContestEntry.entered_at.desc())
               .all())
    return render_template('my_entries.html',
        entries      = entries,
        current_month= month,
        genre_labels = GENRE_LABELS,
        month_name   = now.strftime('%B %Y'),
    )


@app.route('/open-contest/enter', methods=['GET', 'POST'])
@login_required
def open_contest_enter():
    if not is_open_contest_active():
        flash('The Open Competition is not currently accepting entries. Check back closer to Grand Prix.', 'info')
        return redirect(url_for('contests'))

    if not getattr(current_user, 'is_subscribed', False):
        flash('An active Camera or Mobile subscription is required to enter the Open Competition.', 'error')
        return redirect(url_for('pricing'))

    platform_year = datetime.utcnow().year

    # Step 1 — GET: show genre + image selector
    # Step 2 — POST confirm=0: show summary (genre + image + ₹50)
    # Step 3 — POST confirm=1: write to DB (dummy payment gate)

    # Fetch user's scored images for the selector
    user_images = (Image.query
                   .filter_by(user_id=current_user.id, status='scored')
                   .order_by(Image.score.desc())
                   .all())

    # Genres the user has already entered this year
    existing_entries = OpenContestEntry.query.filter_by(
        user_id=current_user.id, platform_year=platform_year
    ).all()
    entered_genres = {e.genre for e in existing_entries}

    if request.method == 'POST':
        genre    = request.form.get('genre', '').strip()
        image_id = request.form.get('image_id', '').strip()
        confirm  = request.form.get('confirm', '0')

        # Validate genre
        if genre not in GENRE_IDS:
            flash('Please select a valid genre.', 'error')
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=1, platform_year=platform_year)

        # Validate image
        try:
            image_id = int(image_id)
        except (ValueError, TypeError):
            flash('Please select an image.', 'error')
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=1, platform_year=platform_year)

        img = Image.query.filter_by(id=image_id, user_id=current_user.id, status='scored').first()
        if not img:
            flash('Invalid image selection.', 'error')
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=1, platform_year=platform_year)

        # Already entered this genre?
        if genre in entered_genres:
            flash(f'You have already entered the {GENRE_LABELS.get(genre, genre)} category this year.', 'error')
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=1, platform_year=platform_year)

        if confirm == '1':
            # Step 3 — write to DB (dummy payment confirmed)
            try:
                entry = OpenContestEntry(
                    user_id=current_user.id,
                    image_id=img.id,
                    genre=genre,
                    platform_year=platform_year,
                    amount_paise=5000,
                    payment_ref='DUMMY-' + str(int(datetime.utcnow().timestamp())),
                    status='confirmed'
                )
                db.session.add(entry)
                db.session.commit()
                flash(f'🎯 Entry confirmed! "{img.asset_name}" is entered in {GENRE_LABELS.get(genre, genre)} — Open Competition {platform_year}.', 'success')
                return redirect(url_for('contests'))
            except Exception:
                db.session.rollback()
                flash('Entry already exists for this genre, or a database error occurred.', 'error')
                return redirect(url_for('contests'))
        else:
            # Step 2 — show summary for confirmation
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=2, selected_genre=genre, selected_image=img,
                platform_year=platform_year)

    # GET — Step 1
    return render_template('open_contest_enter.html',
        user_images=user_images, genres=GENRE_IDS,
        genre_labels=GENRE_LABELS, entered_genres=entered_genres,
        step=1, platform_year=platform_year)




# ===========================================================================
# Weekly Challenge
# ===========================================================================

def _current_week_ref():
    """Returns ISO week string e.g. '2026-W17' for the current week."""
    now = datetime.utcnow()
    return f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"


def _get_active_challenge():
    """Return the currently open challenge, or the most recent one."""
    now = datetime.utcnow()
    ch = WeeklyChallenge.query.filter(
        WeeklyChallenge.opens_at <= now,
        WeeklyChallenge.closes_at >= now,
        WeeklyChallenge.is_active == True,
    ).first()
    if not ch:
        ch = WeeklyChallenge.query.filter_by(is_active=True)               .order_by(WeeklyChallenge.opens_at.desc()).first()
    return ch


@app.route('/challenge')
def weekly_challenge():
    """Public challenge page — visible to all, submit requires login."""
    challenge = _get_active_challenge()
    if not challenge:
        return render_template('challenge.html', challenge=None,
                               submissions=[], user_subs=[], slots_used=0,
                               slot_limit=0, can_submit=False)

    # Top submissions for display (subscribers only on leaderboard)
    top_subs = (WeeklySubmission.query
                .filter_by(challenge_id=challenge.id, is_subscriber=True)
                .join(Image, WeeklySubmission.image_id == Image.id)
                .filter(Image.score != None)
                .order_by(Image.score.desc())
                .limit(20).all())

    user_subs = []
    slots_used = 0
    slot_limit = 0
    can_submit = False

    if current_user.is_authenticated:
        user_subs  = WeeklySubmission.query.filter_by(
            challenge_id=challenge.id, user_id=current_user.id).all()
        slots_used = len(user_subs)
        slot_limit = 3 if getattr(current_user, 'is_subscribed', False) else 1
        can_submit = challenge.is_open and slots_used < slot_limit

    return render_template('challenge.html',
        challenge=challenge,
        top_subs=top_subs,
        user_subs=user_subs,
        slots_used=slots_used,
        slot_limit=slot_limit,
        can_submit=can_submit,
    )


@app.route('/challenge/submit', methods=['GET', 'POST'])
@login_required
def challenge_submit():
    """Submit an existing scored image to the current challenge."""
    challenge = _get_active_challenge()
    if not challenge or not challenge.is_open:
        flash('No active challenge at the moment. Check back Monday.', 'info')
        return redirect(url_for('weekly_challenge'))

    is_sub     = getattr(current_user, 'is_subscribed', False)
    slot_limit = 3 if is_sub else 1
    slots_used = WeeklySubmission.query.filter_by(
        challenge_id=challenge.id, user_id=current_user.id).count()

    if slots_used >= slot_limit:
        flash(f'You have used all {slot_limit} challenge slot{"s" if slot_limit > 1 else ""} for this week.', 'error')
        return redirect(url_for('weekly_challenge'))

    if request.method == 'POST':
        image_id = request.form.get('image_id', type=int)
        if not image_id:
            flash('Please select an image.', 'error')
            return redirect(url_for('challenge_submit'))

        image = Image.query.filter_by(id=image_id, user_id=current_user.id, status='scored').first()
        if not image:
            flash('Image not found or not yet scored.', 'error')
            return redirect(url_for('challenge_submit'))

        # Check not already submitted this image to this challenge
        exists = WeeklySubmission.query.filter_by(
            challenge_id=challenge.id, image_id=image_id).first()
        if exists:
            flash('This image has already been submitted to this challenge.', 'error')
            return redirect(url_for('challenge_submit'))

        sub = WeeklySubmission(
            challenge_id=challenge.id,
            user_id=current_user.id,
            image_id=image_id,
            is_subscriber=is_sub,
        )
        db.session.add(sub)
        db.session.commit()

        flash(f'Image submitted to the challenge! {slot_limit - slots_used - 1} slot{"s" if slot_limit - slots_used - 1 != 1 else ""} remaining this week.', 'success')
        return redirect(url_for('weekly_challenge'))

    # GET — show image picker
    # Only scored images, owned by user, not already submitted this week
    already_submitted_ids = [
        s.image_id for s in WeeklySubmission.query.filter_by(
            challenge_id=challenge.id, user_id=current_user.id).all()
    ]
    eligible_images = (Image.query
        .filter_by(user_id=current_user.id, status='scored')
        .filter(Image.score != None, Image.is_flagged == False)
        .filter(Image.id.notin_(already_submitted_ids) if already_submitted_ids else db.true())
        .order_by(Image.score.desc())
        .all())

    return render_template('challenge_submit.html',
        challenge=challenge,
        eligible_images=eligible_images,
        slots_used=slots_used,
        slot_limit=slot_limit,
        slots_remaining=slot_limit - slots_used,
    )


@app.route('/challenge/withdraw/<int:sub_id>', methods=['POST'])
@login_required
def challenge_withdraw(sub_id):
    """Withdraw a submission — only allowed while challenge is still open."""
    sub = WeeklySubmission.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    if sub.challenge.is_closed:
        flash('Challenge is closed — submissions cannot be withdrawn.', 'error')
        return redirect(url_for('weekly_challenge'))
    db.session.delete(sub)
    db.session.commit()
    flash('Submission withdrawn.', 'info')
    return redirect(url_for('weekly_challenge'))


@app.route('/challenge/results/<week_ref>')
def challenge_results(week_ref):
    """Results page for a past challenge."""
    challenge = WeeklyChallenge.query.filter_by(week_ref=week_ref).first_or_404()
    if not challenge.is_closed:
        return redirect(url_for('weekly_challenge'))

    all_subs = (WeeklySubmission.query
                .filter_by(challenge_id=challenge.id)
                .join(Image, WeeklySubmission.image_id == Image.id)
                .filter(Image.score != None)
                .order_by(Image.score.desc())
                .all())

    winners  = [s for s in all_subs if s.result_rank and s.result_rank <= 3]
    rest     = [s for s in all_subs if not s.result_rank or s.result_rank > 3]

    return render_template('challenge_results.html',
        challenge=challenge,
        winners=winners,
        rest=rest,
        total=len(all_subs),
    )


# ---------------------------------------------------------------------------
# Admin — Weekly Challenge management
# ---------------------------------------------------------------------------

@app.route('/admin/weekly-challenge', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_weekly_challenge():
    """
    Admin page to create and manage weekly challenges.
    GET  — list all challenges + form to create new one.
    POST — create a new challenge week.
    """
    if request.method == 'POST':
        action = request.form.get('action', 'create')

        if action == 'create':
            week_ref     = request.form.get('week_ref', '').strip()
            prompt_title = request.form.get('prompt_title', '').strip()
            prompt_body  = request.form.get('prompt_body', '').strip()
            opens_str    = request.form.get('opens_at', '').strip()
            closes_str   = request.form.get('closes_at', '').strip()
            sponsor_name = request.form.get('sponsor_name', '').strip() or None
            sponsor_prize= request.form.get('sponsor_prize', '').strip() or None

            if not all([week_ref, prompt_title, opens_str, closes_str]):
                flash('Week ref, prompt title, opens and closes dates are required.', 'error')
                return redirect(url_for('admin_weekly_challenge'))

            if WeeklyChallenge.query.filter_by(week_ref=week_ref).first():
                flash(f'A challenge for {week_ref} already exists.', 'error')
                return redirect(url_for('admin_weekly_challenge'))

            try:
                opens_at  = datetime.strptime(opens_str,  '%Y-%m-%dT%H:%M')
                closes_at = datetime.strptime(closes_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid date format.', 'error')
                return redirect(url_for('admin_weekly_challenge'))

            ch = WeeklyChallenge(
                week_ref=week_ref,
                prompt_title=prompt_title,
                prompt_body=prompt_body or None,
                opens_at=opens_at,
                closes_at=closes_at,
                results_at=closes_at + timedelta(days=1),
                sponsor_name=sponsor_name,
                sponsor_prize=sponsor_prize,
                created_by=current_user.id,
            )
            db.session.add(ch)
            db.session.commit()

            # Send email notification to all users
            notify = request.form.get('notify_users') == '1'
            if notify:
                flash(f'Challenge "{prompt_title}" ({week_ref}) created. Sending notifications...', 'success')
            else:
                flash(f'Challenge "{prompt_title}" ({week_ref}) created.', 'success')

            if notify:
                # Fire email in background thread — pass ID only, re-query inside thread
                import threading
                def _notify(challenge_id):
                    with app.app_context():
                        try:
                            ch_fresh = WeeklyChallenge.query.get(challenge_id)
                            if ch_fresh:
                                sent = send_challenge_notification(ch_fresh)
                                app.logger.info(f'[challenge] Notifications sent to {sent} users')
                        except Exception as _e:
                            app.logger.error(f'[challenge] Notification failed: {_e}')
                t = threading.Thread(target=_notify, args=(ch.id,), daemon=True)
                t.start()

            return redirect(url_for('admin_weekly_challenge'))

        elif action == 'publish_results':
            challenge_id = request.form.get('challenge_id', type=int)
            ch = WeeklyChallenge.query.get_or_404(challenge_id)
            # Read winner rankings from form — rank_<sub_id> = 1|2|3
            for key, value in request.form.items():
                if key.startswith('rank_'):
                    sub_id = int(key.split('_')[1])
                    sub = WeeklySubmission.query.get(sub_id)
                    if sub and sub.challenge_id == challenge_id:
                        try:
                            sub.result_rank = int(value) if value else None
                        except ValueError:
                            sub.result_rank = None
                if key.startswith('note_'):
                    sub_id = int(key.split('_')[1])
                    sub = WeeklySubmission.query.get(sub_id)
                    if sub and sub.challenge_id == challenge_id:
                        sub.result_note = value.strip() or None
            db.session.commit()
            flash(f'Results published for {ch.week_ref}.', 'success')
            return redirect(url_for('admin_weekly_challenge'))

        elif action == 'deactivate':
            challenge_id = request.form.get('challenge_id', type=int)
            ch = WeeklyChallenge.query.get_or_404(challenge_id)
            ch.is_active = False
            db.session.commit()
            flash(f'Challenge {ch.week_ref} deactivated.', 'info')
            return redirect(url_for('admin_weekly_challenge'))

        elif action == 'resend_notification':
            challenge_id = request.form.get('challenge_id', type=int)
            ch = WeeklyChallenge.query.get_or_404(challenge_id)
            import threading
            def _resend(challenge_id):
                with app.app_context():
                    try:
                        ch_fresh = WeeklyChallenge.query.get(challenge_id)
                        if ch_fresh:
                            sent = send_challenge_notification(ch_fresh)
                            app.logger.info(f'[challenge] Resend complete — {sent} users notified')
                    except Exception as _e:
                        app.logger.error(f'[challenge] Resend failed: {_e}')
            t = threading.Thread(target=_resend, args=(ch.id,), daemon=True)
            t.start()
            flash(f'Notification sending in background for {ch.week_ref}. Check Railway logs for delivery count.', 'success')
            return redirect(url_for('admin_weekly_challenge'))

        elif action == 'edit':
            challenge_id  = request.form.get('challenge_id', type=int)
            ch = WeeklyChallenge.query.get_or_404(challenge_id)
            ch.prompt_title  = request.form.get('prompt_title', ch.prompt_title).strip()
            ch.prompt_body   = request.form.get('prompt_body', '').strip() or None
            ch.sponsor_name  = request.form.get('sponsor_name', '').strip() or None
            ch.sponsor_prize = request.form.get('sponsor_prize', '').strip() or None
            opens_str  = request.form.get('opens_at', '').strip()
            closes_str = request.form.get('closes_at', '').strip()
            try:
                if opens_str:
                    ch.opens_at  = datetime.strptime(opens_str,  '%Y-%m-%dT%H:%M')
                if closes_str:
                    ch.closes_at = datetime.strptime(closes_str, '%Y-%m-%dT%H:%M')
                    ch.results_at = ch.closes_at + timedelta(days=1)
            except ValueError:
                flash('Invalid date format.', 'error')
                return redirect(url_for('admin_weekly_challenge'))
            db.session.commit()
            flash(f'Challenge {ch.week_ref} updated.', 'success')
            return redirect(url_for('admin_weekly_challenge'))

        elif action == 'delete':
            challenge_id = request.form.get('challenge_id', type=int)
            ch = WeeklyChallenge.query.get_or_404(challenge_id)
            if ch.submission_count > 0:
                flash(f'Cannot delete {ch.week_ref} — it has {ch.submission_count} submission(s). Deactivate it instead.', 'error')
                return redirect(url_for('admin_weekly_challenge'))
            db.session.delete(ch)
            db.session.commit()
            flash(f'Challenge {ch.week_ref} deleted.', 'info')
            return redirect(url_for('admin_weekly_challenge'))

    # GET
    challenges = WeeklyChallenge.query.order_by(WeeklyChallenge.opens_at.desc()).all()
    # Default week_ref for new challenge form
    now = datetime.utcnow()
    default_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    # Default opens Monday 00:00, closes Sunday 23:59
    today        = now.date()
    monday       = today - timedelta(days=today.weekday())
    sunday       = monday + timedelta(days=6)
    default_open = datetime(monday.year, monday.month, monday.day, 0, 0)
    default_close= datetime(sunday.year, sunday.month, sunday.day, 23, 59)

    return render_template('admin_weekly_challenge.html',
        challenges=challenges,
        default_week=default_week,
        default_open=default_open.strftime('%Y-%m-%dT%H:%M'),
        default_close=default_close.strftime('%Y-%m-%dT%H:%M'),
    )


# ---------------------------------------------------------------------------
# Razorpay subscription
# ---------------------------------------------------------------------------

@app.route('/subscribe/<track>', methods=['GET', 'POST'])
@login_required
def subscribe(track):
    if track not in ('camera', 'mobile'):
        return redirect(url_for('pricing'))

    plan = request.args.get('plan', 'monthly')
    if plan not in ('monthly', 'annual'):
        plan = 'monthly'

    razorpay_key    = os.getenv('RAZORPAY_KEY_ID', '')
    razorpay_secret = os.getenv('RAZORPAY_KEY_SECRET', '')

    plan_ids = {
        'mobile': {
            'monthly': os.getenv('RAZORPAY_PLAN_MOBILE_MONTHLY', ''),
            'annual':  os.getenv('RAZORPAY_PLAN_MOBILE_ANNUAL', ''),
        },
        'camera': {
            'monthly': os.getenv('RAZORPAY_PLAN_CAMERA_MONTHLY', ''),
            'annual':  os.getenv('RAZORPAY_PLAN_CAMERA_ANNUAL', ''),
        },
    }
    display_prices = {
        'mobile': {'monthly': 299,  'annual': 2499},
        'camera': {'monthly': 599,  'annual': 4999},
    }

    plan_id = plan_ids[track][plan]
    amount  = display_prices[track][plan]

    if request.method == 'POST':
        payment_id      = request.form.get('razorpay_payment_id', '')
        subscription_id = request.form.get('razorpay_subscription_id', '')
        signature       = request.form.get('razorpay_signature', '')

        if not razorpay_key:
            flash('Payment system not configured. Contact support.', 'error')
            return redirect(url_for('pricing'))

        try:
            import hmac as _hmac, hashlib as _hashlib
            # Subscription signature: HMAC-SHA256 of payment_id|subscription_id
            expected_sig = _hmac.new(
                razorpay_secret.encode('utf-8'),
                f'{payment_id}|{subscription_id}'.encode('utf-8'),
                _hashlib.sha256
            ).hexdigest()
            if not _hmac.compare_digest(expected_sig, signature):
                raise Exception('Payment signature verification failed')

            current_user.subscription_track = track
            current_user.subscription_plan  = plan
            current_user.subscribed_at       = datetime.utcnow()
            current_user.is_subscribed       = True
            current_user.razorpay_sub_id     = subscription_id
            db.session.commit()

            flash(f'🎉 Welcome to the {track.title()} Track! Your subscription is active.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            app.logger.error(f'[subscribe] verification failed: {e}')
            flash('Payment verification failed. Please contact support if you were charged.', 'error')
            return redirect(url_for('subscribe', track=track, plan=plan))

    # GET — create Razorpay subscription
    subscription = None
    if razorpay_key and plan_id:
        try:
            import razorpay
            client = razorpay.Client(auth=(razorpay_key, razorpay_secret))
            subscription = client.subscription.create({
                'plan_id':         plan_id,
                'total_count':     10 if plan == 'annual' else 120,
                'quantity':        1,
                'customer_notify': 1,
            })
        except Exception as e:
            app.logger.error(f'[subscribe] subscription create failed: {e}')
            flash('Could not initialise payment. Please try again.', 'error')

    return render_template('subscribe.html',
        track=track, plan=plan, amount=amount,
        subscription=subscription,
        razorpay_key=razorpay_key,
    )


@app.route('/razorpay/webhook', methods=['POST'])
def razorpay_webhook():
    import hmac as _hmac, hashlib as _hashlib, json as _json
    webhook_secret = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
    payload        = request.get_data()
    sig            = request.headers.get('X-Razorpay-Signature', '')

    if webhook_secret:
        expected = _hmac.new(
            webhook_secret.encode(), payload, _hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(expected, sig):
            app.logger.warning('[webhook] invalid signature')
            return jsonify({'status': 'invalid signature'}), 400

    try:
        event      = _json.loads(payload)
        event_type = event.get('event', '')
        app.logger.info(f'[webhook] {event_type}')
        sub_data   = (event.get('payload', {}).get('subscription', {}).get('entity', {}))
        sub_id     = sub_data.get('id', '')

        if event_type == 'subscription.activated':
            user = User.query.filter_by(razorpay_sub_id=sub_id).first()
            if user:
                user.is_subscribed = True
                db.session.commit()

        elif event_type in ('subscription.cancelled', 'subscription.completed', 'subscription.halted'):
            user = User.query.filter_by(razorpay_sub_id=sub_id).first()
            if user:
                user.is_subscribed      = False
                user.subscription_track = None
                user.subscription_plan  = None
                db.session.commit()

    except Exception as e:
        app.logger.error(f'[webhook] error: {e}')

    return jsonify({'status': 'ok'}), 200


@app.route('/subscription/cancel', methods=['GET', 'POST'])
@login_required
def cancel_subscription():
    """
    GET  — confirmation page (user must confirm before cancelling)
    POST — actually cancel: call Razorpay API, clear DB fields, redirect to dashboard
    RBI / Razorpay compliance: user must be able to self-cancel without contacting support.
    """
    if request.method == 'GET':
        return render_template('cancel_subscription.html')

    # POST — confirmed cancellation
    razorpay_key    = os.getenv('RAZORPAY_KEY_ID', '')
    razorpay_secret = os.getenv('RAZORPAY_KEY_SECRET', '')
    sub_id          = current_user.razorpay_sub_id

    # Cancel on Razorpay's end if we have a live subscription ID
    if sub_id and razorpay_key:
        try:
            import razorpay as _rz
            client = _rz.Client(auth=(razorpay_key, razorpay_secret))
            # cancel_at_cycle_end=1 means access continues until end of paid period
            client.subscription.cancel(sub_id, {'cancel_at_cycle_end': 1})
            app.logger.info(f'[cancel] Razorpay subscription {sub_id} cancelled for user {current_user.id}')
        except Exception as e:
            app.logger.error(f'[cancel] Razorpay cancel failed for {sub_id}: {e}')
            # Still cancel locally — don't leave user stuck
            flash('Your subscription has been cancelled. If you continue to be charged, contact sreeks@gmail.com.', 'warning')

    # Clear subscription fields in DB
    current_user.is_subscribed      = False
    current_user.subscription_track = None
    current_user.subscription_plan  = None
    current_user.razorpay_sub_id    = None
    db.session.commit()

    flash('Your subscription has been cancelled. You will retain access until the end of your current billing period.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    results = []
    if request.method == 'POST':
        files = request.files.getlist('images')
        if len(files) > 10:
            flash('Maximum 10 images per bulk upload. Please split into batches of 10.', 'error')
            return redirect(url_for('bulk_upload'))
        raw_genre = request.form.get('genre', '').strip()
        if not raw_genre:
            flash('Please select a genre before uploading.', 'error')
            return redirect(url_for('bulk_upload'))
        genre = normalise_genre(raw_genre)

        if current_user.role != 'admin' and not getattr(current_user, 'is_subscribed', False):
            from datetime import date as _date
            today      = _date.today()
            reg_date   = current_user.created_at.date() if current_user.created_at else today
            in_month1  = (today.year == reg_date.year and today.month == reg_date.month)
            free_limit = FREE_IMAGE_LIMIT_MONTH1 if in_month1 else FREE_IMAGE_LIMIT_DEFAULT
            month_start = datetime(today.year, today.month, 1)
            month_count = Image.query.filter(
                Image.user_id == current_user.id,
                Image.created_at >= month_start,
            ).count()
            if month_count >= free_limit:
                flash(
                    f'You have used all {free_limit} free scored images for this month. '
                    'Upgrade to Camera or Mobile track for unlimited uploads.',
                    'error'
                )
                return redirect(url_for('pricing'))
        photographer = (request.form.get('photographer_name') or '').strip()
        if not photographer:
            photographer = current_user.full_name or current_user.username
        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        for file in files:
            if not file or not file.filename:
                continue
            if not allowed_file(file.filename):
                results.append({'filename': file.filename, 'score': None, 'tier': None, 'status': 'skipped'})
                continue
            result_row = {'filename': file.filename, 'score': None, 'tier': None, 'status': 'failed'}
            try:
                uid      = str(uuid.uuid4())
                filename = secure_filename(file.filename)
                raw_path = os.path.join(app.config['UPLOAD_FOLDER'], 'raw', f"{uid}_{filename}")
                file.save(raw_path)
                thumb_path, w, h, fmt, phash = ingest_image(raw_path, app.config['UPLOAD_FOLDER'])
                if os.path.exists(raw_path): os.remove(raw_path)

                from engine.processor import hash_similarity_pct
                existing_imgs = Image.query.filter(Image.phash.isnot(None)).all()
                duplicate_found = False
                for ex in existing_imgs:
                    sim = hash_similarity_pct(phash, ex.phash)
                    if sim >= 90.0:
                        if ex.user_id == current_user.id:
                            result_row['status'] = f'duplicate: already uploaded as "{ex.asset_name or ex.original_filename}"'
                        else:
                            result_row['status'] = 'rejected: image already submitted by another member'
                        duplicate_found = True
                        if os.path.exists(thumb_path): os.remove(thumb_path)
                        break
                if duplicate_found:
                    results.append(result_row)
                    continue

                thumb_url = _r2_upload_thumb(thumb_path, uid)

                from models import Image as ImageModel
                img = ImageModel(
                    user_id=current_user.id, original_filename=filename,
                    stored_filename=os.path.basename(thumb_path),
                    thumb_path=thumb_path, thumb_url=thumb_url,
                    file_size_kb=int(os.path.getsize(thumb_path)/1024),
                    width=w, height=h, format=fmt,
                    asset_name=auto_title(filename, genre),
                    phash=phash, genre=genre, photographer_name=photographer,
                    camera_track=getattr(current_user, 'subscription_track', None),
                    status='pending',
                    is_public=(request.form.get('is_public', '1') == '1'),
                )
                db.session.add(img)
                db.session.flush()
                if api_key:
                    from engine.auto_score import auto_score, build_audit_data
                    from engine.compositor import build_card1 as _build_card
                    scored = auto_score(image_path=img.thumb_path, genre=genre,
                                        title=img.asset_name, photographer=photographer)
                    img.dod_score=float(scored.get('dod',0))
                    img.disruption_score=float(scored.get('disruption',0))
                    img.dm_score=float(scored.get('dm',0))
                    img.wonder_score=float(scored.get('wonder',0))
                    img.aq_score=float(scored.get('aq',0))
                    img.score=float(scored.get('score',0))
                    img.tier=get_tier(float(scored.get('score',0)))
                    img.archetype=scored.get('archetype','')
                    img.soul_bonus=scored.get('soul_bonus',False)
                    img.status='scored'; img.scored_at=datetime.utcnow()
                    audit = build_audit_data(scored, img)
                    img.set_audit(audit)
                    card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                                  f"{secure_filename(photographer.replace(' ',''))}_{genre}_{img.score}.jpg")
                    card_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
                    _build_card(img.thumb_path, audit, card_path)
                    img.card_path = card_path
                    card_url = _r2_upload_card(card_path, uid + '_card')
                    if card_url: img.card_url = card_url
                    result_row['score']=img.score; result_row['tier']=img.tier; result_row['status']='scored'
                else:
                    img.status='pending'; result_row['status']='uploaded'
                db.session.commit()
            except Exception as e:
                try:
                    db.session.rollback()
                except:
                    pass
                import traceback
                app.logger.error(f'Bulk upload error for {file.filename}: {traceback.format_exc()}')
                result_row['status'] = f'error: {str(e)[:120]}'
            results.append(result_row)
    try:
        db.session.commit()
    except Exception as ce:
        app.logger.error(f'Final bulk commit error: {ce}')
        try:
            db.session.rollback()
        except:
            pass

    if request.method == 'POST' and results:
        scored_count  = sum(1 for r in results if r['status'] == 'scored')
        saved_count   = sum(1 for r in results if 'saved' in r['status'] or r['status'] == 'uploaded')
        error_count   = sum(1 for r in results if 'error' in r['status'])
        msg_parts = []
        if scored_count:  msg_parts.append(f'{scored_count} scored')
        if saved_count:   msg_parts.append(f'{saved_count} saved (pending)')
        if error_count:   msg_parts.append(f'{error_count} failed')
        flash(f"Bulk upload complete: {', '.join(msg_parts)}.", 'success')
        return redirect(url_for('dashboard'))
    return render_template('bulk_upload.html', genres=GENRE_IDS, results=results)




# ---------------------------------------------------------------------------
# Peer Rating Routes
# ---------------------------------------------------------------------------

@app.route('/rate')
@login_required
def rate():
    """Blind peer rating queue page."""
    from datetime import date as _date
    from sqlalchemy import extract

    user = current_user
    user.reset_credits_if_needed()
    db.session.commit()

    is_subscriber = getattr(user, 'is_subscribed', False)
    credits       = user.rating_credits or 0
    lifetime      = user.lifetime_ratings_given or 0

    now = datetime.utcnow()
    month_given = PeerRating.query.filter(
        PeerRating.rater_id == user.id,
        extract('month', PeerRating.rated_at) == now.month,
        extract('year',  PeerRating.rated_at) == now.year,
    ).count()

    assignment      = None
    image           = None
    queue_remaining = 0

    if is_subscriber:
        assignment = get_or_assign_next_image(user.id)
        if assignment:
            if assignment.status == 'assigned':
                assignment.status     = 'started'
                assignment.started_at = datetime.utcnow()
                db.session.commit()
            image = assignment.image

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

    current_user.reset_credits_if_needed()

    # Server-side time check — must be ≥13s (2s tolerance for network)
    client_start = request.form.get('client_start_ts', type=int)
    time_spent   = request.form.get('time_spent', type=int) or 0
    if client_start:
        server_elapsed = int((datetime.utcnow().timestamp() * 1000 - client_start) / 1000)
        if server_elapsed < 13:
            flash('Please spend more time viewing the image before rating.', 'warning')
            return redirect(url_for('rate'))

    try:
        dod        = float(request.form.get('dod', 5))
        disruption = float(request.form.get('disruption', 5))
        dm         = float(request.form.get('dm', 5))
        wonder     = float(request.form.get('wonder', 5))
        aq         = float(request.form.get('aq', 5))
    except (ValueError, TypeError):
        flash('Invalid scores submitted.', 'error')
        return redirect(url_for('rate'))

    def clamp(v):
        return max(1.0, min(10.0, round(v * 2) / 2))
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
        if (current_user.lifetime_ratings_given or 0) % 5 == 0:
            flash('🎉 You\'ve unlocked a peer pool entry! Go to your dashboard to choose an image to submit for peer rating.', 'info')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[submit_rating] {e}')
        flash('Submission failed. Please try again.', 'error')

    return redirect(url_for('rate'))


@app.route('/rate/skip', methods=['POST'])
@login_required
def skip_rating():
    """Skip a rating assignment — expires it, no credit cost."""
    assignment_id = request.form.get('assignment_id', type=int)
    if assignment_id:
        a = RatingAssignment.query.get(assignment_id)
        if a and a.rater_id == current_user.id and a.status != 'submitted':
            a.status = 'expired'
            db.session.commit()
    return redirect(url_for('rate'))


# ---------------------------------------------------------------------------
# Admin Rating Audit Routes
# ---------------------------------------------------------------------------

@app.route('/admin/ratings')
@login_required
@admin_required
def admin_ratings():
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

    per_page         = 50
    total            = q.count()
    pages            = max(1, (total + per_page - 1) // per_page)
    ratings          = q.offset((page - 1) * per_page).limit(per_page).all()

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
        ratings          = ratings,
        page             = page,
        pages            = pages,
        total_ratings    = total_ratings,
        total_raters     = total_raters,
        images_with_peer = images_with_peer,
        biased_raters    = biased_raters,
        biased_users     = biased_users,
        all_raters       = all_raters,
        all_genres       = GENRE_IDS,
        rater_filter     = rater_filter,
        genre_filter     = genre_filter,
        outliers_only    = outliers_only,
    )


@app.route('/admin/ratings/export-csv')
@login_required
@admin_required
def admin_export_ratings_csv():
    """Export full peer rating audit as CSV."""
    import io, csv
    from flask import Response

    ratings = PeerRating.query.order_by(PeerRating.rated_at.desc()).all()
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow([
        'rated_at', 'rater_username', 'rater_name',
        'image_id', 'image_title', 'photographer', 'genre',
        'time_spent_seconds',
        'peer_dod', 'peer_disruption', 'peer_dm', 'peer_wonder', 'peer_aq',
        'peer_ll_score', 'ddi_score', 'delta_from_ddi', 'rater_bias_flag',
    ])
    for r in ratings:
        img   = r.image
        rater = r.rater
        writer.writerow([
            r.rated_at.strftime('%Y-%m-%d %H:%M:%S') if r.rated_at else '',
            rater.username  if rater else '',
            rater.full_name if rater else '',
            r.image_id,
            img.asset_name        if img else '',
            img.photographer_name if img else '',
            r.genre,
            r.time_spent_seconds or '',
            r.dod, r.disruption, r.dm, r.wonder, r.aq,
            r.peer_ll_score,
            img.score if img else '',
            r.delta_from_ddi if r.delta_from_ddi is not None else '',
            '1' if (rater and rater.rating_bias_flag) else '0',
        ])

    filename = f'lens_league_peer_ratings_{date.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )




# ---------------------------------------------------------------------------
# Admin — Subscription view
# ---------------------------------------------------------------------------

@app.route('/admin/subscriptions')
@login_required
@admin_required
def admin_subscriptions():
    """Subscription status overview for all users."""
    subscribers = User.query.filter_by(is_subscribed=True).order_by(User.subscribed_at.desc()).all()
    free_users  = User.query.filter(
        User.role != 'admin',
        db.or_(User.is_subscribed == False, User.is_subscribed == None)
    ).order_by(User.created_at.desc()).all()
    total_mrr = sum(
        (299 if u.subscription_track == 'mobile' else 599)
        for u in subscribers if u.subscription_plan == 'monthly'
    )
    total_arr = sum(
        (2499 if u.subscription_track == 'mobile' else 4999)
        for u in subscribers if u.subscription_plan == 'annual'
    )
    return render_template('admin_subscriptions.html',
        subscribers=subscribers, free_users=free_users,
        total_mrr=total_mrr, total_arr=total_arr,
    )


# ---------------------------------------------------------------------------
# Admin CSV Exports
# ---------------------------------------------------------------------------

@app.route('/admin/export/users')
@login_required
@admin_required
def admin_export_users():
    """Export full user base as CSV."""
    import io, csv
    from flask import Response
    from datetime import date as _date

    users  = User.query.filter(User.role != 'admin').order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'user_id', 'username', 'full_name', 'email',
        'joined_date', 'is_subscribed', 'subscription_track', 'subscription_plan',
        'subscribed_at', 'razorpay_sub_id',
        'total_images', 'scored_images',
        'rating_credits', 'lifetime_ratings_given', 'peer_pool_unlocks',
        'rating_bias_flag', 'is_active',
    ])
    for u in users:
        total_imgs  = Image.query.filter_by(user_id=u.id).count()
        scored_imgs = Image.query.filter_by(user_id=u.id, status='scored').count()
        writer.writerow([
            u.id, u.username, u.full_name or '', u.email,
            u.created_at.strftime('%Y-%m-%d') if u.created_at else '',
            '1' if u.is_subscribed else '0',
            u.subscription_track or '',
            u.subscription_plan  or '',
            u.subscribed_at.strftime('%Y-%m-%d %H:%M:%S') if u.subscribed_at else '',
            u.razorpay_sub_id or '',
            total_imgs, scored_imgs,
            u.rating_credits or 0,
            u.lifetime_ratings_given or 0,
            u.peer_pool_unlocks or 0,
            '1' if u.rating_bias_flag else '0',
            '1' if u.is_active else '0',
        ])
    filename = f'lens_league_users_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.route('/admin/export/subscriptions')
@login_required
@admin_required
def admin_export_subscriptions():
    """Export subscribers only as CSV."""
    import io, csv
    from flask import Response

    subs   = User.query.filter_by(is_subscribed=True).order_by(User.subscribed_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'user_id', 'username', 'full_name', 'email',
        'subscription_track', 'subscription_plan',
        'monthly_value_inr', 'subscribed_at', 'razorpay_sub_id',
    ])
    price_map = {
        ('mobile', 'monthly'): 299,  ('mobile', 'annual'): 2499,
        ('camera', 'monthly'): 599,  ('camera', 'annual'): 4999,
    }
    for u in subs:
        price = price_map.get((u.subscription_track, u.subscription_plan), 0)
        writer.writerow([
            u.id, u.username, u.full_name or '', u.email,
            u.subscription_track or '', u.subscription_plan or '',
            price,
            u.subscribed_at.strftime('%Y-%m-%d %H:%M:%S') if u.subscribed_at else '',
            u.razorpay_sub_id or '',
        ])
    filename = f'lens_league_subscriptions_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.route('/admin/export/images')
@login_required
@admin_required
def admin_export_images():
    """Export all scored images with EXIF, scores, and lens data as CSV."""
    import io, csv
    from flask import Response

    images = Image.query.filter_by(status='scored').order_by(Image.scored_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'image_id', 'asset_name', 'genre', 'track',
        'photographer', 'user_id',
        'score', 'tier', 'archetype',
        'dod', 'disruption', 'dm', 'wonder', 'aq',
        'soul_bonus', 'blended_score', 'peer_rating_count',
        'exif_camera', 'exif_date_taken', 'exif_settings',
        'exif_status', 'needs_review', 'is_flagged',
        'scored_at', 'created_at',
    ])
    for img in images:
        writer.writerow([
            img.id, img.asset_name or '', img.genre or '', img.camera_track or '',
            img.photographer_name or '', img.user_id,
            img.score or '', img.tier or '', img.archetype or '',
            img.dod_score or '', img.disruption_score or '', img.dm_score or '',
            img.wonder_score or '', img.aq_score or '',
            '1' if img.soul_bonus else '0',
            img.blended_score or '', img.peer_rating_count or 0,
            img.exif_camera or '', img.exif_date_taken or '', img.exif_settings or '',
            img.exif_status or '', '1' if img.needs_review else '0',
            '1' if img.is_flagged else '0',
            img.scored_at.strftime('%Y-%m-%d %H:%M:%S') if img.scored_at else '',
            img.created_at.strftime('%Y-%m-%d %H:%M:%S') if img.created_at else '',
        ])
    filename = f'lens_league_images_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.route('/admin/export/camera-rankings')
@login_required
@admin_required
def admin_export_camera_rankings():
    """Export camera and phone model rankings by avg score as CSV."""
    import io, csv
    from flask import Response
    from collections import defaultdict

    images = Image.query.filter(
        Image.status == 'scored',
        Image.score != None,
        Image.exif_camera != None,
        Image.exif_camera != '',
    ).all()

    camera_data  = defaultdict(list)
    mobile_data  = defaultdict(list)

    for img in images:
        cam = (img.exif_camera or '').strip()
        if not cam:
            continue
        if img.camera_track == 'camera':
            camera_data[cam].append(img.score)
        elif img.camera_track == 'mobile':
            mobile_data[cam].append(img.score)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['track', 'camera_model', 'image_count', 'avg_score', 'min_score', 'max_score'])

    for model, scores in sorted(camera_data.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if len(scores) >= 2:
            writer.writerow([
                'camera', model, len(scores),
                round(sum(scores)/len(scores), 2),
                round(min(scores), 2), round(max(scores), 2),
            ])
    for model, scores in sorted(mobile_data.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if len(scores) >= 2:
            writer.writerow([
                'mobile', model, len(scores),
                round(sum(scores)/len(scores), 2),
                round(min(scores), 2), round(max(scores), 2),
            ])

    filename = f'lens_league_camera_rankings_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.route('/admin/export/lens-rankings')
@login_required
@admin_required
def admin_export_lens_rankings():
    """Export lens model rankings by avg score as CSV (camera track only)."""
    import io, csv
    from flask import Response
    from collections import defaultdict

    # Extract lens from exif_settings — format: focal · aperture · iso · shutter
    # Lens model lives in exif_camera field for many cameras; use exif_settings for focal context
    images = Image.query.filter(
        Image.status == 'scored',
        Image.score != None,
        Image.camera_track == 'camera',
        Image.exif_camera != None,
        Image.exif_camera != '',
    ).all()

    lens_data = defaultdict(list)
    for img in images:
        # Use exif_camera as the lens/camera identifier for now
        # When dedicated lens EXIF field is added this can be updated
        cam = (img.exif_camera or '').strip()
        if cam:
            lens_data[cam].append(img.score)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['camera_lens_model', 'image_count', 'avg_score', 'min_score', 'max_score'])
    for model, scores in sorted(lens_data.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if len(scores) >= 2:
            writer.writerow([
                model, len(scores),
                round(sum(scores)/len(scores), 2),
                round(min(scores), 2), round(max(scores), 2),
            ])

    filename = f'lens_league_lens_rankings_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.route('/admin/export/peer-ratings')
@login_required
@admin_required
def admin_export_peer_ratings_full():
    """Export full peer-to-peer rating audit with bias data as CSV."""
    import io, csv
    from flask import Response

    ratings = (PeerRating.query
               .order_by(PeerRating.rated_at.desc()).all())
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow([
        'rated_at', 'rater_id', 'rater_username', 'rater_name',
        'rater_bias_flag', 'rater_lifetime_given',
        'image_id', 'image_title', 'photographer', 'genre', 'track',
        'ddi_score', 'peer_dod', 'peer_disruption', 'peer_dm', 'peer_wonder', 'peer_aq',
        'peer_ll_score', 'delta_from_ddi', 'time_spent_seconds',
        'image_peer_rating_count', 'image_blended_score',
    ])
    for r in ratings:
        img   = r.image
        rater = r.rater
        writer.writerow([
            r.rated_at.strftime('%Y-%m-%d %H:%M:%S') if r.rated_at else '',
            rater.id            if rater else '',
            rater.username      if rater else '',
            rater.full_name     if rater else '',
            '1' if (rater and rater.rating_bias_flag) else '0',
            rater.lifetime_ratings_given if rater else '',
            r.image_id,
            img.asset_name        if img else '',
            img.photographer_name if img else '',
            r.genre,
            img.camera_track      if img else '',
            img.score             if img else '',
            r.dod, r.disruption, r.dm, r.wonder, r.aq,
            r.peer_ll_score,
            r.delta_from_ddi if r.delta_from_ddi is not None else '',
            r.time_spent_seconds or '',
            img.peer_rating_count if img else '',
            img.blended_score     if img else '',
        ])

    filename = f'lens_league_peer_ratings_full_{date.today().strftime("%Y%m%d")}.csv'
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})

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



# ---------------------------------------------------------------------------
# Peer Pool Entry — user chooses which image to submit for peer rating
# ---------------------------------------------------------------------------

@app.route('/rate/enter-pool', methods=['POST'])
@login_required
def enter_peer_pool():
    """Submit a chosen image into the peer rating pool."""
    image_id = request.form.get('image_id', type=int)
    if not image_id:
        flash('Please select an image.', 'error')
        return redirect(url_for('dashboard'))

    # Verify the user has pending unlocks
    lifetime_given  = current_user.lifetime_ratings_given or 0
    unlocks_earned  = lifetime_given // 5
    unlocks_used    = PeerPoolEntry.query.filter_by(user_id=current_user.id).count()
    unlocks_pending = unlocks_earned - unlocks_used

    if unlocks_pending <= 0:
        flash('No pool entry unlocks available. Rate more images to earn one.', 'warning')
        return redirect(url_for('dashboard'))

    # Verify the image belongs to this user and is eligible
    img = Image.query.filter_by(id=image_id, user_id=current_user.id, status='scored').first()
    if not img:
        flash('Invalid image selection.', 'error')
        return redirect(url_for('dashboard'))

    if img.is_in_peer_pool:
        flash('This image is already in the peer rating pool.', 'info')
        return redirect(url_for('dashboard'))

    # Create pool entry
    entry = PeerPoolEntry(
        user_id       = current_user.id,
        image_id      = image_id,
        unlock_number = unlocks_used + 1,
    )
    db.session.add(entry)
    img.is_in_peer_pool      = True
    img.pool_entry_chosen_at = datetime.utcnow()
    current_user.peer_pool_unlocks = unlocks_used + 1
    db.session.commit()

    flash(f'✅ "{img.asset_name}" is now in the peer rating pool. Other photographers will start rating it soon.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/reset-rating-credits', methods=['POST'])
@login_required
@admin_required
def admin_reset_rating_credits():
    """Reset all users' rating credits to 0 (v27 migration)."""
    updated = User.query.filter(User.role != 'admin').all()
    for u in updated:
        u.rating_credits         = 0
        u.lifetime_ratings_given = 0
        u.peer_pool_unlocks      = 0
    # Also clear any existing pool entries and reset image flags
    try:
        db.session.execute(db.text('DELETE FROM peer_pool_entries'))
        db.session.execute(db.text('UPDATE images SET is_in_peer_pool = FALSE, pool_entry_chosen_at = NULL'))
        db.session.execute(db.text('DELETE FROM rating_assignments'))
        db.session.execute(db.text('DELETE FROM peer_ratings'))
        db.session.execute(db.text('UPDATE images SET peer_avg_score=NULL, peer_rating_count=0, blended_score=NULL, peer_avg_dod=NULL, peer_avg_disruption=NULL, peer_avg_dm=NULL, peer_avg_wonder=NULL, peer_avg_aq=NULL'))
    except Exception as e:
        app.logger.error(f'[reset_credits] {e}')
    db.session.commit()
    flash(f'Reset rating credits and peer data for {len(updated)} users.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/share/<int:image_id>')
def share_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.status != 'scored':
        abort(404)
    audit = img.get_audit()
    show_score = (
        current_user.is_authenticated and
        (current_user.id == img.user_id or current_user.role == 'admin')
    )
    already_reported = False
    if current_user.is_authenticated and current_user.id != img.user_id:
        already_reported = ImageReport.query.filter_by(
            image_id=image_id, reporter_id=current_user.id
        ).first() is not None
    return render_template('share.html', image=img, audit=audit, show_score=show_score,
                           already_reported=already_reported)


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(413)
def file_too_large(e):
    msg = (
        '⚠️ File too large. Maximum file size is 20 MB. '
        'On iPhone: share your photo and choose "Medium" size. '
        'On Samsung/Android: use Gallery → resize before sharing.'
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': True, 'message': msg}), 413
    flash(msg, 'error')
    return redirect(url_for('upload'))

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'Lens League Apex'}), 200


@app.route('/upload-debug', methods=['POST'])
@login_required
def upload_debug():
    """Temporary debug route — remove after mobile upload is confirmed working."""
    files_info = {}
    for key, f in request.files.items():
        data = f.read()
        files_info[key] = {
            'filename': f.filename,
            'content_type': f.content_type,
            'size_bytes': len(data),
        }
    return jsonify({
        'xhr_header': request.headers.get('X-Requested-With', 'NOT SET'),
        'content_type': request.content_type,
        'form_keys': list(request.form.keys()),
        'form_camera_track': request.form.get('camera_track', 'NOT SET'),
        'files': files_info,
        'user_agent': request.headers.get('User-Agent', ''),
    })


if __name__ == '__main__':
    app.run(debug=True)
