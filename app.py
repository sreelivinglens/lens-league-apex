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

from models import db, User, Image, CalibrationLog, CalibrationNote
from engine.scoring import (calculate_score, get_tier, GENRE_WEIGHTS, GENRE_IDS,
                              normalise_genre, ARCHETYPES, compute_calibration_stats,
                              OPEN_PRIZES)
from engine.processor import ingest_image, allowed_file
import storage as r2

load_dotenv()

FREE_IMAGE_LIMIT = 3  # Lifetime free images for non-subscribed users

app = Flask(__name__)
app.config['SECRET_KEY']          = os.getenv('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///lensleague.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']       = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH']  = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))

uri = app.config['SQLALCHEMY_DATABASE_URI']
if uri and uri.startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = uri.replace('postgres://', 'postgresql://', 1)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

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
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_subscribed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_track VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscribed_at TIMESTAMP",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_uploads_used INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_reset_date DATE",
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
    """
    Returns True if the Open Competition is currently accepting entries.
    Set OPEN_CONTEST_ACTIVE=1 in Railway env vars to enable.
    """
    return os.getenv('OPEN_CONTEST_ACTIVE', '0') == '1'


def is_bow_active() -> bool:
    """
    Returns True if Body of Work submissions are currently open.
    BOW accepts submissions from Month 1 through end of Month 11 of the platform year.
    Env var BOW_ACTIVE='1' enables; defaults to '0' (closed) until contest system is built.
    Replace with a date-range check tied to the platform year when subscription system is built.
    """
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
    except Exception:
        stats = {'total_images': 0, 'total_members': 0, 'avg_score': 0}
        top_images = []
    return render_template('index.html', stats=stats, top_images=top_images, now=datetime.utcnow())


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
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
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
    return render_template('dashboard.html', images=images, stats=stats,
                           query=query, search_enabled=(total_images >= 20))


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

        # ── Free quota check ──────────────────────────────────────────────
        if current_user.role != 'admin' and not getattr(current_user, 'is_subscribed', False):
            user_total = Image.query.filter_by(user_id=current_user.id).count()
            if user_total >= FREE_IMAGE_LIMIT:
                flash(
                    f'You have used all {FREE_IMAGE_LIMIT} free images. '
                    'Upgrade to Camera or Mobile track to continue uploading.',
                    'error'
                )
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

        # Normalise genre from form input
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
            camera_track      = getattr(current_user, 'subscription_track', None),
            phash             = phash,
            status            = 'pending',
            legal_declaration = bool(request.form.get('legal_declaration')),
            exif_status=exif_status, exif_camera=exif_data.get('camera', ''),
            exif_date_taken=exif_data.get('date_taken', ''),
            exif_settings=exif_settings, exif_warning=exif_warning,
        )
        db.session.add(img)
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
                img.dod_score=float(result.get('dod',0))
                img.disruption_score=float(result.get('disruption',0))
                img.dm_score=float(result.get('dm',0))
                img.wonder_score=float(result.get('wonder',0))
                img.aq_score=float(result.get('aq',0))
                img.score=float(result.get('score',0))
                img.tier=get_tier(float(result.get('score',0)))
                img.archetype=result.get('archetype','')
                img.soul_bonus=result.get('soul_bonus',False)
                img.status='scored'
                img.scored_at=datetime.utcnow()
                audit = build_audit_data(result, img)
                img.set_audit(audit)

                # Commit scores immediately — card building is non-critical
                db.session.commit()

                # Build and upload card — wrapped separately so a card failure
                # never rolls back the score that was already saved
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

        return redirect(url_for('image_detail', image_id=img.id))

    return render_template('upload.html', genres=GENRE_IDS)


@app.route('/image/<int:image_id>/retry-score', methods=['POST'])
@login_required
def retry_score(image_id):
    """User-facing retry for pending images where auto-scoring failed at upload time."""
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id:
        abort(403)
    if img.status == 'scored':
        flash('This image has already been scored.', 'info')
        return redirect(url_for('image_detail', image_id=image_id))
    if not img.thumb_path or not os.path.exists(img.thumb_path):
        # thumb_path not on disk — try fetching from R2
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

        # If thumb not on disk, download from R2 to a temp file
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

        # Build and upload card — non-critical, don't block on failure
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
    return render_template('image_detail.html', image=img, archetypes=ARCHETYPES)


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
    """Public. Generates two landscape cards and serves as ZIP."""
    img = Image.query.get_or_404(image_id)
    if not img.score:
        return "This image has not been scored yet.", 404

    import io, tempfile, zipfile, os as _os
    from engine.compositor import build_card1, build_card2

    audit = img.get_audit() or {}
    app.logger.info(f'[download] img={image_id} audit_keys={list(audit.keys())} rows_count={len(audit.get("rows",[]))} byline_1_len={len(audit.get("byline_1",""))} byline_2={len(audit.get("byline_2",""))} byline_2_body={len(audit.get("byline_2_body",""))}')
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
    """Redirect to R2 URL if available, otherwise serve local file."""
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
    if request.method == 'POST':
        current  = request.form.get('current_password', '')
        new_pw   = request.form.get('new_password', '')
        confirm  = request.form.get('confirm_password', '')
        if not check_password_hash(current_user.password_hash, current):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('change_password'))
        if len(new_pw) < 8:
            flash('New password must be at least 8 characters.', 'error')
            return redirect(url_for('change_password'))
        if new_pw != confirm:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('change_password'))
        current_user.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        db.session.refresh(current_user)
        flash('Password updated. Please log in again with your new password.', 'success')
        logout_user()
        return redirect(url_for('login'))
    return render_template('change_password.html')


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

        # ── Free quota check ──────────────────────────────────────────────
        if current_user.role != 'admin' and not getattr(current_user, 'is_subscribed', False):
            user_total = Image.query.filter_by(user_id=current_user.id).count()
            if user_total >= FREE_IMAGE_LIMIT:
                flash(
                    f'You have used all {FREE_IMAGE_LIMIT} free images. '
                    'Upgrade to Camera or Mobile track to continue uploading.',
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
                err_detail = traceback.format_exc()
                app.logger.error(f'Bulk upload error for {file.filename}: {err_detail}')
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


@app.route('/share/<int:image_id>')
def share_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.status != 'scored':
        abort(404)
    audit = img.get_audit()
    return render_template('share.html', image=img, audit=audit)


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
            Image.status == 'scored'
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

    pg_query = db.session.query(
        Image.photographer_name,
        func.max(Image.score).label('best_score'),
        func.avg(Image.score).label('avg_score'),
        func.count(Image.id).label('image_count')
    )
    pg_query = apply_filters(pg_query)
    photographer_stats = (pg_query
                          .group_by(Image.photographer_name)
                          .order_by(desc('best_score'))
                          .limit(10)
                          .all())

    all_tiers = ['Apprentice', 'Practitioner', 'Master', 'Grandmaster', 'Legend']

    return render_template('leaderboard.html',
        top_images=top_images,
        photographer_stats=photographer_stats,
        all_genres=GENRE_IDS,
        all_tiers=all_tiers,
        genre=genre,
        tier=tier,
        period=period,
        track=track,
        tab=tab,
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

    return render_template('admin.html', total_users=total_users, total_images=total_images,
                           scored=scored, pending=pending, recent=recent,
                           cal_stats=cal_stats, cal_trend=cal_trend, drift_alerts=drift_alerts,
                           all_users=all_users)


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
            db.session.delete(img)
            deleted += 1
        except Exception as e:
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
    """Score one image at a time — used by progressive bulk upload."""
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
    notes = CalibrationNote.query.order_by(CalibrationNote.created_at.desc()).all()
    return render_template('calibration_notes.html', notes=notes)


@app.route('/admin/calibration-notes/<int:note_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_calibration_note(note_id):
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

    # Top 3 images this month per genre per track (raw SQL for camera_track compatibility)
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
        open_contest_active= is_open_contest_active(),
        bow_active         = is_bow_active(),
    )


# ---------------------------------------------------------------------------
# Body of Work submission
# ---------------------------------------------------------------------------

@app.route('/bow/submit', methods=['GET', 'POST'])
@login_required
def bow_submit():
    """
    Body of Work submission entry point.
    Stub — full implementation in roadmap (contest system).
    When live: BOW_ACTIVE env var must be '1'.
    Requirements: active subscriber, 6–12 images scored on this account,
    cross-genre allowed, no track split, one submission per photographer per year,
    closes end of Month 11.
    """
    if not is_bow_active():
        flash('Body of Work submissions are not currently open. Check back from Month 1 of the platform year.', 'info')
        return redirect(url_for('contests'))

    if not getattr(current_user, 'is_subscribed', False):
        flash('An active Camera or Mobile subscription is required to submit a Body of Work.', 'error')
        return redirect(url_for('pricing'))

    # TODO: Implement full BOW submission flow:
    #   - Photographer selects 6–12 scored images from their account
    #   - Series title and thematic statement (required)
    #   - Confirm submission (cannot be modified after deadline)
    #   - Store in BodyOfWork model (to be created)
    #   - Assign to Jury Legends pool for evaluation
    flash('Body of Work submission is coming soon. Your scored images will be available to select when submissions open.', 'info')
    return redirect(url_for('contests'))


# ---------------------------------------------------------------------------
# Open Competition entry
# ---------------------------------------------------------------------------

@app.route('/open-contest/enter', methods=['GET', 'POST'])
@login_required
def open_contest_enter():
    """
    Open Competition entry point.
    Stub — full implementation in roadmap item #8 (contest system).
    When live: OPEN_CONTEST_ACTIVE env var must be '1'.
    Entry fee: ₹50/image (OPEN_PRIZES['Entry_Fee']).
    No track split — Camera and Mobile compete together.
    """
    if not is_open_contest_active():
        flash('The Open Competition is not currently accepting entries. Check back closer to Grand Prix.', 'info')
        return redirect(url_for('contests'))

    if not getattr(current_user, 'is_subscribed', False):
        flash('An active Camera or Mobile subscription is required to enter the Open Competition.', 'error')
        return redirect(url_for('pricing'))

    # TODO: Implement full Open Competition entry flow:
    #   - Genre selection (from GENRE_IDS)
    #   - Image selection (must be previously scored on this account)
    #   - Razorpay payment: OPEN_PRIZES['Entry_Fee'] (₹50) per entry
    #   - One entry per genre per photographer
    #   - Store entry in OpenContestEntry model (to be created)
    flash('Open Competition entry is coming soon. You will be notified when entries open.', 'info')
    return redirect(url_for('contests'))




# ---------------------------------------------------------------------------
# Razorpay subscription
# ---------------------------------------------------------------------------

@app.route('/subscribe/<track>', methods=['GET', 'POST'])
@login_required
def subscribe(track):
    if track not in ('camera', 'mobile'):
        return redirect(url_for('pricing'))

    razorpay_key = os.getenv('RAZORPAY_KEY_ID', '')
    prices = {
        'camera': {'monthly': 20000, 'annual': 200000},  # paise
        'mobile': {'monthly': 10000, 'annual': 100000},
    }
    plan   = request.args.get('plan', 'monthly')
    amount = prices[track][plan]

    if request.method == 'POST':
        payment_id = request.form.get('razorpay_payment_id', '')
        order_id   = request.form.get('razorpay_order_id', '')
        signature  = request.form.get('razorpay_signature', '')

        if not razorpay_key:
            flash('Payment system not configured. Contact support.', 'error')
            return redirect(url_for('pricing'))

        try:
            import razorpay, hmac, hashlib
            client = razorpay.Client(auth=(razorpay_key, os.getenv('RAZORPAY_KEY_SECRET', '')))
            params = {'razorpay_order_id': order_id,
                      'razorpay_payment_id': payment_id,
                      'razorpay_signature': signature}
            client.utility.verify_payment_signature(params)

            current_user.subscription_track = track
            current_user.subscription_plan  = plan
            current_user.subscribed_at       = datetime.utcnow()
            current_user.is_subscribed       = True
            db.session.commit()

            flash(f'🎉 Welcome to the {track.title()} Track! Your subscription is active.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Payment verification failed: {e}', 'error')
            return redirect(url_for('subscribe', track=track, plan=plan))

    order = None
    if razorpay_key:
        try:
            import razorpay
            client = razorpay.Client(auth=(razorpay_key, os.getenv('RAZORPAY_KEY_SECRET', '')))
            order = client.order.create({
                'amount': amount,
                'currency': 'INR',
                'payment_capture': 1,
            })
        except Exception as e:
            flash(f'Could not create payment order: {e}', 'error')

    return render_template('subscribe.html',
        track=track, plan=plan, amount=amount,
        order=order, razorpay_key=razorpay_key,
    )


@app.route('/subscription/cancel', methods=['POST'])
@login_required
def cancel_subscription():
    current_user.is_subscribed       = False
    current_user.subscription_track  = None
    current_user.subscription_plan   = None
    db.session.commit()
    flash('Your subscription has been cancelled. You can continue on the free plan.', 'info')
    return redirect(url_for('dashboard'))


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'Lens League Apex'}), 200


if __name__ == '__main__':
    app.run(debug=True)
