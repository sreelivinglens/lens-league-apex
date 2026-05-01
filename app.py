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
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# IST offset — admin types local IST times; subtract to store as UTC
_IST_OFFSET = timedelta(hours=5, minutes=30)

from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from models import (db, User, Image, CalibrationLog, ContestEntry, OpenContestEntry, ImageReport,
                    RatingAssignment, PeerRating, PeerPoolEntry,
                    WeeklyChallenge, WeeklySubmission,
                    BowSubmission, ContestPeriod, BrandContest, BrandEntry, ContestAnnouncement,
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
# Email utility  -  Gmail SMTP
# Env vars: MAIL_USERNAME, MAIL_PASSWORD
# Falls back silently if not configured  -  never crashes the app
# ---------------------------------------------------------------------------

def send_email(to_addresses, subject, html_body, text_body=None):
    """
    Send email via Brevo (HTTP API)  -  works on Railway (no SMTP port restrictions).
    Env var: BREVO_API_KEY
    to_addresses: str (single) or list of str.
    Returns True on success, False on failure.
    """
    import urllib.request
    import json as _json

    api_key = os.getenv('BREVO_API_KEY', '')
    if not api_key:
        app.logger.warning('[email] BREVO_API_KEY not set  -  skipping send')
        return False

    if isinstance(to_addresses, str):
        to_addresses = [to_addresses]

    sender_email = os.getenv('MAIL_USERNAME', CONTACT_EMAIL)

    payload = {
        'sender':     {'name': PLATFORM_NAME, 'email': sender_email},
        'to':         [{'email': addr} for addr in to_addresses],
        'subject':    subject,
        'htmlContent': html_body,
    }
    if text_body:
        payload['textContent'] = text_body

    data = _json.dumps(payload).encode('utf-8')
    req  = urllib.request.Request(
        'https://api.brevo.com/v3/smtp/email',
        data=data,
        headers={
            'accept':       'application/json',
            'content-type': 'application/json',
            'api-key':      api_key,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                app.logger.info(f'[email] Sent "{subject}" to {to_addresses}')
                return True
            else:
                body = resp.read().decode()
                app.logger.error(f'[email] Brevo returned {resp.status}: {body}')
                return False
    except Exception as e:
        app.logger.error(f'[email] Failed to send "{subject}": {e}')
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

    site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
    challenge_url = f"{site_url}/challenge"

    sponsor_line = ''
    if challenge.sponsor_name:
        prize_text = f'  -  Prize: {challenge.sponsor_prize}' if challenge.sponsor_prize else ''
        sponsor_line = f'<p style="margin:0 0 16px; color:#8a8070; font-size:15px;">Sponsored by <strong style="color:#C8A84B;">{challenge.sponsor_name}</strong>{prize_text}</p>'

    sent = 0
    for user in users:
        is_sub = getattr(user, 'is_subscribed', False)
        slot_text = '3 images this week' if is_sub else '1 image this week (subscribe for 3)'
        cta_text  = 'Submit your image ->' if is_sub else 'Enter the challenge ->'

        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F0E8;padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;overflow:hidden;max-width:560px;width:100%;">

      <!-- Header -->
      <tr><td style="background:#1a1a18;padding:24px 32px;">
        <p style="margin:0;font-family:'Courier New',monospace;font-size:13px;font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">SHUTTER LEAGUE</p>
      </td></tr>

      <!-- Challenge banner -->
      <tr><td style="background:#1a1a18;padding:0 32px 28px;">
        <p style="margin:0 0 6px;font-family:'Courier New',monospace;font-size:11px;letter-spacing:2px;color:#6a6458;text-transform:uppercase;">Weekly Challenge . {challenge.week_ref}</p>
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
          Closes {(challenge.closes_at + _IST_OFFSET).strftime('%A %d %B, %H:%M IST')}
        </p>
        <a href="{challenge_url}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:'Courier New',monospace;font-size:14px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;">{cta_text}</a>
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding:20px 32px;border-top:1px solid #E0D8C8;">
        <p style="margin:0;font-size:13px;color:#8a8070;line-height:1.6;">
          You're receiving this because you have an account on Shutter League.<br>
          <a href="{site_url}" style="color:#C8A84B;">shutterleague.com</a>
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

        text_body = f"""SHUTTER LEAGUE  -  Weekly Challenge

This week: {challenge.prompt_title}
{challenge.week_ref}

{'Brief: ' + challenge.prompt_body if challenge.prompt_body else ''}

You have: {slot_text}
Closes: {(challenge.closes_at + _IST_OFFSET).strftime('%A %d %B, %H:%M IST')}

Enter here: {challenge_url}

 -  Shutter League"""

        if send_email(user.email, f"This week's challenge: {challenge.prompt_title}", html_body, text_body):
            sent += 1

    return sent


FREE_IMAGE_LIMIT_MONTH1 = 6  # Free images in first calendar month after registration
FREE_IMAGE_LIMIT_DEFAULT = 3  # Free images per month from month 2 onwards
LEARNING_IMAGE_LIMIT = 12    # ₹100 Learning tier — 12 images/month

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config['SECRET_KEY']          = os.getenv('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///shutterleague.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle':  1800,
    'pool_timeout':  30,
    'pool_size':     5,
    'max_overflow':  10,
}
app.config['UPLOAD_FOLDER']       = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH']  = int(os.getenv('MAX_CONTENT_LENGTH', 20971520))

# Session cookie settings  -  required for mobile Safari (iOS ITP)
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

# ---------------------------------------------------------------------------
# Platform constants  -  single source of truth for branding + contact emails
# Change these env vars in Railway; no code deploy needed.
# ---------------------------------------------------------------------------
PLATFORM_NAME    = os.getenv('PLATFORM_NAME',    'Shutter League')
TERMS_VERSION    = 'v1'   # bump this whenever T&C page is updated
CONTACT_EMAIL    = os.getenv('CONTACT_EMAIL',    'info@shutterleague.com')
ADMIN_EMAIL      = os.getenv('ADMIN_EMAIL',      'admin@shutterleague.com')
ADMIN_NOTIFY_EMAIL = os.getenv('ADMIN_NOTIFY_EMAIL', 'admin@shutterleague.com')

# Startup warnings for missing critical env vars
_REQUIRED_ENV_VARS = [
    ('BREVO_API_KEY',       'emails will not send'),
    ('CONTACT_EMAIL',       'falling back to info@shutterleague.com'),
    ('ADMIN_EMAIL',         'falling back to admin@shutterleague.com'),
    ('ADMIN_NOTIFY_EMAIL',  'falling back to admin@shutterleague.com'),
    ('RAZORPAY_KEY_ID',     'payments will not work'),
    ('SECRET_KEY',          'using insecure dev key'),
]
for _var, _hint in _REQUIRED_ENV_VARS:
    if not os.getenv(_var):
        import logging
        logging.warning(f'[config] ENV VAR NOT SET: {_var} — {_hint}')

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


@app.before_request
def block_railway_url():
    """Block Railway UAT URL — show dead-end page."""
    host = request.host.lower()
    if 'railway.app' in host:
        return '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UAT Closed</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:#0D0D0B;color:#F0EFE8;font-family:"Courier New",monospace;
       display:flex;align-items:center;justify-content:center;height:100vh;}
  .box{text-align:center;padding:40px;}
  .title{font-size:18px;letter-spacing:4px;color:#C8A84B;margin-bottom:20px;}
  .msg{font-size:14px;color:#4a4a48;letter-spacing:1px;line-height:1.8;}
</style>
</head>
<body>
  <div class="box">
    <div class="title">UAT PERIOD CLOSED</div>
    <div class="msg">This testing environment is no longer available.<br>Thank you for your participation.</div>
  </div>
</body>
</html>''', 410

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
                # v27 peer rating columns  -  updated
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
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_review_pending BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS peer_pool_unlocks INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS razorpay_sub_id VARCHAR(64)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS is_in_peer_pool BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS pool_entry_chosen_at TIMESTAMP",
                # v28  -  location + league integrity
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
                # v52  -  legal consent tracking
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_ip VARCHAR(45)",
                # v53  -  POTY banner + contest framework
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS poty_banner_dismissed BOOLEAN DEFAULT FALSE",
                # v53  -  BOW submission fields
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS location VARCHAR(180)",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS period_of_work VARCHAR(120)",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS significance VARCHAR(300)",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS other_details TEXT",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS images_agreed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS is_subscriber BOOLEAN DEFAULT FALSE",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS amount_paise INTEGER DEFAULT 0",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS payment_ref VARCHAR(120)",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'free'",
                "ALTER TABLE bow_submissions ADD COLUMN IF NOT EXISTS qualifier_emailed BOOLEAN DEFAULT FALSE",
                # v53  -  open contest entry fixes
                "ALTER TABLE open_contest_entries ADD COLUMN IF NOT EXISTS is_free_slot BOOLEAN DEFAULT FALSE",
                "ALTER TABLE open_contest_entries ADD COLUMN IF NOT EXISTS qualifier_emailed BOOLEAN DEFAULT FALSE",
                # v53  -  new contest tables
                "CREATE TABLE IF NOT EXISTS contest_periods (id SERIAL PRIMARY KEY, platform_year INTEGER UNIQUE NOT NULL, poty_opens_at TIMESTAMP, poty_closes_at TIMESTAMP, poty_status VARCHAR(20) DEFAULT 'upcoming', bow_entry_opens_at TIMESTAMP, bow_entry_closes_at TIMESTAMP, bow_judging_ends_at TIMESTAMP, bow_status VARCHAR(20) DEFAULT 'upcoming', open_opens_at TIMESTAMP, open_closes_at TIMESTAMP, open_cooling_ends_at TIMESTAMP, open_status VARCHAR(20) DEFAULT 'upcoming', winners_announced_at TIMESTAMP, announcement_banner TEXT, banner_active BOOLEAN DEFAULT FALSE, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMP DEFAULT NOW())",
                "CREATE TABLE IF NOT EXISTS brand_contests (id SERIAL PRIMARY KEY, title VARCHAR(180) NOT NULL, brand_name VARCHAR(120) NOT NULL, brief TEXT NOT NULL, prize_desc TEXT NOT NULL, prize_value VARCHAR(80), opens_at TIMESTAMP NOT NULL, closes_at TIMESTAMP NOT NULL, max_entries_per_user INTEGER DEFAULT 3, status VARCHAR(20) DEFAULT 'draft', results_published_at TIMESTAMP, announcement_sent_at TIMESTAMP, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMP DEFAULT NOW())",
                "CREATE TABLE IF NOT EXISTS brand_entries (id SERIAL PRIMARY KEY, contest_id INTEGER NOT NULL REFERENCES brand_contests(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id), image_id INTEGER NOT NULL REFERENCES images(id), entered_at TIMESTAMP DEFAULT NOW(), result_rank INTEGER, result_note TEXT, result_emailed BOOLEAN DEFAULT FALSE, CONSTRAINT uq_brand_entry UNIQUE(contest_id, user_id, image_id))",
                "CREATE TABLE IF NOT EXISTS contest_announcements (id SERIAL PRIMARY KEY, contest_type VARCHAR(20) NOT NULL, contest_ref VARCHAR(40), title VARCHAR(180) NOT NULL, body TEXT NOT NULL, cta_label VARCHAR(80), cta_url VARCHAR(255), audience VARCHAR(20) DEFAULT 'all', delivery VARCHAR(20) DEFAULT 'both', status VARCHAR(20) DEFAULT 'draft', send_at TIMESTAMP, sent_at TIMESTAMP, banner_active BOOLEAN DEFAULT FALSE, banner_expires_at TIMESTAMP, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMP DEFAULT NOW())",
                "CREATE INDEX IF NOT EXISTS ix_brand_contests_status ON brand_contests(status)",
                "CREATE INDEX IF NOT EXISTS ix_contest_announcements_banner ON contest_announcements(banner_active)",
                # v29  -  weekly challenge
                "CREATE TABLE IF NOT EXISTS weekly_challenges (id SERIAL PRIMARY KEY, week_ref VARCHAR(10) UNIQUE NOT NULL, prompt_title VARCHAR(120) NOT NULL, prompt_body TEXT, opens_at TIMESTAMP NOT NULL, closes_at TIMESTAMP NOT NULL, results_at TIMESTAMP, sponsor_name VARCHAR(120), sponsor_prize TEXT, is_active BOOLEAN DEFAULT TRUE, created_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT NOW())",
                "CREATE TABLE IF NOT EXISTS weekly_submissions (id SERIAL PRIMARY KEY, challenge_id INTEGER NOT NULL REFERENCES weekly_challenges(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE, is_subscriber BOOLEAN DEFAULT FALSE, submitted_at TIMESTAMP DEFAULT NOW(), result_rank INTEGER, result_note TEXT, CONSTRAINT uq_weekly_sub_image UNIQUE(challenge_id, image_id))",
                "CREATE INDEX IF NOT EXISTS ix_weekly_challenges_week_ref ON weekly_challenges(week_ref)",
                # v30  -  image columns for jury + RAW verification
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS raw_verification_required BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS raw_verified BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS raw_disqualified BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS in_judge_pool BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS judge_score FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS judge_final_score FLOAT",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS judge_flagged BOOLEAN DEFAULT FALSE",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS judge_flag_type VARCHAR(40)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS contest_result_status VARCHAR(20)",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_original_width INTEGER",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_original_height INTEGER",
                "ALTER TABLE images ADD COLUMN IF NOT EXISTS exif_capture_datetime VARCHAR(40)",
                # v31 - jury flag resolution
                "ALTER TABLE judge_assignments ADD COLUMN IF NOT EXISTS admin_flag_decision VARCHAR(20)",
                "ALTER TABLE judge_assignments ADD COLUMN IF NOT EXISTS admin_flag_note TEXT",
                "ALTER TABLE judge_assignments ADD COLUMN IF NOT EXISTS admin_flag_decided_at TIMESTAMP",
                # v32 - automated RAW verification + appeal system
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS auto_decision VARCHAR(20)",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS auto_decided_at TIMESTAMP",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS auto_flag_reasons TEXT",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS appeal_submitted_at TIMESTAMP",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS appeal_decision VARCHAR(20)",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS appeal_decided_at TIMESTAMP",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS appeal_admin_note TEXT",
                "ALTER TABLE raw_submissions ADD COLUMN IF NOT EXISTS appeal_decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL",
            ]
            for sql in _migrations:
                try:
                    conn.execute(db.text(sql))
                except Exception as _e:
                    print(f'[migration] {_e}')
            conn.commit()

        # Fix calibration_logs  -  force correct schema on every startup
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

        # Fix open_contest_entries unique constraint: user+genre+year → user+image+year
        try:
            with db.engine.connect() as conn_fix:
                conn_fix.execute(db.text(
                    "ALTER TABLE open_contest_entries DROP CONSTRAINT IF EXISTS open_contest_entries_user_id_genre_platform_year_key"
                ))
                conn_fix.commit()
            print('open_contest_entries old constraint dropped.')
        except Exception as ce:
            print(f'open_contest_entries drop constraint warning: {ce}')
        try:
            with db.engine.connect() as conn_fix2:
                conn_fix2.execute(db.text(
                    "ALTER TABLE open_contest_entries ADD CONSTRAINT uq_oce_user_image_year UNIQUE (user_id, image_id, platform_year)"
                ))
                conn_fix2.commit()
            print('open_contest_entries constraint fix OK.')
        except Exception as ce:
            print(f'open_contest_entries add constraint warning: {ce}')

        # v27  -  peer rating tables
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

        # v30  -  judges table
        try:
            with db.engine.connect() as conn7:
                conn7.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS judges (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        status VARCHAR(20) DEFAULT \'invited\',
                        invite_token VARCHAR(64) UNIQUE,
                        invite_sent_at TIMESTAMP,
                        invite_expires_at TIMESTAMP,
                        name VARCHAR(120),
                        email VARCHAR(120) UNIQUE NOT NULL,
                        phone VARCHAR(40),
                        address TEXT,
                        city VARCHAR(80),
                        country VARCHAR(80),
                        photo_key VARCHAR(512),
                        years_experience INTEGER,
                        judged_before BOOLEAN DEFAULT FALSE,
                        bio TEXT,
                        agreed_terms BOOLEAN DEFAULT FALSE,
                        agreed_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT NOW(),
                        approved_at TIMESTAMP,
                        approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL
                    )
                '''))
                conn7.commit()
            print('judges schema OK.')
        except Exception as ce:
            print(f'judges migration warning: {ce}')

        # v30  -  judge_category_assignments table
        try:
            with db.engine.connect() as conn8:
                conn8.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS judge_category_assignments (
                        id SERIAL PRIMARY KEY,
                        judge_id INTEGER NOT NULL REFERENCES judges(id) ON DELETE CASCADE,
                        category VARCHAR(60) NOT NULL,
                        contest_type VARCHAR(20) DEFAULT \'all\',
                        assigned_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        assigned_at TIMESTAMP DEFAULT NOW(),
                        active BOOLEAN DEFAULT TRUE
                    )
                '''))
                conn8.commit()
            print('judge_category_assignments schema OK.')
        except Exception as ce:
            print(f'judge_category_assignments migration warning: {ce}')

        # v30  -  contest_judge_configs table
        try:
            with db.engine.connect() as conn9:
                conn9.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS contest_judge_configs (
                        id SERIAL PRIMARY KEY,
                        contest_ref VARCHAR(40) NOT NULL,
                        contest_type VARCHAR(20) NOT NULL,
                        score_threshold FLOAT DEFAULT 8.0,
                        weighting_mode VARCHAR(20) DEFAULT \'tiebreaker\',
                        ddi_weight INTEGER DEFAULT 100,
                        judge_weight INTEGER DEFAULT 0,
                        cooling_period_hours INTEGER DEFAULT 48,
                        pool_populated_at TIMESTAMP,
                        results_emailed_at TIMESTAMP,
                        leaderboard_published_at TIMESTAMP,
                        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        created_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(contest_ref, contest_type)
                    )
                '''))
                conn9.commit()
            print('contest_judge_configs schema OK.')
        except Exception as ce:
            print(f'contest_judge_configs migration warning: {ce}')

        # v30  -  judge_assignments table
        try:
            with db.engine.connect() as conn10:
                conn10.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS judge_assignments (
                        id SERIAL PRIMARY KEY,
                        judge_id INTEGER NOT NULL REFERENCES judges(id) ON DELETE CASCADE,
                        image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                        contest_ref VARCHAR(40),
                        contest_type VARCHAR(20),
                        assigned_at TIMESTAMP DEFAULT NOW(),
                        deadline TIMESTAMP,
                        status VARCHAR(20) DEFAULT \'pending\',
                        reminder_48_sent BOOLEAN DEFAULT FALSE,
                        reminder_24_sent BOOLEAN DEFAULT FALSE,
                        UNIQUE(judge_id, image_id)
                    )
                '''))
                conn10.commit()
            print('judge_assignments schema OK.')
        except Exception as ce:
            print(f'judge_assignments migration warning: {ce}')

        # v30  -  judge_scores table
        try:
            with db.engine.connect() as conn11:
                conn11.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS judge_scores (
                        id SERIAL PRIMARY KEY,
                        judge_assignment_id INTEGER NOT NULL REFERENCES judge_assignments(id) ON DELETE CASCADE,
                        judge_id INTEGER NOT NULL REFERENCES judges(id) ON DELETE CASCADE,
                        image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                        dod_score FLOAT,
                        disruption_score FLOAT,
                        dm_score FLOAT,
                        wonder_score FLOAT,
                        aq_score FLOAT,
                        judge_total FLOAT,
                        submitted_at TIMESTAMP DEFAULT NOW(),
                        flag_type VARCHAR(40),
                        flag_notes TEXT,
                        UNIQUE(judge_assignment_id)
                    )
                '''))
                conn11.commit()
            print('judge_scores schema OK.')
        except Exception as ce:
            print(f'judge_scores migration warning: {ce}')

        # v30  -  raw_submissions table
        try:
            with db.engine.connect() as conn12:
                conn12.execute(db.text('''
                    CREATE TABLE IF NOT EXISTS raw_submissions (
                        id SERIAL PRIMARY KEY,
                        image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        contest_ref VARCHAR(40),
                        contest_type VARCHAR(20),
                        submission_method VARCHAR(20) DEFAULT \'upload\',
                        raw_file_key VARCHAR(512),
                        raw_link TEXT,
                        submitted_at TIMESTAMP,
                        deadline TIMESTAMP,
                        reminder_48_sent BOOLEAN DEFAULT FALSE,
                        reminder_24_sent BOOLEAN DEFAULT FALSE,
                        analysis_status VARCHAR(20) DEFAULT \'pending\',
                        analysis_run_at TIMESTAMP,
                        exif_match BOOLEAN,
                        crop_percentage FLOAT,
                        crop_flagged BOOLEAN DEFAULT FALSE,
                        dimension_match BOOLEAN,
                        raw_original_width INTEGER,
                        raw_original_height INTEGER,
                        vision_ai_detected BOOLEAN,
                        vision_objects_removed BOOLEAN,
                        vision_objects_added BOOLEAN,
                        vision_logo_trademark BOOLEAN,
                        vision_meaning_changed BOOLEAN,
                        vision_painterly BOOLEAN,
                        vision_crop_consistent BOOLEAN,
                        vision_notes TEXT,
                        overall_flag BOOLEAN DEFAULT FALSE,
                        flag_reasons TEXT,
                        admin_decision VARCHAR(20),
                        admin_notes TEXT,
                        admin_decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        admin_decided_at TIMESTAMP,
                        disqualified BOOLEAN DEFAULT FALSE,
                        notified_at TIMESTAMP,
                        UNIQUE(image_id, contest_ref, contest_type)
                    )
                '''))
                conn12.commit()
            print('raw_submissions schema OK.')
        except Exception as ce:
            print(f'raw_submissions migration warning: {ce}')

        print('Columns migrated OK.')
    except Exception as e:
        print(f'Migration warning: {e}')

    try:
        with db.engine.connect() as conn:
            new_hash = generate_password_hash('LensAdmin2026!')
            exists = conn.execute(db.text("SELECT id FROM users WHERE email='admin@shutterleague.com'")).fetchone()
            if not exists:
                conn.execute(db.text(
                    "INSERT INTO users (email, username, password_hash, full_name, role, is_active, created_at) "
                    "VALUES ('admin@shutterleague.com','admin',:h,'Admin','admin',true,NOW())"
                ), {'h': new_hash})
                print('Admin account created.')
            else:
                conn.execute(db.text(
                    "UPDATE users SET password_hash=:h, role='admin', is_active=true WHERE email='admin@shutterleague.com'"
                ), {'h': new_hash})
                print('Admin account updated.')
            conn.commit()
        print('Database ready.')
    except Exception as e:
        print(f'Admin init warning: {e}')


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.context_processor
def inject_globals():
    """Inject platform constants and judge status into every template context."""
    is_approved_judge = False
    if current_user.is_authenticated and current_user.role != 'admin':
        try:
            result = db.session.execute(
                db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
                {'uid': current_user.id}
            ).fetchone()
            is_approved_judge = result is not None
        except Exception:
            pass
    return {
        'is_approved_judge': is_approved_judge,
        'platform_name':     PLATFORM_NAME,
        'contact_email':     CONTACT_EMAIL,
        'admin_email':       ADMIN_EMAIL,
        'timedelta':         timedelta,
        'now':               datetime.utcnow,
    }


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helper  -  open contest active flag
# ---------------------------------------------------------------------------

def is_open_contest_active() -> bool:
    return os.getenv('OPEN_CONTEST_ACTIVE', '0') == '1'


def is_bow_active() -> bool:
    return os.getenv('BOW_ACTIVE', '0') == '1'


# ---------------------------------------------------------------------------
# Helper  -  upload both thumb and card to R2, return public URLs
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
        # Recent public scored images for bottom strips
        recent_images = (Image.query
                         .filter(Image.status=='scored', Image.score!=None,
                                 Image.is_public==True, Image.is_flagged==False)
                         .order_by(Image.scored_at.desc())
                         .limit(6).all())
        # Hero carousel — Grandmaster/Master only, score >= 8.0
        carousel_images = (Image.query
                           .filter(Image.status=='scored', Image.score!=None,
                                   Image.is_public==True, Image.is_flagged==False,
                                   Image.tier.in_(['Legend','Grandmaster','Master']),
                                   Image.score>=8.0)
                           .order_by(Image.score.desc())
                           .limit(6).all())
        active_challenge = _get_active_challenge()
        # Top challenge entry thumb for Slide 2 carousel
        challenge_thumb = None
        if active_challenge:
            top_sub = (WeeklySubmission.query
                       .filter_by(challenge_id=active_challenge.id)
                       .join(Image, WeeklySubmission.image_id == Image.id)
                       .filter(Image.thumb_url != None)
                       .order_by(Image.score.desc())
                       .first())
            if top_sub:
                challenge_thumb = top_sub.image.thumb_url
    except Exception:
        recent_images = []
        carousel_images = []
        active_challenge = None
        challenge_thumb = None
    return render_template('index.html',
                           recent_images=recent_images,
                           carousel_images=carousel_images,
                           active_challenge=active_challenge,
                           challenge_thumb=challenge_thumb,
                           now=datetime.utcnow())


@app.route('/register')
def register():
    if current_user.is_authenticated:
        # Judge already logged in -- send to jury dashboard
        _jc = db.session.execute(
            db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
            {'uid': current_user.id}
        ).fetchone()
        if _jc:
            return redirect(url_for('judge_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/auth/google')
def auth_google():
    # Save next URL in session so we can redirect after OAuth
    next_url = request.args.get('next', '')
    if next_url:
        session['post_login_next'] = next_url
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
        flash('Google sign-in failed  -  no email returned. Please try again.', 'error')
        return redirect(url_for('login'))

    # Find existing user by google_id or email
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    if user:
        # Existing user  -  update google_id if not set
        if not user.google_id:
            user.google_id = google_id
        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user)
        if not getattr(user, 'onboarding_complete', True):
            return redirect(url_for('onboarding'))
        # Check if this user is an approved judge -- send to jury dashboard
        judge_check = db.session.execute(
            db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
            {'uid': user.id}
        ).fetchone()
        if judge_check:
            return redirect(url_for('judge_dashboard'))
        # Redirect to stored next URL if available
        post_next = session.pop('post_login_next', None)
        if post_next:
            return redirect(post_next)
        return redirect(url_for('dashboard'))
    else:
        # New user  -  create account, send to onboarding
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
        terms   = request.form.get('terms')

        if not country or not state or not city:
            flash('Please select your country, state/province, and city.', 'error')
            return redirect(url_for('onboarding'))
        if not agreed:
            flash('Please accept the Member Agreement to continue.', 'error')
            return redirect(url_for('onboarding'))
        if not terms:
            flash('Please accept the Terms & Conditions to continue.', 'error')
            return redirect(url_for('onboarding'))

        now = datetime.utcnow()
        current_user.country             = country
        current_user.state               = state
        current_user.city                = city
        current_user.agreed_at           = now
        current_user.terms_accepted_at   = now
        current_user.terms_version       = TERMS_VERSION
        current_user.signup_ip           = request.remote_addr
        current_user.onboarding_complete = True
        db.session.commit()
        try:
            send_welcome_email(current_user)
        except Exception as _we:
            app.logger.warning('[welcome_email] Error: ' + str(_we))
        flash('Welcome to Shutter League! Your account is ready.', 'success')
        # Redirect to intended destination if set before login
        post_next = session.pop('post_login_next', None)
        if post_next:
            return redirect(post_next)
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
        # Judge already logged in -- send to jury dashboard
        _jc = db.session.execute(
            db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
            {'uid': current_user.id}
        ).fetchone()
        if _jc:
            return redirect(url_for('judge_dashboard'))
        return redirect(url_for('dashboard'))


    # Store ?next= in session on GET so Google OAuth callback can redirect
    # correctly after login. Email/password path reads request.args directly.
    # Google OAuth goes to /auth/google without ?next= so we cache it here.
    if request.method == 'GET':
        _next = request.args.get('next', '').strip()
        if _next:
            session['post_login_next'] = _next

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
        # Check if this user is an approved judge -- send to jury dashboard
        judge_check = db.session.execute(
            db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
            {'uid': user.id}
        ).fetchone()
        if judge_check:
            return redirect(url_for('judge_dashboard'))
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
    # Approved judges should not see the photographer dashboard
    if current_user.role != 'admin':
        _jc = db.session.execute(
            db.text("SELECT id FROM judges WHERE user_id = :uid AND status = 'approved'"),
            {'uid': current_user.id}
        ).fetchone()
        if _jc:
            return redirect(url_for('judge_dashboard'))
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

    # -- POTY top-6 tracker --------------------------------------------------
    # Live top-6 average per genre for the current user.
    # Deleted images intentionally not excluded  -  per contest rules, deletions
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

    # Zone notification data -- all pages, not just current
    zone3_flagged = Image.query.filter(
        Image.user_id == current_user.id,
        Image.needs_review == True,
        Image.judge_referral == True,
        Image.is_flagged == False,
        Image.peer_avg_score != None,
        Image.peer_rating_count >= 5
    ).all() if current_user.role != 'admin' else []
    zone2_pending = Image.query.filter_by(
        user_id=current_user.id, peer_review_pending=True, needs_review=False, is_flagged=False
    ).all() if not current_user.role == 'admin' else []

    # Contest wins -- images with published results
    contest_wins = []
    if current_user.role != 'admin':
        contest_wins = Image.query.filter_by(
            user_id=current_user.id,
            contest_result_status='published'
        ).filter(Image.judge_final_score != None).order_by(
            Image.judge_final_score.desc()
        ).all()

    # POTY welcome banner
    show_poty_banner = not getattr(current_user, 'poty_banner_dismissed', False)

    # Contest announcement banners — active banners matching user audience
    _is_sub = getattr(current_user, 'is_subscribed', False)
    _ann_q  = ContestAnnouncement.query.filter_by(banner_active=True)
    if current_user.role != 'admin':
        if _is_sub:
            _ann_q = _ann_q.filter(
                ContestAnnouncement.audience.in_(['all', 'subscribers'])
            )
        else:
            _ann_q = _ann_q.filter(
                ContestAnnouncement.audience.in_(['all', 'non_subscribers'])
            )
    contest_banners = _ann_q.order_by(ContestAnnouncement.created_at.desc()).all()

    # RAW pending -- images flagged for verification not yet verified or disqualified
    raw_pending = Image.query.filter(
        Image.user_id == current_user.id,
        Image.raw_verification_required == True,
        Image.raw_verified == False,
        Image.raw_disqualified == False
    ).all() if current_user.role != 'admin' else []

    return render_template('dashboard.html', images=images, stats=stats,
                           query=query, search_enabled=(total_images >= 20),
                           rating_widget=rating_widget, free_tier=free_tier,
                           poty_tracker=poty_tracker,
                           active_challenge=active_challenge,
                           zone3_flagged=zone3_flagged,
                           zone2_pending=zone2_pending,
                           contest_wins=contest_wins,
                           show_poty_banner=show_poty_banner,
                           contest_banners=contest_banners,
                           raw_pending=raw_pending)


# ---------------------------------------------------------------------------
# POTY welcome banner dismiss
# ---------------------------------------------------------------------------

@app.route('/dismiss-poty-banner', methods=['POST'])
@login_required
def dismiss_poty_banner():
    current_user.poty_banner_dismissed = True
    db.session.commit()
    return ('', 204)


# ---------------------------------------------------------------------------
# Profile  -  edit name/username + change password (combined page)
# ---------------------------------------------------------------------------

def _build_progress_data(user):
    """Returns progress dict for profile dashboard, or None if < 5 scored images."""
    scored = (Image.query
              .filter_by(user_id=user.id, status='scored')
              .filter(Image.score.isnot(None),
                      Image.is_flagged.isnot(True),
                      Image.needs_review.isnot(True))
              .order_by(Image.scored_at.asc())
              .all())

    if len(scored) < 5:
        return None

    dim_labels = {
        'dod': 'Detail', 'disruption': 'Disruption',
        'dm': 'Moment', 'wonder': 'Wonder', 'aq': 'Authenticity'
    }
    dim_fields = {
        'dod': 'dod_score', 'disruption': 'disruption_score',
        'dm': 'dm_score', 'wonder': 'wonder_score', 'aq': 'aq_score'
    }

    avgs = {}
    for d in dim_fields:
        vals = [getattr(img, dim_fields[d]) for img in scored
                if getattr(img, dim_fields[d]) is not None]
        avgs[d] = round(sum(vals) / len(vals), 2) if vals else 0.0

    trend_imgs = scored[-10:]
    trend = [{'label': f'#{i+1}', 'tier': img.tier or get_tier(img.score), 'score': img.score}
             for i, img in enumerate(trend_imgs)]

    strongest = max(avgs, key=avgs.get)
    weakest   = min(avgs, key=avgs.get)

    from collections import Counter
    genre_counts = Counter(img.genre for img in scored if img.genre)
    top_genre = genre_counts.most_common(1)[0][0] if genre_counts else None

    avg_score = round(sum(img.score for img in scored) / len(scored), 2)

    return {
        'count':      len(scored),
        'avg_tier':   get_tier(avg_score),
        'dim_avgs':   avgs,
        'dim_labels': dim_labels,
        'trend':      trend,
        'strongest':  strongest,
        'weakest':    weakest,
        'top_genre':  top_genre,
    }


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    images_used = Image.query.filter_by(user_id=current_user.id).count()

    if request.method == 'POST':
        action = request.form.get('action')

        # -- Update profile details ----------------------------------------
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

        # -- Change password -----------------------------------------------
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

    progress_data = _build_progress_data(current_user)
    return render_template('profile.html', images_used=images_used, progress_data=progress_data)


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

        # -- Free quota check (6 in month 1, 3/month thereafter) ----------
        if current_user.role != 'admin':
            from datetime import date as _date
            today       = _date.today()
            month_start = datetime(today.year, today.month, 1)
            month_count = Image.query.filter(
                Image.user_id == current_user.id,
                Image.created_at >= month_start,
            ).count()
            _track = getattr(current_user, 'subscription_track', None) or ''
            _is_sub = getattr(current_user, 'is_subscribed', False)

            if not _is_sub:
                # Free tier
                reg_date  = current_user.created_at.date() if current_user.created_at else today
                in_month1 = (today.year == reg_date.year and today.month == reg_date.month)
                free_limit = FREE_IMAGE_LIMIT_MONTH1 if in_month1 else FREE_IMAGE_LIMIT_DEFAULT
                if month_count >= free_limit:
                    flash(
                        f'You have used all {free_limit} free scored images for this month. '
                        'Upgrade to Learning (₹100/mo) for 12 images/month, or Camera/Mobile for unlimited.',
                        'error'
                    )
                    return redirect(url_for('pricing'))
            elif _track == 'learning':
                # ₹100 Learning tier — 12 images/month
                if month_count >= LEARNING_IMAGE_LIMIT:
                    flash(
                        f'You have used all {LEARNING_IMAGE_LIMIT} Learning tier images for this month. '
                        'Upgrade to Camera or Mobile track for unlimited uploads and contest access.',
                        'error'
                    )
                    return redirect(url_for('pricing'))
            # Camera/Mobile/Mentor tracks — unlimited, no check needed

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
        # Extract EXIF from original file BEFORE deletion  -  raw_path still has full metadata
        from engine.exif_check import extract_exif
        exif_status, exif_data, exif_warning = extract_exif(raw_path)
        exif_settings = '  .  '.join(filter(None, [
            exif_data.get('focal_length',''), exif_data.get('aperture',''),
            exif_data.get('iso',''), exif_data.get('shutter',''),
        ]))

        if os.path.exists(raw_path): os.remove(raw_path)

        from engine.processor import hash_similarity_pct
        existing = Image.query.filter(Image.phash.isnot(None)).all()
        for ex in existing:
            sim = hash_similarity_pct(phash, ex.phash)
            if sim >= 98.0:
                if os.path.exists(thumb_path): os.remove(thumb_path)
                if ex.user_id == current_user.id:
                    return jsonify({'error': True, 'message':
                        f' This image appears identical to one you already uploaded (\"{ ex.asset_name or ex.original_filename }\"). Please upload a different photograph.'
                    }), 409
                else:
                    return jsonify({'error': True, 'message':
                        'We were unable to accept this image. Our system has detected that it may be identical to a photograph already in our database. '
                        'Please ensure you are submitting your own original work. '
                        'If you believe this is an error, contact info@shutterleague.com and we will review it promptly.'
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

        # -- League integrity check (three-strike system) ------------------
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
                f'detected on Mobile League subscription  -  strike {strike}/3]'
            )
            db.session.commit()
            app.logger.warning(
                f'[league_mismatch] user={current_user.id} image={img.id} '
                f'exif={_exif_cam_lower} strike={strike}'
            )

            if strike == 1:
                flash(
                    ' League check: this image appears to have been taken on a dedicated camera, '
                    'but you are in the Mobile League. The image has been held for review. '
                    'If you shoot on a camera, please switch to the Camera League. '
                    'Contact '+CONTACT_EMAIL+' with questions.',
                    'warning'
                )
            elif strike == 2:
                flash(
                    ' Second league mismatch. This image has been held for review and '
                    'your contest entries for this month have been removed pending admin review. '
                    'One more mismatch will suspend your contest access.',
                    'warning'
                )
                _month = datetime.utcnow().strftime('%Y-%m')
                ContestEntry.query.filter_by(user_id=current_user.id, contest_month=_month).delete()
                db.session.commit()
            elif strike >= 3:
                flash(
                    ' Three league mismatches detected. Your contest access has been suspended '
                    'and this month\'s contest entries have been removed. '
                    'Contact '+CONTACT_EMAIL+' to resolve.',
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

                # -- AI suspicion check ------------------------------------
                ai_suspicion = float(result.get('ai_suspicion', 0.0))
                img.ai_suspicion        = ai_suspicion
                img.ai_suspicion_reason = result.get('ai_suspicion_reason') or None
                img.needs_review        = bool(result.get('needs_review', False))

                if ai_suspicion >= 0.7:
                    # TIER 3  -  Auto-flagged: almost certainly AI-generated
                    img.score            = 0.0
                    img.tier = 'Rookie'
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
                    try:
                        _u = User.query.get(img.user_id)
                        _uname = (_u.full_name or _u.username) if _u else 'Photographer'
                        _iurl = f'https://shutterleague.com/image/{img.id}'
                        send_email(
                            to_addresses=[_u.email] if _u else [],
                            subject='[Shutter League] Image Flagged — AI Generation Detected',
                            html_body=('<p>Hi ' + _uname + ',</p><p>Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has been flagged as potentially AI-generated.</p><p>Contact <a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a> if this is an error.</p><p>The Shutter League Team</p>'),
                            text_body=('Hi ' + _uname + ',\n\nYour image "' + (img.asset_name or 'Untitled') + '" was flagged as potentially AI-generated.\n\nContact ' + CONTACT_EMAIL + ' if this is an error.\n\nThe Shutter League Team')
                        )
                        send_email(
                            to_addresses=[ADMIN_EMAIL],
                            subject='[Admin] AI Flag — ' + (img.asset_name or 'Untitled'),
                            html_body=('<p>Auto-flagged AI image.</p><ul><li>Image: ' + (img.asset_name or 'Untitled') + '</li><li>AI Suspicion: ' + str(round(ai_suspicion, 2)) + '</li><li>User: ' + (_u.email if _u else 'unknown') + '</li></ul><p><a href="' + _iurl + '">Review</a></p>'),
                            text_body=('AI Flag\nImage: ' + (img.asset_name or 'Untitled') + '\nSuspicion: ' + str(round(ai_suspicion, 2)) + '\nUser: ' + (_u.email if _u else 'unknown') + '\nReview: ' + _iurl)
                        )
                    except Exception as _me:
                        app.logger.error(f'[AI flag email error] {_me}')
                    flash(
                        ' This image has been flagged as potentially AI-generated and cannot be submitted. '
                        'Only original photographs taken by you are accepted. '
                        'If you believe this is an error, contact '+CONTACT_EMAIL+'.',
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

                    # TIER 2  -  Needs human review:
                    # (a) AI suspicion in amber zone 0.4-0.69, OR
                    # (b) Grandmaster score (9.0+)  -  always requires RAW verification
                    if ai_suspicion >= 0.4 or img.score >= 9.0:
                        img.needs_review    = True
                        img.is_public       = False   # held from public until admin clears
                        review_reason_parts = []
                        if ai_suspicion >= 0.4:
                            review_reason_parts.append(f'AI suspicion score {ai_suspicion:.2f} (amber zone)')
                        if img.score >= 9.0:
                            review_reason_parts.append(f'Grandmaster score {img.score} requires RAW verification')
                        img.flagged_reason  = ' . '.join(review_reason_parts)

                        try:
                            _u = User.query.get(img.user_id)
                            _uname = (_u.full_name or _u.username) if _u else 'Photographer'
                            _iurl = f'https://shutterleague.com/image/{img.id}'
                            _site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
                            if img.score >= 9.0 and ai_suspicion < 0.4:
                                # Set flag + create raw_submissions record automatically
                                img.raw_verification_required = True
                                _deadline = datetime.utcnow() + timedelta(days=7)
                                _submit_url = f'{_site_url}/raw/submit/weekly/{img.id}'
                                try:
                                    db.session.execute(db.text(
                                        "INSERT INTO raw_submissions "
                                        "(image_id, user_id, contest_ref, contest_type, deadline, analysis_status) "
                                        "VALUES (:iid, :uid, 'grandmaster', 'weekly', :dl, 'awaiting') "
                                        "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE SET deadline=:dl"
                                    ), {'iid': img.id, 'uid': img.user_id, 'dl': _deadline})
                                except Exception:
                                    pass
                                # Email user — branded, direct submit link
                                send_email(
                                    to_addresses=[_u.email] if _u else [],
                                    subject='[Shutter League] Grandmaster Score — RAW Verification Required',
                                    html_body=(
                                        '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;background:#fffef9;color:#111111;">'
                                        '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#F5C518;margin-bottom:24px;">Shutter League</p>'
                                        '<h2 style="font-size:22px;font-weight:700;color:#111111;margin-bottom:16px;">Grandmaster Score &#8212; RAW Verification Required</h2>'
                                        '<p style="font-size:16px;line-height:1.7;color:#111111;">Congratulations ' + _uname + ' &#8212; <strong>' + (img.asset_name or 'Untitled') + '</strong> scored <strong style="color:#F5C518;">' + str(img.score) + '</strong> (' + (img.tier or '') + ').</p>'
                                        '<p style="font-size:16px;line-height:1.7;color:#111111;">To confirm your result, please submit your original RAW file within <strong>7 days</strong>. Your image is held from public view until verified.</p>'
                                        '<a href="' + _submit_url + '" style="display:inline-block;background:#F5C518;color:#000000;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:20px 0 8px 0;">Submit RAW File &#8594;</a>'
                                        '<p style="font-size:14px;color:#111111;margin-top:8px;">Or visit: <a href="' + _submit_url + '" style="color:#F5C518;">' + _submit_url + '</a></p>'
                                        '<p style="font-size:14px;color:#555555;margin-top:24px;">&#8212; Shutter League</p>'
                                        '</div>'
                                    )
                                )
                                # Notify admin
                                send_email(
                                    to_addresses=[ADMIN_EMAIL],
                                    subject='[Admin] Grandmaster RAW Required — ' + (img.asset_name or 'Untitled') + ' (' + str(img.score) + ')',
                                    html_body=('<p>Grandmaster image auto-flagged for RAW verification. Submission record created. User notified with direct submit link.</p><ul><li>Image: ' + (img.asset_name or 'Untitled') + '</li><li>Score: ' + str(img.score) + ' — ' + (img.tier or '') + '</li><li>Photographer: ' + (img.photographer_name or _uname) + '</li><li>User: ' + (_u.email if _u else 'unknown') + '</li><li>Deadline: 7 days</li></ul><p><a href="' + _site_url + '/admin/raw-verification/' + str(img.id) + '">View in RAW Queue</a></p>'),
                                    text_body=('Grandmaster RAW auto-flagged\nImage: ' + (img.asset_name or 'Untitled') + '\nScore: ' + str(img.score) + '\nUser: ' + (_u.email if _u else 'unknown'))
                                )
                            else:
                                send_email(
                                    to_addresses=[ADMIN_EMAIL],
                                    subject='[Admin] Image Flagged for Review — ' + (img.asset_name or 'Untitled'),
                                    html_body=('<p>Image flagged for review.</p><ul><li>Image: ' + (img.asset_name or 'Untitled') + '</li><li>Score: ' + str(img.score) + ' — ' + (img.tier or '') + '</li><li>Reason: ' + (img.flagged_reason or '') + '</li><li>User: ' + (_u.email if _u else 'unknown') + '</li></ul><p><a href="' + _iurl + '">Review</a></p>'),
                                    text_body=('Flagged for review.\nImage: ' + (img.asset_name or 'Untitled') + '\nReason: ' + (img.flagged_reason or '') + '\nUser: ' + (_u.email if _u else 'unknown') + '\nReview: ' + _iurl)
                                )
                        except Exception as _me:
                            app.logger.error(f'[review notification email error] {_me}')

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

                    flash(f'Auto-scored! LL-Score: {img.score}  -  {img.tier}', 'success')
                    if getattr(img, 'needs_review', False):
                        if img.score >= 9.0 and ai_suspicion < 0.4:
                            flash(
                                f' Grandmaster score! Your image has been held for RAW verification. '
                                f'Check your email for a direct link to submit your original RAW file within 7 days.',
                                'warning'
                            )
                        else:
                            flash(
                                f' Your image has been flagged for human review before going public. '
                                f'This is usually resolved within 24-48 hours. '
                                f'Contact {CONTACT_EMAIL} if you have questions.',
                                'warning'
                            )
            except Exception as e:
                app.logger.error(f'[upload scoring error] {traceback.format_exc()}')
                db.session.commit()
                err_str = str(e)
                if '529' in err_str or 'overloaded' in err_str.lower():
                    flash('Image uploaded   -  AI servers are currently busy (peak hours). '
                          'Your image has been saved. Please score it from the dashboard '
                          'during off-peak hours: 6am-11am IST or 11pm-5am IST.', 'warning')
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
                    'message': ' This image has been flagged as potentially AI-generated and cannot be submitted. Only original photographs taken by you are accepted. If you believe this is an error, contact '+CONTACT_EMAIL+'.',
                    'redirect': url_for('dashboard')
                })
            if getattr(img, 'needs_review', False):
                if img.score >= 9.0:
                    msg = (f' Grandmaster score ({img.score})! Your image has been held for RAW verification. '
                           f'Check your email for a direct link to submit your RAW file within 7 days.')
                else:
                    msg = (' Your image has been held for human review before going public. '
                           'Usually resolved within 24-48 hours.')
                return jsonify({
                    'status': 'needs_review',
                    'image_id': img.id,
                    'score': img.score,
                    'tier': img.tier,
                    'message': msg,
                    'redirect': url_for('image_detail', image_id=img.id)
                })
            _next = request.args.get('next', '')
            _redir = (url_for('challenge_submit') + f'?highlight={img.id}') if _next == 'challenge' else url_for('image_detail', image_id=img.id)
            return jsonify({
                'status': 'ok',
                'image_id': img.id,
                'score': img.score,
                'tier': img.tier,
                'redirect': _redir
            })
        # If user came from challenge submit page, send them back there
        next_page = request.args.get('next', '')
        if next_page == 'challenge':
            return redirect(url_for('challenge_submit') + f'?highlight={img.id}')
        return redirect(url_for('image_detail', image_id=img.id))

    return render_template('upload.html', genres=GENRE_IDS, genre_choices=GENRE_CHOICES,
                           next_page=request.args.get('next', ''))


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

        flash(f'Scored! LL-Score: {img.score}  -  {img.tier}', 'success')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[retry_score] {traceback.format_exc()}')
        err = str(e)
        if '529' in err or 'overloaded' in err.lower():
            flash('AI engine is busy right now. Try again during off-peak hours: 6am-11am IST or 11pm-5am IST.', 'warning')
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
            'meta': f"{img.genre}  .  {img.format}  .  {img.subject}  .  {img.location}",
            'score': str(final_score), 'tier': tier, 'dec': archetype,
            'credit': img.photographer_name,
            'genre_tag': f"{img.genre.upper()}  .  {img.format}",
            'soul_bonus': soul_bonus, 'iucn_tag': iucn_tag or None,
            'modules': [('DoD',dod),('VD',disruption),('DM',dm),('WF',wonder),('AQ',aq)],
            'rows': [
                ('Depth of\nDifficulty', request.form.get('row_technical','')),
                ('Visual\nDisruption',   request.form.get('row_geometric','')),
                ('Decisive\nMoment',     request.form.get('row_dm','')),
                ('Wonder\nFactor',       request.form.get('row_wonder','')),
                ('AQ  -  Soul',            request.form.get('row_aq','')),
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
        flash(f'Scored! LL-Score: {final_score}  -  {tier}', 'success')
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
        ('DoD', img.dod_score),
        ('VD',  img.disruption_score),
        ('DM',  img.dm_score),
        ('WF',  img.wonder_score),
        ('AQ',  img.aq_score),
    ] if v and float(v) > 0]

    card_data = {
        'score':         img.score,
        'tier':          img.tier or '',
        'asset':         img.asset_name or img.original_filename or 'Untitled',
        'meta':          '  .  '.join(filter(None,[img.genre,img.format,img.location])),
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
            'Content-Disposition': f'inline; filename="ShutterLeague_{clean}_RatingCard.pdf"',
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

    # Top Photographers  -  grouped by user_id, sorted by avg_score DESC
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

    all_tiers = ['Rookie', 'Shooter', 'Contender', 'Craftsman', 'Maverick', 'Master', 'Grandmaster', 'Legend']

    # -- Camera rankings (lazy  -  only computed for Cameras tab) ---------------
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

    # -- Lens rankings (lazy  -  only computed for Lenses tab) ------------------
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

    admin_q    = request.args.get('q', '').strip()
    admin_page = request.args.get('page', 1, type=int)
    img_query  = Image.query.order_by(Image.created_at.desc())
    if admin_q:
        img_query = img_query.join(User, User.id == Image.user_id).filter(
            db.or_(
                Image.asset_name.ilike(f'%{admin_q}%'),
                Image.original_filename.ilike(f'%{admin_q}%'),
                Image.genre.ilike(f'%{admin_q}%'),
                User.username.ilike(f'%{admin_q}%'),
                User.full_name.ilike(f'%{admin_q}%'),
            )
        )
    recent_pages = img_query.paginate(page=admin_page, per_page=40, error_out=False)
    recent       = recent_pages.items
    user_ids     = list({img.user_id for img in recent if img.user_id})
    recent_users = {u.id: u.username for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
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
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg score {s["avg_score"]}  -  possible under-scoring'})
        elif s['avg_score'] > 8.5:
            drift_alerts.append({'genre': genre_key, 'type': 'high', 'msg': f'Avg score {s["avg_score"]}  -  possible over-scoring'})
        if s['avg_dod'] < 3.0:
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg DoD {s["avg_dod"]}  -  engine may be under-valuing difficulty'})
        if s['avg_aq'] < 4.0:
            drift_alerts.append({'genre': genre_key, 'type': 'low', 'msg': f'Avg AQ {s["avg_aq"]}  -  low emotional resonance scores across genre'})

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

    # Active contest banners — shown in admin dashboard for visibility
    active_contest_banners = ContestAnnouncement.query.filter_by(banner_active=True).all()

    return render_template('admin.html', total_users=total_users, total_images=total_images,
                           scored=scored, pending=pending, recent=recent,
                           recent_pages=recent_pages, admin_q=admin_q, recent_users=recent_users,
                           cal_stats=cal_stats, cal_trend=cal_trend, drift_alerts=drift_alerts,
                           all_users=all_users, open_reports_count=open_reports_count,
                           suspended_users=suspended_users, mismatch_users=mismatch_users,
                           stats=stats_sub,
                           active_contest_banners=active_contest_banners)


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


@app.route('/image/<int:image_id>/delete', methods=['POST'])
@login_required
def delete_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)

    # Collect R2 keys before DB delete
    r2_keys = []
    for url_attr in ['thumb_url', 'card_url']:
        url = getattr(img, url_attr, None)
        if url:
            try:
                r2_keys.append(url.split(r2.R2_PUBLIC_URL + '/')[-1])
            except Exception:
                pass

    # Direct SQL deletes — instant, no ORM cascade
    iid = image_id
    for sql in [
        "DELETE FROM raw_submissions      WHERE image_id = :iid",
        "DELETE FROM weekly_submissions   WHERE image_id = :iid",
        "DELETE FROM contest_entries      WHERE image_id = :iid",
        "DELETE FROM open_contest_entries WHERE image_id = :iid",
        "DELETE FROM image_reports        WHERE image_id = :iid",
        "DELETE FROM rating_assignments   WHERE image_id = :iid",
        "DELETE FROM peer_ratings         WHERE image_id = :iid",
        "DELETE FROM peer_pool_entries    WHERE image_id = :iid",
        "DELETE FROM brand_entries        WHERE image_id = :iid",
        "DELETE FROM calibration_notes    WHERE image_id = :iid",
        "DELETE FROM judge_assignments    WHERE image_id = :iid",
        "DELETE FROM judge_scores         WHERE image_id = :iid",
    ]:
        try:
            db.session.execute(db.text(sql), {'iid': iid})
        except Exception:
            pass

    db.session.execute(db.text("DELETE FROM images WHERE id = :iid AND user_id = :uid"),
                       {'iid': iid, 'uid': current_user.id})
    db.session.commit()

    # R2 cleanup in background — does not block user
    if r2_keys:
        import threading
        def _cleanup(keys):
            for k in keys:
                try:
                    r2.delete_file(k)
                except Exception:
                    pass
        threading.Thread(target=_cleanup, args=(r2_keys,), daemon=True).start()

    flash('Image deleted. Your scores and contest standings have been updated accordingly.', 'warning')
    return redirect(url_for('dashboard'))


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
    try:
        db.session.execute(db.text("DELETE FROM raw_submissions WHERE image_id = :iid"), {'iid': image_id})
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
    db.session.execute(db.text("DELETE FROM raw_submissions WHERE image_id IN (SELECT id FROM images WHERE thumb_url IS NULL)"))
    db.session.execute(db.text("DELETE FROM image_reports WHERE image_id IN (SELECT id FROM images WHERE thumb_url IS NULL)"))
    db.session.execute(db.text("DELETE FROM rating_assignments WHERE image_id IN (SELECT id FROM images WHERE thumb_url IS NULL)"))
    db.session.execute(db.text("DELETE FROM peer_ratings WHERE image_id IN (SELECT id FROM images WHERE thumb_url IS NULL)"))
    db.session.execute(db.text("DELETE FROM peer_pool_entries WHERE image_id IN (SELECT id FROM images WHERE thumb_url IS NULL)"))
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
            try:
                db.session.execute(db.text("DELETE FROM raw_submissions WHERE image_id = :iid"), {'iid': img.id})
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
                        'message': 'API busy  -  saved for later scoring'
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
        flash(f'No images to transfer  -  all images credited to "{photographer}" already belong to their account.', 'info')
        return redirect(url_for('admin_dashboard'))

    for img in images:
        img.user_id = target_user.id
    db.session.commit()

    flash(f' Transferred {len(images)} image{"s" if len(images)>1 else ""} to {target_user.full_name or target_user.username}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/flag', methods=['POST'])
@login_required
@admin_required
def admin_flag_image(image_id):
    """Flag an image as AI-generated  -  hides from public, keeps in DB for ML."""
    img    = Image.query.get_or_404(image_id)
    reason = request.form.get('reason', 'Manually flagged as AI-generated by admin').strip()
    img.is_flagged     = True
    img.needs_review   = True
    img.is_public      = False
    img.flagged_reason = reason
    img.flagged_at     = datetime.utcnow()
    img.score          = 0.0
    img.tier           = 'Rookie'
    db.session.commit()
    try:
        _u = User.query.get(img.user_id)
        _uname = (_u.full_name or _u.username) if _u else 'Photographer'
        send_email(
            to_addresses=[_u.email] if _u else [],
            subject='[Shutter League] Image Removed — Policy Violation',
            html_body=('<p>Hi ' + _uname + ',</p><p>Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has been removed. Reason: ' + reason + '</p><p>Contact <a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a> if this is an error.</p><p>The Shutter League Team</p>'),
            text_body=('Hi ' + _uname + ',\n\nYour image "' + (img.asset_name or 'Untitled') + '" has been removed.\nReason: ' + reason + '\nContact ' + CONTACT_EMAIL + ' if this is an error.\n\nThe Shutter League Team')
        )
    except Exception as _me:
        app.logger.error(f'[admin flag email error] {_me}')
    flash(f'Image "{img.asset_name}" flagged and hidden from public view.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/unflag', methods=['POST'])
@login_required
@admin_required
def admin_unflag_image(image_id):
    """Unflag an image  -  returns it to normal visibility."""
    img = Image.query.get_or_404(image_id)
    img.is_flagged     = False
    img.needs_review   = False
    img.is_public      = True
    img.flagged_reason = None
    img.flagged_at     = None
    db.session.commit()
    try:
        _u = User.query.get(img.user_id)
        _uname = (_u.full_name or _u.username) if _u else 'Photographer'
        _iurl = f'https://shutterleague.com/image/{img.id}'
        send_email(
            to_addresses=[_u.email] if _u else [],
            subject='[Shutter League] Your Image Has Been Restored',
            html_body=('<p>Hi ' + _uname + ',</p><p>Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has been restored to public view.</p><p><a href="' + _iurl + '">View your image</a></p><p>The Shutter League Team</p>'),
            text_body=('Hi ' + _uname + ',\n\nYour image "' + (img.asset_name or 'Untitled') + '" has been restored to public view.\nView: ' + _iurl + '\n\nThe Shutter League Team')
        )
    except Exception as _me:
        app.logger.error(f'[unflag email error] {_me}')
    flash(f'Image "{img.asset_name}" unflagged and restored to public view.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/approve-review', methods=['POST'])
@login_required
@admin_required
def admin_approve_review(image_id):
    """Clear the needs_review flag  -  approves image for public display."""
    img = Image.query.get_or_404(image_id)
    img.needs_review   = False
    img.is_public      = True
    img.flagged_reason = None
    db.session.commit()
    try:
        _u = User.query.get(img.user_id)
        _uname = (_u.full_name or _u.username) if _u else 'Photographer'
        _iurl = f'https://shutterleague.com/image/{img.id}'
        send_email(
            to_addresses=[_u.email] if _u else [],
            subject='[Shutter League] Your Image Is Now Live',
            html_body=('<p>Hi ' + _uname + ',</p><p>Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has passed review and is now live.</p><p>Score: <strong>' + str(img.score) + '</strong> — ' + (img.tier or '') + '</p><p><a href="' + _iurl + '">View your image</a></p><p>The Shutter League Team</p>'),
            text_body=('Hi ' + _uname + ',\n\nYour image "' + (img.asset_name or 'Untitled') + '" is now live.\nScore: ' + str(img.score) + ' — ' + (img.tier or '') + '\nView: ' + _iurl + '\n\nThe Shutter League Team')
        )
    except Exception as _me:
        app.logger.error(f'[approve review email error] {_me}')
    flash(f'Image "{img.asset_name}" approved  -  now visible to public.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/image/<int:image_id>/reject-review', methods=['POST'])
@login_required
@admin_required
def admin_reject_review(image_id):
    """Reject RAW verification — image remains hidden, user notified."""
    img    = Image.query.get_or_404(image_id)
    reason = request.form.get('reason', 'RAW file not provided or did not match submitted image.').strip()
    img.needs_review   = True
    img.is_public      = False
    img.is_flagged     = True
    img.flagged_reason = 'RAW verification rejected: ' + reason
    img.flagged_at     = datetime.utcnow()
    img.score          = 0.0
    img.tier           = 'Rookie'
    db.session.commit()
    try:
        _u = User.query.get(img.user_id)
        _uname = (_u.full_name or _u.username) if _u else 'Photographer'
        send_email(
            to_addresses=[_u.email] if _u else [],
            subject='[Shutter League] RAW Verification — Image Removed',
            html_body=('<p>Hi ' + _uname + ',</p><p>Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> did not pass RAW verification and has been removed. Reason: ' + reason + '</p><p>Contact <a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a> if this is an error.</p><p>The Shutter League Team</p>'),
            text_body=('Hi ' + _uname + ',\n\nYour image "' + (img.asset_name or 'Untitled') + '" did not pass RAW verification.\nReason: ' + reason + '\nContact ' + CONTACT_EMAIL + ' if this is an error.\n\nThe Shutter League Team')
        )
    except Exception as _me:
        app.logger.error(f'[reject review email error] {_me}')
    flash(f'Image "{img.asset_name}" rejected — user notified.', 'warning')
    return redirect(request.referrer or url_for('admin_dashboard'))



# -- Community Report Routes ---------------------------------------------------

@app.route('/image/<int:image_id>/report', methods=['POST'])
@login_required
def report_image(image_id):
    """Submit a community report on a scored image."""
    img = Image.query.get_or_404(image_id)

    # Determine safe redirect  -  reporter may not own the image so image_detail would 403
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

    # Notify admin by email
    reporter_name = current_user.full_name or current_user.username
    img_owner = User.query.get(img.user_id)
    owner_name = img_owner.username if img_owner else 'unknown'
    subject = 'Image Flagged by User — ' + reason
    html_body = (
        '<h2 style="color:#c0392b;">Image Report Filed</h2>'
        '<p><strong>Reporter:</strong> ' + reporter_name + ' (ID ' + str(current_user.id) + ')</p>'
        '<p><strong>Image:</strong> ' + (img.asset_name or 'Untitled') + ' (ID ' + str(img.id) + ')</p>'
        '<p><strong>Owner:</strong> ' + owner_name + '</p>'
        '<p><strong>Reason:</strong> ' + reason + '</p>'
        '<p><strong>Detail:</strong> ' + (detail or '—') + '</p>'
        '<p><a href="https://shutterleague.com/sree-admin" style="background:#c0392b;color:#fff;padding:10px 20px;'
        'text-decoration:none;font-weight:700;border-radius:4px;">Review in Admin</a></p>'
    )
    try:
        import threading
        threading.Thread(
            target=send_email,
            args=([ADMIN_NOTIFY_EMAIL], subject, html_body),
            daemon=True
        ).start()
    except Exception:
        pass

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
    # Notify the image owner
    _owner = User.query.get(img.user_id)
    if _owner:
        _uname  = _owner.full_name or _owner.username
        _ititle = img.asset_name or 'Untitled'
        try:
            import threading
            threading.Thread(
                target=send_email,
                args=(
                    [_owner.email],
                    '[Shutter League] RAW File Requested for Your Image',
                    '<p>Hi ' + _uname + ',</p>'
                    '<p>Your image <strong>' + _ititle + '</strong> has been held for review following a community report.</p>'
                    '<p>To complete verification, please email your original RAW file to '
                    '<a href="mailto:' + CONTACT_EMAIL + '">' + CONTACT_EMAIL + '</a> within <strong>7 days</strong>.</p>'
                    '<p>Your image will remain hidden from public view until the review is complete.</p>'
                    '<p>If you believe this is an error, reply to this email and we will look into it.</p>'
                    '<p>The Shutter League Team</p>'
                ),
                daemon=True
            ).start()
        except Exception:
            pass
    flash(f'RAW requested for "{img.asset_name}"  -  image held for review.', 'success')
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
    tier_order = ['Legend', 'Grandmaster', 'Master', 'Maverick', 'Craftsman', 'Contender', 'Shooter', 'Rookie']
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

@app.route('/poty')
def poty():
    return render_template('poty.html')

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/shipping-policy')
def shipping_policy():
    return render_template('shipping_policy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/refund-policy')
def refund_policy():
    return render_template('refund_policy.html')

@app.route('/robots.txt')
def robots_txt():
    content = (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /sree-admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /profile\n"
        "Disallow: /upload\n"
        "Disallow: /bulk-upload\n"
        "Disallow: /rate\n"
        "Disallow: /raw\n"
        "Disallow: /judge\n"
        "Disallow: /subscribe\n"
        "Disallow: /subscription\n"
        "Crawl-delay: 10\n"
        "\n"
        "# Automated scraping, bulk harvesting, and data extraction are\n"
        "# strictly prohibited. See /terms for full legal restrictions.\n"
    )
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name    = request.form.get('name',    '').strip()
        email   = request.form.get('email',   '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        # Basic validation
        if not name or not email or not subject or not message:
            flash('Please fill in all fields.', 'error')
            return render_template('contact.html',
                                   form_name=name, form_email=email,
                                   form_subject=subject, form_message=message)

        if len(message) > 3000:
            flash('Message is too long (max 3000 characters).', 'error')
            return render_template('contact.html',
                                   form_name=name, form_email=email,
                                   form_subject=subject, form_message=message)

        # Simple rate limit — one submission per session per 60 seconds
        import time as _time
        last_sent = session.get('contact_last_sent', 0)
        if _time.time() - last_sent < 60:
            flash('Please wait a moment before sending another message.', 'warning')
            return render_template('contact.html',
                                   form_name=name, form_email=email,
                                   form_subject=subject, form_message=message)

        # Build and send email to admin
        html_body = (
            f'<h2 style="color:#B8892A;">Contact Form — {PLATFORM_NAME}</h2>'
            f'<table style="border-collapse:collapse; font-family:Arial,sans-serif; font-size:15px;">'
            f'<tr><td style="padding:8px 16px 8px 0; color:#8A8478; font-weight:600;">FROM</td>'
            f'<td style="padding:8px 0;">{name} &lt;{email}&gt;</td></tr>'
            f'<tr><td style="padding:8px 16px 8px 0; color:#8A8478; font-weight:600;">SUBJECT</td>'
            f'<td style="padding:8px 0;">{subject}</td></tr>'
            f'</table>'
            f'<hr style="border:none; border-top:1px solid #E0D8C8; margin:20px 0;">'
            f'<p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.7; color:#1a1a18;">'
            f'{message.replace(chr(10), "<br>")}</p>'
            f'<hr style="border:none; border-top:1px solid #E0D8C8; margin:20px 0;">'
            f'<p style="font-size:13px; color:#8A8478;">Reply directly to {email}</p>'
        )
        text_body = f'From: {name} <{email}>\nSubject: {subject}\n\n{message}'

        admin_to = ADMIN_NOTIFY_EMAIL
        mail_subject = f'[{PLATFORM_NAME}] Contact: {subject}'

        ok = send_email(admin_to, mail_subject, html_body, text_body)

        if ok:
            session['contact_last_sent'] = _time.time()
            flash('Your message has been sent. We respond within 2 working days.', 'success')
            return render_template('contact.html')
        else:
            app.logger.error(f'[contact] Failed to send contact email from {email}')
            flash('Message could not be sent right now. Please email us directly at '
                  + CONTACT_EMAIL + '.', 'error')
            return render_template('contact.html',
                                   form_name=name, form_email=email,
                                   form_subject=subject, form_message=message)

    return render_template('contact.html')

@app.route('/contest-rules')
def contest_rules():
    return render_template('contest_rules.html')


@app.route('/notify-me', methods=['POST'])
def notify_me():
    email   = request.form.get('email', '').strip()
    subject = request.form.get('subject', 'Early access notification')
    if email:
        try:
            # Log to contact table or just flash and redirect
            app.logger.info(f'[notify-me] {email} — {subject}')
            # Send email notification to admin
            _send_email(
                to=os.getenv('ADMIN_EMAIL', 'admin@shutterleague.com'),
                subject=f'Early Access Request: {subject}',
                body=f'Email: {email}\nSubject: {subject}'
            )
        except Exception as e:
            app.logger.error(f'[notify-me] error: {e}')
    flash('Got it! We will notify you as soon as payments go live.', 'success')
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('index'))


@app.route('/learning')
def learning():
    return render_template('learning.html',
                           learning_limit=LEARNING_IMAGE_LIMIT)

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

        flash(f' Your Body of Work "{series_title}" has been submitted successfully  -  {len(selected_ids)} images. Jury evaluation will begin after Month 11 submissions close.', 'success')
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
        flash(' Your contest access is suspended due to league mismatches. Contact '+CONTACT_EMAIL+' to resolve.', 'error')
        return redirect(url_for('poty'))

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
            flash(f'"{img.asset_name}" entered into {GENRE_LABELS.get(genre, genre)}  -  {track.title()} Track . {now.strftime("%B %Y")}.', 'success')

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

    # Step 1  -  GET: show genre + image selector
    # Step 2  -  POST confirm=0: show summary (genre + image + 50)
    # Step 3  -  POST confirm=1: write to DB (dummy payment gate)

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
            # Step 3  -  write to DB (dummy payment confirmed)
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
                flash(f' Entry confirmed! "{img.asset_name}" is entered in {GENRE_LABELS.get(genre, genre)}  -  Open Competition {platform_year}.', 'success')
                return redirect(url_for('contests'))
            except Exception:
                db.session.rollback()
                flash('Entry already exists for this genre, or a database error occurred.', 'error')
                return redirect(url_for('contests'))
        else:
            # Step 2  -  show summary for confirmation
            return render_template('open_contest_enter.html',
                user_images=user_images, genres=GENRE_IDS,
                genre_labels=GENRE_LABELS, entered_genres=entered_genres,
                step=2, selected_genre=genre, selected_image=img,
                platform_year=platform_year)

    # GET  -  Step 1
    return render_template('open_contest_enter.html',
        user_images=user_images, genres=GENRE_IDS,
        genre_labels=GENRE_LABELS, entered_genres=entered_genres,
        step=1, platform_year=platform_year)




# ===========================================================================
# Weekly Challenge
# ===========================================================================

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
    """Public challenge page  -  visible to all, submit requires login."""
    challenge = _get_active_challenge()
    if not challenge:
        return render_template('challenge.html', challenge=None,
                               submissions=[], user_subs=[], slots_used=0,
                               slot_limit=0, can_submit=False)

    # Top submissions for display  -  all submissions ranked by score
    # is_subscriber flag controls whether they compete for prizes, not visibility
    top_subs = (WeeklySubmission.query
                .filter_by(challenge_id=challenge.id)
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
        # Admin treated as subscribed for challenge slot purposes
        is_sub_or_admin = getattr(current_user, 'is_subscribed', False) or current_user.role == 'admin'
        slot_limit = 3 if is_sub_or_admin else 1
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

    is_sub     = getattr(current_user, 'is_subscribed', False) or current_user.role == 'admin'
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
            is_subscriber=getattr(current_user, 'is_subscribed', False),
        )
        db.session.add(sub)
        db.session.commit()

        flash(f'Image submitted to the challenge! {slot_limit - slots_used - 1} slot{"s" if slot_limit - slots_used - 1 != 1 else ""} remaining this week.', 'success')
        return redirect(url_for('weekly_challenge'))

    # GET  -  show image picker
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
    """Withdraw a submission  -  only allowed while challenge is still open."""
    sub = WeeklySubmission.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    if sub.challenge.is_closed:
        flash('Challenge is closed  -  submissions cannot be withdrawn.', 'error')
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
# Admin  -  Weekly Challenge management
# ---------------------------------------------------------------------------

@app.route('/admin/weekly-challenge', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_weekly_challenge():
    """
    Admin page to create and manage weekly challenges.
    GET   -  list all challenges + form to create new one.
    POST  -  create a new challenge week.
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
                opens_at  = datetime.strptime(opens_str,  '%Y-%m-%dT%H:%M') - _IST_OFFSET
                closes_at = datetime.strptime(closes_str, '%Y-%m-%dT%H:%M') - _IST_OFFSET
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
                # Fire email in background thread  -  pass ID only, re-query inside thread
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
            # Read winner rankings from form  -  rank_<sub_id> = 1|2|3
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
                            app.logger.info(f'[challenge] Resend complete  -  {sent} users notified')
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
                    ch.opens_at  = datetime.strptime(opens_str,  '%Y-%m-%dT%H:%M') - _IST_OFFSET
                if closes_str:
                    ch.closes_at = datetime.strptime(closes_str, '%Y-%m-%dT%H:%M') - _IST_OFFSET
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
                flash(f'Cannot delete {ch.week_ref}  -  it has {ch.submission_count} submission(s). Deactivate it instead.', 'error')
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
    if track not in ('camera', 'mobile', 'learning', 'mentor'):
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
        'learning': {
            'monthly': os.getenv('RAZORPAY_PLAN_LEARNING_MONTHLY', ''),
            'annual':  os.getenv('RAZORPAY_PLAN_LEARNING_ANNUAL', ''),
        },
        'mentor': {
            'monthly': os.getenv('RAZORPAY_PLAN_MENTOR_MONTHLY', ''),
            'annual':  os.getenv('RAZORPAY_PLAN_MENTOR_ANNUAL', ''),
        },
    }
    display_prices = {
        'mobile':   {'monthly': 299,  'annual': 2499},
        'camera':   {'monthly': 599,  'annual': 4999},
        'learning': {'monthly': 100,  'annual': 999},
        'mentor':   {'monthly': 999,  'annual': 9999},
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

            track_names = {
                'camera':   'Camera Track',
                'mobile':   'Mobile Track',
                'learning': 'Learning — ₹100/mo',
                'mentor':   'Human + AI Mentor',
            }
            flash(f'Welcome to {track_names.get(track, track.title())}! Your subscription is active.', 'success')
            return redirect(url_for('learning') if track in ('learning', 'mentor') else url_for('dashboard'))
        except Exception as e:
            app.logger.error(f'[subscribe] verification failed: {e}')
            flash('Payment verification failed. Please contact support if you were charged.', 'error')
            return redirect(url_for('subscribe', track=track, plan=plan))

    # GET  -  create Razorpay subscription
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

    track_labels = {
        'camera':   'Camera Track',
        'mobile':   'Mobile Track',
        'learning': 'Learning Only',
        'mentor':   'Human + AI Mentor',
    }
    track_descriptions = {
        'camera':   'Unlimited uploads · POTY · Contests',
        'mobile':   'Unlimited uploads · POTY · Contests',
        'learning': '12 scored images/month · AI mentor · Improvement paths',
        'mentor':   '12 scored images/month · Weekly 1-on-1 · Human + AI',
    }
    return render_template('subscribe.html',
        track=track, plan=plan, amount=amount,
        subscription=subscription,
        razorpay_key=razorpay_key,
        track_label=track_labels.get(track, track.title()),
        track_description=track_descriptions.get(track, ''),
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
    GET   -  confirmation page (user must confirm before cancelling)
    POST  -  actually cancel: call Razorpay API, clear DB fields, redirect to dashboard
    RBI / Razorpay compliance: user must be able to self-cancel without contacting support.
    """
    if request.method == 'GET':
        return render_template('cancel_subscription.html')

    # POST  -  confirmed cancellation
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
            # Still cancel locally  -  don't leave user stuck
            flash('Your subscription has been cancelled. If you continue to be charged, contact '+CONTACT_EMAIL+'.', 'warning')

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
    if current_user.role != 'admin':
        abort(403)
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
                    if sim >= 98.0:
                        if ex.user_id == current_user.id:
                            result_row['status'] = f'duplicate: already uploaded as "{ex.asset_name or ex.original_filename}"'
                        else:
                            result_row['status'] = 'unable to accept: image may already exist in our database — contact info@shutterleague.com if you believe this is an error'
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

    # Server-side time check  -  must be 13s (2s tolerance for network)
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
        flash(f'Rating submitted! Peer LL-Score: {rating.peer_ll_score} . +1 credit earned.', 'success')
        if (current_user.lifetime_ratings_given or 0) % 5 == 0:
            flash(' You\'ve unlocked a peer pool entry! Go to your dashboard to choose an image to submit for peer rating.', 'info')

        # Zone notifications
        img = assignment.image
        photographer = User.query.get(img.user_id) if img else None
        if img and photographer:
            if img.needs_review and img.judge_referral and img.peer_avg_score is not None:
                delta = abs((img.peer_avg_score or 0) - (img.score or 0))
                # Zone 3 - notify photographer
                try:
                    send_email(
                        photographer.email,
                        'Your image is under peer review - Shutter League',
                        f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                        f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#B8892A;">Shutter League</p>'
                        f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">Peer Review Triggered</h2>'
                        f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image <strong>"{img.asset_name or "Untitled"}"</strong> has received peer ratings that diverge significantly from its DDI score. Your DDI score of <strong style="color:#B8892A;">{img.score}</strong> is protected and unchanged.</p>'
                        f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">This image has been referred to our jury for review. You will be notified once the review is complete. No action is required from you.</p>'
                        f'<p style="font-size:14px;color:#8A8478;margin-top:24px;">Questions? Contact <a href="mailto:'+CONTACT_EMAIL+'" style="color:#B8892A;">'+CONTACT_EMAIL+'</a></p>'
                        f'</div>'
                    )
                except Exception as mail_err:
                    app.logger.error(f'[zone3 photographer email] {mail_err}')
                # Zone 3 - notify admin
                try:
                    admin_emails = _admin_notify_emails()
                    if admin_emails:
                        send_email(
                            admin_emails,
                            f'[Zone 3] Peer divergence on image #{img.id} - {img.asset_name}',
                            f'<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                            f'<p style="font-size:14px;font-weight:700;color:#C0392B;">ZONE 3 - PEER DIVERGENCE ALERT</p>'
                            f'<p style="font-size:14px;line-height:1.7;">Image: <strong>{img.asset_name or "Untitled"}</strong> (ID: {img.id})<br>'
                            f'Photographer: {photographer.username} ({photographer.email})<br>'
                            f'DDI Score: {img.score}<br>'
                            f'Peer Average: {img.peer_avg_score}<br>'
                            f'Delta: {round(delta, 2)}<br>'
                            f'Peer Rating Count: {img.peer_rating_count}<br>'
                            f'Status: needs_review=True, judge_referral=True</p>'
                            f'<p style="font-size:13px;color:#8A8478;">DDI score is protected. Blended score not applied to POTY. Jury review triggered automatically.</p>'
                            f'</div>'
                        )
                except Exception as mail_err:
                    app.logger.error(f'[zone3 admin email] {mail_err}')

            elif getattr(img, 'peer_review_pending', False) and not img.needs_review:
                # Zone 2 - notify photographer only
                try:
                    send_email(
                        photographer.email,
                        'Peer review in progress on your image - Shutter League',
                        f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                        f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#B8892A;">Shutter League</p>'
                        f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">Peer Review In Progress</h2>'
                        f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image <strong>"{img.asset_name or "Untitled"}"</strong> is receiving peer ratings that are being reviewed for consistency. Your DDI score of <strong style="color:#B8892A;">{img.score}</strong> stands and is unaffected.</p>'
                        f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">This is an automated notice. No action is required from you. The peer review process will complete automatically.</p>'
                        f'<p style="font-size:14px;color:#8A8478;margin-top:24px;">Questions? Contact <a href="mailto:'+CONTACT_EMAIL+'" style="color:#B8892A;">'+CONTACT_EMAIL+'</a></p>'
                        f'</div>'
                    )
                except Exception as mail_err:
                    app.logger.error(f'[zone2 photographer email] {mail_err}')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[submit_rating] {e}')
        flash('Submission failed. Please try again.', 'error')

    return redirect(url_for('rate'))


@app.route('/rate/skip', methods=['POST'])
@login_required
def skip_rating():
    """Skip a rating assignment  -  expires it, no credit cost."""
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

    filename = f'shutter_league_peer_ratings_{date.today().strftime("%Y%m%d")}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )




# ---------------------------------------------------------------------------
# Admin  -  Subscription view
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Admin — Contest Management (v53)
# ---------------------------------------------------------------------------

@app.route('/admin/contests', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_contests():
    """
    Contest management hub: POTY/BOW/Open period + Brand contests + Announcements.
    """
    current_year = datetime.utcnow().year

    if request.method == 'POST':
        action = request.form.get('action', '')

        # ── Save / update contest period ────────────────────────────────────
        if action == 'save_period':
            year = request.form.get('platform_year', type=int) or current_year

            def _parse_ist(field):
                val = request.form.get(field, '').strip()
                if not val:
                    return None
                try:
                    return datetime.strptime(val, '%Y-%m-%dT%H:%M') - _IST_OFFSET
                except ValueError:
                    return None

            period = ContestPeriod.query.filter_by(platform_year=year).first()
            if not period:
                period = ContestPeriod(platform_year=year, created_by=current_user.id)
                db.session.add(period)

            period.poty_opens_at        = _parse_ist('poty_opens_at')
            period.poty_closes_at       = _parse_ist('poty_closes_at')
            period.poty_status          = request.form.get('poty_status', 'upcoming')
            period.bow_entry_opens_at   = _parse_ist('bow_entry_opens_at')
            period.bow_entry_closes_at  = _parse_ist('bow_entry_closes_at')
            period.bow_judging_ends_at  = _parse_ist('bow_judging_ends_at')
            period.bow_status           = request.form.get('bow_status', 'upcoming')
            period.open_opens_at        = _parse_ist('open_opens_at')
            period.open_closes_at       = _parse_ist('open_closes_at')
            period.open_cooling_ends_at = _parse_ist('open_cooling_ends_at')
            period.open_status          = request.form.get('open_status', 'upcoming')
            period.winners_announced_at = _parse_ist('winners_announced_at')
            period.announcement_banner  = request.form.get('announcement_banner', '').strip() or None
            period.banner_active        = request.form.get('banner_active') == '1'
            db.session.commit()
            flash('Contest period saved.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Brand contest — create ──────────────────────────────────────────
        elif action == 'create_brand':
            brand_name  = request.form.get('brand_name', '').strip()
            title       = request.form.get('title', '').strip()
            brief       = request.form.get('brief', '').strip()
            prize_desc  = request.form.get('prize_desc', '').strip()
            prize_value = request.form.get('prize_value', '').strip() or None
            opens_str   = request.form.get('opens_at', '').strip()
            closes_str  = request.form.get('closes_at', '').strip()
            max_entries = request.form.get('max_entries_per_user', 3, type=int)

            if not all([brand_name, title, brief, prize_desc, opens_str, closes_str]):
                flash('All fields except prize value are required.', 'error')
                return redirect(url_for('admin_contests'))

            try:
                opens_at  = datetime.strptime(opens_str,  '%Y-%m-%dT%H:%M') - _IST_OFFSET
                closes_at = datetime.strptime(closes_str, '%Y-%m-%dT%H:%M') - _IST_OFFSET
            except ValueError:
                flash('Invalid date format.', 'error')
                return redirect(url_for('admin_contests'))

            bc = BrandContest(
                brand_name=brand_name,
                title=title,
                brief=brief,
                prize_desc=prize_desc,
                prize_value=prize_value,
                opens_at=opens_at,
                closes_at=closes_at,
                max_entries_per_user=max_entries,
                status='draft',
                created_by=current_user.id,
            )
            db.session.add(bc)
            db.session.commit()
            flash(f'Brand contest "{title}" created as draft.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Brand contest — status transitions ─────────────────────────────
        elif action in ('brand_activate', 'brand_close', 'brand_judging', 'brand_publish'):
            bc_id = request.form.get('brand_contest_id', type=int)
            bc    = BrandContest.query.get_or_404(bc_id)
            status_map = {
                'brand_activate': 'active',
                'brand_close':    'closed',
                'brand_judging':  'judging',
                'brand_publish':  'results_published',
            }
            bc.status = status_map[action]
            if action == 'brand_publish':
                bc.results_published_at = datetime.utcnow()
            db.session.commit()
            flash(f'Brand contest "{bc.title}" status updated to {bc.status}.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Announcement — create ──────────────────────────────────────────
        elif action == 'create_announcement':
            title        = request.form.get('title', '').strip()
            body         = request.form.get('body', '').strip()
            contest_type = request.form.get('contest_type', 'poty')
            audience     = request.form.get('audience', 'all')
            delivery     = request.form.get('delivery', 'both')
            cta_label    = request.form.get('cta_label', '').strip() or None
            cta_url      = request.form.get('cta_url', '').strip() or None
            banner_active= request.form.get('banner_active') == '1'

            if not title or not body:
                flash('Title and body are required.', 'error')
                return redirect(url_for('admin_contests'))

            ann = ContestAnnouncement(
                contest_type=contest_type,
                title=title,
                body=body,
                audience=audience,
                delivery=delivery,
                cta_label=cta_label,
                cta_url=cta_url,
                banner_active=banner_active,
                status='draft',
                created_by=current_user.id,
            )
            db.session.add(ann)
            db.session.commit()
            flash(f'Announcement "{title}" created.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Announcement — toggle banner ───────────────────────────────────
        elif action in ('banner_activate', 'banner_deactivate'):
            ann_id = request.form.get('announcement_id', type=int)
            ann    = ContestAnnouncement.query.get_or_404(ann_id)
            ann.banner_active = (action == 'banner_activate')
            db.session.commit()
            flash('Banner ' + ('activated.' if ann.banner_active else 'deactivated.'), 'success')
            return redirect(url_for('admin_contests'))

        # ── Announcement — send email ──────────────────────────────────────
        elif action == 'send_announcement':
            ann_id = request.form.get('announcement_id', type=int)
            ann    = ContestAnnouncement.query.get_or_404(ann_id)
            ann.status  = 'sent'
            ann.sent_at = datetime.utcnow()
            db.session.commit()

            # Fire emails in background thread — same pattern as challenge notifications
            import threading
            def _send_ann(ann_id_inner):
                with app.app_context():
                    try:
                        ann_inner = ContestAnnouncement.query.get(ann_id_inner)
                        if not ann_inner:
                            return
                        if ann_inner.audience == 'subscribers':
                            recips = User.query.filter_by(is_active=True, is_subscribed=True).all()
                        elif ann_inner.audience == 'non_subscribers':
                            recips = User.query.filter_by(is_active=True, is_subscribed=False).filter(User.role != 'admin').all()
                        else:
                            recips = User.query.filter_by(is_active=True).filter(User.role != 'admin').all()
                        sent = 0
                        for u in recips:
                            try:
                                _send_contest_announcement_email(u, ann_inner)
                                sent += 1
                            except Exception as _e:
                                app.logger.warning('[contest_ann] email failed user ' + str(u.id) + ': ' + str(_e))
                        app.logger.info('[contest_ann] sent to ' + str(sent) + ' users')
                    except Exception as _e:
                        app.logger.error('[contest_ann] thread error: ' + str(_e))
            t = threading.Thread(target=_send_ann, args=(ann_id,), daemon=True)
            t.start()
            flash('Announcement queued — emails sending in background.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Announcement — edit ───────────────────────────────────────────
        elif action == 'edit_announcement':
            ann_id   = request.form.get('announcement_id', type=int)
            ann      = ContestAnnouncement.query.get_or_404(ann_id)
            title    = request.form.get('title', '').strip()
            body     = request.form.get('body', '').strip()
            cta_label= request.form.get('cta_label', '').strip() or None
            cta_url  = request.form.get('cta_url', '').strip() or None
            audience = request.form.get('audience', ann.audience)
            delivery = request.form.get('delivery', ann.delivery)
            if not title or not body:
                flash('Title and body are required.', 'error')
                return redirect(url_for('admin_contests'))
            ann.title     = title
            ann.body      = body
            ann.cta_label = cta_label
            ann.cta_url   = cta_url
            ann.audience  = audience
            ann.delivery  = delivery
            db.session.commit()
            flash('Announcement updated.', 'success')
            return redirect(url_for('admin_contests'))

        # ── Announcement — delete ─────────────────────────────────────────
        elif action == 'delete_announcement':
            ann_id = request.form.get('announcement_id', type=int)
            ann    = ContestAnnouncement.query.get_or_404(ann_id)
            db.session.delete(ann)
            db.session.commit()
            flash('Announcement deleted.', 'success')
            return redirect(url_for('admin_contests'))

        flash('Unknown action.', 'error')
        return redirect(url_for('admin_contests'))

    # ── GET ─────────────────────────────────────────────────────────────────
    period        = ContestPeriod.query.filter_by(platform_year=current_year).first()
    brand_contests= BrandContest.query.order_by(BrandContest.created_at.desc()).all()
    announcements = ContestAnnouncement.query.order_by(ContestAnnouncement.created_at.desc()).all()

    return render_template('admin_contests.html',
        current_year=current_year,
        period=period,
        brand_contests=brand_contests,
        announcements=announcements,
        ist=_IST_OFFSET,
    )


def _send_contest_announcement_email(user, ann):
    """Send a contest announcement email to a single user via Brevo."""
    name = user.full_name or user.username
    cta_html = ''
    if ann.cta_label and ann.cta_url:
        cta_url = ann.cta_url if ann.cta_url.startswith('http') else 'https://shutterleague.com' + ann.cta_url
        cta_html = (
            '<div style="margin-top:24px;">'
            '<a href="' + cta_url + '" style="background:#F5C518; color:#000; font-weight:700; '
            'padding:12px 28px; border-radius:6px; text-decoration:none; font-size:15px;">'
            + ann.cta_label + '</a></div>'
        )
    import html as _html
    safe_title = _html.escape(ann.title)
    safe_body  = _html.escape(ann.body)
    safe_name  = _html.escape(name)
    html_body = (
        '<div style="font-family:Arial,sans-serif; max-width:600px; margin:0 auto;'
        ' background:#000; color:#fff; padding:32px; border-radius:8px;">'
        '<div style="font-family:monospace; font-size:11px; letter-spacing:3px;'
        ' color:#F5C518; text-transform:uppercase; margin-bottom:8px;">Shutter League</div>'
        '<h2 style="color:#F5C518; margin:0 0 16px 0;">' + safe_title + '</h2>'
        '<p style="color:#ccc; font-size:15px; line-height:1.6; margin:0 0 16px 0;">Hi ' + safe_name + ',</p>'
        '<div style="color:#fff; font-size:15px; line-height:1.7; white-space:pre-wrap;">' + safe_body + '</div>'
        + cta_html
        + '<p style="color:#666; font-size:12px; margin-top:32px;">You are receiving this because you are'
        ' a member of Shutter League. '
        '<a href="https://shutterleague.com/dashboard" style="color:#F5C518;">Visit your dashboard</a></p>'
        '</div>'
    )
    send_email(user.email, ann.title, html_body)


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
    filename = f'shutter_league_users_{date.today().strftime("%Y%m%d")}.csv'
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
    filename = f'shutter_league_subscriptions_{date.today().strftime("%Y%m%d")}.csv'
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
    filename = f'shutter_league_images_{date.today().strftime("%Y%m%d")}.csv'
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

    filename = f'shutter_league_camera_rankings_{date.today().strftime("%Y%m%d")}.csv'
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

    # Extract lens from exif_settings  -  format: focal . aperture . iso . shutter
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

    filename = f'shutter_league_lens_rankings_{date.today().strftime("%Y%m%d")}.csv'
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

    filename = f'shutter_league_peer_ratings_full_{date.today().strftime("%Y%m%d")}.csv'
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
# Peer Pool Entry  -  user chooses which image to submit for peer rating
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

    flash(f' "{img.asset_name}" is now in the peer rating pool. Other photographers will start rating it soon.', 'success')
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
        ' File too large. Maximum file size is 20 MB. '
        'On iPhone: share your photo and choose "Medium" size. '
        'On Samsung/Android: use Gallery -> resize before sharing.'
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
    return jsonify({'status': 'ok', 'app': 'Shutter League'}), 200


# ===========================================================================
# Jury System + RAW Verification  (v30)
# ===========================================================================

# ---------------------------------------------------------------------------
# Helper  -  judge role checker
# ---------------------------------------------------------------------------

def _get_current_judge():
    """Return judge row for current logged-in user (approved only), or None."""
    if not current_user.is_authenticated:
        return None
    return db.session.execute(
        db.text("SELECT * FROM judges WHERE user_id = :uid AND status = 'approved'"),
        {'uid': current_user.id}
    ).fetchone()


def _get_judge_by_id(judge_id):
    return db.session.execute(
        db.text("SELECT * FROM judges WHERE id = :jid"),
        {'jid': judge_id}
    ).fetchone()


def _admin_notify_emails():
    """Return list of admin notification email addresses.
    Prefers ADMIN_NOTIFY_EMAIL env var (comma-separated) over DB query,
    since the DB admin account uses a placeholder address."""
    env_emails = os.getenv('ADMIN_NOTIFY_EMAIL', '').strip()
    if env_emails:
        return [e.strip() for e in env_emails.split(',') if e.strip()]
    # Fallback: query DB (only reliable if admin user has a real email)
    return [u.email for u in User.query.filter_by(role='admin').all() if u.email]


# ---------------------------------------------------------------------------
# Judge invite + registration (token-gated)
# ---------------------------------------------------------------------------

@app.route('/admin/judges/invite', methods=['POST'])
@login_required
@admin_required
def admin_judge_invite():
    import secrets
    email = request.form.get('email', '').strip().lower()
    name  = request.form.get('name', '').strip()
    if not email:
        flash('Email is required.', 'error')
        return redirect(url_for('admin_judges'))
    existing = db.session.execute(
        db.text("SELECT id FROM judges WHERE email = :e"), {'e': email}
    ).fetchone()
    if existing:
        flash(f'A judge record for {email} already exists.', 'warning')
        return redirect(url_for('admin_judges'))
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=72)
    db.session.execute(db.text(
        "INSERT INTO judges (email, name, status, invite_token, invite_sent_at, invite_expires_at, created_at) "
        "VALUES (:e, :n, 'invited', :t, NOW(), :exp, NOW())"
    ), {'e': email, 'n': name or None, 't': token, 'exp': expires_at})
    db.session.commit()
    site_url     = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    register_url = f"{site_url}/judge/register/{token}"
    html_body = (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        f'<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F0E8;padding:32px 16px;">'
        f'<tr><td align="center">'
        f'<table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;overflow:hidden;max-width:560px;width:100%;">'
        f'<tr><td style="background:#1a1a18;padding:24px 32px;">'
        f'<p style="margin:0;font-family:\'Courier New\',monospace;font-size:13px;font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">SHUTTER LEAGUE</p>'
        f'</td></tr>'
        f'<tr><td style="padding:28px 32px;">'
        f'<h2 style="margin:0 0 16px;font-size:22px;color:#1a1a18;">You have been invited to join our jury</h2>'
        f'<p style="font-size:16px;color:#4A4840;line-height:1.7;">Dear {name or "Photographer"},</p>'
        f'<p style="font-size:16px;color:#4A4840;line-height:1.7;">We would be honoured to have you serve as a judge on Shutter League.</p>'
        f'<p style="font-size:16px;color:#4A4840;line-height:1.7;">Please complete your judge profile. This link expires in 72 hours.</p>'
        f'<a href="{register_url}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:\'Courier New\',monospace;font-size:14px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:16px 0;">Complete Judge Profile</a>'
        f'<p style="font-size:13px;color:#8a8070;margin-top:24px;">If the button does not work: {register_url}</p>'
        f'</td></tr></table></td></tr></table></body></html>'
    )
    send_email(email, 'Invitation to join the Shutter League Jury', html_body)
    flash(f'Invitation sent to {email}. Token valid 72 hours.', 'success')
    return redirect(url_for('admin_judges'))


@app.route('/judge/register/<token>', methods=['GET', 'POST'])
def judge_register(token):
    judge = db.session.execute(
        db.text("SELECT * FROM judges WHERE invite_token = :t"), {'t': token}
    ).fetchone()
    if not judge:
        abort(404)
    if judge.status not in ('invited',):
        return render_template('judge_register.html', judge=judge, token=token, already_submitted=True)
    if judge.invite_expires_at and datetime.utcnow() > judge.invite_expires_at:
        return render_template('judge_register.html', judge=judge, token=token, expired=True)

    if request.method == 'POST':
        name          = request.form.get('name', '').strip()
        phone         = request.form.get('phone', '').strip()
        address       = request.form.get('address', '').strip()
        city          = request.form.get('city', '').strip()
        country       = request.form.get('country', '').strip()
        years_exp     = request.form.get('years_experience', type=int)
        judged_before = request.form.get('judged_before') == 'yes'
        bio           = request.form.get('bio', '').strip()
        agreed        = request.form.get('agreed_terms') == '1'

        errors = []
        if not name:        errors.append('Name is required.')
        if not phone:       errors.append('Contact number is required.')
        if not address:     errors.append('Address is required.')
        if not city:        errors.append('City is required.')
        if not country:     errors.append('Country is required.')
        if not years_exp:   errors.append('Years of experience is required.')
        if not bio:         errors.append('Bio / achievements is required.')
        if len(bio) > 1800: errors.append('Bio must be 300 words or fewer.')
        if not agreed:      errors.append('You must agree to the terms to proceed.')

        photo_key  = None
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename:
            uid      = str(uuid.uuid4())
            ext      = os.path.splitext(secure_filename(photo_file.filename))[1].lower() or '.jpg'
            key      = f'judges/{uid}{ext}'
            tmp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'raw', f'{uid}{ext}')
            photo_file.save(tmp_path)
            uploaded_url = r2.upload_file(tmp_path, key, content_type='image/jpeg')
            if uploaded_url:
                photo_key = key
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        else:
            errors.append('A photo of yourself is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('judge_register.html', judge=judge, token=token, form_data=request.form)

        db.session.execute(db.text(
            "UPDATE judges SET name=:name, phone=:phone, address=:address, city=:city, "
            "country=:country, years_experience=:yrs, judged_before=:jb, bio=:bio, "
            "photo_key=:pk, agreed_terms=:ag, agreed_at=NOW(), status='pending_approval', "
            "invite_token=NULL WHERE id=:jid"
        ), {'name': name, 'phone': phone, 'address': address, 'city': city,
            'country': country, 'yrs': years_exp, 'jb': judged_before, 'bio': bio,
            'pk': photo_key, 'ag': agreed, 'jid': judge.id})
        db.session.commit()

        admin_emails = _admin_notify_emails()
        if admin_emails:
            send_email(
                admin_emails,
                f'[Jury] New judge application -- {name}',
                (f'<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-weight:700;color:#C8A84B;">NEW JUDGE APPLICATION</p>'
                 f'<p>Name: <strong>{name}</strong><br>Email: {judge.email}<br>'
                 f'City: {city}, {country}<br>Years exp: {years_exp}<br>'
                 f'Judged before: {"Yes" if judged_before else "No"}</p>'
                 f'<p><a href="{os.getenv("SITE_URL","")}/admin/judges/{judge.id}" style="color:#C8A84B;">Review application</a></p>'
                 f'</div>')
            )
        return redirect(url_for('judge_pending'))

    return render_template('judge_register.html', judge=judge, token=token)


@app.route('/judge/pending')
def judge_pending():
    return render_template('judge_pending.html')


# ---------------------------------------------------------------------------
# Judge Dashboard + Scoring
# ---------------------------------------------------------------------------

@app.route('/judge/dashboard')
@login_required
def judge_dashboard():
    judge = _get_current_judge()
    if not judge:
        abort(403)
    now     = datetime.utcnow()
    pending = db.session.execute(db.text(
        "SELECT ja.*, i.thumb_url, i.asset_name, i.genre "
        "FROM judge_assignments ja JOIN images i ON i.id = ja.image_id "
        "WHERE ja.judge_id = :jid AND ja.status = 'pending' ORDER BY ja.deadline ASC NULLS LAST"
    ), {'jid': judge.id}).fetchall()
    scored_count  = db.session.execute(db.text(
        "SELECT COUNT(*) FROM judge_assignments WHERE judge_id=:jid AND status='scored'"
    ), {'jid': judge.id}).scalar()
    flagged_count = db.session.execute(db.text(
        "SELECT COUNT(*) FROM judge_assignments WHERE judge_id=:jid AND status='flagged'"
    ), {'jid': judge.id}).scalar()
    # Flags this judge raised that admin has actioned
    resolved_flags = db.session.execute(db.text(
        "SELECT ja.id, ja.admin_flag_decision, ja.admin_flag_note, ja.admin_flag_decided_at, "
        "i.asset_name, i.genre "
        "FROM judge_assignments ja JOIN images i ON i.id = ja.image_id "
        "WHERE ja.judge_id=:jid AND ja.status='flagged' AND ja.admin_flag_decision IS NOT NULL "
        "ORDER BY ja.admin_flag_decided_at DESC LIMIT 10"
    ), {'jid': judge.id}).fetchall()

    return render_template('judge_dashboard.html',
        judge=judge, pending=pending, scored_count=scored_count,
        flagged_count=flagged_count, resolved_flags=resolved_flags, now=now)


@app.route('/judge/score/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def judge_score_image(assignment_id):
    judge = _get_current_judge()
    if not judge:
        abort(403)
    assignment = db.session.execute(db.text(
        "SELECT ja.*, i.thumb_url, i.asset_name, i.genre, ja.image_id "
        "FROM judge_assignments ja JOIN images i ON i.id = ja.image_id "
        "WHERE ja.id = :aid AND ja.judge_id = :jid"
    ), {'aid': assignment_id, 'jid': judge.id}).fetchone()
    if not assignment:
        abort(404)
    if assignment.status in ('scored', 'flagged'):
        flash('This image has already been reviewed.', 'info')
        return redirect(url_for('judge_dashboard'))

    if request.method == 'POST':
        action = request.form.get('action', 'score')

        if action == 'flag':
            flag_type  = request.form.get('flag_type', '').strip()
            flag_notes = request.form.get('flag_notes', '').strip()
            if flag_type not in ('ai_generated', 'stolen', 'technically_impossible', 'other'):
                flash('Invalid flag type.', 'error')
                return redirect(request.url)
            if flag_type == 'other' and not flag_notes:
                flash('Please describe the reason for flagging.', 'error')
                return redirect(request.url)
            db.session.execute(db.text(
                "INSERT INTO judge_scores (judge_assignment_id, judge_id, image_id, flag_type, flag_notes, submitted_at) "
                "VALUES (:aid, :jid, :iid, :ft, :fn, NOW()) "
                "ON CONFLICT (judge_assignment_id) DO UPDATE SET flag_type=:ft, flag_notes=:fn, submitted_at=NOW()"
            ), {'aid': assignment_id, 'jid': judge.id, 'iid': assignment.image_id, 'ft': flag_type, 'fn': flag_notes or None})
            db.session.execute(db.text(
                "UPDATE judge_assignments SET status='flagged' WHERE id=:aid"
            ), {'aid': assignment_id})
            db.session.execute(db.text(
                "UPDATE images SET judge_flagged=TRUE, judge_flag_type=:ft WHERE id=:iid"
            ), {'ft': flag_type, 'iid': assignment.image_id})
            db.session.commit()
            admin_emails = _admin_notify_emails()
            if admin_emails:
                send_email(
                    admin_emails,
                    f'[Jury Flag] Image #{assignment.image_id} -- {flag_type}',
                    (f'<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;">'
                     f'<p style="color:#C0392B;font-weight:700;">JURY FLAG RAISED</p>'
                     f'<p>Image: {assignment.asset_name} (ID: {assignment.image_id})<br>'
                     f'Genre: {assignment.genre}<br>Judge: {judge.name}<br>'
                     f'Flag: <strong>{flag_type}</strong><br>Notes: {flag_notes or "None"}</p></div>')
                )
            flash('Image flagged and sent to admin for review.', 'warning')
            return redirect(url_for('judge_dashboard'))

        # Score action
        try:
            dod_s    = float(request.form.get('dod_score', 0))
            dis_s    = float(request.form.get('disruption_score', 0))
            dm_s     = float(request.form.get('dm_score', 0))
            wonder_s = float(request.form.get('wonder_score', 0))
            aq_s     = float(request.form.get('aq_score', 0))
        except (ValueError, TypeError):
            flash('Invalid scores submitted.', 'error')
            return redirect(request.url)

        def _clamp(v): return max(0.0, min(10.0, round(v, 1)))
        dod_s = _clamp(dod_s); dis_s = _clamp(dis_s); dm_s = _clamp(dm_s)
        wonder_s = _clamp(wonder_s); aq_s = _clamp(aq_s)
        judge_total = round((dod_s + dis_s + dm_s + wonder_s + aq_s) / 5, 2)

        db.session.execute(db.text(
            "INSERT INTO judge_scores (judge_assignment_id, judge_id, image_id, "
            "dod_score, disruption_score, dm_score, wonder_score, aq_score, judge_total, submitted_at) "
            "VALUES (:aid, :jid, :iid, :dod, :dis, :dm, :won, :aq, :tot, NOW()) "
            "ON CONFLICT (judge_assignment_id) DO UPDATE "
            "SET dod_score=:dod, disruption_score=:dis, dm_score=:dm, "
            "wonder_score=:won, aq_score=:aq, judge_total=:tot, submitted_at=NOW()"
        ), {'aid': assignment_id, 'jid': judge.id, 'iid': assignment.image_id,
            'dod': dod_s, 'dis': dis_s, 'dm': dm_s, 'won': wonder_s, 'aq': aq_s, 'tot': judge_total})
        db.session.execute(db.text(
            "UPDATE judge_assignments SET status='scored' WHERE id=:aid"
        ), {'aid': assignment_id})

        # Update image judge_score (avg across all judges for this image)
        avg_result = db.session.execute(db.text(
            "SELECT AVG(judge_total) FROM judge_scores "
            "WHERE image_id=:iid AND judge_total IS NOT NULL AND flag_type IS NULL"
        ), {'iid': assignment.image_id}).scalar()
        if avg_result is not None:
            db.session.execute(db.text(
                "UPDATE images SET judge_score=:js WHERE id=:iid"
            ), {'js': round(float(avg_result), 2), 'iid': assignment.image_id})
        db.session.commit()

        flash('Score submitted. Thank you.', 'success')
        next_a = db.session.execute(db.text(
            "SELECT id FROM judge_assignments WHERE judge_id=:jid AND status='pending' "
            "ORDER BY deadline ASC NULLS LAST LIMIT 1"
        ), {'jid': judge.id}).fetchone()
        if next_a:
            return redirect(url_for('judge_score_image', assignment_id=next_a.id))
        return redirect(url_for('judge_dashboard'))

    ddi_descriptions = {
        'DoD':        'Depth of Detail -- technical precision, sharpness, compositional complexity',
        'Disruption': 'Disruption -- visual surprise, unconventional perspective, breaks convention',
        'DM':         'Decisive Moment -- the unrepeatable instant, timing, narrative peak',
        'Wonder':     'Wonder -- emotional impact, transcendence, the feeling it leaves',
        'AQ':         "Authenticity Quotient -- soul, honesty, the photographer's unique voice",
    }
    return render_template('judge_score.html',
        assignment=assignment, judge=judge, ddi_descriptions=ddi_descriptions)


@app.route('/judge/score/<int:assignment_id>/skip', methods=['POST'])
@login_required
def judge_skip_assignment(assignment_id):
    judge = _get_current_judge()
    if not judge:
        abort(403)
    db.session.execute(db.text(
        "UPDATE judge_assignments SET status='skipped' WHERE id=:aid AND judge_id=:jid AND status='pending'"
    ), {'aid': assignment_id, 'jid': judge.id})
    db.session.commit()
    flash('Assignment skipped. It remains in your queue.', 'info')
    return redirect(url_for('judge_dashboard'))


@app.route('/judge/history')
@login_required
def judge_history():
    judge = _get_current_judge()
    if not judge:
        abort(403)
    scored = db.session.execute(db.text(
        "SELECT ja.id, ja.image_id, ja.assigned_at, ja.deadline, ja.status, "
        "js.judge_total, js.flag_type, i.asset_name, i.genre, i.thumb_url "
        "FROM judge_assignments ja "
        "LEFT JOIN judge_scores js ON js.judge_assignment_id = ja.id "
        "JOIN images i ON i.id = ja.image_id "
        "WHERE ja.judge_id=:jid AND ja.status IN ('scored','flagged') "
        "ORDER BY js.submitted_at DESC"
    ), {'jid': judge.id}).fetchall()
    return render_template('judge_history.html', judge=judge, scored=scored)


# ---------------------------------------------------------------------------
# Admin  -  Judge Management
# ---------------------------------------------------------------------------

@app.route('/admin/judges')
@login_required
@admin_required
def admin_judges():
    judges = db.session.execute(db.text(
        "SELECT j.*, "
        "(SELECT COUNT(*) FROM judge_assignments ja WHERE ja.judge_id=j.id AND ja.status='pending') AS pending_count, "
        "(SELECT COUNT(*) FROM judge_assignments ja WHERE ja.judge_id=j.id AND ja.status='scored') AS scored_count "
        "FROM judges j ORDER BY j.created_at DESC"
    )).fetchall()
    return render_template('admin_judges.html', judges=judges, genre_ids=GENRE_IDS)


@app.route('/admin/judges/<int:judge_id>')
@login_required
@admin_required
def admin_judge_detail(judge_id):
    judge = _get_judge_by_id(judge_id)
    if not judge:
        abort(404)
    categories  = db.session.execute(db.text(
        "SELECT * FROM judge_category_assignments WHERE judge_id=:jid AND active=TRUE"
    ), {'jid': judge_id}).fetchall()
    assignments = db.session.execute(db.text(
        "SELECT ja.*, i.asset_name, i.genre, i.thumb_url, js.judge_total, js.flag_type "
        "FROM judge_assignments ja JOIN images i ON i.id = ja.image_id "
        "LEFT JOIN judge_scores js ON js.judge_assignment_id = ja.id "
        "WHERE ja.judge_id=:jid ORDER BY ja.assigned_at DESC LIMIT 50"
    ), {'jid': judge_id}).fetchall()
    photo_url = (f"{r2.R2_PUBLIC_URL}/{judge.photo_key}") if judge.photo_key else None
    return render_template('admin_judge_detail.html',
        judge=judge, categories=categories, assignments=assignments,
        photo_url=photo_url, genre_ids=GENRE_IDS)


@app.route('/admin/judges/<int:judge_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_judge_approve(judge_id):
    judge = _get_judge_by_id(judge_id)
    if not judge:
        abort(404)
    db.session.execute(db.text(
        "UPDATE judges SET status='approved', approved_at=NOW(), approved_by=:admin WHERE id=:jid"
    ), {'admin': current_user.id, 'jid': judge_id})
    # Auto-link user_id by matching judge email to users table
    db.session.execute(db.text(
        "UPDATE judges SET user_id = (SELECT id FROM users WHERE email = :email LIMIT 1) "
        "WHERE id = :jid AND user_id IS NULL"
    ), {'email': judge.email, 'jid': judge_id})
    db.session.commit()
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    send_email(
        judge.email,
        'Welcome to the Shutter League Jury',
        (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
         f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
         f'<h2>Welcome, {judge.name}.</h2>'
         f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your judge profile has been approved. You can now access your judging dashboard.</p>'
         f'<a href="{site_url}/judge/dashboard" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;">Go to Dashboard</a>'
         f'</div>')
    )
    flash(f'Judge {judge.name} approved. Welcome email sent.', 'success')
    return redirect(url_for('admin_judge_detail', judge_id=judge_id))


@app.route('/admin/judges/<int:judge_id>/suspend', methods=['POST'])
@login_required
@admin_required
def admin_judge_suspend(judge_id):
    db.session.execute(db.text("UPDATE judges SET status='suspended' WHERE id=:jid"), {'jid': judge_id})
    db.session.commit()
    flash('Judge suspended.', 'warning')
    return redirect(url_for('admin_judges'))


@app.route('/admin/judges/<int:judge_id>/assign-categories', methods=['POST'])
@login_required
@admin_required
def admin_judge_assign_categories(judge_id):
    judge = _get_judge_by_id(judge_id)
    if not judge:
        abort(404)
    db.session.execute(db.text(
        "UPDATE judge_category_assignments SET active=FALSE WHERE judge_id=:jid"
    ), {'jid': judge_id})
    categories   = request.form.getlist('categories')
    contest_type = request.form.get('contest_type', 'all')
    for cat in categories:
        if cat in GENRE_IDS:
            db.session.execute(db.text(
                "INSERT INTO judge_category_assignments "
                "(judge_id, category, contest_type, assigned_by, assigned_at, active) "
                "VALUES (:jid, :cat, :ct, :by, NOW(), TRUE)"
            ), {'jid': judge_id, 'cat': cat, 'ct': contest_type, 'by': current_user.id})
    db.session.commit()
    flash(f'Category assignments updated for {judge.name}.', 'success')
    return redirect(url_for('admin_judge_detail', judge_id=judge_id))


# ---------------------------------------------------------------------------
# Admin  -  Judge Pool Config + Population
# ---------------------------------------------------------------------------

@app.route('/admin/judge-queue')
@login_required
@admin_required
def admin_judge_queue():
    now = datetime.utcnow()
    assignments = db.session.execute(db.text(
        "SELECT ja.*, j.name AS judge_name, j.email AS judge_email, "
        "i.asset_name, i.genre, i.thumb_url, i.score AS ddi_score, "
        "js.judge_total, js.flag_type "
        "FROM judge_assignments ja JOIN judges j ON j.id=ja.judge_id "
        "JOIN images i ON i.id=ja.image_id "
        "LEFT JOIN judge_scores js ON js.judge_assignment_id=ja.id "
        "ORDER BY ja.deadline ASC NULLS LAST, ja.assigned_at DESC"
    )).fetchall()
    return render_template('admin_judge_queue.html', assignments=assignments, now=now)


@app.route('/admin/contest/judge-config', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_judge_config():
    if request.method == 'POST':
        contest_ref    = request.form.get('contest_ref', '').strip()
        contest_type   = request.form.get('contest_type', 'weekly')
        score_threshold= request.form.get('score_threshold', 8.0, type=float)
        weighting_mode = request.form.get('weighting_mode', 'tiebreaker')
        ddi_weight     = request.form.get('ddi_weight', 100, type=int)
        judge_weight   = request.form.get('judge_weight', 0, type=int)
        cooling_hours  = request.form.get('cooling_period_hours', 48, type=int)
        if weighting_mode == 'weighted' and (ddi_weight + judge_weight) != 100:
            flash('DDI weight + Judge weight must sum to 100.', 'error')
            return redirect(url_for('admin_judge_config'))
        db.session.execute(db.text(
            "INSERT INTO contest_judge_configs "
            "(contest_ref, contest_type, score_threshold, weighting_mode, "
            "ddi_weight, judge_weight, cooling_period_hours, created_by, created_at) "
            "VALUES (:cr, :ct, :st, :wm, :dw, :jw, :cp, :by, NOW()) "
            "ON CONFLICT (contest_ref, contest_type) DO UPDATE "
            "SET score_threshold=:st, weighting_mode=:wm, ddi_weight=:dw, judge_weight=:jw, cooling_period_hours=:cp"
        ), {'cr': contest_ref, 'ct': contest_type, 'st': score_threshold, 'wm': weighting_mode,
            'dw': ddi_weight, 'jw': judge_weight, 'cp': cooling_hours, 'by': current_user.id})
        db.session.commit()
        flash(f'Judge config saved for {contest_ref} ({contest_type}).', 'success')
        return redirect(url_for('admin_judge_config'))
    configs = db.session.execute(db.text(
        "SELECT * FROM contest_judge_configs ORDER BY created_at DESC"
    )).fetchall()
    return render_template('admin_judge_config.html', configs=configs, genre_ids=GENRE_IDS)


@app.route('/admin/contest/populate-judge-pool', methods=['POST'])
@login_required
@admin_required
def admin_populate_judge_pool():
    contest_ref    = request.form.get('contest_ref', '').strip()
    contest_type   = request.form.get('contest_type', 'weekly')
    threshold      = request.form.get('score_threshold', 8.0, type=float)
    deadline_hours = request.form.get('deadline_hours', 72, type=int)
    if not contest_ref:
        flash('Contest reference is required.', 'error')
        return redirect(url_for('admin_judge_config'))

    judges = db.session.execute(db.text(
        "SELECT j.id, j.name, j.email, string_agg(jca.category, ',') AS categories "
        "FROM judges j "
        "JOIN judge_category_assignments jca ON jca.judge_id=j.id AND jca.active=TRUE "
        "WHERE j.status='approved' AND (jca.contest_type='all' OR jca.contest_type=:ct) "
        "GROUP BY j.id, j.name, j.email"
    ), {'ct': contest_type}).fetchall()

    if not judges:
        flash('No approved judges with matching category assignments found.', 'warning')
        return redirect(url_for('admin_judge_config'))

    eligible = db.session.execute(db.text(
        "SELECT id, genre, score, asset_name FROM images "
        "WHERE status='scored' AND score>=:thresh "
        "AND raw_verified=TRUE "
        "AND is_flagged=FALSE AND needs_review=FALSE "
        "AND id NOT IN ("
        "  SELECT DISTINCT image_id FROM judge_assignments "
        "  WHERE contest_ref=:cr AND contest_type=:ct"
        ")"
    ), {'thresh': threshold, 'cr': contest_ref, 'ct': contest_type}).fetchall()

    if not eligible:
        flash(f'No eligible RAW-verified images above threshold {threshold}.', 'warning')
        return redirect(url_for('admin_judge_config'))

    deadline       = datetime.utcnow() + timedelta(hours=deadline_hours)
    assigned_count = 0
    site_url       = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')

    for img in eligible:
        matching = [j for j in judges if img.genre in (j.categories or '').split(',')]
        if not matching:
            continue
        for judge in matching:
            existing = db.session.execute(db.text(
                "SELECT id FROM judge_assignments WHERE judge_id=:jid AND image_id=:iid"
            ), {'jid': judge.id, 'iid': img.id}).fetchone()
            if existing:
                continue
            db.session.execute(db.text(
                "INSERT INTO judge_assignments "
                "(judge_id, image_id, contest_ref, contest_type, assigned_at, deadline, status) "
                "VALUES (:jid, :iid, :cr, :ct, NOW(), :dl, 'pending')"
            ), {'jid': judge.id, 'iid': img.id, 'cr': contest_ref, 'ct': contest_type, 'dl': deadline})
            assigned_count += 1
        # in_judge_pool kept for reference but eligibility is now per-contest
        db.session.execute(db.text("UPDATE images SET in_judge_pool=TRUE WHERE id=:iid"), {'iid': img.id})

    db.session.execute(db.text(
        "UPDATE contest_judge_configs SET pool_populated_at=NOW() "
        "WHERE contest_ref=:cr AND contest_type=:ct"
    ), {'cr': contest_ref, 'ct': contest_type})
    db.session.commit()

    for judge in judges:
        pending_count = db.session.execute(db.text(
            "SELECT COUNT(*) FROM judge_assignments WHERE judge_id=:jid AND status='pending'"
        ), {'jid': judge.id}).scalar()
        if pending_count:
            send_email(
                judge.email,
                f'[Shutter League Jury] {pending_count} image(s) assigned for {contest_ref}',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League  --  Jury</p>'
                 f'<h2 style="font-size:20px;">New images assigned</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">You have <strong>{pending_count} image(s)</strong> for <strong>{contest_ref}</strong>.<br>'
                 f'Deadline: <strong>{deadline.strftime("%d %B %Y, %H:%M UTC")}</strong> -- <strong style="color:#C8A84B;">{deadline_hours} hours from now</strong></p>'
                 f'<p style="font-size:15px;color:#C0392B;line-height:1.6;">Please complete all assigned images before the deadline. Late submissions cannot be accepted.</p>'
                 f'<a href="{site_url}/judge/dashboard" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">Open Dashboard</a>'
                 f'</div>')
            )
    flash(f'Pool populated: {assigned_count} assignments across {len(judges)} judge(s).', 'success')
    return redirect(url_for('admin_judge_config'))


@app.route('/admin/contest/publish-results', methods=['POST'])
@login_required
@admin_required
def admin_publish_results():
    contest_ref  = request.form.get('contest_ref', '').strip()
    contest_type = request.form.get('contest_type', 'weekly')

    # Block compute if unreviewed flags exist for this contest
    unreviewed_flags = db.session.execute(db.text(
        "SELECT COUNT(*) FROM judge_assignments "
        "WHERE contest_ref=:cr AND contest_type=:ct AND status='flagged' AND admin_flag_decision IS NULL"
    ), {'cr': contest_ref, 'ct': contest_type}).scalar() or 0
    if unreviewed_flags:
        flash(
            f'{unreviewed_flags} flagged image(s) in this contest have not been reviewed by admin. '
            f'Go to the Judge Queue, resolve all flags (Disqualify or Override), then compute results.',
            'error'
        )
        return redirect(url_for('admin_judge_config'))

    config = db.session.execute(db.text(
        "SELECT * FROM contest_judge_configs WHERE contest_ref=:cr AND contest_type=:ct"
    ), {'cr': contest_ref, 'ct': contest_type}).fetchone()
    cooling_hours  = config.cooling_period_hours if config else 48
    publish_at     = datetime.utcnow() + timedelta(hours=cooling_hours)
    weighting_mode = config.weighting_mode if config else 'tiebreaker'
    ddi_w          = (config.ddi_weight   / 100.0) if config else 1.0
    judge_w        = (config.judge_weight / 100.0) if config else 0.0

    images_in_pool = db.session.execute(db.text(
        "SELECT DISTINCT ja.image_id FROM judge_assignments ja "
        "WHERE ja.contest_ref=:cr AND ja.contest_type=:ct AND ja.status='scored'"
    ), {'cr': contest_ref, 'ct': contest_type}).fetchall()

    for row in images_in_pool:
        img = Image.query.get(row.image_id)
        if not img or not img.score:
            continue
        final = round(ddi_w * img.score + judge_w * img.judge_score, 2) \
            if (weighting_mode == 'weighted' and img.judge_score is not None) else img.score
        db.session.execute(db.text(
            "UPDATE images SET judge_final_score=:fs, contest_result_status='provisional' WHERE id=:iid"
        ), {'fs': final, 'iid': row.image_id})

    db.session.execute(db.text(
        "UPDATE contest_judge_configs SET results_emailed_at=NOW() WHERE contest_ref=:cr AND contest_type=:ct"
    ), {'cr': contest_ref, 'ct': contest_type})
    db.session.commit()
    flash(
        f'Results computed for {contest_ref}. Cooling: {cooling_hours}hrs. '
        f'Use Go Live when ready (after {publish_at.strftime("%d %b %H:%M UTC")}).',
        'success'
    )
    return redirect(url_for('admin_judge_config'))


@app.route('/admin/contest/go-live', methods=['POST'])
@login_required
@admin_required
def admin_contest_go_live():
    contest_ref  = request.form.get('contest_ref', '').strip()
    contest_type = request.form.get('contest_type', 'weekly')
    db.session.execute(db.text(
        "UPDATE images SET contest_result_status='published' "
        "WHERE contest_result_status='provisional' "
        "AND id IN (SELECT DISTINCT image_id FROM judge_assignments WHERE contest_ref=:cr AND contest_type=:ct)"
    ), {'cr': contest_ref, 'ct': contest_type})
    db.session.execute(db.text(
        "UPDATE contest_judge_configs SET leaderboard_published_at=NOW() WHERE contest_ref=:cr AND contest_type=:ct"
    ), {'cr': contest_ref, 'ct': contest_type})
    db.session.commit()

    # Email winners -- top 3 by judge_final_score for this contest
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    winners = db.session.execute(db.text(
        "SELECT i.id, i.asset_name, i.genre, i.judge_final_score, i.user_id "
        "FROM images i "
        "JOIN judge_assignments ja ON ja.image_id = i.id "
        "WHERE ja.contest_ref=:cr AND ja.contest_type=:ct "
        "AND i.contest_result_status='published' AND i.judge_final_score IS NOT NULL "
        "GROUP BY i.id, i.asset_name, i.genre, i.judge_final_score, i.user_id "
        "ORDER BY i.judge_final_score DESC LIMIT 3"
    ), {'cr': contest_ref, 'ct': contest_type}).fetchall()

    ordinals = {1: '1st', 2: '2nd', 3: '3rd'}
    for rank, row in enumerate(winners, 1):
        photographer = User.query.get(row.user_id)
        if not photographer:
            continue
        send_email(
            photographer.email,
            f'🏆 You placed {ordinals[rank]} in {contest_ref} -- Shutter League',
            (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
             f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
             f'<h2 style="font-size:24px;font-weight:700;margin-bottom:8px;">Congratulations, {photographer.full_name or photographer.username}!</h2>'
             f'<p style="font-size:18px;color:#4A4840;line-height:1.7;">Your image <strong>"{row.asset_name}"</strong> ({row.genre}) has placed <strong style="color:#C8A84B;">{ordinals[rank]}</strong> in <strong>{contest_ref}</strong>.</p>'
             f'<p style="font-size:16px;color:#4A4840;line-height:1.7;">The results are now live on the leaderboard.</p>'
             f'<a href="{site_url}/leaderboard" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">View Leaderboard →</a>'
             f'</div>')
        )

    flash(f'Leaderboard published for {contest_ref}. Results are now live. {len(winners)} winner(s) notified by email.', 'success')
    return redirect(url_for('admin_judge_config'))


# ---------------------------------------------------------------------------
# RAW Verification  -  contestant submission
# ---------------------------------------------------------------------------
# RAW presigned upload — browser uploads directly to R2, bypassing Gunicorn
# ---------------------------------------------------------------------------

@app.route('/raw/presign/<int:image_id>')
@login_required
def raw_presign(image_id):
    """Return a presigned R2 PUT URL for direct browser upload."""
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)
    filename = request.args.get('filename', 'raw_file.bin')
    filename = secure_filename(filename)
    key = f'raw_submissions/{str(uuid.uuid4())}_{filename}'
    presigned_url = r2.generate_presigned_put(key, expires=900)
    if not presigned_url:
        return jsonify({'error': 'Could not generate upload URL'}), 500
    return jsonify({'url': presigned_url, 'key': key})


@app.route('/raw/confirm/<contest_type>/<int:image_id>', methods=['POST'])
@login_required
def raw_confirm(contest_type, image_id):
    """Called by browser after direct R2 upload completes. Records submission and fires analysis."""
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)
    raw_file_key = request.form.get('key', '').strip()
    raw_link     = request.form.get('raw_link', '').strip()
    method       = request.form.get('method', 'upload')
    contest_ref  = request.form.get('contest_ref', '')
    if method == 'upload' and not raw_file_key:
        return jsonify({'error': 'Missing file key'}), 400
    if method == 'link' and not raw_link:
        return jsonify({'error': 'Missing link'}), 400
    if not getattr(img, 'raw_verification_required', False):
        img.raw_verification_required = True
    db.session.execute(db.text(
        "INSERT INTO raw_submissions "
        "(image_id, user_id, contest_ref, contest_type, submission_method, raw_file_key, raw_link, submitted_at, analysis_status) "
        "VALUES (:iid, :uid, :cr, :ct, :meth, :fk, :lnk, NOW(), 'pending') "
        "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE "
        "SET submission_method=:meth, raw_file_key=:fk, raw_link=:lnk, submitted_at=NOW(), analysis_status='pending'"
    ), {'iid': image_id, 'uid': current_user.id, 'cr': contest_ref,
        'ct': contest_type, 'meth': method, 'fk': raw_file_key or None, 'lnk': raw_link or None})
    db.session.commit()
    sub_row = db.session.execute(db.text(
        "SELECT id FROM raw_submissions WHERE image_id=:iid AND contest_type=:ct ORDER BY submitted_at DESC LIMIT 1"
    ), {'iid': image_id, 'ct': contest_type}).fetchone()
    sub_id = sub_row.id if sub_row else None
    if sub_id:
        import threading
        t = threading.Thread(target=_auto_decide_raw, args=(image_id, sub_id), daemon=True)
        t.start()
    redirect_url = url_for('raw_status', image_id=image_id)
    return jsonify({'redirect': redirect_url})


# ---------------------------------------------------------------------------

@app.route('/raw/submit/<contest_type>/<int:image_id>', methods=['GET', 'POST'])
@login_required
def raw_submit(contest_type, image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)
    # Allow RAW submission if: admin flagged it required, OR user arrived via contest RAW link
    # Do NOT block — if user has the link, they were directed here intentionally
    if not getattr(img, 'raw_verification_required', False):
        # Mark it required now so the submission proceeds correctly
        img.raw_verification_required = True
        db.session.commit()
    existing = db.session.execute(db.text(
        "SELECT * FROM raw_submissions WHERE image_id=:iid AND contest_type=:ct LIMIT 1"
    ), {'iid': image_id, 'ct': contest_type}).fetchone()
    if existing and existing.submitted_at:
        return render_template('raw_submit.html', img=img, existing=existing,
                               contest_type=contest_type, already_submitted=True)

    if request.method == 'POST':
        method       = request.form.get('method', 'upload')
        raw_file_key = None
        raw_link     = None
        if method == 'upload':
            raw_file = request.files.get('raw_file')
            if not raw_file or not raw_file.filename:
                flash('Please select a RAW file to upload.', 'error')
                return redirect(request.url)
            uid      = str(uuid.uuid4())
            filename = secure_filename(raw_file.filename)
            key      = f'raw_submissions/{uid}_{filename}'
            uploaded = r2.upload_fileobj(raw_file.stream, key, content_type='application/octet-stream')
            if not uploaded:
                flash('Upload failed. Please try again or use a shareable link.', 'error')
                return redirect(request.url)
            raw_file_key = key
        elif method == 'link':
            raw_link = request.form.get('raw_link', '').strip()
            if not raw_link:
                flash('Please provide a shareable link to your RAW file.', 'error')
                return redirect(request.url)
        else:
            flash('Invalid submission method.', 'error')
            return redirect(request.url)

        contest_ref = request.form.get('contest_ref', '')
        db.session.execute(db.text(
            "INSERT INTO raw_submissions "
            "(image_id, user_id, contest_ref, contest_type, submission_method, raw_file_key, raw_link, submitted_at, analysis_status) "
            "VALUES (:iid, :uid, :cr, :ct, :meth, :fk, :lnk, NOW(), 'pending') "
            "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE "
            "SET submission_method=:meth, raw_file_key=:fk, raw_link=:lnk, submitted_at=NOW(), analysis_status='pending'"
        ), {'iid': image_id, 'uid': current_user.id, 'cr': contest_ref,
            'ct': contest_type, 'meth': method, 'fk': raw_file_key, 'lnk': raw_link})
        db.session.commit()

        # Fetch the submission ID for the background thread
        sub_row = db.session.execute(db.text(
            "SELECT id FROM raw_submissions WHERE image_id=:iid AND contest_type=:ct ORDER BY submitted_at DESC LIMIT 1"
        ), {'iid': image_id, 'ct': contest_type}).fetchone()
        sub_id = sub_row.id if sub_row else None

        # Fire background thread immediately — receipt email + analysis
        # both happen in the thread so the HTTP response returns at once.
        _photographer_email = current_user.email
        _photographer_name  = current_user.full_name or current_user.username
        _asset_name         = img.asset_name
        if sub_id:
            import threading
            t = threading.Thread(
                target=_auto_decide_raw,
                args=(image_id, sub_id),
                daemon=True
            )
            t.start()

        flash('RAW file uploaded successfully. We are verifying it now — you will receive an email confirmation shortly.', 'success')
        return redirect(url_for('raw_status', image_id=image_id))

    return render_template('raw_submit.html', img=img, existing=existing,
                           contest_type=contest_type, already_submitted=False)


@app.route('/raw/status/<int:image_id>')
@login_required
def raw_status(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    submission = db.session.execute(db.text(
        "SELECT * FROM raw_submissions WHERE image_id=:iid ORDER BY submitted_at DESC LIMIT 1"
    ), {'iid': image_id}).fetchone()
    return render_template('raw_status.html', img=img, submission=submission)


# ---------------------------------------------------------------------------
# Admin  -  RAW Verification Queue
# ---------------------------------------------------------------------------

@app.route('/admin/raw-verification')
@login_required
@admin_required
def admin_raw_verification():
    submissions = db.session.execute(db.text(
        "SELECT rs.*, i.asset_name, i.genre, i.score, i.thumb_url, u.username, u.email AS photographer_email "
        "FROM raw_submissions rs JOIN images i ON i.id=rs.image_id JOIN users u ON u.id=rs.user_id "
        "WHERE rs.admin_decision IS NULL ORDER BY rs.submitted_at ASC"
    )).fetchall()
    return render_template('admin_raw_verification.html', submissions=submissions)


@app.route('/admin/raw-verification/poty')
@login_required
@admin_required
def admin_raw_poty():
    pool = db.session.execute(db.text(
        "SELECT i.id, i.asset_name, i.genre, i.score, i.thumb_url, "
        "u.username, u.email, "
        "rs.submitted_at, rs.analysis_status, rs.admin_decision, rs.disqualified, rs.deadline "
        "FROM images i JOIN users u ON u.id=i.user_id "
        "LEFT JOIN raw_submissions rs ON rs.image_id=i.id "
        "WHERE i.raw_verification_required=TRUE "
        "ORDER BY rs.submitted_at ASC NULLS LAST, i.score DESC"
    )).fetchall()
    submitted    = sum(1 for r in pool if r.submitted_at)
    pending      = sum(1 for r in pool if not r.submitted_at)
    verified     = sum(1 for r in pool if r.admin_decision == 'approved')
    disqualified = sum(1 for r in pool if r.disqualified)
    return render_template('admin_raw_poty.html',
        pool=pool, submitted=submitted, pending=pending,
        verified=verified, disqualified=disqualified)


@app.route('/admin/raw-verification/<int:image_id>')
@login_required
@admin_required
def admin_raw_detail(image_id):
    img        = Image.query.get_or_404(image_id)
    submission = db.session.execute(db.text(
        "SELECT rs.*, u.username, u.email AS photographer_email "
        "FROM raw_submissions rs JOIN users u ON u.id=rs.user_id "
        "WHERE rs.image_id=:iid ORDER BY rs.submitted_at DESC LIMIT 1"
    ), {'iid': image_id}).fetchone()
    raw_file_url = (f"{r2.R2_PUBLIC_URL}/{submission.raw_file_key}") if (submission and submission.raw_file_key) else None
    # Check if appeal is pending (submitted but not yet decided)
    appeal_pending = (
        submission and
        submission.appeal_submitted_at and
        not submission.appeal_decision
    ) if submission else False
    return render_template('admin_raw_detail.html',
        img=img, submission=submission, raw_file_url=raw_file_url,
        appeal_pending=appeal_pending)


@app.route('/admin/image/<int:image_id>/mark-raw-verified', methods=['POST'])
@login_required
@admin_required
def admin_mark_raw_verified(image_id):
    """Admin shortcut -- mark image as RAW verified without a formal submission.
    Used for testing and manual override when contestant has verified by other means."""
    img = Image.query.get_or_404(image_id)
    img.raw_verified      = True
    img.raw_disqualified  = False
    # Also close out any open submission record so it leaves the queue
    db.session.execute(db.text(
        "UPDATE raw_submissions SET admin_decision='approved', admin_decided_at=NOW() "
        "WHERE image_id=:iid AND admin_decision IS NULL"
    ), {'iid': image_id})
    db.session.commit()
    flash(f'"{img.asset_name}" marked as RAW verified. It will now appear in the judge pool.', 'success')
    return redirect(url_for('admin_raw_detail', image_id=image_id))


@app.route('/admin/image/<int:image_id>/request-raw', methods=['POST'])
@login_required
@admin_required
def admin_request_raw(image_id):
    """Admin manually requests RAW verification from a photographer."""
    img = Image.query.get_or_404(image_id)
    if img.raw_verification_required:
        flash(f'RAW verification already requested for "{img.asset_name}".', 'info')
        return redirect(request.referrer or url_for('admin_dashboard'))
    img.raw_verification_required = True
    _deadline = datetime.utcnow() + timedelta(days=7)
    try:
        db.session.execute(db.text(
            "INSERT INTO raw_submissions "
            "(image_id, user_id, contest_ref, contest_type, deadline, analysis_status) "
            "VALUES (:iid, :uid, 'admin-request', 'weekly', :dl, 'awaiting') "
            "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE SET deadline=:dl"
        ), {'iid': img.id, 'uid': img.user_id, 'dl': _deadline})
    except Exception:
        pass
    db.session.commit()
    owner = User.query.get(img.user_id)
    if owner:
        _site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
        _submit_url = f'{_site_url}/raw/submit/weekly/{img.id}'
        _uname = owner.full_name or owner.username
        send_email(
            to_addresses=[owner.email],
            subject='[Shutter League] RAW File Requested — ' + (img.asset_name or 'Untitled'),
            html_body=(
                '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;background:#fffef9;color:#111111;">'
                '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#F5C518;margin-bottom:24px;">Shutter League</p>'
                '<h2 style="font-size:22px;font-weight:700;color:#111111;margin-bottom:16px;">RAW File Requested</h2>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">Hi ' + _uname + ',</p>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">We are conducting a routine authenticity audit. Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has been selected for RAW file verification.</p>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">Please submit your original RAW file within <strong>7 days</strong> to confirm your result.</p>'
                '<a href="' + _submit_url + '" style="display:inline-block;background:#F5C518;color:#000000;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:20px 0 8px 0;">Submit RAW File &#8594;</a>'
                '<p style="font-size:14px;color:#555555;margin-top:24px;">&#8212; Shutter League</p>'
                '</div>'
            )
        )
    flash(f'RAW verification requested for "{img.asset_name}" — photographer notified.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/bulk-request-raw', methods=['POST'])
@login_required
@admin_required
def admin_bulk_request_raw():
    """Admin bulk-requests RAW verification from multiple photographers."""
    image_ids = request.form.getlist('image_ids')
    if not image_ids:
        flash('No images selected.', 'warning')
        return redirect(url_for('admin_dashboard'))
    requested = 0
    skipped   = 0
    for iid in image_ids:
        try:
            img = Image.query.get(int(iid))
            if not img or img.status != 'scored':
                continue
            if img.raw_verification_required:
                skipped += 1
                continue
            img.raw_verification_required = True
            _deadline = datetime.utcnow() + timedelta(days=7)
            try:
                db.session.execute(db.text(
                    "INSERT INTO raw_submissions "
                    "(image_id, user_id, contest_ref, contest_type, deadline, analysis_status) "
                    "VALUES (:iid, :uid, 'admin-request', 'weekly', :dl, 'awaiting') "
                    "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE SET deadline=:dl"
                ), {'iid': img.id, 'uid': img.user_id, 'dl': _deadline})
            except Exception:
                pass
            owner = User.query.get(img.user_id)
            if owner:
                _site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
                _submit_url = f'{_site_url}/raw/submit/weekly/{img.id}'
                _uname = owner.full_name or owner.username
                send_email(
                    to_addresses=[owner.email],
                    subject='[Shutter League] RAW File Requested — ' + (img.asset_name or 'Untitled'),
                    html_body=(
                        '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;background:#fffef9;color:#111111;">'
                        '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#F5C518;margin-bottom:24px;">Shutter League</p>'
                        '<h2 style="font-size:22px;font-weight:700;color:#111111;margin-bottom:16px;">RAW File Requested</h2>'
                        '<p style="font-size:16px;line-height:1.7;color:#111111;">Hi ' + _uname + ',</p>'
                        '<p style="font-size:16px;line-height:1.7;color:#111111;">We are conducting a routine authenticity audit. Your image <strong>' + (img.asset_name or 'Untitled') + '</strong> has been selected for RAW file verification.</p>'
                        '<p style="font-size:16px;line-height:1.7;color:#111111;">Please submit your original RAW file within <strong>7 days</strong> to confirm your result.</p>'
                        '<a href="' + _submit_url + '" style="display:inline-block;background:#F5C518;color:#000000;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:20px 0 8px 0;">Submit RAW File &#8594;</a>'
                        '<p style="font-size:14px;color:#555555;margin-top:24px;">&#8212; Shutter League</p>'
                        '</div>'
                    )
                )
            requested += 1
        except Exception as e:
            app.logger.error(f'[bulk_request_raw] image {iid}: {e}')
    db.session.commit()
    msg = f'RAW verification requested for {requested} image(s).'
    if skipped:
        msg += f' {skipped} already had RAW requested (skipped).'
    flash(msg, 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/raw-verification/<int:image_id>/send-reminder', methods=['POST'])
@login_required
@admin_required
def admin_raw_send_reminder(image_id):
    """Manually send a RAW submission reminder to the photographer."""
    img   = Image.query.get_or_404(image_id)
    owner = User.query.get(img.user_id)
    if not owner:
        flash('User not found.', 'error')
        return redirect(url_for('admin_raw_detail', image_id=image_id))
    sub = db.session.execute(db.text(
        'SELECT * FROM raw_submissions WHERE image_id=:iid ORDER BY id DESC LIMIT 1'
    ), {'iid': image_id}).fetchone()
    deadline_str  = sub.deadline.strftime('%d %B %Y, %H:%M UTC') if (sub and sub.deadline) else '—'
    contest_type  = (sub.contest_type or 'weekly') if sub else 'weekly'
    site_url      = os.getenv('SITE_URL', 'https://shutterleague.com')
    submit_url    = f'{site_url}/raw/submit/{contest_type}/{image_id}'
    uname  = owner.full_name or owner.username
    ititle = img.asset_name or 'Untitled'
    try:
        import threading
        threading.Thread(
            target=send_email,
            args=(
                [owner.email],
                '[Shutter League] Reminder: RAW File Required for ' + ititle,
                '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;'
                'background:#fffef9;color:#111111;">'
                '<p style="font-family:\'Courier New\',monospace;font-size:12px;letter-spacing:2px;'
                'text-transform:uppercase;color:#F5C518;margin-bottom:24px;">Shutter League</p>'
                '<h2 style="font-size:22px;font-weight:700;color:#111111;margin-bottom:16px;">'
                'RAW File Required &#8212; Action Needed</h2>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">Hi ' + uname + ',</p>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">Your RAW file for '
                '<strong>' + ititle + '</strong> is required to confirm your contest standing.</p>'
                '<p style="font-size:16px;line-height:1.7;color:#111111;">'
                'Deadline: <strong style="color:#F5C518;">' + deadline_str + '</strong></p>'
                '<a href="' + submit_url + '" style="display:inline-block;background:#F5C518;'
                'color:#000000;font-family:\'Courier New\',monospace;font-size:13px;font-weight:700;'
                'letter-spacing:1px;text-transform:uppercase;padding:14px 28px;'
                'text-decoration:none;border-radius:4px;margin:20px 0 8px 0;">'
                'Submit RAW File &#8594;</a>'
                '<p style="font-size:14px;color:#111111;margin-top:8px;">Or visit: '
                '<a href="' + submit_url + '" style="color:#F5C518;">' + submit_url + '</a></p>'
                '<p style="font-size:14px;color:#555555;margin-top:24px;">&#8212; Shutter League</p>'
                '</div>',
            ),
            daemon=True
        ).start()
        flash('Reminder email sent to ' + owner.email + '.', 'success')
    except Exception as e:
        flash('Failed to send reminder: ' + str(e), 'error')
    return redirect(url_for('admin_raw_detail', image_id=image_id))


@app.route('/admin/raw-verification/<int:image_id>/delete-submission', methods=['POST'])
@login_required
@admin_required
def admin_raw_delete_submission(image_id):
    """Delete the RAW submission record for this image. Does not delete the image itself."""
    img = Image.query.get_or_404(image_id)
    db.session.execute(db.text(
        'DELETE FROM raw_submissions WHERE image_id=:iid'
    ), {'iid': image_id})
    db.session.commit()
    flash('RAW submission record deleted for "' + (img.asset_name or 'Untitled') + '".', 'success')
    return redirect(url_for('admin_raw_verification'))


@app.route('/admin/raw-verification/bulk-delete', methods=['POST'])
@login_required
@admin_required
def admin_raw_bulk_delete():
    image_ids = request.form.getlist('image_ids')
    if not image_ids:
        flash('No images selected.', 'warning')
        return redirect(url_for('admin_raw_verification'))
    deleted = 0
    for iid in image_ids:
        try:
            db.session.execute(db.text(
                'DELETE FROM raw_submissions WHERE image_id=:iid'
            ), {'iid': int(iid)})
            deleted += 1
        except Exception:
            pass
    db.session.commit()
    flash(f'{deleted} RAW submission record(s) deleted.', 'success')
    return redirect(url_for('admin_raw_verification'))


@app.route('/admin/raw-verification/bulk-remind', methods=['POST'])
@login_required
@admin_required
def admin_raw_bulk_remind():
    image_ids = request.form.getlist('image_ids')
    if not image_ids:
        flash('No images selected.', 'warning')
        return redirect(url_for('admin_raw_verification'))
    site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
    sent = 0
    for iid in image_ids:
        try:
            iid   = int(iid)
            img   = Image.query.get(iid)
            owner = User.query.get(img.user_id) if img else None
            if not img or not owner:
                continue
            sub = db.session.execute(db.text(
                'SELECT * FROM raw_submissions WHERE image_id=:iid ORDER BY id DESC LIMIT 1'
            ), {'iid': iid}).fetchone()
            deadline_str = sub.deadline.strftime('%d %B %Y, %H:%M UTC') if (sub and sub.deadline) else '---'
            contest_type = (sub.contest_type or 'weekly') if sub else 'weekly'
            submit_url   = f'{site_url}/raw/submit/{contest_type}/{iid}'
            uname  = owner.full_name or owner.username
            ititle = img.asset_name or 'Untitled'
            import threading
            threading.Thread(
                target=send_email,
                args=(
                    [owner.email],
                    '[Shutter League] Reminder: RAW File Required for ' + ititle,
                    '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;background:#fffef9;color:#111111;">'
                    '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#F5C518;margin-bottom:24px;">Shutter League</p>'
                    '<h2 style="font-size:22px;font-weight:700;color:#111111;margin-bottom:16px;">RAW File Required &#8212; Action Needed</h2>'
                    '<p style="font-size:16px;line-height:1.7;color:#111111;">Hi ' + uname + ',</p>'
                    '<p style="font-size:16px;line-height:1.7;color:#111111;">Your RAW file for <strong>' + ititle + '</strong> is required to confirm your contest standing.</p>'
                    '<p style="font-size:16px;line-height:1.7;color:#111111;">Deadline: <strong style="color:#F5C518;">' + deadline_str + '</strong></p>'
                    '<a href="' + submit_url + '" style="display:inline-block;background:#F5C518;color:#000000;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:20px 0 8px 0;">Submit RAW File &#8594;</a>'
                    '<p style="font-size:14px;color:#111111;margin-top:8px;">Or visit: <a href="' + submit_url + '" style="color:#F5C518;">' + submit_url + '</a></p>'
                    '<p style="font-size:14px;color:#555555;margin-top:24px;">&#8212; Shutter League</p>'
                    '</div>',
                ),
                daemon=True
            ).start()
            sent += 1
        except Exception:
            pass
    flash(f'Reminder emails sent to {sent} photographer(s).', 'success')
    return redirect(url_for('admin_raw_verification'))


@app.route('/admin/raw-verification/bulk-verify', methods=['POST'])
@login_required
@admin_required
def admin_raw_bulk_verify():
    image_ids = request.form.getlist('image_ids')
    if not image_ids:
        flash('No images selected.', 'warning')
        return redirect(url_for('admin_raw_verification'))
    verified = 0
    for iid in image_ids:
        try:
            iid = int(iid)
            img = Image.query.get(iid)
            if not img:
                continue
            img.raw_verified     = True
            img.raw_disqualified = False
            db.session.execute(db.text(
                "UPDATE raw_submissions SET admin_decision='approved', admin_decided_at=NOW() "
                "WHERE image_id=:iid AND admin_decision IS NULL"
            ), {'iid': iid})
            verified += 1
        except Exception:
            pass
    db.session.commit()
    flash(f'{verified} image(s) marked as RAW verified.', 'success')
    return redirect(url_for('admin_raw_verification'))


@app.route('/admin/raw-verification/<int:image_id>/decide', methods=['POST'])
@login_required
@admin_required
def admin_raw_decide(image_id):
    img      = Image.query.get_or_404(image_id)
    decision = request.form.get('decision', '')
    notes    = request.form.get('notes', '').strip()
    if decision not in ('approved', 'rejected', 'resubmit_requested'):
        flash('Invalid decision.', 'error')
        return redirect(url_for('admin_raw_detail', image_id=image_id))

    db.session.execute(db.text(
        "UPDATE raw_submissions SET admin_decision=:dec, admin_notes=:notes, "
        "admin_decided_by=:by, admin_decided_at=NOW() WHERE image_id=:iid"
    ), {'dec': decision, 'notes': notes or None, 'by': current_user.id, 'iid': image_id})

    photographer = User.query.get(img.user_id)

    if decision == 'approved':
        db.session.execute(db.text(
            "UPDATE images SET raw_verified=TRUE, raw_disqualified=FALSE WHERE id=:iid"
        ), {'iid': image_id})
        if photographer:
            send_email(
                photographer.email,
                'RAW verification approved -- Shutter League',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
                 f'<h2>RAW Verification Approved</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image <strong>"{img.asset_name}"</strong> has passed RAW verification.</p>'
                 f'{"<p>Admin note: " + notes + "</p>" if notes else ""}'
                 f'</div>')
            )
        flash(f'RAW approved for "{img.asset_name}".', 'success')

    elif decision == 'rejected':
        db.session.execute(db.text(
            "UPDATE images SET raw_verified=FALSE, raw_disqualified=TRUE WHERE id=:iid"
        ), {'iid': image_id})
        db.session.execute(db.text(
            "UPDATE raw_submissions SET disqualified=TRUE WHERE image_id=:iid"
        ), {'iid': image_id})
        if photographer:
            send_email(
                photographer.email,
                'RAW verification failed -- Shutter League',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
                 f'<h2 style="color:#C0392B;">RAW Verification Failed</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image <strong>"{img.asset_name}"</strong> has been disqualified.</p>'
                 f'{"<p>Reason: " + notes + "</p>" if notes else ""}'
                 f'<p style="font-size:14px;color:#8a8070;">Contact '+CONTACT_EMAIL+' to contest within 48 hours.</p>'
                 f'</div>')
            )
        flash(f'RAW rejected -- "{img.asset_name}" disqualified.', 'warning')

    elif decision == 'resubmit_requested':
        site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
        if photographer:
            send_email(
                photographer.email,
                'RAW resubmission required -- Shutter League',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
                 f'<h2>RAW Resubmission Required</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Please resubmit the RAW for <strong>"{img.asset_name}"</strong> within 24 hours.</p>'
                 f'{"<p>Reason: " + notes + "</p>" if notes else ""}'
                 f'<a href="{site_url}/raw/status/{image_id}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">Resubmit RAW</a>'
                 f'</div>')
            )
        flash(f'Resubmission requested for "{img.asset_name}".', 'info')

    db.session.commit()
    return redirect(url_for('admin_raw_verification'))


@app.route('/admin/judge-assignment/<int:assignment_id>/resolve-flag', methods=['POST'])
@login_required
@admin_required
def admin_resolve_flag(assignment_id):
    """Admin resolves a judge-raised flag: disqualify or override (keep in pool)."""
    decision = request.form.get('decision', '').strip()
    note     = request.form.get('note', '').strip()
    if decision not in ('disqualify', 'override'):
        flash('Invalid decision.', 'error')
        return redirect(url_for('admin_judge_queue'))

    assignment = db.session.execute(db.text(
        "SELECT ja.*, i.asset_name, i.genre, j.email AS judge_email, j.name AS judge_name "
        "FROM judge_assignments ja "
        "JOIN images i ON i.id = ja.image_id "
        "JOIN judges j ON j.id = ja.judge_id "
        "WHERE ja.id = :aid"
    ), {'aid': assignment_id}).fetchone()
    if not assignment:
        abort(404)

    db.session.execute(db.text(
        "UPDATE judge_assignments SET admin_flag_decision=:dec, admin_flag_note=:note, "
        "admin_flag_decided_at=NOW() WHERE id=:aid"
    ), {'dec': decision, 'note': note or None, 'aid': assignment_id})

    if decision == 'disqualify':
        # Remove image from contest pool
        db.session.execute(db.text(
            "UPDATE images SET in_judge_pool=FALSE, contest_result_status='disqualified' WHERE id=:iid"
        ), {'iid': assignment.image_id})
        action_label = 'disqualified from the contest'
    else:
        # Override -- clear the flag, treat as pending for scoring
        db.session.execute(db.text(
            "UPDATE judge_assignments SET status='pending' WHERE id=:aid"
        ), {'aid': assignment_id})
        action_label = 'kept in the contest pool -- flag overridden'

    db.session.commit()

    # Email the judge who raised the flag
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    if assignment.judge_email:
        send_email(
            assignment.judge_email,
            f'Your flag has been reviewed -- {assignment.asset_name}',
            (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
             f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League -- Jury</p>'
             f'<h2 style="font-size:20px;font-weight:700;margin-bottom:12px;">Flag Reviewed</h2>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you for flagging <strong>"{assignment.asset_name}"</strong> ({assignment.genre}).</p>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Admin decision: <strong style="color:#C8A84B;">{action_label.title()}</strong>.</p>'
             f'{"<p style=\"font-size:15px;color:#8A8478;\">Note: " + note + "</p>" if note else ""}'
             f'<a href="{site_url}/judge/dashboard" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">View Dashboard</a>'
             f'</div>')
        )

    flash(f'Flag resolved: "{assignment.asset_name}" {action_label}.', 'success')
    return redirect(url_for('admin_judge_queue'))


@app.route('/admin/raw-verification/trigger-analysis/<int:image_id>', methods=['POST'])
@login_required
@admin_required
def admin_raw_trigger_analysis(image_id):
    submission = db.session.execute(db.text(
        "SELECT * FROM raw_submissions WHERE image_id=:iid ORDER BY submitted_at DESC LIMIT 1"
    ), {'iid': image_id}).fetchone()
    if not submission:
        flash('No RAW submission found for this image.', 'error')
        return redirect(url_for('admin_raw_detail', image_id=image_id))

    img = Image.query.get_or_404(image_id)
    db.session.execute(db.text(
        "UPDATE raw_submissions SET analysis_status='running', analysis_run_at=NOW() WHERE image_id=:iid"
    ), {'iid': image_id})
    db.session.commit()

    try:
        flags, results = _run_raw_analysis(submission, img)
        flag_reasons = []
        if results.get('crop_flagged'):
            flag_reasons.append(f'Crop {results.get("crop_percentage",0):.1%} exceeds 20%')
        for key, label in [
            ('vision_ai_detected', 'Vision: AI generation'),
            ('vision_objects_removed', 'Vision: Objects removed'),
            ('vision_objects_added', 'Vision: Objects added'),
            ('vision_logo_trademark', 'Vision: Logo/trademark'),
            ('vision_meaning_changed', 'Vision: Meaning changed'),
            ('vision_painterly', 'Vision: Painterly'),
        ]:
            if results.get(key):
                flag_reasons.append(label)

        db.session.execute(db.text(
            "UPDATE raw_submissions SET analysis_status='complete', "
            "exif_match=:em, crop_percentage=:cp, crop_flagged=:cf, dimension_match=:dm, "
            "raw_original_width=:rw, raw_original_height=:rh, "
            "vision_ai_detected=:vai, vision_objects_removed=:vor, vision_objects_added=:voa, "
            "vision_logo_trademark=:vlt, vision_meaning_changed=:vmc, vision_painterly=:vp, "
            "vision_crop_consistent=:vcc, vision_notes=:vn, overall_flag=:of, flag_reasons=:fr "
            "WHERE image_id=:iid"
        ), {
            'em': results.get('exif_match'), 'cp': results.get('crop_percentage'),
            'cf': results.get('crop_flagged', False), 'dm': results.get('dimension_match'),
            'rw': results.get('raw_width'), 'rh': results.get('raw_height'),
            'vai': results.get('vision_ai_detected'), 'vor': results.get('vision_objects_removed'),
            'voa': results.get('vision_objects_added'), 'vlt': results.get('vision_logo_trademark'),
            'vmc': results.get('vision_meaning_changed'), 'vp': results.get('vision_painterly'),
            'vcc': results.get('vision_crop_consistent'), 'vn': results.get('vision_notes'),
            'of': flags, 'fr': ' | '.join(flag_reasons) if flag_reasons else None,
            'iid': image_id,
        })
        db.session.commit()
        flash(f'Analysis complete. {"Flags raised -- review required." if flags else "No flags."}',
              'warning' if flags else 'success')
    except Exception as e:
        db.session.execute(db.text(
            "UPDATE raw_submissions SET analysis_status='failed' WHERE image_id=:iid"
        ), {'iid': image_id})
        db.session.commit()
        app.logger.error(f'[raw_analysis] image {image_id}: {e}')
        flash(f'Analysis failed: {str(e)[:120]}', 'error')

    return redirect(url_for('admin_raw_detail', image_id=image_id))


def _run_raw_analysis(submission, img):
    """
    RAW file authenticity analysis. Returns (overall_flag, results_dict).

    VERIFICATION PHILOSOPHY:
    ─────────────────────────────────────────────────────────────────────
    This engine verifies that the submitted JPEG and the RAW file show
    the SAME photograph. It does NOT penalise legitimate photographic
    practice. The following are explicitly acceptable and must NOT flag:

      ✓ Exposure, contrast, shadows, highlights adjustments
      ✓ Colour grading, white balance changes
      ✓ Sharpening, noise reduction, lens corrections
      ✓ Cropping — including heavy crops from high-resolution cameras
        (a 100MP RAW cropped to a 2000px JPEG is completely legitimate)
      ✓ EXIF stripped by editing software (Lightroom, Photoshop etc.)
      ✓ Dimension mismatch due to crop or resolution difference

    The ONLY triggers for a flag are:
      ✗ File cannot be decoded (corrupt, wrong file, wrong format)
      ✗ Objects added or removed (compositing, generative AI)
      ✗ Subject or scene is materially different from the RAW
      ✗ AI generation detected in the submitted JPEG
      ✗ Logo or trademark added

    DO NOT reintroduce dimension/crop checks or EXIF checks as flag
    triggers. These punish high-resolution shooters and photographers
    who edit in software that strips metadata — both are legitimate.
    ─────────────────────────────────────────────────────────────────────
    """
    import tempfile, io as _io, base64, json as _json
    import urllib.request as _ur

    results     = {}
    overall_flag= False
    raw_path    = None

    # Step 1  -  Metadata
    try:
        if submission.raw_file_key:
            from storage import get_client, BUCKET
            import os as _os
            _raw_ext = _os.path.splitext(submission.raw_file_key)[1] or '.raw'
            tf = tempfile.NamedTemporaryFile(suffix=_raw_ext, delete=False)
            get_client().download_fileobj(BUCKET, submission.raw_file_key, tf)
            tf.close()
            raw_path = tf.name

        if raw_path:
            # ── Format-agnostic RAW decode ─────────────────────────────────
            # Strategy:
            #   1. Try rawpy (works for older/standard CR2, NEF, ARW, DNG)
            #   2. Fall back to embedded JPEG extraction — works for ALL
            #      formats: CR3, RAF, Z9 HE*, GFX 100, Alpha 1, Hasselblad.
            #      Every RAW file contains an embedded JPEG (FF D8...FF D9).
            # Only mark raw_decode_failed if BOTH methods fail.

            def _extract_embedded_jpeg(path):
                """Extract largest embedded JPEG from any RAW binary.
                Scans for FF D8 (JPEG SOI) ... FF D9 (EOI) sequences.
                Format-agnostic — works on every camera RAW ever made."""
                from PIL import Image as _PIL
                import io as _io2
                with open(path, 'rb') as _f:
                    _data = _f.read()
                SOI = b'\xff\xd8'
                EOI = b'\xff\xd9'
                _candidates = []
                _pos = 0
                while True:
                    _start = _data.find(SOI, _pos)
                    if _start == -1:
                        break
                    _end = _data.find(EOI, _start + 2)
                    if _end == -1:
                        break
                    _candidates.append(_data[_start:_end + 2])
                    _pos = _start + 1
                if not _candidates:
                    raise ValueError('No embedded JPEG found in RAW file')
                _jpeg = max(_candidates, key=len)
                if len(_jpeg) < 10000:
                    raise ValueError(f'Embedded JPEG too small ({len(_jpeg)} bytes)')
                return _PIL.open(_io2.BytesIO(_jpeg)).convert('RGB')

            def _open_raw_as_pil(path):
                """Try rawpy first, then embedded JPEG extraction."""
                try:
                    import rawpy
                    import numpy as _np
                    from PIL import Image as _PIL
                    with rawpy.imread(path) as _raw:
                        _rgb = _raw.postprocess(half_size=True)
                    app.logger.info(f'[raw_analysis] rawpy decode OK')
                    return _PIL.fromarray(_rgb)
                except Exception as _rawpy_err:
                    app.logger.warning(f'[rawpy] failed ({_rawpy_err}) — trying embedded JPEG')
                try:
                    _pil = _extract_embedded_jpeg(path)
                    app.logger.info(f'[raw_analysis] embedded JPEG extracted OK')
                    return _pil
                except Exception as _emb_err:
                    app.logger.warning(f'[raw_analysis] embedded JPEG failed: {_emb_err}')
                    raise ValueError('Could not decode RAW file by any method')

        if raw_path:
            try:
                pil_raw = _open_raw_as_pil(raw_path)
                raw_w, raw_h = pil_raw.size
                results['raw_width']  = raw_w
                results['raw_height'] = raw_h
                jpg_w = img.width  or 0
                jpg_h = img.height or 0
                if jpg_w and jpg_h and raw_w and raw_h:
                    crop_pct = 1.0 - (min(raw_w, jpg_w) * min(raw_h, jpg_h)) / (raw_w * raw_h)
                    results['crop_percentage'] = round(crop_pct, 4)
                    results['crop_flagged']    = crop_pct > 0.20
                    results['dimension_match'] = abs(raw_w - jpg_w) < raw_w * 0.5
                results['exif_match'] = True
                app.logger.info(f'[raw_analysis] decode success: {raw_w}x{raw_h}')
            except Exception as _raw_err:
                app.logger.warning(f'[raw_analysis] all decode methods failed: {_raw_err}')
                results['exif_match'] = False
                results['raw_decode_failed'] = True
                overall_flag = True
    except Exception as meta_err:
        app.logger.warning(f'[raw_metadata] {meta_err}')
        results['exif_match'] = False

    # Step 2  -  Vision
    try:
        jpg_b64 = None
        if img.thumb_url:
            try:
                resp    = _ur.urlopen(img.thumb_url, timeout=10)
                jpg_b64 = base64.b64encode(resp.read()).decode('utf-8')
            except Exception:
                pass

        raw_b64 = None
        if raw_path and not results.get('raw_decode_failed'):
            try:
                # Reuse the same dual-strategy decoder (rawpy + embedded JPEG)
                pil_r = _open_raw_as_pil(raw_path).convert('RGB')
                # Cap to 1024px — sufficient for vision comparison, ~95% smaller payload
                _max_px = 1024
                if max(pil_r.size) > _max_px:
                    pil_r.thumbnail((_max_px, _max_px))
                buf   = _io.BytesIO()
                pil_r.save(buf, format='JPEG', quality=85)
                raw_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                app.logger.info(f'[raw_vision] preview encoded: {pil_r.size}')
            except Exception as _v_err:
                app.logger.warning(f'[raw_vision] could not prepare preview: {_v_err}')

        if jpg_b64 and raw_b64:
            api_key = os.getenv('ANTHROPIC_API_KEY', '')
            if api_key:
                payload = {
                    'model': 'claude-sonnet-4-20250514',
                    'max_tokens': 400,
                    'messages': [{
                        'role': 'user',
                        'content': [
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': jpg_b64}},
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': raw_b64}},
                            {'type': 'text', 'text': (
                                'You are a RAW file authenticity verifier for a photography contest. '
                                'Image A is the submitted JPEG (may have editing: exposure, colour grade, shadows, highlights, sharpening — all acceptable). '
                                'Image B is the RAW file preview (unedited or minimally processed straight from camera). '
                                'Your job is to verify they show the SAME photograph — same scene, same subject, same moment, same composition. '
                                'Editing differences (brightness, contrast, colour, crop within reason) are FINE and should NOT be flagged. '
                                'Only flag genuine content manipulation. '
                                'Respond ONLY with JSON, no markdown:\n'
                                '{"ai_generated":bool,"objects_removed":bool,"objects_added":bool,'
                                '"subject_different":bool,"scene_different":bool,'
                                '"logo_or_trademark":bool,"meaning_changed":bool,"painterly":bool,'
                                '"notes":"max 80 words — focus on whether this is the same photograph"}'
                            )}
                        ]
                    }]
                }
                data = _json.dumps(payload).encode('utf-8')
                req  = _ur.Request(
                    'https://api.anthropic.com/v1/messages', data=data,
                    headers={'Content-Type': 'application/json', 'x-api-key': api_key,
                             'anthropic-version': '2023-06-01'},
                    method='POST'
                )
                with _ur.urlopen(req, timeout=30) as resp:
                    rdata  = _json.loads(resp.read().decode())
                    text   = rdata.get('content', [{}])[0].get('text', '{}')
                    text   = text.strip().lstrip('`').lstrip('json').strip('`').strip()
                    vision = _json.loads(text)

                results['vision_ai_detected']    = bool(vision.get('ai_generated'))
                results['vision_objects_removed'] = bool(vision.get('objects_removed'))
                results['vision_objects_added']   = bool(vision.get('objects_added'))
                results['vision_logo_trademark']  = bool(vision.get('logo_or_trademark'))
                results['vision_meaning_changed'] = bool(vision.get('meaning_changed') or vision.get('subject_different') or vision.get('scene_different'))
                results['vision_painterly']       = bool(vision.get('painterly'))
                results['vision_crop_consistent'] = True  # editing is acceptable
                results['vision_notes']           = vision.get('notes', '')
                # Only flag genuine content manipulation — editing differences are acceptable
                if any([results['vision_ai_detected'], results['vision_objects_removed'],
                        results['vision_objects_added'], results['vision_logo_trademark'],
                        results['vision_meaning_changed']]):
                    overall_flag = True
    except Exception as vision_err:
        app.logger.warning(f'[raw_vision] {vision_err}')
    finally:
        if raw_path:
            try:
                os.unlink(raw_path)
            except Exception:
                pass

    return overall_flag, results


# ---------------------------------------------------------------------------
# Automated RAW decision + appeal system  (v32)
# ---------------------------------------------------------------------------

def _auto_decide_raw(image_id, submission_id):
    """
    Run immediately after RAW submission in a background thread.
    Analyses the RAW, auto-approves or auto-disqualifies, sends email to photographer.
    """
    with app.app_context():
        try:
            submission = db.session.execute(db.text(
                "SELECT * FROM raw_submissions WHERE id=:sid"
            ), {'sid': submission_id}).fetchone()
            img = Image.query.get(image_id)
            if not submission or not img:
                return

            photographer = User.query.get(img.user_id)
            site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')

            # Mark as running
            db.session.execute(db.text(
                "UPDATE raw_submissions SET analysis_status='running', analysis_run_at=NOW() WHERE id=:sid"
            ), {'sid': submission_id})
            db.session.commit()

            # Send receipt email now — upload is confirmed in DB, user can close browser
            if photographer:
                _uname = photographer.full_name or photographer.username
                send_email(
                    photographer.email,
                    'RAW file received — ' + (img.asset_name or 'Untitled'),
                    ('<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                     '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                     '<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">RAW File Received</h2>'
                     '<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you, ' + _uname + '.</p>'
                     '<p style="font-size:16px;line-height:1.7;color:#4A4840;">We have received your RAW file for <strong>"' + (img.asset_name or 'Untitled') + '"</strong>. '
                     'Our automated system is now verifying it. You will receive a result by email shortly.</p>'
                     '<p style="font-size:14px;color:#8a8070;margin-top:24px;">&#8212; Shutter League</p>'
                     '</div>')
                )

            # Run analysis
            flags, results = _run_raw_analysis(submission, img)

            # Build flag reason list
            flag_reasons = []
            decode_failed = results.get('raw_decode_failed', False)
            if decode_failed:
                flag_reasons.append('RAW file could not be decoded by automated system — camera format may require manual verification')
            flag_map = [
                ('vision_ai_detected',    'AI generation detected in submitted image'),
                ('vision_objects_removed','Subject or objects appear to have been removed from the original'),
                ('vision_objects_added',  'Subject or objects appear to have been added that are not in the RAW'),
                ('vision_logo_trademark', 'Logo or trademark detected'),
                ('vision_meaning_changed','The photograph appears to show a different scene or subject than the RAW file'),
            ]
            for key, label in flag_map:
                if results.get(key):
                    flag_reasons.append(label)

            # If only flag is decode failure (format unsupported), route to manual review
            # Do NOT auto-disqualify — camera format support is a technical limitation
            only_decode_fail = decode_failed and len(flag_reasons) == 1
            if not flags:
                auto_decision = 'approved'
            elif only_decode_fail:
                auto_decision = 'manual_review'
            else:
                auto_decision = 'disqualified'
            flag_str = ' | '.join(flag_reasons) if flag_reasons else None

            # Update DB
            db.session.execute(db.text(
                "UPDATE raw_submissions SET "
                "analysis_status='complete', auto_decision=:dec, auto_decided_at=NOW(), "
                "auto_flag_reasons=:fr, "
                "exif_match=:em, crop_percentage=:cp, crop_flagged=:cf, dimension_match=:dm, "
                "raw_original_width=:rw, raw_original_height=:rh, "
                "vision_ai_detected=:vai, vision_objects_removed=:vor, vision_objects_added=:voa, "
                "vision_logo_trademark=:vlt, vision_meaning_changed=:vmc, vision_painterly=:vp, "
                "vision_crop_consistent=:vcc, vision_notes=:vn, overall_flag=:of, flag_reasons=:fr2 "
                "WHERE id=:sid"
            ), {
                'dec': auto_decision, 'fr': flag_str,
                'em': results.get('exif_match'), 'cp': results.get('crop_percentage'),
                'cf': results.get('crop_flagged', False), 'dm': results.get('dimension_match'),
                'rw': results.get('raw_width'), 'rh': results.get('raw_height'),
                'vai': results.get('vision_ai_detected'), 'vor': results.get('vision_objects_removed'),
                'voa': results.get('vision_objects_added'), 'vlt': results.get('vision_logo_trademark'),
                'vmc': results.get('vision_meaning_changed'), 'vp': results.get('vision_painterly'),
                'vcc': results.get('vision_crop_consistent'), 'vn': results.get('vision_notes'),
                'of': flags, 'fr2': flag_str, 'sid': submission_id,
            })

            if auto_decision == 'manual_review':
                # Camera format not supported by automated system — flag for admin manual check
                db.session.execute(db.text(
                    "UPDATE raw_submissions SET analysis_status='manual_review', overall_flag=FALSE WHERE id=:sid"
                ), {'sid': submission_id})
                db.session.commit()
                photographer = User.query.get(img.user_id)
                # Email photographer — reassure, no disqualification
                if photographer:
                    send_email(
                        photographer.email,
                        f'RAW File Received — Manual Verification — {img.asset_name}',
                        (
                            '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                            '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                            '<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">RAW File Received</h2>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you, ' + (photographer.full_name or photographer.username) + '.</p>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">We have received your RAW file for <strong>"' + (img.asset_name or 'Untitled') + '"</strong>. '
                            'Your camera&#39;s RAW format requires manual verification by our team. '
                            'We will review it within <strong>48 hours</strong> and notify you of the outcome.</p>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image remains active and your contest standing is not affected during this review.</p>'
                            '<p style="font-size:14px;color:#8a8070;margin-top:24px;">— Shutter League</p>'
                            '</div>'
                        )
                    )
                # Notify admin for manual review
                admin_emails = _admin_notify_emails()
                if not admin_emails:
                    admin_emails = [ADMIN_NOTIFY_EMAIL]
                site_url = os.getenv('SITE_URL', 'https://shutterleague.com')
                send_email(
                    admin_emails,
                    f'[RAW Manual Review Required] Image #{image_id} — {img.asset_name}',
                    (
                        '<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;">'
                        '<p style="color:#C8A84B;font-weight:700;">RAW MANUAL REVIEW REQUIRED</p>'
                        '<p>Camera RAW format could not be decoded by automated system (likely newer Nikon Z-series, Sony, or Canon format).</p>'
                        '<p>Image: ' + (img.asset_name or 'Untitled') + ' (ID: ' + str(image_id) + ')<br>'
                        'Photographer: ' + (photographer.username if photographer else 'unknown') + '<br>'
                        'Score: ' + str(img.score) + ' · ' + (img.genre or '') + '</p>'
                        '<p>Please download the RAW file and verify manually.</p>'
                        '<a href="' + site_url + '/admin/raw-verification/' + str(image_id) + '" style="color:#C8A84B;">Review submission →</a>'
                        '</div>'
                    )
                )

            elif auto_decision == 'approved':
                db.session.execute(db.text(
                    "UPDATE raw_submissions SET admin_decision='approved', disqualified=FALSE WHERE id=:sid"
                ), {'sid': submission_id})
                db.session.execute(db.text(
                    "UPDATE images SET raw_verified=TRUE, raw_disqualified=FALSE WHERE id=:iid"
                ), {'iid': image_id})
                db.session.commit()

                # Email 1 — Auto Approved
                if photographer:
                    send_email(
                        photographer.email,
                        f'RAW Verification Passed — {img.asset_name}',
                        (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                         f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                         f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">RAW Verification Passed ✓</h2>'
                         f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Dear {photographer.full_name or photographer.username},</p>'
                         f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your RAW file for <strong>"{img.asset_name}"</strong> has been verified by our automated system. Our analysis found no issues with the file.</p>'
                         f'<div style="background:#F0F7F0;border:1px solid #4CAF50;border-radius:6px;padding:16px 20px;margin:20px 0;">'
                         f'<p style="margin:0;font-family:Courier New,monospace;font-size:15px;color:#2E7D32;font-weight:700;">VERIFIED ✓ &nbsp;·&nbsp; DDI Score: {img.score} &nbsp;·&nbsp; {img.genre}</p>'
                         f'</div>'
                         f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image stands verified and your result is confirmed. Thank you for submitting your original file — this is what keeps Shutter League honest.</p>'
                         f'<p style="font-size:14px;color:#8a8070;margin-top:24px;">— Shutter League</p>'
                         f'</div>')
                    )

                # Notify admin
                admin_emails = _admin_notify_emails()
                if not admin_emails:
                    admin_emails = [ADMIN_NOTIFY_EMAIL]
                send_email(
                    admin_emails,
                    f'[RAW Auto-Approved] Image #{image_id} — {img.asset_name}',
                    (f'<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;">'
                     f'<p style="color:#4CAF50;font-weight:700;">RAW AUTO-APPROVED ✓</p>'
                     f'<p>Image: {img.asset_name} (ID: {image_id})<br>'
                     f'Photographer: {photographer.username if photographer else "unknown"}<br>'
                     f'Score: {img.score} · {img.genre}</p>'
                     f'<p style="color:#8a8070;">No flags raised. Photographer notified.</p>'
                     f'</div>')
                )

            else:
                # Flags raised — route to admin for human decision, NOT auto-disqualified
                # Never send disqualification emails to photographers — admin makes the call
                db.session.execute(db.text(
                    "UPDATE raw_submissions SET analysis_status='flagged', overall_flag=TRUE WHERE id=:sid"
                ), {'sid': submission_id})
                db.session.commit()

                # Email photographer — neutral, reassuring, no mention of disqualification
                if photographer:
                    send_email(
                        photographer.email,
                        f'RAW File Received — Under Review · {img.asset_name}',
                        (
                            '<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                            '<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                            '<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">RAW File Under Review</h2>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you, ' + (photographer.full_name or photographer.username) + '.</p>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">We have received your RAW file for <strong>"' + (img.asset_name or 'Untitled') + '"</strong>. '
                            'Our team is reviewing it and will notify you of the outcome within <strong>48 hours</strong>.</p>'
                            '<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image remains active and your contest standing is not affected during this review.</p>'
                            '<p style="font-size:14px;color:#8a8070;margin-top:24px;">— Shutter League</p>'
                            '</div>'
                        )
                    )

                # Notify admin — full flag details for human decision
                admin_emails = _admin_notify_emails()
                if not admin_emails:
                    admin_emails = [ADMIN_NOTIFY_EMAIL]
                reasons_html = ''.join(f'<li>{r}</li>' for r in flag_reasons)
                send_email(
                    admin_emails,
                    f'[RAW Review Required] Image #{image_id} — {img.asset_name}',
                    (
                        '<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;">'
                        '<p style="color:#C8A84B;font-weight:700;font-size:15px;">RAW VERIFICATION — HUMAN REVIEW REQUIRED</p>'
                        '<p>The automated system raised flags on this submission. '
                        'No action has been taken and the photographer has NOT been notified of any issue.</p>'
                        '<p><strong>Image:</strong> ' + (img.asset_name or 'Untitled') + ' (ID: ' + str(image_id) + ')<br>'
                        '<strong>Photographer:</strong> ' + (photographer.username if photographer else 'unknown') + ' (' + (photographer.email if photographer else '') + ')<br>'
                        '<strong>Score:</strong> ' + str(img.score) + ' · ' + (img.genre or '') + '</p>'
                        '<p><strong>Flags raised:</strong></p>'
                        '<ul style="color:#C0392B;">' + reasons_html + '</ul>'
                        '<p>Please download and inspect the RAW file manually, then approve or reject from the admin panel.</p>'
                        '<a href="' + site_url + '/admin/raw-verification/' + str(image_id) + '" '
                        'style="display:inline-block;background:#C8A84B;color:#000;padding:12px 24px;'
                        'text-decoration:none;font-weight:700;border-radius:4px;">Review &amp; Decide →</a>'
                        '</div>'
                    )
                )

        except Exception as e:
            app.logger.error(f'[auto_decide_raw] image {image_id}: {e}')
            try:
                db.session.execute(db.text(
                    "UPDATE raw_submissions SET analysis_status='failed' WHERE id=:sid"
                ), {'sid': submission_id})
                db.session.commit()
            except Exception:
                pass


@app.route('/raw/appeal/<int:image_id>', methods=['GET', 'POST'])
@login_required
def raw_appeal(image_id):
    """User submits an appeal against auto-disqualification."""
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)

    submission = db.session.execute(db.text(
        "SELECT * FROM raw_submissions WHERE image_id=:iid ORDER BY submitted_at DESC LIMIT 1"
    ), {'iid': image_id}).fetchone()

    if not submission:
        flash('No RAW submission found for this image.', 'error')
        return redirect(url_for('dashboard'))

    # Must be auto-disqualified and not already appealed
    if submission.auto_decision != 'disqualified':
        flash('This image is not eligible for appeal.', 'info')
        return redirect(url_for('raw_status', image_id=image_id))

    if submission.appeal_submitted_at:
        flash('You have already submitted an appeal for this image. We will notify you once it has been reviewed.', 'info')
        return redirect(url_for('raw_status', image_id=image_id))

    # Check 48hr window
    if submission.auto_decided_at:
        hours_elapsed = (datetime.utcnow() - submission.auto_decided_at).total_seconds() / 3600
        if hours_elapsed > 48:
            flash('The 48-hour appeal window has closed for this image.', 'error')
            return redirect(url_for('raw_status', image_id=image_id))

    if request.method == 'POST':
        # Record the appeal
        db.session.execute(db.text(
            "UPDATE raw_submissions SET appeal_submitted_at=NOW() WHERE image_id=:iid"
        ), {'iid': image_id})
        db.session.commit()

        site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')

        # Notify admin — human review required
        admin_emails = _admin_notify_emails()
        if not admin_emails:
            admin_emails = [ADMIN_NOTIFY_EMAIL]
        send_email(
            admin_emails,
            f'[RAW Appeal] Human Review Required — Image #{image_id} · {img.asset_name}',
            (f'<div style="font-family:Courier New,monospace;max-width:560px;margin:0 auto;padding:32px;">'
             f'<p style="color:#C8A84B;font-weight:700;font-size:16px;">⚠️ RAW APPEAL — HUMAN REVIEW REQUIRED</p>'
             f'<p>Image: <strong>{img.asset_name}</strong> (ID: {image_id})<br>'
             f'Photographer: {current_user.username} ({current_user.email})<br>'
             f'DDI Score: {img.score} · {img.genre}</p>'
             f'<p>Auto-disqualification reasons:<br>'
             f'<strong style="color:#C0392B;">{submission.auto_flag_reasons or "See analysis"}</strong></p>'
             f'<p style="background:#FFF8E1;border:1px solid #C8A84B;border-radius:4px;padding:12px 16px;">'
             f'The photographer has appealed. Please download the RAW file, compare it manually with the submitted image, and make a final decision.</p>'
             f'<a href="{site_url}/admin/raw-verification/{image_id}" '
             f'style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;'
             f'font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;'
             f'text-decoration:none;border-radius:4px;margin:16px 0;">Review &amp; Decide →</a>'
             f'</div>')
        )

        flash('Your appeal has been submitted. Our admin team will review your RAW file manually and notify you of the outcome.', 'success')
        return redirect(url_for('raw_status', image_id=image_id))

    return render_template('raw_appeal.html', img=img, submission=submission)


@app.route('/admin/raw-appeal/<int:image_id>/decide', methods=['POST'])
@login_required
@admin_required
def admin_raw_appeal_decide(image_id):
    """Admin makes final decision on a RAW appeal — uphold or overturn."""
    img = Image.query.get_or_404(image_id)
    decision  = request.form.get('decision', '').strip()  # 'uphold' or 'overturn'
    admin_note = request.form.get('admin_note', '').strip()

    if decision not in ('uphold', 'overturn'):
        flash('Invalid decision.', 'error')
        return redirect(url_for('admin_raw_detail', image_id=image_id))

    photographer = User.query.get(img.user_id)
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')

    db.session.execute(db.text(
        "UPDATE raw_submissions SET appeal_decision=:dec, appeal_decided_at=NOW(), "
        "appeal_admin_note=:note, appeal_decided_by=:by WHERE image_id=:iid"
    ), {'dec': decision, 'note': admin_note or None, 'by': current_user.id, 'iid': image_id})

    if decision == 'uphold':
        # Disqualification confirmed — already disqualified in DB, just notify
        if photographer:
            send_email(
                photographer.email,
                f'Appeal Decision — Disqualification Confirmed · {img.asset_name}',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                 f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">Appeal Decision — Disqualification Confirmed</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Dear {photographer.full_name or photographer.username},</p>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you for appealing the automated disqualification of <strong>"{img.asset_name}"</strong>.</p>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Our admin team has personally downloaded and reviewed your original RAW file against the submitted image. After careful examination, we have determined that the concerns raised by our automated system are valid.</p>'
                 f'<div style="background:#FFF5F5;border:1px solid #FFCCCC;border-radius:6px;padding:16px 20px;margin:16px 0;">'
                 f'<p style="margin:0;font-size:16px;font-weight:700;color:#C0392B;">The disqualification stands.</p>'
                 + (f'<p style="margin:8px 0 0;font-size:15px;color:#4A4840;">Reason: {admin_note}</p>' if admin_note else '')
                 + f'</div>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your account remains active and all your other scores and contest standings are unaffected. You are welcome to continue participating in future contests.</p>'
                 f'<p style="font-size:14px;color:#8a8070;margin-top:24px;">— Shutter League</p>'
                 f'</div>')
            )
        flash(f'Appeal upheld — disqualification of "{img.asset_name}" confirmed. Photographer notified.', 'warning')

    else:
        # Overturn — reinstate the image
        db.session.execute(db.text(
            "UPDATE raw_submissions SET disqualified=FALSE, admin_decision='approved' WHERE image_id=:iid"
        ), {'iid': image_id})
        db.session.execute(db.text(
            "UPDATE images SET raw_verified=TRUE, raw_disqualified=FALSE WHERE id=:iid"
        ), {'iid': image_id})

        if photographer:
            send_email(
                photographer.email,
                f'Appeal Successful — Image Reinstated · {img.asset_name}',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#C8A84B;">Shutter League</p>'
                 f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">Appeal Successful — Image Reinstated</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Dear {photographer.full_name or photographer.username},</p>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Thank you for appealing the automated disqualification of <strong>"{img.asset_name}"</strong>.</p>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Our admin team has personally downloaded and reviewed your original RAW file against the submitted image. After careful examination, we have found that our automated system made an incorrect assessment.</p>'
                 f'<div style="background:#F0F7F0;border:1px solid #4CAF50;border-radius:6px;padding:16px 20px;margin:16px 0;">'
                 f'<p style="margin:0;font-size:16px;font-weight:700;color:#2E7D32;">The disqualification has been overturned. Your image is reinstated. ✓</p>'
                 f'</div>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your result and DDI score of <strong>{img.score}</strong> stand confirmed. We apologise for the inconvenience caused by the automated flag.</p>'
                 f'<p style="font-size:14px;color:#8a8070;margin-top:24px;">— Shutter League</p>'
                 f'</div>')
            )
        flash(f'Appeal overturned — "{img.asset_name}" reinstated. Photographer notified.', 'success')

    db.session.commit()
    return redirect(url_for('admin_raw_detail', image_id=image_id))


# ---------------------------------------------------------------------------
# Winner notification + RAW window trigger
# ---------------------------------------------------------------------------

@app.route('/admin/contest/notify-winners', methods=['POST'])
@login_required
@admin_required
def admin_notify_winners():
    """
    Notify contest winners and open RAW verification window.
    Two modes:
    - auto: system fetches top N images per genre from contest entries / judge scores
    - manual: admin supplies comma-separated image IDs (fallback / override)
    """
    contest_ref   = request.form.get('contest_ref', '').strip()
    contest_type  = request.form.get('contest_type', 'weekly')
    top_n         = request.form.get('top_n', 3, type=int)   # top N per genre to notify
    manual_ids    = request.form.get('winner_image_ids', '').strip()
    raw_hours     = request.form.get('raw_hours', 48, type=int)

    if not contest_ref:
        flash('Contest reference is required.', 'error')
        return redirect(url_for('admin_judge_config'))

    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    deadline = datetime.utcnow() + timedelta(hours=raw_hours)

    # -- Determine winner image IDs ----------------------------------------
    winner_image_ids = []

    if manual_ids:
        # Manual override -- admin supplied IDs directly
        for part in manual_ids.split(','):
            part = part.strip()
            if part.isdigit():
                winner_image_ids.append(int(part))
    else:
        # Auto-detect: top N per genre
        # Priority 1: judge_final_score (if jury contest has been computed)
        # Priority 2: DDI score (for monthly/community contests)
        # For each genre, pick top N unique images by best available score
        genres_found = db.session.execute(db.text(
            "SELECT DISTINCT genre FROM images "
            "WHERE status='scored' AND score IS NOT NULL "
            "AND is_flagged=FALSE AND needs_review=FALSE"
        )).fetchall()

        for genre_row in genres_found:
            genre = genre_row.genre
            if not genre:
                continue

            # Try jury-scored images for this contest first
            jury_top = db.session.execute(db.text(
                "SELECT DISTINCT i.id, i.judge_final_score AS best_score "
                "FROM images i "
                "JOIN judge_assignments ja ON ja.image_id = i.id "
                "WHERE ja.contest_ref=:cr AND ja.contest_type=:ct "
                "AND i.genre=:genre AND i.judge_final_score IS NOT NULL "
                "AND i.is_flagged=FALSE "
                "ORDER BY i.judge_final_score DESC LIMIT :n"
            ), {'cr': contest_ref, 'ct': contest_type, 'genre': genre, 'n': top_n}).fetchall()

            if jury_top:
                winner_image_ids.extend([r.id for r in jury_top])
            else:
                # Fall back to DDI score for this genre
                ddi_top = db.session.execute(db.text(
                    "SELECT id FROM images "
                    "WHERE status='scored' AND genre=:genre "
                    "AND score IS NOT NULL AND is_flagged=FALSE AND needs_review=FALSE "
                    "ORDER BY score DESC LIMIT :n"
                ), {'genre': genre, 'n': top_n}).fetchall()
                winner_image_ids.extend([r.id for r in ddi_top])

    if not winner_image_ids:
        flash('No eligible images found for this contest. Check contest ref or use manual IDs.', 'warning')
        return redirect(url_for('admin_judge_config'))

    # Deduplicate
    winner_image_ids = list(dict.fromkeys(winner_image_ids))

    notified = 0
    for image_id in winner_image_ids:
        img          = Image.query.get(image_id)
        photographer = User.query.get(img.user_id) if img else None
        if not img or not photographer:
            continue

        img.raw_verification_required = True
        img.contest_result_status     = 'provisional'

        db.session.execute(db.text(
            "INSERT INTO raw_submissions "
            "(image_id, user_id, contest_ref, contest_type, deadline, analysis_status) "
            "VALUES (:iid, :uid, :cr, :ct, :dl, 'awaiting') "
            "ON CONFLICT (image_id, contest_ref, contest_type) DO UPDATE SET deadline=:dl"
        ), {'iid': image_id, 'uid': img.user_id, 'cr': contest_ref, 'ct': contest_type, 'dl': deadline})

        send_email(
            photographer.email,
            f'Congratulations -- provisional winner in {contest_ref}',
            (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
             f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
             f'<h2>Congratulations, {photographer.full_name or photographer.username}.</h2>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Your image <strong>"{img.asset_name}"</strong> ({img.genre}) has achieved a provisional winning position in <strong>{contest_ref}</strong>.</p>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">To confirm your result, submit the original RAW file within <strong>{raw_hours} hours</strong>.</p>'
             f'<a href="{site_url}/raw/submit/{contest_type}/{image_id}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:14px 28px;text-decoration:none;border-radius:4px;margin:16px 0;">Submit RAW File</a>'
             f'<p style="font-size:14px;color:#8a8070;">Deadline: {deadline.strftime("%d %B %Y, %H:%M UTC")} ({raw_hours} hours from now). Results will not be published until RAW verification is complete.</p>'
             f'</div>')
        )
        notified += 1

    db.session.commit()
    genre_count = len(genres_found) if not manual_ids else 'manual'
    flash(
        f'{notified} image(s) across {genre_count} genre(s) notified privately. '
        f'RAW window: {raw_hours} hours.',
        'success'
    )
    return redirect(url_for('admin_judge_config'))


# ---------------------------------------------------------------------------
# SLA reminder crons
# ---------------------------------------------------------------------------

@app.route('/admin/cron/judge-reminders', methods=['POST'])
@login_required
@admin_required
def cron_judge_reminders():
    now      = datetime.utcnow()
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    sent_48  = 0
    sent_24  = 0

    for hours, field, label in [(48, 'reminder_48_sent', '48hrs'), (24, 'reminder_24_sent', '24 hours')]:
        due = db.session.execute(db.text(
            f"SELECT ja.judge_id, j.email, j.name, COUNT(*) AS cnt, MIN(ja.deadline) AS dl "
            f"FROM judge_assignments ja JOIN judges j ON j.id=ja.judge_id "
            f"WHERE ja.status='pending' AND ja.deadline IS NOT NULL "
            f"AND ja.deadline BETWEEN :now AND :future AND ja.{field}=FALSE "
            f"GROUP BY ja.judge_id, j.email, j.name"
        ), {'now': now, 'future': now + timedelta(hours=hours)}).fetchall()

        for row in due:
            send_email(
                row.email,
                f'[{"Reminder" if hours==48 else "Final Reminder"}] {row.cnt} image(s) due in {label}',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League  --  Jury</p>'
                 f'<h2 style="font-size:20px;{"color:#C0392B;" if hours==24 else ""}">'
                 f'{"Reminder" if hours==48 else "Final reminder"}: {row.cnt} image(s) to review</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">Deadline: <strong>{row.dl.strftime("%d %B %Y, %H:%M UTC")}</strong></p>'
                 f'<a href="{site_url}/judge/dashboard" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">Review Now</a>'
                 f'</div>')
            )
            db.session.execute(db.text(
                f"UPDATE judge_assignments SET {field}=TRUE "
                f"WHERE judge_id=:jid AND status='pending' AND deadline BETWEEN :now AND :future"
            ), {'jid': row.judge_id, 'now': now, 'future': now + timedelta(hours=hours)})
            if hours == 48:
                sent_48 += 1
            else:
                sent_24 += 1

    db.session.commit()
    return jsonify({'sent_48hr': sent_48, 'sent_24hr': sent_24, 'status': 'ok'})


@app.route('/admin/cron/raw-reminders', methods=['POST'])
@login_required
@admin_required
def cron_raw_reminders():
    now      = datetime.utcnow()
    site_url = os.getenv('SITE_URL', 'https://lens-league-apex-production.up.railway.app')
    sent_48  = 0
    sent_24  = 0
    disq     = 0

    for hours, field, label in [(48, 'reminder_48_sent', '48hrs'), (24, 'reminder_24_sent', '24 hours')]:
        pending = db.session.execute(db.text(
            f"SELECT rs.image_id, rs.contest_type, rs.deadline, i.asset_name, u.email, u.full_name "
            f"FROM raw_submissions rs JOIN images i ON i.id=rs.image_id JOIN users u ON u.id=rs.user_id "
            f"WHERE rs.submitted_at IS NULL AND rs.deadline IS NOT NULL "
            f"AND rs.deadline BETWEEN :now AND :future AND rs.{field}=FALSE AND rs.disqualified=FALSE"
        ), {'now': now, 'future': now + timedelta(hours=hours)}).fetchall()

        for row in pending:
            send_email(
                row.email,
                f'[{"Reminder" if hours==48 else "FINAL"}] RAW for "{row.asset_name}" due in {label}',
                (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
                 f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
                 f'<h2 style="font-size:20px;{"color:#C0392B;" if hours==24 else ""}">RAW file due in {label}</h2>'
                 f'<p style="font-size:16px;line-height:1.7;color:#4A4840;"><strong>"{row.asset_name}"</strong><br>'
                 f'Deadline: <strong>{row.deadline.strftime("%d %B %Y, %H:%M UTC")}</strong></p>'
                 f'<p style="font-size:15px;color:#C0392B;">Failure to submit will result in disqualification.</p>'
                 f'<a href="{site_url}/raw/submit/{row.contest_type}/{row.image_id}" style="display:inline-block;background:#C8A84B;color:#1a1a18;font-family:Courier New,monospace;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:12px 24px;text-decoration:none;border-radius:4px;margin:16px 0;">Submit RAW Now</a>'
                 f'</div>')
            )
            db.session.execute(db.text(
                f"UPDATE raw_submissions SET {field}=TRUE WHERE image_id=:iid"
            ), {'iid': row.image_id})
            if hours == 48:
                sent_48 += 1
            else:
                sent_24 += 1

    # Auto-disqualify overdue
    overdue = db.session.execute(db.text(
        "SELECT rs.image_id, u.email, i.asset_name "
        "FROM raw_submissions rs JOIN images i ON i.id=rs.image_id JOIN users u ON u.id=rs.user_id "
        "WHERE rs.submitted_at IS NULL AND rs.deadline IS NOT NULL "
        "AND rs.deadline < :now AND rs.disqualified=FALSE"
    ), {'now': now}).fetchall()

    for row in overdue:
        db.session.execute(db.text(
            "UPDATE raw_submissions SET disqualified=TRUE WHERE image_id=:iid"
        ), {'iid': row.image_id})
        db.session.execute(db.text(
            "UPDATE images SET raw_disqualified=TRUE WHERE id=:iid"
        ), {'iid': row.image_id})
        send_email(
            row.email,
            f'Your image was not considered for this competition -- RAW file not received',
            (f'<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;padding:32px;color:#1a1a18;">'
             f'<p style="font-family:Courier New,monospace;font-size:12px;letter-spacing:2px;color:#C8A84B;text-transform:uppercase;">Shutter League</p>'
             f'<h2 style="font-size:22px;font-weight:700;margin-bottom:16px;">We are sorry -- your image could not be considered</h2>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">We regret to inform you that your image <strong>"{row.asset_name}"</strong> was not considered for this competition because the RAW file was not received within the required deadline.</p>'
             f'<p style="font-size:16px;line-height:1.7;color:#4A4840;">RAW verification is a mandatory step for all provisional winners to confirm the authenticity of the original photograph. Without it, we are unable to confirm your result.</p>'
             f'<div style="background:#F5F0E8;border-left:3px solid #C8A84B;padding:16px 20px;margin:20px 0;font-size:16px;color:#4A4840;line-height:1.7;">'
             f'<strong style="color:#1a1a18;">You are welcome to continue competing.</strong> The same image may be entered again in future contests. If your image achieves a provisional winning position, please ensure you submit your RAW file within the timeframe stated in the notification email.'
             f'</div>'
             f'<p style="font-size:15px;color:#8A8478;line-height:1.7;">If you believe this notice was sent in error, please write to <a href="mailto:'+CONTACT_EMAIL+'" style="color:#C8A84B;">'+CONTACT_EMAIL+'</a> within 48 hours.</p>'
             f'<p style="font-size:14px;color:#8A8478;margin-top:24px;">Your account remains active and your DDI scores are unaffected.</p>'
             f'</div>')
        )
        disq += 1

    db.session.commit()
    return jsonify({'sent_48hr': sent_48, 'sent_24hr': sent_24, 'disqualified': disq, 'status': 'ok'})



# ===========================================================================
# Weekly results announcement  -  sent to all active users
# ===========================================================================

def send_results_announcement(challenge, winners):
    """Send weekly results email to all active users."""
    users = User.query.filter_by(is_active=True).filter(
        User.email != None, User.email != ''
    ).all()
    if not users:
        return 0

    site_url    = os.getenv('SITE_URL', 'https://shutterleague.com')
    results_url = site_url + '/challenge/results/' + challenge.week_ref
    ordinals    = {1: '1st', 2: '2nd', 3: '3rd'}

    winners_html = ''
    for w in sorted(winners, key=lambda x: x.result_rank):
        img       = w.image
        owner     = User.query.get(w.user_id) if w.user_id else None
        name      = (owner.full_name or owner.username) if owner else 'Photographer'
        score_str = str(img.score) if img and img.score else ''
        winners_html += (
            '<tr>'
            '<td style="padding:10px 16px;font-family:Courier New,monospace;font-size:13px;'
            'font-weight:700;color:#C8A84B;width:48px;">' + ordinals[w.result_rank] + '</td>'
            '<td style="padding:10px 16px;font-size:15px;color:#1a1a18;">'
            + (img.asset_name if img else 'Untitled') +
            '</td>'
            '<td style="padding:10px 16px;font-size:14px;color:#6a6458;">' + name + '</td>'
            '<td style="padding:10px 16px;font-family:Courier New,monospace;font-size:13px;'
            'color:#8a8070;">' + score_str + '</td>'
            '</tr>'
        )

    sent = 0
    for user in users:
        html_body = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
            '<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">'
            '<table width="100%" cellpadding="0" cellspacing="0"'
            ' style="background:#F5F0E8;padding:32px 16px;"><tr><td align="center">'
            '<table width="560" cellpadding="0" cellspacing="0"'
            ' style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;'
            'overflow:hidden;max-width:560px;width:100%;">'
            '<tr><td style="background:#1a1a18;padding:24px 32px;">'
            '<p style="margin:0;font-family:Courier New,monospace;font-size:13px;'
            'font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">'
            'SHUTTER LEAGUE</p></td></tr>'
            '<tr><td style="background:#1a1a18;padding:0 32px 28px;">'
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:11px;'
            'letter-spacing:2px;color:#6a6458;text-transform:uppercase;">'
            'Results . ' + challenge.week_ref + '</p>'
            '<h1 style="margin:0;font-size:30px;font-style:italic;color:#C8A84B;line-height:1.1;">'
            + challenge.prompt_title + '</h1></td></tr>'
            '<tr><td style="padding:28px 32px;">'
            '<p style="margin:0 0 20px;font-size:16px;color:#4A4840;line-height:1.6;">'
            'The results are in. Here are this week&#39;s top photographers:</p>'
            '<table width="100%" cellpadding="0" cellspacing="0"'
            ' style="border:1px solid #E0D8C8;border-radius:6px;overflow:hidden;margin-bottom:24px;">'
            + winners_html +
            '</table>'
            '<a href="' + results_url + '"'
            ' style="display:inline-block;background:#C8A84B;color:#1a1a18;'
            'font-family:Courier New,monospace;font-size:14px;font-weight:700;'
            'letter-spacing:1px;text-transform:uppercase;padding:14px 28px;'
            'text-decoration:none;border-radius:4px;">See Full Results</a>'
            '</td></tr>'
            '<tr><td style="padding:20px 32px;border-top:1px solid #E0D8C8;">'
            '<p style="margin:0;font-size:13px;color:#8a8070;line-height:1.6;">'
            'You&#39;re receiving this because you have an account on Shutter League.<br>'
            '<a href="' + site_url + '" style="color:#C8A84B;">shutterleague.com</a>'
            '</p></td></tr>'
            '</table></td></tr></table></body></html>'
        )
        text_body = (
            'SHUTTER LEAGUE  -  Weekly Results\n\n'
            'Challenge: ' + challenge.prompt_title + ' (' + challenge.week_ref + ')\n\n'
        )
        for w in sorted(winners, key=lambda x: x.result_rank):
            img2  = w.image
            own2  = User.query.get(w.user_id) if w.user_id else None
            nam2  = (own2.full_name or own2.username) if own2 else 'Photographer'
            text_body += (
                ordinals[w.result_rank] + ': '
                + (img2.asset_name if img2 else 'Untitled')
                + '  -  ' + nam2 + '\n'
            )
        text_body += '\nSee full results: ' + results_url + '\n\n -  Shutter League'

        if send_email(
            user.email,
            'Results: ' + challenge.prompt_title + ' (' + challenge.week_ref + ')',
            html_body,
            text_body
        ):
            sent += 1

    return sent


def send_winners_email(challenge, winners):
    """
    Send a personalised congratulations email to each of the top-3 winners.
    Called immediately after ranking in auto_publish_weekly_challenge.
    Each winner gets their rank, image title, score, and a link to the results page.
    """
    site_url    = os.getenv('SITE_URL', 'https://shutterleague.com')
    results_url = site_url + '/challenge/results/' + challenge.week_ref
    ordinals    = {1: '1st', 2: '2nd', 3: '3rd'}
    medals      = {1: '🥇', 2: '🥈', 3: '🥉'}

    sent = 0
    for w in sorted(winners, key=lambda x: x.result_rank):
        owner = User.query.get(w.user_id) if w.user_id else None
        if not owner or not owner.email:
            continue
        img       = w.image
        name      = owner.full_name or owner.username
        rank_str  = ordinals.get(w.result_rank, str(w.result_rank))
        medal     = medals.get(w.result_rank, '')
        img_title = img.asset_name if img else 'Your image'
        score_str = str(img.score) if img and img.score else ''
        score_line = (
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:13px;'
            'letter-spacing:1px;color:#8a8070;">DDI Score: '
            + score_str + '</p>'
        ) if score_str else ''

        html_body = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
            '<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">'
            '<table width="100%" cellpadding="0" cellspacing="0"'
            ' style="background:#F5F0E8;padding:32px 16px;"><tr><td align="center">'
            '<table width="560" cellpadding="0" cellspacing="0"'
            ' style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;'
            'overflow:hidden;max-width:560px;width:100%;">'

            '<tr><td style="background:#1a1a18;padding:24px 32px;">'
            '<p style="margin:0;font-family:Courier New,monospace;font-size:13px;'
            'font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">'
            'SHUTTER LEAGUE</p></td></tr>'

            '<tr><td style="background:#1a1a18;padding:0 32px 28px;">'
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:11px;'
            'letter-spacing:2px;color:#6a6458;text-transform:uppercase;">'
            'Weekly Challenge . ' + challenge.week_ref + '</p>'
            '<h1 style="margin:0;font-size:30px;font-style:italic;color:#C8A84B;line-height:1.1;">'
            + medal + ' You placed ' + rank_str + '</h1>'
            '</td></tr>'

            '<tr><td style="padding:32px 32px 24px;">'
            '<p style="margin:0 0 20px;font-size:17px;color:#1a1a18;line-height:1.6;">'
            'Congratulations, ' + name + '.</p>'
            '<p style="margin:0 0 24px;font-size:16px;color:#4A4840;line-height:1.6;">'
            'Your photograph <strong style="color:#1a1a18;">' + img_title + '</strong> '
            'placed <strong style="color:#C8A84B;">' + rank_str + '</strong> in this week&#39;s '
            '<em>' + challenge.prompt_title + '</em> challenge.'
            '</p>'

            '<table cellpadding="0" cellspacing="0"'
            ' style="background:#F5F0E8;border:1px solid #E0D8C8;border-radius:6px;'
            'padding:16px 20px;margin-bottom:28px;width:100%;">'
            '<tr><td>'
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:13px;'
            'letter-spacing:1px;color:#8a8070;">Challenge: ' + challenge.prompt_title + '</p>'
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:13px;'
            'letter-spacing:1px;color:#8a8070;">Week: ' + challenge.week_ref + '</p>'
            '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:13px;'
            'letter-spacing:1px;color:#8a8070;">Image: ' + img_title + '</p>'
            + score_line +
            '<p style="margin:0;font-family:Courier New,monospace;font-size:14px;'
            'font-weight:700;letter-spacing:1px;color:#C8A84B;">Rank: '
            + medal + ' ' + rank_str + '</p>'
            '</td></tr></table>'

            '<a href="' + results_url + '"'
            ' style="display:inline-block;background:#C8A84B;color:#1a1a18;'
            'font-family:Courier New,monospace;font-size:14px;font-weight:700;'
            'letter-spacing:1px;text-transform:uppercase;padding:14px 28px;'
            'text-decoration:none;border-radius:4px;">View Full Results</a>'
            '</td></tr>'

            '<tr><td style="padding:20px 32px;border-top:1px solid #E0D8C8;">'
            '<p style="margin:0;font-size:13px;color:#8a8070;line-height:1.6;">'
            'You&#39;re receiving this because you placed in a Shutter League weekly challenge.<br>'
            '<a href="' + site_url + '" style="color:#C8A84B;">shutterleague.com</a>'
            '</p></td></tr>'

            '</table></td></tr></table></body></html>'
        )

        text_body = (
            'SHUTTER LEAGUE  -  ' + medal + ' You placed ' + rank_str + '!\n\n'
            'Congratulations, ' + name + '.\n\n'
            'Your photograph "' + img_title + '" placed ' + rank_str
            + ' in the ' + challenge.prompt_title + ' challenge (' + challenge.week_ref + ').\n'
        )
        if score_str:
            text_body += 'DDI Score: ' + score_str + '\n'
        text_body += '\nSee full results: ' + results_url + '\n\n -  Shutter League'

        if send_email(
            owner.email,
            medal + ' You placed ' + rank_str + ' — ' + challenge.prompt_title,
            html_body,
            text_body
        ):
            sent += 1
            app.logger.info(
                '[winners_email] Sent to ' + owner.email
                + ' (' + rank_str + ' — ' + img_title + ')'
            )

    return sent



def send_welcome_email(user):
    """
    Send a welcome email to a new user after they complete onboarding.
    Confirms T&C acceptance, links to dashboard, upload, how-it-works, challenge, support.
    """
    site_url     = os.getenv('SITE_URL', 'https://shutterleague.com')
    name         = user.full_name or user.username
    dashboard_url = site_url + '/dashboard'
    upload_url    = site_url + '/upload'
    hiw_url       = site_url + '/how-it-works'
    challenge_url = site_url + '/challenge'
    terms_url     = site_url + '/terms'
    accepted_date = user.terms_accepted_at.strftime('%d %b %Y') if user.terms_accepted_at else 'today'

    html_body = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#F5F0E8;font-family:Georgia,serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0"'
        ' style="background:#F5F0E8;padding:32px 16px;"><tr><td align="center">'
        '<table width="560" cellpadding="0" cellspacing="0"'
        ' style="background:#ffffff;border:1px solid #E0D8C8;border-radius:8px;'
        'overflow:hidden;max-width:560px;width:100%;">'

        '<tr><td style="background:#1a1a18;padding:24px 32px;">'
        '<p style="margin:0;font-family:Courier New,monospace;font-size:13px;'
        'font-weight:700;letter-spacing:3px;color:#C8A84B;text-transform:uppercase;">'
        'SHUTTER LEAGUE</p></td></tr>'

        '<tr><td style="background:#1a1a18;padding:0 32px 28px;">'
        '<p style="margin:0 0 6px;font-family:Courier New,monospace;font-size:11px;'
        'letter-spacing:2px;color:#6a6458;text-transform:uppercase;">Welcome</p>'
        '<h1 style="margin:0;font-size:28px;font-style:italic;color:#C8A84B;line-height:1.2;">'
        'You&#39;re in, ' + name + '.</h1>'
        '</td></tr>'

        '<tr><td style="padding:32px 32px 8px;">'
        '<p style="margin:0 0 20px;font-size:16px;color:#4A4840;line-height:1.7;">'
        'Your account is live. Get scored. See what to improve. Compete when ready.</p>'

        '<table cellpadding="0" cellspacing="0"'
        ' style="background:#F5F0E8;border:1px solid #E0D8C8;border-radius:6px;'
        'padding:16px 20px;margin-bottom:28px;width:100%;">'
        '<tr><td>'
        '<p style="margin:0 0 4px;font-family:Courier New,monospace;font-size:12px;'
        'letter-spacing:1px;color:#8a8070;text-transform:uppercase;">Agreement confirmed</p>'
        '<p style="margin:0;font-size:14px;color:#1a1a18;">Member Agreement &amp; '
        '<a href="' + terms_url + '" style="color:#C8A84B;">Terms &amp; Conditions</a>'
        ' accepted on ' + accepted_date + '.</p>'
        '</td></tr></table>'

        '<p style="margin:0 0 12px;font-family:Courier New,monospace;font-size:12px;'
        'font-weight:700;letter-spacing:2px;color:#1a1a18;text-transform:uppercase;">'
        'What you can do now</p>'

        '<table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:28px;">'
        '<tr><td style="padding:10px 0;border-bottom:1px solid #E0D8C8;">'
        '<a href="' + upload_url + '" style="text-decoration:none;">'
        '<p style="margin:0;font-size:15px;font-weight:700;color:#1a1a18;">'
        '📸 Upload your first photo</p>'
        '<p style="margin:2px 0 0;font-size:14px;color:#4A4840;">'
        'Get your DDI score — composition, light, emotion, difficulty, all scored.</p>'
        '</a></td></tr>'
        '<tr><td style="padding:10px 0;border-bottom:1px solid #E0D8C8;">'
        '<a href="' + challenge_url + '" style="text-decoration:none;">'
        '<p style="margin:0;font-size:15px;font-weight:700;color:#1a1a18;">'
        '🏆 Enter the weekly challenge</p>'
        '<p style="margin:2px 0 0;font-size:14px;color:#4A4840;">'
        'Submit your best shot. Top 3 win. Results every Monday.</p>'
        '</a></td></tr>'
        '<tr><td style="padding:10px 0;border-bottom:1px solid #E0D8C8;">'
        '<a href="' + dashboard_url + '" style="text-decoration:none;">'
        '<p style="margin:0;font-size:15px;font-weight:700;color:#1a1a18;">'
        '📊 Your dashboard</p>'
        '<p style="margin:2px 0 0;font-size:14px;color:#4A4840;">'
        'Track scores, tier, leaderboard position, and POTY standings.</p>'
        '</a></td></tr>'
        '<tr><td style="padding:10px 0;">'
        '<a href="' + hiw_url + '" style="text-decoration:none;">'
        '<p style="margin:0;font-size:15px;font-weight:700;color:#1a1a18;">'
        '📖 How scoring works</p>'
        '<p style="margin:2px 0 0;font-size:14px;color:#4A4840;">'
        'Understand your DDI score and what each dimension means.</p>'
        '</a></td></tr>'
        '</table>'

        '<a href="' + upload_url + '"'
        ' style="display:inline-block;background:#C8A84B;color:#1a1a18;'
        'font-family:Courier New,monospace;font-size:14px;font-weight:700;'
        'letter-spacing:1px;text-transform:uppercase;padding:14px 28px;'
        'text-decoration:none;border-radius:4px;">Upload Your First Photo &rarr;</a>'
        '</td></tr>'

        '<tr><td style="padding:20px 32px;border-top:1px solid #E0D8C8;margin-top:16px;">'
        '<p style="margin:0;font-size:13px;color:#8a8070;line-height:1.6;">'
        'Questions? Reply to this email or write to '
        '<a href="mailto:info@shutterleague.com" style="color:#C8A84B;">info@shutterleague.com</a>.<br>'
        '<a href="' + site_url + '" style="color:#C8A84B;">shutterleague.com</a>'
        '</p></td></tr>'

        '</table></td></tr></table></body></html>'
    )

    text_body = (
        'SHUTTER LEAGUE  -  Welcome, ' + name + '!\n\n'
        'Your account is live. Get scored. See what to improve. Compete when ready.\n\n'
        'Agreement confirmed: Member Agreement & Terms and Conditions accepted on ' + accepted_date + '.\n\n'
        'WHAT YOU CAN DO NOW\n'
        '- Upload your first photo: ' + upload_url + '\n'
        '- Enter the weekly challenge: ' + challenge_url + '\n'
        '- Your dashboard: ' + dashboard_url + '\n'
        '- How scoring works: ' + hiw_url + '\n\n'
        'Questions? Write to info@shutterleague.com\n\n'
        ' -  Shutter League'
    )
    if send_email(user.email, 'Welcome to Shutter League — you are in', html_body, text_body):
        app.logger.info('[welcome_email] Sent to ' + user.email)
    else:
        app.logger.warning('[welcome_email] Failed to send to ' + user.email)


# ===========================================================================
# Scheduled jobs
# ===========================================================================

def auto_publish_weekly_challenge():
    """
    Cron: every Monday 13:30 UTC (7:00 PM IST).
    Finds most recently closed challenge, auto-ranks top 3 by DDI score
    (subscribers prioritised), emails results to all users + admin reminder.
    Skips silently if results already manually published.
    """
    with app.app_context():
        try:
            now = datetime.utcnow()
            app.logger.info('[cron] auto_publish_weekly_challenge running')

            challenge = (WeeklyChallenge.query
                         .filter(WeeklyChallenge.closes_at < now,
                                 WeeklyChallenge.is_active == True)
                         .order_by(WeeklyChallenge.closes_at.desc())
                         .first())

            if not challenge:
                app.logger.info('[cron] No closed challenge found - skipping')
                _send_admin_reminder(now)
                return

            already_ranked = WeeklySubmission.query.filter(
                WeeklySubmission.challenge_id == challenge.id,
                WeeklySubmission.result_rank != None
            ).count()

            if already_ranked > 0:
                app.logger.info(
                    '[cron] ' + challenge.week_ref + ' already ranked - skipping'
                )
                _send_admin_reminder(now)
                return

            all_subs = (WeeklySubmission.query
                        .filter_by(challenge_id=challenge.id)
                        .join(Image, WeeklySubmission.image_id == Image.id)
                        .filter(Image.score != None,
                                Image.is_flagged == False,
                                Image.needs_review == False)
                        .order_by(
                            WeeklySubmission.is_subscriber.desc(),
                            Image.score.desc()
                        )
                        .all())

            if not all_subs:
                app.logger.info(
                    '[cron] ' + challenge.week_ref + ' has no scoreable submissions - skipping'
                )
                _send_admin_reminder(now)
                return

            ranked     = []
            seen_users = set()
            rank       = 1
            for sub in all_subs:
                if sub.user_id in seen_users:
                    continue
                sub.result_rank = rank
                ranked.append(sub)
                seen_users.add(sub.user_id)
                rank += 1
                if rank > 3:
                    break

            db.session.commit()
            app.logger.info(
                '[cron] ' + challenge.week_ref + ' - ranked ' + str(len(ranked)) + ' winners'
            )

            sent = send_results_announcement(challenge, ranked)
            app.logger.info('[cron] Results announcement sent to ' + str(sent) + ' users')

            wsent = send_winners_email(challenge, ranked)
            app.logger.info('[cron] Winners emails sent to ' + str(wsent) + ' winners')

            _send_admin_reminder(now)

        except Exception as e:
            app.logger.error('[cron] auto_publish_weekly_challenge error: ' + str(e))
            try:
                db.session.rollback()
            except Exception:
                pass


def _send_admin_reminder(now):
    """Email admin to create next week's challenge."""
    try:
        site_url      = os.getenv('SITE_URL', 'https://shutterleague.com')
        next_week_ref = _next_week_ref(now)
        send_email(
            [ADMIN_EMAIL],
            '[Shutter League] Create next week\'s challenge - ' + next_week_ref,
            (
                '<div style="font-family:Courier New,monospace;max-width:560px;'
                'margin:0 auto;padding:32px;color:#1a1a18;">'
                '<p style="font-weight:700;color:#C8A84B;font-size:15px;'
                'letter-spacing:2px;text-transform:uppercase;">'
                'Shutter League  -  Admin Reminder</p>'
                '<h2 style="font-size:20px;margin-bottom:12px;">'
                'Create this week\'s challenge</h2>'
                '<p style="font-size:15px;line-height:1.7;color:#4A4840;">'
                'It&#39;s Monday evening. Results have been published.<br>'
                'Please create the challenge for <strong>' + next_week_ref + '</strong>.</p>'
                '<a href="' + site_url + '/admin/weekly-challenge"'
                ' style="display:inline-block;background:#C8A84B;color:#1a1a18;'
                'font-family:Courier New,monospace;font-size:13px;font-weight:700;'
                'letter-spacing:1px;text-transform:uppercase;padding:12px 24px;'
                'text-decoration:none;border-radius:4px;margin:16px 0;">'
                'Create Challenge</a>'
                '</div>'
            ),
            (
                'Shutter League Admin Reminder\n\n'
                'Create challenge for ' + next_week_ref + '.\n'
                + site_url + '/admin/weekly-challenge'
            )
        )
        app.logger.info('[cron] Admin reminder sent for ' + next_week_ref)
    except Exception as e:
        app.logger.error('[cron] Admin reminder failed: ' + str(e))


def _next_week_ref(now):
    """Return ISO week ref for the week after the given datetime."""
    days_ahead  = (7 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    next_monday = now + timedelta(days=days_ahead)
    iso         = next_monday.isocalendar()
    return str(iso[0]) + '-W' + str(iso[1]).zfill(2)


# ---------------------------------------------------------------------------
# Start APScheduler - only in main worker, not Flask reloader child process
# ---------------------------------------------------------------------------
@app.route('/admin/cron/test-weekly-results', methods=['POST'])
@login_required
@admin_required
def admin_test_weekly_results():
    """Manually trigger the weekly results cron for testing. Admin only."""
    import threading
    t = threading.Thread(target=auto_publish_weekly_challenge, daemon=True)
    t.start()
    flash('Weekly results cron triggered - check Railway logs for output.', 'success')
    return redirect(url_for('admin_weekly_challenge'))


# Scheduler starts once in the master process via --preload Gunicorn flag.
# Workers fork after this runs, so the scheduler is inherited, not duplicated.
if True:
    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(
        func             = auto_publish_weekly_challenge,
        trigger          = CronTrigger(day_of_week='mon', hour=13, minute=30, timezone='UTC'),
        id               = 'weekly_results',
        name             = 'Auto-publish weekly challenge results',
        replace_existing = True,
    )
    _scheduler.start()
    import atexit as _atexit
    _atexit.register(lambda: _scheduler.shutdown(wait=False))


if __name__ == '__main__':
    app.run(debug=True)
