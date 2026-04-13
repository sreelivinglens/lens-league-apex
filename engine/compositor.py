"""
Apex Rating Card — v20 CLEAN REBUILD
Single column. Every section stacks top to bottom.
Palette matches base.html exactly.
Fonts: 18pt body minimum. Legible at any age.
Canvas: 900px wide.
"""

from PIL import Image, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))
F_BOLD   = os.path.join(FONT_DIR, 'LiberationSans-Bold.ttf')
F_REG    = os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')
F_MONO   = os.path.join(FONT_DIR, 'DejaVuSansMono-Bold.ttf')
F_MONO_R = os.path.join(FONT_DIR, 'DejaVuSansMono.ttf')

# ── Font loader ───────────────────────────────────────────────────────────────
def fnt(path, size):
    candidates = [
        path,
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                pass
    return ImageFont.load_default()

# ── Palette — exact match to base.html CSS variables ─────────────────────────
BLACK    = (13,  13,  11)   # --black
S1       = (20,  20,  18)   # --surface-1
S2       = (28,  28,  26)   # --surface-2
S3       = (36,  36,  34)   # --surface-3
S4       = (46,  46,  44)   # --surface-4
BORDER   = (56,  56,  54)   # --border
T1       = (240, 239, 232)  # --text-primary
T2       = (184, 182, 174)  # --text-secondary
T3       = (122, 120, 112)  # --text-muted
GOLD     = (200, 168,  75)  # --gold
GOLD_L   = (223, 192, 112)  # --gold-light
GOLD_D   = (139, 105,  20)  # --gold-dark
GREEN    = (76,  175, 115)  # --green
RED      = (224,  85,  85)  # --red
AMBER    = (224, 153,  64)  # --amber

# ── Canvas ────────────────────────────────────────────────────────────────────
CW  = 1400   # canvas width
PAD = 64    # left/right padding

# ── Helpers ───────────────────────────────────────────────────────────────────
def line_h(font):
    """Height of one line of text."""
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    bb = d.textbbox((0, 0), 'Ag', font=font)
    return bb[3] - bb[1] + 6

def text_w(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]

def wrap_text(draw, text, font, max_w):
    """Wrap text to fit max_w. Returns list of lines."""
    if not text or not text.strip():
        return []
    words  = text.split()
    lines  = []
    cur    = []
    for word in words:
        test = ' '.join(cur + [word])
        if text_w(draw, test, font) > max_w and cur:
            lines.append(' '.join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(' '.join(cur))
    return lines

def measure_text_h(draw, text, font, max_w, line_sp=10):
    """Total pixel height of wrapped text block."""
    lines = wrap_text(draw, text, font, max_w)
    if not lines:
        return 0
    return len(lines) * line_h(font) + max(0, len(lines) - 1) * line_sp

def draw_text_block(draw, text, font, color, x, y, max_w, line_sp=10):
    """Draw wrapped text. Returns y after last line."""
    for line in wrap_text(draw, text, font, max_w):
        draw.text((x, y), line, font=font, fill=color)
        y += line_h(font) + line_sp
    return y

def hr(draw, y, color=BORDER, lpad=0, rpad=0):
    """Draw horizontal rule. Returns y + 1."""
    draw.rectangle([lpad, y, CW - rpad, y + 1], fill=color)
    return y + 1

def section_block_h(draw, label, body, label_font, body_font, w,
                    label_sp=8, body_sp=10, after=28):
    """Calculate height of a labelled section block."""
    h  = line_h(label_font) + label_sp
    h += measure_text_h(draw, body, body_font, w, body_sp)
    h += after
    return h

def draw_section(draw, label, body, label_font, body_font,
                 label_color, body_color, x, y, w,
                 label_sp=8, body_sp=10, after=28):
    """Draw a labelled section. Returns y after block."""
    draw.text((x, y), label, font=label_font, fill=label_color)
    y += line_h(label_font) + label_sp
    if body and body.strip():
        y = draw_text_block(draw, body, body_font, body_color, x, y, w, body_sp)
    y += after
    return y

# ── Main build function ───────────────────────────────────────────────────────
def build_card(photo_path, data, out_path):
    """
    Build a single-column rating card JPG.
    data keys: score, tier, asset, meta, genre_tag, dec, credit,
               soul_bonus, iucn_tag, modules, rows,
               byline_1, byline_2_body, badges_g, badges_w
    """

    # ── Define all fonts ──────────────────────────────────────────────────────
    F = {
        'brand':    fnt(F_MONO,   22),
        'engine':   fnt(F_MONO_R, 18),
        'score':    fnt(F_BOLD,   132),   # dominant score number
        'tier':     fnt(F_MONO,   30),
        'title':    fnt(F_BOLD,   42),
        'meta':     fnt(F_REG,    26),
        'tag':      fnt(F_MONO_R, 21),
        'mod_lbl':  fnt(F_MONO_R, 21),
        'mod_val':  fnt(F_BOLD,   54),   # large module numbers
        'sec_hdr':  fnt(F_MONO,   22),   # section label
        'body':     fnt(F_REG,    28),   # ALL body text — 28pt
        'imp':      fnt(F_BOLD,   28),   # improvement text bold
        'badge_h':  fnt(F_MONO,   22),
        'footer':   fnt(F_MONO_R, 20),
    }

    W = CW - PAD * 2  # inner content width
    dummy = ImageDraw.Draw(Image.new('RGB', (CW, 10)))

    # ── Extract data ──────────────────────────────────────────────────────────
    score   = str(data.get('score', '—'))
    tier    = str(data.get('tier', '')).upper()
    asset   = data.get('asset', 'Untitled')
    meta    = data.get('meta', '')
    gtag    = data.get('genre_tag', '')
    dec     = data.get('dec', '')
    credit  = data.get('credit', '')
    soul    = data.get('soul_bonus', False)
    iucn    = data.get('iucn_tag', '')
    modules = data.get('modules', [])
    rows    = data.get('rows', [])
    b1      = data.get('byline_1', '').strip()
    b2      = data.get('byline_2_body', '').strip()
    strengths = [b for b in data.get('badges_g', []) if b.strip()]
    gaps      = [b for b in data.get('badges_w', []) if b.strip()]

    # ── Calculate heights of each section ─────────────────────────────────────
    HEADER_H = 56
    PHOTO_H  = 800
    SCORE_H  = 260

    # Module row
    MOD_H = PAD + line_h(F['mod_lbl']) + 10 + line_h(F['mod_val']) + 14 + 6 + PAD

    # Analysis sections
    analysis_h = PAD
    for _, body in rows:
        analysis_h += section_block_h(dummy, '', body, F['sec_hdr'], F['body'], W,
                                      after=26)
    analysis_h += PAD // 2

    # Byline section
    byline_h  = PAD
    byline_h += line_h(F['sec_hdr']) + 10
    byline_h += measure_text_h(dummy, b1, F['body'], W, 10)
    byline_h += 28
    byline_h += line_h(F['sec_hdr']) + 10
    byline_h += measure_text_h(dummy, b2, F['imp'], W, 10)
    byline_h += PAD

    # Badges section
    badges_h = 0
    if strengths or gaps:
        badges_h += PAD
        if strengths:
            badges_h += line_h(F['badge_h']) + 10
            badges_h += measure_text_h(dummy, ', '.join(strengths), F['body'], W, 8)
            badges_h += 20
        if gaps:
            badges_h += line_h(F['badge_h']) + 10
            badges_h += measure_text_h(dummy, ', '.join(gaps), F['body'], W, 8)
            badges_h += 20
        badges_h += PAD // 2

    FOOTER_H = 56

    CH = (HEADER_H + PHOTO_H + SCORE_H +
          1 + MOD_H +
          1 + analysis_h +
          1 + byline_h +
          (1 + badges_h if badges_h else 0) +
          FOOTER_H)

    # ── Create canvas ─────────────────────────────────────────────────────────
    canvas = Image.new('RGB', (CW, CH), BLACK)
    draw   = ImageDraw.Draw(canvas)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 1 — GOLD HEADER STRIP
    # └─────────────────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, CW, HEADER_H], fill=GOLD)
    draw.text((PAD, 17), 'THE LENS LEAGUE', font=F['brand'], fill=BLACK)
    tag = 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.'
    tw  = text_w(draw, tag, F['engine'])
    draw.text((CW - PAD - tw, 21), tag, font=F['engine'], fill=(40, 30, 5))

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 2 — PHOTO (full width, no padding)
    # └─────────────────────────────────────────────────────────────────────────
    PH_Y = HEADER_H
    try:
        img_raw = Image.open(photo_path).convert('RGB')
        pw, ph  = img_raw.size
        scale   = max(CW / pw, PHOTO_H / ph)
        nw, nh  = int(pw * scale), int(ph * scale)
        img_raw = img_raw.resize((nw, nh), Image.LANCZOS)
        cx = (nw - CW) // 2
        cy = (nh - PHOTO_H) // 2
        img_raw = img_raw.crop((cx, cy, cx + CW, cy + PHOTO_H))
        canvas.paste(img_raw, (0, PH_Y))
    except Exception as e:
        draw.rectangle([0, PH_Y, CW, PH_Y + PHOTO_H], fill=S3)
        draw.text((PAD, PH_Y + 20), f'Photo unavailable: {e}', font=F['body'], fill=T3)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 3 — SCORE BLOCK (dark, below photo)
    # └─────────────────────────────────────────────────────────────────────────
    SB_Y = HEADER_H + PHOTO_H
    draw.rectangle([0, SB_Y, CW, SB_Y + SCORE_H], fill=S1)

    # Large score — left
    scw = text_w(draw, score, F['score'])
    sc_y = SB_Y + (SCORE_H - line_h(F['score'])) // 2 - 6
    draw.text((PAD, sc_y), score, font=F['score'], fill=GOLD)

    # Tier + pips — right of score
    TX = PAD + scw + 40
    TY = SB_Y + (SCORE_H - line_h(F['tier'])) // 2 - 18
    draw.text((TX, TY), tier, font=F['tier'], fill=GOLD)

    tier_map = {'APPRENTICE':1, 'PRACTITIONER':2, 'MASTER':3, 'GRANDMASTER':4, 'LEGEND':5}
    active   = tier_map.get(tier, 1)
    pip_y    = TY + line_h(F['tier']) + 14
    for i in range(5):
        px  = TX + i * 24
        col = GOLD if i < active else (56, 56, 54)
        draw.rectangle([px, pip_y, px + 16, pip_y + 9], fill=col)

    # Title — top right
    ttw = text_w(draw, asset, F['title'])
    draw.text((CW - PAD - ttw, SB_Y + 22), asset, font=F['title'], fill=T1)

    # Meta — below title
    mtw = text_w(draw, meta, F['meta'])
    draw.text((CW - PAD - mtw, SB_Y + 22 + line_h(F['title']) + 6),
              meta, font=F['meta'], fill=T2)

    # Archetype + photographer — bottom right
    arch = f"{dec}  ·  {credit}" if dec and credit else dec or credit
    if arch:
        aw = text_w(draw, arch, F['tag'])
        draw.text((CW - PAD - aw, SB_Y + SCORE_H - line_h(F['tag']) - 22),
                  arch, font=F['tag'], fill=T3)

    # Soul bonus / IUCN — bottom left
    extra_y = SB_Y + SCORE_H - line_h(F['tag']) - 22
    if soul:
        draw.text((PAD, extra_y), '★  SOUL BONUS  —  AQ ≥ 8.0', font=F['tag'], fill=GOLD)
    elif iucn:
        iu = iucn.upper()
        ic = RED if any(x in iu for x in ['CRITICAL','ENDANGERED','VULNERABLE']) \
             else AMBER if 'NEAR' in iu else GREEN
        draw.text((PAD, extra_y), iucn, font=F['tag'], fill=ic)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 4 — MODULE SCORES (full width, surface-2 background)
    # └─────────────────────────────────────────────────────────────────────────
    y = hr(draw, SB_Y + SCORE_H)
    draw.rectangle([0, y, CW, y + MOD_H], fill=S2)

    n      = max(len(modules), 1)
    MW     = (CW - PAD * 2) // n
    max_sc = max((float(s) for _, s in modules if s), default=0)
    MY     = y + PAD

    for i, (name, mscore) in enumerate(modules):
        mx  = PAD + i * MW
        top = float(mscore) == max_sc
        col = GOLD if top else T2

        # Separator line between modules
        if i > 0:
            sep_top = MY - 4
            sep_bot = MY + line_h(F['mod_lbl']) + 10 + line_h(F['mod_val']) + 16
            draw.rectangle([mx - 1, sep_top, mx, sep_bot], fill=BORDER)

        draw.text((mx + 14, MY), name.upper(), font=F['mod_lbl'], fill=T3)
        draw.text((mx + 14, MY + line_h(F['mod_lbl']) + 10), str(mscore),
                  font=F['mod_val'], fill=col)

        # Progress bar
        bar_y = MY + line_h(F['mod_lbl']) + 10 + line_h(F['mod_val']) + 12
        bar_w = MW - 32
        draw.rectangle([mx + 14, bar_y, mx + 14 + bar_w, bar_y + 6], fill=S3)
        fw = int(bar_w * float(mscore) / 10)
        if fw > 0:
            draw.rectangle([mx + 14, bar_y, mx + 14 + fw, bar_y + 6],
                           fill=GOLD if top else GOLD_D)

    y = hr(draw, y + MOD_H)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 5 — ANALYSIS ROWS (single column, full width)
    # └─────────────────────────────────────────────────────────────────────────
    y += PAD

    for idx, (label, body) in enumerate(rows):
        lbl = label.replace('\\n', ' ').replace('\n', ' ').upper()

        # Gold label
        draw.text((PAD, y), lbl, font=F['sec_hdr'], fill=GOLD)
        y += line_h(F['sec_hdr']) + 10

        # Body — 19pt, full inner width
        if body and body.strip():
            y = draw_text_block(draw, body, F['body'], T2, PAD, y, W, 10)

        y += 26

        # Subtle rule between sections (not after last)
        if idx < len(rows) - 1:
            hr(draw, y - 14, color=(42, 42, 40), lpad=PAD, rpad=PAD)

    y += PAD // 2
    y = hr(draw, y)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 6 — APEX BYLINE (single column, gold left accent)
    # └─────────────────────────────────────────────────────────────────────────
    byline_start_y = y
    y += PAD

    draw.text((PAD, y), 'APEX BYLINE', font=F['sec_hdr'], fill=GOLD)
    y += line_h(F['sec_hdr']) + 10
    if b1:
        y = draw_text_block(draw, b1, F['body'], T2, PAD, y, W, 10)
    y += 28

    draw.text((PAD, y), 'THE ONE IMPROVEMENT', font=F['sec_hdr'], fill=GOLD)
    y += line_h(F['sec_hdr']) + 10
    if b2:
        y = draw_text_block(draw, b2, F['imp'], T1, PAD, y, W, 10)
    y += PAD

    # Gold left accent bar for entire byline section
    draw.rectangle([0, byline_start_y, 5, y], fill=GOLD_D)

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 7 — STRENGTHS & GAPS (single column, full width)
    # └─────────────────────────────────────────────────────────────────────────
    if strengths or gaps:
        y = hr(draw, y)
        y += PAD

        if strengths:
            draw.text((PAD, y), 'STRENGTHS', font=F['badge_h'], fill=GREEN)
            y += line_h(F['badge_h']) + 10
            y = draw_text_block(draw, ', '.join(strengths), F['body'], GREEN, PAD, y, W, 8)
            y += 20

        if gaps:
            draw.text((PAD, y), 'AREAS TO DEVELOP', font=F['badge_h'], fill=RED)
            y += line_h(F['badge_h']) + 10
            y = draw_text_block(draw, ', '.join(gaps), F['body'], RED, PAD, y, W, 8)
            y += 20

        y += PAD // 2

    # ┌─────────────────────────────────────────────────────────────────────────
    # │ SECTION 8 — FOOTER
    # └─────────────────────────────────────────────────────────────────────────
    FY = CH - FOOTER_H
    draw.rectangle([0, FY, CW, CH], fill=S1)
    draw.rectangle([0, FY, CW, FY + 1], fill=BORDER)

    foot_l = 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  LENS LEAGUE APEX'
    draw.text((PAD, FY + 19), foot_l, font=F['footer'], fill=T3)

    stamp = f"LL · {score} · {tier}"
    sw    = text_w(draw, stamp, F['footer'])
    draw.text((CW - PAD - sw, FY + 19), stamp, font=F['footer'], fill=GOLD)

    canvas.save(out_path, 'JPEG', quality=96, optimize=True)
    return out_path
