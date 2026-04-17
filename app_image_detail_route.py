# ─────────────────────────────────────────────────────────────────────────────
# REPLACE the existing /image/<int:image_id> route in app.py with this version.
# Only change: computes percentile stats and passes them to the template.
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/image/<int:image_id>')
@login_required
def image_detail(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)

    # ── SPRINT 2: Compute percentile stats for scored images ──────────────────
    percentile_data = {}
    if img.status == 'scored' and img.score and not img.is_flagged:
        try:
            from engine.scoring import compute_percentile
            percentile_data = compute_percentile(
                score=float(img.score),
                genre=img.genre,
            )
        except Exception as e:
            app.logger.warning(f'[percentile] {e}')

    return render_template(
        'image_detail.html',
        image=img,
        archetypes=ARCHETYPES,
        percentile=percentile_data,
    )
