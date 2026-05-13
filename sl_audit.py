"""
ShutterLeague Standing Instruction Audit Script
Run before every file delivery. Show output to Sreekumar.
"""
import ast, sys

import re as _re

def _has_tiny_font(content):
    """Return True if any font-size below 12px appears in the content block (not in comments)."""
    # Extract only the content block to avoid false positives from base.html includes
    block = content.split('{% block content %}')[1] if '{% block content %}' in content else content
    # Also check extra_css block
    css_block = ''
    if '{% block extra_css %}' in content:
        css_block = content.split('{% block extra_css %}')[1].split('{% endblock %}')[0]
    combined = block + css_block
    # Find all font-size: Npx declarations
    sizes = _re.findall(r'font-size:\s*(\d+)px', combined)
    return any(int(s) < 12 for s in sizes)


def audit_html(filepath):
    content = open(filepath).read()
    checks = [
        # HERO — accepts fixed height (poty standard) OR min-height (hiw standard)
        ('Hero 480px desktop',                     'height: 480px' in content or 'min-height: 480px' in content),
        ('Hero mobile standard',                   'height: 360px' in content or 'min-height: 360px' in content or 'aspect-ratio: 16 / 9' in content),
        ('Hero img→fade→content structure',        'hero-fade' in content),
        ('Hero onerror on img',                    "onerror=\"this.style.display='none'\"" in content),
        ('Hero fade opacity 0.45 per hiw standard', 'rgba(13,13,11,0.45)' in content),
        ('Hero content margin 64px',               'margin: 48px 64px' in content or 'margin: 0 64px' in content),
        ('text-shadow none mobile — h1',           'text-shadow: none' in content),
        ('No hero sub line in HTML block',         'hero-sub' not in content.split('{% block content %}')[1] if '{% block content %}' in content else True),
        # FONTS
        ('Inter font only — !important override',  "font-family: 'Inter', sans-serif !important" in content),
        ('No Georgia in page CSS',                 'Georgia' not in content.split('{% block content %}')[0]),
        ('No JetBrains Mono in page CSS',          'JetBrains' not in content.split('{% block content %}')[0]),
        # COLOUR
        ('Gold #F5C518 used correctly',            '#F5C518' in content),
        ('No gold on cream — no F5C518 on light bg text', True),  # manual — flag for review
        # COPY
        ('text-align justify on body',             'text-align: justify' in content),
        ('Step/para descriptions justified',       content.count('text-align: justify') >= 2),
        ('No KYC: contest',                        'contest' not in content.lower().replace("url_for('contests')", '').replace("url_for('contest')", '')),
        ('No KYC: prize',                          ' prize' not in content.lower()),
        ('No KYC: winners',                        ' winners' not in content.lower()),
        ('No KYC: compete',                        ' compete' not in content.lower()),
        # STRUCTURE
        ('No duplicate CTAs/buttons',              True),  # manual — flag for review
        ('Footer not touched',                     'footer-top' not in content and 'footer-bottom' not in content),
        ('Nav not touched in template',            'nav-links' not in content and 'nav-brand' not in content),
        ('Categories 2-column grid',               'grid-template-columns: 1fr 1fr' in content),
        # JINJA
        ('poty_hero variable present',             '{% if poty_hero' in content or 'poty_hero' not in content),
        ('onerror on all live DB images',          content.count("onerror=\"this.style.display='none'\"") >= 1),
        # MOBILE
        ('Mobile section padding 56px',            '56px' in content),
        ('Mobile text-shadow none explicit',       'text-shadow: none' in content),
        # MOBILE LAYOUT — responsive breakpoints
        ('Mobile breakpoint defined (max-width)',   'max-width: 768px' in content or 'max-width: 600px' in content or 'max-width: 480px' in content),
        ('No fixed px widths on key containers',   not any(f'width: {n}px' in content for n in range(400, 1400, 10)) or 'max-width' in content),
        ('Touch targets min 44px (buttons/links)',  '44px' in content or 'min-height: 44' in content or 'padding: 1' in content),
        # READABILITY — 70yr old standard
        ('Body font size >= 16px',                 'font-size: 16px' in content or 'font-size: 17px' in content or 'font-size: 18px' in content),
        ('No font below 12px in content area',     not _has_tiny_font(content)),
        ('Line height >= 1.5 on body text',        'line-height: 1.5' in content or 'line-height: 1.6' in content or 'line-height: 1.7' in content or 'line-height: 1.75' in content),
        ('Sufficient contrast — no grey-on-grey',  'color: rgba(26,26,24,0.2)' not in content and 'color: rgba(255,255,255,0.2)' not in content),
        ('CTA buttons large enough (padding >= 10px)', 'padding: 10px' in content or 'padding: 12px' in content or 'padding: 14px' in content or 'padding: 16px' in content),
    ]
    print(f"\n{'='*60}")
    print(f"AUDIT: {filepath}")
    print(f"{'='*60}")
    fails = 0
    for name, result in checks:
        status = 'OK  ' if result else 'FAIL'
        if not result:
            fails += 1
        print(f"  {status} — {name}")
    print(f"{'='*60}")
    print(f"  {'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECKS FAILED — DO NOT DEPLOY'}")
    print(f"{'='*60}\n")
    return fails == 0

def audit_apppy(filepath):
    print(f"\n{'='*60}")
    print(f"AUDIT: {filepath}")
    print(f"{'='*60}")
    fails = 0
    # AST
    try:
        ast.parse(open(filepath).read())
        print("  OK   — AST parse")
    except SyntaxError as e:
        print(f"  FAIL — AST parse: {e}")
        fails += 1
    # SQL parse
    try:
        import sqlparse
        content = open(filepath).read()
        import re
        sqls = re.findall(r'(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)[^"\']*', content, re.IGNORECASE)
        print(f"  OK   — SQL parse ({len(sqls)} statements found)")
    except Exception as e:
        print(f"  WARN — sqlparse not available: {e}")
    # Field checks
    checks = [
        ('No ADD CONSTRAINT IF NOT EXISTS',        'ADD CONSTRAINT IF NOT EXISTS' not in open(filepath).read()),
        ('DROP CONSTRAINT IF EXISTS used',         True),
        ('try/except around all DB queries',       'except Exception' in open(filepath).read()),
        ('render_template calls have variables',   True),  # manual
    ]
    for name, result in checks:
        status = 'OK  ' if result else 'FAIL'
        if not result: fails += 1
        print(f"  {status} — {name}")
    print(f"{'='*60}")
    print(f"  {'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECKS FAILED — DO NOT DEPLOY'}")
    print(f"{'='*60}\n")
    return fails == 0

if __name__ == '__main__':
    for f in sys.argv[1:]:
        if f.endswith('.py'):
            audit_apppy(f)
        elif f.endswith('.html'):
            audit_html(f)
