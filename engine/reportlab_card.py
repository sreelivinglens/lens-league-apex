"""
Shutter League — Reportlab Scorecard PDF
Session 141 — pure Python, no system dependencies.
Two A4 portrait pages:
  Page 1: Photo hero + score band + dimensions + opening bold
  Page 2: Four pastel eval columns + edit guide + where to shoot + quote
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
import io, textwrap, re, requests

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY     = HexColor('#0F2A22')
NAVY_DK  = HexColor('#0A1A12')
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
DIM_LBL  = HexColor('#AAAAAA')

# Pastel card palettes — bg, accent line, eyebrow text, headline text
CARD_STYLES = [
    (HexColor('#FDF3E3'), HexColor('#854F0B'), HexColor('#854F0B'), DARK),   # amber
    (HexColor('#EAF0FA'), HexColor('#185FA5'), HexColor('#185FA5'), DARK),   # blue
    (HexColor('#EAF5EE'), HexColor('#3B6D11'), HexColor('#3B6D11'), DARK),   # forest
    (HexColor('#F5EAF0'), HexColor('#722440'), HexColor('#722440'), DARK),   # plum
]

# ── A4 ────────────────────────────────────────────────────────────────────────
PW, PH = A4
PAD = 12 * mm

# ── Text utilities ────────────────────────────────────────────────────────────
def _font(bold=False):
    return 'Helvetica-Bold' if bold else 'Helvetica'

def _set(c, size, bold=False, color=None):
    c.setFont(_font(bold), size)
    if color:
        c.setFillColor(color)

def _clean(text):
    """
    Strip audit JSON artifacts:
    - '■' bullet markers → newline (paragraph break)
    - The truncated preview sentence that appears before the full body
      (pattern: short sentence ending in '…' followed by the same content in full)
    - Double spaces, leading/trailing whitespace
    """
    if not text:
        return ''
    # Replace bullet markers with paragraph breaks
    text = text.replace('■', '\n')
    # Collapse multiple newlines
    text = re.sub(r'\n{2,}', '\n', text)
    # Remove truncated preview: a short line ending in '…' at the start
    # Pattern: "Some text truncated…\n Same text in full..." — drop the first short para
    paras = [p.strip() for p in text.split('\n') if p.strip()]
    if len(paras) >= 2 and paras[0].endswith('…') and len(paras[0]) < 120:
        paras = paras[1:]
    text = '\n'.join(paras)
    # Clean up **bold** markdown markers (not rendered by reportlab)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text.strip()

def _first_sentence(text):
    """First sentence as headline — from cleaned text."""
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
            lines.extend(textwrap.wrap(para, chars) or [''])
        # blank line between paragraphs
    return lines or ['']

def _draw_text_block(c, text, x, y, width, font_size, bold=False,
                     color=None, line_height=None, max_lines=None):
    if not text:
        return y
    if color:
        c.setFillColor(color)
    c.setFont(_font(bold), font_size)
    lh    = line_height or (font_size * 1.45)
    lines = _wrap(text, width, font_size, bold)
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        if y < 8 * mm:
            break
        c.drawString(x, y, line)
        y -= lh
    return y

def _block_height(text, width, font_size, bold=False, line_height=None, max_lines=None):
    if not text:
        return 0
    lh    = line_height or (font_size * 1.45)
    lines = _wrap(text, width, font_size, bold)
    if max_lines:
        lines = lines[:max_lines]
    return len(lines) * lh

# ── Gradient simulation — stacked rectangles light→white ──────────────────────
def _gradient_rect(c, x, y, w, h, color_hex, steps=12):
    """Simulate top-to-bottom gradient: pastel at top fading to near-white at bottom."""
    base = color_hex if not isinstance(color_hex, str) else HexColor(color_hex)
    br, bg, bb = base.red, base.green, base.blue
    step_h = h / steps
    for i in range(steps):
        t = i / (steps - 1)           # 0 = top (full colour), 1 = bottom (white)
        r = br + (1.0 - br) * t
        g = bg + (1.0 - bg) * t
        b = bb + (1.0 - bb) * t
        c.setFillColor(HexColor((r, g, b)))
        c.rect(x, y + (steps - 1 - i) * step_h, w, step_h + 0.5, fill=1, stroke=0)

# ── Header / Footer ───────────────────────────────────────────────────────────
def _draw_header(c, left, right, y_top, h=7*mm):
    c.setFillColor(NAVY)
    c.rect(0, y_top - h, PW, h, fill=1, stroke=0)
    _set(c, 7, bold=True, color=GOLD)
    c.drawString(PAD, y_top - h + 2.2*mm, left)
    _set(c, 6, bold=False, color=HexColor('#AAAAAA'))
    c.drawRightString(PW - PAD, y_top - h + 2.2*mm, right)

def _draw_footer(c, stamp):
    h = 6 * mm
    c.setFillColor(NAVY_DK)
    c.rect(0, 0, PW, h, fill=1, stroke=0)
    _set(c, 5, bold=False, color=HexColor('#555555'))
    c.drawString(PAD, 2*mm,
                 'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.')
    _set(c, 6, bold=True, color=GOLD)
    c.drawRightString(PW - PAD, 2*mm, stamp)

# ── Tier dots ─────────────────────────────────────────────────────────────────
TIER_ORDER = ['Rookie','Shooter','Contender','Craftsman',
              'Maverick','Master','Grandmaster','Legend']

def _draw_tier_dots(c, tier, x, y, dot_w=7, dot_h=2.5, gap=2.5):
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
    HEADER_H = 7 * mm
    PHOTO_H  = PH * 0.50
    BAND_TOP = PH - HEADER_H - PHOTO_H

    _draw_header(c, 'SHUTTER LEAGUE', 'APEX DDI ENGINE  ·  FULL EVALUATION', PH)

    # Photo
    photo_bot = BAND_TOP
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

    # Watermark
    credit = data.get('credit','')
    if credit:
        parts   = credit.strip().split()
        display = f"\u00a9 {parts[0]} {parts[-1][0]}" if len(parts)>=2 else f"\u00a9 {credit}"
        _set(c, 6, bold=False, color=HexColor('#AAAAAA'))
        c.drawRightString(PW - 4*mm, photo_bot + 3*mm, display)

    # Navy score band
    band_h = BAND_TOP - 6*mm   # footer is 6mm
    c.setFillColor(NAVY)
    c.rect(0, 6*mm, PW, band_h, fill=1, stroke=0)

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()

    # Score
    _set(c, 48, bold=True, color=white)
    score_w = c.stringWidth(score_str, _font(True), 48)
    sx, sy  = PAD, 6*mm + band_h - 15*mm
    c.drawString(sx, sy, score_str)

    # Tier + dots
    _set(c, 9, bold=True, color=GOLD)
    c.drawString(sx, sy - 5*mm, tier_str)
    _draw_tier_dots(c, data.get('tier',''), sx, sy - 8.5*mm)

    # Meta right of score
    mx = sx + score_w + 8*mm
    mw = PW - mx - PAD
    my = sy + 1*mm
    if credit:
        _set(c, 7, bold=True, color=GOLD)
        c.drawString(mx, my, f"PHOTOGRAPHY BY :  {credit.upper()}")
        my -= 4.5*mm
    meta = '  ·  '.join(filter(None,[data.get('genre',''),
                                      data.get('format',''),
                                      data.get('location','')]))
    if meta:
        _set(c, 6.5, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(mx, my, meta)
        my -= 4*mm
    aff = data.get('affective_state','')
    if aff:
        _set(c, 6, bold=False, color=GOLD_DK)
        c.drawString(mx, my, f"Affective State: {aff}")

    # Separator + dimensions
    sep_y = sy - 10*mm
    c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW-PAD, sep_y)

    dims   = data.get('dim_breakdown', [])
    if dims:
        n      = len(dims)
        dw     = (PW - 2*PAD) / n
        max_sc = max(d['score'] for d in dims)
        dy     = sep_y - 2*mm
        for i, dim in enumerate(dims):
            cx = PAD + i*dw
            if i > 0:
                c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
                c.line(cx, dy, cx, dy - 12*mm)
            for j, lbl in enumerate([dim['l1'], dim['l2']]):
                _set(c, 5, bold=False, color=DIM_LBL)
                lx = cx + dw/2 - c.stringWidth(lbl, _font(False), 5)/2
                c.drawString(lx, dy - j*3.5*mm, lbl)
            sc    = f"{dim['score']:.1f}"
            scol  = GOLD if dim['score']==max_sc else white
            _set(c, 14, bold=True, color=scol)
            sw = c.stringWidth(sc, _font(True), 14)
            c.drawString(cx + dw/2 - sw/2, dy - 8*mm, sc)

    # Opening bold
    wso = _clean(data.get('wso',''))
    if wso:
        wy = sep_y - 14*mm
        c.setStrokeColor(BAND_BD); c.setLineWidth(0.5)
        c.line(PAD, wy+1*mm, PW-PAD, wy+1*mm)
        _draw_text_block(c, wso, PAD, wy-1*mm, PW-2*PAD,
                         7, bold=True, color=white, line_height=4.2*mm, max_lines=5)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 2
# ════════════════════════════════════════════════════════════════════════
def _draw_page2(c, data):
    HEADER_H  = 7 * mm
    FOOTER_H  = 6 * mm
    PAGE_TOP  = PH - HEADER_H
    COL_H     = 88 * mm       # taller columns for full text
    COL_TOP   = PAGE_TOP - 2*mm

    score_str = f"{float(data.get('score',0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset','Untitled')

    _draw_header(c, f"FULL EVALUATION  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    # Cream page background
    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, PH-HEADER_H-FOOTER_H, fill=1, stroke=0)

    # ── Four pastel columns ──
    raw_bodies = [
        data.get('c1_body',''),
        data.get('c2_body',''),
        data.get('c3_body',''),
        data.get('c4_body',''),
    ]
    eyebrows = [
        "The Photographer's Advice",
        "What You Controlled",
        "What to Watch Next",
        "Keep This in Mind",
    ]

    n_cols = 4
    col_w  = (PW - 2*PAD) / n_cols

    for i, (eyebrow, raw) in enumerate(zip(eyebrows, raw_bodies)):
        body   = _clean(raw)
        cx     = PAD + i * col_w
        cy_top = COL_TOP
        cy_bot = COL_TOP - COL_H

        # Pastel gradient background
        bg_hex, accent, ey_col, hl_col = CARD_STYLES[i]
        _gradient_rect(c, cx, cy_bot, col_w, COL_H, bg_hex, steps=16)

        # Top accent line (2pt)
        c.setFillColor(accent)
        c.rect(cx, cy_top - 1.5, col_w, 2, fill=1, stroke=0)

        # Thin vertical divider between cards
        if i > 0:
            c.setStrokeColor(BORDER); c.setLineWidth(0.3)
            c.line(cx, cy_top, cx, cy_bot)

        # Eyebrow
        _set(c, 5, bold=True, color=ey_col)
        c.drawString(cx + 3*mm, cy_top - 4.5*mm, eyebrow.upper())

        # Headline — first sentence of cleaned body
        headline = _first_sentence(body)
        hy = cy_top - 9*mm
        hy = _draw_text_block(c, headline, cx+3*mm, hy, col_w-6*mm,
                              6.5, bold=True, color=hl_col,
                              line_height=3.8*mm, max_lines=3)

        # Thin rule under headline
        c.setStrokeColor(BORDER); c.setLineWidth(0.3)
        c.line(cx+3*mm, hy, cx+col_w-3*mm, hy)
        hy -= 2.5*mm

        # Body text — skip first sentence to avoid duplication
        body_skip = body[len(headline):].strip() if headline and body.startswith(headline) else body
        _draw_text_block(c, body_skip, cx+3*mm, hy, col_w-6*mm,
                         5.5, bold=False, color=DARK2,
                         line_height=3*mm, max_lines=22)

    # Separator below columns
    sep_y = COL_TOP - COL_H - 2*mm
    c.setStrokeColor(BORDER); c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW-PAD, sep_y)

    # ── Edit Guide ──
    edit_base     = _clean(data.get('edit_base',''))
    edit_creative = _clean(data.get('edit_creative',''))
    ey = sep_y - 4*mm

    if edit_base or edit_creative:
        _set(c, 5, bold=True, color=MUTED)
        c.drawString(PAD, ey, 'EDIT GUIDE')
        ey -= 4*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.3)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)
        ey -= 1*mm

        half_w  = (PW - 2*PAD - 6*mm) / 2
        ey_l = ey_r = ey

        if edit_base:
            _set(c, 5.5, bold=True, color=GOLD_DK)
            c.drawString(PAD, ey_l, 'STANDARD EDIT')
            _set(c, 5, bold=False, color=MUTED)
            sx = PAD + c.stringWidth('STANDARD EDIT', _font(True), 5.5) + 3*mm
            c.drawString(sx, ey_l, '· Balanced. Light editing.')
            ey_l -= 3.5*mm
            ey_l = _draw_text_block(c, edit_base, PAD+2*mm, ey_l, half_w,
                                    5.5, bold=False, color=DARK2,
                                    line_height=3*mm, max_lines=10)

        if edit_creative:
            rx = PAD + half_w + 6*mm
            _set(c, 5.5, bold=True, color=HexColor('#2A5A3A'))
            c.drawString(rx, ey_r, 'CREATIVE EDIT')
            _set(c, 5, bold=False, color=MUTED)
            sx = rx + c.stringWidth('CREATIVE EDIT', _font(True), 5.5) + 3*mm
            c.drawString(sx, ey_r, '· Artistic. Heavy editing.')
            ey_r -= 3.5*mm
            ey_r = _draw_text_block(c, edit_creative, rx+2*mm, ey_r, half_w,
                                    5.5, bold=False, color=DARK2,
                                    line_height=3*mm, max_lines=10)

        ey = min(ey_l, ey_r) - 3*mm
        c.setStrokeColor(BORDER); c.setLineWidth(0.3)
        c.line(PAD, ey+1*mm, PW-PAD, ey+1*mm)

    # ── Where to Shoot Next ──
    loc1      = _clean(data.get('mentor_location_1',''))
    loc2      = _clean(data.get('mentor_location_2',''))
    days_lang = data.get('days_since_language','')

    if loc1:
        half_w = (PW - 2*PAD - 6*mm) / 2
        l1_h   = _block_height(loc1, half_w, 5.5, line_height=3*mm)
        l2_h   = _block_height(loc2, half_w, 5.5, line_height=3*mm) if loc2 else 0
        dl_h   = 5*mm if days_lang else 0
        box_h  = 6*mm + max(l1_h, l2_h) + dl_h + 6*mm

        box_top = ey - 1*mm
        box_bot = box_top - box_h

        # Dark green box
        c.setFillColor(GREEN)
        c.rect(PAD, box_bot, PW-2*PAD, box_h, fill=1, stroke=0)

        iy = box_top - 4*mm
        _set(c, 5, bold=True, color=GREEN_L)
        c.drawString(PAD+3*mm, iy, 'WHERE TO SHOOT NEXT')
        iy -= 4.5*mm

        if loc2:
            _set(c, 5, bold=True, color=GREEN_L)
            c.drawString(PAD+3*mm, iy, 'NOW OPEN')
            c.drawString(PAD+3*mm+half_w+6*mm, iy, 'COMING UP')
            iy -= 3.5*mm
            _draw_text_block(c, loc1, PAD+3*mm, iy, half_w,
                             5.5, bold=False, color=HexColor('#CCDDCC'),
                             line_height=3*mm, max_lines=12)
            _draw_text_block(c, loc2, PAD+3*mm+half_w+6*mm, iy, half_w,
                             5.5, bold=False, color=HexColor('#AABBAA'),
                             line_height=3*mm, max_lines=12)
        else:
            _draw_text_block(c, loc1, PAD+3*mm, iy, PW-2*PAD-6*mm,
                             5.5, bold=False, color=HexColor('#CCDDCC'),
                             line_height=3*mm, max_lines=8)

        if days_lang:
            # Gold bar at bottom of green box
            c.setStrokeColor(GREEN_B); c.setLineWidth(0.5)
            c.line(PAD+3*mm, box_bot+dl_h+1*mm, PW-PAD-3*mm, box_bot+dl_h+1*mm)
            _set(c, 5.5, bold=True, color=GOLD)
            c.drawString(PAD+3*mm, box_bot+2.5*mm, days_lang[:130])

        ey = box_bot - 3*mm

    # ── HCB Quote ──
    quote = ('\u201cTo photograph is to hold one\u2019s breath when all '
             'faculties converge to capture fleeting reality.\u201d')
    attr  = '\u2014 Henri Cartier-Bresson'
    if ey > FOOTER_H + 10*mm:
        c.setFillColor(GOLD)
        c.rect(PAD, ey-8*mm, 1.5*mm, 7*mm, fill=1, stroke=0)
        _draw_text_block(c, quote, PAD+4*mm, ey-2*mm, PW-2*PAD-4*mm,
                         6, bold=False, color=MUTED, line_height=3.5*mm)
        _set(c, 5.5, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(PAD+4*mm, ey-7.5*mm, attr)

    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
def build_scorecard_pdf(data: dict) -> bytes:
    """
    Build two-page A4 portrait PDF using reportlab.
    Pure Python — no system library dependencies.
    """
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
