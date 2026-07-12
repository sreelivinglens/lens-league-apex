"""
Shutter League — Reportlab Scorecard PDF  Session 141
Two A4 portrait pages, pure Python, no system deps.

Page 1: Photo hero · Score band · Dimensions · Opening bold ·
        Four evaluation rows (full width, gold-labelled)
Page 2: Edit Guide · Where to Shoot Next · HCB quote

70yr rule: minimum 11pt body, 12pt preferred. Pastel backgrounds throughout.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
import io, textwrap, re, requests

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY      = HexColor('#D6EAF8')   # pastel sky blue (light bg)
NAVY_DK   = HexColor('#1A2A3A')   # dark footer
NAVY_ROW  = HexColor('#BFD9EE')   # slightly deeper pastel for alt rows
GOLD      = HexColor('#B8860B')   # dark gold — readable on light bg
GOLD_DK   = HexColor('#8B6508')
CREAM     = HexColor('#F6F2E9')
DARK      = HexColor('#1A1A18')
DARK2     = HexColor('#3A3A38')
BORDER    = HexColor('#D0CAB8')
MUTED     = HexColor('#555555')
BAND_BD   = HexColor('#A0BDD0')   # muted blue border
DIM_LBL   = HexColor('#334455')   # dark label text
ROW_SEP   = HexColor('#A0BDD0')

# Pastel sky blue gradient stops (light → very light)
GRAD_TOP  = HexColor('#EBF5FB')   # near-white sky — top of page (lightest)
GRAD_MID  = HexColor('#D6EAF8')   # pastel sky blue
GRAD_BOT  = HexColor('#C2DCF0')   # medium pastel sky — bottom of page (slightly deeper)

# Pastel where-to-shoot background
WHERE_BG      = HexColor('#E8F2EC')
WHERE_TXT     = HexColor('#1A3A2A')
WHERE_LBL     = HexColor('#2A6A3A')
WHERE_DAYS_BG = HexColor('#D4EAD8')
WHERE_DAYS_TXT= HexColor('#1A3A2A')

# Row accent colours — left bar + eyebrow (dark enough for light bg)
ROW_ACCENTS = [
    HexColor('#B8860B'),   # dark gold  — Photographer's Advice
    HexColor('#1A6A9A'),   # dark blue  — What You Controlled
    HexColor('#1A6A3A'),   # dark green — What to Watch Next
    HexColor('#8A3A6A'),   # dark rose  — Keep This in Mind
]

# Alt row background — slightly deeper pastel
ROW_BG_ALT = HexColor('#BFD9EE')

PW, PH = A4
PAD = 12 * mm

# ── Font helpers ──────────────────────────────────────────────────────────────
def _font(bold=False):
    return 'Helvetica-Bold' if bold else 'Helvetica'

def _set(c, size, bold=False, color=None):
    c.setFont(_font(bold), size)
    if color:
        c.setFillColor(color)

# ── Text cleaning ─────────────────────────────────────────────────────────────
def _clean(text):
    """
    Strip all audit JSON artifacts:
    - Truncated preview (text before first '…') — drop it
    - '■' bullet markers — replace with newline
    - **bold** markdown
    """
    if not text:
        return ''
    # Drop truncated preview block (everything up to and including '…')
    ell = text.find('…')
    if 0 < ell < 250:
        text = text[ell + 1:].lstrip('\n ')
    # Strip remaining ■ bullets (some fields have no truncation prefix)
    text = text.replace('■', ' ')
    # Collapse whitespace runs
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    # Strip **bold** markdown
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text.strip()

def _first_sentence(text):
    text = _clean(text)
    if not text:
        return ''
    for sep in ['. ', '.\n', '! ', '? ']:
        idx = text.find(sep)
        if 0 < idx < 120:
            return text[:idx + 1]
    return text[:100].rstrip() + ('…' if len(text) > 100 else '')

def _wrap(text, width_pts, font_size, bold=False):
    if not text:
        return []
    avg_char = font_size * 0.52
    chars    = max(1, int(width_pts / avg_char))
    lines    = []
    for para in text.split('\n'):
        para = para.strip()
        if para:
            lines.extend(textwrap.wrap(para, chars) or [])
    return lines or []

def _draw_text_block(c, text, x, y, width, font_size, bold=False,
                     color=None, line_height=None, max_lines=None):
    if not text:
        return y
    if color:
        c.setFillColor(color)
    c.setFont(_font(bold), font_size)
    lh    = line_height or (font_size * 1.55)
    lines = _wrap(text, width, font_size, bold)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    for line in lines:
        if y < 8 * mm:
            break
        c.drawString(x, y, line)
        y -= lh
    return y

def _block_height(text, width, font_size, bold=False,
                  line_height=None, max_lines=None):
    if not text:
        return 0
    lh    = line_height or (font_size * 1.55)
    lines = _wrap(text, width, font_size, bold)
    if max_lines:
        lines = lines[:max_lines]
    return len(lines) * lh

# ── Header / Footer ───────────────────────────────────────────────────────────
def _draw_header(c, left, right, y_top, h=8*mm):
    c.setFillColor(NAVY)
    c.rect(0, y_top - h, PW, h, fill=1, stroke=0)
    _set(c, 8, bold=True, color=GOLD)
    c.drawString(PAD, y_top - h + 2.5*mm, left)
    _set(c, 7, bold=False, color=HexColor('#AAAAAA'))
    c.drawRightString(PW - PAD, y_top - h + 2.5*mm, right)

def _draw_footer(c, stamp):
    h = 7 * mm
    c.setFillColor(NAVY_DK)
    c.rect(0, 0, PW, h, fill=1, stroke=0)
    _set(c, 6, bold=False, color=HexColor('#CCCCCC'))
    c.drawString(PAD, 2.5*mm,
                 'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.')
    _set(c, 7, bold=True, color=GOLD)
    c.drawRightString(PW - PAD, 2.5*mm, stamp)

# ── Tier dots ─────────────────────────────────────────────────────────────────
TIER_ORDER = ['Rookie','Shooter','Contender','Craftsman',
              'Maverick','Master','Grandmaster','Legend']

def _draw_tier_dots(c, tier, x, y, dot_w=9, dot_h=3.5, gap=3):
    idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    for i in range(8):
        c.setFillColor(GOLD if i <= idx else BAND_BD)
        c.rect(x + i*(dot_w+gap), y, dot_w, dot_h, fill=1, stroke=0)

# ── Photo fetch ───────────────────────────────────────────────────────────────
def _fetch_photo(url):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return ImageReader(io.BytesIO(r.content))
    except Exception as e:
        print(f'[reportlab_card] photo fetch: {e}')
        return None

# ════════════════════════════════════════════════════════════════════════
#  PAGE 1
# ════════════════════════════════════════════════════════════════════════
def _draw_gradient_bg(c, x, y, w, h, color_top, color_bot, steps=60):
    """Simulate a vertical linear gradient with stacked thin rects."""
    step_h = h / steps
    r0, g0, b0 = color_top.red, color_top.green, color_top.blue
    r1, g1, b1 = color_bot.red, color_bot.green, color_bot.blue
    for i in range(steps):
        t  = i / (steps - 1)
        rc = r0 + (r1 - r0) * t
        gc = g0 + (g1 - g0) * t
        bc = b0 + (b1 - b0) * t
        c.setFillColor(Color(rc, gc, bc))
        c.rect(x, y + i * step_h, w, step_h + 0.5, fill=1, stroke=0)


def _draw_page1(c, data):
    HEADER_H = 8  * mm
    FOOTER_H = 7  * mm
    PHOTO_H  = PH * 0.32

    photo_bot = PH - HEADER_H - PHOTO_H
    band_top  = photo_bot

    _draw_header(c, 'SHUTTER LEAGUE',
                 'APEX DDI ENGINE  ·  FULL EVALUATION', PH)

    # ── Photo ──
    c.setFillColor(HexColor('#111111'))
    c.rect(0, photo_bot, PW, PHOTO_H, fill=1, stroke=0)
    img = _fetch_photo(data.get('photo_url'))
    if img:
        try:
            iw, ih = img.getSize()
            scale  = min(PW/iw, PHOTO_H/ih)   # contain — full image, no crop
            nw, nh = iw*scale, ih*scale
            ox = (PW-nw)/2
            oy = photo_bot + (PHOTO_H-nh)/2
            c.drawImage(img, ox, oy, nw, nh, mask='auto')
        except Exception:
            pass

    credit = data.get('credit','')
    if credit:
        parts   = credit.strip().split()
        display = f"\u00a9 {parts[0]} {parts[-1][0]}" if len(parts)>=2 else f"\u00a9 {credit}"
        _set(c, 7, bold=False, color=HexColor('#AAAAAA'))
        c.drawRightString(PW - 4*mm, photo_bot + 3*mm, display)

    # ── Cream background below photo (matches page 2) ──
    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, band_top - FOOTER_H, fill=1, stroke=0)

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()

    # ── Score block ──
    sx = PAD
    sy = band_top - 22*mm

    _set(c, 56, bold=True, color=DARK)
    score_w = c.stringWidth(score_str, _font(True), 56)
    c.drawString(sx, sy, score_str)

    _set(c, 11, bold=True, color=GOLD)
    c.drawString(sx, sy - 8*mm, tier_str)
    _draw_tier_dots(c, data.get('tier',''), sx, sy - 13*mm)

    # ── Meta block ──
    mx = sx + score_w + 10*mm
    my = sy + 4*mm

    credit = data.get('credit','')
    if credit:
        _set(c, 9, bold=True, color=GOLD_DK)
        c.drawString(mx, my, f"PHOTOGRAPHY BY :  {credit.upper()}")
        my -= 5*mm
        c.setStrokeColor(GOLD_DK)
        c.setLineWidth(0.4)
        c.line(mx, my + 0.5*mm, mx + 80*mm, my + 0.5*mm)
        my -= 5*mm

    meta = '  ·  '.join(filter(None, [data.get('genre',''),
                                       data.get('format',''),
                                       data.get('location','')]))
    if meta:
        _set(c, 8, bold=False, color=DARK2)
        c.drawString(mx, my, meta)
        my -= 6*mm

    aff = data.get('affective_state','')
    if aff:
        _set(c, 8, bold=False, color=GOLD_DK)
        c.drawString(mx, my, f"Affective State: {aff}")

    # ── Dimensions ──
    sep_y = sy - 19*mm
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW-PAD, sep_y)

    dims = data.get('dim_breakdown', [])
    if dims:
        n      = len(dims)
        dw     = (PW - 2*PAD) / n
        max_sc = max(d['score'] for d in dims)
        dy     = sep_y - 3*mm
        for i, dim in enumerate(dims):
            cx = PAD + i*dw
            if i > 0:
                c.setStrokeColor(BORDER)
                c.setLineWidth(0.5)
                c.line(cx, dy, cx, dy - 16*mm)
            for j, lbl in enumerate([dim['l1'], dim['l2']]):
                _set(c, 7.5, bold=False, color=MUTED)
                lx = cx + dw/2 - c.stringWidth(lbl, _font(False), 7.5)/2
                c.drawString(lx, dy - j*4.5*mm, lbl)
            sc   = f"{dim['score']:.1f}"
            scol = GOLD_DK if dim['score']==max_sc else DARK
            _set(c, 20, bold=True, color=scol)
            sw = c.stringWidth(sc, _font(True), 20)
            c.drawString(cx + dw/2 - sw/2, dy - 11.5*mm, sc)

    # ── Opening bold ──
    wso   = _clean(data.get('wso',''))
    wso_y = sep_y - 22*mm
    wso_end = wso_y - 3*mm
    if wso:
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.5)
        c.line(PAD, wso_y + 2*mm, PW-PAD, wso_y + 2*mm)
        wso_end = _draw_text_block(
            c, wso, PAD, wso_y - 3*mm, PW - 2*PAD,
            12, bold=True, color=DARK, line_height=7*mm)

    # ── The Photographer's Advice — row 1 on page 1 ──
    c1_body = _clean(data.get('c1_body',''))
    if c1_body:
        accent  = ROW_ACCENTS[0]
        BODY_FS = 11
        BODY_LH = 6*mm
        LABEL_H = 5.5*mm
        ROW_PAD = 5*mm
        LABEL_GAP = 4*mm
        bh    = _block_height(c1_body, PW-2*PAD-8*mm, BODY_FS, line_height=BODY_LH)
        row_h = ROW_PAD + LABEL_H + LABEL_GAP + bh + ROW_PAD
        ry    = wso_end - 4*mm

        c.setStrokeColor(BORDER); c.setLineWidth(0.5)
        c.line(PAD, ry + 1*mm, PW-PAD, ry + 1*mm)

        c.setFillColor(accent)
        c.rect(PAD, ry - row_h + 3*mm, 3, row_h - 6*mm, fill=1, stroke=0)

        _set(c, 9, bold=True, color=accent)
        c.drawString(PAD + 6*mm, ry - ROW_PAD - LABEL_H + 1.5*mm,
                     "THE PHOTOGRAPHER'S ADVICE")

        _draw_text_block(
            c, c1_body, PAD + 6*mm, ry - ROW_PAD - LABEL_H - LABEL_GAP,
            PW - 2*PAD - 10*mm,
            BODY_FS, bold=False, color=DARK, line_height=BODY_LH)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 2
# ════════════════════════════════════════════════════════════════════════
def _draw_page2(c, data):
    HEADER_H = 8 * mm
    FOOTER_H = 7 * mm
    PAGE_TOP  = PH - HEADER_H

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset','Untitled')

    _draw_header(c, f"FULL EVALUATION  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, PH-HEADER_H-FOOTER_H, fill=1, stroke=0)

    ey = PAGE_TOP - 5*mm

    # ── Evaluation rows 2–4 ──────────────────────────────────────────────────
    row_data = [
        ("What You Controlled",  data.get('c2_body','')),
        ("What to Watch Next",   data.get('c3_body','')),
        ("Keep This in Mind",    data.get('c4_body','')),
    ]

    BODY_FS   = 11
    LABEL_FS  = 9
    BODY_LH   = 6*mm
    LABEL_H   = 5.5*mm
    ROW_PAD   = 5*mm
    LABEL_GAP = 4*mm

    for i, (label, raw) in enumerate(row_data):
        body = _clean(raw)
        if not body:
            continue
        accent = ROW_ACCENTS[i]
        bh     = _block_height(body, PW-2*PAD-8*mm, BODY_FS, line_height=BODY_LH)
        row_h  = ROW_PAD + LABEL_H + LABEL_GAP + bh + ROW_PAD

        if i % 2 == 1:
            c.setFillColor(HexColor('#EEEAE0'))
            c.rect(0, ey - row_h, PW, row_h, fill=1, stroke=0)

        c.setFillColor(accent)
        c.rect(PAD, ey - row_h + 3*mm, 3, row_h - 6*mm, fill=1, stroke=0)

        _set(c, LABEL_FS, bold=True, color=accent)
        c.drawString(PAD + 6*mm, ey - ROW_PAD - LABEL_H + 1.5*mm, label.upper())

        _draw_text_block(
            c, body, PAD + 6*mm, ey - ROW_PAD - LABEL_H - LABEL_GAP,
            PW - 2*PAD - 10*mm,
            BODY_FS, bold=False, color=DARK, line_height=BODY_LH)

        ey -= row_h
        if i < 3:
            c.setStrokeColor(BORDER); c.setLineWidth(0.4)
            c.line(PAD + 6*mm, ey, PW - PAD, ey)

    ey -= 6*mm

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 3
# ════════════════════════════════════════════════════════════════════════
def _draw_page3(c, data):
    HEADER_H = 8 * mm
    FOOTER_H = 7 * mm
    PAGE_TOP  = PH - HEADER_H

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset','Untitled')

    _draw_header(c, f"EDIT GUIDE  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, PH-HEADER_H-FOOTER_H, fill=1, stroke=0)

    ey = PAGE_TOP - 5*mm

    # ── Edit Guide ───────────────────────────────────────────────────────────
    edit_base     = _clean(data.get('edit_base',''))
    edit_creative = _clean(data.get('edit_creative',''))

    if edit_base or edit_creative:
        _set(c, 8, bold=True, color=MUTED)
        c.drawString(PAD, ey, 'EDIT GUIDE')
        ey -= 5*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.5)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)
        ey -= 4*mm

        half_w = (PW - 2*PAD - 10*mm) / 2
        ey_l = ey_r = ey

        if edit_base:
            _set(c, 9, bold=True, color=GOLD_DK)
            c.drawString(PAD, ey_l, 'STANDARD EDIT')
            _set(c, 8, bold=False, color=MUTED)
            sx = PAD + c.stringWidth('STANDARD EDIT', _font(True), 9) + 3*mm
            c.drawString(sx, ey_l, '· Balanced. Light editing.')
            ey_l -= 6*mm
            ey_l = _draw_text_block(c, edit_base, PAD+2*mm, ey_l, half_w,
                                    11, bold=False, color=DARK2, line_height=6*mm)

        if edit_creative:
            rx = PAD + half_w + 10*mm
            _set(c, 9, bold=True, color=HexColor('#2A6A3A'))
            c.drawString(rx, ey_r, 'CREATIVE EDIT')
            _set(c, 8, bold=False, color=MUTED)
            sx = rx + c.stringWidth('CREATIVE EDIT', _font(True), 9) + 3*mm
            c.drawString(sx, ey_r, '· Artistic. Heavy editing.')
            ey_r -= 6*mm
            ey_r = _draw_text_block(c, edit_creative, rx+2*mm, ey_r, half_w,
                                    11, bold=False, color=DARK2, line_height=6*mm)

        ey = min(ey_l, ey_r) - 6*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)

    # ── Where to Shoot Next ───────────────────────────────────────────────────
    loc1 = _clean(data.get('mentor_location_1',''))
    loc2 = _clean(data.get('mentor_location_2',''))

    if loc1:
        half_w = (PW - 2*PAD - 10*mm) / 2
        l1_h   = _block_height(loc1, PW-2*PAD-10*mm if not loc2 else half_w,
                               11, line_height=6*mm)
        l2_h   = _block_height(loc2, half_w, 11, line_height=6*mm) if loc2 else 0
        box_h  = 10*mm + max(l1_h, l2_h) + 10*mm

        box_top = ey - 3*mm
        box_bot = box_top - box_h

        c.setFillColor(WHERE_BG)
        c.rect(PAD, box_bot, PW-2*PAD, box_h, fill=1, stroke=0)
        c.setStrokeColor(HexColor('#A8CEB0')); c.setLineWidth(0.5)
        c.rect(PAD, box_bot, PW-2*PAD, box_h, fill=0, stroke=1)

        iy = box_top - 6*mm
        _set(c, 8, bold=True, color=WHERE_LBL)
        c.drawString(PAD+5*mm, iy, 'WHERE TO SHOOT NEXT')
        iy -= 6*mm

        if loc2:
            _set(c, 9, bold=True, color=WHERE_LBL)
            c.drawString(PAD+5*mm, iy, 'NOW OPEN')
            c.drawString(PAD+5*mm+half_w+10*mm, iy, 'COMING UP')
            iy -= 5*mm
            _draw_text_block(c, loc1, PAD+5*mm, iy, half_w,
                             11, bold=False, color=WHERE_TXT, line_height=6*mm)
            _draw_text_block(c, loc2, PAD+5*mm+half_w+10*mm, iy, half_w,
                             11, bold=False, color=WHERE_TXT, line_height=6*mm)
        else:
            _draw_text_block(c, loc1, PAD+5*mm, iy, PW-2*PAD-10*mm,
                             11, bold=False, color=WHERE_TXT, line_height=6*mm)

        ey = box_bot - 6*mm

    # ── HCB Quote ─────────────────────────────────────────────────────────────
    if ey > FOOTER_H + 16*mm:
        quote = ('\u201cTo photograph is to hold one\u2019s breath when all '
                 'faculties converge to capture fleeting reality.\u201d')
        attr  = '\u2014 Henri Cartier-Bresson'
        c.setFillColor(GOLD)
        c.rect(PAD, ey - 14*mm, 2.5*mm, 12*mm, fill=1, stroke=0)
        _draw_text_block(c, quote, PAD+6*mm, ey-3*mm, PW-2*PAD-6*mm,
                         11, bold=False, color=MUTED, line_height=6*mm)
        _set(c, 9, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(PAD+6*mm, ey-13*mm, attr)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
def build_scorecard_pdf(data: dict) -> bytes:
    """Three-page A4 portrait PDF. Pure Python, no system deps."""
    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Shutter League Evaluation — {data.get('asset','')}")
    c.setAuthor('Shutter League')
    _draw_page1(c, data)
    c.showPage()
    _draw_page2(c, data)
    c.showPage()
    _draw_page3(c, data)
    c.showPage()
    c.save()
    return buf.getvalue()
