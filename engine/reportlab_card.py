"""
Shutter League — Reportlab Scorecard PDF  Session 141
Two A4 portrait pages, pure Python, no system deps.

Page 1: Photo hero · Score band · Dimensions · Opening bold ·
        Four evaluation rows (full width, gold-labelled)
Page 2: Edit Guide · Where to Shoot Next · HCB quote
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
import io, textwrap, re, requests

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY     = HexColor('#0F2A22')
NAVY_DK  = HexColor('#0A1A12')
NAVY_ROW = HexColor('#122E26')   # slightly lighter navy for alternating rows
GOLD     = HexColor('#D6A428')
GOLD_DK  = HexColor('#A37B2C')
GREEN    = HexColor('#1A3A2A')
GREEN_L  = HexColor('#7AAA8A')
GREEN_B  = HexColor('#2A5A3A')
CREAM    = HexColor('#F6F2E9')
DARK     = HexColor('#1A1A18')
DARK2    = HexColor('#3A3A38')
BORDER   = HexColor('#D0CAB8')
MUTED    = HexColor('#888880')
BAND_BD  = HexColor('#2A2A28')
DIM_LBL  = HexColor('#BBBBBB')
ROW_SEP  = HexColor('#1E3830')   # row divider on navy

# Row accent colours (eyebrow label colour per section)
ROW_ACCENTS = [
    HexColor('#D6A428'),   # gold   — Photographer's Advice
    HexColor('#7AAACB'),   # blue   — What You Controlled
    HexColor('#7AAA8A'),   # green  — What to Watch Next
    HexColor('#C87AA0'),   # rose   — Keep This in Mind
]

PW, PH = A4
PAD = 12 * mm

# ── Font helpers ──────────────────────────────────────────────────────────────
def _font(bold=False):
    return 'Helvetica-Bold' if bold else 'Helvetica'

def _set(c, size, bold=False, color=None):
    c.setFont(_font(bold), size)
    if color:
        c.setFillColor(color)

# ── Text utilities ────────────────────────────────────────────────────────────
def _clean(text):
    """Strip ■ bullets, truncated preview, **bold** markers."""
    if not text:
        return ''
    # Drop truncated preview — everything up to and including first '…'
    ell = text.find('…')
    if 0 < ell < 200:
        text = text[ell + 1:].lstrip('\n ')
    text = text.replace('■', '\n')
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text.strip()

def _first_sentence(text):
    text = _clean(text)
    if not text:
        return ''
    for sep in ['. ', '.\n', '! ', '? ']:
        idx = text.find(sep)
        if 0 < idx < 100:
            return text[:idx + 1]
    return text[:80].rstrip() + ('…' if len(text) > 80 else '')

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
    lh    = line_height or (font_size * 1.5)
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
    lh    = line_height or (font_size * 1.5)
    lines = _wrap(text, width, font_size, bold)
    if max_lines:
        lines = lines[:max_lines]
    return len(lines) * lh

# ── Header / Footer ───────────────────────────────────────────────────────────
def _draw_header(c, left, right, y_top, h=7*mm):
    c.setFillColor(NAVY)
    c.rect(0, y_top - h, PW, h, fill=1, stroke=0)
    _set(c, 7.5, bold=True, color=GOLD)
    c.drawString(PAD, y_top - h + 2.2*mm, left)
    _set(c, 6.5, bold=False, color=HexColor('#AAAAAA'))
    c.drawRightString(PW - PAD, y_top - h + 2.2*mm, right)

def _draw_footer(c, stamp):
    h = 6 * mm
    c.setFillColor(NAVY_DK)
    c.rect(0, 0, PW, h, fill=1, stroke=0)
    _set(c, 5.5, bold=False, color=HexColor('#555555'))
    c.drawString(PAD, 2*mm,
                 'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.')
    _set(c, 6.5, bold=True, color=GOLD)
    c.drawRightString(PW - PAD, 2*mm, stamp)

# ── Tier dots ─────────────────────────────────────────────────────────────────
TIER_ORDER = ['Rookie','Shooter','Contender','Craftsman',
              'Maverick','Master','Grandmaster','Legend']

def _draw_tier_dots(c, tier, x, y, dot_w=8, dot_h=3, gap=3):
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
    HEADER_H = 7  * mm
    FOOTER_H = 6  * mm
    PHOTO_H  = PH * 0.42          # photo takes 42% of page height

    photo_bot = PH - HEADER_H - PHOTO_H
    band_top  = photo_bot          # navy band from here down to footer

    _draw_header(c, 'SHUTTER LEAGUE',
                 'APEX DDI ENGINE  ·  FULL EVALUATION', PH)

    # ── Photo ──
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
        _set(c, 6.5, bold=False, color=HexColor('#AAAAAA'))
        c.drawRightString(PW - 4*mm, photo_bot + 3*mm, display)

    # ── Full navy band ──
    c.setFillColor(NAVY)
    c.rect(0, FOOTER_H, PW, band_top - FOOTER_H, fill=1, stroke=0)

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()

    # Score + tier
    _set(c, 52, bold=True, color=white)
    score_w = c.stringWidth(score_str, _font(True), 52)
    sx = PAD
    sy = band_top - 16*mm
    c.drawString(sx, sy, score_str)

    _set(c, 10, bold=True, color=GOLD)
    c.drawString(sx, sy - 6*mm, tier_str)
    _draw_tier_dots(c, data.get('tier',''), sx, sy - 10*mm)

    # Meta right of score
    mx = sx + score_w + 8*mm
    my = sy + 2*mm
    if credit:
        _set(c, 8, bold=True, color=GOLD)
        c.drawString(mx, my, f"PHOTOGRAPHY BY :  {credit.upper()}")
        my -= 5.5*mm
    meta = '  ·  '.join(filter(None,[data.get('genre',''),
                                      data.get('format',''),
                                      data.get('location','')]))
    if meta:
        _set(c, 7, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(mx, my, meta)
        my -= 4.5*mm
    aff = data.get('affective_state','')
    if aff:
        _set(c, 7, bold=False, color=GOLD_DK)
        c.drawString(mx, my, f"Affective State: {aff}")

    # Separator + dimensions
    sep_y = sy - 12*mm
    c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW-PAD, sep_y)

    dims = data.get('dim_breakdown', [])
    if dims:
        n      = len(dims)
        dw     = (PW - 2*PAD) / n
        max_sc = max(d['score'] for d in dims)
        dy     = sep_y - 2.5*mm
        for i, dim in enumerate(dims):
            cx = PAD + i*dw
            if i > 0:
                c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
                c.line(cx, dy, cx, dy - 14*mm)
            for j, lbl in enumerate([dim['l1'], dim['l2']]):
                _set(c, 6.5, bold=False, color=DIM_LBL)
                lx = cx + dw/2 - c.stringWidth(lbl, _font(False), 6.5)/2
                c.drawString(lx, dy - j*4*mm, lbl)
            sc   = f"{dim['score']:.1f}"
            scol = GOLD if dim['score']==max_sc else white
            _set(c, 18, bold=True, color=scol)
            sw = c.stringWidth(sc, _font(True), 18)
            c.drawString(cx + dw/2 - sw/2, dy - 10*mm, sc)

    # Opening bold (what_stood_out)
    wso = _clean(data.get('wso',''))
    wso_sep_y = sep_y - 16*mm
    if wso:
        c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
        c.line(PAD, wso_sep_y + 1*mm, PW-PAD, wso_sep_y + 1*mm)
        wso_end_y = _draw_text_block(
            c, wso, PAD, wso_sep_y - 2*mm, PW - 2*PAD,
            9, bold=True, color=white, line_height=5*mm, max_lines=4)
    else:
        wso_end_y = wso_sep_y - 2*mm

    # ── Four evaluation rows — full width on navy ──
    row_labels = [
        ("The Photographer's Advice", data.get('c1_body','')),
        ("What You Controlled",       data.get('c2_body','')),
        ("What to Watch Next",        data.get('c3_body','')),
        ("Keep This in Mind",         data.get('c4_body','')),
    ]
    MAX_BODY_LINES = 5
    BODY_FS        = 7.5
    LABEL_FS       = 7
    BODY_LH        = 4.5*mm
    LABEL_H        = 5*mm
    ROW_PAD        = 3*mm
    ROW_GAP        = 1.5*mm

    ry = wso_end_y - 6*mm

    for i, (label, raw) in enumerate(row_labels):
        body   = _clean(raw)
        if not body:
            continue
        accent = ROW_ACCENTS[i]
        row_h  = ROW_PAD + LABEL_H + _block_height(
                     body, PW-2*PAD-4*mm, BODY_FS,
                     line_height=BODY_LH, max_lines=MAX_BODY_LINES) + ROW_PAD

        # Alternate row background for visual separation
        if i % 2 == 1:
            c.setFillColor(NAVY_ROW)
            c.rect(PAD, ry - row_h, PW-2*PAD, row_h, fill=1, stroke=0)

        # Gold accent left bar (3pt wide)
        c.setFillColor(accent)
        c.rect(PAD, ry - row_h + 2*mm, 2.5, row_h - 4*mm, fill=1, stroke=0)

        # Label
        _set(c, LABEL_FS, bold=True, color=accent)
        c.drawString(PAD + 5*mm, ry - ROW_PAD - LABEL_H + 2*mm,
                     label.upper())

        # Body
        _draw_text_block(
            c, body,
            PAD + 5*mm, ry - ROW_PAD - LABEL_H - 1*mm,
            PW - 2*PAD - 8*mm,
            BODY_FS, bold=False, color=HexColor('#DDDDDD'),
            line_height=BODY_LH, max_lines=MAX_BODY_LINES)

        # Row separator
        ry -= row_h + ROW_GAP
        if i < len(row_labels)-1:
            c.setStrokeColor(ROW_SEP); c.setLineWidth(0.4)
            c.line(PAD, ry + ROW_GAP/2, PW-PAD, ry + ROW_GAP/2)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 2
# ════════════════════════════════════════════════════════════════════════
def _draw_page2(c, data):
    HEADER_H = 7 * mm
    FOOTER_H = 6 * mm
    PAGE_TOP = PH - HEADER_H

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset','Untitled')

    _draw_header(c, f"FULL EVALUATION  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, PH-HEADER_H-FOOTER_H, fill=1, stroke=0)

    ey = PAGE_TOP - 4*mm

    # ── Edit Guide ──
    edit_base     = _clean(data.get('edit_base',''))
    edit_creative = _clean(data.get('edit_creative',''))

    if edit_base or edit_creative:
        _set(c, 6, bold=True, color=MUTED)
        c.drawString(PAD, ey, 'EDIT GUIDE')
        ey -= 4*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.5)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)
        ey -= 2*mm

        half_w = (PW - 2*PAD - 8*mm) / 2
        ey_l = ey_r = ey

        if edit_base:
            _set(c, 7, bold=True, color=GOLD_DK)
            c.drawString(PAD, ey_l, 'STANDARD EDIT')
            _set(c, 6.5, bold=False, color=MUTED)
            sx = PAD + c.stringWidth('STANDARD EDIT', _font(True), 7) + 3*mm
            c.drawString(sx, ey_l, '· Balanced. Light editing.')
            ey_l -= 4.5*mm
            ey_l = _draw_text_block(c, edit_base, PAD+2*mm, ey_l, half_w,
                                    7, bold=False, color=DARK2,
                                    line_height=4*mm, max_lines=12)

        if edit_creative:
            rx = PAD + half_w + 8*mm
            _set(c, 7, bold=True, color=HexColor('#2A6A3A'))
            c.drawString(rx, ey_r, 'CREATIVE EDIT')
            _set(c, 6.5, bold=False, color=MUTED)
            sx = rx + c.stringWidth('CREATIVE EDIT', _font(True), 7) + 3*mm
            c.drawString(sx, ey_r, '· Artistic. Heavy editing.')
            ey_r -= 4.5*mm
            ey_r = _draw_text_block(c, edit_creative, rx+2*mm, ey_r, half_w,
                                    7, bold=False, color=DARK2,
                                    line_height=4*mm, max_lines=12)

        ey = min(ey_l, ey_r) - 5*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.4)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)

    # ── Where to Shoot Next ──
    loc1      = _clean(data.get('mentor_location_1',''))
    loc2      = _clean(data.get('mentor_location_2',''))
    days_lang = data.get('days_since_language','')

    if loc1:
        half_w = (PW - 2*PAD - 8*mm) / 2
        l1_h   = _block_height(loc1, half_w, 7, line_height=4*mm)
        l2_h   = _block_height(loc2, half_w, 7, line_height=4*mm) if loc2 else 0
        dl_h   = 7*mm if days_lang else 0
        box_h  = 8*mm + max(l1_h, l2_h) + dl_h + 8*mm

        box_top = ey - 2*mm
        box_bot = box_top - box_h
        c.setFillColor(GREEN)
        c.rect(PAD, box_bot, PW-2*PAD, box_h, fill=1, stroke=0)

        iy = box_top - 5*mm
        _set(c, 6, bold=True, color=GREEN_L)
        c.drawString(PAD+4*mm, iy, 'WHERE TO SHOOT NEXT')
        iy -= 5*mm

        if loc2:
            _set(c, 6.5, bold=True, color=GREEN_L)
            c.drawString(PAD+4*mm, iy, 'NOW OPEN')
            c.drawString(PAD+4*mm+half_w+8*mm, iy, 'COMING UP')
            iy -= 4*mm
            _draw_text_block(c, loc1, PAD+4*mm, iy, half_w,
                             7, bold=False, color=HexColor('#CCDDCC'),
                             line_height=4*mm, max_lines=14)
            _draw_text_block(c, loc2, PAD+4*mm+half_w+8*mm, iy, half_w,
                             7, bold=False, color=HexColor('#AABBAA'),
                             line_height=4*mm, max_lines=14)
        else:
            _draw_text_block(c, loc1, PAD+4*mm, iy, PW-2*PAD-8*mm,
                             7, bold=False, color=HexColor('#CCDDCC'),
                             line_height=4*mm, max_lines=10)

        if days_lang:
            c.setStrokeColor(GREEN_B); c.setLineWidth(0.5)
            c.line(PAD+4*mm, box_bot+dl_h+1*mm, PW-PAD-4*mm, box_bot+dl_h+1*mm)
            _set(c, 7, bold=True, color=GOLD)
            c.drawString(PAD+4*mm, box_bot+3*mm, days_lang[:130])

        ey = box_bot - 5*mm

    # ── HCB Quote ──
    if ey > FOOTER_H + 14*mm:
        quote = ('\u201cTo photograph is to hold one\u2019s breath when all '
                 'faculties converge to capture fleeting reality.\u201d')
        attr  = '\u2014 Henri Cartier-Bresson'
        c.setFillColor(GOLD)
        c.rect(PAD, ey - 12*mm, 2*mm, 10*mm, fill=1, stroke=0)
        _draw_text_block(c, quote, PAD+5*mm, ey-3*mm, PW-2*PAD-5*mm,
                         8, bold=False, color=MUTED, line_height=4.5*mm)
        _set(c, 7, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(PAD+5*mm, ey-11*mm, attr)

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
