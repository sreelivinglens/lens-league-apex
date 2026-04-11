"""
Apex Audit Card — v10
Canvas: 900px wide, dynamic height
Designed to be read at screen size without zooming
Photo: 220x148 thumbnail top-left
White background, black text, gold accents
"""

from PIL import Image, ImageDraw, ImageFont
import os

L = "/usr/share/fonts/truetype/liberation/"
D = "/usr/share/fonts/truetype/dejavu/"
F_BOLD   = L + "LiberationSans-Bold.ttf"
F_REG    = L + "LiberationSans-Regular.ttf"
F_MONO   = D + "DejaVuSansMono-Bold.ttf"
F_MONO_R = D + "DejaVuSansMono.ttf"
if not os.path.exists(F_BOLD):  F_BOLD  = D + "DejaVuSans-Bold.ttf"
if not os.path.exists(F_REG):   F_REG   = D + "DejaVuSans.ttf"

def fnt(path, size):
    try:    return ImageFont.truetype(path, size)
    except: return ImageFont.load_default()

BG       = (255, 255, 255)
BLACK    = (20,  20,  20)
GREY     = (90,  90,  90)
LGREY    = (210, 210, 210)
GOLD     = (170, 130, 30)
GOLD_BG  = (255, 250, 230)
GREEN    = (35,  130, 45)
RED      = (190, 35,  35)
STRIP_BG = (28,  28,  28)

CW         = 900
TH_W, TH_H = 220, 148
PAD        = 24


def fh(font):
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    return d.textbbox((0, 0), 'Ag', font=font)[3] + 5


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


def measure_h(text, font, max_w, draw, spacing=5):
    lines = wrap(text, font, max_w, draw)
    if not lines:
        return 0
    return len(lines) * fh(font) + max(0, len(lines) - 1) * spacing


def draw_wrapped(draw, text, font, color, x, y, max_w, spacing=5):
    for line in wrap(text, font, max_w, draw):
        draw.text((x, y), line, font=font, fill=color)
        y += fh(font) + spacing
    return y


def build_card(photo_path, data, out_path):

    # ── Fonts — sized for 900px canvas, readable at screen size ───────────────
    f_strip = fnt(F_BOLD, 15)
    f_score    = fnt(F_BOLD,    52)   # big score — unchanged intention
    f_tier = fnt(F_MONO, 13)
    f_asset = fnt(F_BOLD, 19)   # title — unchanged intention
    f_meta = fnt(F_REG, 13)
    f_tag = fnt(F_MONO_R, 12)
    f_mod_lbl = fnt(F_MONO_R, 12)
    f_mod_val = fnt(F_BOLD, 24)
    f_sec_hdr = fnt(F_MONO, 12)
    f_sec_body = fnt(F_REG, 14)
    f_byline_h = fnt(F_MONO, 12)
    f_byline_b = fnt(F_REG, 14)
    f_byline_i = fnt(F_BOLD, 14)
    f_badge = fnt(F_MONO_R, 12)

    dummy = ImageDraw.Draw(Image.new("RGB", (CW, 10)))

    # ── Column layout ─────────────────────────────────────────────────────────
    COL_GAP = 24
    COL_W   = (CW - PAD * 2 - COL_GAP) // 2
    LC_X    = PAD
    RC_X    = PAD + COL_W + COL_GAP

    # ── Measure all content heights ───────────────────────────────────────────
    STRIP_H     = 28
    TH_X, TH_Y  = PAD, STRIP_H + PAD
    photo_row_h = TH_H + 18
    mod_row_h   = fh(f_mod_lbl) + fh(f_mod_val) + 14 + 10

    # Left column
    left_h = 0
    for _, body in data.get("rows", []):
        left_h += fh(f_sec_hdr) + 3
        left_h += measure_h(body, f_sec_body, COL_W, dummy, 4) if body.strip() else 0
        left_h += 12

    # Right column
    right_h = 0
    b1 = data.get("byline_1", "").strip()
    b2 = data.get("byline_2_body", "").strip()
    right_h += fh(f_byline_h) + 3
    right_h += measure_h(b1, f_byline_b, COL_W, dummy, 4) if b1 else 0
    right_h += 12
    right_h += fh(f_byline_h) + 3
    right_h += measure_h(b2, f_byline_i, COL_W, dummy, 4) if b2 else 0
    right_h += 14

    def badge_h(badges):
        if not badges: return 0
        h = fh(f_byline_h) + 4
        bx, rows = 0, 1
        for b in badges:
            bb = dummy.textbbox((0, 0), b, font=f_badge)
            bw = bb[2] - bb[0] + 16
            if bx + bw > COL_W:
                rows += 1; bx = 0
            bx += bw + 6
        h += rows * (fh(f_badge) + 8) + 8
        return h

    badges_g = [b for b in data.get("badges_g", []) if b.strip()]
    badges_w = [b for b in data.get("badges_w", []) if b.strip()]
    right_h += badge_h(badges_g) + badge_h(badges_w)

    two_col_h = max(left_h, right_h)
    BOT_H     = 28

    CH = STRIP_H + PAD + photo_row_h + 1 + 14 + mod_row_h + 1 + 14 + two_col_h + 16 + BOT_H

    # ── Canvas ────────────────────────────────────────────────────────────────
    canvas = Image.new("RGB", (CW, CH), BG)
    draw   = ImageDraw.Draw(canvas)

    # ── Top strip ─────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, CW, STRIP_H], fill=STRIP_BG)
    draw.text((PAD, 8), "THE LENS LEAGUE", font=f_strip, fill=(200, 168, 75))
    et  = "APEX DDI ENGINE  ·  FULL EVALUATION"
    etb = draw.textbbox((0, 0), et, font=f_strip)
    draw.text((CW - PAD - (etb[2] - etb[0]), 8), et, font=f_strip, fill=(150, 120, 50))

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    photo = Image.open(photo_path).convert("RGB")
    pw, ph = photo.size
    scale  = max(TH_W / pw, TH_H / ph)
    nw, nh = int(pw * scale), int(ph * scale)
    photo  = photo.resize((nw, nh), Image.LANCZOS)
    cx, cy = (nw - TH_W) // 2, (nh - TH_H) // 2
    photo  = photo.crop((cx, cy, cx + TH_W, cy + TH_H))
    canvas.paste(photo, (TH_X, TH_Y))
    draw.rectangle([TH_X - 1, TH_Y - 1, TH_X + TH_W, TH_Y + TH_H], outline=LGREY, width=1)

    # ── Score badge ───────────────────────────────────────────────────────────
    BX, BY = TH_X + TH_W + 16, TH_Y
    BW, BH = 100, TH_H
    draw.rectangle([BX, BY, BX + BW, BY + BH], fill=GOLD_BG, outline=GOLD, width=2)
    sc  = str(data.get("score", "0.0"))
    sb  = draw.textbbox((0, 0), sc, font=f_score)
    draw.text((BX + (BW - (sb[2] - sb[0])) // 2, BY + 18), sc, font=f_score, fill=GOLD)
    tier_t = data.get("tier", "").upper()
    tierb  = draw.textbbox((0, 0), tier_t, font=f_tier)
    draw.text((BX + (BW - (tierb[2] - tierb[0])) // 2, BY + 96), tier_t, font=f_tier, fill=GOLD)

    # ── Info ──────────────────────────────────────────────────────────────────
    IX = BX + BW + 16
    IY = TH_Y + 6
    IW = CW - IX - PAD

    draw.text((IX, IY), data.get("asset", ""), font=f_asset, fill=BLACK)
    IY += fh(f_asset) + 2
    draw.text((IX, IY), data.get("meta", ""), font=f_meta, fill=GREY)
    IY += fh(f_meta) + 2
    draw.text((IX, IY), data.get("genre_tag", ""), font=f_tag, fill=GREY)
    IY += fh(f_tag) + 4

    if data.get("soul_bonus"):
        draw.text((IX, IY), "★  SOUL BONUS ACTIVE", font=f_tag, fill=GOLD)
        IY += fh(f_tag) + 3
    if data.get("iucn_tag"):
        draw.text((IX, IY), data["iucn_tag"], font=f_tag, fill=RED)
        IY += fh(f_tag) + 3

    combined = (f"Affective State:  {data.get('dec', '')}"
                f"   ·   Photographer:  {data.get('credit', '')}")
    draw.text((IX, IY), combined, font=f_meta, fill=BLACK)

    # ── Divider ───────────────────────────────────────────────────────────────
    D1Y = TH_Y + TH_H + 14
    draw.rectangle([PAD, D1Y, CW - PAD, D1Y + 1], fill=LGREY)

    # ── Module scores ─────────────────────────────────────────────────────────
    MY      = D1Y + 10
    modules = data.get("modules", [])
    n       = max(len(modules), 1)
    MW      = (CW - PAD * 2) // n
    max_sc  = max((float(s) for _, s in modules), default=0)

    for i, (name, score) in enumerate(modules):
        mx  = PAD + i * MW
        col = GOLD if float(score) == max_sc else BLACK
        draw.text((mx, MY), name.upper(), font=f_mod_lbl, fill=GREY)
        draw.text((mx, MY + fh(f_mod_lbl) + 1), str(score), font=f_mod_val, fill=col)
        bar_x = mx
        bar_y = MY + fh(f_mod_lbl) + fh(f_mod_val) + 4
        bar_w = MW - 16
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 4], fill=LGREY)
        fw = int(bar_w * float(score) / 10)
        draw.rectangle([bar_x, bar_y, bar_x + fw, bar_y + 4],
                       fill=GOLD if float(score) == max_sc else (160, 130, 50))
        if i > 0:
            draw.rectangle([mx - 1, MY, mx, bar_y + 4], fill=LGREY)

    # ── Divider ───────────────────────────────────────────────────────────────
    D2Y = MY + fh(f_mod_lbl) + fh(f_mod_val) + 12
    draw.rectangle([PAD, D2Y, CW - PAD, D2Y + 1], fill=LGREY)

    # ── Two columns ───────────────────────────────────────────────────────────
    CY_L = D2Y + 12
    CY_R = D2Y + 12

    # LEFT — sections
    for label, body in data.get("rows", []):
        lbl = label.replace("\\n", " ").replace("\n", " ")
        draw.text((LC_X, CY_L), lbl.upper(), font=f_sec_hdr, fill=GOLD)
        CY_L += fh(f_sec_hdr) + 3
        if body and body.strip():
            CY_L = draw_wrapped(draw, body, f_sec_body, BLACK, LC_X, CY_L, COL_W, 4)
        CY_L += 12

    # RIGHT — byline
    draw.text((RC_X, CY_R), "APEX BYLINE", font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 3
    if b1:
        CY_R = draw_wrapped(draw, b1, f_byline_b, BLACK, RC_X, CY_R, COL_W, 4)
    CY_R += 12

    draw.text((RC_X, CY_R), "THE ONE IMPROVEMENT:", font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 3
    if b2:
        CY_R = draw_wrapped(draw, b2, f_byline_i, BLACK, RC_X, CY_R, COL_W, 4)
    CY_R += 14

    if badges_g:
        draw.text((RC_X, CY_R), "STRENGTHS", font=f_byline_h, fill=GREEN)
        CY_R += fh(f_byline_h) + 4
        bx_pos = RC_X
        for badge in badges_g:
            bb = draw.textbbox((0, 0), badge, font=f_badge)
            bw = bb[2] - bb[0] + 16
            if bx_pos + bw > RC_X + COL_W:
                bx_pos = RC_X; CY_R += fh(f_badge) + 8
            draw.rectangle([bx_pos, CY_R - 1, bx_pos + bw, CY_R + fh(f_badge) + 3],
                           fill=(240, 255, 240), outline=GREEN, width=1)
            draw.text((bx_pos + 8, CY_R), badge, font=f_badge, fill=GREEN)
            bx_pos += bw + 6
        CY_R += fh(f_badge) + 14

    if badges_w:
        draw.text((RC_X, CY_R), "GAPS", font=f_byline_h, fill=RED)
        CY_R += fh(f_byline_h) + 4
        bx_pos = RC_X
        for badge in badges_w:
            bb = draw.textbbox((0, 0), badge, font=f_badge)
            bw = bb[2] - bb[0] + 16
            if bx_pos + bw > RC_X + COL_W:
                bx_pos = RC_X; CY_R += fh(f_badge) + 8
            draw.rectangle([bx_pos, CY_R - 1, bx_pos + bw, CY_R + fh(f_badge) + 3],
                           fill=(255, 240, 240), outline=RED, width=1)
            draw.text((bx_pos + 8, CY_R), badge, font=f_badge, fill=RED)
            bx_pos += bw + 6

    # ── Bottom strip ──────────────────────────────────────────────────────────
    BOT_Y = CH - BOT_H
    draw.rectangle([0, BOT_Y, CW, CH], fill=STRIP_BG)

    tier_map = {"APPRENTICE":1,"PRACTITIONER":2,"MASTER":3,"GRANDMASTER":4,"LEGEND":5}
    active   = tier_map.get(data.get("tier", "").upper(), 2)
    pip_x, pip_y = CW // 2 - 40, BOT_Y + 9
    for i in range(5):
        col = (200, 168, 75) if i < active else (70, 70, 70)
        draw.rectangle([pip_x + i * 18, pip_y, pip_x + i * 18 + 12, pip_y + 10],
                       fill=col if i < active else None, outline=col, width=1)

    sc_txt = f"LL  {data.get('score', '')}  ·  {data.get('tier', '').upper()}"
    scb    = draw.textbbox((0, 0), sc_txt, font=f_strip)
    draw.text((CW - PAD - (scb[2] - scb[0]), BOT_Y + 8), sc_txt, font=f_strip, fill=(150, 120, 50))
    draw.text((PAD, BOT_Y + 8), "APEX DDI ENGINE", font=f_strip, fill=(100, 90, 70))

    canvas.save(out_path, "JPEG", quality=95, optimize=True)
    return out_path
