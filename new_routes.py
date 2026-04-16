# ──────────────────────────────────────────────────────────────
# ROUTES TO ADD / REPLACE IN app.py
# Add these after your existing route definitions.
# Replace the old /contests route with the one below.
# ──────────────────────────────────────────────────────────────

import datetime

def is_open_contest_active():
    """Returns True during the Open Competition entry window (Sep–Nov)."""
    month = datetime.datetime.utcnow().month
    return 9 <= month <= 11


# ── Homepage ──────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── Contests (REPLACE old /contests route) ────────────────────
@app.route('/contests')
def contests():
    return render_template('contests.html', is_open_contest_active=is_open_contest_active)


# ── Body of Work info page (NEW) ──────────────────────────────
@app.route('/bow')
def bow_info():
    return render_template('bow.html')


# ── How It Works ──────────────────────────────────────────────
@app.route('/how-it-works')
def how_it_works():
    return render_template('how-it-works.html')


# ── Example Score ─────────────────────────────────────────────
@app.route('/example-score')
def example_score():
    example_image = (
        Image.query
        .filter(Image.status == 'scored', Image.score != None, Image.is_public == True)
        .order_by(db.func.random())
        .first()
    )
    return render_template('example-score.html', example_image=example_image)


# ── Live Stats ────────────────────────────────────────────────
@app.route('/stats')
def stats_page():
    from engine.scoring import compute_calibration_stats
    total_images  = Image.query.filter_by(status='scored').count()
    total_members = User.query.filter(User.role != 'admin').count()
    avg_score     = (
        db.session.query(db.func.avg(Image.score))
        .filter(Image.score != None)
        .scalar() or 0
    )
    stats = {
        'total_images':  total_images,
        'total_members': total_members,
        'avg_score':     round(float(avg_score), 2),
    }
    genre_stats = compute_calibration_stats(
        Image.query.filter_by(status='scored').all()
    )
    return render_template('stats.html', stats=stats, genre_stats=genre_stats)
