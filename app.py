"""
app.py — Making Images Matter (MIM) Platform
Version: Session 160.7 · 2026-07-25
makingimagesmatter.com — Railway service (separate from shutterleague.com)

Changes in 159.8:
- _pull_ddi_for_image(): passes session theme to SL /api/mim-ddi?theme=REFLECTION
  SL engine now returns ddi_theme (float 1–10) + ddi_theme_paragraph (coaching sentence)
  Theme paragraph appended to ddi_narrative so it surfaces on reveal screen.
  Timeout increased to 30s (theme scoring adds ~10s to SL response time).

Changes in 159.7:
- _make_token(): strips visually ambiguous chars (l, I, 1, O, 0) from session tokens
  so eval links shared via WhatsApp are always unambiguous.

Rules:
- No Shutter League branding during eval phase
- Blind evaluation — no names on images
- File number as identity during session
- KYC language: evaluation/standing — never score/prize/winner/contest/rank
- sl_audit.py clean before every deploy
- No Railway push without founder approval
"""

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file, make_response
)
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os, secrets, json, io, csv

_IST = timedelta(hours=5, minutes=30)

# ── Token generation — ambiguity-safe ─────────────────────────────────────────
# base64url chars include l (lowercase-L), I (uppercase-i), 1, O, 0 which are
# visually identical in most fonts. Session tokens appear in WhatsApp links —
# a misread char causes a 404. Strip all ambiguous chars and regenerate until clean.
_AMBIGUOUS = set('lI1O0')

def _make_token(nbytes=8):
    """Return a url-safe token with no visually ambiguous characters."""
    while True:
        t = secrets.token_urlsafe(nbytes)
        if not any(c in _AMBIGUOUS for c in t):
            return t

def _to_ist(dt):
    """Convert a UTC datetime to IST. Safe on None."""
    if dt is None:
        return None
    return dt + _IST

app = Flask(__name__)

# ── IST Jinja2 filter — use {{ reg.created_at | ist }} in templates ───────────
@app.template_filter('ist')
def _jinja_ist(dt, fmt='%d %b %Y %H:%M'):
    """Convert UTC datetime to IST string. {{ some_dt | ist }}"""
    if dt is None:
        return '—'
    return (dt + _IST).strftime(fmt)

# Ensure Flask logs appear in gunicorn — S153
import logging
gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)
app.secret_key = os.environ.get('MIM_SECRET_KEY', secrets.token_hex(32))
# Railway Postgres URLs start with postgres:// — SQLAlchemy needs postgresql://
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///mim.db')
# Railway provides postgres:// — SQLAlchemy needs postgresql://
# Use pg8000 driver (pure Python, no libpq needed) for Postgres
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql+pg8000://', 1)
elif _db_url.startswith('postgresql://'):
    _db_url = _db_url.replace('postgresql://', 'postgresql+pg8000://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB

# Shutter League API base URL — for DDI pull by original_filename
SL_API_URL = os.environ.get('SL_API_URL', 'https://shutterleague.com')

# Admin/test emails — always saved as waitlist, never consume a seat.
# Add emails here to test without affecting capacity. Works all cities.
TEST_EMAILS = {
    'sreeks@gmail.com',
    'sree@shutterleague.com',
    'sree@thelivinglens.org',
    'test@makingimagesmatter.com',
    'sreelivinglens@gmail.com',   # founder account — S156 fix
}

db = SQLAlchemy(app)

# ── Models ────────────────────────────────────────────────────────────────────

class MIMSession(db.Model):
    __tablename__ = 'mim_sessions'

    id           = db.Column(db.Integer, primary_key=True)
    token        = db.Column(db.String(12), unique=True, nullable=False, index=True)
    title        = db.Column(db.String(120), nullable=False)   # e.g. "MIM · Bengaluru · 19 Jul"
    theme        = db.Column(db.String(80),  nullable=False)   # e.g. "SILENCE"
    genre        = db.Column(db.String(80),  nullable=False)   # e.g. "Street"
    event_date   = db.Column(db.Date,        nullable=False)
    city         = db.Column(db.String(80),  nullable=False)
    total_images = db.Column(db.Integer,     nullable=False, default=10)
    capacity     = db.Column(db.Integer,     nullable=False, default=10)   # max registrations
    status       = db.Column(db.String(20),  nullable=False, default='setup')
    # setup → eval_open → eval_closed → published
    created_at   = db.Column(db.DateTime,    default=datetime.utcnow)
    published_at         = db.Column(db.DateTime, nullable=True)
    reveal_current_image = db.Column(db.Integer,  nullable=True, default=0)
    registration_closed  = db.Column(db.Boolean,  nullable=False, default=False)
    is_live              = db.Column(db.Boolean,  nullable=False, default=False)  # shows on /register
    go_live_at           = db.Column(db.DateTime, nullable=True)   # auto go-live datetime
    is_test              = db.Column(db.Boolean,  nullable=False, default=False)  # never shows on /register

    images       = db.relationship('MIMImage',      backref='mim_session', lazy=True)
    evaluations  = db.relationship('MIMEvaluation', backref='mim_session', lazy=True)


class MIMImage(db.Model):
    __tablename__ = 'mim_images'

    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('mim_sessions.id'), nullable=False)
    file_number  = db.Column(db.Integer, nullable=False)   # 1–N, shown to evaluators
    filename         = db.Column(db.String(255), nullable=True)
    original_filename = db.Column(db.String(255), nullable=True)  # original name from camera, for SL DDI pull
    upload_token      = db.Column(db.String(32),  nullable=True, unique=True)  # single-use token for self-upload URL
    uploaded_by_self  = db.Column(db.Boolean, default=False)  # True = photographer uploaded themselves
    # DDI scores — filled after reveal
    ddi_craft      = db.Column(db.Float, nullable=True)
    ddi_theme      = db.Column(db.Float, nullable=True)
    ddi_score      = db.Column(db.Float, nullable=True)   # combined
    ddi_narrative  = db.Column(db.Text,  nullable=True)   # Sherpa block
    ddi_dimensions = db.Column(db.Text,  nullable=True)   # JSON: {"DoD":6.8,"Disruption":8.1,...} Session 155
    # Photographer identity — revealed after eval
    photographer_name = db.Column(db.String(120), nullable=True)
    sl_username       = db.Column(db.String(80),  nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    evaluations = db.relationship('MIMEvaluation', backref='mim_image', lazy=True)


class MIMEvaluation(db.Model):
    __tablename__ = 'mim_evaluations'

    id              = db.Column(db.Integer, primary_key=True)
    session_id      = db.Column(db.Integer, db.ForeignKey('mim_sessions.id'), nullable=False)
    image_id        = db.Column(db.Integer, db.ForeignKey('mim_images.id'),   nullable=False)
    evaluator_file_number = db.Column(db.Integer, nullable=False)  # who evaluated (their file number)
    theme_score     = db.Column(db.Integer, nullable=False)   # 1–10
    craft_score     = db.Column(db.Integer, nullable=False)   # 1–10
    what_worked     = db.Column(db.Text,    nullable=False)
    what_to_change  = db.Column(db.Text,    nullable=False)
    submitted_at    = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('image_id', 'evaluator_file_number',
                            name='uq_eval_image_evaluator'),
    )




class MIMRegistration(db.Model):
    __tablename__ = 'mim_registrations'
    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('mim_sessions.id'), nullable=True)
    is_waitlist  = db.Column(db.Boolean, default=False)   # True = next session interest
    full_name    = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(120), nullable=False)
    mobile       = db.Column(db.String(20),  nullable=False)
    address      = db.Column(db.Text,        nullable=True)
    experience   = db.Column(db.String(80),  nullable=True)
    created_at   = db.Column(db.DateTime,    default=datetime.utcnow)

# ── Admin auth (simple password, env-controlled) ──────────────────────────────

ADMIN_PASSWORD   = os.environ.get('MIM_ADMIN_PASSWORD', 'changeme')
ADMIN_PASSWORD_2 = os.environ.get('MIM_ADMIN_PASSWORD_2', '')   # Unni — Session 155


def send_email(to_email, subject, html_body):
    """Send email via Brevo HTTP API — replaces SMTP (port blocked on Railway). Session 153."""
    try:
        api_key = os.environ.get('BREVO_API_KEY', '') or os.environ.get('BREVO_SMTP_KEY', '')
        smtp_login = os.environ.get('BREVO_SMTP_LOGIN', 'b2a1a3001@smtp-brevo.com')
        if not api_key:
            app.logger.warning('[send_email] BREVO_SMTP_KEY not set')
            return False

        import urllib.request, json as _json
        payload = _json.dumps({
            'sender':   {'name': 'Making Images Matter', 'email': 'noreply@makingimagesmatter.com'},
            'to':       [{'email': to_email}],
            'subject':  subject,
            'htmlContent': html_body,
        }).encode('utf-8')

        app.logger.warning(f'[send_email] Calling Brevo API for {to_email} subject={subject[:30]}')
        req = urllib.request.Request(
            'https://api.brevo.com/v3/smtp/email',
            data=payload,
            headers={
                'accept':       'application/json',
                'api-key':      api_key,
                'content-type': 'application/json',
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode('utf-8', errors='ignore')
            app.logger.warning(f'[send_email] Brevo API → {status} to {to_email} body={body[:100]}')
            return status in (200, 201)
    except Exception as e:
        app.logger.error(f'[send_email] Brevo API error: {e}')
        return False

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('mim_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated



# ── Registration ─────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Pick the session explicitly marked as live for registration.
    # is_live=True is set manually by admin OR auto-triggered by go_live_at scheduler.
    # Test sessions (is_test=True) are never shown here.
    # This is the ONLY correct way — no date ordering, no status guessing.
    _now = datetime.utcnow()

    # Auto-trigger go_live_at — if a scheduled session's time has passed, set it live
    _scheduled = MIMSession.query.filter(
        MIMSession.go_live_at <= _now,
        MIMSession.is_live == False,
        MIMSession.is_test == False,
        MIMSession.status == 'setup'
    ).order_by(MIMSession.go_live_at.asc()).first()
    if _scheduled:
        # Clear any existing live session first
        MIMSession.query.filter_by(is_live=True).update({'is_live': False})
        _scheduled.is_live = True
        db.session.commit()

    s = MIMSession.query.filter(
        MIMSession.is_live == True,
        MIMSession.is_test == False,
        MIMSession.status == 'setup'
    ).first()

    # Capacity check — count confirmed (non-waitlist) registrations for this session
    reg_count = 0
    capacity  = 10  # default
    seats_full = False
    if s:
        capacity  = s.capacity or 10
        reg_count = MIMRegistration.query.filter_by(
            session_id=s.id, is_waitlist=False
        ).count()
        seats_full = reg_count >= capacity or bool(getattr(s, 'registration_closed', False))

    if request.method == 'POST':
        full_name  = request.form.get('full_name', '').strip()
        email      = request.form.get('email', '').strip()
        mobile     = request.form.get('mobile', '').strip()
        address    = request.form.get('address', '').strip()
        experience = request.form.get('experience', '').strip()
        is_waitlist_form = request.form.get('is_waitlist', '0') == '1'

        # Admin/test email bypass — never consumes a seat, always waitlist
        # Works for all sessions and cities. No DB touching required.
        if email.lower().strip() in TEST_EMAILS:
            is_waitlist_form = True

        if not full_name or not email or not mobile:
            flash('Please fill in all required fields.')
            return render_template('register.html', s=s, seats_full=seats_full, reg_count=reg_count, capacity=capacity)

        # Re-check capacity at submit time (race condition guard)
        if s:
            current_count = MIMRegistration.query.filter_by(
                session_id=s.id, is_waitlist=False
            ).count()
            if current_count >= capacity and not is_waitlist_form:
                seats_full = True
                flash('All seats are now taken. We have added you to the interest list for the next session.')
                is_waitlist_form = True

        reg = MIMRegistration(
            session_id  = s.id if s else None,
            full_name   = full_name,
            email       = email,
            mobile      = mobile,
            address     = address,
            experience  = experience,
            is_waitlist = is_waitlist_form,
        )
        db.session.add(reg)
        db.session.commit()

        # Confirmation email to registrant
        # Pre-compute values to avoid complex expressions inside f-string
        _conf_date  = s.event_date.strftime('%A, %d %B %Y') if s else 'Sunday, 26th July 2026'
        _conf_theme = s.theme if s else 'BETWEEN'
        confirm_html = f"""
        <div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;color:#0F1F3D;">
          <div style="background:#0F1F3D;padding:32px;text-align:center;">
            <div style="border:1.5px solid #C8A84B;display:inline-block;padding:8px 14px;margin-bottom:16px;">
              <span style="font-size:10px;letter-spacing:0.2em;text-transform:uppercase;color:#C8A84B;display:block;">THE</span>
              <span style="font-size:14px;letter-spacing:0.2em;text-transform:uppercase;color:#FEFCF8;font-weight:600;">LIVING LENS</span>
            </div>
            <h1 style="font-size:28px;color:#FEFCF8;margin:0 0 4px;">Making Images Matter</h1>
            <p style="color:#C8A84B;font-size:16px;margin:0;">You're registered.</p>
          </div>
          <div style="padding:32px;background:#FEFCF8;">
            <p style="font-size:18px;color:#0F1F3D;">Dear {full_name},</p>
            <p style="font-size:16px;color:#5C5040;line-height:1.8;margin:16px 0;">
              Thank you for registering for <strong>Making Images Matter</strong>.
              We look forward to seeing you on <strong>26th July 2026</strong>.
            </p>
            <div style="background:#F5F0E8;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
              <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 12px;font-family:sans-serif;">Event Details</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Date:</strong> {_conf_date}</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Time:</strong> 7:00 AM onwards</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Venue:</strong> Ramanashree Richmond, 16 Raja Ram Mohan Roy Rd, Sampangi Rama Nagara, Bengaluru — 560025</p>
            </div>
            <div style="background:#1A1A2E;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
              <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 8px;font-family:sans-serif;">Session Theme</p>
              <p style="font-size:26px;font-weight:700;color:#FFFFFF;letter-spacing:0.12em;margin:0 0 16px;font-family:Georgia,serif;">{_conf_theme}</p>
              <p style="font-size:15px;color:rgba(255,255,255,0.82);line-height:1.8;margin:0;">
                Spend time with this word before you arrive.<br>
                The space between two people. The moment between decision and action.<br>
                The light between two buildings. The silence between two notes.<br><br>
                <strong style="color:#C8A84B;">Come with at least one frame already in your mind.</strong>
              </p>
            </div>
            <div style="background:#F5F0E8;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
              <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 12px;font-family:sans-serif;">Bring with you</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">📷 Your camera</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">💻 Your laptop</p>
              <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">🧠 An open mind</p>
            </div>
            <p style="font-size:16px;color:#5C5040;line-height:1.8;">
              For any queries, please contact Sreekumar directly:<br>
              <strong style="color:#0F1F3D;">📞 9880008265</strong>
            </p>
            <p style="font-size:16px;color:#5C5040;line-height:1.8;margin-top:24px;">
              See you on the 26th.<br>
              <strong style="color:#0F1F3D;">Sreekumar Krishnan</strong><br>
              <span style="color:#C8A84B;">The Living Lens</span>
            </p>
          </div>
          <div style="background:#0F1F3D;padding:20px;text-align:center;">
            <p style="color:rgba(255,255,255,0.4);font-size:12px;font-family:sans-serif;margin:0;">Making Images Matter · The Living Lens · Bengaluru</p>
          </div>
        </div>
        """
        email_subject = 'Making Images Matter — Interest noted for next session' if is_waitlist_form else 'Making Images Matter — You are registered!'
        try:
            send_email(email, email_subject, confirm_html)
        except Exception as _email_err:
            app.logger.error(f'[register] confirm email failed: {_email_err}')

        # Notification to Sree — suppressed for TEST_EMAILS (founder test accounts)
        # S156: loud Railway log on Brevo failure so registrations are never missed
        if email.lower().strip() not in TEST_EMAILS:
            notify_email = os.environ.get('NOTIFY_EMAIL', 'sreeks@gmail.com')
            _session_label = s.title if s else 'No session linked'
            _session_theme = s.theme if s else ''
            _session_date  = s.event_date.strftime('%d %b') if s else ''
            _reg_ist = (datetime.utcnow() + _IST).strftime('%d %b %Y %H:%M IST')
            _status_label = 'Waitlist' if is_waitlist_form else 'Confirmed seat'
            notify_html = f"""
            <div style="font-family:sans-serif;max-width:500px;margin:0 auto;color:#0F1F3D;">
              <div style="background:#0F1F3D;padding:20px 24px;margin-bottom:0;">
                <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#C8A84B;">Making Images Matter</p>
                <p style="margin:0;font-size:20px;font-weight:700;color:#FFFFFF;">{_session_label}</p>
                {f'<p style="margin:4px 0 0;font-size:14px;color:rgba(255,255,255,0.6);">Theme: {_session_theme}</p>' if _session_theme else ''}
              </div>
              <div style="background:#FFFFFF;padding:20px 24px;border:1px solid #E8E4DC;">
                <p style="font-size:18px;font-weight:700;color:#0F1F3D;margin:0 0 16px;">{full_name}</p>
                <p style="margin:6px 0;"><strong>Status:</strong> <span style="color:{'#1A5C2E' if not is_waitlist_form else '#888'};font-weight:700;">{_status_label}</span></p>
                <p style="margin:6px 0;"><strong>Email:</strong> {email}</p>
                <p style="margin:6px 0;"><strong>Mobile:</strong> {mobile}</p>
                <p style="margin:6px 0;"><strong>Experience:</strong> {experience or '—'}</p>
                <p style="margin:6px 0;"><strong>City:</strong> {address or '—'}</p>
                <p style="margin:16px 0 0;font-size:12px;color:#888;">Registered {_reg_ist}</p>
              </div>
            </div>
            """
            notify_tag = '[WAITLIST]' if is_waitlist_form else '[CONFIRMED]'
            _notify_subject = f'New Registration · {_session_date} · {_session_theme} · {full_name}' if _session_date else f'{notify_tag} MIM Registration — {full_name}'
            try:
                _notify_ok = send_email(notify_email, _notify_subject, notify_html)
                if not _notify_ok:
                    # Brevo accepted but returned non-200 — log loudly for Railway
                    app.logger.error(
                        f'[REGISTER ALERT - CHECK MANUALLY] '
                        f'Brevo non-200. Name={full_name} Email={email} '
                        f'Mobile={mobile} Session={_session_label} Status={notify_tag} At={_reg_ist}'
                    )
            except Exception as _notify_err:
                # Brevo completely failed — loud log so Railway dashboard shows it
                app.logger.error(
                    f'[REGISTER ALERT - CHECK MANUALLY] '
                    f'Brevo exception: {_notify_err}. '
                    f'Name={full_name} Email={email} Mobile={mobile} '
                    f'Session={_session_label} Status={notify_tag} At={_reg_ist}'
                )

        return redirect(url_for('register_thanks'))

    return render_template('register.html', s=s, seats_full=seats_full, reg_count=reg_count, capacity=capacity)


@app.route('/register/thanks')
def register_thanks():
    return render_template('register_thanks.html')




@app.route('/admin/registration/<int:reg_id>/resend', methods=['POST'])
@admin_required
def admin_resend_confirmation(reg_id):
    """S156 — Resend confirmation email to a registrant. Used when Brevo failed on registration."""
    reg = MIMRegistration.query.get_or_404(reg_id)
    s   = MIMSession.query.get(reg.session_id) if reg.session_id else None
    _theme = s.theme if s else 'BETWEEN'
    _date  = s.event_date.strftime('%A, %d %B %Y') if s else 'Sunday, 26th July 2026'
    confirm_html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;color:#0F1F3D;">
      <div style="background:#0F1F3D;padding:32px;text-align:center;">
        <p style="font-family:sans-serif;font-size:13px;letter-spacing:0.14em;text-transform:uppercase;color:#C8A84B;margin:0 0 8px;">Making Images Matter</p>
        <p style="font-size:22px;font-weight:700;color:#FFFFFF;margin:0;">You are registered.</p>
      </div>
      <div style="padding:32px;">
        <p style="font-size:17px;line-height:1.8;color:#0F1F3D;margin-bottom:20px;">
          Dear {reg.full_name},<br>
          Thank you for registering for <strong>Making Images Matter</strong>.
        </p>
        <div style="background:#F5F0E8;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
          <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 12px;font-family:sans-serif;">Event Details</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Date:</strong> {_date}</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Time:</strong> 7:00 AM onwards</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;"><strong>Venue:</strong> Ramanashree Richmond, 16 Raja Ram Mohan Roy Rd, Sampangi Rama Nagara, Bengaluru — 560025</p>
        </div>
        <div style="background:#1A1A2E;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
          <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 8px;font-family:sans-serif;">Session Theme</p>
          <p style="font-size:26px;font-weight:700;color:#FFFFFF;letter-spacing:0.12em;margin:0 0 16px;font-family:Georgia,serif;">{_theme}</p>
          <p style="font-size:15px;color:rgba(255,255,255,0.82);line-height:1.8;margin:0;">
            Spend time with this word before you arrive.<br>
            The space between two people. The moment between decision and action.<br>
            The light between two buildings. The silence between two notes.<br><br>
            <strong style="color:#C8A84B;">Come with at least one frame already in your mind.</strong>
          </p>
        </div>
        <div style="background:#F5F0E8;padding:24px;margin:24px 0;border-left:3px solid #C8A84B;">
          <p style="font-size:14px;letter-spacing:0.1em;text-transform:uppercase;color:#C8A84B;margin:0 0 12px;font-family:sans-serif;">Bring with you</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">📷 Your camera</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">💻 Your laptop</p>
          <p style="font-size:16px;color:#0F1F3D;margin:6px 0;">🧠 An open mind</p>
        </div>
        <p style="font-size:16px;color:#5C5040;line-height:1.8;">
          For any queries: <strong style="color:#0F1F3D;">📞 9880008265</strong>
        </p>
        <p style="font-size:16px;color:#5C5040;line-height:1.8;margin-top:24px;">
          See you on Sunday.<br>
          <strong style="color:#0F1F3D;">Sreekumar Krishnan</strong><br>
          <span style="color:#C8A84B;">The Living Lens</span>
        </p>
      </div>
    </div>
    """
    try:
        ok = send_email(reg.email, 'Making Images Matter — You are registered!', confirm_html)
        if ok:
            flash(f'Confirmation resent to {reg.full_name} ({reg.email})')
        else:
            flash(f'Brevo returned error for {reg.email} — check logs', 'error')
    except Exception as _e:
        flash(f'Send failed: {_e}', 'error')
    return redirect(url_for('admin_registrations'))


@app.route('/admin/registrations-count')
@admin_required
def admin_registrations_count():
    """S156 — JSON endpoint for live seat count badge on admin dashboard."""
    s = MIMSession.query.filter(
        MIMSession.status.in_(['setup', 'eval_open'])
    ).order_by(MIMSession.event_date).first()
    capacity = s.capacity if s else 10
    confirmed = MIMRegistration.query.filter_by(
        session_id=s.id, is_waitlist=False
    ).count() if s else 0
    from flask import jsonify
    return jsonify({'confirmed': confirmed, 'capacity': capacity})

@app.route('/admin/registrations')
@admin_required
def admin_registrations():
    regs = MIMRegistration.query.order_by(MIMRegistration.is_waitlist, MIMRegistration.created_at).all()
    # Attach session title and IST timestamp to each reg for template
    _sessions = {s.id: s for s in MIMSession.query.all()}
    for r in regs:
        r._session = _sessions.get(r.session_id)
        r._created_ist = (r.created_at + _IST).strftime('%d %b %Y %H:%M IST') if r.created_at else '—'
    confirmed_count = sum(1 for r in regs if not r.is_waitlist)
    # Get capacity from most recent active session
    _active = MIMSession.query.filter(
        MIMSession.status.in_(['setup', 'eval_open'])
    ).order_by(MIMSession.event_date).first()
    capacity = _active.capacity if _active else 10
    return render_template('admin_registrations.html', regs=regs,
                           confirmed_count=confirmed_count, capacity=capacity)


# ── Routes — Admin ────────────────────────────────────────────────────────────

@app.route('/robots.txt')
def robots_txt():
    """SEO — robots.txt for MIM. Session 153."""
    return app.response_class(
        response='Sitemap: https://makingimagesmatter.com/sitemap.xml\n\nUser-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /eval\n',
        mimetype='text/plain'
    )


@app.route('/sitemap.xml')
def sitemap_mim():
    """SEO — sitemap for MIM. Session 153."""
    from datetime import date
    today = date.today().isoformat()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url>\n'
        '    <loc>https://makingimagesmatter.com/</loc>\n'
        f'    <lastmod>{today}</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n'
        '    <priority>1.0</priority>\n'
        '  </url>\n'
        '  <url>\n'
        '    <loc>https://makingimagesmatter.com/register</loc>\n'
        f'    <lastmod>{today}</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n'
        '    <priority>0.9</priority>\n'
        '  </url>\n'
        '</urlset>'
    )
    return app.response_class(response=xml, mimetype='application/xml')


@app.route('/')
def landing():
    # Pass seats_full so landing page CTA updates automatically — Session 152
    s = MIMSession.query.filter(
        MIMSession.status.in_(['setup', 'eval_open', 'eval_closed', 'published'])
    ).order_by(MIMSession.event_date).first()
    seats_full = False
    reg_count  = 0
    capacity   = 10
    if s:
        capacity  = s.capacity or 10
        reg_count = MIMRegistration.query.filter_by(session_id=s.id, is_waitlist=False).count()
        seats_full = reg_count >= capacity
    return render_template('landing.html', seats_full=seats_full,
                           spots_remaining=max(0, capacity - reg_count))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if pwd == ADMIN_PASSWORD or (ADMIN_PASSWORD_2 and pwd == ADMIN_PASSWORD_2):
            session['mim_admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Incorrect password.')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('mim_admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    sessions = MIMSession.query.order_by(MIMSession.created_at.desc()).all()
    return render_template('admin_dashboard.html', sessions=sessions)


@app.route('/admin/session/new', methods=['GET', 'POST'])
@admin_required
def admin_new_session():
    if request.method == 'POST':
        token = _make_token(8)
        s = MIMSession(
            token        = token,
            title        = request.form['title'],
            theme        = request.form['theme'].upper().strip(),
            genre        = request.form['genre'].strip(),
            event_date   = datetime.strptime(request.form['event_date'], '%Y-%m-%d').date(),
            city         = request.form['city'].strip(),
            total_images = int(request.form.get('total_images', 10)),
            status       = 'setup',
        )
        db.session.add(s)
        db.session.commit()
        return redirect(url_for('admin_session_detail', token=token))
    return render_template('admin_new_session.html')


@app.route('/admin/session/<token>')
@admin_required
def admin_session_detail(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id).order_by(MIMImage.file_number).all()
    # Evaluation counts per image
    eval_counts = {}
    for img in images:
        eval_counts[img.id] = MIMEvaluation.query.filter_by(image_id=img.id).count()
    session_url = url_for('eval_landing', token=token, _external=True)
    confirmed_reg_count = MIMRegistration.query.filter_by(
        session_id=s.id, is_waitlist=False).count()
    return render_template('admin_session_detail.html',
                           s=s, images=images,
                           eval_counts=eval_counts,
                           session_url=session_url,
                           confirmed_reg_count=confirmed_reg_count)


@app.route('/admin/session/<token>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_session(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if request.method == 'POST':
        s.title        = request.form.get('title', s.title).strip()
        s.theme        = request.form.get('theme', s.theme).upper().strip()
        s.genre        = request.form.get('genre', s.genre).strip()
        s.city         = request.form.get('city', s.city).strip()
        s.total_images = int(request.form.get('total_images', s.total_images))
        if request.form.get('event_date'):
            s.event_date = datetime.strptime(request.form['event_date'], '%Y-%m-%d').date()
        db.session.commit()
        flash('Session updated.')
        return redirect(url_for('admin_session_detail', token=token))
    return render_template('admin_edit_session.html', s=s)


@app.route('/admin/session/<token>/open-eval', methods=['POST'])
@admin_required
def admin_open_eval(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.status = 'eval_open'
    db.session.commit()
    flash('Evaluation is now open. Share the link with participants.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/close-eval', methods=['POST'])
@admin_required
def admin_close_eval(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.status = 'eval_closed'
    db.session.commit()
    flash('Evaluation closed. Ready for DDI results and reveal.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/upload-image', methods=['POST'])
@admin_required
def admin_upload_image(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    file_number = int(request.form['file_number'])
    photographer_name = request.form.get('photographer_name', '').strip()
    sl_username = request.form.get('sl_username', '').strip()

    # Check if image for this file number already exists
    existing = MIMImage.query.filter_by(
        session_id=s.id, file_number=file_number).first()

    f = request.files.get('image')
    filename = None
    if f and f.filename:
        ext = f.filename.rsplit('.', 1)[-1].lower()
        filename = f'session_{s.token}_img_{file_number}.{ext}'
        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        f.save(os.path.join(upload_dir, filename))

    if existing:
        if filename:
            existing.filename = filename
        existing.photographer_name = photographer_name
        existing.sl_username = sl_username
    else:
        img = MIMImage(
            session_id=s.id,
            file_number=file_number,
            filename=filename,
            photographer_name=photographer_name,
            sl_username=sl_username,
        )
        db.session.add(img)

    db.session.commit()
    flash(f'Image {file_number} saved.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/save-ddi', methods=['POST'])
@admin_required
def admin_save_ddi(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    for img in s.images:
        key_craft    = f'ddi_craft_{img.file_number}'
        key_theme    = f'ddi_theme_{img.file_number}'
        key_score    = f'ddi_score_{img.file_number}'
        key_narrative= f'ddi_narrative_{img.file_number}'
        key_name     = f'photographer_name_{img.file_number}'
        if key_craft in request.form:
            img.ddi_craft         = float(request.form[key_craft]) if request.form[key_craft] else None
            img.ddi_theme         = float(request.form[key_theme]) if request.form[key_theme] else None
            img.ddi_score         = float(request.form[key_score]) if request.form[key_score] else None
            img.ddi_narrative     = request.form.get(key_narrative, '').strip()
        # Always save photographer name if provided
        _pname = request.form.get(key_name, '').strip()
        if _pname:
            img.photographer_name = _pname
    db.session.commit()
    flash('DDI evaluations saved.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/publish', methods=['POST'])
@admin_required
def admin_publish(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.status = 'published'
    s.published_at = datetime.utcnow()
    db.session.commit()
    flash('Session published. Reveal is live.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/export-csv')
@admin_required
def admin_export_csv(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id).order_by(MIMImage.file_number).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'File No', 'Photographer', 'SL Username',
        'Peer Theme Avg', 'Peer Craft Avg', 'Peer Evaluators',
        'DDI Theme', 'DDI Craft', 'DDI Score',
        'Theme Gap', 'Craft Gap',
        'Sherpa Narrative'
    ])

    for img in images:
        evals = MIMEvaluation.query.filter_by(image_id=img.id).all()
        n = len(evals)
        peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else ''
        peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else ''
        theme_gap = round(img.ddi_theme - peer_theme_avg, 2) if (img.ddi_theme and peer_theme_avg != '') else ''
        craft_gap = round(img.ddi_craft - peer_craft_avg, 2) if (img.ddi_craft and peer_craft_avg != '') else ''

        writer.writerow([
            img.file_number,
            img.photographer_name or '',
            img.sl_username or '',
            peer_theme_avg,
            peer_craft_avg,
            n,
            img.ddi_theme or '',
            img.ddi_craft or '',
            img.ddi_score or '',
            theme_gap,
            craft_gap,
            img.ddi_narrative or '',
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'MIM_{s.token}_{s.event_date}.csv'
    )


# ── Routes — Participant Evaluation ──────────────────────────────────────────

@app.route('/session/<token>')
def eval_landing(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status not in ('eval_open', 'eval_closed', 'published'):
        return render_template('eval_not_open.html', s=s)

    # ── Auto-identify photographer from cookie set at upload ──
    # Cookie name: mim_slot_<token>  Value: slot number (1..N)
    # Set on the photographer's device when they uploaded their image.
    # No typing needed — system identifies them automatically.
    cookie_slot = request.cookies.get(f'mim_slot_{token}', '').strip()
    if cookie_slot.isdigit():
        slot = int(cookie_slot)
        if 1 <= slot <= s.total_images:
            session['evaluator_file_number'] = slot
            session['eval_session_token'] = token
            return redirect(url_for('eval_image', token=token, file_number=1))

    # Fallback — ?slot=X param (from personal link)
    prefilled_slot = request.args.get('slot', '').strip()
    if prefilled_slot.isdigit():
        prefilled_slot = int(prefilled_slot)
        if 1 <= prefilled_slot <= s.total_images:
            session['evaluator_file_number'] = prefilled_slot
            session['eval_session_token'] = token
            return redirect(url_for('eval_image', token=token, file_number=1))

    # Final fallback — show manual entry form
    return render_template('eval_landing.html', s=s, prefilled_slot='')


@app.route('/session/<token>/start', methods=['POST'])
def eval_start(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    evaluator_num = request.form.get('file_number', '').strip()
    if not evaluator_num or not evaluator_num.isdigit():
        flash('Please enter your file number.')
        return redirect(url_for('eval_landing', token=token))
    evaluator_num = int(evaluator_num)
    if evaluator_num < 1 or evaluator_num > s.total_images:
        flash(f'File number must be between 1 and {s.total_images}.')
        return redirect(url_for('eval_landing', token=token))
    session['evaluator_file_number'] = evaluator_num
    session['eval_session_token'] = token
    return redirect(url_for('eval_image', token=token, file_number=1))


@app.route('/session/<token>/evaluate/<int:file_number>', methods=['GET', 'POST'])
def eval_image(token, file_number):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    evaluator_num = session.get('evaluator_file_number')

    if not evaluator_num or session.get('eval_session_token') != token:
        return redirect(url_for('eval_landing', token=token))

    if s.status == 'published':
        return redirect(url_for('reveal_session', token=token))

    if s.status not in ('eval_open',):
        return render_template('eval_not_open.html', s=s)

    img = MIMImage.query.filter_by(
        session_id=s.id, file_number=file_number).first_or_404()

    # Skip own image
    if file_number == evaluator_num:
        next_num = file_number + 1
        if next_num > s.total_images:
            return redirect(url_for('eval_complete', token=token))
        return redirect(url_for('eval_image', token=token, file_number=next_num))

    # Check if already evaluated this image
    already_done = MIMEvaluation.query.filter_by(
        image_id=img.id,
        evaluator_file_number=evaluator_num
    ).first()

    if request.method == 'POST':
        theme_score    = int(request.form['theme_score'])
        craft_score    = int(request.form['craft_score'])
        what_worked    = request.form['what_worked'].strip()
        what_to_change = request.form['what_to_change'].strip()

        if already_done:
            already_done.theme_score    = theme_score
            already_done.craft_score    = craft_score
            already_done.what_worked    = what_worked
            already_done.what_to_change = what_to_change
        else:
            ev = MIMEvaluation(
                session_id=s.id,
                image_id=img.id,
                evaluator_file_number=evaluator_num,
                theme_score=theme_score,
                craft_score=craft_score,
                what_worked=what_worked,
                what_to_change=what_to_change,
            )
            db.session.add(ev)
        db.session.commit()

        next_num = file_number + 1
        # Skip own image in sequence
        if next_num == evaluator_num:
            next_num += 1
        if next_num > s.total_images:
            return redirect(url_for('eval_complete', token=token))
        return redirect(url_for('eval_image', token=token, file_number=next_num))

    # Progress — how many images this evaluator has done
    done_count = MIMEvaluation.query.filter_by(
        session_id=s.id,
        evaluator_file_number=evaluator_num
    ).count()
    total_to_eval = s.total_images - 1  # excluding own image

    return render_template('eval_image.html',
                           s=s, img=img,
                           file_number=file_number,
                           evaluator_num=evaluator_num,
                           done_count=done_count,
                           total_to_eval=total_to_eval,
                           already_done=already_done)


@app.route('/session/<token>/done')
def eval_complete(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    return render_template('eval_complete.html', s=s)


# ── Routes — Reveal ───────────────────────────────────────────────────────────

@app.route('/session/<token>/reveal')
def reveal_session(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'published':
        return render_template('reveal_not_ready.html', s=s)

    images = MIMImage.query.filter_by(
        session_id=s.id).order_by(MIMImage.file_number).all()

    image_data = []
    for img in images:
        evals = MIMEvaluation.query.filter_by(image_id=img.id).all()
        n = len(evals)
        peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None
        peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None
        image_data.append({
            'img': img,
            'evals': evals,
            'peer_theme_avg': peer_theme_avg,
            'peer_craft_avg': peer_craft_avg,
            'n': n,
        })

    return render_template('reveal_session.html', s=s, image_data=image_data)


@app.route('/session/<token>/reveal/<int:file_number>')
def reveal_image(token, file_number):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'published':
        return render_template('reveal_not_ready.html', s=s)
    img = MIMImage.query.filter_by(
        session_id=s.id, file_number=file_number).first_or_404()
    evals = MIMEvaluation.query.filter_by(image_id=img.id).all()
    n = len(evals)
    peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None
    peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None
    return render_template('reveal_image.html',
                           s=s, img=img, evals=evals,
                           peer_theme_avg=peer_theme_avg,
                           peer_craft_avg=peer_craft_avg, n=n)



# ── Routes — Photographer Self-Upload ────────────────────────────────────────
#
# Flow:
#   Admin creates MIMImage rows with file numbers before the session.
#   Admin visits /admin/session/<token>/generate-upload-links — generates
#   a unique upload_token per image and shows the upload URL for each.
#   Photographer visits /upload/<upload_token> — enters their file number
#   to confirm identity, uploads their image.
#   Admin dashboard shows live upload progress (polling /admin/session/<token>/upload-status).
#   After upload, DDI pull fires automatically in background.


@app.route('/upload/<session_token>', methods=['GET', 'POST'])
def session_upload(session_token):
    """
    Single upload URL per session — photographer opens this link, uploads image.
    System auto-assigns the next available slot number.
    URL format: makingimagesmatter.com/upload/BLR26JUL26
    No per-slot tokens needed.
    """
    s = MIMSession.query.filter_by(token=session_token).first_or_404()

    # Lock once eval opens
    if s.status not in ('setup',):
        return render_template('upload_locked.html', s=s, img=None)

    error = None
    if request.method == 'POST':
        f = request.files.get('image')
        if not f or not f.filename:
            error = 'Please select an image to upload.'
        else:
            # Validate image dimensions — shorter side must be >= 1500px
            try:
                from PIL import Image as PILImage
                import io as _io
                f.stream.seek(0)
                pil_img = PILImage.open(f.stream)
                w, h = pil_img.size
                shorter = min(w, h)
                if shorter < 1500:
                    error = f'Your image is {w}×{h}px. The shorter side must be at least 1500px. Please export a larger version and try again.'
                f.stream.seek(0)
            except Exception:
                pass  # If PIL fails, let it through

            if not error:
                # Auto-assign next available slot
                taken = {img.file_number for img in MIMImage.query.filter_by(
                    session_id=s.id).filter(MIMImage.filename.isnot(None)).all()}
                slot = None
                for n in range(1, s.total_images + 1):
                    if n not in taken:
                        slot = n
                        break

                if slot is None:
                    error = 'All slots are filled. Please contact the session organiser.'
                else:
                    # Get or create the MIMImage row for this slot
                    img = MIMImage.query.filter_by(session_id=s.id, file_number=slot).first()
                    if not img:
                        img = MIMImage(session_id=s.id, file_number=slot)
                        db.session.add(img)
                        db.session.flush()

                    original_name = f.filename
                    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else 'jpg'
                    stored_name = f'session_{s.token}_img_{slot}.{ext}'

                    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)
                    f.save(os.path.join(upload_dir, stored_name))

                    img.filename = stored_name
                    img.original_filename = original_name
                    img.uploaded_by_self = True
                    db.session.commit()

                    app.logger.warning(
                        f'[session-upload] session={s.token} slot={slot} '
                        f'original={original_name} stored={stored_name}'
                    )

                    # Fire DDI pull in background
                    import threading
                    t = threading.Thread(target=_pull_ddi_for_image, args=(img.id,), daemon=True)
                    t.start()

                    resp = make_response(render_template('upload_done.html', img=img, s=s, already=False))
                    # Set cookie so photographer is auto-identified when they open the session link
                    # Cookie expires in 7 days — covers the session day
                    resp.set_cookie(
                        f'mim_slot_{s.token}',
                        str(slot),
                        max_age=7*24*3600,
                        httponly=False,  # needs to be readable by JS for display
                        samesite='Lax'
                    )
                    return resp

    # Check if session is full
    filled = MIMImage.query.filter_by(session_id=s.id).filter(
        MIMImage.filename.isnot(None)).count()
    slots_left = s.total_images - filled

    return render_template('upload_page_session.html', s=s, slots_left=slots_left, error=error)

@app.route('/admin/session/<token>/generate-upload-links', methods=['POST'])
@admin_required
def admin_generate_upload_links(token):
    """Generate upload_token for every image in the session that doesn't have one yet."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    # Ensure all file_number slots exist as MIMImage rows
    for n in range(1, s.total_images + 1):
        img = MIMImage.query.filter_by(session_id=s.id, file_number=n).first()
        if not img:
            img = MIMImage(session_id=s.id, file_number=n)
            db.session.add(img)
            db.session.flush()
        if not img.upload_token:
            img.upload_token = secrets.token_urlsafe(20)
    db.session.commit()
    flash('Upload links generated. Share the individual links with each photographer.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/upload/<upload_token>', methods=['GET', 'POST'])
def photographer_upload(upload_token):
    """Photographer self-upload page — no login required, token is single-use identity.
    Option C: re-upload allowed while session is in 'setup'. Locked once eval_open or later.
    """
    img = MIMImage.query.filter_by(upload_token=upload_token).first_or_404()
    s   = img.mim_session

    # Lock uploads once evaluation has opened
    eval_locked = s.status not in ('setup',)
    already_uploaded = bool(img.filename and img.uploaded_by_self)

    if request.method == 'POST':
        # Hard lock — eval is open or beyond
        if eval_locked:
            return render_template('upload_locked.html', img=img, s=s)

        f = request.files.get('image')
        if not f or not f.filename:
            flash('Please select an image to upload.')
            return render_template('upload_page.html', img=img, s=s,
                                   already_uploaded=already_uploaded, eval_locked=False)

        # Save with original filename preserved for DDI pull
        original_name = f.filename
        ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else 'jpg'
        stored_name = f'session_{s.token}_img_{img.file_number}.{ext}'

        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        f.save(os.path.join(upload_dir, stored_name))

        img.filename          = stored_name
        img.original_filename = original_name
        img.uploaded_by_self  = True
        db.session.commit()

        app.logger.warning(f'[self-upload] session={s.token} file_number={img.file_number} '
                           f'original={original_name} stored={stored_name}')

        # Fire DDI pull in background (non-blocking)
        import threading
        t = threading.Thread(target=_pull_ddi_for_image, args=(img.id,), daemon=True)
        t.start()

        return render_template('upload_done.html', img=img, s=s, already=False)

    # GET — show locked screen if eval has opened
    if eval_locked:
        return render_template('upload_locked.html', img=img, s=s)

    return render_template('upload_page.html', img=img, s=s,
                           already_uploaded=already_uploaded, eval_locked=False)


def _pull_ddi_for_image(image_id):
    """
    Background task — query Shutter League for DDI evaluation by original_filename.
    Populates ddi_score, ddi_craft, ddi_theme, ddi_narrative on the MIMImage row.

    SL endpoint expected:
      GET /api/mim-ddi?filename=<original_filename>&api_key=<MIM_SL_API_KEY>
    Returns JSON:
      {
        "found": true,
        "ddi_score": 7.64,
        "ddi_craft": 7.64,
        "ddi_theme": null,
        "ddi_narrative": "Sherpa block text...",
        "tier": "Maverick",
        "dimensions": {"DoD": 6.8, "Disruption": 8.1, "DM": 7.9, "Wonder": 7.2, "AQ": 8.0}
      }
    If not found yet (image not yet scored on SL), returns {"found": false}.
    """
    with app.app_context():
        try:
            img = MIMImage.query.get(image_id)
            if not img or not img.original_filename:
                return

            api_key  = os.environ.get('MIM_SL_API_KEY', '')
            if not api_key:
                app.logger.warning('[ddi-pull] MIM_SL_API_KEY not set — skipping DDI pull')
                return

            # ── Session 160: pull session theme to pass to SL ─────────────────
            # SL engine scores theme relevance (mim_theme_score + mim_theme_paragraph)
            # when theme is provided. Fetch from parent MIMSession via img.session_id.
            _session_theme = ''
            try:
                _parent = MIMSession.query.get(img.session_id)
                if _parent and _parent.theme:
                    _session_theme = _parent.theme.strip().upper()
            except Exception as _te:
                app.logger.debug(f'[ddi-pull] theme lookup failed: {_te}')

            import urllib.request, urllib.parse, json as _json
            _params = {
                'filename': img.original_filename,
                'api_key':  api_key,
            }
            if _session_theme:
                _params['theme'] = _session_theme

            params = urllib.parse.urlencode(_params)
            url = f'{SL_API_URL}/api/mim-ddi?{params}'
            app.logger.warning(
                f'[ddi-pull] GET filename={img.original_filename} theme={_session_theme or "none"}'
            )

            req = urllib.request.Request(url, headers={
                'Accept': 'application/json',
                'User-Agent': 'MakingImagesMatter/1.0 (internal; makingimagesmatter.com)',
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read().decode('utf-8'))

            if not data.get('found'):
                app.logger.warning(f'[ddi-pull] filename={img.original_filename} → not found on SL yet')
                return

            img.ddi_score      = data.get('ddi_score')
            img.ddi_craft      = data.get('ddi_craft') or data.get('ddi_score')
            img.ddi_theme      = data.get('ddi_theme')    # now a real float from SL engine
            # Session 160: append theme paragraph to narrative so it surfaces on reveal screen
            _craft_narrative   = data.get('ddi_narrative', '') or ''
            _theme_para        = (data.get('ddi_theme_paragraph') or '').strip()
            if _theme_para:
                _theme_label   = f'Theme ({_session_theme.title() if _session_theme else "Session"}): {_theme_para}'
                img.ddi_narrative = '\n\n'.join(filter(None, [_craft_narrative, _theme_label]))
            else:
                img.ddi_narrative = _craft_narrative
            # Session 155 — save all 5 DDI dimensions as JSON for CSV + PDF reports
            import json as _jdim
            img.ddi_dimensions = _jdim.dumps(data.get('dimensions', {}))
            db.session.commit()
            app.logger.warning(
                f'[ddi-pull] ✅ image_id={image_id} ddi_score={img.ddi_score} '
                f'ddi_theme={img.ddi_theme}'
            )

        except Exception as e:
            app.logger.error(f'[ddi-pull] error image_id={image_id}: {e}')


@app.route('/admin/session/<token>/retry-ddi/<int:file_number>', methods=['POST'])
@admin_required
def admin_retry_ddi(token, file_number):
    """
    Session 160.1 — Pull DDI synchronously in-request (no threading).
    Threading was causing silent failures because app.app_context() was
    dying in daemon threads after the request context was torn down.
    """
    s   = MIMSession.query.filter_by(token=token).first_or_404()
    img = MIMImage.query.filter_by(session_id=s.id, file_number=file_number).first_or_404()
    if not img.original_filename:
        flash(f'Image {file_number} has no original filename — upload first.')
        return redirect(url_for('admin_session_detail', token=token))

    api_key = os.environ.get('MIM_SL_API_KEY', '')
    if not api_key:
        flash('MIM_SL_API_KEY not set — cannot pull DDI.')
        return redirect(url_for('admin_session_detail', token=token))

    try:
        import urllib.request, urllib.parse, json as _json, re as _mre

        # Pull session theme
        _session_theme = ''
        if s.theme:
            _session_theme = s.theme.strip().upper()

        # ── Session 160.2: Normalise filename before sending ─────────────────
        # Handles spaces↔underscores, special chars, leading underscores, etc.
        def _mim_normalise_fn(fn):
            fn = fn.strip().split('/')[-1].split('\\')[-1]
            stem, ext = (fn.rsplit('.', 1) if '.' in fn else (fn, ''))
            stem = stem.strip()  # strip trailing/leading spaces from stem
            stem_norm = _mre.sub(r'[^A-Za-z0-9\-]', '_', stem)
            stem_norm = _mre.sub(r'_+', '_', stem_norm).strip('_')
            return f'{stem_norm}.{ext.lower()}' if ext else stem_norm

        _raw_fn   = img.original_filename
        _norm_fn  = _mim_normalise_fn(_raw_fn)

        def _do_pull(fn):
            _p = {'filename': fn, 'api_key': api_key}
            if _session_theme:
                _p['theme'] = _session_theme
            _u = f'{SL_API_URL}/api/mim-ddi?{urllib.parse.urlencode(_p)}'
            app.logger.warning(f'[ddi-pull-sync] GET filename={fn} theme={_session_theme or "none"}')
            _r = urllib.request.Request(_u, headers={
                'Accept': 'application/json',
                'User-Agent': 'MakingImagesMatter/1.0 (internal; makingimagesmatter.com)',
            })
            with urllib.request.urlopen(_r, timeout=30) as _resp:
                return _json.loads(_resp.read().decode('utf-8'))

        # Try exact filename first
        data = _do_pull(_raw_fn)

        # If not found, try normalised (spaces→underscores, special chars stripped)
        if not data.get('found') and _norm_fn != _raw_fn:
            app.logger.warning(f'[ddi-pull-sync] not found — retrying normalised: {_norm_fn}')
            data = _do_pull(_norm_fn)

        if not data.get('found'):
            app.logger.warning(f'[ddi-pull-sync] not found on SL: {img.original_filename}')
            flash(f'Image {file_number} ({img.original_filename}) not found on SL yet — photographer needs to upload first.')
            return redirect(url_for('admin_session_detail', token=token))

        img.ddi_score     = data.get('ddi_score')
        img.ddi_craft     = data.get('ddi_craft') or data.get('ddi_score')
        img.ddi_theme     = data.get('ddi_theme')
        _craft_narrative  = (data.get('ddi_narrative') or '').strip()
        _theme_para       = (data.get('ddi_theme_paragraph') or '').strip()
        if _theme_para:
            _theme_label = f'Theme ({_session_theme.title() if _session_theme else "Session"}): {_theme_para}'
            img.ddi_narrative = '\n\n'.join(filter(None, [_craft_narrative, _theme_label]))
        else:
            img.ddi_narrative = _craft_narrative
        img.ddi_dimensions = json.dumps(data.get('dimensions', {}))
        db.session.commit()
        app.logger.warning(
            f'[ddi-pull-sync] ✅ image={img.id} filename={img.original_filename} '
            f'ddi_score={img.ddi_score} ddi_theme={img.ddi_theme}'
        )
        flash(f'DDI pulled for Image {file_number} — score {img.ddi_score}, theme {img.ddi_theme}')

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[ddi-pull-sync] error image={img.id}: {e}')
        flash(f'DDI pull failed for Image {file_number}: {e}')

    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/upload-status')
@admin_required
def admin_upload_status(token):
    """
    JSON endpoint — admin dashboard polls this every 5 seconds to show live upload progress.
    Returns upload state for all image slots.
    """
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id).order_by(MIMImage.file_number).all()
    result = []
    for img in images:
        result.append({
            'file_number':      img.file_number,
            'uploaded':         bool(img.filename),
            'uploaded_by_self': bool(img.uploaded_by_self),
            'original_filename':img.original_filename or '',
            'ddi_score':        img.ddi_score,
            'ddi_pulled':       img.ddi_score is not None,
            'upload_url':       url_for('photographer_upload',
                                        upload_token=img.upload_token,
                                        _external=True) if img.upload_token else None,
        })
    uploaded_count = sum(1 for r in result if r['uploaded'])
    ddi_count      = sum(1 for r in result if r['ddi_pulled'])
    return jsonify({
        'total':          s.total_images,
        'uploaded_count': uploaded_count,
        'ddi_count':      ddi_count,
        'images':         result,
    })



@app.route('/admin/session/<token>/eval-status')
@admin_required  
def admin_eval_status(token):
    """JSON endpoint — returns per-slot evaluation completion for live counter."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id).order_by(MIMImage.file_number).all()
    total = len(images)
    slots = []
    complete_count = 0
    for img in images:
        # Each photographer must evaluate (total-1) images (all except their own)
        eval_count = MIMEvaluation.query.filter_by(
            evaluator_file_number=img.file_number,
            session_id=s.id
        ).count()
        expected = total - 1
        done = eval_count >= expected
        if done:
            complete_count += 1
        slots.append({
            'file_number': img.file_number,
            'name': img.photographer_name or f'Slot {img.file_number}',
            'done': done,
            'count': eval_count,
            'expected': expected,
        })
    return jsonify({
        'total': total,
        'complete': complete_count,
        'all_done': complete_count >= total,
        'slots': slots,
    })

# ── Routes — Admin-Controlled Reveal (one image at a time) ───────────────────
#
# Admin screen:  /admin/session/<token>/reveal-control
#   Sree sees current image + scores. Buttons: ◀ Prev | Next ▶
#   Clicking Next/Prev updates reveal_current_image on the session.
#
# Participant screen: /session/<token>/reveal-live
#   Shows the current image. Polls /session/<token>/reveal-state every 3s.
#   Updates without page reload when Sree advances.

@app.route('/admin/session/<token>/reveal-control')
@admin_required
def admin_reveal_control(token):
    """Admin-only reveal screen — Sree controls which image is shown."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'published':
        flash('Publish the session first before using the reveal screen.')
        return redirect(url_for('admin_session_detail', token=token))

    images = MIMImage.query.filter_by(
        session_id=s.id).order_by(MIMImage.file_number).all()

    current = s.reveal_current_image or 0
    current_img = None
    current_evals = []
    peer_theme_avg = peer_craft_avg = None

    if current > 0:
        current_img = next((i for i in images if i.file_number == current), None)
        if current_img:
            evals = MIMEvaluation.query.filter_by(image_id=current_img.id).all()
            n = len(evals)
            peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None
            peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None
            current_evals = evals

    return render_template('admin_reveal_control.html',
                           s=s, images=images,
                           current=current,
                           current_img=current_img,
                           current_evals=current_evals,
                           peer_theme_avg=peer_theme_avg,
                           peer_craft_avg=peer_craft_avg)


@app.route('/admin/session/<token>/reveal-advance', methods=['POST'])
@admin_required
def admin_reveal_advance(token):
    """Move reveal forward or backward by one image."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    direction = request.form.get('direction', 'next')
    current   = s.reveal_current_image or 0

    total = MIMImage.query.filter_by(session_id=s.id).count()
    if direction == 'next':
        # total+1 signals "reveal complete" state
        new_current = min(current + 1, total + 1)
    else:
        new_current = max(current - 1, 0)

    s.reveal_current_image = new_current
    db.session.commit()
    app.logger.warning(f'[reveal] session={token} advanced to image {new_current}')
    return redirect(url_for('admin_reveal_control', token=token))


@app.route('/session/<token>/reveal-live')
def reveal_live(token):
    """
    Participant-facing live reveal page.
    Shows whatever image Sree has currently advanced to.
    Polls /session/<token>/reveal-state every 3 seconds and updates without reload.
    """
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'published':
        return render_template('reveal_not_ready.html', s=s)
    return render_template('reveal_live.html', s=s)


@app.route('/session/<token>/reveal-state')
def reveal_state(token):
    """
    JSON polling endpoint for the live reveal page.
    Returns current image data — participant page updates on change.
    """
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'published':
        return jsonify({'status': 'not_published'})

    current = s.reveal_current_image or 0
    if current == 0:
        return jsonify({'status': 'waiting', 'current': 0})

    img = MIMImage.query.filter_by(
        session_id=s.id, file_number=current).first()
    if not img:
        return jsonify({'status': 'waiting', 'current': current})

    evals = MIMEvaluation.query.filter_by(image_id=img.id).all()
    n = len(evals)
    peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None
    peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None

    image_url = url_for('static', filename=f'uploads/{img.filename}') if img.filename else None

    total_images = MIMImage.query.filter_by(session_id=s.id).count()
    is_done = current > total_images
    return jsonify({
        'status':          'done' if is_done else 'live',
        'current':         current,
        'total':           total_images,
        'file_number':     img.file_number,
        'image_url':       image_url,
        'photographer':    img.photographer_name or f'Photographer {img.file_number}',
        'ddi_score':       img.ddi_score,
        'ddi_craft':       img.ddi_craft,
        'ddi_theme':       img.ddi_theme,
        'ddi_narrative':   img.ddi_narrative or '',
        'peer_theme_avg':  peer_theme_avg,
        'peer_craft_avg':  peer_craft_avg,
        'peer_count':      n,
    })


@app.route('/admin/session/<token>/send-reports', methods=['POST'])
@admin_required
def admin_send_reports(token):
    """
    Session 160 — Send individual HTML report to each registered participant.
    Each photographer gets: their image thumbnail, peer scores, all peer comments,
    DDI score, DDI theme score, and Sherpa narrative.
    """
    s = MIMSession.query.filter_by(token=token).first_or_404()
    regs = MIMRegistration.query.filter_by(session_id=s.id, is_waitlist=False).all()
    images = MIMImage.query.filter_by(session_id=s.id).order_by(MIMImage.file_number).all()

    # Build lookup: file_number → image
    img_by_slot = {img.file_number: img for img in images}

    sent = 0
    failed = 0
    skipped = 0

    for reg in regs:
        # Match registration to image by sl_username or name
        img = None
        for i in images:
            if i.sl_username and reg.sl_username and i.sl_username.lower() == reg.sl_username.lower():
                img = i
                break
            if i.photographer_name and reg.full_name and i.photographer_name.lower() == reg.full_name.lower():
                img = i
                break

        if not img:
            app.logger.warning(f'[send-reports] no image match for reg={reg.full_name} ({reg.email}) — skipping')
            skipped += 1
            continue

        # Peer evaluations for this image
        evals = MIMEvaluation.query.filter_by(image_id=img.id).all()
        n = len(evals)
        peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None
        peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None

        # Build peer comments HTML
        comments_html = ''
        for ev in evals:
            if ev.what_worked or ev.what_to_change:
                comments_html += f'''
                <div style="border-left:3px solid #C8A84B;padding:12px 16px;margin-bottom:12px;background:#FEFCF8;">
                  {f'<p style="font-size:15px;color:#0F1F3D;line-height:1.8;margin:0 0 8px;"><strong>What worked:</strong> {ev.what_worked}</p>' if ev.what_worked else ''}
                  {f'<p style="font-size:15px;color:#5C5040;line-height:1.8;margin:0;font-style:italic;"><strong>What to change:</strong> {ev.what_to_change}</p>' if ev.what_to_change else ''}
                </div>'''

        # DDI section
        ddi_html = ''
        if img.ddi_score:
            ddi_html = f'''
            <div style="background:#0F1F3D;border-radius:8px;padding:24px;margin:24px 0;">
              <p style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#C8A84B;margin:0 0 16px;font-family:sans-serif;">DDI Evaluation</p>
              <div style="display:flex;gap:32px;margin-bottom:16px;flex-wrap:wrap;">
                <div>
                  <p style="font-size:11px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.1em;margin:0 0 4px;font-family:sans-serif;">Craft</p>
                  <p style="font-size:36px;font-weight:700;color:#C8A84B;margin:0;">{img.ddi_craft:.1f if img.ddi_craft else '—'}</p>
                </div>
                {f'<div><p style="font-size:11px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.1em;margin:0 0 4px;font-family:sans-serif;">Theme</p><p style="font-size:36px;font-weight:700;color:#C8A84B;margin:0;">{img.ddi_theme:.1f}</p></div>' if img.ddi_theme else ''}
              </div>
              {f'<p style="font-size:15px;color:rgba(255,255,255,0.8);line-height:1.8;margin:0;border-top:1px solid rgba(200,168,75,0.25);padding-top:16px;">{img.ddi_narrative}</p>' if img.ddi_narrative else ''}
            </div>'''

        # Score comparison table
        comparison_html = ''
        if peer_craft_avg or (img.ddi_craft and peer_craft_avg):
            rows = []
            if peer_theme_avg:
                rows.append(f'<tr><td style="padding:10px 0;color:#5C5040;font-size:15px;">Peer Theme</td><td style="padding:10px 0;font-size:20px;font-weight:700;color:#0F1F3D;text-align:right;">{peer_theme_avg}</td></tr>')
            if peer_craft_avg:
                rows.append(f'<tr><td style="padding:10px 0;color:#5C5040;font-size:15px;">Peer Craft</td><td style="padding:10px 0;font-size:20px;font-weight:700;color:#0F1F3D;text-align:right;">{peer_craft_avg}</td></tr>')
            if img.ddi_theme:
                rows.append(f'<tr><td style="padding:10px 0;color:#5C5040;font-size:15px;">DDI Theme</td><td style="padding:10px 0;font-size:20px;font-weight:700;color:#C8A84B;text-align:right;">{img.ddi_theme:.1f}</td></tr>')
            if img.ddi_craft:
                rows.append(f'<tr><td style="padding:10px 0;color:#5C5040;font-size:15px;">DDI Craft</td><td style="padding:10px 0;font-size:20px;font-weight:700;color:#C8A84B;text-align:right;">{img.ddi_craft:.1f}</td></tr>')
            if rows:
                comparison_html = f'''
                <table style="width:100%;border-collapse:collapse;margin:16px 0;">
                  {''.join(rows)}
                </table>'''

        html_body = f"""
        <div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;color:#0F1F3D;background:#F5F0E8;">
          <div style="background:#0F1F3D;padding:28px 32px;">
            <p style="font-size:11px;letter-spacing:0.2em;text-transform:uppercase;color:#C8A84B;margin:0 0 6px;font-family:sans-serif;">Making Images Matter</p>
            <h1 style="font-size:22px;color:#FEFCF8;margin:0 0 4px;">{s.title}</h1>
            <p style="color:#C8A84B;font-size:14px;margin:0;">Theme — {s.theme} · {s.city} · {s.event_date.strftime('%d %B %Y')}</p>
          </div>
          <div style="padding:32px;background:#FEFCF8;">
            <p style="font-size:18px;font-weight:700;color:#0F1F3D;margin:0 0 8px;">Hi {reg.full_name.split()[0]},</p>
            <p style="font-size:16px;color:#5C5040;line-height:1.8;margin:0 0 24px;">
              Here is your complete evaluation from Making Images Matter — peer observations and engine analysis for your image.
            </p>

            <p style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#C8A84B;margin:0 0 12px;font-family:sans-serif;">Your Image — File {img.file_number}</p>
            {comparison_html}

            <p style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;color:#C8A84B;margin:24px 0 12px;font-family:sans-serif;">What Your Peers Observed ({n} evaluation{'s' if n != 1 else ''})</p>
            {comments_html if comments_html else '<p style="color:#9B8F82;font-size:15px;">No peer comments recorded.</p>'}

            {ddi_html}

            <p style="font-size:15px;color:#5C5040;line-height:1.8;margin:24px 0 0;">
              Keep shooting.<br><br>
              <strong style="color:#0F1F3D;">Sreekumar Krishnan</strong><br>
              <span style="color:#C8A84B;font-size:14px;">Making Images Matter · The Living Lens</span>
            </p>
          </div>
        </div>
        """

        try:
            ok = send_email(
                reg.email,
                f'Making Images Matter — {s.title} · Your Evaluation',
                html_body
            )
            if ok:
                sent += 1
                app.logger.warning(f'[send-reports] ✅ sent to {reg.full_name} ({reg.email}) img={img.file_number}')
            else:
                failed += 1
                app.logger.warning(f'[send-reports] Brevo error for {reg.email}')
        except Exception as e:
            app.logger.error(f'[send-reports] failed for {reg.email}: {e}')
            failed += 1

    msg = f'Reports sent: {sent}'
    if skipped: msg += f' · {skipped} skipped (no image match)'
    if failed:  msg += f' · {failed} failed'
    flash(msg, 'success' if not failed else 'warning')
    return redirect(url_for('admin_session_detail', token=token))


# ── SESSION 155 ROUTES ───────────────────────────────────────────────────────

# ── SESSION 160 ROUTES ───────────────────────────────────────────────────────
# 1. /api/sl-ddi-push        — SL webhook: pushes DDI scores when image scored
# 2. /admin/session/<>/ddi-waiting-room — Admin watches DDI populate live
# 3. /admin/session/<>/ddi-status       — JSON poll endpoint for waiting room
# 4. /admin/session/<>/split-screen     — Split screen: peer vs DDI per image
# 5. /admin/session/<>/split-advance    — Advance split screen image
# 6. /admin/session/<>/send-reports     — Upgraded: individual HTML emails
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. SL WEBHOOK — DDI push ─────────────────────────────────────────────────

@app.route('/api/sl-ddi-push', methods=['POST'])
def sl_ddi_push():
    """
    Called by SL when an image is scored and original_filename matches a MIM image.
    Payload: { api_key, filename, ddi_score, ddi_craft, ddi_theme,
               ddi_theme_paragraph, ddi_narrative, dimensions:{} }
    """
    data = request.get_json(silent=True) or {}
    expected_key = os.environ.get('MIM_SL_API_KEY', '')
    if not expected_key or data.get('api_key') != expected_key:
        app.logger.warning('[sl-ddi-push] unauthorized')
        return jsonify({'error': 'unauthorized'}), 401

    filename = (data.get('filename') or '').strip()
    if not filename:
        return jsonify({'error': 'filename required'}), 400

    # ── Session 160.2: Guard — only match images uploaded through MIM ─────────
    # Without this, any SL user whose filename accidentally matches a MIM session
    # image would overwrite that image's DDI score. We only accept pushes for
    # images where uploaded_by_self=True (photographer used their personal MIM
    # upload link) OR where the session is active (not archived/test-only).
    img = MIMImage.query.filter_by(
        original_filename=filename,
        uploaded_by_self=True
    ).first()

    if not img:
        # Also try without uploaded_by_self restriction for admin-uploaded images
        # (admin uploaded on behalf via emergency upload) — but only if session is active
        img_any = MIMImage.query.filter_by(original_filename=filename).first()
        if img_any:
            _sess = MIMSession.query.get(img_any.session_id)
            # Only accept if session is in an active state (not archived, not test)
            if _sess and not _sess.is_test and _sess.status not in ('archived',):
                img = img_any
            else:
                app.logger.warning(
                    f'[sl-ddi-push] rejected: filename={filename} matches MIM image '
                    f'but session is test/archived or not uploaded through MIM upload flow'
                )
                return jsonify({'found': False})

    if not img:
        app.logger.warning(f'[sl-ddi-push] no MIM image for filename={filename}')
        return jsonify({'found': False})

    try:
        img.ddi_score     = data.get('ddi_score')
        img.ddi_craft     = data.get('ddi_craft') or data.get('ddi_score')
        img.ddi_theme     = data.get('ddi_theme')
        _craft_narrative  = (data.get('ddi_narrative') or '').strip()
        _theme_para       = (data.get('ddi_theme_paragraph') or '').strip()
        if _theme_para:
            _s = MIMSession.query.get(img.session_id)
            _label = f'Theme ({_s.theme.title() if _s else "Session"}): {_theme_para}'
            img.ddi_narrative = '\n\n'.join(filter(None, [_craft_narrative, _label]))
        else:
            img.ddi_narrative = _craft_narrative
        img.ddi_dimensions = json.dumps(data.get('dimensions', {}))
        db.session.commit()
        app.logger.warning(
            f'[sl-ddi-push] ✅ filename={filename} image_id={img.id} '
            f'ddi_score={img.ddi_score} ddi_theme={img.ddi_theme}'
        )
        return jsonify({'ok': True, 'image_id': img.id})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'[sl-ddi-push] DB error: {e}')
        return jsonify({'error': 'db error'}), 500


# ── 2. DDI WAITING ROOM ───────────────────────────────────────────────────────

@app.route('/admin/session/<token>/ddi-waiting-room')
@admin_required
def admin_ddi_waiting_room(token):
    """Admin watches DDI scores populate live as photographers upload to SL."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(
        session_id=s.id).order_by(MIMImage.file_number).all()
    ddi_count = sum(1 for img in images if img.ddi_score is not None)
    return render_template('admin_ddi_waiting_room.html',
                           s=s, images=images, ddi_count=ddi_count)


# ── 3. DDI STATUS JSON (waiting room polling) ─────────────────────────────────

@app.route('/admin/session/<token>/ddi-status')
@admin_required
def admin_ddi_status(token):
    """JSON endpoint — waiting room polls every 10s."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(
        session_id=s.id).order_by(MIMImage.file_number).all()
    return jsonify({
        'total': len(images),
        'done':  sum(1 for img in images if img.ddi_score is not None),
        'images': [{
            'file_number': img.file_number,
            'ddi_score':   img.ddi_score,
            'ddi_theme':   img.ddi_theme,
            'ddi_craft':   img.ddi_craft,
            'has_ddi':     img.ddi_score is not None,
        } for img in images]
    })


# ── 4. SPLIT SCREEN REVEAL ───────────────────────────────────────────────────

@app.route('/admin/session/<token>/split-screen')
@admin_required
def admin_split_screen(token):
    """Split screen: left = peer eval, right = DDI. Admin advances image by image."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(
        session_id=s.id).order_by(MIMImage.file_number).all()

    current = s.reveal_current_image or 1
    current_img = next((i for i in images if i.file_number == current), None)
    current_evals = []
    peer_theme_avg = peer_craft_avg = None

    if current_img:
        evals = MIMEvaluation.query.filter_by(image_id=current_img.id).all()
        n = len(evals)
        peer_theme_avg = round(sum(e.theme_score for e in evals) / n, 2) if n else None
        peer_craft_avg = round(sum(e.craft_score for e in evals) / n, 2) if n else None
        current_evals = evals

    return render_template('admin_split_screen.html',
                           s=s, images=images,
                           current=current,
                           current_img=current_img,
                           current_evals=current_evals,
                           peer_theme_avg=peer_theme_avg,
                           peer_craft_avg=peer_craft_avg)


# ── 5. SPLIT SCREEN ADVANCE ──────────────────────────────────────────────────

@app.route('/admin/session/<token>/split-advance', methods=['POST'])
@admin_required
def admin_split_advance(token):
    s = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id).all()
    direction = request.form.get('direction', 'next')
    current = s.reveal_current_image or 1
    if direction == 'next':
        s.reveal_current_image = min(current + 1, len(images) + 1)
    else:
        s.reveal_current_image = max(current - 1, 1)
    db.session.commit()
    return redirect(url_for('admin_split_screen', token=token))


# ── 6. SEND REPORTS (upgraded Session 160) ───────────────────────────────────


# 1. Enhanced CSV export — per-evaluator breakdown + per-dimension DDI
# 2. Individual photographer PDF report (WhatsApp-shareable)
# 3. Reset session status (Reset to Setup / Open Eval / Close Eval / Publish)
# 4. Archive session
# 5. Delete Images from Volume
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. ENHANCED CSV EXPORT ────────────────────────────────────────────────────

@app.route('/admin/session/<token>/download-csv')
@admin_required
def admin_session_download_csv(token):
    """
    Full session CSV — per-evaluator breakdown + per-dimension DDI.
    Columns: File No · Photographer · SL Username · Peer Theme Avg · Peer Craft Avg ·
    Peer Evaluators · EvalN File# · EvalN Theme · EvalN Craft · EvalN What Worked ·
    EvalN What to Change (×up to 9) · DDI Score · DDI Craft · DDI Theme ·
    DDI DoD · DDI Disruption · DDI DM · DDI Wonder · DDI AQ ·
    Sherpa Narrative · Theme Gap (DDI−Peer) · Craft Gap (DDI−Peer)
    """
    s      = MIMSession.query.filter_by(token=token).first_or_404()
    images = MIMImage.query.filter_by(session_id=s.id)\
                 .order_by(MIMImage.file_number).all()

    # Build eval map and find max evaluators for column width
    max_evals = 0
    eval_map  = {}
    for img in images:
        evals = MIMEvaluation.query.filter_by(image_id=img.id)\
                    .order_by(MIMEvaluation.evaluator_file_number).all()
        eval_map[img.id] = evals
        max_evals = max(max_evals, len(evals))

    output = io.StringIO()
    w      = csv.writer(output)

    # Header
    base_hdr = ['File No', 'Photographer', 'SL Username',
                 'Peer Theme Avg', 'Peer Craft Avg', 'Peer Evaluators']
    eval_hdr = []
    for i in range(1, max_evals + 1):
        eval_hdr += [f'Eval{i} File#', f'Eval{i} Theme', f'Eval{i} Craft',
                     f'Eval{i} What Worked', f'Eval{i} What to Change']
    ddi_hdr = ['DDI Score', 'DDI Craft', 'DDI Theme',
               'DDI DoD', 'DDI Disruption', 'DDI DM', 'DDI Wonder', 'DDI AQ',
               'Sherpa Narrative', 'Theme Gap (DDI-Peer)', 'Craft Gap (DDI-Peer)']
    w.writerow(base_hdr + eval_hdr + ddi_hdr)

    for img in images:
        evals = eval_map.get(img.id, [])

        theme_scores   = [e.theme_score for e in evals if e.theme_score is not None]
        craft_scores   = [e.craft_score for e in evals if e.craft_score is not None]
        peer_theme_avg = round(sum(theme_scores) / len(theme_scores), 2) if theme_scores else ''
        peer_craft_avg = round(sum(craft_scores) / len(craft_scores), 2) if craft_scores else ''

        base_row = [img.file_number, img.photographer_name or '',
                    img.sl_username or '', peer_theme_avg, peer_craft_avg, len(evals)]

        eval_row = []
        for i in range(max_evals):
            if i < len(evals):
                e = evals[i]
                eval_row += [e.evaluator_file_number, e.theme_score, e.craft_score,
                             (e.what_worked    or '').strip(),
                             (e.what_to_change or '').strip()]
            else:
                eval_row += ['', '', '', '', '']

        # DDI dimensions from JSON
        _dod = _dis = _dm = _wnd = _aq = ''
        try:
            if img.ddi_dimensions:
                _dims = json.loads(img.ddi_dimensions) if isinstance(img.ddi_dimensions, str) else img.ddi_dimensions
                _dod = _dims.get('DoD', '')
                _dis = _dims.get('Disruption', '')
                _dm  = _dims.get('DM', '')
                _wnd = _dims.get('Wonder', '')
                _aq  = _dims.get('AQ', '')
        except Exception:
            pass

        _theme_gap = _craft_gap = ''
        if img.ddi_theme is not None and peer_theme_avg != '':
            try: _theme_gap = round(float(img.ddi_theme) - float(peer_theme_avg), 2)
            except Exception: pass
        if img.ddi_craft is not None and peer_craft_avg != '':
            try: _craft_gap = round(float(img.ddi_craft) - float(peer_craft_avg), 2)
            except Exception: pass

        ddi_row = [
            round(img.ddi_score, 2) if img.ddi_score is not None else '',
            round(img.ddi_craft, 2) if img.ddi_craft is not None else '',
            round(img.ddi_theme, 2) if img.ddi_theme is not None else '',
            _dod, _dis, _dm, _wnd, _aq,
            (img.ddi_narrative or '').strip(),
            _theme_gap, _craft_gap,
        ]
        w.writerow(base_row + eval_row + ddi_row)

    output.seek(0)
    from flask import Response
    return Response(
        output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=MIM_{s.token}_export.csv'}
    )


# ── 2. INDIVIDUAL PHOTOGRAPHER PDF REPORT ─────────────────────────────────────

@app.route('/admin/session/<token>/photographer-pdf/<int:file_number>')
@admin_required
def admin_photographer_pdf(token, file_number):
    """
    One PDF per photographer — 4 sections:
    1. Identity card  2. All peer comments  3. DDI guidance  4. Comparison
    WhatsApp-shareable. Uses reportlab (pure Python, no wkhtmltopdf needed).
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, HRFlowable)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
    except ImportError:
        return 'reportlab not installed. Add reportlab to requirements.txt and redeploy.', 500

    s   = MIMSession.query.filter_by(token=token).first_or_404()
    img = MIMImage.query.filter_by(session_id=s.id, file_number=file_number).first_or_404()
    evals = MIMEvaluation.query.filter_by(image_id=img.id)\
                .order_by(MIMEvaluation.evaluator_file_number).all()

    # Colours
    NAVY  = rl_colors.HexColor('#1B2B5E')
    GOLD  = rl_colors.HexColor('#C8A951')
    CREAM = rl_colors.HexColor('#FEFCF8')
    SLATE = rl_colors.HexColor('#4A5568')
    WHITE = rl_colors.white
    LGREY = rl_colors.HexColor('#F0EEE9')

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    base   = getSampleStyleSheet()
    h1_s   = ParagraphStyle('H1', parent=base['Normal'],
                fontSize=20, leading=28, textColor=NAVY,
                fontName='Helvetica-Bold', spaceAfter=6)
    h2_s   = ParagraphStyle('H2', parent=base['Normal'],
                fontSize=14, leading=20, textColor=NAVY,
                fontName='Helvetica-Bold', spaceBefore=16, spaceAfter=6)
    h3_s   = ParagraphStyle('H3', parent=base['Normal'],
                fontSize=12, leading=18, textColor=SLATE,
                fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4)
    body_s = ParagraphStyle('Body', parent=base['Normal'],
                fontSize=13, leading=20, textColor=rl_colors.black,
                fontName='Helvetica', spaceAfter=6)
    cap_s  = ParagraphStyle('Cap', parent=base['Normal'],
                fontSize=11, leading=17, textColor=SLATE,
                fontName='Helvetica', spaceAfter=4)
    lbl_s  = ParagraphStyle('Lbl', parent=base['Normal'],
                fontSize=11, leading=17, textColor=GOLD,
                fontName='Helvetica-Bold', spaceAfter=2)
    scr_s  = ParagraphStyle('Scr', parent=base['Normal'],
                fontSize=28, leading=36, textColor=NAVY,
                fontName='Helvetica-Bold', alignment=TA_CENTER)

    story = []

    def hr():
        story.append(HRFlowable(width='100%', thickness=1, color=LGREY,
                                spaceAfter=12, spaceBefore=12))

    def tbl_style(data, col_widths, header=True):
        t = Table(data, colWidths=col_widths)
        ts = [
            ('FONTSIZE',  (0,0), (-1,-1), 12),
            ('LEADING',   (0,0), (-1,-1), 18),
            ('GRID',      (0,0), (-1,-1), 0.5, rl_colors.HexColor('#D0CFC9')),
            ('PADDING',   (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0, 1 if header else 0), (-1,-1), [WHITE, LGREY]),
        ]
        if header:
            ts += [
                ('BACKGROUND', (0,0), (-1,0), NAVY),
                ('TEXTCOLOR',  (0,0), (-1,0), WHITE),
                ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ]
        t.setStyle(TableStyle(ts))
        return t

    # ── Section 1: Identity ────────────────────────────────────────────────────
    story.append(Paragraph('Making Images Matter', lbl_s))
    _date_str = img.mim_session.event_date.strftime('%-d %B %Y') if img.mim_session.event_date else ''
    story.append(Paragraph(f'{s.title}  ·  {_date_str}', cap_s))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(img.photographer_name or f'Photographer {img.file_number}', h1_s))
    if img.sl_username:
        story.append(Paragraph(f'Shutter League: @{img.sl_username}', cap_s))
    story.append(Paragraph(
        f'Image {img.file_number} of {s.total_images}  ·  Theme: {s.theme}  ·  Genre: {s.genre}',
        cap_s))
    hr()

    # Peer summary
    theme_scores   = [e.theme_score for e in evals if e.theme_score is not None]
    craft_scores   = [e.craft_score for e in evals if e.craft_score is not None]
    peer_theme_avg = round(sum(theme_scores)/len(theme_scores), 1) if theme_scores else None
    peer_craft_avg = round(sum(craft_scores)/len(craft_scores), 1) if craft_scores else None

    story.append(Paragraph('Peer Evaluation Summary', h2_s))
    sum_data = [['', 'Theme', 'Craft', 'Evaluators'],
                ['Peer Average',
                 f'{peer_theme_avg}/10' if peer_theme_avg is not None else '—',
                 f'{peer_craft_avg}/10' if peer_craft_avg is not None else '—',
                 str(len(evals))]]
    if img.ddi_score is not None:
        sum_data.append(['Evaluation (DDI)',
                         f'{round(img.ddi_theme,1)}/10' if img.ddi_theme is not None else '—',
                         f'{round(img.ddi_craft,1)}/10' if img.ddi_craft is not None else '—',
                         '—'])
    story.append(tbl_style(sum_data, [5*cm, 3*cm, 3*cm, 3*cm]))
    hr()

    # ── Section 2: All peer comments ──────────────────────────────────────────
    story.append(Paragraph('Peer Feedback — All Evaluators', h2_s))
    if not evals:
        story.append(Paragraph('No evaluations recorded for this image.', body_s))
    else:
        for idx, ev in enumerate(evals, 1):
            story.append(Paragraph(f'Evaluator {ev.evaluator_file_number}', h3_s))
            story.append(Paragraph(f'Theme: {ev.theme_score}/10    Craft: {ev.craft_score}/10', cap_s))
            if (ev.what_worked or '').strip():
                story.append(Paragraph('What made this image work:', lbl_s))
                story.append(Paragraph(ev.what_worked.strip(), body_s))
            if (ev.what_to_change or '').strip():
                story.append(Paragraph('What to change:', lbl_s))
                story.append(Paragraph(ev.what_to_change.strip(), body_s))
            if idx < len(evals):
                story.append(Spacer(1, 0.3*cm))
    hr()

    # ── Section 3: DDI Evaluation ─────────────────────────────────────────────
    story.append(Paragraph('Evaluation Guidance', h2_s))
    if img.ddi_score is None:
        story.append(Paragraph('Evaluation guidance not yet available for this image.', body_s))
    else:
        story.append(Paragraph(f'{round(img.ddi_score, 1)}/10', scr_s))
        story.append(Spacer(1, 0.3*cm))

        _dod = _dis = _dm_v = _wnd = _aq = None
        try:
            if img.ddi_dimensions:
                _d = json.loads(img.ddi_dimensions) if isinstance(img.ddi_dimensions, str) else img.ddi_dimensions
                _dod, _dis, _dm_v, _wnd, _aq = (_d.get('DoD'), _d.get('Disruption'),
                                                  _d.get('DM'), _d.get('Wonder'), _d.get('AQ'))
        except Exception:
            pass

        dim_data = [
            ['Dimension', 'Rating', 'What it measures'],
            ['Depth of Difficulty',  f'{round(_dod,1)}'  if _dod  else '—', 'Technical challenge and execution'],
            ['Disruption',           f'{round(_dis,1)}'  if _dis  else '—', 'How much it breaks the expected'],
            ['Decisive Moment',      f'{round(_dm_v,1)}' if _dm_v else '—', 'Timing and peak action'],
            ['Wonder',               f'{round(_wnd,1)}'  if _wnd  else '—', 'Emotional and visual impact'],
            ['Aesthetic Quality',    f'{round(_aq,1)}'   if _aq   else '—', 'Composition, light, form'],
        ]
        story.append(tbl_style(dim_data, [6*cm, 2.5*cm, 7.5*cm]))
        story.append(Spacer(1, 0.4*cm))

        if (img.ddi_narrative or '').strip():
            story.append(Paragraph('Guidance Note', h3_s))
            for para in img.ddi_narrative.strip().split('\n\n'):
                if para.strip():
                    story.append(Paragraph(para.strip(), body_s))
    hr()

    # ── Section 4: Comparison ─────────────────────────────────────────────────
    story.append(Paragraph('Peer vs Evaluation — Comparison', h2_s))
    if peer_theme_avg is not None and img.ddi_theme is not None:
        theme_gap = round(img.ddi_theme - peer_theme_avg, 1)
        craft_gap = round(img.ddi_craft - peer_craft_avg, 1) if (img.ddi_craft and peer_craft_avg) else None

        comp_data = [
            ['', 'Theme', 'Craft'],
            ['Peer Average',     f'{peer_theme_avg}/10',
             f'{peer_craft_avg}/10' if peer_craft_avg else '—'],
            ['Evaluation (DDI)', f'{round(img.ddi_theme,1)}/10',
             f'{round(img.ddi_craft,1)}/10' if img.ddi_craft else '—'],
            ['Gap (DDI − Peer)',
             f'{"+" if theme_gap > 0 else ""}{theme_gap}',
             f'{"+" if craft_gap and craft_gap > 0 else ""}{craft_gap}' if craft_gap is not None else '—'],
        ]
        story.append(tbl_style(comp_data, [6*cm, 4*cm, 4*cm]))
        story.append(Spacer(1, 0.4*cm))

        if abs(theme_gap) <= 0.5:
            interp = 'The room and the evaluation were closely aligned on theme.'
        elif theme_gap > 0:
            interp = (f'The evaluation rated theme {theme_gap} points higher than the room. '
                      f'The image may have more conceptual depth than was immediately visible to peers.')
        else:
            interp = (f'The room rated theme {abs(theme_gap)} points higher than the evaluation. '
                      f'Strong immediate visual impression — worth examining whether the theme connection holds on second viewing.')
        story.append(Paragraph(interp, body_s))
    else:
        story.append(Paragraph('Comparison not available — peer data or evaluation data missing.', body_s))

    # Footer
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width='100%', thickness=1, color=LGREY, spaceAfter=8))
    story.append(Paragraph(
        f'Making Images Matter  ·  {s.title}  ·  For participant use only', cap_s))

    doc.build(story)
    buf.seek(0)

    safe = (img.photographer_name or f'photographer_{file_number}').replace(' ', '_')
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True,
                     download_name=f'MIM_{s.token}_{safe}_report.pdf')


# ── 3. SET SESSION STATUS (Reset / Unpublish / Archive) ───────────────────────

@app.route('/admin/session/<token>/set-status', methods=['POST'])
@admin_required
def admin_set_session_status(token):
    """Change session status — Reset to Setup / Open Eval / Close Eval / Publish / Archive."""
    s      = MIMSession.query.filter_by(token=token).first_or_404()
    new_st = request.form.get('status', '').strip()
    VALID  = ('setup', 'eval_open', 'eval_closed', 'published', 'archived')
    if new_st not in VALID:
        flash(f'Invalid status: {new_st!r}')
        return redirect(url_for('admin_session_detail', token=token))
    old_st   = s.status
    s.status = new_st
    if new_st == 'published' and not s.published_at:
        s.published_at = datetime.utcnow()
    db.session.commit()
    flash(f'Status changed: {old_st} → {new_st}')
    return redirect(url_for('admin_session_detail', token=token))


# ── 4. ARCHIVE SESSION ────────────────────────────────────────────────────────

@app.route('/admin/session/<token>/archive', methods=['POST'])
@admin_required
def admin_archive_session(token):
    """Archive — hides session from landing and registration. Export CSV first."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status not in ('published', 'eval_closed'):
        flash('Can only archive a published or closed session.')
        return redirect(url_for('admin_session_detail', token=token))
    s.status = 'archived'
    db.session.commit()
    flash('Session archived. Hidden from landing and registration pages.')
    return redirect(url_for('admin_session_detail', token=token))


# ── 5. DELETE IMAGES FROM VOLUME ──────────────────────────────────────────────



# ── SET SESSION LIVE / OFFLINE ────────────────────────────────────────────────

@app.route('/admin/session/<token>/set-live', methods=['POST'])
@admin_required
def admin_set_live(token):
    """Set this session as the live registration session. Clears all others."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    # Clear existing live session
    MIMSession.query.filter_by(is_live=True).update({'is_live': False})
    s.is_live = True
    s.is_test = False
    db.session.commit()
    flash(f'"{s.title}" is now live on the register page.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/set-offline', methods=['POST'])
@admin_required
def admin_set_offline(token):
    """Take this session offline from the register page."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.is_live = False
    db.session.commit()
    flash(f'"{s.title}" removed from register page.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/set-test', methods=['POST'])
@admin_required
def admin_set_test(token):
    """Mark this session as a test session — never shows on register page."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.is_test = True
    s.is_live = False
    db.session.commit()
    flash(f'"{s.title}" marked as test session.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/schedule-live', methods=['POST'])
@admin_required
def admin_schedule_live(token):
    """Schedule this session to go live at a specific datetime."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    go_live_str = request.form.get('go_live_at', '').strip()
    try:
        go_live_dt = datetime.strptime(go_live_str, '%Y-%m-%dT%H:%M')
        s.go_live_at = go_live_dt
        s.is_test = False
        db.session.commit()
        flash(f'"{s.title}" scheduled to go live at {go_live_dt.strftime("%d %b %Y %H:%M")}.')
    except ValueError:
        flash('Invalid date format. Use YYYY-MM-DDTHH:MM.')
    return redirect(url_for('admin_session_detail', token=token))


# ── TEST SESSION PAGE ─────────────────────────────────────────────────────────

@app.route('/test-register')
def test_register():
    """
    Separate test register page — shows the most recent test session.
    Never interferes with the live register page.
    Admin use only for end-to-end testing.
    """
    s = MIMSession.query.filter(
        MIMSession.is_test == True,
        MIMSession.status == 'setup'
    ).order_by(MIMSession.created_at.desc()).first()

    if not s:
        return '<h2 style="font-family:sans-serif;padding:40px;">No test session active. Create one from admin and mark as Test.</h2>'

    reg_count = MIMRegistration.query.filter_by(session_id=s.id, is_waitlist=False).count()
    capacity  = s.capacity or 10
    seats_full = reg_count >= capacity

    return render_template('register.html', s=s, reg_count=reg_count,
                           capacity=capacity, seats_full=seats_full,
                           is_test=True)


# ── 5a. CLOSE / REOPEN REGISTRATIONS ─────────────────────────────────────────

@app.route('/admin/session/<token>/close-registrations', methods=['POST'])
@admin_required
def admin_close_registrations(token):
    """Manually close registrations without changing session status."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.registration_closed = True
    db.session.commit()
    flash('Registrations closed.')
    return redirect(url_for('admin_session_detail', token=token))


@app.route('/admin/session/<token>/reopen-registrations', methods=['POST'])
@admin_required
def admin_reopen_registrations(token):
    """Re-open registrations if closed manually."""
    s = MIMSession.query.filter_by(token=token).first_or_404()
    s.registration_closed = False
    db.session.commit()
    flash('Registrations re-opened.')
    return redirect(url_for('admin_session_detail', token=token))


# ── Session 160.5: DELETE REGISTRATION ───────────────────────────────────────

@app.route('/admin/registration/<int:reg_id>/delete', methods=['POST'])
@admin_required
def admin_delete_registration(reg_id):
    """
    Remove a single registration. Frees up their seat so another photographer
    can register. Silent to participant — admin gets email confirmation.
    """
    reg = MIMRegistration.query.get_or_404(reg_id)
    _name = reg.full_name
    _email = reg.email
    _mobile = reg.mobile
    _token = None
    _session_title = ''
    try:
        _s = MIMSession.query.get(reg.session_id)
        if _s:
            _token = _s.token
            _session_title = f'{_s.title} · {_s.event_date.strftime("%d %b %Y")}'
    except Exception:
        pass

    db.session.delete(reg)
    db.session.commit()
    app.logger.warning(f'[delete-reg] removed: {_name} ({_email}) session={_session_title}')

    # ── Notify admin ──────────────────────────────────────────────────────────
    try:
        _admin_email = os.environ.get('ADMIN_EMAIL', 'sree@thelivinglens.in')
        _body = f"""
        <div style="font-family:Inter,sans-serif;max-width:480px;color:#0F1F3D;padding:24px;">
          <p style="font-size:16px;font-weight:700;margin-bottom:12px;">Registration Removed</p>
          <p style="font-size:15px;color:#5C5040;margin-bottom:8px;">Session: <strong>{_session_title}</strong></p>
          <p style="font-size:15px;color:#5C5040;margin-bottom:4px;">Name: <strong>{_name}</strong></p>
          <p style="font-size:15px;color:#5C5040;margin-bottom:4px;">Email: {_email}</p>
          <p style="font-size:15px;color:#5C5040;margin-bottom:16px;">Mobile: {_mobile}</p>
          <p style="font-size:14px;color:#9B8F82;">Their seat is now available. Re-open registrations if you want them to re-register.</p>
        </div>
        """
        send_email(_admin_email, f'MIM — Registration removed: {_name}', _body)
    except Exception as _e:
        app.logger.warning(f'[delete-reg] admin email failed: {_e}')

    flash(f'{_name} removed from the session. Seat is now available. Admin notified.')
    return redirect(url_for('admin_registrations'))


# ── 5b. DELETE SESSION ────────────────────────────────────────────────────────

@app.route('/admin/session/<token>/delete-session', methods=['POST'])
@admin_required
def admin_delete_session(token):
    """
    Permanently delete a session and all its images, evaluations, registrations.
    NOT permitted on eval_open (prevents live-session accidents).
    """
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status == 'eval_open':
        flash('Cannot delete a session while evaluation is open. Close eval first.')
        return redirect(url_for('admin_session_detail', token=token))

    title = s.title
    for img in MIMImage.query.filter_by(session_id=s.id).all():
        MIMEvaluation.query.filter_by(image_id=img.id).delete()
    MIMImage.query.filter_by(session_id=s.id).delete()
    MIMRegistration.query.filter_by(session_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()

    flash(f'Session \u201c{title}\u201d permanently deleted.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/session/<token>/delete-images', methods=['POST'])
@admin_required
def admin_delete_session_images(token):
    """
    Remove all image files for this session from Railway Volume.
    Only available on archived sessions. DB metadata preserved.
    """
    import glob, os as _os
    s = MIMSession.query.filter_by(token=token).first_or_404()
    if s.status != 'archived':
        flash('Archive the session and export the CSV before deleting images.')
        return redirect(url_for('admin_session_detail', token=token))

    UPLOAD_DIR = '/app/static/uploads'
    pattern    = _os.path.join(UPLOAD_DIR, f'session_{token}_img_*')
    files      = glob.glob(pattern)
    deleted    = 0
    for fpath in files:
        try:
            _os.remove(fpath)
            deleted += 1
        except OSError:
            pass

    # Clear filename on MIMImage rows — keep all other metadata
    for img in MIMImage.query.filter_by(session_id=s.id).all():
        img.filename          = None
        img.original_filename = None
        img.uploaded_by_self  = False
    db.session.commit()
    flash(f'Deleted {deleted} image file(s) from Volume. Database records kept.')
    return redirect(url_for('admin_session_detail', token=token))


# ── END SESSION 155 ROUTES ────────────────────────────────────────────────────


# ── Init ──────────────────────────────────────────────────────────────────────

with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass  # Tables already exist on restart

    # ── Safe column migrations ────────────────────────────────────────────────
    # db.create_all() does not add columns to existing tables.
    # Each ALTER TABLE is wrapped individually — if the column already exists
    # Postgres raises an error which we catch and ignore silently.
    _migrations = [
        # mim_sessions
        "ALTER TABLE mim_sessions ADD COLUMN reveal_current_image INTEGER DEFAULT 0",
        # mim_images
        "ALTER TABLE mim_images ADD COLUMN original_filename VARCHAR(255)",
        "ALTER TABLE mim_images ADD COLUMN upload_token VARCHAR(32)",
        "ALTER TABLE mim_images ADD COLUMN uploaded_by_self BOOLEAN DEFAULT FALSE",
        # Session 155 — DDI 5-dimension JSON storage
        "ALTER TABLE mim_images ADD COLUMN ddi_dimensions TEXT",
        # Session 158-159 — registration and live flags
        "ALTER TABLE mim_sessions ADD COLUMN registration_closed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE mim_sessions ADD COLUMN is_live BOOLEAN DEFAULT FALSE",
        "ALTER TABLE mim_sessions ADD COLUMN go_live_at TIMESTAMP",
        "ALTER TABLE mim_sessions ADD COLUMN is_test BOOLEAN DEFAULT FALSE",
    ]
    for _sql in _migrations:
        try:
            db.session.execute(db.text(_sql))
            db.session.commit()
            app.logger.warning(f'[migration] OK: {_sql[:60]}')
        except Exception as _e:
            db.session.rollback()
            # Column already exists — expected on all restarts after first deploy
            app.logger.warning(f'[migration] skip (already exists): {_sql[:60]}')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))

