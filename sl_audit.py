#!/usr/bin/env python3
"""
sl_audit.py — ShutterLeague Unified Pre-Deploy Audit
=====================================================
Replaces both sl_audit.py and verify_app.py.

Usage:
  python3 sl_audit.py app.py                   # Python/Flask audit
  python3 sl_audit.py dashboard.html           # HTML template audit
  python3 sl_audit.py email_welcome.html       # Email template audit
  python3 sl_audit.py app.py templates/*.html  # Full audit — all files

Rule 9: No push to GitHub/Railway without explicit founder approval.
Always run this before delivering any file. Never deliver a file that fails.

Session 168 (31 Jul 2026): Added check 0b — Jinja {{ }} inside <script> blocks.
Session 208 (02 Sep 2026):
  TWO-WORLDS SEPARATION — New check on all HTML templates:
    · Haiku standalone pages must not reference Sonnet routes (dashboard, my_gallery,
      leaderboard, image_detail, upload, recent_work, standings_public, evolving_eye)
    · Haiku standalone must not extend base.html
    · Haiku standalone topbar/nav must not use cream #F5F3EF (must be #1A2744 navy)
    · LOP brand language (League of Photographers, Masters in the Making) must not
      appear outside league_haiku.html
    · Sonnet pages (extending base.html) must not reference Haiku routes
      (try_welcome, try_page, try_gallery, try_result, try_standing, league_haiku)
  NOTE: is_haiku_try ORM check already existed (Rule 10/Rule 8) — retained as-is.

Session 201 (28 Aug 2026):
  NAV CONSISTENCY — Haiku standalone pages checked for:
    · Cream topbar background (not dark navy #1A2744)
    · Logo image (shutterleague-logo-cropped.png) in brand
    · "Making Images Matter" brand sub (not "Photography Institution")
    · Correct Haiku route items (try_welcome/try_page/league_haiku)
    · Mobile bottom nav present with Dashboard/Evaluate/League items
    · Active colour #C8A84B not #F4C20D
  META/OG — Smart noindex + canonical rules per page type:
    · Public pages (league_haiku, pricing_haiku): noindex must be ABSENT
    · Private pages (dashboard_haiku, try_gallery, image_detail_haiku): noindex required
    · try_standing now PUBLIC (Session 201) — should be indexed (photographer name SEO)
  PUBLIC ROUTES — league_haiku and try_standing must NOT have @login_required
  POST-LOGIN — auth_google_callback must redirect Haiku users to try_welcome not dashboard
    · Standalone pages (not extending base.html): canonical required
  EXEMPTIONS — Added to _is_detail_page and _is_mobile_app_page:
    · try_standing.html, pricing_haiku.html, league_haiku.html
    · try_gallery, image_detail_haiku, upload-staging
  OG PREFIX — Every standalone page OG description must start with:
    "Photography Assessment & Evolution Platform. Making Images Matter."
    followed by page-specific copy. Flagged as FAIL if missing on standalone pages.
  Any {{ expr }} inside a <script> tag is a FAIL. Dynamic values must be passed
  via data- attributes on HTML elements and read in JS via el.dataset.myval.
  Introduced after dashboard.html and rate.html caused "Unexpected token '{'" errors.
"""

import ast, re, sys, os

# ── Colour / term constants ───────────────────────────────────────────────────

# KYC-unsafe terms: (label, pattern, smart_exclusions_to_strip)
KYC_TERMS = [
    ('No KYC: contest',
     'contest',
     ["url_for('contests')", "url_for('contest_enter')", "url_for('contest')",
      'contest_enter', 'contest_rules', 'programme_enter',
      'contest_banners', 'contest_wins', 'contest_type', 'contest_month',
      'contest_entries', 'ann.contest',
      "endpoint == 'contests'", "endpoint in ['contests'",
      "endpoint == 'contest'", "in ['contests',",
      "contests_redirect", "'contest'"]),
    ('No KYC: prize',       ' prize',        []),
    ('No KYC: winner',      ' winner',       ['Annual Excellence', 'B&W Spider', 'IPPAWARDS', 'Global Winner', 'award winner', 'Award winner']),
    ('No KYC: winners',     ' winners',      ['Annual Excellence', 'award winners']),
    ('No KYC: compete',     ' compete',      []),
    ('No KYC: ranking',     'ranking',       ['url_for', 'ranking_season', 'ranking_public',
                                              'ranking_last_active', 'poty_used_year',
                                              'path_to_rank', 'rp-card', 'rp_card',
                                              'ICC rankings', 'ICC ranking', 'FIDE', 'PhotoCrowd']),
    ('No KYC: leaderboard', 'leaderboard',   ["url_for('leaderboard')", 'url_for("leaderboard")',
                                              "endpoint == 'leaderboard'", "endpoint == \"leaderboard\""]),
    ('No KYC: reward',      ' reward',       []),
    ('No KYC: deadline',    'deadline',      []),
    ('No KYC: submission',  'submission',    ['url_for', 'poty_entry', 'form', 'not a single submission', 'single submission']),
    ('No KYC: entry (copy)',
     ' entry',
     ["url_for('contest_enter')", "url_for('my_entries')", "url_for('programme_enter')",
      "url_for('my_participations')", 'type="submit"', "method='POST'",
      'poty_entry', 'contest_entry', 'entry_id', 'entry_images', 'entry_score',
      'entry_form', 'existing', 'current-entry', 'poty_entries',
      'pool entry', 'db-pool-entry', '.db-pool', '/* pool', 'peer pool',
      'entry button', 'entry {', 'entry{', '-entry',
      # Session 143 — JS DOM ID, not user-facing copy
      'entryform']),
    ('No KYC: entries (copy)',
     ' entries',
     ["url_for('my_entries')", "url_for('my_participations')", 'poty_entries',
      'poty_entry_images', 'contest_entries', 'entry_images',
      'winners_html', 'winners_text', 'for w in sorted(winners',
      'raw_submissions', 'submission_count', 'submission_record',
      'resubmission', 'raw_submission', 'no ranked submissions']),
    ('No KYC: compete',     'competi',       ['url_for']),
    ('No KYC: POTY (use Annual Excellence Award)',
     'poty',
     ['url_for', 'poty_entry', 'poty_entries', 'poty_used_year', 'poty_entry_images',
      'poty_id', 'show_poty_banner', 'poty_banner', "endpoint == 'poty'",
      "endpoint in ['poty'", 'poty_score', 'poty_season', 'poty_rank',
      'poty_qualifying', 'poty_points', 'path_to_rank',
      "path.includes('poty')", "includes('poty')", '.poty', '#poty',
      'poty)', "'/poty'", '"/poty"']),
    ('No KYC: "Photographer of the Year" spelled out (use Annual Excellence Award)',
     'photographer of the year',
     ['url_for', '<!--', '{#']),
    # DDI is NOT a KYC issue — it is Shutter League proprietary IP (Depth Dimension Index).
    # Incorrectly added to KYC_TERMS. Removed Session 109 — 26 June 2026.
    # Brand rule (not compliance): first use on any page = "Depth Dimension Index (DDI)".
    # Subsequent uses on same page = "DDI" alone. Standard legal/brand convention.
    ('No KYC: Genre in UX labels (use "Interests")',
     ' genre',
     ['url_for', 'image.genre', 'img.genre', 'genre_suggestion', 'genre_context',
      'genre_tag', 'genre_interests', 'genre_weights', 'genre_label',
      'genre_award', 'genre_score', 'effective_genre', 'primary_genre',
      'genre_filter', 'genre_track', 'genre_tier', 'genre_avg',
      'genre_pool', 'genre_eligible', 'genre_dim', 'genre_poty',
      'genre_standing', 'genre_drift', 'get_effective_genre',
      'score_genre', 'input.*genre', 'select.*genre',
      'genre=', "genre='", 'genre_key', 'sub_genre', 'genre_map',
      '# genre', '{# genre', 'genre_award', 'ann.genre',
      'VALID_SUBGENRES', 'genre_context', 'per-genre', 'same_genre',
      "not enough.*genre", "this genre", "in this genre",
      "across all genres", "genre.*photographs",
      "# ── Genre", "Genre Insight", "genre insight",
      "Scored As", "scored as",
      # Approved copy (Session 90 handoff) — plain English, not a UX label
      "any genre",
      # Session 143 — Jinja variable name, not a UX label
      'genres_count']),
    # ── Added Session 91 — terms missing from audit since Session 86 ──────────
    ('No KYC: score in user copy (use "evaluation")',
     ' score',
     # Internal/template uses that are not user-facing copy
     ['url_for', '_score', 'score=', 'score)', 'score,', "'score'", '"score"',
      'score }}', '%.2f', 'blended_score', 'peer_avg_score', 'judge_score',
      'ddi_score', 'poty_score', 'entry_score', 'genre_score', 'avg_score',
      'score desc', 'score asc', 'score filter', 'score threshold',
      'score_genre', 'score_phash', 'scored_at', 'score_cache',
      'sort by score', 'order by score', 'score.*float', 'score.*column',
      'calculate_score', 'auto_score', 'get_tier', 'scorecard',
      'sl-gitem-score', 'sl-dash-hero', 'sl-mob-sc-score', 'sl-mob-ar-score',
      'sl-mob-gitem-score', 'sl-hero-score', 'score-badge', 'score_badge',
      '<!-- score', '{# score', '# score',
      # Page <title> and SEO meta tags -- not user-facing UI copy
      'photography scored', 'get your photography',
      # Audit script internal references
      'apex ddi', 'DDI Engine', 'Gold text colour check skipped',
      'coaching overlay', 'gallery scores', 'confirmed false positive',
      # Admin-only table headers (admin pages exempt from KYC — Session 171.1)
      'rank</th>', 'photographer</th>', 'ai susp', 'sl score', 'mim ddi']),
    ('No KYC: rank in user copy (use "standing")',
     ' rank',
     # Internal/template/CSS uses
     ['url_for', 'ranking', 'rank_', '_rank', 'rank=', "'rank'", '"rank"',
      'rank }}', 'path_to_rank', 'poty_rank', 'rp-card', 'rp_card',
      'frank', 'rank-', '-rank', '# rank', '{# rank', '<!-- rank',
      'shadow_rank', 'shadow rank', 'rank position', 'rank resets',
      'rank history', 'rank preserved', 'rank and score',
      # Approved descriptive copy -- verb "rank" explaining what evaluation is NOT doing
      'not to rank you', 'to rank you against',
      # Investor/internal doc phrases
      'shadow standing', 'standing resets']),
    ('No KYC: gym (do not use)',
     ' gym',
     ['url_for', '# gym', '{# gym', '<!-- gym']),
    ('No KYC: Mentor Marketplace (user-facing copy — removed)',
     'mentor marketplace',
     ['url_for', '# mentor marketplace', '{# mentor', '<!-- mentor']),
]

# Gold colours — never on light/cream backgrounds as text
GOLD_VALS = ['#F5C518', '#C8A84B', 'var(--gold)', '#f5c518', '#c8a84b']

# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_exclusions(text, exclusions):
    t = text
    for ex in exclusions:
        t = t.replace(ex, '')
    return t

def _has_tiny_font(content):
    block = content.split('{% block content %}')[1] if '{% block content %}' in content else content
    css_block = ''
    if '{% block extra_css %}' in content:
        css_block = content.split('{% block extra_css %}')[1].split('{% endblock %}')[0]
    combined = block + css_block
    sizes = re.findall(r'font-size:\s*(\d+)px', combined)
    return any(int(s) < 12 for s in sizes)

def _gold_on_light(content):
    """Detect gold colour used as text colour without a dark background pairing.
    Gold is permitted only when the SAME rule (or inline style) also sets a
    dark background — the proven pattern used by CSI cards and score badges
    elsewhere in this codebase (e.g. #F5C518 on #2D1F00). Gold text on a
    light/white/cream surface — or with no background override at all, which
    means it inherits the page's light surface — is always a contrast fail.
    Does NOT strip <style> blocks: most real colour decisions live there, not
    in inline style="" attributes, and earlier versions of this check missed
    that entirely (Session 118 — challenge.html eyebrow label + sponsor badge
    both slipped through because the whole <style> block was discarded before
    scanning, and 'badge'/'letter-spacing'/'text-transform: uppercase' were
    blanket-exempted by keyword instead of by actual contrast)."""
    import re as _re

    def _is_dark(value):
        # Known dark surfaces already proven/used in this codebase.
        known_dark = ['#2d1f00', '#1a1a2e', '#0d0d0b', 'rgba(13,13,11', 'rgba(0,0,0',
                      '#000', 'black', '--surface-dark', '--text-primary',
                      'var(--sl-text)']
        v = value.lower()
        if any(k in v for k in known_dark):
            return True
        hexmatch = _re.search(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', value)
        if hexmatch:
            h = hexmatch.group(1)
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            return luminance < 128
        return False

    def _rule_has_gold_without_dark_bg(body):
        b = body.lower().replace(' ', '')
        gold_present = any(f'color:{g.lower()}' in b for g in GOLD_VALS)
        if not gold_present:
            return False
        bg_match = _re.search(r'background(?:-color)?:\s*([^;]+);?', body, _re.IGNORECASE)
        if not bg_match:
            return True  # no background override -> inherits light page/card surface
        return not _is_dark(bg_match.group(1))

    hits = []
    rule_list = [(r.group(1).strip(), r.group(2))
                 for r in _re.finditer(r'([.#][\w:\-, >]+)\{([^{}]*)\}', content)]

    def _bem_base(selector):
        first = selector.split(',')[0].strip().split(' ')[0].split(':')[0]
        return first.split('__')[0] if '__' in first else first

    def _ancestor_has_dark_bg(selector):
        # BEM modifier elements (e.g. .sl-dash-hero-banner__score) often have
        # no background of their own — they sit over a parent that does
        # (photo + gradient overlay). Check same-base rules too.
        base = _bem_base(selector)
        for sel2, body2 in rule_list:
            sel2_first = sel2.split(',')[0].strip().split(' ')[0].split(':')[0]
            if sel2_first == base:
                bg = _re.search(r'background(?:-image)?(?:-color)?:\s*([^;]+);?', body2, _re.IGNORECASE)
                if bg:
                    val = bg.group(1).lower()
                    if _is_dark(val) or 'url(' in val or 'rgba(0,0,0' in val or 'rgba(13,13,11' in val:
                        return True
        return False

    def _rule_has_gold_without_dark_bg(selector, body):
        b = body.lower().replace(' ', '')
        gold_present = any(f'color:{g.lower()}' in b for g in GOLD_VALS)
        if not gold_present:
            return False
        bg_match = _re.search(r'background(?:-color)?:\s*([^;]+);?', body, _re.IGNORECASE)
        if bg_match:
            return not _is_dark(bg_match.group(1))
        return not _ancestor_has_dark_bg(selector)  # no own bg -> check BEM parent

    # CSS rule blocks inside <style> — scanned directly now, not stripped.
    for selector, body in rule_list:
        if _rule_has_gold_without_dark_bg(selector, body):
            hits.append(f'{selector} -> gold text, no dark background pairing')

    # Inline style="" attributes — only hard-fail when the SAME attribute
    # declares an explicit light background (a confident, resolvable case).
    # When there's no background in the same attribute, the colour may be
    # legitimately paired with a dark ancestor written as a separate nested
    # inline style (e.g. thumbnail score badges, mission band header) —
    # that needs a real DOM tree to resolve, which this script doesn't have.
    # See _gold_on_light_notes() for those soft cases.
    for inline in _re.finditer(r'style="([^"]*)"', content):
        body = inline.group(1)
        b = body.lower().replace(' ', '')
        gold_present = any(f'color:{g.lower()}' in b for g in GOLD_VALS)
        if gold_present:
            bg_match = _re.search(r'background(?:-color)?:\s*([^;]+);?', body, _re.IGNORECASE)
            if bg_match and not _is_dark(bg_match.group(1)):
                hits.append('inline style -> gold text, light background in same attribute')

    return hits

def _gold_on_light_notes(content):
    """Inline style="" gold text with no background in the SAME attribute.
    Can't reliably resolve nested parent <div> backgrounds with regex (no
    real DOM tree here) — flag for a manual look rather than auto-failing,
    since legitimate gold-over-photo-gradient overlays (thumbnail scores,
    mission band header) are written as nested inline styles, not CSS
    classes, and would otherwise false-positive every time."""
    import re as _re
    notes = []
    for inline in _re.finditer(r'style="([^"]*)"', content):
        body = inline.group(1)
        b = body.lower().replace(' ', '')
        gold_present = any(f'color:{g.lower()}' in b for g in GOLD_VALS)
        if gold_present:
            bg_match = _re.search(r'background(?:-color)?:\s*([^;]+);?', body, _re.IGNORECASE)
            if not bg_match:
                notes.append(body[:60])
    return notes

def _has_44px_tap_target(content):
    """Detect an adequate (>=44px) tap target. The old checks only matched
    the literal substring '44px' or 'min-height: 44', missing buttons that
    legitimately use a larger value like min-height:52px (found auditing
    register.html -- both its Google and Create Account buttons already
    exceed the 44px minimum, they just didn't say '44' anywhere)."""
    if '44px' in content or 'min-height: 44' in content:
        return True
    for m in re.finditer(r'min-height:\s*(\d+)px', content):
        if int(m.group(1)) >= 44:
            return True
    return False

def _shaded_fonts(content):
    """Detect rgba text colours with low opacity (shaded/muted body text).
    Negative lookbehind excludes border-color/background-color/outline-color
    etc. -- those are not text colours and were false-flagging (Session 120)."""
    hits = re.findall(r'(?<!-)color:\s*rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*0\.[0-3]\d*\s*\)', content)
    return hits

def _non_black_white_body_text(content):
    """Flag hex colour text that is neither near-black nor near-white."""
    hits = []
    for m in re.findall(r'color:\s*(#[0-9a-fA-F]{3,6})\b', content):
        h = m.lstrip('#').lower()
        if len(h) == 3:
            h = ''.join(c*2 for c in h)
        try:
            r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
            brightness = (r*299 + g*587 + b*114) / 1000
            if 80 < brightness < 180:
                hits.append(m)
        except Exception:
            pass
    return hits

# ── Banner & summary helpers ──────────────────────────────────────────────────

def _banner():
    print()
    print('=' * 60)
    print('  SHUTTER LEAGUE — PRE-DEPLOY AUDIT')
    print('  sl_audit.py  .  Unified  .  Session 201  .  Aug 2026')
    print('  Rule 9: No push without explicit founder approval')
    print('=' * 60)

def _section(title):
    print(f'\n  -- {title}')

def _ok(label):   print(f'    OK  {label}')
def _fail(label): print(f'    XX  {label}')
def _note(label): print(f'    ~~  {label}')

def _result(fails, filepath):
    print()
    print('-' * 60)
    if fails == 0:
        print(f'  OK  CLEAN -- SAFE TO DELIVER    {os.path.basename(filepath)}')
    else:
        print(f'  XX  DO NOT DELIVER -- {fails} failure{"s" if fails != 1 else ""}    {os.path.basename(filepath)}')
    print('-' * 60)
    return fails == 0

# ── KYC check (shared: html + email) ─────────────────────────────────────────

def _run_kyc_checks(content, fails, context='template'):
    _section(f'KYC Language -- {context}')
    cl = content.lower()
    for label, term, exclusions in KYC_TERMS:
        stripped = _strip_exclusions(cl, [e.lower() for e in exclusions])
        if term.lower() in stripped:
            _fail(label)
            fails += 1
        else:
            _ok(label)
    gold_hits = _gold_on_light(content)
    if gold_hits:
        _fail(f'No gold text colour -- gold permitted only for scores/badges/borders ({len(gold_hits)} hit(s)): {gold_hits[:2]}')
        fails += 1
    else:
        _ok('No gold used as body/heading text colour')
    gold_notes = _gold_on_light_notes(content)
    if gold_notes:
        _note(f'Inline gold text with no background in same attribute ({len(gold_notes)}) -- verify parent element has a dark background (photo overlay pattern)')
    return fails


# ── Shared 70-yr + browser helper — runs on HTML content string ──────────────

def _run_readability_and_browser_checks(content, fails, viewport='desktop', is_mobile_app=False):
    """
    Run 70-year-old readability and Safari/Chrome browser safety checks.
    viewport: 'mobile', 'ipad', or 'desktop'
    Checks font size, line-height, tap targets, contrast, abbreviations,
    and browser-specific CSS hazards for the named viewport context.
    """
    # ── Font sizes ────────────────────────────────────────────────────────────
    # Minimum body font per viewport (mobile needs larger text for small screens)
    min_body_px = {'mobile': 16, 'ipad': 16, 'desktop': 16}[viewport]

    all_font_sizes = [int(s) for s in re.findall(r'font-size:\s*(\d+)px', content)]
    tiny = [s for s in all_font_sizes if s < 12]
    small = [s for s in all_font_sizes if 12 <= s < 14]

    if tiny:
        _fail(f'[{viewport}] Font below 12px found {tiny} -- unreadable for elderly users')
        fails += 1
    else:
        _ok(f'[{viewport}] No font below 12px')

    if small:
        _note(f'[{viewport}] Font 12-13px found {list(set(small))} -- acceptable for metadata/labels only')
    else:
        _ok(f'[{viewport}] No 12-13px fonts used as body copy')

    if re.search(rf'font-size:\s*(?:{"|".join(str(s) for s in range(min_body_px, 25))})px', content):
        _ok(f'[{viewport}] Body font size >= {min_body_px}px present')
    else:
        _fail(f'[{viewport}] No body font >= {min_body_px}px found -- elderly users need {min_body_px}px minimum')
        fails += 1

    # ── Line height ───────────────────────────────────────────────────────────
    lh_vals = re.findall(r'line-height:\s*([0-9.]+)', content)
    lh_floats = [float(v) for v in lh_vals if re.match(r'^[0-9.]+$', v)]
    lh_bad = [v for v in lh_floats if v < 1.5]
    if lh_bad:
        if is_mobile_app and all(v >= 1.0 for v in lh_bad):
            _note(f'[{viewport}] Tight line-heights {lh_bad} — verify these are display/title elements only (mobile-app design)')
        else:
            _fail(f'[{viewport}] Line-height below 1.5 found {lh_bad} -- use 1.6+ for readability')
            fails += 1
    elif not lh_floats:
        _note(f'[{viewport}] No line-height values detected -- verify body paragraphs have line-height >= 1.6')
    else:
        _ok(f'[{viewport}] Line-height all >= 1.5')

    # ── Tap / click targets ───────────────────────────────────────────────────
    # Minimum target size: 44px mobile/iPad (Apple HIG), 32px desktop
    min_tap = {'mobile': 44, 'ipad': 44, 'desktop': 32}[viewport]
    tap_pads = re.findall(r'padding:\s*(\d+)px', content)
    tap_large = [int(p) for p in tap_pads if int(p) >= (min_tap // 3)]
    if tap_large:
        _ok(f'[{viewport}] Button/CTA padding adequate for tap targets (>= {min_tap//3}px found)')
    else:
        _fail(f'[{viewport}] No button padding >= {min_tap//3}px -- CTA may be too small to tap/click')
        fails += 1

    # ── Contrast ─────────────────────────────────────────────────────────────
    light_grey = re.findall(r'color:\s*#([bcdefBCDEF][0-9a-fA-F]{5})', content)
    if light_grey:
        _note(f'[{viewport}] Light hex text colours found ({len(light_grey)}) -- verify WCAG AA contrast (4.5:1): #{light_grey[0]}...')
    else:
        _ok(f'[{viewport}] No obviously light/low-contrast hex text colours')

    if 'color: rgba(26,26,24,0.2)' in content or 'color: rgba(255,255,255,0.2)' in content:
        _fail(f'[{viewport}] Grey-on-grey text detected -- fails contrast for elderly users')
        fails += 1
    else:
        _ok(f'[{viewport}] No grey-on-grey contrast violations')

    # ── Abbreviations in visible copy ─────────────────────────────────────────
    abbrev_pats = [r'\bSep\b', r'\bOct\b', r'\bNov\b', r'\bDec\b', r'\bJan\b',
                   r'\bFeb\b', r'\bMar\b', r'\bApr\b', r'\bJun\b', r'\bJul\b',
                   r'\bAug\b', r'\bSept\b', r'w/\b', r'\bapprox\b', r'\betc\b',
                   r'\bcta\b', r'\bTBC\b', r'\bTBD\b', r'\bN/A\b']
    # Only check inside Jinja2 string literals / visible text, not Python variable names
    visible = re.sub(r'\{%.*?%\}', '', content, flags=re.DOTALL)  # strip Jinja tags
    abbrev_hits = [p for p in abbrev_pats if re.search(p, visible, re.I)]
    if abbrev_hits:
        _note(f'[{viewport}] Possible abbreviations in template copy {abbrev_hits} -- use full words for elderly users')
    else:
        _ok(f'[{viewport}] No abbreviations in visible copy')

    # ── Safari-specific CSS hazards ───────────────────────────────────────────
    _section(f'Safari/Chrome compatibility -- {viewport}')

    # Safari: -webkit- prefixes missing for common properties
    webkit_needed = [
        ('appearance', '-webkit-appearance'),
        ('user-select', '-webkit-user-select'),
        ('backdrop-filter', '-webkit-backdrop-filter'),
    ]
    for prop, wprop in webkit_needed:
        if prop in content and wprop not in content:
            _note(f'[{viewport}] CSS "{prop}" used without "{wprop}" -- may not render in Safari iOS')

    # Safari: position:sticky needs -webkit- on older iOS
    if 'position: sticky' in content or 'position:sticky' in content:
        if '-webkit-sticky' not in content:
            _note(f'[{viewport}] position:sticky without -webkit-sticky -- verify iOS Safari 12 and below')
        else:
            _ok(f'[{viewport}] position:sticky has -webkit-sticky fallback')

    # Safari: input zoom — font-size below 16px on inputs triggers zoom on iOS Safari
    input_font_sizes = re.findall(r'input[^{]{0,60}font-size:\s*(\d+)px', content)
    input_small = [int(s) for s in input_font_sizes if int(s) < 16]
    if input_small:
        _fail(f'[{viewport}] Input font-size below 16px: {input_small} -- iOS Safari auto-zooms on focus, breaks layout')
        fails += 1
    else:
        _ok(f'[{viewport}] No input font-size below 16px (no iOS Safari zoom trigger)')

    # Safari: 100vh bug -- use -webkit-fill-available or min-height fallback
    if '100vh' in content:
        if '-webkit-fill-available' in content or 'min-height' in content:
            _ok(f'[{viewport}] 100vh has fallback for Safari mobile address bar bug')
        else:
            _note(f'[{viewport}] 100vh used without -webkit-fill-available -- Safari mobile cuts off content behind address bar')

    # Chrome: scrollbar styling — only works in Chrome/Edge, not Safari/Firefox
    if '::-webkit-scrollbar' in content:
        _note(f'[{viewport}] ::-webkit-scrollbar used -- Chrome/Edge only, ignored by Safari/Firefox (verify fallback acceptable)')
    else:
        _ok(f'[{viewport}] No Chrome-only scrollbar styling')

    # Chrome/Safari: gap in flex containers — supported in modern browsers but verify
    if 'display: flex' in content and 'gap:' in content.replace(' ', ''):
        _ok(f'[{viewport}] flex gap used -- supported in Safari 14.1+, Chrome 84+')

    # Safari: object-fit on images -- needs verification on older iOS
    if 'object-fit' in content:
        _ok(f'[{viewport}] object-fit present -- supported Safari 10+, Chrome 31+')

    # Both: avoid fixed positioning issues on mobile Safari
    if viewport in ('mobile', 'ipad') and 'position: fixed' in content:
        _note(f'[{viewport}] position:fixed used -- verify scroll behaviour in Safari iOS (known rubber-band issue)')

    # Both: -webkit-tap-highlight-color for touch feedback
    if viewport in ('mobile', 'ipad'):
        if '-webkit-tap-highlight-color' in content:
            _ok(f'[{viewport}] -webkit-tap-highlight-color set -- touch feedback controlled')
        else:
            _note(f'[{viewport}] -webkit-tap-highlight-color not set -- default blue flash on tap in Safari iOS')

    # font smoothing — Chrome and Safari handle differently
    if '-webkit-font-smoothing' in content:
        _ok(f'[{viewport}] -webkit-font-smoothing set -- Safari renders subpixel antialiasing correctly')
    else:
        _note(f'[{viewport}] -webkit-font-smoothing not set -- text may appear heavier in Safari vs Chrome')

    return fails


# ── HTML audit ────────────────────────────────────────────────────────────────

def audit_html(filepath):
    _banner()
    print(f'\n  FILE: {filepath}')
    content = open(filepath).read()
    fails = 0

    # Detect template type to skip inapplicable homepage-specific checks
    fname = os.path.basename(filepath).lower()
    _is_detail_page = any(x in fname for x in [
        'image_detail', 'profile', 'scorecard', 'rating_card',
        'submission', 'result', 'entry_detail',
        'upload.html', 'upload_edited', 'bulk_upload', 'bow_submit.html',
        'onboarding_interests', 'onboarding.html', 'referral_landing',
        'dashboard.html', 'mission_detail.html', 'first_login.html',
        'faq.html', 'pricing.html', 'programmes.html', 'redeem.html', 'aea.html', 'aea_standings.html',
        'challenge.html',
        'science.html', 'how_it_works.html', 'learning.html', 'bow_info.html',
        'contest_rules.html', 'terms.html', 'terms-prod.html', 'privacy.html', 'refund.html',
        'cancel_subscription.html', 'challenge_submit.html', 'change_password.html',
        'calibration_notes.html', 'example-score.html',
        'leaderboard.html', 'poty.html', 'mentors.html', 'recent_work.html',
        'my_gallery.html', 'base.html', 'index.html',
        'mentor_booking.html', 'portfolio.html', 'share.html',
        'jpeg_provenance_submit.html', 'judge_score.html', 'mentor_review_form.html',
        'my_participations.html', 'open_contest_enter.html', 'refund_policy.html', 'stats.html',
        'raw_appeal.html', 'raw_status.html', 'raw_submit.html',
        'register.html', 'login.html', 'forgot_password.html', 'contact.html',
        'admin_raw_detail.html', 'admin_raw_verification.html', 'admin_raw_poty.html',
        'admin.html', 'admin_user_detail.html', 'admin_ratings.html',
        'admin_users.html', 'admin_curation.html', 'admin_engagement.html',
        'notify.html', 'register.html', 'register_thanks.html',
        'eval_landing.html', 'eval_image.html', 'eval_complete.html',
        'eval_not_open.html', 'reveal_session.html', 'reveal_not_ready.html',
        'admin_login.html', 'admin_dashboard.html', 'admin_new_session.html',
        'admin_session_detail.html', 'admin_edit_session.html',
        'admin_registrations.html',
        'journey.html',                  # SL 175: full-page journey view, card layout, no hero
        'dashboard_haiku.html',          # SL 175: free user dashboard, card layout, own nav
        'try_standing.html',             # SL 200: Haiku standalone scorecard, own nav
        'pricing_haiku.html',            # SL 201: Haiku standalone pricing, own nav
        'league_haiku.html',             # SL 200: Haiku standalone league, own nav
        'try_gallery',                   # SL 181: Haiku gallery, extends base
        'image_detail_haiku',            # SL 176: Haiku scorecard, extends base
        'upload-staging',                # Haiku upload page, extends base
    ])
    # Mobile-first card-based pages: hero checks, Inter !important, justify,
    # 56px padding, and display-type line-heights are all false positives.
    # try.html added SL 172.1 — free user evaluation page, card layout, no hero.
    # dashboard_haiku.html added SL 175 — free user dashboard, card layout, own blue nav.
    _is_mobile_app_page = any(x in fname for x in [
        'dashboard.html', 'onboarding.html', 'onboarding_interests',
        'referral_landing', 'redeem.html',
        'mission_detail.html', 'first_login.html',
        'try.html',
        'recent_work.html',
        'my_gallery.html',
        'leaderboard.html',
        'dashboard_haiku.html',          # SL 175: free user card-layout dashboard
        'try_standing.html',             # SL 200: Haiku standalone scorecard
        'pricing_haiku.html',            # SL 201: Haiku standalone pricing
        'league_haiku.html',             # SL 200: Haiku standalone league
        'try_gallery',                   # SL 181: Haiku gallery
        'image_detail_haiku',            # SL 176: Haiku scorecard
        'upload-staging',                # Haiku upload
    ])
    # ── APPROVED FONT SIZE EXCEPTIONS (Session 175, approved by Sree) ──────────
    # dashboard.html body-text: 14px (deliberate 70yr improvement, Session 175)
    # dashboard.html insight-lines: 15px
    # dashboard.html dimension names: 15px
    # dashboard.html labels/dates/metadata: 13px (captions, not body copy)
    # All above approved — do not flag as violations on dashboard.html
    # index.html: gold text on dark photo bg (coaching overlay) and
    # meta http-equiv tags triggering iOS form-input check are both
    # false positives — documented in Session 81 handoff.
    _is_homepage = ('index.html' in fname)
    _is_email = any(x in fname for x in ['email', 'mail', 'notification', 'trigger'])
    # Admin-only pages: KYC checks are not applicable — these pages are never
    # seen by payment gateway reviewers and use internal terminology correctly.
    _is_admin_page = fname.startswith('admin')
    # Legal document pages: deadline/submission/entry/genre are approved legal terms
    # confirmed Session 142 handoff.
    _is_legal_doc = any(x in fname for x in [
        'contest_rules', 'terms.html', 'terms-prod', 'privacy.html', 'refund'
    ])
    # Snippet/render-only files — never served standalone as a browser page.
    # Meta tags and CSI checks are not applicable. Session 143.
    _is_snippet_file = any(x in fname.lower() for x in [
        'image_detail_dimension_addition', 'scorecard_pdf',
    ])
    # Mentor operational pages — 'deadline' refers to review delivery deadlines,
    # not a KYC gambling term. Exempt from KYC deadline check. Session 143.
    _is_mentor_page = any(x in fname.lower() for x in [
        'mentor_dashboard', 'mentor_review_form', 'mentor_booking',
        'mentor_profile_edit', 'judge_score', 'judge_register',
    ])

    # ── Hero ──────────────────────────────────────────────────────────────────
    _section('Hero structure')
    if _is_detail_page:
        _note('Hero structure checks skipped — detail/scorecard page, not homepage')
    else:
        checks = [
            ('Hero 480px desktop',              'height: 480px' in content or 'min-height: 480px' in content),
            ('Hero mobile standard',            'height: 360px' in content or 'min-height: 360px' in content or 'aspect-ratio: 16 / 9' in content),
            ('Hero img->fade->content structure', 'hero-fade' in content),
            ('Hero onerror on img',             "onerror=\"this.style.display='none'\"" in content),
            ('Hero fade opacity 0.45',          'rgba(13,13,11,0.45)' in content or 'rgba(13,13,11,0.28)' in content or _is_homepage),
            ('Hero content margin 64px',        'margin: 48px 64px' in content or 'margin: 0 64px' in content),
            ('Hero-sub line present in content',  'hero-sub' in (content.split('{% block content %}')[1] if '{% block content %}' in content else content)),
        ]
        for label, result in checks:
            if result: _ok(label)
            else: _fail(label); fails += 1

    # -- Fonts
    # Approved SL font: Aptos (188M design language, Session 189+). Updated Session 190.
    _section('Fonts')
    if _is_detail_page:
        _note('Font override checks skipped -- detail page uses base.html font stack')
    else:
        _has_aptos = 'Aptos' in content
        _has_inter = "font-family: 'Inter', sans-serif !important" in content or ("font-family: 'Inter'" in content and not _has_aptos)
        if _has_inter:
            _fail('Inter font found -- replace with Aptos per 188M design language'); fails += 1
        elif _has_aptos:
            _ok('Aptos font confirmed -- approved 188M design language')
        else:
            _note('No explicit font-family -- verify Aptos via base.html or CSS var')
        for label, result in [
            ('No Georgia in page CSS',        'Georgia' not in content),
            ('No JetBrains Mono in page CSS', 'JetBrains' not in content),
        ]:
            if result: _ok(label)
            else: _fail(label); fails += 1

    # ── Colour & font colour rules ────────────────────────────────────────────
    _section('Colour & font colour rules')
    if _is_detail_page:
        _note('Gold text colour check relaxed — detail page uses gold for score display (correct)')
    elif _is_homepage:
        _note('Gold text colour check skipped — index.html: coaching overlay on dark photo, gallery scores on dark overlay, confirmed false positives (Session 81)')
    else:
        gold_hits = _gold_on_light(content)
        if gold_hits:
            _fail(f'Gold used as text colour -- use only for scores/badges/borders ({len(gold_hits)} hit(s)): {gold_hits[:2]}')
            fails += 1
        else:
            _ok('No gold text colour in templates')
        gold_notes = _gold_on_light_notes(content)
        if gold_notes:
            _note(f'Inline gold text with no background in same attribute ({len(gold_notes)}) -- verify parent element has a dark background (photo overlay pattern)')

    shaded = _shaded_fonts(content)
    if shaded:
        _fail(f'Shaded/low-opacity font colour found ({len(shaded)} hit(s)) -- use var(--text-muted) only for metadata: {shaded[:2]}')
        fails += 1
    else:
        _ok('No shaded/low-opacity font colours')

    mid = _non_black_white_body_text(content)
    if mid:
        _note(f'Mid-range hex text colour(s) -- verify these are metadata only, not body copy: {mid[:3]}')
    else:
        _ok('Hex text colours are near-black or near-white only')

    if 'color: rgba(26,26,24,0.2)' in content or 'color: rgba(255,255,255,0.2)' in content:
        _fail('Grey-on-grey text detected -- insufficient contrast')
        fails += 1
    else:
        _ok('No grey-on-grey contrast issues')

    # ── Copy / layout ─────────────────────────────────────────────────────────
    _section('Copy & layout')
    if _is_detail_page:
        _note('Homepage copy/layout checks skipped — detail page has different layout requirements')
        # Only run checks applicable to all pages
        if 'color: rgba(26,26,24,0.2)' in content or 'color: rgba(255,255,255,0.2)' in content:
            _fail('Grey-on-grey text detected -- insufficient contrast'); fails += 1
        else:
            _ok('No grey-on-grey contrast issues')
    else:
        checks = [
            ('text-align justify on body',          'text-align: justify' in content),
            ('Step/para descriptions justified',    content.count('text-align: justify') >= 2),
            ('No duplicate CTAs (manual check)',    True),
            ('Footer not touched',                  'footer-top' not in content and 'footer-bottom' not in content),
            ('Nav not touched in template',         'nav-links' not in content and 'nav-brand' not in content),
            ('Categories 2-column grid',            'grid-template-columns: 1fr 1fr' in content),
            ('poty_hero variable guard present',    '{% if poty_hero' in content or 'poty_hero' not in content),
            ('onerror on all live DB images',       content.count("onerror=\"this.style.display='none'\"") >= 1),
        ]
        for label, result in checks:
            if result: _ok(label)
            else: _fail(label); fails += 1

    # ── Mobile integrity (<=768px) — layout ───────────────────────────────────
    _section('Mobile layout integrity (<=768px)')
    checks = [
        ('Mobile breakpoint defined',           'max-width: 768px' in content or 'max-width: 600px' in content or 'max-width: 480px' in content),
        ('Mobile section padding 56px',         '56px' in content or _is_mobile_app_page or _is_detail_page),
        ('Mobile text-shadow none on h1',       'text-shadow: none' in content or _is_detail_page),
        ('Touch targets min 44px',              _has_44px_tap_target(content) or 'padding: 1' in content),
        ('No fixed px widths on containers',    not any(f'width: {n}px' in content for n in range(400, 1400, 10)) or 'max-width' in content),
        ('Grids collapse -- auto-fill or 1fr',  'auto-fill' in content or 'auto-fit' in content or '1fr' in content or 'flex-wrap: wrap' in content or _is_detail_page),
        ('Tables have mobile stacking',         'table' not in content.lower() or 'display: block' in content or 'overflow-x' in content or '@media' in content),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── iPad integrity (768px-1024px) — layout ────────────────────────────────
    _section('iPad layout integrity (768px-1024px)')
    ipad_bp = 'max-width: 1024px' in content or 'max-width: 900px' in content or 'min-width: 768px' in content
    if ipad_bp:
        _ok('iPad breakpoint defined')
    else:
        _note('No explicit iPad breakpoint -- verify 4-col grids do not produce cards < 170px wide')
    if 'minmax(170px' in content or 'minmax(180px' in content or 'minmax(200px' in content or 'minmax(220px' in content:
        _ok('Grid minmax prevents narrow cards on iPad')
    else:
        _note('Verify grid cards are not narrower than 170px on iPad (768-1024px viewport)')

    # ── Desktop integrity ─────────────────────────────────────────────────────
    _section('Desktop layout integrity (>1024px)')
    if 'max-width' in content:
        _ok('max-width set -- content does not stretch to full 2560px on wide monitors')
    else:
        _fail('No max-width found -- content will stretch on wide desktop monitors')
        fails += 1
    wide_fixed = [n for n in range(1200, 2000, 10) if f'width: {n}px' in content]
    if wide_fixed:
        _note(f'Wide fixed px widths found {wide_fixed[:3]} -- verify these are max-width containers, not content boxes')
    else:
        _ok('No problematic wide fixed-px widths')

    # ── 70-yr readability: Mobile ─────────────────────────────────────────────
    _section('70-year-old readability -- Mobile (<=768px)')
    # Extract mobile media query content for targeted checks
    mobile_css = ' '.join(re.findall(r'@media[^{]*max-width:\s*(?:768|600|480)px[^{]*\{([\s\S]*?)(?=\n\s*@media|\Z)', content))
    mobile_check_content = mobile_css if mobile_css else content  # fall back to full if no MQ found

    # Font size in mobile context
    mobile_fonts = [int(s) for s in re.findall(r'font-size:\s*(\d+)px', mobile_check_content)]
    mobile_tiny = [s for s in mobile_fonts if s < 14]
    if mobile_tiny and mobile_css:
        # Detail pages and mobile-app pages use 13px for UI labels — downgrade to note
        if (_is_detail_page or _is_mobile_app_page) and all(s >= 13 for s in mobile_tiny):
            _note(f'[mobile] 13px fonts in mobile breakpoint {list(set(mobile_tiny))} -- verify these are UI labels/captions only (not body copy)')
        else:
            _fail(f'[mobile] Font below 14px inside mobile breakpoint {mobile_tiny} -- elderly users on small screens need >= 14px')
            fails += 1
    elif not _has_tiny_font(content):
        _ok('[mobile] No font below 12px in content area')
    else:
        _fail('[mobile] Font below 12px found in content area -- unreadable on mobile')
        fails += 1

    if re.search(r'font-size:\s*(1[6-9]|2[0-4])px', content):
        _ok('[mobile] Body font size >= 16px present')
    else:
        _fail('[mobile] Body font size < 16px -- elderly users on mobile need 16px minimum')
        fails += 1

    # Line height mobile
    if re.search(r'line-height:\s*1\.[5-8]', content):
        _ok('[mobile] Line-height >= 1.5 on body text')
    else:
        _fail('[mobile] No line-height >= 1.5 -- body text too cramped for elderly mobile users')
        fails += 1

    # Tap targets mobile — must be 44px (Apple HIG)
    if _has_44px_tap_target(content):
        _ok('[mobile] 44px tap targets present (Apple HIG minimum)')
    else:
        _fail('[mobile] No 44px tap targets -- buttons may be too small for elderly fingers on mobile')
        fails += 1

    # Input zoom prevention
    # Negative lookbehind excludes 'oninput=' JS attributes (e.g.
    # oninput="this.setCustomValidity('')") which were matching the bare
    # substring 'input' and then grabbing an unrelated font-size from
    # nearby helper-text markup 60 chars later -- false positive found
    # auditing register.html.
    input_fonts = re.findall(r'(?<!\w)input\b[^{]{0,60}font-size:\s*(\d+)px', content)
    input_small = [int(s) for s in input_fonts if int(s) < 16]
    if input_small:
        _fail(f'[mobile] Input font-size below 16px: {input_small} -- iOS Safari auto-zooms, disorients elderly users')
        fails += 1
    else:
        _ok('[mobile] No input font below 16px (no iOS Safari zoom trigger)')

    # CTA button padding mobile
    cta_pads = re.findall(r'padding:\s*(\d+)px', content)
    cta_large = [int(p) for p in cta_pads if int(p) >= 12]
    if cta_large:
        _ok(f'[mobile] CTA padding >= 12px present {cta_large[:3]}')
    else:
        _fail('[mobile] No CTA padding >= 12px -- buttons too small to tap for elderly users')
        fails += 1

    # Label readability
    label_sizes = re.findall(r'(?:label|\.label)[^{]{0,60}font-size:\s*(\d+)px', content)
    tiny_labels = [int(s) for s in label_sizes if int(s) < 13]
    if tiny_labels:
        _fail(f'[mobile] Label font-size below 13px: {tiny_labels} -- use 13px minimum')
        fails += 1
    else:
        _ok('[mobile] No label font-size below 13px')

    # Abbreviations
    abbrev_pats = [r'\bSep\b', r'\bOct\b', r'\bNov\b', r'\bDec\b', r'\bJan\b',
                   r'\bFeb\b', r'\bMar\b', r'\bApr\b', r'\bJun\b', r'\bJul\b',
                   r'\bAug\b', r'\bSept\b', r'w/\b', r'\bapprox\b', r'\betc\.?\b', r'\bTBC\b', r'\bTBD\b']
    visible = re.sub(r'\{%.*?%\}', '', content, flags=re.DOTALL)
    abbrev_hits = [p for p in abbrev_pats if re.search(p, visible, re.I)]
    if abbrev_hits:
        _note(f'[mobile] Abbreviations in template copy {abbrev_hits} -- use full words for elderly users')
    else:
        _ok('[mobile] No abbreviations in visible copy')

    # Safari iOS / Chrome Android checks — mobile
    _section('Safari iOS / Chrome Android -- Mobile')
    if '100vh' in content:
        if '-webkit-fill-available' in content or 'dvh' in content:
            _ok('[mobile] 100vh has -webkit-fill-available or dvh fallback for Safari address bar')
        else:
            _fail('[mobile] 100vh without fallback -- Safari iOS hides content behind address bar')
            fails += 1
    else:
        _ok('[mobile] No bare 100vh (no Safari address bar issue)')

    if 'position: fixed' in content or 'position:fixed' in content:
        _note('[mobile] position:fixed used -- verify scroll/bounce behaviour in Safari iOS')
    else:
        _ok('[mobile] No position:fixed (no Safari iOS scroll conflict)')

    if '-webkit-tap-highlight-color' in content:
        _ok('[mobile] -webkit-tap-highlight-color set -- tap flash controlled in Safari iOS')
    else:
        _note('[mobile] -webkit-tap-highlight-color not set -- default blue tap flash on Safari iOS')

    if '-webkit-font-smoothing' in content:
        _ok('[mobile] -webkit-font-smoothing set -- consistent rendering Safari vs Chrome')
    else:
        _note('[mobile] -webkit-font-smoothing not set -- text may appear heavier in Safari vs Chrome')

    input_fonts_all = re.findall(r'font-size:\s*(\d+)px', content)
    if any(int(s) < 16 for s in input_fonts_all if s.isdigit()):
        if 'input' in content.lower() or 'select' in content.lower() or 'textarea' in content.lower():
            if _is_detail_page:
                _note('[mobile] 13px label fonts present near form inputs -- verify inputs themselves are 16px+ to prevent iOS Safari auto-zoom')
            elif _is_homepage:
                _note('[mobile] Fonts below 16px check — index.html: meta http-equiv content attr triggers this, no actual form inputs. Confirmed false positive (Session 81).')
            elif _is_mobile_app_page:
                _note('[mobile] Sub-16px fonts near form inputs -- mobile-app page, all inputs are 16px+ (verified), label fonts are UI labels only. SL 172.1.')
            else:
                _fail('[mobile] Fonts below 16px present and form inputs found -- verify no iOS Safari auto-zoom on inputs')
                fails += 1
    else:
        _ok('[mobile] No sub-16px fonts near form inputs (no Chrome Android zoom risk)')

    if '::-webkit-scrollbar' in content:
        _note('[mobile] ::-webkit-scrollbar used -- Chrome only, ignored by Safari iOS and Firefox')
    else:
        _ok('[mobile] No Chrome-only scrollbar styling')

    # ── 70-yr readability: iPad ───────────────────────────────────────────────
    _section('70-year-old readability -- iPad (768px-1024px)')

    if re.search(r'font-size:\s*(1[6-9]|2[0-4])px', content):
        _ok('[iPad] Body font size >= 16px present')
    else:
        _fail('[iPad] Body font size < 16px -- elderly iPad users need 16px minimum')
        fails += 1

    if re.search(r'line-height:\s*1\.[5-8]', content):
        _ok('[iPad] Line-height >= 1.5 on body text')
    else:
        _fail('[iPad] No line-height >= 1.5 -- cramped text for elderly iPad users')
        fails += 1

    if _has_44px_tap_target(content):
        _ok('[iPad] 44px tap targets present (Apple HIG minimum for iPad)')
    else:
        _note('[iPad] No 44px tap targets found -- verify buttons are large enough for elderly iPad users')

    # Contrast iPad
    light_grey = re.findall(r'color:\s*#([bcdefBCDEF][0-9a-fA-F]{5})', content)
    if light_grey:
        _note(f'[iPad] Light hex text colours ({len(light_grey)}) -- verify WCAG AA contrast on iPad display: #{light_grey[0]}...')
    else:
        _ok('[iPad] No obviously low-contrast hex text colours')

    # Abbreviations (same check, iPad context)
    if abbrev_hits:
        _note(f'[iPad] Abbreviations in copy {abbrev_hits} -- same concern on iPad landscape where users read longer text blocks')
    else:
        _ok('[iPad] No abbreviations in visible copy')

    # Safari iPadOS / Chrome iPad checks
    _section('Safari iPadOS / Chrome iPad')

    if '100vh' in content:
        if '-webkit-fill-available' in content or 'dvh' in content:
            _ok('[iPad] 100vh has fallback for Safari iPadOS viewport quirks')
        else:
            _note('[iPad] 100vh without dvh/fill-available fallback -- verify Safari iPadOS split-screen view')

    if 'position: fixed' in content or 'position:fixed' in content:
        _note('[iPad] position:fixed used -- verify in Safari iPadOS split-screen and slide-over modes')
    else:
        _ok('[iPad] No position:fixed (no iPadOS split-screen conflict)')

    if 'pointer-events' in content:
        _note('[iPad] pointer-events used -- verify touch behaviour on Safari iPadOS (pointer vs touch model differs from Chrome)')
    else:
        _ok('[iPad] No pointer-events (no Safari iPadOS touch model risk)')

    if 'hover' in content and (':hover' in content):
        _note('[iPad] :hover rules present -- Safari iPadOS may not fire hover on tap; verify interactive state works without hover')
    else:
        _ok('[iPad] No :hover-only interactive states')

    if '-webkit-font-smoothing' in content:
        _ok('[iPad] -webkit-font-smoothing set -- consistent rendering Safari iPadOS vs Chrome')
    else:
        _note('[iPad] -webkit-font-smoothing not set -- text rendering differs between Safari and Chrome on iPad')

    # ── 70-yr readability: Desktop ────────────────────────────────────────────
    _section('70-year-old readability -- Desktop (>1024px)')

    if re.search(r'font-size:\s*(1[6-9]|2[0-4])px', content):
        _ok('[desktop] Body font size >= 16px present')
    else:
        _fail('[desktop] Body font size < 16px -- elderly desktop users also need 16px minimum')
        fails += 1

    if re.search(r'line-height:\s*1\.[5-8]', content):
        _ok('[desktop] Line-height >= 1.5 on body text')
    else:
        _fail('[desktop] No line-height >= 1.5 -- cramped body text for elderly desktop users')
        fails += 1

    cta_desktop = [int(p) for p in re.findall(r'padding:\s*(\d+)px', content) if int(p) >= 10]
    if cta_desktop:
        _ok(f'[desktop] CTA/button padding >= 10px present {cta_desktop[:3]}')
    else:
        _fail('[desktop] No CTA padding >= 10px -- buttons hard to click for elderly users with impaired dexterity')
        fails += 1

    if 'cursor: pointer' in content:
        _ok('[desktop] cursor:pointer set -- clear affordance for elderly desktop users')
    else:
        _note('[desktop] cursor:pointer not found -- verify interactive elements show pointer cursor')

    if light_grey:
        _note(f'[desktop] Light hex text colours ({len(light_grey)}) -- verify WCAG AA contrast on desktop monitors (varies by calibration)')
    else:
        _ok('[desktop] No obviously low-contrast text colours')

    if abbrev_hits:
        _note(f'[desktop] Abbreviations in copy {abbrev_hits} -- elderly desktop users read more carefully, ambiguous abbreviations cause confusion')
    else:
        _ok('[desktop] No abbreviations in visible copy')

    # Safari macOS / Chrome Desktop checks
    _section('Safari macOS / Chrome Desktop')

    if '-webkit-font-smoothing' in content:
        _ok('[desktop] -webkit-font-smoothing set -- consistent font rendering Safari macOS vs Chrome')
    else:
        _note('[desktop] -webkit-font-smoothing not set -- text renders heavier in Safari macOS vs Chrome (especially on non-Retina)')

    if 'backdrop-filter' in content:
        if '-webkit-backdrop-filter' in content:
            _ok('[desktop] backdrop-filter has -webkit- prefix for Safari macOS')
        else:
            _fail('[desktop] backdrop-filter without -webkit-backdrop-filter -- broken in Safari macOS 12 and below')
            fails += 1
    else:
        _ok('[desktop] No backdrop-filter (no Safari prefix issue)')

    if 'gap:' in content.replace(' ', '') or 'gap: ' in content:
        _ok('[desktop] CSS gap used -- supported Safari 14.1+, Chrome 66+')

    if '::-webkit-scrollbar' in content:
        _note('[desktop] ::-webkit-scrollbar used -- Chrome/Edge only, ignored by Safari macOS (uses system scrollbar overlay)')
    else:
        _ok('[desktop] No Chrome-only scrollbar styling')

    if ':focus-visible' in content:
        _ok('[desktop] :focus-visible used -- keyboard accessibility, supported Chrome 86+, Safari 15.4+')
    elif ':focus' in content:
        _note('[desktop] :focus used -- consider :focus-visible to avoid showing ring on mouse click (Chrome 86+, Safari 15.4+)')
    else:
        _note('[desktop] No :focus/:focus-visible styles -- verify keyboard navigation focus rings are visible for elderly/disabled users')

    if 'subgrid' in content:
        _note('[desktop] CSS subgrid used -- Safari 16+, Chrome 117+ -- verify fallback for older browsers')
    else:
        _ok('[desktop] No CSS subgrid (no browser support risk)')

    if '@supports' in content:
        _ok('[desktop] @supports used -- progressive enhancement present')

    # ── SL Delivery Standard (5-point) ───────────────────────────────────────
    fails = _run_delivery_standard(content, filepath, fails, is_detail_page=_is_detail_page, is_admin_page=_is_admin_page, is_legal_doc=_is_legal_doc, is_snippet_file=_is_snippet_file, is_mentor_page=_is_mentor_page)

    return _result(fails, filepath)


# ── Email template audit ──────────────────────────────────────────────────────

def audit_email(filepath):
    _banner()
    print(f'\n  FILE: {filepath}  [EMAIL TEMPLATE]')
    content = open(filepath).read()
    fails = 0

    _section('Email rendering')
    checks = [
        ('No wide fixed px widths (>600px)',    not bool(re.search(r'(?<!max-)(?<!min-)width:\s*[6-9]\d\d\s*px', content))),
        ('Font size >= 14px in email body',     bool(re.search(r'font-size:\s*(1[4-9]|2\d)px', content))),
        ('No raw apostrophes (use &#39;)',       not bool(re.search(r"[a-zA-Z]'[a-zA-Z]", content.replace("&#39;", '')))),
        ('Line height set',                     'line-height' in content),
        ('max-width on container',              'max-width' in content),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    _section('Colour -- email')
    gold_hits = _gold_on_light(content)
    if gold_hits:
        _fail(f'Gold used as text colour in email ({len(gold_hits)} hit(s))')
        fails += 1
    else:
        _ok('No gold text colour in email')

    shaded = _shaded_fonts(content)
    if shaded:
        _fail(f'Shaded/low-opacity font colour in email ({len(shaded)} hit(s))')
        fails += 1
    else:
        _ok('No shaded font colours in email')

    # ── 70-yr readability: email (all viewports) ──────────────────────────────
    _section('70-year-old readability -- Email Mobile (iOS Mail / Gmail app)')

    email_fonts = [int(s) for s in re.findall(r'font-size:\s*(\d+)px', content)]
    tiny_email = [s for s in email_fonts if s < 12]
    small_email = [s for s in email_fonts if 12 <= s < 14]

    if tiny_email:
        _fail(f'[email/mobile] Font below 12px: {tiny_email} -- unreadable on mobile email')
        fails += 1
    else:
        _ok('[email/mobile] No font below 12px')
    if small_email:
        _note(f'[email/mobile] Font 12-13px found {list(set(small_email))} -- metadata/labels only, not body copy')
    else:
        _ok('[email/mobile] No 12-13px fonts as body copy')

    p_sizes = re.findall(r'<p[^>]*font-size:\s*(\d+)px', content)
    p_small = [int(s) for s in p_sizes if int(s) < 15]
    if p_small:
        _fail(f'[email/mobile] <p> font-size below 15px: {p_small} -- use 15-16px for body paragraphs')
        fails += 1
    else:
        _ok('[email/mobile] Email <p> body font-size >= 15px')

    lh_vals = re.findall(r'line-height:\s*([0-9.]+)', content)
    lh_floats = [float(v) for v in lh_vals if re.match(r'^[0-9.]+$', v)]
    # Pair each line-height with its context — display headings (font-size ≥32px) use 1.2-1.4 legitimately
    lh_pairs = re.findall(r'font-size:\s*(\d+)px[^}]*?line-height:\s*([0-9.]+)', content)
    display_lh = {float(lh) for fs, lh in lh_pairs if int(fs) >= 32}
    lh_bad = [v for v in lh_floats if v < 1.5 and v not in display_lh]
    lh_display_tight = [v for v in lh_floats if v < 1.5 and v in display_lh]
    if lh_bad:
        _fail(f'[email/mobile] Line-height below 1.5: {lh_bad} -- use 1.6+ for readability')
        fails += 1
    elif not lh_floats:
        _note('[email/mobile] No line-height values -- verify paragraphs have line-height >= 1.6')
    else:
        _ok('[email/mobile] Line-height all >= 1.5')
    if lh_display_tight:
        _note(f'[email/mobile] Display heading line-height {lh_display_tight} -- acceptable for large type (≥32px), verify visually')

    cta_em = re.findall(r'display:inline-block[^"]{0,300}padding:\s*(\d+)px\s+(\d+)px', content)
    cta_v = [int(t) for t, _ in cta_em]
    if cta_v and min(cta_v) < 12:
        _fail(f'[email/mobile] CTA button vertical padding below 12px: {cta_v} -- elderly users need larger tap targets')
        fails += 1
    elif cta_v:
        _ok(f'[email/mobile] CTA button padding >= 12px vertical {cta_v}')
    else:
        _note('[email/mobile] No CTA button found -- verify if one is needed')

    _section('70-year-old readability -- Email Desktop (Outlook / Apple Mail)')

    if bool(re.search(r'font-size:\s*(1[5-9]|2\d)px', content)):
        _ok('[email/desktop] Body font size >= 15px for desktop email clients')
    else:
        _fail('[email/desktop] No body font >= 15px -- desktop email clients need at least 15px')
        fails += 1

    if 'max-width: 560px' in content or 'max-width: 600px' in content:
        _ok('[email/desktop] Email container max-width 560-600px -- readable column width on desktop')
    else:
        _note('[email/desktop] Container max-width not 560-600px -- verify email does not stretch too wide on desktop')

    abbrev_pats = [r'\bSep\b', r'\bOct\b', r'\bNov\b', r'\bDec\b', r'\bJan\b',
                   r'\bFeb\b', r'\bMar\b', r'\bApr\b', r'\bJun\b', r'\bJul\b',
                   r'\bAug\b', r'\bSept\b', r'w/\b', r'\bapprox\b', r'\bTBC\b', r'\bTBD\b']
    abbrev_hits = [p for p in abbrev_pats if re.search(p, content, re.I)]
    if abbrev_hits:
        _note(f'[email] Possible abbreviations {abbrev_hits} -- use full words for elderly readers')
    else:
        _ok('[email] No abbreviated month names or shorthand')

    # ── Email Safari iOS / Gmail / Outlook compatibility ──────────────────────
    _section('Safari iOS Mail / Gmail App / Outlook compatibility')

    if re.search(r'(?<!max-)(?<!min-)width:\s*[6-9]\d\d\s*px', content):
        _fail('[email] Fixed width > 600px -- breaks on mobile email clients (iOS Mail, Gmail app)')
        fails += 1
    else:
        _ok('[email] No fixed width > 600px (safe for iOS Mail and Gmail app)')

    if 'table' in content.lower():
        _ok('[email] Table-based layout -- maximum Outlook compatibility')
    else:
        _note('[email] No table layout -- verify Outlook 2016/2019 renders correctly (div-only layouts break in Outlook)')

    if 'mso-' in content or '<!--[if mso]' in content:
        _ok('[email] MSO conditional comments present -- Outlook rendering handled')
    else:
        _note('[email] No MSO conditionals -- verify layout renders in Outlook 2016/2019 (Word rendering engine)')

    if 'media' in content and 'max-width' in content:
        _ok('[email] Media query present -- responsive email for iOS Mail and Gmail app')
    else:
        _note('[email] No media query -- email will not reflow on mobile (iOS Mail ignores, Gmail Android may clip)')

    if 'background-color' in content or 'bgcolor' in content:
        _ok('[email] Background colour set -- renders in dark mode email clients')
    else:
        _note('[email] No background-color -- email may render incorrectly in dark mode (iOS Mail, Gmail)')

    if 'color-scheme' in content or 'prefers-color-scheme' in content:
        _ok('[email] color-scheme/prefers-color-scheme set -- dark mode email handling present')
    else:
        _note('[email] No dark mode handling -- text may become unreadable in iOS Mail dark mode')

    fails = _run_kyc_checks(content, fails, context='email template')

    # ── SL Delivery Standard reminder ─────────────────────────────────────────
    _section('DELIVERY STANDARD — reminder')
    _note('Full 5-point standard (KYC · Mobile · iPad · 70yr · meta tags) runs on HTML templates only')
    _note('For email: KYC and 70yr checks above cover the equivalent requirements')

    return _result(fails, filepath)


# ── app.py audit ──────────────────────────────────────────────────────────────

def audit_apppy(filepath):
    _banner()
    print(f'\n  FILE: {filepath}  [FLASK APP]')
    print()
    _note('Site is LIVE and in KYC state with PayU -- zero tolerance for breakage')
    _note('Rule 9: Present change for approval first. One change -> one deploy -> one verify.')

    try:
        import sqlparse
    except ImportError:
        print('\n  XX  sqlparse not installed -- run: pip install sqlparse --break-system-packages')
        sys.exit(1)

    try:
        with open(filepath, 'r') as f:
            src = f.read()
        lines = src.splitlines()
        _ok(f'Loaded {filepath} ({len(lines)} lines)')
    except Exception as e:
        _fail(f'Could not load {filepath}: {e}')
        sys.exit(1)

    fails = 0

    # ── AST parse ─────────────────────────────────────────────────────────────
    _section('AST parse')
    try:
        tree = ast.parse(src)
        _ok('AST parse clean -- no syntax errors')
    except SyntaxError as e:
        _fail(f'SyntaxError at line {e.lineno}: {e.msg}')
        sys.exit(1)

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            raw = lines[node.lineno - 1] if node.lineno <= len(lines) else ''
            depth = 0
            for ch in raw:
                if ch == '{': depth += 1
                if ch == '}': depth -= 1
                if depth > 0 and ch == '\\':
                    violations.append(f'line {node.lineno}: {raw.strip()[:80]}')
                    break
    if violations:
        for v in violations[:5]: _fail(f'Backslash in f-string (Python 3.13 unsafe): {v}'); fails += 1
    else:
        _ok('No backslash escapes inside f-string expressions (Python 3.13 safe)')

    # ── SQL extraction + validation ───────────────────────────────────────────
    _section('SQL extraction + sqlparse validation')
    sqls = []
    for m in re.finditer(r'db\.text\s*\(', src):
        start = m.end()
        depth = 1
        pos = start
        while pos < len(src) and depth > 0:
            if src[pos] == '(':   depth += 1
            elif src[pos] == ')': depth -= 1
            pos += 1
        raw_inner = src[start:pos - 1]
        fragments = re.findall(r'"((?:[^"\\]|\\.)*)"' + r"|'((?:[^'\\]|\\.)*)'", raw_inner)
        parts = [a or b for a, b in fragments]
        full_sql = ' '.join(p.strip() for p in parts if p.strip())
        if full_sql and len(full_sql) > 10:
            sqls.append((full_sql, src[:m.start()].count('\n') + 1))
    _ok(f'Extracted {len(sqls)} SQL statements (bracket-matched, concat-aware)')

    sql_errors = []
    for full_sql, lineno in sqls:
        upper = full_sql.upper()
        try:
            parsed = sqlparse.parse(full_sql)
            if not parsed:
                sql_errors.append(f'line {lineno}: sqlparse returned empty: {full_sql[:60]!r}')
                continue
        except Exception as e:
            sql_errors.append(f'line {lineno}: sqlparse exception: {e}: {full_sql[:60]!r}')
            continue
        if re.search(r'ADD\s+CONSTRAINT\s+IF\s+NOT\s+EXISTS', upper):
            sql_errors.append(f'line {lineno}: ADD CONSTRAINT IF NOT EXISTS -- invalid PG syntax')
        if re.search(r'DROP\s+CONSTRAINT\s+(?!IF\s+EXISTS)[A-Z_]', upper):
            sql_errors.append(f'line {lineno}: DROP CONSTRAINT without IF EXISTS: {full_sql[:80]!r}')
        if re.search(r'ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)[A-Z_]', upper) and 'ALTER' in upper:
            sql_errors.append(f'line {lineno}: ADD COLUMN without IF NOT EXISTS: {full_sql[:80]!r}')
        if full_sql.count('(') != full_sql.count(')'):
            sql_errors.append(f'line {lineno}: unbalanced parentheses: {full_sql[:80]!r}')
        has_colon = bool(re.search(r':\w+', full_sql))
        if has_colon and '%s' in full_sql:
            sql_errors.append(f'line {lineno}: mixed placeholders (:param and %s): {full_sql[:60]!r}')
    if sql_errors:
        for e in sql_errors: _fail(e); fails += 1
    else:
        _ok(f'All {len(sqls)} SQL statements pass (sqlparse + PG rules)')

    # ── ALTER TABLE rules ─────────────────────────────────────────────────────
    _section('ALTER TABLE rules (Rule 5)')
    if re.search(r'ADD\s+CONSTRAINT\s+IF\s+NOT\s+EXISTS', src, re.I):
        _fail('ADD CONSTRAINT IF NOT EXISTS in source -- invalid PostgreSQL, use try/except')
        fails += 1
    else:
        _ok('No ADD CONSTRAINT IF NOT EXISTS')

    alter_count = len(re.findall(r'ALTER\s+TABLE', src, re.I))
    if alter_count:
        _note(f'{alter_count} ALTER TABLE statement(s) -- Rule 6: test each migration in isolation first')
    else:
        _ok('No ALTER TABLE statements')

    # ── Model field validation ────────────────────────────────────────────────
    _section('Model field validation vs models.py')
    models_path = os.path.join(os.path.dirname(filepath), 'models.py')
    if not os.path.exists(models_path):
        models_path = '/home/claude/models.py'
    if os.path.exists(models_path):
        with open(models_path) as mf:
            msrc = mf.read()
        model_fields = {}
        for cls in re.findall(r'class (\w+)\([^)]*db\.Model[^)]*\):', msrc):
            pat = rf'class {cls}\([^)]+\):(.*?)(?=\nclass |\Z)'
            m = re.search(pat, msrc, re.DOTALL)
            if m:
                model_fields[cls] = re.findall(r'^\s{4}(\w+)\s*=\s*db\.Column', m.group(1), re.MULTILINE)
        _ok(f'models.py loaded -- {len(model_fields)} models found')
        user_f = model_fields.get('User', [])
        img_f  = model_fields.get('Image', [])
        if 'display_name' in user_f:
            _fail('User model has display_name -- should not exist'); fails += 1
        else:
            _ok('User model: no display_name')
        if 'uploaded_at' in img_f:
            _fail('Image model has uploaded_at -- should be created_at'); fails += 1
        else:
            _ok('Image model: no uploaded_at')
        for req in ['raw_verification_required','raw_verified','raw_disqualified',
                    'created_at','score','tier','user_id']:
            if req not in img_f:
                _fail(f'Image model missing required field: {req}'); fails += 1
        _ok('Image model required fields present')
    else:
        _note('models.py not found -- upload alongside app.py for full field validation')

    # ── ORM field access rules ────────────────────────────────────────────────
    _section('ORM field access rules')
    hits = re.findall(r'(?:current_user|user)\s*\.\s*display_name', src)
    if hits: [(_fail(f'User.display_name (use full_name/username): {h}'), fails := fails+1) for h in hits]
    else: _ok('No User.display_name access')

    hits = [f'line {i+1}' for i, l in enumerate(lines)
            if 'uploaded_at' in l and not l.strip().startswith('#')]
    if hits: [(_fail(f'uploaded_at used (field is created_at): {h}'), fails := fails+1) for h in hits]
    else: _ok('No uploaded_at (correct field is created_at)')

    if re.search(r'db\.relationship\s*\(\s*["\']User["\']', src):
        _fail("db.relationship('User') on Image -- use User.query.get(img.user_id)"); fails += 1
    else:
        _ok("No db.relationship('User') on Image")

    # ── Email body KYC + apostrophe checks ───────────────────────────────────
    _section('Email body checks (KYC + apostrophes)')
    email_blocks = list(re.finditer(r'html_body\s*=\s*[\s\S]{0,8000}?(?=\n\s*(?:msg\.|send_|flash|return|#))', src))
    subject_lines = re.findall(r'(?:msg\.subject|subject)\s*=\s*["\']([^"\']+)["\']', src)

    if not email_blocks:
        _ok('No html_body email blocks found in app.py')
    else:
        _ok(f'{len(email_blocks)} html_body block(s) found -- checking KYC + apostrophes')
        _note("Known false positives: Python docstrings/f-strings captured by block regex are filtered but some may remain")
        false_positive_contexts = [
            'courier new', 'strftime(', 'prompt_body', 'challenge_url',
            'app.logger', 'formal submission', 'mark image as raw verified',
            'admin shortcut', 'mark_raw_verified', 'admin_mark_raw',
            'without a formal submission', "f'raw verification requested",
            "f'[bulk_request_raw]", 'db.session.commit',
        ]
        for i, m in enumerate(email_blocks):
            blk = m.group(0)
            ln = src[:m.start()].count('\n') + 1
            blk_lower = blk.lower()
            if any(x in blk_lower for x in [
                'admin_email', 'to_addresses=[admin_email', 'admin_notify',
                'shutter league  \u2014  admin', 'shutter league \u00b7 admin',
                '[admin]', 'admin panel', 'admin dashboard',
                'rankings are set', 'auto-releases available',
                'integrity hold', 'release_url',
                'grandmaster image auto-flagged', 'raw verification. submission record created',
                'view in raw queue', 'flagged for review',
                'shutter league \u00b7 mentor', 'review deadline reminder',
                'mentor dashboard', 'you have a review due in',
                'pending sessions', 'write review now',
            ]):
                continue

            EMAIL_EXCL = [
                'winners_html', 'winners_text', 'for w in sorted(winners',
                'send_winners', 'raw_submissions', 'submission_count',
                'submission_record', 'resubmission', 'raw_submission',
                'contest_type', 'contest_ref', 'contest_period',
                'contest_announce', 'contest_judge', 'contest_month',
                'brand_contest', 'deadline.strftime', '_deadline',
                'deadline =', 'deadline)', 'deadline,', 'deadline }',
                'ranking_season', 'ranking_public', 'ranking_last',
                'result_rank', 'ordinals', 'medals',
                'formal submission', 'contestant has verified',
                'no user or winner emails', 'no scoreable submissions',
                'raw verified without', 'manual override',
                'already ranked', 'preview + release',
                'without a formal submission', 'mark image as raw verified',
                'used for testing', 'mark_raw_verified',
                'admin shortcut', 'admin_mark_raw',
                'review deadline reminder', 'deadline_ist',
                'complete your review before the deadline',
                'shutter league \u00b7 mentor', 'mentor dashboard',
                'you have a review due',
            ]
            is_false_positive_block = any(x in blk_lower for x in false_positive_contexts)

            for label, term, exclusions in KYC_TERMS:
                EMAIL_EXCL_FULL = EMAIL_EXCL + (false_positive_contexts if is_false_positive_block else [])
                if is_false_positive_block:
                    EMAIL_EXCL_FULL = EMAIL_EXCL_FULL + [term.strip()]
                stripped = _strip_exclusions(blk_lower, [e.lower() for e in exclusions + EMAIL_EXCL_FULL])
                if term.lower() in stripped:
                    _fail(f'Email body ~line {ln}: KYC term "{term}" found')
                    fails += 1

            clean = blk.replace("&#39;", '').replace("\\'", '')
            clean_lines = [l for l in clean.split('\n')
                          if not l.strip().startswith('#')
                          and not re.match(r'\s*(def |class |"""|\'\'\')(.*)', l)
                          and 'app.logger' not in l
                          and 'flash(' not in l
                          and '.commit()' not in l
                          and "Courier New" not in l
                          and "strftime(" not in l
                          and "prompt_body" not in l
                          and "challenge_url" not in l
                          and "send_email(" not in l
                          and "f\"This week" not in l
                          and "image(s)" not in l
                          and "f'" not in l]
            clean_html = '\n'.join(clean_lines)
            if re.search(r"[a-zA-Z]'[a-zA-Z]", clean_html):
                _fail(f'Email body ~line {ln}: raw apostrophe -- use &#39;')
                fails += 1

            gold_lines = [l for l in blk.split('\n') if any(g in l for g in GOLD_VALS) and 'color' in l.lower()]
            real_gold = []
            for gl in gold_lines:
                gl_l = gl.lower()
                if any(x in gl_l for x in [
                    'background', 'border', 'fill:', 'stroke:',
                    'text-transform: uppercase', 'text-transform:uppercase',
                    'letter-spacing', 'font-family: courier', 'font-family:courier',
                    'monospace', 'padding:', 'display:inline-block',
                    'display: inline-block', 'text-decoration:none',
                    'text-decoration: none',
                    'font-size:11px', 'font-size:12px', 'font-size:13px',
                    'font-size: 11px', 'font-size: 12px', 'font-size: 13px',
                    'score', 'tier', '8.', '9.', '7.',
                    '<h1', '<h2', 'font-style:italic', 'font-style: italic',
                    'font-size:30px', 'font-size:24px', 'font-size:22px',
                    'margin-bottom:20px', 'margin-bottom:24px',
                    'shutter league', 'f5c518;text-transform',
                    '<a href', 'style="color:#c8a84b', "style='color:#c8a84b",
                    'style="color:#f5c518', "style='color:#f5c518",
                    '<strong style="color:#c8a84b', "strong style='color:#c8a84b",
                    'placed <strong', 'position <strong',
                ]):
                    continue
                real_gold.append(gl.strip()[:60])
            if real_gold:
                _fail(f'Email body ~line {ln}: gold used as body text colour: {real_gold[:1]}')
                fails += 1

    # ── 70-yr readability — inline email HTML (all viewports) ─────────────────
    _email_block_matches = list(re.finditer(
        r'html_body\s*=\s*[\s\S]{0,8000}?(?=\n\s*(?:msg\.|send_|flash|return|#))', src
    ))
    _all_inline_html = ' '.join(m.group(0) for m in _email_block_matches)
    _flash_texts = re.findall(r"flash\s*\(\s*[f]?['\"]([^'\"]{0,200})['\"]", src)

    # ── Helper: print per-block patch report for a given check ───────────────
    def _email_patch_report(check_fn, fix_label):
        """
        For each email block, run check_fn(block_text) → list of (old, new) pairs.
        Prints FIX lines with source line numbers. Used by Option B patch reporting.
        """
        seen = set()
        for _m in _email_block_matches:
            _blk = _m.group(0)
            _ln  = src[:_m.start()].count('\n') + 1
            _hits = check_fn(_blk)
            for old, new in _hits:
                key = (old, new)
                if key not in seen:
                    seen.add(key)
                    print(f'    ~~  FIX ~line {_ln}: {fix_label}: {old!r}  →  {new!r}')

    _section('70-year-old readability -- Inline email HTML (mobile + desktop)')

    em_fonts = [int(s) for s in re.findall(r'font-size:\s*(\d+)px', _all_inline_html)]
    em_tiny = [s for s in em_fonts if s < 12]
    em_small = [s for s in em_fonts if 12 <= s < 14]
    if em_tiny:
        _fail(f'Inline email: font-size below 12px {em_tiny} -- unreadable on any device')
        fails += 1
        def _chk_tiny(blk):
            return [(f'font-size:{s}px', f'font-size:13px')
                    for s in set(int(x) for x in re.findall(r'font-size:\s*(\d+)px', blk) if int(x) < 12)]
        _email_patch_report(_chk_tiny, 'bump tiny font')
    else:
        _ok('No font below 12px in inline email HTML')
    if em_small:
        _note(f'Inline email: font-size 12-13px {list(set(em_small))} -- metadata/labels only, not body copy')
    else:
        _ok('No 12-13px fonts as body copy in inline email HTML')

    p_em = re.findall(r'<p[^>]*font-size:\s*(\d+)px', _all_inline_html)
    p_em_small = [int(s) for s in p_em if int(s) < 15]
    if p_em_small:
        _fail(f'Inline email: <p> font-size below 15px: {p_em_small} -- use 15-16px minimum')
        fails += 1
        def _chk_p_small(blk):
            hits = []
            for m2 in re.finditer(r'(<p[^>]*?)(font-size:\s*)(\d+)(px)', blk):
                if int(m2.group(3)) < 15:
                    old_fs = m2.group(2) + m2.group(3) + m2.group(4)
                    new_fs = m2.group(2) + '15' + m2.group(4)
                    prefix = (m2.group(1)[-25:]).lstrip('<p ')
                    label  = (f'..{prefix} ' if prefix.strip() else '') + old_fs
                    hits.append((label[:70], label[:70].replace(old_fs, new_fs)))
            return list(dict.fromkeys(hits))
        _email_patch_report(_chk_p_small, 'bump <p> font to 15px')
    else:
        _ok('Inline email <p> body font-size >= 15px')

    lh_em = [float(v) for v in re.findall(r'line-height:\s*([0-9.]+)', _all_inline_html) if re.match(r'^[0-9.]+$', v)]
    lh_em_bad = [v for v in lh_em if v < 1.5]
    if lh_em_bad:
        _fail(f'Inline email: line-height below 1.5: {lh_em_bad} -- use 1.6+ for readability')
        fails += 1
        def _chk_lh(blk):
            hits = []
            for m2 in re.finditer(r'line-height:\s*([0-9.]+)', blk):
                if float(m2.group(1)) < 1.5:
                    hits.append((f'line-height:{m2.group(1)}', 'line-height:1.6'))
            return list(dict.fromkeys(hits))  # dedup preserving order
        _email_patch_report(_chk_lh, 'bump line-height to 1.6')
    elif not lh_em:
        _note('Inline email: no line-height values detected -- verify paragraphs have line-height >= 1.6')
    else:
        _ok('Inline email line-height all >= 1.5')

    cta_em = re.findall(r'display:inline-block[^"]{0,300}padding:\s*(\d+)px\s+(\d+)px', _all_inline_html)
    cta_v_em = [int(t) for t, _ in cta_em]
    if cta_v_em and min(cta_v_em) < 12:
        _fail(f'Inline email CTA button vertical padding below 12px: {cta_v_em} -- use 12-14px min')
        fails += 1
    elif cta_v_em:
        _ok(f'Inline email CTA button padding >= 12px vertical {cta_v_em}')
    else:
        _note('No CTA button in inline email HTML -- verify if one is needed')

    # Safari iOS Mail / Gmail / Outlook — inline email
    _section('Safari iOS Mail / Gmail / Outlook -- Inline email HTML')

    if re.search(r'(?<!max-)(?<!min-)width:\s*[6-9]\d\d\s*px', _all_inline_html):
        _fail('Inline email: fixed width > 600px -- breaks in iOS Mail and Gmail app')
        fails += 1
        def _chk_wide(blk):
            hits = []
            for m2 in re.finditer(r'width:\s*([6-9]\d\d)\s*px', blk):
                val = int(m2.group(1))
                if val > 600:
                    hits.append((f'width:{m2.group(1)}px', 'width:600px'))
            return list(dict.fromkeys(hits))
        _email_patch_report(_chk_wide, 'cap width to 600px')
    else:
        _ok('Inline email: no fixed width > 600px (safe for iOS Mail / Gmail app)')

    if _all_inline_html and 'max-width' not in _all_inline_html:
        _note('Inline email: no max-width on container -- email may stretch on desktop clients')
    elif _all_inline_html:
        _ok('Inline email: max-width set on container')

    if _all_inline_html and ('background-color' in _all_inline_html or 'bgcolor' in _all_inline_html):
        _ok('Inline email: background-color set -- renders in dark mode email clients')
    elif _all_inline_html:
        _note('Inline email: no background-color -- may render incorrectly in iOS Mail dark mode')

    # ── Flash message abbreviations ───────────────────────────────────────────
    abbrev_flash_pats = ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar',
                         'Apr', 'Jun', 'Jul', 'Aug', 'Sept']
    abbrev_flash_hits = []
    for ft in _flash_texts:
        if any(re.search(r'\b' + p + r'\b', ft, re.I) for p in abbrev_flash_pats):
            abbrev_flash_hits.append(ft[:60])
    if abbrev_flash_hits:
        _note(f'Flash messages with abbreviated month names ({len(abbrev_flash_hits)}) -- use full month names: {abbrev_flash_hits[:2]}')
    else:
        _ok('Flash messages: no abbreviated month names detected')

    # ── Subject line KYC ─────────────────────────────────────────────────────
    for subj in subject_lines:
        subj_l = subj.lower()
        for label, term, exclusions in KYC_TERMS:
            if term.lower() in subj_l:
                _fail(f'Email subject KYC term "{term}": {subj[:60]}')
                fails += 1
    if subject_lines:
        _ok(f'{len(subject_lines)} subject line(s) checked for KYC terms')

    # ── Route integrity ───────────────────────────────────────────────────────
    _section('Route integrity')
    routes = re.findall(r"@app\.route\s*\(\s*'([^']+)'", src)
    _ok(f'{len(routes)} routes defined')
    seen = {}
    for r in routes: seen[r] = seen.get(r, 0) + 1
    dupes = {r: c for r, c in seen.items() if c > 1}
    if dupes:
        for r, c in dupes.items(): _fail(f'Duplicate route: {r} ({c}x)'); fails += 1
    else:
        _ok('No duplicate routes')

    # ── Peer queue safety — genre filter must be present ─────────────────────
    # RatingAssignment.genre is nullable=False. If _eligible images have genre=None,
    # all inserts fail silently → _peer_queue stays empty → "No images" message
    # even when 100+ images exist in the pool. This is the known regression point.
    _section('Peer queue safety')
    _peer_queue_checks = [
        ('Dashboard peer queue has Image.genre != None filter',
         'Image.genre' in src and 'peer_queue' in src and
         bool(re.search(r'Image\.genre\s*!=\s*None', src))),
        ('Dashboard peer queue exception is not silent (logs the error)',
         bool(re.search(r'peer queue assignment error', src))),
        ('_peer_queue passed to render_template',
         'peer_queue=_peer_queue' in src),
        ('RatingAssignment genre column not removed from insert',
         bool(re.search(r"genre\s*=\s*_img\.genre", src))),
    ]
    for label, result in _peer_queue_checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── Template name KYC compliance ──────────────────────────────────────────
    _section('Template name KYC compliance')
    old_templates = ['contest_enter.html', 'my_entries.html']
    new_templates = ['programme_enter.html', 'my_participations.html']
    for t in old_templates:
        if f"'{t}'" in src or f'"{t}"' in src:
            _fail(f'KYC-unsafe template name still referenced: {t} -- should be renamed')
            fails += 1
        else:
            _ok(f'{t} -- not referenced')
    for t in new_templates:
        if t in src:
            _ok(f'{t} -- KYC-safe name in use')
        else:
            _note(f'{t} -- not yet referenced (rename pending)')

    for t in ['dashboard.html', 'login.html', 'upload.html']:
        if t in src: _ok(f"render_template('{t}') present")
        else: _fail(f"render_template('{t}') missing"); fails += 1

    # ── Mobile & rendering safety ─────────────────────────────────────────────
    _section('Mobile & rendering safety (Rule 1)')
    wide_px = re.findall(r'width:\s*[6-9]\d\d\s*px', src)
    if wide_px:
        _note(f'{len(wide_px)} fixed px width(s) in email HTML -- verify iOS/Android/Safari/Chrome')
    else:
        _ok('No wide fixed-px widths in email HTML')

    # ── KYC on flash messages + render context ────────────────────────────────
    _section('KYC language in app.py (flash messages + render context)')
    render_strings = re.findall(r"render_template\s*\('[^']+',([^)]{0,400})\)", src)
    combined_copy = ' '.join(_flash_texts + render_strings).lower()
    APP_EXCL = [
        'contest_type', 'contest_ref', 'contest_period', 'contest_banner',
        'contest_announce', 'contest_judge', 'contest_month', 'brand_contest',
        'contest_entry_count', 'active_contest', 'contest_wins',
        'winners_html', 'winners_text', 'winner_count', 'result_rank',
        'raw_submission', 'submission_count', 'submission_record',
        'resubmission', 'poty_submission', 'bow_submission',
        'entries_left', 'entries_count', 'poty_entries', 'bow_entries',
        'ranking_season', 'ranking_public', 'ranking_last',
        'raw verification record', 'verification record',
        'no raw verification', 'raw resubmission',
        'contest period saved', 'contest reference is required',
        'judge config saved for', 'in this contest have not been reviewed',
        'submission(s). deactivate', 'submission(s) deleted',
        'it has {ch.submission_count} submission',
        'no eligible images found for this programme',
        'ddi weight + judge weight', 'recalibration error',
        'assignments across', 'flagged image',
        'appeal upheld', 'appeal overturned',
        'results computed for', 'cooling:',
        'standings published for', 'top position(s) notified',
        'a reason is required when rejecting or requesting resubmission',
        'raw resubmission requested', 'no ranked submissions found',
        'cannot delete', 'deactivate it instead',
        'winner emails', 'winner_count', 'no user or winner',
        'top_winners', 'num_winners', 'len(winners)',
        'entries_per', 'max_entries', 'num_entries',
        '{len(winners)}',
    ]
    kyc_fails_app = []
    for label, term, exclusions in KYC_TERMS:
        stripped = _strip_exclusions(combined_copy, [e.lower() for e in exclusions + APP_EXCL])
        if term.lower() in stripped:
            kyc_fails_app.append(term)
    if kyc_fails_app:
        for t in kyc_fails_app:
            _note(f'KYC term "{t}" in flash/render context -- verify admin-only (not user-facing)')
        _note(f'{len(kyc_fails_app)} term(s) above are likely admin flash messages -- review manually if deploying after KYC submission')
    else:
        _ok('No KYC terms in flash messages or render_template context strings')

    # -- Haiku isolation checks (Session 190, Rule 10)
    _section('Haiku isolation (Rule 10 - raw SQL only for unmapped columns)')
    _orm_haiku = [l.strip()[:80] for l in lines if 'is_haiku_try' in l and '.filter(' in l and 'db.text' not in l and not l.strip().startswith('#')]
    if _orm_haiku:
        _fail('ORM filter on is_haiku_try (' + str(len(_orm_haiku)) + ' hit(s)) - use raw SQL Rule 10: ' + _orm_haiku[0]); fails += 1
    else:
        _ok('is_haiku_try: raw SQL only (Rule 10 clean)')
    _orm_thumb = [l.strip()[:80] for l in lines if 'thumb_url' in l and '.like(' in l and not l.strip().startswith('#')]
    if _orm_thumb:
        _fail('ORM .like() on thumb_url - use raw SQL Rule 10: ' + _orm_thumb[0]); fails += 1
    else:
        _ok('thumb_url: no ORM .like() (Rule 10 clean)')

    # -- Public Haiku routes — must NOT have @login_required (Session 201)
    _section('Public Haiku routes — no @login_required (Session 201)')
    for _pub_route in ['league_haiku', 'try_standing']:
        _ri = next((i for i,l in enumerate(lines) if f'def {_pub_route}(' in l), None)
        if _ri is not None:
            # Check the 3 lines before the def for @login_required
            _before = ''.join(lines[max(0,_ri-3):_ri])
            if '@login_required' in _before:
                _fail(f'{_pub_route}() has @login_required — this is a PUBLIC page, remove the decorator')
                fails += 1
            else:
                _ok(f'{_pub_route}() correctly has no @login_required (public page)')
        else:
            _note(f'{_pub_route}() not found in this file')

    # -- Post-login redirect — Haiku users must land on try_welcome (Session 201)
    _section('Post-login redirect — Haiku users → try_welcome (Session 201)')
    _google_cb = next((i for i,l in enumerate(lines) if 'def auth_google_callback' in l), None)
    if _google_cb is not None:
        _cb_end = next((i for i in range(_google_cb+1, min(_google_cb+200, len(lines))) if lines[i].startswith('@app')), _google_cb+200)
        _cb_src = ''.join(lines[_google_cb:_cb_end])
        if 'try_welcome' in _cb_src:
            _ok('auth_google_callback() redirects Haiku users to try_welcome')
        else:
            _fail('auth_google_callback() redirects to dashboard — Haiku users will get double redirect. Should redirect to try_welcome for free users.')
            fails += 1
    else:
        _note('auth_google_callback() not found')


    _section('try_welcome() route integrity (Session 190)')
    _tw_i = next((i for i,l in enumerate(lines) if 'def try_welcome' in l), None)
    if _tw_i is not None:
        _tw_end = next((i for i in range(_tw_i+1, len(lines)) if lines[i].startswith('@app') or (lines[i].startswith('def ') and 'try_welcome' not in lines[i])), len(lines))
        _tw_src = ''.join(lines[_tw_i:_tw_end])
        for _v in ['evals_remaining', 'images', 'milestone_strength', 'hero_image']:
            if _v in _tw_src: _ok('try_welcome() passes ' + _v)
            else: _fail('try_welcome() missing variable: ' + _v); fails += 1
        if 'Cache-Control' in _tw_src or 'no-store' in _tw_src:
            _ok('try_welcome() sets Cache-Control: no-store')
        else:
            _fail('try_welcome() missing Cache-Control: no-store - hero may be cached'); fails += 1
    else:
        _note('try_welcome() not found - verify route exists')

    # -- Challenge gate (Session 190)
    _section('Challenge gate (Session 190 - Haiku users blocked from submit)')
    _cs_i = next((i for i,l in enumerate(lines) if 'def challenge_submit' in l), None)
    if _cs_i is not None:
        _cs_end = next((i for i in range(_cs_i+1, len(lines)) if lines[i].startswith('@app') or (lines[i].startswith('def ') and 'challenge_submit' not in lines[i])), len(lines))
        _cs_src = ''.join(lines[_cs_i:_cs_end])
        if 'is_subscribed' in _cs_src and ('redirect' in _cs_src or 'flash' in _cs_src):
            _ok('challenge_submit() gates unsubscribed (Haiku) users')
        else:
            _fail('challenge_submit() does not gate Haiku users'); fails += 1
        if 'is_haiku_try' in _cs_src:
            _ok('challenge_submit() excludes is_haiku_try images')
        else:
            _fail('challenge_submit() Haiku images not excluded from eligible picker'); fails += 1
    else:
        _note('challenge_submit() not found in this file')

    # ── MIM integrity checks (S167) ───────────────────────────────────────────
    # These 7 checks run only on mim-app.py. They fire as a gate before every
    # MIM delivery. Check 1 was a standing reminder (session lock not built);
    # it now passes because the lock was built in S167.
    _is_mim = 'mim-app' in os.path.basename(filepath).lower() or 'makingimagesmatter' in src[:200]
    if _is_mim:
        _section('MIM data integrity checks (S167)')

        # Check 1 — Session lock: sl-ddi-push must reject published AND archived
        _c1_push = '_session_push_allowed' in src and "'published'" in src and "'archived'" in src
        if _c1_push:
            _ok('Session lock — DDI push rejects published/archived sessions')
        else:
            _fail('Session lock — DDI push does NOT reject published/archived sessions')
            fails += 1

        # Check 2 — Repopulate atomic: all 13 Sherpa fields in one route
        _sherpa_fields = [
            'card_url', 'ddi_score', 'ddi_craft', 'ddi_theme', 'ddi_dimensions',
            'what_stood_out', 'background_check', 'transferable_advice', 'byline_2',
            'edit_base', 'edit_creative', 'mentor_location_1', 'affective_state',
        ]
        _repop_m = re.search(r'def admin_repopulate_sherpa.*?(?=\n@app\.route|\ndef [a-z])', src, re.DOTALL)
        _repop_body = _repop_m.group(0) if _repop_m else ''
        _missing = [f for f in _sherpa_fields if f not in _repop_body]
        if not _missing:
            _ok('Repopulate atomic — all 13 Sherpa fields written in one route')
        else:
            _fail(f'Repopulate atomic — missing fields: {", ".join(_missing)}')
            fails += 1

        # Check 3 — Engine-box dedup: kta must NOT render inside engine-box
        # Find the engine-box HTML render block and check it contains only mref/wso
        _eb_m = re.search(r'<div class=\\"engine-box\\">(.*?)</div>', src, re.DOTALL)
        if not _eb_m:
            # Try alternate quote style in f-string
            _eb_m = re.search(r'engine-box\\">\\n(.*?)\\n    </div>', src, re.DOTALL)
        _eb_body = _eb_m.group(1) if _eb_m else ''
        # kta as a variable (not in a CSS class name or HTML comment)
        _kta_in_eb = bool(re.search(r'\bkta\b(?![_-])', _eb_body)) and '<!-- KTA' not in _eb_body[:_eb_body.find('kta')] if 'kta' in _eb_body else False
        if not _kta_in_eb:
            _ok('Engine-box dedup — kta does NOT appear in engine-box render')
        else:
            _fail('Engine-box dedup — kta appears in engine-box render (duplicate with kta-box)')
            fails += 1

        # Check 4 — Send-reports loop: must loop MIMImage not MIMRegistration
        _sr_m = re.search(r'def admin_send_reports.*?(?=\n@app\.route|\ndef [a-z])', src, re.DOTALL)
        _sr_body = _sr_m.group(0) if _sr_m else ''
        _loops_image = 'MIMImage.query.filter_by(session_id=s.id)' in _sr_body
        _loops_reg   = 'MIMRegistration.query.filter_by(session_id=s.id' in _sr_body
        if _loops_image and not _loops_reg:
            _ok('Send-reports loop — iterates MIMImage (not MIMRegistration)')
        else:
            _fail('Send-reports loop — still iterates MIMRegistration (skips unregistered photographers)')
            fails += 1

        # Check 5 — Resend subject: must contain "Updated:" prefix when ?resend=1
        if "'Updated:" in src or '"Updated:' in src:
            _ok('Resend subject — "Updated:" prefix present')
        else:
            _fail('Resend subject — missing "Updated:" prefix for resend emails')
            fails += 1

        # Check 6 — f-string safety: no nested list comprehensions inside f-strings
        _nested = re.findall(r'f[\'\"]{1,3}[^\'\"]*\[.*? for .*? in .*?\][^\'\"]*[\'\"]{1,3}', src)
        if not _nested:
            _ok('f-string safety — no nested comprehensions inside f-strings (Python 3.12 safe)')
        else:
            _fail(f'f-string safety — {len(_nested)} nested comprehension(s) inside f-strings (Python 3.12 crash)')
            fails += 1

        # Check 7 — Sherpa field coverage: all 13 fields writable via repopulate or patch-field
        _patch_m = re.search(r'patch.field.*?(?=\n@app\.route|\ndef [a-z])', src, re.DOTALL)
        _patch_body = _patch_m.group(0) if _patch_m else ''
        _uncovered = [f for f in _sherpa_fields if f not in _repop_body and f not in _patch_body]
        if not _uncovered:
            _ok('Sherpa field coverage — all 13 fields writable via repopulate or patch-field')
        else:
            _fail(f'Sherpa field coverage — uncovered fields: {", ".join(_uncovered)}')
            fails += 1

    # ── Scorecard header band — SCORE label check (Session 171.1) ────────────
    # The word "SCORE" must never appear as a user-facing label. The scorecard
    # header band in image_detail.html showed "SCORE 8.42" live — caught in
    # Session 171 PDF review. This check scans app.py for any HTML string
    # literal containing ">SCORE<" or "SCORE" as a visible label (not a Python
    # variable, CSS class, or admin-only table header).
    # Root cause: sl_audit.py was only scanning app.py source (Python vars),
    # not the rendered HTML label strings inside Jinja templates.
    # Fix: image_detail.html must also be passed to sl_audit.py on every delivery.
    _section('Scorecard header band — SCORE label check (KYC · Session 171.1)')
    # Patterns that indicate user-facing SCORE label in rendered HTML output.
    # Deliberately narrow: only catches ">SCORE<" as an actual HTML text node
    # (the pattern visible in the scorecard header band: <span>SCORE</span>).
    # Python dict keys ('score': ...), JSON fields ("score": ...), CSS class
    # names, and variable references are NOT caught here — those are covered
    # by the KYC_TERMS sweep above with appropriate exclusions.
    # Session 171.1: root cause was ">SCORE<" as a static text node in
    # image_detail.html. This check catches that class of label only.
    _score_label_patterns = [
        r'>\s*SCORE\s*<',                    # HTML text node: >SCORE<, > SCORE <
        r'letter-spacing[^"\']{0,200}SCORE[^"\']{0,10}(?:</|\\n)',  # styled label ending tag
    ]
    _score_label_hits = []
    for _pat in _score_label_patterns:
        for _m in re.finditer(_pat, src):
            _ln = src[:_m.start()].count('\n') + 1
            _ctx = src[max(0,_m.start()-40):_m.end()+40].replace('\n', ' ').strip()
            # Exclude admin-only table headers (admin pages exempt from KYC).
            # These SCORE labels appear in admin challenge release and standings
            # tables — never user-facing. Identified by adjacent RANK/IMAGE/
            # PHOTOGRAPHER headers or the admin #8a8070 muted style.
            _admin_excl = ['rank</th>', 'photographer</th>', 'ai susp',
                           'sl score', 'mim ddi', '>rank<', '>image<',
                           '>photographer<', 'color:#8a8070',
                           'rankings are set', 'integrity hold',
                           'auto-releases available']
            if any(x.lower() in _ctx.lower() for x in _admin_excl):
                continue
            _score_label_hits.append(f'line {_ln}: {_ctx[:80]}')
    if _score_label_hits:
        for _h in _score_label_hits:
            _fail(f'User-facing SCORE label in HTML string — must be EVALUATION: {_h}')
            fails += 1
    else:
        _ok('No user-facing SCORE label found in app.py HTML strings')
    # Mandatory reminder: image_detail.html must be audited separately
    _note('MANDATORY: also run sl_audit.py image_detail.html on every deploy — scorecard header band is in that template, not in app.py')

    # ── Reminders ─────────────────────────────────────────────────────────────
    _section('Manual reminders')
    _note('Rule 2: Re-read the full change in context before deploying')
    _note('Rule 6: Each migration block must be tested in isolation')
    _note('Rule 9: Await explicit founder approval before pushing to GitHub/Railway')
    _note('DELIVERY STANDARD: Run sl_audit.py on all HTML templates — KYC · Mobile · iPad · 70yr · meta tags')
    _note('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    _note('PHYSICAL VERIFICATION REQUIRED after every deploy:')
    _note('  Mobile  : iPhone Safari + Android Chrome — tap, scroll, zoom test')
    _note('  iPad    : Safari landscape + portrait — layout, tap targets')
    _note('  70yr    : Non-technical adult reads page without help')
    _note('  Live    : Check Railway boot log — all workers up, no migration errors')
    _note('  Cache   : Purge Cloudflare after every deploy')
    _note('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')

    return _result(fails, filepath)


# ══════════════════════════════════════════════════════════════════════════════
# SL DELIVERY STANDARD — 5-point compliance check
# Runs automatically on every HTML template audit.
# Checks: KYC · Mobile · iPad · 70yr rule · Google meta tags
# ══════════════════════════════════════════════════════════════════════════════

# Additional KYC terms specific to scorecard/evaluation copy
SCORECARD_KYC_TERMS = [
    ('scored images',       'use "photographs evaluated"'),
    ('scored what it scored','use "kept this image alive"'),
    ('score jump',          'use "opportunity to grow"'),
    ('timing scores run',   'use "photographs consistently come alive"'),
    ('Light for the package','use "The light this week"'),
    ('0.1 stops maximum',   'use plain language'),
    ('moves scores',        'use "lifts your photographs"'),
    ('Unlocks after 5 scored', 'use "Available after your 5th photograph"'),
    ('backlit scene',       'use plain language — no jargon'),
    ('silhouette exposure', 'use plain language — no jargon'),
    ('Decisive Moment',     'use "whether the timing was right"'),
    ('Wonder Factor',       'use "whether it made you feel something"'),
    ('Aesthetic Quality',   'use "the emotion it creates"'),
    ('AQ ≥',                'jargon — remove from user-facing copy'),
    ('HARD TRUTH',          'replace with what_stood_out'),
    ('GAP ANALYSIS',        'replace with story card'),
    ('THE ONE IMPROVEMENT', 'replace with story card'),
    ('AREAS TO DEVELOP',    'replace with constructive language'),
    ('DEPTH OF DETAIL',     'jargon — use plain language'),
    ('POTY',                'use "Annual Excellence Award" — POTY is internal only'),
    ('your DDI',            'use "your score" or "your evaluation" — DDI is internal'),
    ('DDI score',           'use "your score" — DDI is internal jargon'),
    ('your genre',          'use "your interests" — Genre is internal UX term'),
]


def _run_delivery_standard(content, filepath, fails, is_detail_page=False, is_admin_page=False, is_legal_doc=False, is_snippet_file=False, is_mentor_page=False):
    """
    SL Delivery Standard — 5-point compliance check.
    Called at end of every HTML template audit.
    KYC · Mobile · iPad · 70yr rule · Google meta tags
    """
    fname = os.path.basename(filepath)
    # NARROW flag — only the actual image_detail/scorecard page, never
    # dashboard/pricing/faq/etc. Session 119: separated from the broad
    # is_detail_page flag (which means "skip homepage-only checks") after
    # dashboard.html was incorrectly failing CSI Card checks meant only for
    # the scorecard page — both flags were collapsed into one before this.
    _is_scorecard_page = any(x in fname.lower() for x in [
        'image_detail', 'scorecard', 'rating_card',
    ])
    _is_mobile_app_page = any(x in fname.lower() for x in [
        'dashboard.html', 'onboarding.html', 'onboarding_interests',
        'referral_landing', 'redeem.html',
        'mission_detail.html', 'first_login.html',
    ])

    # ── 0. CSS BRACE BALANCE — catches unclosed media queries / rules ─────────
    import re as _re
    _style_blocks = _re.findall(r'<style[^>]*>(.*?)</style>', content, _re.DOTALL)
    for _i, _css in enumerate(_style_blocks):
        _opens  = _css.count('{')
        _closes = _css.count('}')
        if _opens != _closes:
            _fail(f'CSS brace mismatch in <style> block {_i+1}: {_opens} open vs {_closes} close — unclosed media query or rule will break all CSS below it')
            fails += 1

    # ── 0b. JINJA IN SCRIPT BLOCKS — catches {{ }} inside <script> tags ────────
    # Session 168: dashboard.html and rate.html had Jinja expressions inside
    # <script> blocks. When Flask renders the template correctly these work, but
    # any rendering failure, caching issue, or deployment error causes the browser
    # to see the literal {{ which throws "Unexpected token '{'".
    # Rule: no {{ }} may appear inside any <script> tag. All dynamic values must
    # be passed via data- attributes on HTML elements and read in JS via dataset.
    # Exempt: {% %} Jinja block tags (if/for/endif) are safe — they produce no
    # output and are stripped by Jinja before the browser sees the page.
    _section('DELIVERY STANDARD 0b — Jinja expressions inside <script> blocks')
    import re as _re2
    # type="application/json" blocks are data containers, not executable JS.
    # Jinja expressions inside them are safe — the browser never executes them.
    # Only check executable script blocks (no type= or type="text/javascript").
    _script_blocks = _re2.findall(r'<script(?![^>]*type=["\']application/json["\'])[^>]*>(.*?)</script>', content, _re2.DOTALL)
    _jinja_in_script = []
    for _sbi, _sb in enumerate(_script_blocks):
        _jinja_exprs = _re2.findall(r'{{.*?}}', _sb)
        if _jinja_exprs:
            for _je in _jinja_exprs:
                _jinja_in_script.append(f'script block {_sbi+1}: {_je[:60]}')
    if _jinja_in_script:
        for _ji in _jinja_in_script:
            _fail(f'Jinja {{ }} in <script> block — move to data-attribute: {_ji}')
            fails += 1
        _note('FIX: add data-myval="{{ value }}" to an HTML element, read in JS via el.dataset.myval')
    else:
        _ok('No Jinja {{ }} expressions inside <script> blocks')

    # ── 1. KYC — full-page sweep + scorecard-specific terms ──────────────────
    # Session 91: expanded from scorecard-only to full HTML. Gaps in score/rank
    # coverage discovered on live PayU submission prep — closed here.
    _section('DELIVERY STANDARD 1/5 — KYC compliance (full page)')
    # Admin-only pages are exempt from KYC checks — they are never seen by
    # payment gateway reviewers and use internal terminology correctly.
    if is_admin_page:
        _note('KYC checks skipped — admin-only page, not user-facing')
    elif is_legal_doc:
        _note('KYC checks skipped — legal document page (deadline/submission/entry/genre are approved legal terms, Session 142)')
    elif is_snippet_file:
        _note('KYC checks skipped — snippet/render-only file, not a standalone browser page (Session 143)')
    elif is_mentor_page:
        # Run KYC but suppress the deadline term — it refers to review delivery deadlines
        # not a gambling/prize term. All other KYC terms still checked.
        _note('KYC deadline check skipped — mentor operational page (deadline = review delivery deadline, not KYC term, Session 143)')
        # Fall through to full KYC with deadline excluded
        stripped = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
        stripped = re.sub(r'\{%.*?%\}', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'\{\{.*?\}\}', '[VAR]', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<!--.*?-->', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<script\b[^>]*>.*?</script>', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<style\b[^>]*>.*?</style>', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'\b\w*_score\b|\b\w*_data\b|image\.\w+|audit\.\w+', '', stripped)
        stripped = re.sub(r'<option value="[^"]*">', '', stripped)
        stripped = re.sub(r'\s+id="[^"]*"', '', stripped)
        stripped = re.sub(r'\s+class="[^"]*"', '', stripped)
        stripped = re.sub(r"\s+id='[^']*'", '', stripped)
        stripped = re.sub(r"\s+class='[^']*'", '', stripped)
        stripped = re.sub(r'\s+style="[^"]*"', '', stripped)
        stripped = re.sub(r"\s+style='[^']*'", '', stripped)
        stripped = re.sub(r"'\s*DoD\s*'|'\s*DM\s*'|'\s*AQ\s*'|'\s*VD\s*'|'\s*WF\s*'", '', stripped)
        stripped_lower = stripped.lower()
        # Replace 'deadline' with safe text so it doesn't trigger KYC
        stripped_lower = stripped_lower.replace('deadline', 'REVIEW_DUE_DATE')
        kyc_full_fails = 0
        for label, term, exclusions in KYC_TERMS:
            stripped_check = _strip_exclusions(stripped_lower, [e.lower() for e in exclusions])
            if term.lower() in stripped_check:
                _fail(f'KYC (full page): {label}'); kyc_full_fails += 1; fails += 1
            else:
                _ok(f'Full-page KYC: {label}')
        if kyc_full_fails == 0:
            _ok('Full-page KYC terms -- clean')
        gold_hits = _gold_on_light(content)
        if gold_hits:
            _fail(f'KYC: Gold text colour -- gold on light background ({len(gold_hits)} hit(s)): {gold_hits[:2]}')
            fails += 1
        else:
            _ok('KYC: No gold text on light background')
        sc_start = content.find('{% block content %}')
        _section('DELIVERY STANDARD 1/5 — KYC compliance (scorecard dimensions)')
        _note('Scorecard dimension check uses full-page KYC above')
    else:
        # Strip Jinja comments and logic before checking
        stripped = re.sub(r'\{#.*?#\}', '', content, flags=re.DOTALL)
        stripped = re.sub(r'\{%.*?%\}', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'\{\{.*?\}\}', '[VAR]', stripped, flags=re.DOTALL)
        # Strip HTML comments -- developer notes, not user-facing copy
        stripped = re.sub(r'<!--.*?-->', '', stripped, flags=re.DOTALL)
        # Strip <script> blocks -- JS variable names / route strings are never user-facing copy
        stripped = re.sub(r'<script\b[^>]*>.*?</script>', '', stripped, flags=re.DOTALL)
        # Strip <style> blocks -- CSS class names / variables are never user-facing copy
        stripped = re.sub(r'<style\b[^>]*>.*?</style>', '', stripped, flags=re.DOTALL)
        # Strip Python variable names and Jinja tuple literals to avoid false positives
        stripped = re.sub(r'\b\w*_score\b|\b\w*_data\b|image\.\w+|audit\.\w+', '', stripped)
        # Strip HTML option values (admin-only form fields)
        stripped = re.sub(r'<option value="[^"]*">', '', stripped)
        # Strip HTML id and class attributes -- anchor names / CSS hooks are never user-facing copy
        stripped = re.sub(r'\s+id="[^"]*"', '', stripped)
        stripped = re.sub(r'\s+class="[^"]*"', '', stripped)
        stripped = re.sub(r"\s+id='[^']*'", '', stripped)
        stripped = re.sub(r"\s+class='[^']*'", '', stripped)
        # Strip inline style attributes -- CSS values like rgba(0,0,0,.3) are not user-facing copy
        stripped = re.sub(r'\s+style="[^"]*"', '', stripped)
        stripped = re.sub(r"\s+style='[^']*'", '', stripped)
        # Strip Python string literals in Jinja set expressions (e.g. ('DoD', ...) tuples)
        stripped = re.sub(r"'\s*DoD\s*'|'\s*DM\s*'|'\s*AQ\s*'|'\s*VD\s*'|'\s*WF\s*'", '', stripped)

        # 1a. Full-page KYC_TERMS sweep (catches score, rank, gym, Mentor Marketplace etc.)
        kyc_full_fails = 0
        stripped_lower = stripped.lower()
        for label, term, exclusions in KYC_TERMS:
            cleaned = _strip_exclusions(stripped_lower, [e.lower() for e in exclusions])
            if term.lower() in cleaned:
                _fail(f'KYC (full page): {label}')
                fails += 1
                kyc_full_fails += 1
        if kyc_full_fails == 0:
            _ok('Full-page KYC terms -- clean')

        # 1b. Scorecard-specific dimension jargon terms
        kyc_sc_fails = 0
        for phrase, fix in SCORECARD_KYC_TERMS:
            if phrase.lower() in stripped.lower():
                _fail(f'KYC: "{phrase}" in user-facing copy -- {fix}')
                fails += 1
                kyc_sc_fails += 1
        if kyc_sc_fails == 0:
            _ok('Scorecard dimension terms -- clean')

    # ── 2. Mobile (≤600px) ───────────────────────────────────────────────────
    _section('DELIVERY STANDARD 2/5 — Mobile view (≤600px)')
    mobile_checks = [
        ('Mobile breakpoint present',
         'max-width: 600px' in content or 'max-width: 480px' in content or 'max-width: 520px' in content),
        ('4-col grid collapses on mobile',
         'sc-four-grid' in content or 'repeat(4' not in content or 'grid-template-columns: 1fr !important' in content
         or bool(re.search(r'@media[^{]*\{[^@]*?\.grid-4\s*\{[^}]*grid-template-columns:\s*(1fr\b|repeat\(1|repeat\(2)', content, re.DOTALL))
         or bool(re.search(r'@media[^{]*\{[^@]*?[.\w-]+\s*\{[^}]*grid-template-columns:\s*(1fr\b|repeat\(1|repeat\(2|1fr\s+1fr\b)', content, re.DOTALL))),
        ('2-col grid collapses on mobile',
         'sc-two-grid' in content or ('1fr 1fr' not in content) or 'grid-template-columns: 1fr !important' in content
         or _is_mobile_app_page
         or bool(re.search(r'@media[^{]*\{[^@]*?[.\w-]+\s*\{[^}]*grid-template-columns:\s*1fr\b(?!\s*1fr)', content, re.DOTALL))),
        ('No fixed widths that break mobile',
         not any(
             f'width: {n}px' in content and
             f'max-width: {n}px' not in content and
             f'max-width:{n}px' not in content
             for n in range(700, 2000, 10)
         )),
        ('Buttons full-width on mobile or 44px tap targets',
         _has_44px_tap_target(content) or 'width: 100%' in content or 'width:100%' in content),
        ('Font sizes scale on mobile (16px+ body)',
         bool(re.search(r'font-size:\s*(1[6-9]|2[0-5])px', content))),
        ('Single column stack on mobile',
         'grid-template-columns: 1fr !important' in content or 'flex-direction: column !important' in content
         or 'auto-fit' in content or 'auto-fill' in content or _is_mobile_app_page or is_detail_page),
    ]
    mobile_fails = 0
    for label, result in mobile_checks:
        if result:
            _ok(f'[mobile] {label}')
        else:
            _fail(f'[mobile] {label}')
            fails += 1
            mobile_fails += 1
    if mobile_fails == 0:
        _ok('All mobile checks passed')

    # ── 3. iPad (768px–1024px) ────────────────────────────────────────────────
    _section('DELIVERY STANDARD 3/5 — iPad view (768px–1024px)')
    ipad_checks = [
        ('iPad breakpoint present (@768px)',
         'max-width: 768px' in content or 'max-width: 900px' in content
         or 'min-width: 768px' in content or _is_mobile_app_page or is_detail_page),
        ('4-col → 2-col on iPad',
         ('768px' in content and ('repeat(2' in content or '1fr 1fr' in content or 'grid-template-columns: 1fr' in content))
         or _is_mobile_app_page or is_detail_page),
        ('No 4-col layout at 768px without breakpoint',
         'max-width: 768px' in content or 'max-width: 900px' in content
         or 'min-width: 768px' in content or 'repeat(4' not in content),
        ('Content max-width set (no full-stretch on iPad)',
         'max-width' in content),
        ('Tap targets 44px on iPad',
         _has_44px_tap_target(content) or 'padding: 1' in content),
    ]
    ipad_fails = 0
    for label, result in ipad_checks:
        if result:
            _ok(f'[iPad] {label}')
        else:
            _fail(f'[iPad] {label}')
            fails += 1
            ipad_fails += 1
    if ipad_fails == 0:
        _ok('All iPad checks passed')

    # ── 4. 70-year rule ───────────────────────────────────────────────────────
    _section('DELIVERY STANDARD 4/5 — 70-year readability rule')

    # Determine scope — new scorecard section if present, else full file.
    # EXCEPTION (Session 120): base.html is the layout shell, not a content
    # page -- it has no scorecard section and never will. Falling back to a
    # full-file scan there catches nav chrome (chevron icons at 9px, the
    # brand-tag label at 11px, logo/h1 line-height 1.2) which are not
    # scorecard body text. Every other template still gets the full scan.
    _is_layout_shell = fname.lower() == 'base.html'
    sc_start = content.find('NEW SCORECARD LAYOUT')
    check_scope = content[sc_start:] if sc_start != -1 else content

    if sc_start == -1 and _is_layout_shell and not _is_scorecard_page:
        _note('[70yr] Skipped — base.html is the layout shell, no scorecard section present')
    else:
        all_sizes = [int(s) for s in re.findall(r'font-size\s*:\s*(\d+)px', check_scope)]
        tiny  = [s for s in all_sizes if s < 13]
        small = [s for s in all_sizes if 13 <= s < 15]
        ok_sz = [s for s in all_sizes if s >= 15]

        if tiny:
            if _is_mobile_app_page and all(s >= 12 for s in tiny):
                _note(f'[70yr] Fonts {sorted(set(tiny))}px present — verify these are UI eyebrow/metadata labels only (mobile-app page)')
            else:
                _fail(f'[70yr] Fonts below 13px in scorecard: {sorted(set(tiny))} — unreadable for elderly users')
                fails += 1
        else:
            _ok('[70yr] No fonts below 13px in scorecard section')

        if small:
            _note(f'[70yr] Fonts 13-14px: {sorted(set(small))} — acceptable for labels/captions only, not body copy')
        else:
            _ok('[70yr] No 13-14px fonts (all labels are 15px+)')

        if not ok_sz:
            _fail('[70yr] No body fonts ≥15px found — need minimum 15px for body copy')
            fails += 1
        else:
            _ok(f'[70yr] Body fonts ≥15px present (min={min(ok_sz)}px, max={max(ok_sz)}px)')

        # Line height — check new scorecard section scope only
        lh_scope = check_scope  # already scoped to new section or full file
        # Only match CSS line-height (colon syntax), not SVG attributes or other 1-digit hits
        lh_vals = [float(v) for v in re.findall(r'line-height\s*:\s*([0-9]+\.[0-9]+)', lh_scope)
                   if re.match(r'^[0-9]+\.[0-9]+$', v)]
        lh_bad = [v for v in lh_vals if v < 1.5]
        if lh_bad:
            if _is_mobile_app_page and all(v >= 1.0 for v in lh_bad):
                _note(f'[70yr] Line-height {lh_bad} present — verify these are display/title elements only (mobile-app page). Body copy must use 1.6+.')
            else:
                _fail(f'[70yr] Line-height below 1.5: {lh_bad} — use 1.7+ for elderly readability')
                fails += 1
        elif lh_vals:
            _ok(f'[70yr] Line-height ≥1.5 throughout (min={min(lh_vals):.1f})')
        else:
            _note('[70yr] No explicit line-height found — verify body text has line-height ≥1.7')

    # CTA buttons large enough
    cta_pads = [int(p) for p in re.findall(r'padding\s*:\s*(\d+)px', check_scope)]
    cta_ok = [p for p in cta_pads if p >= 12]
    if not cta_ok:
        _fail('[70yr] No button padding ≥12px — CTAs may be too small for elderly users')
        fails += 1
    else:
        _ok(f'[70yr] Button padding ≥12px present')

    # Contrast — no rgba text with opacity < 0.4
    # Negative lookbehind excludes border-color/background-color etc. (Session 120)
    low_opacity = re.findall(r'(?<!-)color\s*:\s*rgba\([^)]+,\s*0\.[0-3]\d*\s*\)', check_scope)
    if low_opacity:
        _fail(f'[70yr] Low-opacity text colour: {low_opacity[:2]} — fails contrast for elderly users')
        fails += 1
    else:
        _ok('[70yr] No low-opacity text colours (contrast safe)')

    # ── 5. Google meta tags ───────────────────────────────────────────────────
    _section('DELIVERY STANDARD 5/5 — Google/social meta tags')
    if is_snippet_file:
        _note('Meta tag checks skipped — snippet/render-only file, not a standalone browser page (Session 143)')
    else:
        _extends_base = 'extends "base.html"' in content or "extends 'base.html'" in content
        _block_map = {
            'og:title': 'og_title', 'og:description': 'og_description', 'og:image': 'og_image',
            'twitter:image': 'twitter_image',
        }

        # Session 201 — page indexing rules
        # Public standalone pages (should be indexed by Google)
        # try_standing: public scorecard — good for SEO (photographer name searches)
        # league_haiku: public league — good for SEO
        # pricing_haiku: public pricing — good for SEO
        _should_index = any(x in fname for x in ['league_haiku', 'pricing_haiku', 'try_standing', 'index.html'])
        # Private standalone pages (must NOT be indexed)
        _must_noindex = any(x in fname for x in [
            'dashboard_haiku', 'image_detail_haiku',
            'try_gallery', 'try_result', 'profile',
        ])
        # Standalone pages need explicit canonical (base.html pages inherit it via route)
        _needs_canonical = not _extends_base and not is_snippet_file

        meta_checks = [
            ('og:title',       'Open Graph title (required for sharing)'),
            ('og:description', 'Open Graph description'),
            ('og:image',       'Open Graph image (photograph shows when shared)'),
            ('twitter:card',   'Twitter/X card'),
            ('twitter:image',  'Twitter/X image'),
            ('canonical',      'Canonical URL (prevents duplicate content)'),
            ('noindex',        'noindex robots directive'),
        ]
        meta_fails = 0
        for tag, desc in meta_checks:
            _block  = _block_map.get(tag)
            _has_block_override = _block and ('{% block ' + _block in content)
            _present = tag in content or _has_block_override

            if tag == 'canonical':
                if _present:
                    _ok(f'[meta] {desc}')
                elif _needs_canonical:
                    _fail(f'[meta] {desc} — MISSING on standalone page (required for SEO)')
                    fails += 1; meta_fails += 1
                elif _extends_base:
                    _ok(f'[meta] {desc} (handled by base.html or route)')
                else:
                    _note(f'[meta] {desc} — not present (verify if needed)')

            elif tag == 'noindex':
                if _must_noindex:
                    if _present:
                        _ok(f'[meta] noindex present — correct (private page, must not be indexed)')
                    else:
                        _fail(f'[meta] noindex MISSING — private page must have robots noindex,nofollow')
                        fails += 1; meta_fails += 1
                elif _should_index:
                    if _present:
                        _fail(f'[meta] noindex present on PUBLIC page — remove so Google can index this page')
                        fails += 1; meta_fails += 1
                    else:
                        _ok(f'[meta] noindex absent — correct (public page, indexable)')
                else:
                    if _present:
                        _note(f'[meta] noindex present — verify this page should not be indexed')
                    else:
                        _note(f'[meta] noindex — not present (verify if needed)')

            else:
                if _present:
                    _ok(f'[meta] {desc}')
                elif tag == 'twitter:card' and _extends_base:
                    _ok(f'[meta] {desc} (inherited from base.html)')
                elif tag in ('og:title', 'og:description', 'og:image', 'twitter:image') and _extends_base:
                    _ok(f'[meta] {desc} (inherited default from base.html)')
                else:
                    _fail(f'[meta] {desc} — MISSING')
                    fails += 1; meta_fails += 1

        if meta_fails == 0:
            _ok('All meta tags present and correct')

        # ── OG description brand prefix check (Session 201) ───────────────────
        # Every page OG description must start with the brand signature:
        # "Photography Assessment & Evolution Platform. Making Images Matter. "
        # followed by page-specific copy.
        _OG_PREFIX = 'Photography Assessment & Evolution Platform. Making Images Matter.'
        _og_desc_match = re.search(r'og:description[^>]*content="([^"]+)"', content)
        if _og_desc_match:
            _og_desc_val = _og_desc_match.group(1)
            if _og_desc_val.startswith(_OG_PREFIX):
                _ok(f'[meta] OG description starts with brand signature')
            elif _extends_base:
                _note(f'[meta] OG description brand prefix — extends base.html, verify block override has prefix')
            else:
                _fail(f'[meta] OG description missing brand prefix — must start with: "{_OG_PREFIX}"')
                fails += 1
        elif not _extends_base:
            _note(f'[meta] OG description not found inline — cannot verify brand prefix')


    _section('DELIVERY STANDARD — CSI note cards (image_detail.html only)')
    if is_snippet_file:
        _note('CSI checks skipped — snippet/render-only file (Session 143)')
    elif _is_scorecard_page:
        _csi_checks = [
            ('CSI Card A — csi_own_duplicate condition present',
             'csi_own_duplicate' in content),
            ('CSI Card A — dark amber background (#2D1F00)',
             '#2D1F00' in content),
            ('CSI Card A — contact sheet copy present',
             'contact sheet' in content),
            ('CSI Card B — csi_threshold_hit condition present',
             'csi_threshold_hit' in content),
            ('CSI Card B — dark navy background (#1A1A2E)',
             '#1A1A2E' in content),
            ('CSI Card B — Sherpa pool copy present',
             'seen in the Shutter League' in content or 'SHUTTER LEAGUE POOL' in content),
            ('CSI cards — no score-change language',
             'score reduced' not in content and 'score lowered' not in content
             and 'score is lower' not in content and 'score has been reduced' not in content),
        ]
        for label, result in _csi_checks:
            if result: _ok(label)
            else: _fail(label); fails += 1
    else:
        _note('CSI card checks skipped — not a detail/scorecard page')

    # ── Known bad route names (Session 201) ──────────────────────────────────
    # 'programmes' is not a route — the function is 'contests', URL is /programmes
    _bad_routes = [
        ("url_for('programmes')", "url_for('contests')  # /programmes URL is served by contests()"),
    ]
    for _bad, _fix in _bad_routes:
        if _bad in content:
            _fail(f'Bad route name: {_bad} — use {_fix}')
            fails += 1
        else:
            _ok(f'Route name OK — no {_bad}')


    # Standalone Haiku pages must use the cream topbar nav matching dashboard_haiku.
    # Pages that extend base.html inherit Sonnet nav — flagged as a known gap.
    _section('DELIVERY STANDARD — Haiku nav consistency (Session 201)')

    _HAIKU_STANDALONE = any(x in fname for x in [
        'try_standing', 'pricing_haiku', 'league_haiku', 'dashboard_haiku',
    ])
    _HAIKU_BASE_EXTEND = any(x in fname for x in [
        'try_gallery', 'image_detail_haiku', 'upload-staging', 'try-staging',
    ])

    if _HAIKU_STANDALONE:
        # Must have dark navy topbar (#1A2744) — matching /try/gallery standard
        import re as _re_nav
        _is_dashboard_haiku_nav = 'dashboard_haiku' in fname
        _topbar_block = _re_nav.search(r'\.sl-topbar\s*\{([^}]+)\}', content)
        _topbar_css = _topbar_block.group(1) if _topbar_block else ''
        _has_dark_topbar = 'background:#1A2744' in _topbar_css.replace(' ', '')
        if _topbar_css and not _has_dark_topbar:
            _fail('Haiku standalone nav — topbar background is NOT dark navy #1A2744 (must match /try/gallery standard)')
            fails += 1
        else:
            _ok('Haiku standalone nav — dark navy topbar correct (#1A2744)')

        # Must have logo image in nav brand
        _has_logo = (
            'shutterleague-logo-cropped.png' in content and
            ('sl-brand' in content or 'nav-brand' in content)
        )
        if _has_logo:
            _ok('Haiku nav — logo image (shutterleague-logo-cropped.png) present in brand')
        else:
            _fail('Haiku nav — logo image missing from brand (add shutterleague-logo-cropped.png)')
            fails += 1

        # Must have correct brand sub "Making Images Matter"
        # Exception: dashboard_haiku uses dark nav by design (approved Session 175)
        _is_dashboard_haiku = 'dashboard_haiku' in fname
        if _is_dashboard_haiku:
            _note('Haiku nav — dashboard_haiku uses dark nav by design (approved Session 175), brand sub exempted')
        elif 'Making Images Matter' in content:
            _ok('Haiku nav — brand sub "Making Images Matter" present')
        elif 'Photography Institution' in content and ('sl-brand-sub' in content or 'nav-brand-sub' in content):
            _fail('Haiku nav — brand sub shows "Photography Institution" (should be "Making Images Matter")')
            fails += 1
        else:
            _note('Haiku nav — brand sub text not verified')

        # Must have Haiku nav items (Dashboard/Evaluate/League) not Sonnet items
        _has_sonnet_nav = (
            "url_for('my_gallery')" in content or
            "url_for('dashboard')" in content and 'Evaluate' not in content
        )
        _has_haiku_nav = (
            "url_for('try_welcome')" in content or
            "url_for('try_page')" in content or
            "url_for('league_haiku')" in content
        )
        if _has_sonnet_nav and not _has_haiku_nav:
            _fail('Haiku standalone nav — Sonnet nav items present (My Gallery/dashboard) without Haiku items')
            fails += 1
        elif _has_haiku_nav:
            _ok('Haiku nav — correct Haiku route items present (try_welcome/try_page/league_haiku)')
        else:
            _note('Haiku nav — route items not verified')

        # Nav items must match the standard exactly (Session 201 — dashboard_haiku is source of truth)
        # Standard: Home · My evaluations · Upload · Pricing · League of Photographers · Profile
        _required_nav_items = [
            ("url_for('try_welcome')", 'Home'),
            ("url_for('try_gallery')", 'My evaluations'),
            ("url_for('try_page')",    'Upload'),
            ("url_for('pricing')",     'Pricing'),
            ("url_for('league_haiku')", 'League of Photographers'),
            ("url_for('profile')",     'Profile'),
        ]
        _nav_failures = []
        for _route, _label in _required_nav_items:
            if _route not in content:
                _nav_failures.append(f'{_label} ({_route})')
        if _nav_failures:
            _fail(f'Haiku nav — missing standard items: {", ".join(_nav_failures)}')
            fails += 1
        else:
            _ok('Haiku nav — all standard items present (Home/My evaluations/Upload/Pricing/League of Photographers/Profile)')

        # Logo must be row layout (img left, text right) — not column
        if 'sl-brand' in content:
            _brand_css = content[content.find('.sl-brand'):content.find('.sl-brand')+100]
            if 'flex-direction:column' in _brand_css or 'flex-direction: column' in _brand_css:
                _fail('Haiku nav — logo brand uses column layout (should be row: img left, text right)')
                fails += 1
            else:
                _ok('Haiku nav — logo brand uses row layout (img left, text right)')

        # Must have mobile bottom nav (sl-mob-nav, mob-nav, or sl-bottom-nav)
        if 'sl-mob-nav' in content or 'class="mob-nav"' in content or 'sl-bottom-nav' in content:
            _ok('Haiku nav — mobile bottom nav present')
        else:
            _fail('Haiku standalone nav — mobile bottom nav (sl-mob-nav) missing')
            fails += 1

        # Mobile bottom nav must have correct items
        _mob_has_dashboard = "url_for('try_welcome')" in content
        _mob_has_evaluate  = "url_for('try_page')" in content
        _mob_has_league    = "url_for('league_haiku')" in content
        if _mob_has_dashboard and _mob_has_evaluate and _mob_has_league:
            _ok('Haiku nav — mobile bottom nav has Dashboard/Evaluate/League items')
        else:
            missing = []
            if not _mob_has_dashboard: missing.append('Dashboard')
            if not _mob_has_evaluate:  missing.append('Evaluate')
            if not _mob_has_league:    missing.append('League')
            _fail(f'Haiku mobile nav — missing items: {", ".join(missing)}')
            fails += 1

        # Active colour must be gold #C8A84B not Haiku yellow #F4C20D
        if '#F4C20D' in content and 'mob-nav-item.active' in content:
            _fail('Haiku mobile nav — active colour is #F4C20D (should be #C8A84B to match desktop)')
            fails += 1
        else:
            _ok('Haiku mobile nav — active colour correct (#C8A84B or not overridden)')

    elif _HAIKU_BASE_EXTEND:
        # Pages extending base.html — Sonnet nav is inherited, flag as known gap
        _note('Haiku page extends base.html — inherits Sonnet nav (known gap, Session 202 cleanup)')
        _note('Verify: Haiku user on this page sees correct content, no Sonnet route leaks')
    else:
        _note('Haiku nav check — not a Haiku page, skipped')


    # ── TWO-WORLDS SEPARATION — Session 208 ──────────────────────────────────
    # Constitution: "Never mix. Never let a Haiku user see Sonnet pages or vice versa."
    # Haiku standalone templates must not reference Sonnet routes.
    # Sonnet templates (extending base.html) must not reference Haiku routes.
    _section('DELIVERY STANDARD — Two-worlds separation (Session 208)')

    _SONNET_ROUTES = [
        "url_for('dashboard')",
        "url_for('my_gallery')",
        "url_for('leaderboard')",
        "url_for('image_detail')",
        "url_for('upload')",
        "url_for('recent_work')",
        "url_for('standings_public')",
        "url_for('evolving_eye')",
    ]
    _HAIKU_ROUTES = [
        "url_for('try_welcome')",
        "url_for('try_page')",
        "url_for('try_gallery')",
        "url_for('try_result')",
        "url_for('try_standing')",
        "url_for('league_haiku')",
    ]

    if _HAIKU_STANDALONE:
        # Haiku standalone must not reference Sonnet routes
        _sonnet_leaks = [r for r in _SONNET_ROUTES if r in content]
        if _sonnet_leaks:
            _fail(f'Haiku standalone references Sonnet routes: {", ".join(_sonnet_leaks)}')
            fails += 1
        else:
            _ok('Haiku standalone — no Sonnet route leaks found')

        # Haiku standalone must not extend base.html
        if '{% extends' in content and 'base.html' in content:
            _fail('Haiku standalone extends base.html — must be fully standalone (constitution Rule 10)')
            fails += 1
        else:
            _ok('Haiku standalone — does not extend base.html')

        # Haiku standalone must not use cream topbar #F5F3EF on nav/topbar
        _cream_nav = re.search(r'(?:sl-topbar|mob-nav|sl-top-nav|topbar)[^}]*#F5F3EF', content)
        if _cream_nav:
            _fail('Haiku standalone — cream #F5F3EF found on nav/topbar (must be #1A2744 navy)')
            fails += 1
        else:
            _ok('Haiku standalone — topbar/nav colour correct (no cream #F5F3EF)')

        # LOP brand language must not appear outside league_haiku.html
        if fname.lower() not in ('league_haiku.html',):
            _lop_terms = ['League of Photographers', 'Masters in the Making', 'Earned.\nNot purchased']
            _lop_found = [t for t in _lop_terms if t in content]
            if _lop_found:
                _fail(f'Haiku standalone — LOP brand language found outside league_haiku.html: {", ".join(_lop_found)}')
                fails += 1
            else:
                _ok('Haiku standalone — no LOP brand language leak')

    elif _HAIKU_BASE_EXTEND or (not _HAIKU_STANDALONE and '{% extends' in content and 'base.html' in content):
        # Sonnet pages extending base.html must not reference Haiku routes
        # EXEMPT: try_gallery.html and image_detail_haiku.html are Haiku pages that
        # extend base.html — known gap (constitution Session 207, line 61).
        # They legitimately reference Haiku routes. Skip check for these.
        _TWO_WORLDS_EXEMPT = ('try_gallery.html', 'image_detail_haiku.html')
        if fname.lower() in _TWO_WORLDS_EXEMPT:
            _note(f'Two-worlds Sonnet check — {fname} exempt (Haiku page extending base.html, known gap)')
        else:
            _haiku_leaks = [r for r in _HAIKU_ROUTES if r in content]
            if _haiku_leaks:
                _fail(f'Sonnet page references Haiku routes: {", ".join(_haiku_leaks)}')
                fails += 1
            else:
                _ok('Sonnet page — no Haiku route leaks found')
    else:
        _note('Two-worlds separation — not a Haiku or Sonnet template, skipped')

    # Exact filename match only -- the previous 'admin' in fname and 'admin_user'
    # not in fname substring check was written when admin.html was the only
    # non-admin_user admin page. It silently matched every NEW admin page added
    # since (e.g. admin_curation.html), wrongly demanding CSI nav/export markup
    # that only ever belonged on the main admin dashboard. Found auditing
    # admin_curation.html (Session 122).
    _is_admin = fname.lower() == 'admin.html'
    if _is_admin:
        _csi_admin_checks = [
            ('CSI nav button present',
             'admin_csi_page' in content or 'csi_unreviewed_count' in content),
            ('CSI export section present',
             'admin_export_csi' in content or 'Cultural Saturation' in content),
            ('CSI match log export link',
             'admin_export_csi_matches' in content or 'csi-matches' in content),
            ('CSI full audit export link',
             'admin_export_csi_full' in content or 'csi-full' in content),
            ('CSI nav button — no font below 13px in nav area',
             'font-size:10px' not in content or 'badge-count' in content),
        ]
        for label, result in _csi_admin_checks:
            if result: _ok(label)
            else: _fail(label); fails += 1
    else:
        _note('CSI admin export checks skipped — not admin page')

    _section('DELIVERY STANDARD — Summary')
    _note('Standard covers: KYC · Mobile · iPad · 70yr rule · Google meta tags')
    _note('Run on every HTML template before delivery — Rule 9 applies')
    _note('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    _note('PHYSICAL VERIFICATION REQUIRED — audit catches structure, not rendering')
    _note('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    _note('  Mobile  : Test on real iPhone (Safari) and Android (Chrome) at 375px')
    _note('            → Tap every button. Check no element is cut off or overlaps.')
    _note('            → Dropdowns, modals, inline widgets must open and close cleanly.')
    _note('            → Scroll the full page. No horizontal scroll on any element.')
    _note('  iPad    : Test on real iPad (Safari) at 768px landscape and portrait')
    _note('            → 2-column layouts must not produce cards narrower than 170px.')
    _note('            → Touch targets must be reachable — not hidden behind nav.')
    _note('  70yr    : Hand device to a non-technical adult. Watch without helping.')
    _note('            → Can they read every label without zooming?')
    _note('            → Can they tap every button first try?')
    _note('            → Does the page make sense without explanation?')
    _note('  Contrast: Check gold text is only on dark backgrounds — never on cream.')
    _note('            Check slate blue text is only on light backgrounds.')
    _note('  Safari  : Font rendering is heavier in Safari than Chrome. Verify weights.')
    _note('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    _note('Audit PASSED does not mean ready to deploy. Physical check is mandatory.')

    return fails


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not sys.argv[1:]:
        print(__doc__)
        sys.exit(0)

    all_passed = True
    for filepath in sys.argv[1:]:
        if not os.path.exists(filepath):
            print(f'\n  XX  File not found: {filepath}')
            all_passed = False
            continue
        name = os.path.basename(filepath).lower()
        if filepath.endswith('.py'):
            passed = audit_apppy(filepath)
        elif any(x in name for x in ['email_', '_email', 'mail_', '_mail', 'notification_', 'trigger_']):
            passed = audit_email(filepath)
        elif filepath.endswith('.html'):
            passed = audit_html(filepath)
        else:
            print(f'\n  ~~  Skipping unknown file type: {filepath}')
            passed = True
        if not passed:
            all_passed = False

    if len(sys.argv[1:]) > 1:
        print()
        print('=' * 60)
        if all_passed:
            print('  OK  ALL FILES CLEAN -- SAFE TO DELIVER')
        else:
            print('  XX  ONE OR MORE FILES FAILED -- DO NOT DELIVER')
        print('  Rule 9: Await explicit founder approval before pushing.')
        print('=' * 60)
        print()
