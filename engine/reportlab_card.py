"""
Shutter League — Reportlab Scorecard PDF
Session 141 — replaces WeasyPrint (system lib issues) with pure-Python reportlab.
Two A4 portrait pages:
  Page 1: Photo hero + score band + dimensions + opening bold
  Page 2: Four eval columns + edit guide + where to shoot + quote
No system dependencies beyond reportlab itself.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Spacer
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
import io, textwrap, requests

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY    = HexColor('#0F2A22')
NAVY_DK = HexColor('#0A1A12')
GOLD    = HexColor('#D6A428')
GOLD_DK = HexColor('#A37B2C')
GREEN   = HexColor('#1A3A2A')
GREEN_L = HexColor('#7AAA8A')
GREEN_B = HexColor('#2A5A3A')
CREAM   = HexColor('#F6F2E9')
DARK    = HexColor('#1A1A18')
DARK2   = HexColor('#3A3A38')
BORDER  = HexColor('#D0CAB8')
MUTED   = HexColor('#888880')
WHITE05 = HexColor('#FFFFFF')
DIM_LBL = HexColor('#AAAAAA')  # dimension label colour on dark bg
BAND_BD = HexColor('#2A2A28')  # band internal borders

# ── A4 dimensions ─────────────────────────────────────────────────────────────
PW, PH = A4          # 595.27 x 841.89 pts
PAD = 14 * mm        # outer margin

# ── Font helpers ──────────────────────────────────────────────────────────────
def _font(bold=False):
    return 'Helvetica-Bold' if bold else 'Helvetica'

def _set(c, size, bold=False, color=None):
    c.setFont(_font(bold), size)
    if color:
        c.setFillColor(color)

# ── Text wrapping ─────────────────────────────────────────────────────────────
def _wrap(text, width_pts, font_size, bold=False):
    """Wrap text to fit width_pts, returns list of lines."""
    if not text:
        return []
    avg_char = font_size * 0.52
    chars_per_line = max(1, int(width_pts / avg_char))
    return textwrap.wrap(text, chars_per_line) or ['']

def _draw_text_block(c, text, x, y, width, font_size, bold=False, color=None,
                     line_height=None, max_lines=None):
    """Draw wrapped text block, return y after last line."""
    if not text:
        return y
    if color:
        c.setFillColor(color)
    c.setFont(_font(bold), font_size)
    lh = line_height or (font_size * 1.45)
    lines = _wrap(text, width, font_size, bold)
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        c.drawString(x, y, line)
        y -= lh
    return y

def _text_block_height(text, width, font_size, bold=False, line_height=None):
    """Measure height of wrapped text block without drawing."""
    if not text:
        return 0
    lh = line_height or (font_size * 1.45)
    lines = _wrap(text, width, font_size, bold)
    return len(lines) * lh

def _first_sentence(text):
    """Extract first sentence as headline."""
    if not text:
        return ''
    for sep in ['. ', '.\n', '! ', '? ']:
        idx = text.find(sep)
        if idx != -1 and idx < 120:
            return text[:idx + 1]
    return text[:80].rstrip() + ('…' if len(text) > 80 else '')

# ── Photo fetch ───────────────────────────────────────────────────────────────
def _fetch_photo(photo_url):
    """Fetch photo from URL, return ImageReader or None."""
    if not photo_url:
        return None
    try:
        resp = requests.get(photo_url, timeout=10)
        resp.raise_for_status()
        return ImageReader(io.BytesIO(resp.content))
    except Exception as e:
        print(f'[reportlab_card] photo fetch failed: {e}')
        return None

# ── Header / Footer ───────────────────────────────────────────────────────────
def _draw_header(c, left, right, y_top, h=7*mm):
    c.setFillColor(NAVY)
    c.rect(0, y_top - h, PW, h, fill=1, stroke=0)
    _set(c, 7, bold=True, color=GOLD)
    c.drawString(PAD, y_top - h + 2*mm, left)
    _set(c, 6, bold=False, color=HexColor('#AAAAAA'))
    c.drawRightString(PW - PAD, y_top - h + 2*mm, right)

def _draw_footer(c, stamp, y_bottom=0, h=6*mm):
    c.setFillColor(NAVY_DK)
    c.rect(0, y_bottom, PW, h, fill=1, stroke=0)
    _set(c, 5.5, bold=False, color=HexColor('#444444'))
    c.drawString(PAD, y_bottom + 2*mm,
                 'BETTER LIGHT.  MORE CLARITY.  STRONGER STORY.  YOU, ONE FRAME AT A TIME.')
    _set(c, 6, bold=True, color=GOLD)
    c.drawRightString(PW - PAD, y_bottom + 2*mm, stamp)

# ── Tier dots ─────────────────────────────────────────────────────────────────
TIER_ORDER = ['Rookie','Shooter','Contender','Craftsman',
              'Maverick','Master','Grandmaster','Legend']

def _draw_tier_dots(c, tier, x, y, dot_w=8, dot_h=2.5, gap=3):
    idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    for i in range(8):
        c.setFillColor(GOLD if i <= idx else BAND_BD)
        c.rect(x + i*(dot_w+gap), y, dot_w, dot_h, fill=1, stroke=0)

# ════════════════════════════════════════════════════════════════════════
#  PAGE 1
# ════════════════════════════════════════════════════════════════════════
def _draw_page1(c, data):
    HEADER_H = 7 * mm
    FOOTER_H = 6 * mm
    PHOTO_H  = PH * 0.48          # ~48% of page for photo
    BAND_Y   = PH - HEADER_H - PHOTO_H  # top of score band

    # ── Header ──
    _draw_header(c, 'SHUTTER LEAGUE', 'APEX DDI ENGINE  ·  FULL EVALUATION', PH)

    # ── Photo ──
    photo_top    = PH - HEADER_H
    photo_bottom = photo_top - PHOTO_H
    c.setFillColor(HexColor('#111111'))
    c.rect(0, photo_bottom, PW, PHOTO_H, fill=1, stroke=0)

    photo_img = _fetch_photo(data.get('photo_url'))
    if photo_img:
        try:
            iw, ih = photo_img.getSize()
            scale   = max(PW / iw, PHOTO_H / ih)
            nw, nh  = iw * scale, ih * scale
            ox      = (PW - nw) / 2
            oy      = photo_bottom + (PHOTO_H - nh) / 2
            c.drawImage(photo_img, ox, oy, nw, nh, mask='auto')
        except Exception:
            pass

    # Watermark credit
    credit = data.get('credit', '')
    if credit:
        parts = credit.strip().split()
        display = f"\u00a9 {parts[0]} {parts[-1][0]}" if len(parts) >= 2 else f"\u00a9 {credit}"
        _set(c, 6, bold=False, color=HexColor('#AAAAAA'))
        c.drawRightString(PW - 4*mm, photo_bottom + 3*mm, display)

    # ── Score band (navy) ──
    band_h = BAND_Y - FOOTER_H
    c.setFillColor(NAVY)
    c.rect(0, FOOTER_H, PW, band_h, fill=1, stroke=0)

    # Score number
    score_str = f"{float(data.get('score', 0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    _set(c, 52, bold=True, color=white)
    score_w = c.stringWidth(score_str, _font(True), 52)
    score_x = PAD
    score_y = FOOTER_H + band_h - 16*mm
    c.drawString(score_x, score_y, score_str)

    # Tier label
    _set(c, 9, bold=True, color=GOLD)
    c.drawString(score_x, score_y - 5*mm, tier_str)

    # Tier dots
    _draw_tier_dots(c, data.get('tier',''), score_x, score_y - 8.5*mm)

    # Meta block (right of score)
    meta_x = score_x + score_w + 8*mm
    meta_w = PW - meta_x - PAD
    my = score_y + 2*mm

    photographer = (data.get('credit') or '').strip()
    if photographer:
        _set(c, 7, bold=True, color=GOLD)
        c.drawString(meta_x, my, f"PHOTOGRAPHY BY :  {photographer.upper()}")
        my -= 4.5*mm

    meta_line = '  ·  '.join(filter(None, [
        data.get('genre',''), data.get('format',''), data.get('location','')
    ]))
    if meta_line:
        _set(c, 6.5, bold=False, color=HexColor('#AAAAAA'))
        c.drawString(meta_x, my, meta_line)
        my -= 4*mm

    affective = data.get('affective_state','')
    if affective:
        _set(c, 6, bold=False, color=GOLD_DK)
        c.drawString(meta_x, my, f"Affective State: {affective}")
        my -= 4*mm

    # Separator
    sep_y = score_y - 10*mm
    c.setStrokeColor(BAND_BD)
    c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW - PAD, sep_y)

    # Dimensions row
    dims = data.get('dim_breakdown', [])
    if dims:
        n       = len(dims)
        col_w   = (PW - 2*PAD) / n
        dim_y   = sep_y - 2*mm
        max_sc  = max(d['score'] for d in dims)
        for i, dim in enumerate(dims):
            cx = PAD + i * col_w
            if i > 0:
                c.setStrokeColor(BAND_BD)
                c.setLineWidth(0.5)
                c.line(cx, dim_y, cx, dim_y - 12*mm)
            # Label
            for j, lbl in enumerate([dim['l1'], dim['l2']]):
                _set(c, 5, bold=False, color=DIM_LBL)
                lx = cx + col_w/2 - c.stringWidth(lbl, _font(False), 5)/2
                c.drawString(lx, dim_y - j*3.5*mm, lbl)
            # Score
            sc_str = f"{dim['score']:.1f}"
            sc_col = GOLD if dim['score'] == max_sc else white
            _set(c, 14, bold=True, color=sc_col)
            sw = c.stringWidth(sc_str, _font(True), 14)
            c.drawString(cx + col_w/2 - sw/2, dim_y - 8*mm, sc_str)

    # Opening bold (what_stood_out)
    wso = data.get('wso', '')
    if wso:
        wso_y = sep_y - 14*mm
        c.setStrokeColor(BAND_BD)
        c.line(PAD, wso_y + 1*mm, PW - PAD, wso_y + 1*mm)
        _draw_text_block(c, wso, PAD, wso_y - 1*mm, PW - 2*PAD,
                         7, bold=True, color=white, line_height=4*mm, max_lines=4)

    # ── Footer ──
    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PAGE 2
# ════════════════════════════════════════════════════════════════════════
def _draw_page2(c, data):
    HEADER_H = 7 * mm
    FOOTER_H = 6 * mm
    content_top = PH - HEADER_H
    content_bot = FOOTER_H
    content_h   = content_top - content_bot

    score_str = f"{float(data.get('score', 0)):.2f}"
    tier_str  = (data.get('tier') or '').upper()
    asset     = data.get('asset', 'Untitled')

    # ── Header ──
    _draw_header(c, f"FULL EVALUATION  ·  {asset}",
                 'APEX DDI ENGINE  ·  RATED BY SCIENCE', PH)

    # ── Cream background ──
    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PW, content_h, fill=1, stroke=0)

    # ── Four evaluation columns ──
    col_data = [
        ("The Photographer's Advice", data.get('c1_body','')),
        ("What You Controlled",       data.get('c2_body','')),
        ("What to Watch Next",        data.get('c3_body','')),
        ("Keep This in Mind",         data.get('c4_body','')),
    ]

    n_cols   = 4
    col_w    = (PW - 2*PAD) / n_cols
    col_h    = 64 * mm
    col_top  = content_top - 2*mm

    for i, (eyebrow, body) in enumerate(col_data):
        cx = PAD + i * col_w
        # Divider
        if i > 0:
            c.setStrokeColor(BORDER)
            c.setLineWidth(0.5)
            c.line(cx, col_top, cx, col_top - col_h)
        # Eyebrow
        _set(c, 5, bold=True, color=GOLD_DK)
        c.drawString(cx + 3*mm, col_top - 3*mm, eyebrow.upper())
        # Headline
        headline = _first_sentence(body)
        hy = col_top - 7*mm
        _draw_text_block(c, headline, cx + 3*mm, hy, col_w - 6*mm,
                         6.5, bold=True, color=DARK, line_height=3.5*mm, max_lines=3)
        # Body
        by = col_top - 14*mm
        _draw_text_block(c, body, cx + 3*mm, by, col_w - 6*mm,
                         5.5, bold=False, color=DARK2, line_height=3*mm, max_lines=18)

    # Separator after columns
    sep_y = col_top - col_h - 1*mm
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(PAD, sep_y, PW - PAD, sep_y)

    # ── Edit Guide ──
    edit_base     = data.get('edit_base', '')
    edit_creative = data.get('edit_creative', '')
    eg_y = sep_y - 4*mm

    if edit_base or edit_creative:
        _set(c, 5, bold=True, color=MUTED)
        c.drawString(PAD, eg_y, 'EDIT GUIDE')
        eg_y -= 4*mm
        c.setStrokeColor(BORDER)
        c.line(PAD, eg_y + 1*mm, PW - PAD, eg_y + 1*mm)
        eg_y -= 1*mm

        half_w = (PW - 2*PAD - 6*mm) / 2
        eg_left_y = eg_y
        eg_right_y = eg_y

        if edit_base:
            _set(c, 5.5, bold=True, color=GOLD_DK)
            c.drawString(PAD, eg_left_y, 'STANDARD EDIT')
            sub_x = PAD + c.stringWidth('STANDARD EDIT', _font(True), 5.5) + 4*mm
            _set(c, 5, bold=False, color=MUTED)
            c.drawString(sub_x, eg_left_y, '· Balanced. Light editing.')
            eg_left_y -= 3.5*mm
            eg_left_y = _draw_text_block(c, edit_base, PAD + 2*mm, eg_left_y,
                                         half_w, 5.5, bold=False, color=DARK2,
                                         line_height=3*mm, max_lines=10)

        if edit_creative:
            rx = PAD + half_w + 6*mm
            _set(c, 5.5, bold=True, color=HexColor('#2A5A3A'))
            c.drawString(rx, eg_right_y, 'CREATIVE EDIT')
            sub_x = rx + c.stringWidth('CREATIVE EDIT', _font(True), 5.5) + 4*mm
            _set(c, 5, bold=False, color=MUTED)
            c.drawString(sub_x, eg_right_y, '· Artistic. Heavy editing.')
            eg_right_y -= 3.5*mm
            eg_right_y = _draw_text_block(c, edit_creative, rx + 2*mm, eg_right_y,
                                          half_w, 5.5, bold=False, color=DARK2,
                                          line_height=3*mm, max_lines=10)

        eg_y = min(eg_left_y, eg_right_y) - 3*mm
        c.setStrokeColor(BORDER)
        c.line(PAD, eg_y + 1*mm, PW - PAD, eg_y + 1*mm)

    # ── Where to Shoot Next ──
    loc1      = data.get('mentor_location_1', '')
    loc2      = data.get('mentor_location_2', '')
    days_lang = data.get('days_since_language', '')

    if loc1:
        # Measure green box height
        half_w  = (PW - 2*PAD - 6*mm) / 2
        l1_h    = _text_block_height(loc1, half_w, 5.5, line_height=3*mm)
        l2_h    = _text_block_height(loc2, half_w, 5.5, line_height=3*mm) if loc2 else 0
        dl_h    = 4*mm if days_lang else 0
        box_h   = 6*mm + max(l1_h, l2_h) + dl_h + 6*mm

        box_top = eg_y - 1*mm
        c.setFillColor(GREEN)
        c.rect(PAD, box_top - box_h, PW - 2*PAD, box_h, fill=1, stroke=0)

        iy = box_top - 4*mm
        _set(c, 5, bold=True, color=GREEN_L)
        c.drawString(PAD + 3*mm, iy, 'WHERE TO SHOOT NEXT')
        iy -= 4*mm

        # Two sub-columns
        col1_x = PAD + 3*mm
        col2_x = PAD + half_w + 6*mm if loc2 else None

        if loc2:
            _set(c, 5, bold=True, color=GREEN_L)
            c.drawString(col1_x, iy, 'NOW OPEN')
            c.drawString(col2_x, iy, 'COMING UP')
            iy -= 3.5*mm
            _draw_text_block(c, loc1, col1_x, iy, half_w,
                             5.5, bold=False, color=HexColor('#CCDDCC'),
                             line_height=3*mm, max_lines=12)
            _draw_text_block(c, loc2, col2_x, iy, half_w,
                             5.5, bold=False, color=HexColor('#AABBAA'),
                             line_height=3*mm, max_lines=12)
        else:
            _draw_text_block(c, loc1, col1_x, iy, PW - 2*PAD - 6*mm,
                             5.5, bold=False, color=HexColor('#CCDDCC'),
                             line_height=3*mm, max_lines=8)

        if days_lang:
            dl_y = box_top - box_h + 4*mm
            c.setStrokeColor(GREEN_B)
            c.setLineWidth(0.5)
            c.line(PAD + 3*mm, dl_y + 2.5*mm, PW - PAD - 3*mm, dl_y + 2.5*mm)
            _set(c, 5.5, bold=True, color=GOLD)
            c.drawString(PAD + 3*mm, dl_y, days_lang[:120])

        eg_y = box_top - box_h - 2*mm

    # ── Quote ──
    quote = ('\u201cTo photograph is to hold one\u2019s breath when all '
             'faculties converge to capture fleeting reality.\u201d')
    attr  = '\u2014 Henri Cartier-Bresson'

    # Gold left bar
    c.setFillColor(GOLD)
    c.rect(PAD, eg_y - 8*mm, 1.5*mm, 7*mm, fill=1, stroke=0)
    _draw_text_block(c, quote, PAD + 4*mm, eg_y - 2*mm, PW - 2*PAD - 4*mm,
                     6, bold=False, color=MUTED, line_height=3.5*mm)
    _set(c, 5.5, bold=False, color=HexColor('#AAAAAA'))
    c.drawString(PAD + 4*mm, eg_y - 7*mm, attr)

    # ── Footer ──
    _draw_footer(c, f"SL  ·  {score_str}  ·  {tier_str}")


# ════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
def build_scorecard_pdf(data: dict) -> bytes:
    """
    Build two-page A4 PDF scorecard using reportlab (pure Python).
    data keys:
      score, tier, asset, credit, genre, format, location,
      affective_state, wso, dim_breakdown (list of {score,l1,l2}),
      c1_body, c2_body, c3_body, c4_body,
      edit_base, edit_creative,
      mentor_location_1, mentor_location_2, days_since_language,
      photo_url
    Returns raw PDF bytes.
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
