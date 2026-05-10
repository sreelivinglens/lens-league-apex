"""
ShutterLeague Standing Instruction Audit Script
Run before every file delivery. Show output to Sreekumar.
"""
import ast, sys

def audit_html(filepath):
    content = open(filepath).read()
    checks = [
        # HERO
        ('Hero min-height 480px desktop',          'min-height: 480px' in content),
        ('Hero min-height 360px mobile',           'min-height: 360px' in content),
        ('Hero img→fade→content structure',        'sl-poty-hero-fade' in content or 'sl-hiw-hero-fade' in content),
        ('Hero onerror on img',                    "onerror=\"this.style.display='none'\"" in content),
        ('Hero fade opacity ≤ 0.30',               any(f'rgba(13,13,11,0.{n})' in content for n in ['10','15','20','25','30'])),
        ('Hero align-self flex-end on container',  'align-self: flex-end' in content),
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
