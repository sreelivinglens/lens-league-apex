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
from models import (db, User, Image, CalibrationLog, ContestEntry, OpenContestEntry, ImageReport,
                    RatingAssignment, PeerRating, PeerPoolEntry,
                    get_or_assign_next_image, submit_peer_rating)
from engine.scoring import (calculate_score, get_tier, GENRE_WEIGHTS, GENRE_IDS,
                              normalise_genre, ARCHETYPES, compute_calibration_stats,
                              OPEN_PRIZES, GENRE_LABELS, GENRE_CHOICES)
from engine.processor import ingest_image, allowed_file
import storage as r2

load_dotenv()

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
        stats = {
            'total_images': Image.query.filter_by(status='scored').count(),
            'total_members': User.query.filter(User.role != 'admin').count(),
            'avg_score': db.session.query(db.func.avg(Image.score))
                           .filter(Image.score != None).scalar() or 0,
        }
        top_images = (Image.query
                      .filter(Image.status=='scored', Image.score != None)
                      .order_by(Image.score.desc())
                      .limit(6).all())
        example_image = (Image.query
                         .filter(Image.status=='scored', Image.score != None)
                         .order_by(db.func.random())
                         .first())
    except Exception:
        stats = {'total_images': 0, 'total_members': 0, 'avg_score': 0}
        top_images = []
        example_image = None
    return render_template('index.html', stats=stats, top_images=top_images, example_image=example_image, now=datetime.utcnow())


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        if not request.form.get('agreed') and not request.form.get('user_agreed'):
            flash('You must accept the Member Agreement to register.', 'error')
            return redirect(url_for('register'))
        email    = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        fullname = request.form.get('full_name', '').strip()
        sq       = request.form.get('security_question', '').strip()
        sa       = request.form.get('security_answer', '').strip().lower()
        if not sq or not sa:
            flash('Please select a security question and provide an answer.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return redirect(url_for('register'))
        user = User(
            email=email, username=username,
            password_hash=generate_password_hash(password),
            full_name=fullname, security_question=sq,
            security_answer=sa, agreed_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Welcome to Lens League!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            # Check for images flagged as AI-generated since last login
            last_seen = user.last_login or datetime(2000, 1, 1)
            flagged_since = Image.query.filter(
                Image.user_id == user.id,
                Image.is_flagged == True,
                Image.flagged_at != None,
                Image.flagged_at > last_seen
            ).count()
            # Check for images held under review (amber zone or Grandmaster)
            review_pending = Image.query.filter(
                Image.user_id == user.id,
                Image.needs_review == True,
                Image.is_flagged == False
            ).count()
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            if flagged_since:
                flash(
                    f'⚠️ {flagged_since} of your image{"s" if flagged_since > 1 else ""} '
                    f'{"were" if flagged_since > 1 else "was"} flagged as potentially AI-generated '
                    f'and removed from public view. Visit your dashboard to review.',
                    'warning'
                )
            if review_pending:
                flash(
                    f'🔍 {review_pending} of your image{"s" if review_pending > 1 else ""} '
                    f'{"are" if review_pending > 1 else "is"} currently under admin review '
                    f'and not yet visible to the public.',
                    'info'
                )
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
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

    return render_template('dashboard.html', images=images, stats=stats,
                           query=query, search_enabled=(total_images >= 20),
                           rating_widget=rating_widget)


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

        from engine.exif_check import extract_exif
        exif_status, exif_data, exif_warning = extract_exif(thumb_path)
        exif_settings = '  ·  '.join(filter(None, [
            exif_data.get('focal_length',''), exif_data.get('aperture',''),
            exif_data.get('iso',''), exif_data.get('shutter',''),
        ]))

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
            exif_date_taken=exif_data.get('date_taken', ''),
            exif_settings=exif_settings, exif_warning=exif_warning,
        )
        db.session.add(img)
        db.session.commit()

        # ── EXIF track cheat detection ────────────────────────────────────
        # If user is on mobile track but EXIF shows a known camera brand → flag for review
        _CAMERA_BRANDS = ('canon', 'nikon', 'sony', 'fuji', 'fujifilm', 'olympus',
                          'panasonic', 'leica', 'hasselblad', 'pentax', 'sigma', 'ricoh')
        _user_track = getattr(current_user, 'subscription_track', None) or ''
        _exif_cam   = (exif_data.get('camera', '') or '').lower()
        if _user_track == 'mobile' and any(b in _exif_cam for b in _CAMERA_BRANDS):
            img.needs_review = True
            img.exif_warning = (img.exif_warning or '') + \
                f' [TRACK MISMATCH: Camera EXIF "{exif_data.get("camera","")}" detected on Mobile subscription]'
            db.session.commit()
            app.logger.warning(f'[exif_cheat] user={current_user.id} image={img.id} exif={_exif_cam}')

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
                        'If you believe this is an error, contact verify@lensleague.com.',
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
                                f'Email your original RAW file to verify@lensleague.com within 7 days.',
                                'warning'
                            )
                        else:
                            flash(
                                f'⚠️ Your image has been flagged for human review before going public. '
                                f'This is usually resolved within 24–48 hours. '
                                f'Contact verify@lensleague.com if you have questions.',
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
                    'message': '🚫 This image has been flagged as potentially AI-generated and cannot be submitted. Only original photographs taken by you are accepted. If you believe this is an error, contact verify@lensleague.com.',
                    'redirect': url_for('dashboard')
                })
            if getattr(img, 'needs_review', False):
                if img.score >= 9.0:
                    msg = (f'🏆 Grandmaster score ({img.score})! Your image has been held for RAW verification. '
                           f'Email your original RAW file to verify@lensleague.com within 7 days.')
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

    import io, tempfile, zipfile, os as _os
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

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf,'w',zipfile.ZIP_DEFLATED) as zf:
            zf.write(t1.name, f'LensLeague_{clean}_ScoreCard.jpg')
            zf.write(t2.name, f'LensLeague_{clean}_Analysis.jpg')
        zip_bytes = zip_buf.getvalue()

    finally:
        for p in [t1.name if t1 else None, t2.name if t2 else None, photo_tmp]:
            try:
                if p: _os.unlink(p)
            except: pass

    from flask import Response
    return Response(
        zip_bytes,
        headers={
            'Content-Type':              'application/zip',
            'Content-Disposition':       f'attachment; filename="LensLeague_{clean}_RatingCards.zip"',
            'Content-Length':            str(len(zip_bytes)),
            'Cache-Control':             'no-store, no-cache, must-revalidate',
            'Pragma':                    'no-cache',
            'X-Content-Type-Options':    'nosniff',
            'Content-Transfer-Encoding': 'binary',
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

    now = datetime.utcnow()
    if period == 'week':
        since = now - timedelta(days=7)
    elif period == 'month':
        since = now - timedelta(days=30)
    else:
        since = None

    def apply_filters(q):
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
        return q

    top_images = (apply_filters(Image.query)
                  .order_by(desc(Image.score))
                  .limit(20)
                  .all())

    # Top Photographers — grouped by user_id, sorted by avg_score DESC
    pg_base = (
        db.session.query(
            Image.user_id,
            User.username,
            User.full_name,
            func.avg(Image.score).label('avg_score'),
            func.max(Image.score).label('best_score'),
            func.count(Image.id).label('image_count'),
            func.sum(Image.peer_rating_count).label('total_peer_ratings'),
        )
        .join(User, Image.user_id == User.id)
    )
    pg_base = apply_filters(pg_base)
    pg_rows = (
        pg_base
        .group_by(Image.user_id, User.username, User.full_name)
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
            'avg_score':          round(float(row.avg_score), 2) if row.avg_score else 0,
            'best_score':         float(row.best_score) if row.best_score else 0,
            'image_count':        row.image_count,
            'total_peer_ratings': int(row.total_peer_ratings or 0),
        })

    all_tiers = ['Apprentice', 'Practitioner', 'Master', 'Grandmaster', 'Legend']

    return render_template('leaderboard.html',
        top_images         = top_images,
        photographer_stats = photographer_stats,
        all_genres         = GENRE_IDS,
        all_tiers          = all_tiers,
        genre              = genre,
        tier               = tier,
        period             = period,
        track              = track,
        tab                = tab,
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
    return render_template('admin.html', total_users=total_users, total_images=total_images,
                           scored=scored, pending=pending, recent=recent,
                           cal_stats=cal_stats, cal_trend=cal_trend, drift_alerts=drift_alerts,
                           all_users=all_users, open_reports_count=open_reports_count)


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
        user.subscription_plan  = 'beta'
        user.subscribed_at      = datetime.utcnow()
    else:
        user.subscription_track = None
        user.subscription_plan  = None
    db.session.commit()
    status = 'activated' if user.is_subscribed else 'deactivated'
    flash(f'Subscription {status} for {user.full_name or user.username}.', 'success')
    return redirect(url_for('admin_users'))


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

@app.route('/terms')
def terms():
    return render_template('terms.html')

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
            import razorpay
            client = razorpay.Client(auth=(razorpay_key, razorpay_secret))
            client.utility.verify_payment_signature({
                'razorpay_payment_id':      payment_id,
                'razorpay_subscription_id': subscription_id,
                'razorpay_signature':        signature,
            })

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


@app.route('/subscription/cancel', methods=['POST'])
@login_required
def cancel_subscription():
    current_user.is_subscribed       = False
    current_user.subscription_track  = None
    current_user.subscription_plan   = None
    db.session.commit()
    flash('Your subscription has been cancelled. You can continue on the free plan.', 'info')
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
