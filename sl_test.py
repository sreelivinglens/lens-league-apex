#!/usr/bin/env python3
"""
sl_test.py — ShutterLeague local scoring test harness
Run before every deploy that touches auto_score.py or scoring.py.

Usage:
  python sl_test.py <image_path> <genre> <title> [options]

Examples:
  python sl_test.py swan.jpg Street "Swan" --sub-genre creative_minimalist --photographer Srichaitanya
  python sl_test.py uprising.jpg Street "Uprising" --photographer Srichaitanya
  python sl_test.py swan.jpg Street "Swan" --dry-run   # inspect prompts only, no API call

Options:
  --sub-genre STR       Photographer's filed sub-genre (optional)
  --photographer STR    Photographer name (default: Test)
  --subject STR         Subject description (optional)
  --location STR        Location (optional)
  --dry-run             Print all prompts as they'd be sent — no API call
  --vision-only         Run vision pass only, no scoring pass
  --expected-dod F      Assert DoD >= this value (fails test if not met)
  --expected-dis F      Assert Disruption >= this value
  --expected-dm F       Assert DM >= this value
  --expected-wonder F   Assert Wonder >= this value
  --expected-aq F       Assert AQ >= this value
  --expected-score F    Assert final score >= this value
  --expected-tier STR   Assert tier equals this value (e.g. Grandmaster)
  --expected-subgenre S Assert engine detected this sub-genre
"""

import argparse
import json
import os
import sys
import re
import time

# ── Path setup — allow running from /home/claude without installing ───────────
sys.path.insert(0, '/home/claude')

# ── Colour codes ──────────────────────────────────────────────────────────────
GRN  = '\033[92m'
RED  = '\033[91m'
YLW  = '\033[93m'
BLU  = '\033[94m'
CYN  = '\033[96m'
GRY  = '\033[90m'
BOLD = '\033[1m'
RST  = '\033[0m'

def ok(msg):   print(f"  {GRN}✓{RST}  {msg}")
def fail(msg): print(f"  {RED}✗{RST}  {msg}")
def warn(msg): print(f"  {YLW}~{RST}  {msg}")
def info(msg): print(f"  {BLU}·{RST}  {msg}")
def head(msg): print(f"\n{BOLD}{CYN}{'═'*60}{RST}\n{BOLD}{CYN}  {msg}{RST}\n{BOLD}{CYN}{'═'*60}{RST}")
def sub(msg):  print(f"\n{BOLD}  {msg}{RST}")

PASS_COUNT = 0
FAIL_COUNT = 0

def assert_gte(label, actual, expected):
    global PASS_COUNT, FAIL_COUNT
    if actual is None:
        fail(f"{label}: missing in result")
        FAIL_COUNT += 1
        return
    if float(actual) >= float(expected):
        ok(f"{label}: {actual:.2f} >= {expected:.2f}")
        PASS_COUNT += 1
    else:
        fail(f"{label}: {actual:.2f} < {expected:.2f}  ← BELOW THRESHOLD")
        FAIL_COUNT += 1

def assert_eq(label, actual, expected):
    global PASS_COUNT, FAIL_COUNT
    if str(actual).lower() == str(expected).lower():
        ok(f"{label}: '{actual}'")
        PASS_COUNT += 1
    else:
        fail(f"{label}: got '{actual}', expected '{expected}'")
        FAIL_COUNT += 1

# ── Prompt inspection helpers ─────────────────────────────────────────────────

def show_system_brief_summary(system_brief: str):
    """Print the key sections of SYSTEM_BRIEF that affect scoring."""
    sub("SYSTEM_BRIEF — key sections")
    lines = system_brief.split('\n')
    in_step0 = False
    in_weights = False
    for line in lines:
        if 'GENRE WEIGHTS' in line:
            in_weights = True
        if 'STEP 0' in line:
            in_weights = False
            in_step0 = True
        if 'STEP 1' in line:
            in_step0 = False
        if in_weights or in_step0:
            print(f"    {GRY}{line}{RST}")

def show_genre_context_summary(genre_context: str):
    """Print the first 800 chars of genre_context to verify correct rubric loaded."""
    sub("GENRE_CONTEXT — first 800 chars")
    print(f"    {GRY}{genre_context[:800].replace(chr(10), chr(10)+'    ')}{RST}")
    if len(genre_context) > 800:
        print(f"    {GRY}... [{len(genre_context)} chars total]{RST}")

def show_score_prompt_summary(prompt: str):
    """Show the final assembled prompt structure."""
    sub("SCORE_PROMPT — structure check")
    sections = ['GENRE CONTEXT', 'WEIGHT OVERRIDE', 'STEP 0', 'AWARD-LEVEL', 'HARD FLOOR', 'MINIMALIST']
    for s in sections:
        present = s in prompt
        if present:
            ok(f"Prompt contains: {s}")
        else:
            warn(f"Prompt missing:  {s}")

# ── Monkey-patch to intercept prompts before API call ────────────────────────

_captured = {}

def _patch_httpx(dry_run: bool):
    """
    Intercept the httpx.post call inside auto_score to:
    1. Capture the exact payload (system + user prompt) before it's sent
    2. In dry-run mode, return a fake response instead of hitting the API
    """
    import httpx as _httpx
    _orig_post = _httpx.post

    def _fake_post(url, **kwargs):
        payload = kwargs.get('json', {})
        _captured['system']  = payload.get('system', '')
        _captured['prompt']  = ''
        for msg in payload.get('messages', []):
            for block in msg.get('content', []):
                if block.get('type') == 'text':
                    _captured['prompt'] += block.get('text', '')
        _captured['model']   = payload.get('model', '')
        _captured['payload'] = payload

        if dry_run:
            # Return a fake valid response so parsing doesn't crash
            fake = {
                "content": [{"type": "text", "text": json.dumps({
                    "dod": 0.0, "disruption": 0.0, "dm": 0.0,
                    "wonder": 0.0, "aq": 0.0, "score": 0.0,
                    "tier": "DRY_RUN", "title_name": "DRY RUN",
                    "apex_verdict": "Dry run — no API call made.",
                    "technical": "", "moment": "", "next_image": "",
                    "creative_direction": "", "edit_base": "", "edit_creative": "",
                    "soul_bonus": False, "judge_referral": False,
                    "excellence_bonus": False, "scored_as": "dry_run",
                    "genre_insight": None, "genre_suggestion": None,
                })}],
                "model": "dry-run", "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0}
            }
            class FakeResp:
                status_code = 200
                def json(self): return fake
            return FakeResp()

        return _orig_post(url, **kwargs)

    _httpx.post = _fake_post
    return _orig_post

def _unpatch_httpx(orig):
    import httpx as _httpx
    _httpx.post = orig

# ── Vision pass interceptor ───────────────────────────────────────────────────

_vision_captured = {}

def _patch_vision():
    """Capture vision_analyse inputs/outputs."""
    import auto_score as _as
    _orig = _as.vision_analyse

    def _wrapped(img_data, media_type, title, subject):
        result = _orig(img_data, media_type, title, subject)
        _vision_captured['result'] = result
        return result

    _as.vision_analyse = _wrapped
    return _orig

def _unpatch_vision(orig):
    import auto_score as _as
    _as.vision_analyse = orig

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='ShutterLeague local scoring harness')
    parser.add_argument('image',         help='Path to image file')
    parser.add_argument('genre',         help='Genre (Street, Creative, Documentary, etc.)')
    parser.add_argument('title',         help='Image title')
    parser.add_argument('--sub-genre',   default=None, dest='sub_genre')
    parser.add_argument('--photographer',default='Test', dest='photographer')
    parser.add_argument('--subject',     default='', dest='subject')
    parser.add_argument('--location',    default='', dest='location')
    parser.add_argument('--dry-run',     action='store_true', dest='dry_run')
    parser.add_argument('--vision-only', action='store_true', dest='vision_only')
    # Assertions
    parser.add_argument('--expected-dod',      type=float, default=None)
    parser.add_argument('--expected-dis',      type=float, default=None)
    parser.add_argument('--expected-dm',       type=float, default=None)
    parser.add_argument('--expected-wonder',   type=float, default=None)
    parser.add_argument('--expected-aq',       type=float, default=None)
    parser.add_argument('--expected-score',    type=float, default=None)
    parser.add_argument('--expected-tier',     type=str,   default=None)
    parser.add_argument('--expected-subgenre', type=str,   default=None)
    args = parser.parse_args()

    head(f"SL TEST HARNESS — {args.title}")
    info(f"Image:        {args.image}")
    info(f"Genre:        {args.genre}")
    info(f"Sub-genre:    {args.sub_genre or '(auto-detect)'}")
    info(f"Photographer: {args.photographer}")
    info(f"Mode:         {'DRY RUN — no API call' if args.dry_run else 'LIVE — hitting API'}")

    # ── Import engine ──────────────────────────────────────────────────────────
    sub("Loading engine modules")
    try:
        import auto_score as _as
        from engine.scoring import calculate_score, GENRE_WEIGHTS, get_effective_genre
        ok("auto_score imported")
        ok("engine.scoring imported")
    except ImportError as e:
        fail(f"Import error: {e}")
        fail("Run from /home/claude with scoring.py and engine/ present")
        sys.exit(1)

    # ── Validate image ─────────────────────────────────────────────────────────
    sub("Image validation")
    if not os.path.exists(args.image):
        fail(f"Image not found: {args.image}")
        sys.exit(1)
    ok(f"Image found: {args.image}")

    # ── Prompt pre-flight — show what WILL be sent ─────────────────────────────
    sub("Prompt pre-flight — genre_context and SYSTEM_BRIEF checks")

    from auto_score import (
        SYSTEM_BRIEF, get_genre_context, get_effective_genre as _geg,
        SCORE_PROMPT
    )
    from engine.scoring import VALID_SUBGENRES

    # Simulate sub-genre routing (without vision call) using filed sub-genre
    preflight_subgenre = args.sub_genre
    # Use effective genre for context lookup — mirrors what auto_score() does
    _preflight_eff_genre = get_effective_genre(args.genre, preflight_subgenre)
    gc = get_genre_context(args.genre, sub_genre=preflight_subgenre)

    # Check SYSTEM_BRIEF for key tokens
    sb_checks = [
        ('MINIMALIST AND SILHOUETTE EXCEPTION', 'STEP 0 minimalist exception'),
        ('creative_minimalist', 'creative_minimalist in STEP 0'),
        ('NEVER below 7.0 for a cleanly executed minimalist', 'DoD floor ≥ 7.0'),
        ('HARD FLOOR', 'Crisis disruption hard floor'),
    ]
    for token, label in sb_checks:
        if token in SYSTEM_BRIEF:
            ok(f"SYSTEM_BRIEF: {label}")
        else:
            warn(f"SYSTEM_BRIEF missing: {label}")

    # Check genre_context for relevant rubric
    gc_checks = []
    if preflight_subgenre == 'creative_minimalist' or 'creative_minimalist' in (preflight_subgenre or ''):
        gc_checks = [
            ('compositional DECISION is the difficulty', 'minimalist DoD decision rule'),
            ('AWARD-LEVEL CALIBRATION', 'award-level calibration block'),
            ('8.5–9.5', 'Disruption range 8.5-9.5'),
        ]
    elif 'doc_crisis' in (preflight_subgenre or ''):
        gc_checks = [
            ('HARD FLOOR', 'crisis disruption hard floor in rubric'),
            ('AWARD-LEVEL CALIBRATION', 'award-level calibration block'),
            ('slingshot', 'slingshot example'),
        ]
    for token, label in gc_checks:
        if token in gc:
            ok(f"genre_context: {label}")
        else:
            warn(f"genre_context missing: {label}")

    if args.dry_run:
        show_system_brief_summary(SYSTEM_BRIEF)
        show_genre_context_summary(gc)

    # ── Vision-only mode ───────────────────────────────────────────────────────
    if args.vision_only:
        sub("Running vision pass only")
        orig_vision = _patch_vision()
        try:
            img_data, media_type = _as.encode_image(args.image)
            vision = _as.vision_analyse(img_data, media_type, args.title, args.subject)
            sub("Vision result")
            for k, v in vision.items():
                print(f"    {GRY}{k}: {v}{RST}")
        finally:
            _unpatch_vision(orig_vision)
        print()
        sys.exit(0)

    # ── Score ──────────────────────────────────────────────────────────────────
    sub("Running auto_score()" + (" [DRY RUN]" if args.dry_run else ""))
    orig_httpx  = _patch_httpx(args.dry_run)
    orig_vision = _patch_vision()
    # In dry-run, also stub out vision_analyse so no API key is needed
    if args.dry_run:
        import auto_score as _as2
        _real_vision = _as2.vision_analyse
        def _stub_vision(img_data, media_type, title, subject):
            _vision_captured['result'] = {
                'summary': 'DRY RUN — no vision call',
                'suggested_subgenre': args.sub_genre,
                'suggested_subgenre_reason': 'dry-run: using filed sub-genre',
                'subject_types': [], 'composition_type': 'unknown',
            }
            return _vision_captured['result']
        _as2.vision_analyse = _stub_vision
    t0 = time.time()

    try:
        result = _as.auto_score(
            image_path   = args.image,
            genre        = args.genre,
            title        = args.title,
            photographer = args.photographer,
            subject      = args.subject,
            location     = args.location,
            sub_genre    = args.sub_genre,
        )
    except ValueError as e:
        if args.dry_run and 'ANTHROPIC_API_KEY' in str(e):
            warn("No API key in this environment — prompt inspection complete, scores skipped")
            print()
            sys.exit(0)
        fail(f"auto_score() raised: {e}")
        sys.exit(1)
    except Exception as e:
        fail(f"auto_score() raised: {e}")
        sys.exit(1)
    finally:
        _unpatch_httpx(orig_httpx)
        _unpatch_vision(orig_vision)
        if args.dry_run:
            _as2.vision_analyse = _real_vision

    elapsed = time.time() - t0

    # ── Show prompts (dry-run or always for key sections) ──────────────────────
    if _captured:
        sub("Payload inspection")
        info(f"Model:         {_captured.get('model','?')}")
        info(f"System brief:  {len(_captured.get('system',''))} chars")
        info(f"Score prompt:  {len(_captured.get('prompt',''))} chars")
        if args.dry_run:
            show_score_prompt_summary(_captured.get('prompt', ''))

    # ── Vision result ──────────────────────────────────────────────────────────
    if _vision_captured.get('result'):
        sub("Vision pass result")
        v = _vision_captured['result']
        detected_sg = v.get('suggested_subgenre', '—')
        detected_reason = v.get('suggested_subgenre_reason', '')[:80]
        info(f"Detected sub-genre: {BOLD}{detected_sg}{RST}")
        if detected_reason:
            info(f"Reason:             {detected_reason}")
        for key in ['summary', 'subject_types', 'composition_type', 'species_id']:
            val = v.get(key)
            if val:
                info(f"{key}: {val}")

    # ── Routing ────────────────────────────────────────────────────────────────
    sub("Routing")
    eff_sg    = result.get('_effective_subgenre', '—')
    phot_sg   = result.get('_photographer_subgenre', '—')
    overridden = result.get('_subgenre_overridden', False)
    eff_genre = result.get('_effective_genre', args.genre)

    info(f"Photographer filed:    {phot_sg}")
    info(f"Engine detected:       {BOLD}{eff_sg}{RST}  {'← OVERRIDDEN' if overridden else ''}")
    info(f"Effective genre:       {eff_genre}{'  ← WEIGHT OVERRIDE' if eff_genre != args.genre else ''}")

    if args.expected_subgenre:
        assert_eq("Sub-genre routing", eff_sg, args.expected_subgenre)

    # ── Scores ─────────────────────────────────────────────────────────────────
    sub("Dimension scores")
    dims = [
        ('dod',       'DoD        '),
        ('disruption','Disruption '),
        ('dm',        'DM         '),
        ('wonder',    'Wonder     '),
        ('aq',        'AQ         '),
    ]
    for key, label in dims:
        val = result.get(key)
        bar = '█' * int((val or 0)) + '░' * (10 - int((val or 0)))
        print(f"    {label}  {BOLD}{val:>5.2f}{RST}  {GRY}{bar}{RST}")

    final_score = result.get('score')
    tier        = result.get('tier', '—')
    soul_bonus  = result.get('soul_bonus', False)
    exc_bonus   = result.get('excellence_bonus', False)

    print()
    print(f"    {'Final score':12}  {BOLD}{GRN if (final_score or 0) >= 9.0 else YLW}{final_score:>5.2f}{RST}  "
          f"{BOLD}{tier}{RST}"
          f"{'  ✦ SOUL BONUS' if soul_bonus else ''}"
          f"{'  ★ EXCELLENCE BONUS' if exc_bonus else ''}")
    print(f"    {'Elapsed':12}  {elapsed:.1f}s")

    # ── Assertions ─────────────────────────────────────────────────────────────
    has_assertions = any([
        args.expected_dod, args.expected_dis, args.expected_dm,
        args.expected_wonder, args.expected_aq, args.expected_score, args.expected_tier
    ])
    if has_assertions:
        sub("Assertions")
        if args.expected_dod    is not None: assert_gte("DoD",        result.get('dod'),        args.expected_dod)
        if args.expected_dis    is not None: assert_gte("Disruption", result.get('disruption'), args.expected_dis)
        if args.expected_dm     is not None: assert_gte("DM",         result.get('dm'),         args.expected_dm)
        if args.expected_wonder is not None: assert_gte("Wonder",     result.get('wonder'),     args.expected_wonder)
        if args.expected_aq     is not None: assert_gte("AQ",         result.get('aq'),         args.expected_aq)
        if args.expected_score  is not None: assert_gte("Score",      result.get('score'),      args.expected_score)
        if args.expected_tier   is not None: assert_eq( "Tier",       result.get('tier',''),    args.expected_tier)

    # ── Apex verdict ───────────────────────────────────────────────────────────
    sub("Apex verdict")
    verdict = result.get('apex_verdict', '')
    print(f"    {GRY}{verdict[:200]}{RST}")

    # ── Score reconstruction check ─────────────────────────────────────────────
    # Re-run calculate_score locally and compare — catches weight bugs
    sub("Score reconstruction")
    try:
        reconstructed = calculate_score(
            eff_genre,
            result.get('dod', 0),
            result.get('disruption', 0),
            result.get('dm', 0),
            result.get('wonder', 0),
            result.get('aq', 0),
        )
        delta = abs(reconstructed - (final_score or 0))
        if delta < 0.15:
            ok(f"Reconstructed: {reconstructed:.2f}  (delta {delta:.3f} — within tolerance)")
        else:
            warn(f"Reconstructed: {reconstructed:.2f}  (delta {delta:.3f} — weight mismatch?)")
    except Exception as e:
        warn(f"Score reconstruction failed: {e}")

    # ── Summary ────────────────────────────────────────────────────────────────
    sub("Summary")
    if args.dry_run:
        warn("DRY RUN — no API call made, scores are 0.00 placeholders")
    elif FAIL_COUNT > 0:
        fail(f"{FAIL_COUNT} assertion(s) failed — rubric or routing fix needed")
        print()
        sys.exit(1)
    elif has_assertions:
        ok(f"All {PASS_COUNT} assertion(s) passed")
    else:
        info("No assertions specified — add --expected-score, --expected-dod etc. to gate on thresholds")
    print()


if __name__ == '__main__':
    main()
