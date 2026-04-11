import os
import uuid
import json
from datetime import datetime, date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, jsonify, abort, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from models import db, User, Image, CalibrationLog
from engine.scoring import (calculate_score, get_tier, GENRE_WEIGHTS,
                              ARCHETYPES, compute_calibration_stats)
from engine.processor import ingest_image, allowed_file

load_dotenv()

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY']          = os.getenv('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///lensleague.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']       = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH']  = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))

# Fix for Railway PostgreSQL URL format
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

# ── Auto-initialise database on first run ─────────────────────────────────────
with app.app_context():
    try:
        db.create_all()
        if not User.query.filter_by(email='admin@lenslague.com').first():
            admin = User(
                email         = 'admin@lenslague.com',
                username      = 'admin',
                password_hash = generate_password_hash('changeme123'),
                full_name     = 'Admin',
                role          = 'admin',
            )
            db.session.add(admin)
            db.session.commit()
            print('Admin account created.')
        print('Database ready.')
    except Exception as e:
        print(f'DB init warning: {e}')

# ── Auth helpers ──────────────────────────────────────────────────────────────
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

# ── Public routes ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    try:
        stats = {
            'total_images': Image.query.filter_by(status='scored').count(),
            'total_members': User.query.filter_by(role='member').count(),
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
    return render_template('index.html', stats=stats, top_images=top_images)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        fullname = request.form.get('full_name', '').strip()

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'error')
            return redirect(url_for('register'))

        user = User(
            email=email, username=username,
            password_hash=generate_password_hash(password),
            full_name=fullname
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

# ── Member dashboard ──────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    page  = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()

    images_q = Image.query.filter_by(user_id=current_user.id)
    total_images = images_q.count()

    if query and total_images >= 20:
        images_q = images_q.filter(
            db.or_(
                Image.asset_name.ilike(f'%{query}%'),
                Image.genre.ilike(f'%{query}%'),
                Image.subject.ilike(f'%{query}%'),
                Image.location.ilike(f'%{query}%'),
            )
        )

    images = (images_q.order_by(Image.created_at.desc())
              .paginate(page=page, per_page=12, error_out=False))

    stats = {
        'total': total_images,
        'scored': Image.query.filter_by(user_id=current_user.id, status='scored').count(),
        'avg_score': db.session.query(db.func.avg(Image.score))
                       .filter(Image.user_id==current_user.id, Image.score!=None)
                       .scalar() or 0,
        'best_score': db.session.query(db.func.max(Image.score))
                        .filter(Image.user_id==current_user.id)
                        .scalar() or 0,
    }
    return render_template('dashboard.html',
                           images=images, stats=stats,
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

        uid       = str(uuid.uuid4())
        filename  = secure_filename(file.filename)
        raw_path  = os.path.join(app.config['UPLOAD_FOLDER'], 'raw', f"{uid}_{filename}")
        file.save(raw_path)

        try:
            thumb_path, w, h, fmt = ingest_image(raw_path, app.config['UPLOAD_FOLDER'])
        except Exception as e:
            flash(f'Image processing failed: {e}', 'error')
            if os.path.exists(raw_path):
                os.remove(raw_path)
            return redirect(request.url)

        if os.path.exists(raw_path):
            os.remove(raw_path)

        img = Image(
            user_id           = current_user.id,
            original_filename = filename,
            stored_filename   = os.path.basename(thumb_path),
            thumb_path        = thumb_path,
            file_size_kb      = int(os.path.getsize(thumb_path) / 1024),
            width             = w,
            height            = h,
            format            = fmt,
            asset_name        = request.form.get('asset_name', filename),
            genre             = request.form.get('genre', 'Wildlife'),
            subject           = request.form.get('subject', ''),
            location          = request.form.get('location', ''),
            conditions        = request.form.get('conditions', ''),
            photographer_name = request.form.get('photographer_name',
                                                  current_user.full_name or current_user.username),
            status            = 'pending',
        )
        db.session.add(img)
        db.session.commit()

        # Auto-score via Claude Vision if API key is set
        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if api_key:
            try:
                from engine.auto_score import auto_score, build_audit_data
                from engine.compositor import build_card
                result = auto_score(
                    image_path   = img.thumb_path,
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
                img.tier             = result.get('tier', 'Practitioner')
                img.archetype        = result.get('archetype', '')
                img.soul_bonus       = result.get('soul_bonus', False)
                img.status           = 'scored'
                img.scored_at        = datetime.utcnow()
                audit = build_audit_data(result, img)
                img.set_audit(audit)
                card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                              f"{secure_filename((img.photographer_name or 'unknown').replace(' ',''))}_"
                              f"{img.genre}_{img.score}.jpg")
                card_path  = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
                build_card(img.thumb_path, audit, card_path)
                img.card_path = card_path
                db.session.commit()
                flash(f'Auto-scored! LL-Score: {img.score} — {img.tier}', 'success')
            except Exception as e:
                db.session.commit()
                flash(f'Uploaded. Auto-scoring failed: {e}. Score manually below.', 'warning')
        else:
            flash('Image uploaded! Add scores below.', 'success')

        return redirect(url_for('image_detail', image_id=img.id))

    genres = list(GENRE_WEIGHTS.keys())
    return render_template('upload.html', genres=genres)


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
        dod        = float(request.form.get('dod', 0))
        disruption = float(request.form.get('disruption', 0))
        dm         = float(request.form.get('dm', 0))
        wonder     = float(request.form.get('wonder', 0))
        aq         = float(request.form.get('aq', 0))
        archetype  = request.form.get('archetype', 'Sovereign Momentum')
        byline_1   = request.form.get('byline_1', '')
        byline_2   = request.form.get('byline_2', '')
        iucn_tag   = request.form.get('iucn_tag', '')

        final_score, tier, soul_bonus, checks = calculate_score(
            img.genre, dod, disruption, dm, wonder, aq
        )

        img.dod_score        = dod
        img.disruption_score = disruption
        img.dm_score         = dm
        img.wonder_score     = wonder
        img.aq_score         = aq
        img.score            = final_score
        img.tier             = tier
        img.archetype        = archetype
        img.soul_bonus       = soul_bonus
        img.status           = 'scored'
        img.scored_at        = datetime.utcnow()

        audit = {
            'asset':       img.asset_name,
            'meta':        f"{img.genre}  ·  {img.format}  ·  {img.subject}  ·  {img.location}",
            'score':       str(final_score),
            'tier':        tier,
            'dec':         archetype,
            'credit':      img.photographer_name,
            'genre_tag':   f"{img.genre.upper()}  ·  {img.format}",
            'soul_bonus':  soul_bonus,
            'iucn_tag':    iucn_tag or None,
            'modules': [
                ('DoD',        dod),
                ('Disruption', disruption),
                ('DM',         dm),
                ('Wonder',     wonder),
                ('AQ',         aq),
            ],
            'rows': [
                ('Technical\nIntegrity',  request.form.get('row_technical', '')),
                ('Geometric\nHarmony',    request.form.get('row_geometric', '')),
                ('Decisive\nMoment',      request.form.get('row_dm', '')),
                ('Wonder\nFactor',        request.form.get('row_wonder', '')),
                ('AQ — Soul',             request.form.get('row_aq', '')),
            ],
            'byline_1':      byline_1,
            'byline_2_body': byline_2,
            'badges_g':      request.form.get('badges_g', '').splitlines(),
            'badges_w':      request.form.get('badges_w', '').splitlines(),
        }
        img.set_audit(audit)

        # Generate rating card JPG
        from engine.compositor import build_card
        today_str  = date.today().strftime("%Y%m%d")
        safe_name  = secure_filename((img.photographer_name or 'unknown').replace(' ',''))
        card_fname = f"LL_{today_str}_{safe_name}_{img.genre}_{final_score}.jpg"
        card_path  = os.path.join(app.config['UPLOAD_FOLDER'], 'cards', card_fname)
        build_card(img.thumb_path, audit, card_path)
        img.card_path = card_path

        db.session.commit()
        flash(f'Scored! LL-Score: {final_score} — {tier}', 'success')

    except Exception as e:
        flash(f'Scoring error: {e}', 'error')

    return redirect(url_for('image_detail', image_id=image_id))


@app.route('/image/<int:image_id>/download')
@login_required
def download_card(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    if not img.card_path or not os.path.exists(img.card_path):
        flash('Rating card not yet generated.', 'error')
        return redirect(url_for('image_detail', image_id=image_id))
    safe_name = secure_filename(f"LL_{img.score}_{img.tier}_{img.asset_name or 'card'}.jpg")
    return send_file(img.card_path, as_attachment=True, download_name=safe_name)


@app.route('/image/<int:image_id>/thumb')
@login_required
def serve_thumb(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    if not img.thumb_path or not os.path.exists(img.thumb_path):
        abort(404)
    return send_file(img.thumb_path, mimetype='image/jpeg')



# ── Bulk upload route ─────────────────────────────────────────────────────────
@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    results = []

    if request.method == 'POST':
        files        = request.files.getlist('images')
        genre        = request.form.get('genre', 'Wildlife')
        photographer = request.form.get('photographer_name',
                                        current_user.full_name or current_user.username)

        api_key = os.getenv('ANTHROPIC_API_KEY', '')

        for file in files:
            if not file or not file.filename:
                continue
            if not allowed_file(file.filename):
                results.append({'filename': file.filename, 'score': None,
                                 'tier': None, 'status': 'skipped'})
                continue

            result_row = {'filename': file.filename, 'score': None,
                          'tier': None, 'status': 'failed'}
            try:
                uid      = str(uuid.uuid4())
                filename = secure_filename(file.filename)
                raw_path = os.path.join(app.config['UPLOAD_FOLDER'], 'raw',
                                        f"{uid}_{filename}")
                file.save(raw_path)

                thumb_path, w, h, fmt = ingest_image(raw_path,
                                                     app.config['UPLOAD_FOLDER'])
                if os.path.exists(raw_path):
                    os.remove(raw_path)

                from models import Image as ImageModel
                img = ImageModel(
                    user_id           = current_user.id,
                    original_filename = filename,
                    stored_filename   = os.path.basename(thumb_path),
                    thumb_path        = thumb_path,
                    file_size_kb      = int(os.path.getsize(thumb_path) / 1024),
                    width             = w,
                    height            = h,
                    format            = fmt,
                    asset_name        = os.path.splitext(filename)[0],
                    genre             = genre,
                    photographer_name = photographer,
                    status            = 'pending',
                )
                db.session.add(img)
                db.session.flush()   # get img.id without full commit

                if api_key:
                    from engine.auto_score import auto_score, build_audit_data
                    from engine.compositor import build_card as _build_card

                    scored = auto_score(
                        image_path   = img.thumb_path,
                        genre        = genre,
                        title        = img.asset_name,
                        photographer = photographer,
                    )
                    img.dod_score        = float(scored.get('dod', 0))
                    img.disruption_score = float(scored.get('disruption', 0))
                    img.dm_score         = float(scored.get('dm', 0))
                    img.wonder_score     = float(scored.get('wonder', 0))
                    img.aq_score         = float(scored.get('aq', 0))
                    img.score            = float(scored.get('score', 0))
                    img.tier             = scored.get('tier', 'Practitioner')
                    img.archetype        = scored.get('archetype', '')
                    img.soul_bonus       = scored.get('soul_bonus', False)
                    img.status           = 'scored'
                    img.scored_at        = datetime.utcnow()

                    audit = build_audit_data(scored, img)
                    img.set_audit(audit)

                    card_fname = (f"LL_{date.today().strftime('%Y%m%d')}_"
                                  f"{secure_filename(photographer.replace(' ',''))}_"
                                  f"{genre}_{img.score}.jpg")
                    card_path  = os.path.join(app.config['UPLOAD_FOLDER'],
                                              'cards', card_fname)
                    _build_card(img.thumb_path, audit, card_path)
                    img.card_path = card_path

                    result_row['score']  = img.score
                    result_row['tier']   = img.tier
                    result_row['status'] = 'scored'
                else:
                    img.status           = 'pending'
                    result_row['status'] = 'uploaded'

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                result_row['status'] = f'error: {str(e)[:60]}'

            results.append(result_row)

    genres = list(GENRE_WEIGHTS.keys())
    return render_template('bulk_upload.html', genres=genres, results=results)

# ── Admin routes ──────────────────────────────────────────────────────────────
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_users  = User.query.count()
    total_images = Image.query.count()
    scored       = Image.query.filter_by(status='scored').count()
    pending      = Image.query.filter_by(status='pending').count()
    recent       = Image.query.order_by(Image.created_at.desc()).limit(20).all()
    cal_stats    = compute_calibration_stats(
                       Image.query.filter_by(status='scored').all()
                   )
    return render_template('admin.html',
                           total_users=total_users,
                           total_images=total_images,
                           scored=scored, pending=pending,
                           recent=recent, cal_stats=cal_stats)


@app.route('/admin/calibrate', methods=['POST'])
@login_required
@admin_required
def run_calibration():
    images = Image.query.filter_by(status='scored').all()
    stats  = compute_calibration_stats(images)
    for genre, s in stats.items():
        log = CalibrationLog(
            genre       = genre,
            image_count = s['count'],
            avg_score   = s['avg_score'],
            avg_dod     = s['avg_dod'],
            avg_dis     = s['avg_dis'],
            avg_dm      = s['avg_dm'],
            avg_wonder  = s['avg_wonder'],
            avg_aq      = s['avg_aq'],
        )
        db.session.add(log)
    db.session.commit()
    flash(f'Calibration logged for {len(stats)} genres.', 'success')
    return redirect(url_for('admin_dashboard'))


# ── Health check ──────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': 'Lens League Apex'}), 200


if __name__ == '__main__':
    app.run(debug=True)
