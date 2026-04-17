# ─────────────────────────────────────────────────────────────────────────────
# PERCENTILE NOT SHOWING — MOST LIKELY CAUSE:
# The image_detail route in app.py was NOT updated to pass percentile= to the template.
# The template block is silently skipped when percentile is undefined.
#
# In app.py find the image_detail route. It ends with:
#     return render_template('image_detail.html', image=img, archetypes=ARCHETYPES)
#
# REPLACE the entire route with the block below.
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/image/<int:image_id>')
@login_required
def image_detail(image_id):
    img = Image.query.get_or_404(image_id)
    if img.user_id != current_user.id and current_user.role != 'admin':
        abort(403)

    # Compute global percentile for scored, unflagged images
    percentile_data = {}
    if img.status == 'scored' and img.score and not getattr(img, 'is_flagged', False):
        try:
            from engine.scoring import compute_percentile
            percentile_data = compute_percentile(float(img.score), genre=img.genre)
        except Exception as e:
            app.logger.warning(f'[percentile] {e}')

    return render_template(
        'image_detail.html',
        image=img,
        archetypes=ARCHETYPES,
        percentile=percentile_data,
    )
