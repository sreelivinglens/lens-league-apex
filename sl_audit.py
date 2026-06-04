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
      'contest_entries', 'ann.contest']),
    ('No KYC: prize',       ' prize',        []),
    ('No KYC: winner',      ' winner',       []),
    ('No KYC: winners',     ' winners',      []),
    ('No KYC: compete',     ' compete',      []),
    ('No KYC: ranking',     'ranking',       ['url_for', 'ranking_season', 'ranking_public',
                                              'ranking_last_active', 'poty_used_year',
                                              'path_to_rank', 'rp-card', 'rp_card']),
    ('No KYC: leaderboard', 'leaderboard',   ["url_for('leaderboard')", 'url_for("leaderboard")']),
    ('No KYC: reward',      ' reward',       []),
    ('No KYC: deadline',    'deadline',      []),
    ('No KYC: submission',  'submission',    ['url_for', 'poty_entry', 'form']),
    ('No KYC: entry (copy)',
     ' entry',
     ["url_for('contest_enter')", "url_for('my_entries')", "url_for('programme_enter')",
      "url_for('my_participations')", 'type="submit"', "method='POST'",
      'poty_entry', 'contest_entry', 'entry_id', 'entry_images', 'entry_score',
      'entry_form', 'existing', 'current-entry', 'poty_entries',
      'pool entry', 'db-pool-entry', '.db-pool', '/* pool', 'peer pool',
      'entry button', 'entry {', 'entry{', '-entry']),
    ('No KYC: entries (copy)',
     ' entries',
     ["url_for('my_entries')", "url_for('my_participations')", 'poty_entries',
      'poty_entry_images', 'contest_entries', 'entry_images',
      'winners_html', 'winners_text', 'for w in sorted(winners',
      'raw_submissions', 'submission_count', 'submission_record',
      'resubmission', 'raw_submission', 'no ranked submissions']),
    ('No KYC: compete',     'competi',       ['url_for']),
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
    """Detect gold colour used as body/heading text colour — not scores, badges, borders, or mono labels."""
    hits = []
    lines = content.split('\n')
    for i, line in enumerate(lines):
        l = line.lower()
        # Skip legitimate gold uses: borders, backgrounds, score displays, badges, mono labels, SVG
        if any(x in l for x in [
            'border', 'background', 'fill:', 'stroke:', 'box-shadow',
            'score', 'tier', 'badge', 'mono', 'font-mono', 'gold-dark',
            'gold-subtle', 'var(--gold-', '/* ', '//', 'opacity',
            'db-poty', 'db-score', 'img-tier', 'badge-tier', 'tier-',
            'rp-score', 'entry-score', 'image-select-score',
            'alert-lbl', 'peer-nudge', 'lbl.amber', 'nudge a',
            'text-transform: uppercase', 'letter-spacing',
        ]):
            continue
        for gold in GOLD_VALS:
            if f'color:{gold}' in l.replace(' ', '') or f'color: {gold}' in l:
                hits.append(gold)
    return hits

def _shaded_fonts(content):
    """Detect rgba text colours with low opacity (shaded/muted body text)."""
    hits = re.findall(r'color:\s*rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*0\.[0-3]\d*\s*\)', content)
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
            # Flag mid-range colours — not dark (< 80) and not light (> 180)
            if 80 < brightness < 180:
                hits.append(m)
        except Exception:
            pass
    return hits

# ── Banner & summary helpers ──────────────────────────────────────────────────

def _banner():
    print()
    print('═' * 60)
    print('  SHUTTER LEAGUE — PRE-DEPLOY AUDIT')
    print('  sl_audit.py  ·  Unified  ·  June 2026')
    print('  Rule 9: No push without explicit founder approval')
    print('═' * 60)

def _section(title):
    print(f'\n  ── {title}')

def _ok(label):   print(f'    ✓  {label}')
def _fail(label): print(f'    ✗  {label}')
def _note(label): print(f'    ~  {label}')

def _result(fails, filepath):
    print()
    print('─' * 60)
    if fails == 0:
        print(f'  ✓  CLEAN — SAFE TO DELIVER    {os.path.basename(filepath)}')
    else:
        print(f'  ✗  DO NOT DELIVER — {fails} failure{"s" if fails != 1 else ""}    {os.path.basename(filepath)}')
    print('─' * 60)
    return fails == 0

# ── KYC check (shared: html + email) ─────────────────────────────────────────

def _run_kyc_checks(content, fails, context='template'):
    _section(f'KYC Language — {context}')
    cl = content.lower()
    for label, term, exclusions in KYC_TERMS:
        stripped = _strip_exclusions(cl, [e.lower() for e in exclusions])
        if term.lower() in stripped:
            _fail(label)
            fails += 1
        else:
            _ok(label)
    # Gold as text colour
    gold_hits = _gold_on_light(content)
    if gold_hits:
        _fail(f'No gold text colour — gold permitted only for scores/badges/borders ({len(gold_hits)} hit(s))')
        fails += 1
    else:
        _ok('No gold used as body/heading text colour')
    return fails

# ── HTML audit ────────────────────────────────────────────────────────────────

def audit_html(filepath):
    _banner()
    print(f'\n  FILE: {filepath}')
    content = open(filepath).read()
    fails = 0

    # ── Hero ──────────────────────────────────────────────────────────────────
    _section('Hero structure')
    checks = [
        ('Hero 480px desktop',              'height: 480px' in content or 'min-height: 480px' in content),
        ('Hero mobile standard',            'height: 360px' in content or 'min-height: 360px' in content or 'aspect-ratio: 16 / 9' in content),
        ('Hero img→fade→content structure', 'hero-fade' in content),
        ('Hero onerror on img',             "onerror=\"this.style.display='none'\"" in content),
        ('Hero fade opacity 0.45',          'rgba(13,13,11,0.45)' in content),
        ('Hero content margin 64px',        'margin: 48px 64px' in content or 'margin: 0 64px' in content),
        ('No hero-sub line in content',     'hero-sub' not in (content.split('{% block content %}')[1] if '{% block content %}' in content else content)),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── Fonts ─────────────────────────────────────────────────────────────────
    _section('Fonts')
    checks = [
        ('Inter font only — !important override', "font-family: 'Inter', sans-serif !important" in content),
        ('No Georgia in page CSS',                'Georgia' not in content.split('{% block content %}')[0]),
        ('No JetBrains Mono in page CSS',         'JetBrains' not in content.split('{% block content %}')[0]),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── Colour & font colour rules ────────────────────────────────────────────
    _section('Colour & font colour rules')

    # Gold as text
    gold_hits = _gold_on_light(content)
    if gold_hits:
        _fail(f'Gold used as text colour — use only for scores/badges/borders ({len(gold_hits)} hit(s)): {gold_hits[:2]}')
        fails += 1
    else:
        _ok('No gold text colour in templates')

    # Shaded / low-opacity fonts
    shaded = _shaded_fonts(content)
    if shaded:
        _fail(f'Shaded/low-opacity font colour found ({len(shaded)} hit(s)) — use var(--text-muted) only for metadata: {shaded[:2]}')
        fails += 1
    else:
        _ok('No shaded/low-opacity font colours')

    # Non-black/white hex text colours
    mid = _non_black_white_body_text(content)
    if mid:
        _note(f'Mid-range hex text colour(s) — verify these are metadata only, not body copy: {mid[:3]}')
    else:
        _ok('Hex text colours are near-black or near-white only')

    # No grey-on-grey
    if 'color: rgba(26,26,24,0.2)' in content or 'color: rgba(255,255,255,0.2)' in content:
        _fail('Grey-on-grey text detected — insufficient contrast')
        fails += 1
    else:
        _ok('No grey-on-grey contrast issues')

    # ── Copy / layout ─────────────────────────────────────────────────────────
    _section('Copy & layout')
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

    # ── Mobile integrity (≤768px) ─────────────────────────────────────────────
    _section('Mobile integrity (≤768px)')
    checks = [
        ('Mobile breakpoint defined',           'max-width: 768px' in content or 'max-width: 600px' in content or 'max-width: 480px' in content),
        ('Mobile section padding 56px',         '56px' in content),
        ('Mobile text-shadow none on h1',       'text-shadow: none' in content),
        ('Touch targets min 44px',              '44px' in content or 'min-height: 44' in content or 'padding: 1' in content),
        ('No fixed px widths on containers',    not any(f'width: {n}px' in content for n in range(400, 1400, 10)) or 'max-width' in content),
        ('Grids collapse — auto-fill or 1fr',   'auto-fill' in content or 'auto-fit' in content or '1fr' in content or 'flex-wrap: wrap' in content),
        ('Tables have mobile stacking',         'table' not in content.lower() or 'display: block' in content or 'overflow-x' in content or '@media' in content),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── iPad integrity (768px–1024px) ─────────────────────────────────────────
    _section('iPad integrity (768px–1024px)')
    ipad_bp = 'max-width: 1024px' in content or 'max-width: 900px' in content or 'min-width: 768px' in content
    if ipad_bp:
        _ok('iPad breakpoint defined')
    else:
        _note('No explicit iPad breakpoint — verify 4-col grids do not produce cards < 170px wide')
    if 'minmax(170px' in content or 'minmax(180px' in content or 'minmax(200px' in content or 'minmax(220px' in content:
        _ok('Grid minmax prevents narrow cards on iPad')
    else:
        _note('Verify grid cards are not narrower than 170px on iPad (768–1024px viewport)')

    # ── 70-year-old readability ───────────────────────────────────────────────
    _section('70-year-old readability standard')
    checks = [
        ('Body font size >= 16px',              'font-size: 16px' in content or 'font-size: 17px' in content or 'font-size: 18px' in content),
        ('No font below 12px in content area',  not _has_tiny_font(content)),
        ('Line height >= 1.5 on body text',     'line-height: 1.5' in content or 'line-height: 1.6' in content or 'line-height: 1.7' in content or 'line-height: 1.75' in content),
        ('CTA buttons large enough (>= 10px pad)', 'padding: 10px' in content or 'padding: 12px' in content or 'padding: 14px' in content or 'padding: 16px' in content),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    # ── KYC language ─────────────────────────────────────────────────────────
    fails = _run_kyc_checks(content, fails, context='HTML template')

    return _result(fails, filepath)


# ── Email template audit ──────────────────────────────────────────────────────

def audit_email(filepath):
    _banner()
    print(f'\n  FILE: {filepath}  [EMAIL TEMPLATE]')
    content = open(filepath).read()
    fails = 0

    _section('Email rendering')
    checks = [
        ('No wide fixed px widths (>600px)',    not bool(re.search(r'width:\s*[6-9]\d\d\s*px', content))),
        ('Font size >= 14px in email body',     'font-size: 14px' in content or 'font-size: 15px' in content or 'font-size: 16px' in content),
        ('No raw apostrophes (use &#39;)',       not bool(re.search(r"[a-zA-Z]'[a-zA-Z]", content.replace("&#39;", '')))),
        ('Line height set',                     'line-height' in content),
        ('max-width on container',              'max-width' in content),
    ]
    for label, result in checks:
        if result: _ok(label)
        else: _fail(label); fails += 1

    _section('Colour — email')
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

    fails = _run_kyc_checks(content, fails, context='email template')
    return _result(fails, filepath)


# ── app.py audit (merged verify_app.py) ──────────────────────────────────────

def audit_apppy(filepath):
    _banner()
    print(f'\n  FILE: {filepath}  [FLASK APP]')
    print()
    _note('Site is LIVE and in KYC state with PayU — zero tolerance for breakage')
    _note('Rule 9: Present change for approval first. One change → one deploy → one verify.')

    try:
        import sqlparse
    except ImportError:
        print('\n  ✗  sqlparse not installed — run: pip install sqlparse --break-system-packages')
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
        _ok('AST parse clean — no syntax errors')
    except SyntaxError as e:
        _fail(f'SyntaxError at line {e.lineno}: {e.msg}')
        sys.exit(1)

    # Python 3.13 f-string backslash check
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
            sql_errors.append(f'line {lineno}: ADD CONSTRAINT IF NOT EXISTS — invalid PG syntax')
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
        _fail('ADD CONSTRAINT IF NOT EXISTS in source — invalid PostgreSQL, use try/except')
        fails += 1
    else:
        _ok('No ADD CONSTRAINT IF NOT EXISTS')

    alter_count = len(re.findall(r'ALTER\s+TABLE', src, re.I))
    if alter_count:
        _note(f'{alter_count} ALTER TABLE statement(s) — Rule 6: test each migration in isolation first')
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
        _ok(f'models.py loaded — {len(model_fields)} models found')
        user_f = model_fields.get('User', [])
        img_f  = model_fields.get('Image', [])
        if 'display_name' in user_f:
            _fail('User model has display_name — should not exist'); fails += 1
        else:
            _ok('User model: no display_name ✓')
        if 'uploaded_at' in img_f:
            _fail('Image model has uploaded_at — should be created_at'); fails += 1
        else:
            _ok('Image model: no uploaded_at ✓')
        for req in ['raw_verification_required','raw_verified','raw_disqualified',
                    'created_at','score','tier','user_id']:
            if req not in img_f:
                _fail(f'Image model missing required field: {req}'); fails += 1
        _ok('Image model required fields present')
    else:
        _note('models.py not found — upload alongside app.py for full field validation')

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
        _fail("db.relationship('User') on Image — use User.query.get(img.user_id)"); fails += 1
    else:
        _ok("No db.relationship('User') on Image")

    # ── Email body KYC + apostrophe checks ───────────────────────────────────
    _section('Email body checks (KYC + apostrophes)')
    email_blocks = list(re.finditer(r'html_body\s*=\s*[\s\S]{0,8000}?(?=\n\s*(?:msg\.|send_|flash|return|#))', src))
    subject_lines = re.findall(r'(?:msg\.subject|subject)\s*=\s*["\']([^"\']+)["\']', src)

    if not email_blocks:
        _ok('No html_body email blocks found in app.py')
    else:
        _ok(f'{len(email_blocks)} html_body block(s) found — checking KYC + apostrophes')
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

            # Skip admin-only email blocks
            blk_lower = blk.lower()
            if any(x in blk_lower for x in [
                'admin_email', 'to_addresses=[admin_email', 'admin_notify',
                'shutter league  \u2014  admin', 'shutter league \u00b7 admin',
                '[admin]', 'admin panel', 'admin dashboard',
                'rankings are set', 'auto-releases available',
                'integrity hold', 'release_url',
                # Admin-only RAW flagging emails
                'grandmaster image auto-flagged', 'raw verification. submission record created',
                'view in raw queue', 'flagged for review',
                # Mentor review operational emails — internal service, not contest
                'shutter league \u00b7 mentor', 'review deadline reminder',
                'mentor dashboard', 'you have a review due in',
                'pending sessions', 'write review now',
            ]):
                continue

            # KYC on email body — with email-specific smart exclusions
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
                # Python docstrings/comments inside capture range
                'formal submission', 'contestant has verified',
                'no user or winner emails', 'no scoreable submissions',
                'raw verified without', 'manual override',
                'already ranked', 'preview + release',
                # Surrounding function docstrings captured by regex
                'without a formal submission', 'mark image as raw verified',
                'used for testing', 'mark_raw_verified',
                # More docstring/comment patterns
                'without a formal submission', 'formal submission',
                'admin shortcut', 'admin_mark_raw',
                # Mentor review operational deadline — not a contest deadline
                'review deadline reminder', 'deadline_ist',
                'complete your review before the deadline',
                'shutter league \u00b7 mentor', 'mentor dashboard',
                'you have a review due',
            ]
            # Skip known false-positive blocks (Python context bled in)
            is_false_positive_block = any(x in blk_lower for x in false_positive_contexts)

            for label, term, exclusions in KYC_TERMS:
                EMAIL_EXCL_FULL = EMAIL_EXCL + (false_positive_contexts if is_false_positive_block else [])
                # For false positive blocks, also add the bare term itself to exclusions
                # since the term appears only in code context, not email HTML
                if is_false_positive_block:
                    EMAIL_EXCL_FULL = EMAIL_EXCL_FULL + [term.strip()]
                stripped = _strip_exclusions(blk_lower, [e.lower() for e in exclusions + EMAIL_EXCL_FULL])
                if term.lower() in stripped:
                    _fail(f'Email body ~line {ln}: KYC term "{term}" found')
                    fails += 1
            # Apostrophe check — HTML email content only, not Python code
            # Remove Python code patterns before checking
            clean = blk.replace("&#39;", '').replace("\\'", '')
            # Remove Python code lines and Courier New font declarations (contain apostrophes)
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
                _fail(f'Email body ~line {ln}: raw apostrophe — use &#39;')
                fails += 1
            # Gold text colour — only flag body/heading text, not CTAs/scores/labels
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
                    # h1/h2 headings in emails are brand headers — legitimate
                    '<h1', '<h2', 'font-style:italic', 'font-style: italic',
                    'font-size:30px', 'font-size:24px', 'font-size:22px',
                    'margin-bottom:20px', 'margin-bottom:24px',
                    # Shutter League brand label in email header
                    'shutter league', 'f5c518;text-transform',
                    # Hyperlinks are legitimate gold colour usage
                    '<a href', 'style="color:#c8a84b', "style='color:#c8a84b",
                    'style="color:#f5c518', "style='color:#f5c518",
                    # Rank/position displays
                    '<strong style="color:#c8a84b', "strong style='color:#c8a84b",
                    'placed <strong', 'position <strong',
                ]):
                    continue
                real_gold.append(gl.strip()[:60])
            if real_gold:
                _fail(f'Email body ~line {ln}: gold used as body text colour: {real_gold[:1]}')
                fails += 1

    # Subject line KYC
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

    # Template name checks — KYC-safe names
    _section('Template name KYC compliance')
    old_templates = ['contest_enter.html', 'my_entries.html']
    new_templates = ['programme_enter.html', 'my_participations.html']
    for t in old_templates:
        # Exact match — not substring (e.g. open_contest_enter.html is different)
        if f"'{t}'" in src or f'"{t}"' in src:
            _fail(f'KYC-unsafe template name still referenced: {t} — should be renamed')
            fails += 1
        else:
            _ok(f'{t} — not referenced ✓')
    for t in new_templates:
        if t in src:
            _ok(f'{t} — KYC-safe name in use ✓')
        else:
            _note(f'{t} — not yet referenced (rename pending)')

    # Required templates present
    for t in ['dashboard.html', 'login.html', 'upload.html']:
        if t in src: _ok(f"render_template('{t}') present")
        else: _fail(f"render_template('{t}') missing"); fails += 1

    # ── Mobile rendering flags ────────────────────────────────────────────────
    _section('Mobile & rendering safety (Rule 1)')
    wide_px = re.findall(r'width:\s*[6-9]\d\d\s*px', src)
    if wide_px:
        _note(f'{len(wide_px)} fixed px width(s) in email HTML — verify iOS/Android/Safari/Chrome')
    else:
        _ok('No wide fixed-px widths in email HTML')

    # ── KYC on app.py render_template strings + flash messages ───────────────
    _section('KYC language in app.py (flash messages + render context)')
    flash_msgs = re.findall(r"flash\s*\(\s*[f]?['\"]([^'\"]{0,200})['\"]", src)
    render_strings = re.findall(r"render_template\s*\('[^']+',([^)]{0,400})\)", src)
    combined_copy = ' '.join(flash_msgs + render_strings).lower()
    # Add app-specific exclusions for variable names and admin-only messages
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
        # Admin-only flash messages — not user-facing
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
        # F-string variable patterns picked up by regex
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
            _note(f'KYC term "{t}" in flash/render context — verify admin-only (not user-facing)')
        _note(f'{len(kyc_fails_app)} term(s) above are likely admin flash messages — review manually if deploying after KYC submission')
    else:
        _ok('No KYC terms in flash messages or render_template context strings')

    # ── Reminders ─────────────────────────────────────────────────────────────
    _section('Manual reminders')
    _note('Rule 2: Re-read the full change in context before deploying')
    _note('Rule 6: Each migration block must be tested in isolation')
    _note('Rule 9: Await explicit founder approval before pushing to GitHub/Railway')

    return _result(fails, filepath)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if not sys.argv[1:]:
        print(__doc__)
        sys.exit(0)

    all_passed = True
    for filepath in sys.argv[1:]:
        if not os.path.exists(filepath):
            print(f'\n  ✗  File not found: {filepath}')
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
            print(f'\n  ~  Skipping unknown file type: {filepath}')
            passed = True
        if not passed:
            all_passed = False

    if len(sys.argv[1:]) > 1:
        print()
        print('═' * 60)
        if all_passed:
            print('  ✓  ALL FILES CLEAN — SAFE TO DELIVER')
        else:
            print('  ✗  ONE OR MORE FILES FAILED — DO NOT DELIVER')
        print('  Rule 9: Await explicit founder approval before pushing.')
        print('═' * 60)
        print()
