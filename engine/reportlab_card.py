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
NAVY      = HexColor('#0F2A22')
NAVY_DK   = HexColor('#0A1A12')
NAVY_ROW  = HexColor('#122E26')
GOLD      = HexColor('#D6A428')
GOLD_DK   = HexColor('#A37B2C')
CREAM     = HexColor('#F6F2E9')
DARK      = HexColor('#1A1A18')
DARK2     = HexColor('#3A3A38')
BORDER    = HexColor('#D0CAB8')
MUTED     = HexColor('#888880')
BAND_BD   = HexColor('#2A2A28')
DIM_LBL   = HexColor('#BBBBBB')
ROW_SEP   = HexColor('#1E3830')

# Pastel where-to-shoot background
WHERE_BG      = HexColor('#E8F2EC')   # pale sage
WHERE_TXT     = HexColor('#1A3A2A')   # dark green text
WHERE_LBL     = HexColor('#2A6A3A')   # section label
WHERE_DAYS_BG = HexColor('#D4EAD8')   # slightly deeper for days row
WHERE_DAYS_TXT= HexColor('#1A3A2A')

# Row accent colours — left bar + eyebrow
ROW_ACCENTS = [
    HexColor('#D6A428'),   # gold   — Photographer's Advice
    HexColor('#5A9ABF'),   # blue   — What You Controlled
    HexColor('#5A9A6A'),   # green  — What to Watch Next
    HexColor('#BF7A9A'),   # rose   — Keep This in Mind
]

# Pastel row backgrounds (alternating)
ROW_BG_ALT = HexColor('#162A22')   # slightly lighter navy for odd rows

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
        lines = lines[:max_lines - 1] + [lines[max_lines - 1].rstrip() + '…']
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
    _set(c, 6, bold=False, color=HexColor('#555555'))
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
def _draw_page1(c, data):
    HEADER_H = 8  * mm
    FOOTER_H = 7  * mm
    PHOTO_H  = PH * 0.40

    photo_bot = PH - HEADER_H - PHOTO_H
    band_top  = photo_bot

    _draw_header(c, 'SHUTTER LEAGUE',
                 'APEX DDI ENGINE  ·  FULL EVALUATION', PH)

    # Photo
    c.setFillColor(HexColor('#111111'))
    c.rect(0, photo_bot, PW, PHOTO_H, fill=1, stroke=0)
    img = _fetch_photo(data.get('photo_url'))
    if img:
        try:
            iw, ih = img.getSize()
            scale  = max(PW/iw, PHOTO_H/ih)
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

    # Navy band
    c.setFillColor(NAVY)
    c.rect(0, FOOTER_H, PW, band_top - FOOTER_H, fill=1, stroke=0)

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()

    # Score
    _set(c, 56, bold=True, color=white)
    score_w = c.stringWidth(score_str, _font(True), 56)
    sx = PAD
    sy = band_top - 18*mm
    c.drawString(sx, sy, score_str)

    _set(c, 11, bold=True, color=GOLD)
    c.drawString(sx, sy - 7*mm, tier_str)
    _draw_tier_dots(c, data.get('tier',''), sx, sy - 11.5*mm)

    # Meta
    mx = sx + score_w + 8*mm
    my = sy + 2*mm
    if credit:
        _set(c, 9, bold=True, color=GOLD)
        c.drawString(mx, my, f"PHOTOGRAPHY BY :  {credit.upper()}")
        my -= 6*mm
    meta = '  ·  '.join(filter(None,[data.get('genre',''),
                                      data.get('format',''),
                                      data.get('location','')]))
    if meta:
        _set(c, 8, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(mx, my, meta)
        my -= 5*mm
    aff = data.get('affective_state','')
    if aff:
        _set(c, 8, bold=False, color=GOLD_DK)
        c.drawString(mx, my, f"Affective State: {aff}")

    # Dimensions
    sep_y = sy - 14*mm
    c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
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
                c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
                c.line(cx, dy, cx, dy - 16*mm)
            for j, lbl in enumerate([dim['l1'], dim['l2']]):
                _set(c, 7.5, bold=False, color=DIM_LBL)
                lx = cx + dw/2 - c.stringWidth(lbl, _font(False), 7.5)/2
                c.drawString(lx, dy - j*4.5*mm, lbl)
            sc   = f"{dim['score']:.1f}"
            scol = GOLD if dim['score']==max_sc else white
            _set(c, 20, bold=True, color=scol)
            sw = c.stringWidth(sc, _font(True), 20)
            c.drawString(cx + dw/2 - sw/2, dy - 11.5*mm, sc)

    # Opening bold
    wso = _clean(data.get('wso',''))
    wso_y = sep_y - 18*mm
    if wso:
        c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
        c.line(PAD, wso_y + 1.5*mm, PW-PAD, wso_y + 1.5*mm)
        wso_end = _draw_text_block(
            c, wso, PAD, wso_y - 2*mm, PW - 2*PAD,
            11, bold=True, color=white, line_height=6*mm, max_lines=3)
    else:
        wso_end = wso_y - 2*mm

    # Four evaluation rows
    row_data = [
        ("The Photographer's Advice", data.get('c1_body','')),
        ("What You Controlled",       data.get('c2_body','')),
        ("What to Watch Next",        data.get('c3_body','')),
        ("Keep This in Mind",         data.get('c4_body','')),
    ]

    BODY_FS   = 11
    LABEL_FS  = 9
    BODY_LH   = 6*mm
    LABEL_H   = 5.5*mm
    ROW_PAD   = 3.5*mm
    MAX_LINES = 3      # 3 lines at 11pt fits cleanly with 4 rows

    ry = wso_end - 5*mm

    for i, (label, raw) in enumerate(row_data):
        body   = _clean(raw)
        if not body:
            continue
        accent = ROW_ACCENTS[i]
        bh     = _block_height(body, PW-2*PAD-8*mm, BODY_FS,
                               line_height=BODY_LH, max_lines=MAX_LINES)
        row_h  = ROW_PAD + LABEL_H + bh + ROW_PAD

        # Alternating bg
        if i % 2 == 1:
            c.setFillColor(ROW_BG_ALT)
            c.rect(0, ry - row_h, PW, row_h, fill=1, stroke=0)

        # Accent left bar
        c.setFillColor(accent)
        c.rect(PAD, ry - row_h + 2.5*mm, 3, row_h - 5*mm, fill=1, stroke=0)

        # Label
        _set(c, LABEL_FS, bold=True, color=accent)
        c.drawString(PAD + 6*mm, ry - ROW_PAD - LABEL_H + 1.5*mm, label.upper())

        # Body
        _draw_text_block(
            c, body,
            PAD + 6*mm, ry - ROW_PAD - LABEL_H - 1.5*mm,
            PW - 2*PAD - 10*mm,
            BODY_FS, bold=False, color=HexColor('#DDDDDD'),
            line_height=BODY_LH, max_lines=MAX_LINES)

        # Separator
        ry -= row_h
        if i < 3:
            c.setStrokeColor(ROW_SEP); c.setLineWidth(0.4)
            c.line(PAD + 6*mm, ry, PW - PAD, ry)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 2
# ════════════════════════════════════════════════════════════════════════
def _draw_page2(c, data):
    HEADER_H = 8 * mm
    FOOTER_H = 7 * mm
    PAGE_TOP = PH - HEADER_H

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset','Untitled')

    _draw_header(c, f"FULL EVALUATION  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, PH-HEADER_H-FOOTER_H, fill=1, stroke=0)

    ey = PAGE_TOP - 5*mm

    # ── Edit Guide ──
    edit_base     = _clean(data.get('edit_base',''))
    edit_creative = _clean(data.get('edit_creative',''))

    if edit_base or edit_creative:
        _set(c, 8, bold=True, color=MUTED)
        c.drawString(PAD, ey, 'EDIT GUIDE')
        ey -= 5*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.5)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)
        ey -= 3*mm

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
                                    11, bold=False, color=DARK2,
                                    line_height=6*mm, max_lines=10)

        if edit_creative:
            rx = PAD + half_w + 10*mm
            _set(c, 9, bold=True, color=HexColor('#2A6A3A'))
            c.drawString(rx, ey_r, 'CREATIVE EDIT')
            _set(c, 8, bold=False, color=MUTED)
            sx = rx + c.stringWidth('CREATIVE EDIT', _font(True), 9) + 3*mm
            c.drawString(sx, ey_r, '· Artistic. Heavy editing.')
            ey_r -= 6*mm
            ey_r = _draw_text_block(c, edit_creative, rx+2*mm, ey_r, half_w,
                                    11, bold=False, color=DARK2,
                                    line_height=6*mm, max_lines=10)

        ey = min(ey_l, ey_r) - 6*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)

    # ── Where to Shoot Next — pastel sage ──
    loc1      = _clean(data.get('mentor_location_1',''))
    loc2      = _clean(data.get('mentor_location_2',''))
    days_lang = data.get('days_since_language','')

    if loc1:
        half_w = (PW - 2*PAD - 10*mm) / 2
        l1_h   = _block_height(loc1, half_w, 11, line_height=6*mm)
        l2_h   = _block_height(loc2, half_w, 11, line_height=6*mm) if loc2 else 0
        dl_h   = 10*mm if days_lang else 0
        box_h  = 10*mm + max(l1_h, l2_h) + dl_h + 10*mm

        box_top = ey - 3*mm
        box_bot = box_top - box_h

        # Pastel sage background
        c.setFillColor(WHERE_BG)
        c.rect(PAD, box_bot, PW-2*PAD, box_h, fill=1, stroke=0)
        # Subtle border
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
                             11, bold=False, color=WHERE_TXT,
                             line_height=6*mm, max_lines=14)
            _draw_text_block(c, loc2, PAD+5*mm+half_w+10*mm, iy, half_w,
                             11, bold=False, color=WHERE_TXT,
                             line_height=6*mm, max_lines=14)
        else:
            _draw_text_block(c, loc1, PAD+5*mm, iy, PW-2*PAD-10*mm,
                             11, bold=False, color=WHERE_TXT,
                             line_height=6*mm, max_lines=10)

        if days_lang:
            # Slightly deeper pastel strip for days language
            c.setFillColor(WHERE_DAYS_BG)
            c.rect(PAD, box_bot, PW-2*PAD, dl_h, fill=1, stroke=0)
            _draw_text_block(c, days_lang, PAD+5*mm, box_bot + dl_h - 3*mm,
                             PW-2*PAD-10*mm,
                             11, bold=True, color=WHERE_DAYS_TXT,
                             line_height=6*mm, max_lines=2)

        ey = box_bot - 6*mm

    # ── HCB Quote ──
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
    """Two-page A4 portrait PDF. Pure Python, no system deps."""
    buf = io.BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Shutter League Evaluation — {data.get('asset','')}")
    c.setAuthor('Shutter League')
    _draw_page1(c, data)
    c.showPage()
    _draw_page2(c, data)
    c.showPage()
    c.save()
    return buf.getvalue()
