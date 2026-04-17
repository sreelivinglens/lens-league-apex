# ============================================================================
# APP.PY PATCHES FOR v27
# ============================================================================
#
# 1. UPDATE IMPORTS — add to the models import line:
#
#   from models import (db, User, Image, CalibrationLog, ContestEntry,
#                       OpenContestEntry, ImageReport,
#                       RatingAssignment, PeerRating,
#                       get_or_assign_next_image, submit_peer_rating)
#
# ============================================================================
#
# 2. ADD TO THE _migrations LIST in the startup block (inside app.py):
#
PEER_RATING_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_credits INTEGER DEFAULT 20",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_reset_date DATE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS lifetime_ratings_given INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_bias_flag BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS rating_bias_note TEXT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_score FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_rating_count INTEGER DEFAULT 0",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS blended_score FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_dod FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_disruption FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_dm FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_wonder FLOAT",
    "ALTER TABLE images ADD COLUMN IF NOT EXISTS peer_avg_aq FLOAT",
    """
    CREATE TABLE IF NOT EXISTS rating_assignments (
        id SERIAL PRIMARY KEY,
        rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
        assigned_at TIMESTAMP DEFAULT NOW(),
        started_at TIMESTAMP,
        submitted_at TIMESTAMP,
        time_spent_seconds INTEGER,
        dod FLOAT,
        disruption FLOAT,
        dm FLOAT,
        wonder FLOAT,
        aq FLOAT,
        peer_ll_score FLOAT,
        status VARCHAR(20) DEFAULT 'assigned',
        UNIQUE(rater_id, image_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS peer_ratings (
        id SERIAL PRIMARY KEY,
        rater_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
        genre VARCHAR(60) NOT NULL,
        dod FLOAT NOT NULL,
        disruption FLOAT NOT NULL,
        dm FLOAT NOT NULL,
        wonder FLOAT NOT NULL,
        aq FLOAT NOT NULL,
        peer_ll_score FLOAT NOT NULL,
        delta_from_ddi FLOAT,
        time_spent_seconds INTEGER,
        rated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(rater_id, image_id)
    )
    """,
]
#
# Add each item in PEER_RATING_MIGRATIONS to the existing _migrations list,
# OR run them in their own loop right after the existing _migrations loop:
#
# with app.app_context():
#     with db.engine.connect() as conn:
#         for sql in PEER_RATING_MIGRATIONS:
#             try:
#                 conn.execute(db.text(sql))
#             except Exception as _e:
#                 print(f'[migration v27] {_e}')
#         conn.commit()
#
# ============================================================================
#
# 3. ADD TO base.html NAV (both desktop and mobile menus),
#    AFTER the "Upload" link:
#
NAV_RATE_LINK_DESKTOP = """
      {% if current_user.is_authenticated and current_user.is_subscribed %}
      <a href="{{ url_for('rate') }}" class="{% if request.endpoint == 'rate' %}nav-active{% endif %}">Rate</a>
      {% endif %}
"""
#
# ============================================================================
#
# 4. ADD TO admin.html dashboard nav buttons (top right area):
#
ADMIN_NAV_RATINGS_BTN = """
    <a href="{{ url_for('admin_ratings') }}" class="btn"
       style="border-color:var(--green); color:var(--green); padding:10px 20px;">
      ★ Rating Audit
    </a>
"""
#
# ============================================================================
#
# 5. ADD TO image_detail.html — peer rating section below the score panel.
#    Insert after the percentile block, before the scoring form column.
#    (Only shown if image has peer ratings)
#
IMAGE_DETAIL_PEER_SECTION = """
  {% if image.peer_rating_count and image.peer_rating_count > 0 %}
  <div style="margin-top:16px; background:var(--surface-2); border:1px solid var(--border);
              border-radius:var(--radius-md); overflow:hidden;">
    <div style="padding:14px 20px; border-bottom:1px solid var(--border);
                display:flex; justify-content:space-between; align-items:baseline;">
      <div style="font-family:var(--font-mono); font-size:10px; font-weight:600;
                  letter-spacing:2px; text-transform:uppercase; color:var(--text-muted);">
        Peer Ratings
      </div>
      <div style="font-family:var(--font-mono); font-size:11px; color:var(--green);">
        ● {{ image.peer_rating_count }} rater{{ 's' if image.peer_rating_count != 1 }}
      </div>
    </div>
    <div style="padding:16px 20px;">
      {% if image.blended_score and image.peer_rating_count >= 5 %}
      <div style="margin-bottom:14px; padding:10px 14px;
                  background:rgba(76,175,115,0.08); border:1px solid rgba(76,175,115,0.3);
                  border-radius:var(--radius-sm);">
        <div style="font-family:var(--font-mono); font-size:10px; letter-spacing:1.5px;
                    text-transform:uppercase; color:var(--green); margin-bottom:4px;">
          Blended Score Active (DDI 80% + Peer 20%)
        </div>
        <div style="font-family:var(--font-mono); font-size:28px; font-weight:700; color:var(--green);">
          {{ image.blended_score }}
        </div>
      </div>
      {% endif %}
      {% for label, peer_val, ddi_val in [
        ('DoD',        image.peer_avg_dod,        image.dod_score),
        ('Disruption', image.peer_avg_disruption,  image.disruption_score),
        ('DM',         image.peer_avg_dm,          image.dm_score),
        ('Wonder',     image.peer_avg_wonder,      image.wonder_score),
        ('AQ',         image.peer_avg_aq,          image.aq_score),
      ] %}
      {% if peer_val %}
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
        <div style="font-family:var(--font-mono); font-size:11px; color:var(--text-secondary); width:80px; flex-shrink:0;">{{ label }}</div>
        <div style="flex:1; height:4px; background:var(--surface-3); border-radius:99px; overflow:hidden;">
          <div style="width:{{ [(peer_val/10*100)|int,100]|min }}%; height:100%;
                      background:var(--green); border-radius:99px; opacity:0.7;"></div>
        </div>
        <div style="font-family:var(--font-mono); font-size:12px; font-weight:600;
                    color:var(--green); width:28px; text-align:right;">{{ peer_val }}</div>
        {% if ddi_val %}
        {% set delta = ((peer_val - ddi_val)|round(1)) %}
        <div style="font-family:var(--font-mono); font-size:11px; width:40px; text-align:right;
                    color:{{ 'var(--green)' if delta > 0.3 else ('var(--red)' if delta < -0.3 else 'var(--text-muted)') }};">
          {{ '%+.1f'|format(delta) }}
        </div>
        {% endif %}
      </div>
      {% endif %}
      {% endfor %}
      {% if image.peer_avg_score %}
      <div style="margin-top:12px; padding-top:10px; border-top:1px solid var(--border);
                  font-family:var(--font-mono); font-size:12px; color:var(--text-muted);">
        Peer avg: <strong style="color:var(--green);">{{ image.peer_avg_score }}</strong>
        &nbsp;·&nbsp; DDI: <strong style="color:var(--gold);">{{ image.score }}</strong>
        {% if image.peer_avg_score and image.score %}
        &nbsp;·&nbsp; Delta: <strong style="color:{{ 'var(--green)' if (image.peer_avg_score - image.score) > 0.3 else ('var(--red)' if (image.peer_avg_score - image.score) < -0.3 else 'var(--text-muted)') }};">
          {{ '%+.2f'|format(image.peer_avg_score - image.score) }}
        </strong>
        {% endif %}
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
"""
#
# ============================================================================
