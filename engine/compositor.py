"""
Apex Audit Card — v15
Dark theme redesign matching Lens League Apex brand
Canvas: 960px wide, dynamic height
Palette: Deep black background, gold accents, high contrast text
"""

from PIL import Image, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))
F_BOLD   = os.path.join(FONT_DIR, 'LiberationSans-Bold.ttf')
F_REG    = os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')
F_MONO   = os.path.join(FONT_DIR, 'DejaVuSansMono-Bold.ttf')
F_MONO_R = os.path.join(FONT_DIR, 'DejaVuSansMono.ttf')

def fnt(path, size):
    if os.path.exists(path):
        try: return ImageFont.truetype(path, size)
        except: pass
    for fb in [
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]:
        if os.path.exists(fb):
            try: return ImageFont.truetype(fb, size)
            except: pass
    return ImageFont.load_default()

# ── Dark Theme Palette ────────────────────────────────────────────────────────
BG          = (13,  13,  11)    # #0D0D0B — deep black
SURFACE_1   = (20,  20,  18)    # #141412 — card surface
SURFACE_2   = (28,  28,  26)    # #1C1C1A — raised elements
SURFACE_3   = (36,  36,  34)    # #242422 — subtle panels
BORDER      = (42,  42,  40)    # #2A2A28 — borders
BORDER_MD   = (56,  56,  54)    # #383836 — stronger borders
TEXT_1      = (240, 239, 232)   # #F0EFE8 — primary text
TEXT_2      = (184, 182, 174)   # #B8B6AE — secondary text
TEXT_3      = (122, 120, 112)   # #7A7870 — muted text
GOLD        = (200, 168, 75)    # #C8A84B — gold accent
GOLD_DARK   = (139, 105, 20)    # #8B6914 — dark gold
GOLD_BG     = (28,  24,  12)    # dark gold background
GREEN       = (76,  175, 115)   # #4CAF73
RED         = (224, 85,  85)    # #E05555
AMBER       = (224, 153, 64)    # #E09940
WHITE       = (255, 255, 255)

CW          = 960
PAD         = 32
TH_W, TH_H  = 240, 160          # Larger thumbnail

def fh(font):
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    return d.textbbox((0, 0), 'Ag', font=font)[3] + 4

def wrap(text, font, max_w, draw):
    if not text or not text.strip():
        return []
    words, lines, cur = text.split(), [], []
    for w in words:
        test = ' '.join(cur + [w])
        if draw.textbbox((0, 0), test, font=font)[2] > max_w and cur:
            lines.append(' '.join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(' '.join(cur))
    return lines

def measure_h(text, font, max_w, draw, sp=5):
    lines = wrap(text, font, max_w, draw)
    return len(lines) * fh(font) + max(0, len(lines)-1) * sp if lines else 0

def draw_wrapped(draw, text, font, color, x, y, max_w, sp=5):
    for line in wrap(text, font, max_w, draw):
        draw.text((x, y), line, font=font, fill=color)
        y += fh(font) + sp
    return y

def draw_rect_outline(draw, x, y, w, h, color, width=1):
    draw.rectangle([x, y, x+w, y+h], outline=color, width=width)

def build_card(photo_path, data, out_path):

    # ── Font sizes — bigger for legibility ───────────────────────────────────
    f_brand    = fnt(F_MONO,   13)   # top strip brand
    f_engine   = fnt(F_MONO_R, 11)   # engine tag
    f_score    = fnt(F_BOLD,   52)   # big score number
    f_tier     = fnt(F_MONO,   13)   # tier label
    f_asset    = fnt(F_BOLD,   18)   # image title
    f_meta     = fnt(F_REG,    13)   # meta line
    f_tag      = fnt(F_MONO_R, 11)   # genre/soul tags
    f_mod_lbl  = fnt(F_MONO_R, 11)   # module labels
    f_mod_val  = fnt(F_BOLD,   22)   # module values
    f_sec_hdr  = fnt(F_MONO,   10)   # section headers
    f_sec_body = fnt(F_REG,    13)   # section body
    f_byline_h = fnt(F_MONO,   11)   # byline headers
    f_byline_b = fnt(F_REG,    13)   # byline body
    f_byline_i = fnt(F_BOLD,   13)   # improvement text
    f_str_hdr  = fnt(F_MONO,   10)   # badge headers
    f_str_body = fnt(F_REG,    12)   # badge text
    f_footer   = fnt(F_MONO,   11)   # footer

    dummy = ImageDraw.Draw(Image.new('RGB', (CW, 10)))

    # Column layout
    COL_GAP = 28
    COL_W   = (CW - PAD*2 - COL_GAP) // 2
    LC_X    = PAD
    RC_X    = PAD + COL_W + COL_GAP

    HEADER_H    = 44
    PHOTO_PAD   = 20
    MOD_PAD     = 16

    # Measure two-column section height
    left_h = 0
    for _, body in data.get('rows', []):
        left_h += fh(f_sec_hdr) + 4
        left_h += measure_h(body, f_sec_body, COL_W, dummy, 5) if body.strip() else 0
        left_h += 14

    b1 = data.get('byline_1', '').strip()
    b2 = data.get('byline_2_body', '').strip()
    badges_g = [b for b in data.get('badges_g', []) if b.strip()]
    badges_w = [b for b in data.get('badges_w', []) if b.strip()]

    right_h  = fh(f_byline_h) + 4
    right_h += measure_h(b1, f_byline_b, COL_W, dummy, 5)
    right_h += 14
    right_h += fh(f_byline_h) + 4
    right_h += measure_h(b2, f_byline_i, COL_W, dummy, 5)
    right_h += 16
    if badges_g:
        right_h += fh(f_str_hdr) + 4
        right_h += measure_h(', '.join(badges_g), f_str_body, COL_W, dummy, 4)
        right_h += 12
    if badges_w:
        right_h += fh(f_str_hdr) + 4
        right_h += measure_h(', '.join(badges_w), f_str_body, COL_W, dummy, 4)
        right_h += 12

    two_col_h = max(left_h, right_h)
    FOOTER_H  = 40

    # Total canvas height
    photo_block_h = TH_H + PHOTO_PAD * 2
    mod_block_h   = MOD_PAD + fh(f_mod_lbl) + 4 + fh(f_mod_val) + 8 + 4 + MOD_PAD
    CH = (HEADER_H + photo_block_h + 1 + mod_block_h + 1 + PAD + two_col_h + PAD + FOOTER_H)

    canvas = Image.new('RGB', (CW, CH), BG)
    draw   = ImageDraw.Draw(canvas)

    # ── HEADER STRIP ─────────────────────────────────────────────────────────
    draw.rectangle([0, 0, CW, HEADER_H], fill=GOLD)
    draw.text((PAD, 13), 'THE LENS LEAGUE', font=f_brand, fill=BG)
    et  = 'APEX DDI ENGINE  ·  FULL EVALUATION  ·  RATED BY SCIENCE'
    etb = draw.textbbox((0, 0), et, font=f_engine)
    draw.text((CW - PAD - (etb[2]-etb[0]), 16), et, font=f_engine, fill=(50, 40, 10))

    # ── PHOTO + SCORE BLOCK ───────────────────────────────────────────────────
    PB_Y = HEADER_H   # photo block starts here
    draw.rectangle([0, PB_Y, CW, PB_Y + photo_block_h], fill=SURFACE_1)

    # Thumbnail
    TH_X = PAD
    TH_Y = PB_Y + PHOTO_PAD
    try:
        photo = Image.open(photo_path).convert('RGB')
        pw, ph = photo.size
        scale  = max(TH_W/pw, TH_H/ph)
        nw, nh = int(pw*scale), int(ph*scale)
        photo  = photo.resize((nw, nh), Image.LANCZOS)
        cx, cy = (nw-TH_W)//2, (nh-TH_H)//2
        photo  = photo.crop((cx, cy, cx+TH_W, cy+TH_H))
        canvas.paste(photo, (TH_X, TH_Y))
    except Exception:
        draw.rectangle([TH_X, TH_Y, TH_X+TH_W, TH_Y+TH_H], fill=SURFACE_3)

    # Score badge — right of thumbnail
    SB_X = TH_X + TH_W + 20
    SB_W = 110
    SB_H = TH_H
    draw.rectangle([SB_X, TH_Y, SB_X+SB_W, TH_Y+SB_H], fill=GOLD_BG, outline=GOLD_DARK, width=2)

    # Score number
    sc_txt = str(data.get('score', '0.0'))
    sc_bb  = draw.textbbox((0, 0), sc_txt, font=f_score)
    sc_w   = sc_bb[2] - sc_bb[0]
    draw.text((SB_X + (SB_W - sc_w)//2, TH_Y + 20), sc_txt, font=f_score, fill=GOLD)

    # Tier
    tier_txt = data.get('tier', '').upper()
    tier_bb  = draw.textbbox((0, 0), tier_txt, font=f_tier)
    tier_w   = tier_bb[2] - tier_bb[0]
    draw.text((SB_X + (SB_W - tier_w)//2, TH_Y + SB_H - fh(f_tier) - 12), tier_txt, font=f_tier, fill=GOLD)

    # Tier pips
    pip_y = TH_Y + SB_H - fh(f_tier) - 28
    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active   = tier_map.get(tier_txt, 1)
    pip_total_w = 5 * 14 + 4 * 4
    pip_x_start = SB_X + (SB_W - pip_total_w) // 2
    for i in range(5):
        px = pip_x_start + i * 18
        col = GOLD if i < active else BORDER_MD
        draw.rectangle([px, pip_y, px+12, pip_y+6], fill=col)

    # Image info — right of score badge
    IX = SB_X + SB_W + 20
    IY = TH_Y + 8
    IW = CW - IX - PAD

    asset_name = data.get('asset', 'Untitled')
    draw.text((IX, IY), asset_name, font=f_asset, fill=TEXT_1)
    IY += fh(f_asset) + 4

    meta = data.get('meta', '')
    draw.text((IX, IY), meta, font=f_meta, fill=TEXT_2)
    IY += fh(f_meta) + 4

    genre_tag = data.get('genre_tag', '')
    draw.text((IX, IY), genre_tag, font=f_tag, fill=TEXT_3)
    IY += fh(f_tag) + 6

    if data.get('soul_bonus'):
        draw.text((IX, IY), '★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0', font=f_tag, fill=GOLD)
        IY += fh(f_tag) + 4

    if data.get('iucn_tag'):
        draw.text((IX, IY), data['iucn_tag'], font=f_tag, fill=AMBER)
        IY += fh(f_tag) + 4

    IY += 4
    archetype_line = f"Affective State: {data.get('dec','')}  ·  Photographer: {data.get('credit','')}"
    draw_wrapped(draw, archetype_line, f_meta, TEXT_3, IX, IY, IW, 3)

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    DIV1_Y = PB_Y + photo_block_h
    draw.rectangle([0, DIV1_Y, CW, DIV1_Y+1], fill=BORDER_MD)

    # ── MODULE SCORES ─────────────────────────────────────────────────────────
    MB_Y    = DIV1_Y + 1
    MB_H    = mod_block_h
    draw.rectangle([0, MB_Y, CW, MB_Y + MB_H], fill=SURFACE_2)

    modules = data.get('modules', [])
    n       = max(len(modules), 1)
    MW      = (CW - PAD*2) // n
    max_sc  = max((float(s) for _,s in modules if s), default=0)
    MY      = MB_Y + MOD_PAD

    for i, (name, score) in enumerate(modules):
        mx  = PAD + i * MW
        is_top = float(score) == max_sc
        col = GOLD if is_top else TEXT_2

        # Vertical separator
        if i > 0:
            draw.rectangle([mx - 1, MY - 4, mx, MY + fh(f_mod_lbl) + fh(f_mod_val) + 14], fill=BORDER)

        draw.text((mx + 8, MY), name.upper(), font=f_mod_lbl, fill=TEXT_3)
        draw.text((mx + 8, MY + fh(f_mod_lbl) + 4), str(score), font=f_mod_val, fill=col)

        # Bar
        bar_y = MY + fh(f_mod_lbl) + fh(f_mod_val) + 8
        bar_w = MW - 20
        draw.rectangle([mx + 8, bar_y, mx + 8 + bar_w, bar_y + 4], fill=SURFACE_3)
        fill_w = int(bar_w * float(score) / 10)
        bar_col = GOLD if is_top else GOLD_DARK
        draw.rectangle([mx + 8, bar_y, mx + 8 + fill_w, bar_y + 4], fill=bar_col)

    # ── DIVIDER 2 ─────────────────────────────────────────────────────────────
    DIV2_Y = MB_Y + MB_H
    draw.rectangle([0, DIV2_Y, CW, DIV2_Y+1], fill=BORDER_MD)

    # ── TWO COLUMN CONTENT ────────────────────────────────────────────────────
    CY_L = DIV2_Y + 1 + PAD
    CY_R = DIV2_Y + 1 + PAD

    # Gold left border accent
    draw.rectangle([0, DIV2_Y + 1, 3, CH - FOOTER_H], fill=GOLD_DARK)

    # LEFT — five analysis sections
    for label, body in data.get('rows', []):
        lbl = label.replace('\\n', ' ').replace('\n', ' ').upper()
        draw.text((LC_X, CY_L), lbl, font=f_sec_hdr, fill=GOLD)
        CY_L += fh(f_sec_hdr) + 4
        if body and body.strip():
            CY_L = draw_wrapped(draw, body, f_sec_body, TEXT_2, LC_X, CY_L, COL_W, 5)
        CY_L += 14

    # RIGHT — bylines and badges
    # Apex Byline header
    draw.text((RC_X, CY_R), 'APEX BYLINE', font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 4
    if b1:
        CY_R = draw_wrapped(draw, b1, f_byline_b, TEXT_2, RC_X, CY_R, COL_W, 5)
    CY_R += 14

    draw.text((RC_X, CY_R), 'THE ONE IMPROVEMENT', font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 4
    if b2:
        CY_R = draw_wrapped(draw, b2, f_byline_i, TEXT_1, RC_X, CY_R, COL_W, 5)
    CY_R += 16

    if badges_g:
        draw.text((RC_X, CY_R), 'STRENGTHS', font=f_str_hdr, fill=GREEN)
        CY_R += fh(f_str_hdr) + 4
        CY_R = draw_wrapped(draw, ', '.join(badges_g), f_str_body, GREEN, RC_X, CY_R, COL_W, 4)
        CY_R += 12

    if badges_w:
        draw.text((RC_X, CY_R), 'AREAS TO DEVELOP', font=f_str_hdr, fill=RED)
        CY_R += fh(f_str_hdr) + 4
        CY_R = draw_wrapped(draw, ', '.join(badges_w), f_str_body, RED, RC_X, CY_R, COL_W, 4)

    # ── FOOTER STRIP ──────────────────────────────────────────────────────────
    FT_Y = CH - FOOTER_H
    draw.rectangle([0, FT_Y, CW, CH], fill=SURFACE_1)
    draw.rectangle([0, FT_Y, CW, FT_Y+1], fill=BORDER_MD)

    # Footer left — engine credit
    draw.text((PAD, FT_Y + 13), 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.', font=f_footer, fill=TEXT_3)

    # Footer right — score stamp
    stamp = f"LL · {data.get('score','')} · {data.get('tier','').upper()}"
    sb    = draw.textbbox((0,0), stamp, font=f_footer)
    draw.text((CW - PAD - (sb[2]-sb[0]), FT_Y + 13), stamp, font=f_footer, fill=GOLD)

    canvas.save(out_path, 'JPEG', quality=96, optimize=True)
    return out_path
