#!/usr/bin/env python3
"""
verify_app.py — Shutter League pre-deploy checks
Runs before every app.py output. Full executed output shown to user.

Rules enforced (per standing instructions):
  1.  Mobile/Desktop rendering — flag risky patterns (iOS, Android, Safari, Chrome)
  2.  Re-read full change in context (manual reminder)
  3.  Live site / KYC — zero tolerance for breakage
  4.  SQL syntax — valid PostgreSQL via sqlparse
  5.  ALTER TABLE specifics:
        DROP CONSTRAINT IF EXISTS      ✅
        ADD CONSTRAINT IF NOT EXISTS   ❌  use try/except
        ADD COLUMN IF NOT EXISTS       ✅
  6.  Migration blocks tested in isolation (reminder)
  7.  AST parse
  8.  sqlparse validation on every SQL statement
  9.  Show for approval — one change, one deploy, one verify (reminder)
"""
import ast, re, sys
import sqlparse

PASS = []
FAIL = []

def ok(msg):   PASS.append(msg); print(f"  \u2713 {msg}")
def err(msg):  FAIL.append(msg); print(f"  \u2717 {msg}")
def note(msg):                   print(f"  ~ {msg}")

# ── Load ──────────────────────────────────────────────────────────────────────
try:
    with open('/home/claude/app.py', 'r') as f:
        src = f.read()
    lines = src.splitlines()
    ok(f"Loaded app.py ({len(lines)} lines)")
except Exception as e:
    err(f"Could not load app.py: {e}"); sys.exit(1)

# ── RULES 3 + 9: Live site + approval reminders ───────────────────────────────
print("\n[RULES 3+9] Live site / approval reminders")
note("Site is LIVE and in KYC state with PayU — zero tolerance for breakage or glitches")
note("Rule 9: Present change for approval first. One change \u2192 one deploy \u2192 one verify.")

# ── RULE 7: AST Parse ─────────────────────────────────────────────────────────
print("\n[RULE 7] AST Parse")
try:
    tree = ast.parse(src)
    ok("AST parse clean — no syntax errors")
except SyntaxError as e:
    err(f"SyntaxError at line {e.lineno}: {e.msg}")
    sys.exit(1)

# Python 3.13: no backslash escapes inside f-string expressions
violations = []
for node in ast.walk(tree):
    if isinstance(node, ast.JoinedStr):
        raw = lines[node.lineno - 1] if node.lineno <= len(lines) else ''
        depth = 0
        for ch in raw:
            if ch == '{': depth += 1
            if ch == '}': depth -= 1
            if depth > 0 and ch == '\\':
                violations.append(f"line {node.lineno}: {raw.strip()[:80]}")
                break
if violations:
    for v in violations[:5]: err(f"Backslash in f-string expression: {v}")
else:
    ok("No backslash escapes inside f-string expressions (Python 3.13 safe)")

# ── RULES 4 + 8: SQL extraction and sqlparse validation ──────────────────────
print("\n[RULES 4+8] SQL extraction and sqlparse validation")

# Extract SQL using bracket-matching on db.text(...) to correctly handle
# multi-line implicit string concatenation across Python lines.
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
    fragments = re.findall(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)', raw_inner)
    parts = [a or b for a, b in fragments]
    full_sql = ' '.join(p.strip() for p in parts if p.strip())
    if full_sql and len(full_sql) > 10:
        sqls.append((full_sql, src[:m.start()].count('\n') + 1))

ok(f"Extracted {len(sqls)} SQL statements (bracket-matched, concat-aware)")

sql_errors = []
for full_sql, lineno in sqls:
    upper = full_sql.upper()

    # sqlparse parse check
    try:
        parsed = sqlparse.parse(full_sql)
        if not parsed:
            sql_errors.append(f"line {lineno}: sqlparse returned empty: {full_sql[:60]!r}")
            continue
    except Exception as e:
        sql_errors.append(f"line {lineno}: sqlparse exception: {e}: {full_sql[:60]!r}")
        continue

    # Rule 5a: ADD CONSTRAINT IF NOT EXISTS — invalid PostgreSQL
    if re.search(r'ADD\s+CONSTRAINT\s+IF\s+NOT\s+EXISTS', upper):
        sql_errors.append(f"line {lineno}: ADD CONSTRAINT IF NOT EXISTS — invalid PG syntax")

    # Rule 5b: DROP CONSTRAINT must use IF EXISTS
    if re.search(r'DROP\s+CONSTRAINT\s+(?!IF\s+EXISTS)[A-Z_]', upper):
        sql_errors.append(f"line {lineno}: DROP CONSTRAINT without IF EXISTS: {full_sql[:80]!r}")

    # Rule 5c: ADD COLUMN should use IF NOT EXISTS
    if re.search(r'ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)[A-Z_]', upper) and 'ALTER' in upper:
        sql_errors.append(f"line {lineno}: ADD COLUMN without IF NOT EXISTS: {full_sql[:80]!r}")

    # Unbalanced parentheses (after correct full extraction)
    if full_sql.count('(') != full_sql.count(')'):
        sql_errors.append(f"line {lineno}: unbalanced parentheses in SQL: {full_sql[:80]!r}")

    # Mixed placeholder styles
    has_colon = bool(re.search(r':\w+', full_sql))
    if has_colon and '%s' in full_sql:
        sql_errors.append(f"line {lineno}: mixed placeholders (:param and %s): {full_sql[:60]!r}")

if sql_errors:
    for e in sql_errors: err(e)
else:
    ok(f"All {len(sqls)} SQL statements pass validation (sqlparse + PG rules)")

# ── RULE 5: ALTER TABLE specifics (source-level check) ────────────────────────
print("\n[RULE 5] ALTER TABLE specifics")
if re.search(r'ADD\s+CONSTRAINT\s+IF\s+NOT\s+EXISTS', src, re.I):
    err("ADD CONSTRAINT IF NOT EXISTS in source — invalid PostgreSQL, use try/except")
else:
    ok("No ADD CONSTRAINT IF NOT EXISTS")

# ── MODEL FIELDS ──────────────────────────────────────────────────────────────
print("\n[MODEL FIELDS] User / Image field rules")

hits = re.findall(r'(?:current_user|user)\s*\.\s*display_name', src)
if hits: [err(f"User.display_name (use full_name/username): {h}") for h in hits]
else: ok("No User.display_name access")

hits = [f"line {i+1}" for i, l in enumerate(lines)
        if 'uploaded_at' in l and not l.strip().startswith('#')]
if hits: [err(f"uploaded_at used (field is created_at): {h}") for h in hits]
else: ok("No uploaded_at (field is created_at)")

if re.search(r'db\.relationship\s*\(\s*["\']User["\']', src):
    err("db.relationship('User') on Image — use User.query.get(img.user_id)")
else:
    ok("No db.relationship('User') on Image model")

# ── Apostrophes in email HTML ─────────────────────────────────────────────────
print("\n[RULE 4b] Apostrophes in HTML email strings")
apos_hits = []
for m in re.finditer(r'html_body\s*=\s*[\s\S]{0,4000}?(?=\n\s*\))', src):
    blk = m.group(0).replace("&#39;", '').replace("\\'", '')
    if re.search(r"[a-zA-Z]'[a-zA-Z]", blk):
        ln = src[:m.start()].count('\n') + 1
        apos_hits.append(f"line {ln}")
if apos_hits: [err(f"Raw apostrophe in html_body (use &#39;): {h}") for h in apos_hits[:3]]
else: ok("No raw apostrophes in html_body strings")

# ── Route integrity ───────────────────────────────────────────────────────────
print("\n[RULE 7c] Route integrity")
routes = re.findall(r"@app\.route\s*\(\s*'([^']+)'", src)
ok(f"{len(routes)} routes defined")
seen = {}
for r in routes: seen[r] = seen.get(r, 0) + 1
dupes = {r: c for r, c in seen.items() if c > 1}
if dupes: [err(f"Duplicate route: {r} ({c}x)") for r, c in dupes.items()]
else: ok("No duplicate routes")

# ── RULE 1: Mobile / rendering flags ─────────────────────────────────────────
print("\n[RULE 1] Mobile & rendering safety flags")
wide_px = re.findall(r'width:\s*[6-9]\d\d\s*px', src)
if wide_px:
    note(f"{len(wide_px)} fixed px width(s) in email HTML — verify iOS/Android/Safari/Chrome rendering")
else:
    ok("No wide fixed-px widths in email HTML")
for t in ['dashboard.html', 'login.html', 'upload.html']:
    if t in src: ok(f"render_template('{t}') present")
    else: err(f"render_template('{t}') missing")

# ── RULE 6: Migration isolation reminder ─────────────────────────────────────
print("\n[RULE 6] Migration isolation")
alter_count = len(re.findall(r'ALTER\s+TABLE', src, re.I))
if alter_count:
    note(f"{alter_count} ALTER TABLE statement(s) in app.py")
    note("Rule 6: Each migration block must be tested in isolation before embedding")
else:
    ok("No ALTER TABLE statements")

# ── RULE 2 reminder ───────────────────────────────────────────────────────────
print("\n[RULE 2] Full-context re-read reminder")
note("Rule 2: Re-read the full change in context (not just the isolated block) before deploying")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 54)
print(f"  PASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("  STATUS: \u2717  DO NOT DEPLOY — fix failures above")
    sys.exit(1)
else:
    print("  STATUS: \u2713  SAFE TO DEPLOY")
    print()
    note("Rule 9: Await explicit approval before pushing to GitHub/Railway.")
print("=" * 54)
