"""
Apex Rating Card — v19
STRICT single column. No two-column logic anywhere.
Every section stacks below the previous one.
1000px wide, large fonts, generous spacing.
"""

from PIL import Image, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))
F_BOLD   = os.path.join(FONT_DIR, 'LiberationSans-Bold.ttf')
F_REG    = os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')
F_MONO   = os.path.join(FONT_DIR, 'DejaVuSansMono-Bold.ttf')
F_MONO_R = os.path.join(FONT_DIR, 'DejaVuSansMono.ttf')

def fnt(path, size):
    for p in [path,
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = (13,  13,  11)
S1        = (20,  20,  18)
S2        = (28,  28,  26)
S3        = (36,  36,  34)
BORDER_MD = (56,  56,  54)
BORDER    = (42,  42,  40)
T1        = (240, 239, 232)
T2        = (184, 182, 174)
T3        = (122, 120, 112)
GOLD      = (200, 168,  75)
GOLD_D    = (139, 105,  20)
GREEN     = (76,  175, 115)
RED       = (224,  85,  85)
AMBER     = (224, 153,  64)

CW  = 1000
PAD = 48

def fh(font):
    d = ImageDraw.Draw(Image.new('RGB',(1,1)))
    return d.textbbox((0,0),'Ag',font=font)[3] + 4

def wrap(text, font, max_w, draw):
    if not text or not text.strip(): return []
    words, lines, cur = text.split(), [], []
    for w in words:
        test = ' '.join(cur+[w])
        if draw.textbbox((0,0),test,font=font)[2] > max_w and cur:
            lines.append(' '.join(cur)); cur=[w]
        else: cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def text_h(text, font, max_w, draw, sp=8):
    ls = wrap(text, font, max_w, draw)
    return len(ls) * (fh(font) + sp) if ls else 0

def draw_text(draw, text, font, color, x, y, max_w, sp=8):
    """Draw wrapped text. Returns new y position."""
    for line in wrap(text, font, max_w, draw):
        draw.text((x, y), line, font=font, fill=color)
        y += fh(font) + sp
    return y

def rule(draw, y, left=0, right=None, color=None):
    """Draw a horizontal rule. Returns y+1."""
    draw.rectangle([left, y, right or CW, y+1], fill=color or BORDER_MD)
    return y + 1

def build_card(photo_path, data, out_path):

    # ── Fonts ─────────────────────────────────────────────────────────────────
    fBrand   = fnt(F_MONO,   16)
    fEngine  = fnt(F_MONO_R, 13)
    fScore   = fnt(F_BOLD,   80)
    fTier    = fnt(F_MONO,   18)
    fTitle   = fnt(F_BOLD,   26)
    fMeta    = fnt(F_REG,    16)
    fTag     = fnt(F_MONO_R, 14)
    fModLbl  = fnt(F_MONO_R, 14)
    fModVal  = fnt(F_BOLD,   32)
    fSecHdr  = fnt(F_MONO,   14)
    fBody    = fnt(F_REG,    18)   # all body text same size
    fImp     = fnt(F_BOLD,   18)   # improvement text bold
    fBadgeH  = fnt(F_MONO,   14)
    fFooter  = fnt(F_MONO_R, 13)

    W = CW - PAD * 2   # inner content width
    dummy = ImageDraw.Draw(Image.new('RGB', (CW, 10)))

    # ── Extract data ──────────────────────────────────────────────────────────
    rows    = data.get('rows', [])
    b1      = data.get('byline_1', '').strip()
    b2      = data.get('byline_2_body', '').strip()
    bg      = [b for b in data.get('badges_g', []) if b.strip()]
    bw_list = [b for b in data.get('badges_w', []) if b.strip()]
    modules = data.get('modules', [])
    score   = str(data.get('score', '0.0'))
    tier    = data.get('tier', '').upper()

    # ── Calculate total height ────────────────────────────────────────────────
    HEADER_H  = 56
    PHOTO_H   = 560
    SCORE_H   = 160

    # Module row height
    MOD_H = PAD + fh(fModLbl) + 8 + fh(fModVal) + 12 + 6 + PAD

    # Analysis sections
    sec_h = 0
    for _, body in rows:
        sec_h += PAD // 2 + fh(fSecHdr) + 8
        sec_h += text_h(body, fBody, W, dummy, 8) if body.strip() else 0
        sec_h += PAD

    # Byline
    by_h  = PAD + fh(fSecHdr) + 8
    by_h += text_h(b1, fBody, W, dummy, 8)
    by_h += PAD + fh(fSecHdr) + 8
    by_h += text_h(b2, fImp, W, dummy, 8)
    by_h += PAD

    # Badges
    ba_h = 0
    if bg or bw_list:
        ba_h += PAD
        if bg:   ba_h += fh(fBadgeH) + 8 + text_h(', '.join(bg),   fBody, W, dummy, 6) + PAD // 2
        if bw_list: ba_h += fh(fBadgeH) + 8 + text_h(', '.join(bw_list), fBody, W, dummy, 6) + PAD // 2
        ba_h += PAD // 2

    FOOTER_H = 56

    CH = HEADER_H + PHOTO_H + SCORE_H + 1 + MOD_H + 1 + sec_h + 1 + by_h + (1 + ba_h if ba_h else 0) + FOOTER_H

    # ── Build canvas ──────────────────────────────────────────────────────────
    canvas = Image.new('RGB', (CW, CH), BG)
    draw   = ImageDraw.Draw(canvas)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 1. GOLD HEADER                                                      │
    # └─────────────────────────────────────────────────────────────────────┘
    draw.rectangle([0, 0, CW, HEADER_H], fill=GOLD)
    draw.text((PAD, 18), 'THE LENS LEAGUE', font=fBrand, fill=BG)
    et  = 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.'
    etw = draw.textbbox((0,0), et, font=fEngine)[2]
    draw.text((CW - PAD - etw, 21), et, font=fEngine, fill=(40, 30, 5))

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 2. PHOTO — full width                                               │
    # └─────────────────────────────────────────────────────────────────────┘
    PH_Y = HEADER_H
    try:
        ph = Image.open(photo_path).convert('RGB')
        pw, phh = ph.size
        scale = max(CW / pw, PHOTO_H / phh)
        nw, nh = int(pw * scale), int(phh * scale)
        ph = ph.resize((nw, nh), Image.LANCZOS)
        cx, cy = (nw - CW) // 2, (nh - PHOTO_H) // 2
        ph = ph.crop((cx, cy, cx + CW, cy + PHOTO_H))
        canvas.paste(ph, (0, PH_Y))
    except:
        draw.rectangle([0, PH_Y, CW, PH_Y + PHOTO_H], fill=S3)
        draw.text((PAD, PH_Y + 20), 'Image not available', font=fBody, fill=T3)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 3. SCORE BLOCK                                                      │
    # └─────────────────────────────────────────────────────────────────────┘
    SB_Y = HEADER_H + PHOTO_H
    draw.rectangle([0, SB_Y, CW, SB_Y + SCORE_H], fill=S1)

    # Score number — left
    scb = draw.textbbox((0, 0), score, font=fScore)
    scw = scb[2] - scb[0]
    sc_y = SB_Y + (SCORE_H - fh(fScore)) // 2 - 4
    draw.text((PAD, sc_y), score, font=fScore, fill=GOLD)

    # Tier label + pips — next to score
    tx = PAD + scw + 36
    ty = SB_Y + (SCORE_H - fh(fTier)) // 2 - 14
    draw.text((tx, ty), tier, font=fTier, fill=GOLD)

    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active = tier_map.get(tier, 1)
    pip_y = ty + fh(fTier) + 12
    for i in range(5):
        px = tx + i * 22
        draw.rectangle([px, pip_y, px+14, pip_y+8],
                       fill=GOLD if i < active else BORDER_MD)

    # Title + meta — right side
    title = data.get('asset', 'Untitled')
    meta  = data.get('meta', '')
    tw = draw.textbbox((0, 0), title, font=fTitle)[2]
    mw = draw.textbbox((0, 0), meta,  font=fMeta)[2]
    draw.text((CW - PAD - tw, SB_Y + 28), title, font=fTitle, fill=T1)
    draw.text((CW - PAD - mw, SB_Y + 28 + fh(fTitle) + 6), meta, font=fMeta, fill=T2)

    # Affective state + photographer — bottom right
    arch = f"Affective State: {data.get('dec','')}   ·   Photographer: {data.get('credit','')}"
    aw = draw.textbbox((0, 0), arch, font=fTag)[2]
    draw.text((CW - PAD - aw, SB_Y + SCORE_H - fh(fTag) - 20), arch, font=fTag, fill=T3)

    # Soul bonus / IUCN — bottom left
    extra_y = SB_Y + SCORE_H - fh(fTag) - 20
    if data.get('soul_bonus'):
        draw.text((PAD, extra_y), '★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0', font=fTag, fill=GOLD)
    elif data.get('iucn_tag'):
        iucn = data['iucn_tag']
        iu   = iucn.upper()
        ic   = RED if any(x in iu for x in ['CRITICAL','ENDANGERED','VULNERABLE']) \
               else AMBER if 'NEAR' in iu else GREEN
        draw.text((PAD, extra_y), iucn, font=fTag, fill=ic)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 4. MODULE SCORES — full width, single row                          │
    # └─────────────────────────────────────────────────────────────────────┘
    y = rule(draw, SB_Y + SCORE_H)
    draw.rectangle([0, y, CW, y + MOD_H], fill=S2)

    n      = max(len(modules), 1)
    MW     = (CW - PAD * 2) // n
    max_sc = max((float(s) for _, s in modules if s), default=0)
    MY     = y + PAD

    for i, (name, mscore) in enumerate(modules):
        mx  = PAD + i * MW
        top = float(mscore) == max_sc
        col = GOLD if top else T2
        if i > 0:
            draw.rectangle([mx-1, MY-6, mx, MY+fh(fModLbl)+8+fh(fModVal)+16], fill=BORDER)
        draw.text((mx+14, MY), name.upper(), font=fModLbl, fill=T3)
        draw.text((mx+14, MY+fh(fModLbl)+8), str(mscore), font=fModVal, fill=col)
        bar_y = MY + fh(fModLbl) + 8 + fh(fModVal) + 10
        bar_w = MW - 32
        draw.rectangle([mx+14, bar_y, mx+14+bar_w, bar_y+6], fill=S3)
        fw = int(bar_w * float(mscore) / 10)
        draw.rectangle([mx+14, bar_y, mx+14+fw, bar_y+6], fill=GOLD if top else GOLD_D)

    y = rule(draw, y + MOD_H)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 5. ANALYSIS SECTIONS — single column, full width                   │
    # └─────────────────────────────────────────────────────────────────────┘
    y += PAD // 2

    for idx, (label, body) in enumerate(rows):
        lbl = label.replace('\\n', ' ').replace('\n', ' ').upper()

        # Section label in gold
        draw.text((PAD, y), lbl, font=fSecHdr, fill=GOLD)
        y += fh(fSecHdr) + 8

        # Body text — full width, 18pt
        if body and body.strip():
            y = draw_text(draw, body, fBody, T2, PAD, y, W, 8)
        y += PAD

        # Subtle rule between sections (not after last)
        if idx < len(rows) - 1:
            draw.rectangle([PAD, y - PAD//2, CW - PAD, y - PAD//2 + 1], fill=BORDER)

    y = rule(draw, y)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 6. APEX BYLINE — single column, full width                         │
    # └─────────────────────────────────────────────────────────────────────┘
    # Gold left accent bar spans the entire byline section
    byline_start = y
    y += PAD

    draw.text((PAD, y), 'APEX BYLINE', font=fSecHdr, fill=GOLD)
    y += fh(fSecHdr) + 8
    if b1:
        y = draw_text(draw, b1, fBody, T2, PAD, y, W, 8)
    y += PAD

    draw.text((PAD, y), 'THE ONE IMPROVEMENT', font=fSecHdr, fill=GOLD)
    y += fh(fSecHdr) + 8
    if b2:
        y = draw_text(draw, b2, fImp, T1, PAD, y, W, 8)
    y += PAD

    # Draw gold left accent bar for byline section
    draw.rectangle([0, byline_start, 5, y], fill=GOLD_D)

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 7. STRENGTHS & AREAS TO DEVELOP — single column, full width        │
    # └─────────────────────────────────────────────────────────────────────┘
    if bg or bw_list:
        y = rule(draw, y)
        y += PAD

        if bg:
            draw.text((PAD, y), 'STRENGTHS', font=fBadgeH, fill=GREEN)
            y += fh(fBadgeH) + 8
            y = draw_text(draw, ', '.join(bg), fBody, GREEN, PAD, y, W, 6)
            y += PAD // 2

        if bw_list:
            draw.text((PAD, y), 'AREAS TO DEVELOP', font=fBadgeH, fill=RED)
            y += fh(fBadgeH) + 8
            y = draw_text(draw, ', '.join(bw_list), fBody, RED, PAD, y, W, 6)
            y += PAD // 2

        y += PAD // 2

    # ┌─────────────────────────────────────────────────────────────────────┐
    # │ 8. FOOTER                                                           │
    # └─────────────────────────────────────────────────────────────────────┘
    FY = CH - FOOTER_H
    draw.rectangle([0, FY, CW, CH], fill=S1)
    draw.rectangle([0, FY, CW, FY+1], fill=BORDER_MD)
    draw.text((PAD, FY + 20),
              'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  LENS LEAGUE APEX',
              font=fFooter, fill=T3)
    stamp = f"LL · {score} · {tier}"
    sw    = draw.textbbox((0, 0), stamp, font=fFooter)[2]
    draw.text((CW - PAD - sw, FY + 20), stamp, font=fFooter, fill=GOLD)

    canvas.save(out_path, 'JPEG', quality=96, optimize=True)
    return out_path
