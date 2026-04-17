# ─────────────────────────────────────────────────────────────────────────────
# REPLACE the existing @app.route('/') index route in app.py with this version.
#
# Changes:
#   - top_images limit raised to 6 (was 6 already, confirmed)
#   - Passes top_images to index.html for the Sprint 3 live feed strip
#   - No other changes to logic
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    try:
        stats = {
            'total_images': Image.query.filter_by(status='scored').count(),
            'total_members': User.query.filter(User.role != 'admin').count(),
            'avg_score': db.session.query(db.func.avg(Image.score))
                           .filter(Image.score != None).scalar() or 0,
        }
        # SPRINT 3: top_images passed to template for live feed strip
        # Ordered by most recently scored so the feed feels live, not static
        top_images = (Image.query
                      .filter(
                          Image.status == 'scored',
                          Image.score != None,
                          Image.is_public == True,
                          Image.is_flagged == False,
                      )
                      .order_by(Image.scored_at.desc())
                      .limit(6).all())
        example_image = (Image.query
                         .filter(Image.status == 'scored', Image.score != None, Image.is_public == True)
                         .order_by(db.func.random())
                         .first())
    except Exception:
        stats = {'total_images': 0, 'total_members': 0, 'avg_score': 0}
        top_images = []
        example_image = None

    return render_template(
        'index.html',
        stats=stats,
        top_images=top_images,
        example_image=example_image,
        now=datetime.utcnow()
    )
