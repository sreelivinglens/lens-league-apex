# ── PATCH 1: app.py — add FAQ and Privacy routes ────────────────────────────
# Add these two routes alongside the existing /terms, /contest-rules etc.
# Place after the @app.route('/contest-rules') route:

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


# ── PATCH 2: templates/base.html — update footer ────────────────────────────
# Find the existing footer block:
#
#   &copy; 2026 Lens League Apex. All rights reserved.
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   APEX DDI ENGINE &nbsp;·&nbsp; Rated by Science. Not Opinion.
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/terms" ...>Terms &amp; Conditions</a>
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/contest-rules" ...>Contest Rules</a>
#
# REPLACE with:

#   &copy; 2026 Lens League Apex. All rights reserved.
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   APEX DDI ENGINE &nbsp;·&nbsp; Rated by Science. Not Opinion.
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/terms" ...>Terms &amp; Conditions</a>
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/privacy" ...>Privacy Policy</a>
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/faq" ...>FAQ</a>
#   &nbsp;&nbsp;|&nbsp;&nbsp;
#   <a href="/contest-rules" ...>Contest Rules</a>
#
# (Same inline style as existing links — copy the onmouseover/onmouseout pattern)


# ── FILES TO PUSH ─────────────────────────────────────────────────────────────
# templates/faq.html          — new
# templates/privacy.html      — new
# app.py                      — 2 new routes added
# templates/base.html         — footer updated (Privacy Policy + FAQ links)
