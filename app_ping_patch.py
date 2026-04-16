# ─────────────────────────────────────────────────────────────────────────────
# ADD THIS ROUTE TO app.py
# Place it anywhere after the imports/setup — e.g. just before the @app.route('/')
# index route, or near the other API-style routes.
#
# This is a lightweight session-check endpoint.
# The upload page pings this BEFORE sending the image.
# If it gets 401, it shows the "Session Expired" modal immediately
# instead of letting a 6 MB upload complete only to fail silently.
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/ping')
@login_required
def api_ping():
    """Lightweight session check used by the upload page before sending the image."""
    return jsonify({'ok': True, 'user': current_user.username}), 200
