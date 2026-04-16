# ─────────────────────────────────────────────────────────────────────────────
# ADD 1: 413 error handler — add near the other @app.errorhandler blocks
# (next to the 404 and 500 handlers at the bottom of app.py)
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(413)
def file_too_large(e):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'error': True, 'message':
            '⚠️ File too large. Please resize your image to under 5 MB before uploading. '
            'Most phones have a "resize" or "send as smaller image" option when sharing.'
        }), 413
    flash(
        '⚠️ File too large. Please resize your image to under 5 MB before uploading. '
        'Most phones have a "resize" or "send as smaller image" option when sharing photos.',
        'error'
    )
    return redirect(url_for('upload'))


# ─────────────────────────────────────────────────────────────────────────────
# ADD 2: File size guard at the TOP of the upload POST handler in app.py
# Add this right after:
#     if not allowed_file(file.filename):
#         flash('File type not supported.', 'error')
#         return redirect(request.url)
#
# Insert:
# ─────────────────────────────────────────────────────────────────────────────

        # Check file size — read content-length header first (fast),
        # fall back to reading the stream (handles iOS where size may be 0 at select time)
        MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

        # Try header first
        content_length = request.content_length
        if content_length and content_length > MAX_UPLOAD_BYTES:
            msg = (
                f'Your image is too large ({content_length // (1024*1024):.0f} MB). '
                'Please resize to under 5 MB before uploading. '
                'On iPhone: use "Mail-sized" when AirDropping or sharing. '
                'On Android: use your gallery app\'s "resize before share" option.'
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': True, 'message': msg}), 413
            flash(msg, 'error')
            return redirect(url_for('upload'))
