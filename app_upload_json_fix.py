# ─────────────────────────────────────────────────────────────────────────────
# In app.py — find the /upload route
# Search for this EXACT block (it appears once, near the end of the upload route):
# ─────────────────────────────────────────────────────────────────────────────

        else:
            flash('Image uploaded! Add scores below.', 'success')

        return redirect(url_for('image_detail', image_id=img.id))

    return render_template('upload.html', genres=GENRE_IDS, genre_choices=GENRE_CHOICES)


# ─────────────────────────────────────────────────────────────────────────────
# REPLACE WITH:
# ─────────────────────────────────────────────────────────────────────────────

        else:
            flash('Image uploaded! Add scores below.', 'success')

        # XHR requests (mobile + desktop upload.html) get JSON so the
        # client-side JS can redirect properly without following a 302.
        # Normal form submissions (no XHR header) get the standard redirect.
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'ok',
                'image_id': img.id,
                'score': img.score,
                'tier': img.tier,
                'redirect': url_for('image_detail', image_id=img.id)
            })
        return redirect(url_for('image_detail', image_id=img.id))

    return render_template('upload.html', genres=GENRE_IDS, genre_choices=GENRE_CHOICES)
