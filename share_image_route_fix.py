# ─────────────────────────────────────────────────────────────────────────────
# FIX: Replace the existing share_image route in app.py with this version.
#
# The original route never passed `show_score` to share.html, so numeric DDI
# scores were NEVER shown — even to the image owner.
#
# This fix computes show_score correctly:
#   - True  → logged-in owner (or admin)  → sees full score + module numbers
#   - False → logged-out visitor or non-owner logged-in user → tier only + bars
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/share/<int:image_id>')
def share_image(image_id):
    img = Image.query.get_or_404(image_id)
    if img.status != 'scored':
        abort(404)
    audit = img.get_audit()
    # Numeric DDI score + module numbers visible only to the owner (or admin)
    show_score = (
        current_user.is_authenticated and
        (current_user.id == img.user_id or current_user.role == 'admin')
    )
    return render_template('share.html', image=img, audit=audit, show_score=show_score)
