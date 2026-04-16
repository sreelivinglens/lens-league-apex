# ─────────────────────────────────────────────────────────────────────────────
# APP.PY — TWO CHANGES ONLY
# Both are near the top of app.py. Find and replace exactly as shown.
# ─────────────────────────────────────────────────────────────────────────────


# ── CHANGE 1 ─────────────────────────────────────────────────────────────────
# Find this line (around line 20):
#
#   app.config['MAX_CONTENT_LENGTH']  = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))
#
# Replace with:
#
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 20971520))
#
# 20971520 = 20 MB
# Previously 52428800 = 50 MB (accepted silently — now explicit 20 MB cap)


# ── CHANGE 2 ─────────────────────────────────────────────────────────────────
# Find the existing @app.errorhandler(413) block.
# If it exists already (from upload_size_guard.py patch), replace it entirely.
# If it does NOT exist, add it near the other error handlers (404, 500) at the
# bottom of app.py.
#
# Full replacement block:

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


# ─────────────────────────────────────────────────────────────────────────────
# THAT IS ALL. No other changes to app.py.
# ─────────────────────────────────────────────────────────────────────────────
