# ─────────────────────────────────────────────────────────────────────────────
# In app.py — find the /upload route's final line:
#
#     return redirect(url_for('image_detail', image_id=img.id))
#
# It appears right after this block:
#
#     else:
#         flash('Image uploaded! Add scores below.', 'success')
#
#     return redirect(url_for('image_detail', image_id=img.id))
#
# Replace that final return with the two lines below:
# ─────────────────────────────────────────────────────────────────────────────

    else:
        flash('Image uploaded! Add scores below.', 'success')

    # Return JSON for XHR requests (mobile upload.html uses XHR)
    # Return redirect for normal form submissions
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'status': 'ok',
            'image_id': img.id,
            'score': img.score,
            'tier': img.tier,
            'redirect': url_for('image_detail', image_id=img.id)
        })
    return redirect(url_for('image_detail', image_id=img.id))
