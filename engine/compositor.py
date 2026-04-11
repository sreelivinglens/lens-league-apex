"""
Apex Audit Card — JPG Compositor v4
All text scaled up for readability at display size.
Module scores, section labels, body text all significantly larger.
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

# ── Palette ───────────────────────────────────────────────────────────────────
DARK     = (13,  13,  13)
PANEL    = (22,  22,  22)
PANEL2   = (16,  16,  16)
BORDER   = (45,  45,  45)
MUTED    = (90,  90,  90)
GOLD     = (200, 168, 75)
GOLD_L   = (226, 200, 122)
TEXT     = (232, 226, 213)
TEXT_DIM = (190, 183, 170)
GREEN    = (76,  175, 80)
RED      = (229, 57,  53)
RED_L    = (229, 115, 115)

CARD_W   = 2000   # wider card = more pixel budget per element


def wrap_text(text, font, max_width, draw):
    if not text: return ['']
    words, lines, current = text.split(), [], []
    for word in words:
        test = ' '.join(current + [word])
        if draw.textbbox((0, 0), test, font=font)[2] > max_width and current:
            lines.append(' '.join(current))
            current = [word]
        else:
            current.append(word)
    if current: lines.append(' '.join(current))
    return lines or ['']


def lh(font):
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    return d.textbbox((0, 0), "Ag", font=font)[3] + 4


def block_h(lines, font, spacing=10):
    if not lines: return 0
    return len(lines) * lh(font) + max(0, len(lines) - 1) * spacing


def draw_lines(draw, lines, x, y, font, color, spacing=10):
    h = lh(font)
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += h + spacing
    return y


def build_card(photo_path, data, out_path):
    PAD   = 64
    COL   = CARD_W - PAD * 2
    LBL_W = 240   # section label column width
    SPAD  = 36    # section vertical padding

    # ── Fonts — sized for CARD_W=2000 ────────────────────────────────────────
    f_brand      = fnt(F_BOLD,    32)   # THE LENS LEAGUE
    f_engine     = fnt(F_MONO_R,  22)   # APEX DDI ENGINE header right
    f_tag        = fnt(F_MONO_R,  26)   # genre tag on photo
    f_score_big  = fnt(F_BOLD,   100)   # score number on photo badge
    f_score_lbl  = fnt(F_MONO_R,  24)   # MASTER / PRACTITIONER on badge
    f_title      = fnt(F_BOLD,    70)   # asset name on photo
    f_meta       = fnt(F_MONO_R,  26)   # meta line on photo
    f_mod_lbl    = fnt(F_MONO_R,  26)   # DOD / DISRUPTION labels
    f_mod_score  = fnt(F_BOLD,    88)   # module score numbers  ← KEY FIX
    f_sec_lbl    = fnt(F_MONO,    27)   # TECHNICAL INTEGRITY etc.
    f_sec_body   = fnt(F_REG,     36)   # section body text     ← KEY FIX
    f_badge_t    = fnt(F_MONO_R,  24)   # STRENGTHS / GAPS
    f_badge      = fnt(F_MONO_R,  23)   # badge text
    f_bl_title   = fnt(F_MONO,    26)   # APEX BYLINE
    f_bl_body    = fnt(F_REG,     34)   # byline body
    f_bl_imp     = fnt(F_BOLD,    36)   # THE ONE IMPROVEMENT text
    f_arch_lbl   = fnt(F_MONO_R,  22)   # AFFECTIVE STATE label
    f_arch_val   = fnt(F_BOLD,    38)   # archetype value
    f_credit     = fnt(F_REG,     30)   # photographer credit
    f_bot        = fnt(F_MONO_R,  22)   # bottom strip

    # ── Load & crop photo to fixed height ─────────────────────────────────────
    photo  = Image.open(photo_path).convert("RGB")
    PH     = 640   # photo strip height
    pw, ph = photo.size
    scale  = CARD_W / pw
    new_h  = int(ph * scale)
    photo  = photo.resize((CARD_W, new_h), Image.LANCZOS)
    if new_h > PH:
        top   = (new_h - PH) // 3
        photo = photo.crop((0, top, CARD_W, top + PH))
    else:
        PH    = new_h

    # ── Measure heights ───────────────────────────────────────────────────────
    dummy      = ImageDraw.Draw(Image.new("RGB", (CARD_W, 10)))
    sec_heights = []
    for _, body in data.get("rows", []):
        bl = wrap_text(body, f_sec_body, COL - LBL_W - 40, dummy)
        sec_heights.append(max(block_h(bl, f_sec_body, 10) + SPAD * 2, 100))

    b1l   = wrap_text(data.get("byline_1", ""),      f_bl_body, COL, dummy)
    b2l   = wrap_text(data.get("byline_2_body", ""), f_bl_imp,  COL, dummy)
    byl_h = block_h(b1l, f_bl_body, 10) + block_h(b2l, f_bl_imp, 10) + 120

    HDR_H  = 72
    MOD_H  = 200
    BAD_H  = 150
    FTR_H  = 100
    BOT_H  = 68

    TOTAL_H = (HDR_H + PH + MOD_H +
               sum(sec_heights) + 2 * len(sec_heights) +
               byl_h + BAD_H + FTR_H + BOT_H + PAD)

    canvas = Image.new("RGB", (CARD_W, TOTAL_H), DARK)
    draw   = ImageDraw.Draw(canvas)
    y      = 0

    # ── Header strip ──────────────────────────────────────────────────────────
    draw.rectangle([0, 0, CARD_W, HDR_H], fill=GOLD)
    draw.text((PAD, 20), "THE LENS LEAGUE", font=f_brand, fill=DARK)
    et  = "APEX DDI ENGINE  ·  FULL EVALUATION"
    etb = draw.textbbox((0, 0), et, font=f_engine)
    draw.text((CARD_W - PAD - (etb[2]-etb[0]), 24), et, font=f_engine, fill=(50, 40, 5))
    y += HDR_H

    # ── Photo ─────────────────────────────────────────────────────────────────
    canvas.paste(photo, (0, y))
    PT = y

    # Gradient
    G_H  = 320
    grad = Image.new("RGBA", (CARD_W, G_H))
    for i in range(G_H):
        a = int(255 * (i / G_H) ** 1.3)
        grad.paste((13, 13, 13, a), (0, i, CARD_W, i + 1))
    canvas.paste(grad, (0, PT + PH - G_H), grad)

    # Genre tag
    gt  = data.get("genre_tag", "WILDLIFE  ·  JPEG")
    gtb = draw.textbbox((0, 0), gt, font=f_tag)
    draw.rectangle([PAD-14, PT+30, PAD+(gtb[2]-gtb[0])+14, PT+30+(gtb[3]-gtb[1])+18],
                   fill=(13,13,13), outline=GOLD, width=2)
    draw.text((PAD, PT+37), gt, font=f_tag, fill=GOLD)

    # Score badge
    BSZ = 170
    bx  = CARD_W - PAD - BSZ
    by  = PT + 30
    draw.rectangle([bx, by, bx+BSZ, by+BSZ], fill=(10,10,10), outline=GOLD, width=3)
    sc  = str(data.get("score", "0.0"))
    sb  = draw.textbbox((0, 0), sc, font=f_score_big)
    draw.text((bx + (BSZ-(sb[2]-sb[0]))//2, by+8), sc, font=f_score_big, fill=GOLD)
    tier_t = data.get("tier","").upper()
    tierb  = draw.textbbox((0, 0), tier_t, font=f_score_lbl)
    draw.text((bx+(BSZ-(tierb[2]-tierb[0]))//2, by+120), tier_t, font=f_score_lbl, fill=GOLD)

    # Soul bonus / IUCN
    tag_y = PT + PH - 88
    if data.get("soul_bonus"):
        st  = "★  SOUL BONUS ACTIVE"
        stb = draw.textbbox((0,0), st, font=f_tag)
        sx  = CARD_W - PAD - (stb[2]-stb[0]) - 24
        draw.rectangle([sx-16, tag_y-10, sx+(stb[2]-stb[0])+16, tag_y+(stb[3]-stb[1])+12],
                       fill=(30,25,5), outline=GOLD, width=2)
        draw.text((sx, tag_y), st, font=f_tag, fill=GOLD)
    if data.get("iucn_tag"):
        it  = data["iucn_tag"]
        itb = draw.textbbox((0,0), it, font=f_tag)
        ix  = CARD_W - PAD - (itb[2]-itb[0]) - 24
        draw.rectangle([ix-16, tag_y-10, ix+(itb[2]-itb[0])+16, tag_y+(itb[3]-itb[1])+12],
                       fill=(40,10,10), outline=(180,50,50), width=2)
        draw.text((ix, tag_y), it, font=f_tag, fill=RED_L)

    # Title & meta
    ty = PT + PH - 140
    draw.text((PAD, ty),     data.get("asset",""), font=f_title, fill=TEXT)
    draw.text((PAD, ty+80),  data.get("meta", ""), font=f_meta,  fill=GOLD_L)
    y += PH

    # ── Module row ────────────────────────────────────────────────────────────
    draw.rectangle([0, y, CARD_W, y+MOD_H], fill=PANEL)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)

    modules = data.get("modules", [])
    n       = len(modules) or 1
    cell_w  = CARD_W // n
    max_sc  = max((s for _,s in modules), default=0)

    for i, (name, score) in enumerate(modules):
        cx = i * cell_w
        if i > 0:
            draw.rectangle([cx, y+22, cx+1, y+MOD_H-22], fill=BORDER)
        draw.text((cx+28, y+20), name.upper(), font=f_mod_lbl, fill=TEXT_DIM)
        col = GOLD if score == max_sc else TEXT
        draw.text((cx+28, y+46), str(score), font=f_mod_score, fill=col)
        bx2 = cx+28
        by2 = y+MOD_H-30
        bw  = cell_w-56
        draw.rectangle([bx2, by2, bx2+bw, by2+6], fill=MUTED)
        fw  = int(bw * float(score)/10)
        draw.rectangle([bx2, by2, bx2+fw, by2+6],
                       fill=GOLD if score==max_sc else (160,130,60))
    y += MOD_H

    # ── Section rows ──────────────────────────────────────────────────────────
    for idx, (label, body) in enumerate(data.get("rows", [])):
        bl    = wrap_text(body, f_sec_body, COL-LBL_W-40, draw)
        row_h = sec_heights[idx]
        bg    = PANEL2 if idx%2==0 else (19,19,19)
        draw.rectangle([0, y, CARD_W, y+row_h], fill=bg)
        draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)

        # Label column
        draw.rectangle([0, y, LBL_W, y+row_h], fill=(20,17,8))
        parts  = label.replace("\\n","\n").split("\n")
        lh_e   = lh(f_sec_lbl)
        total  = len(parts)*lh_e + max(0,len(parts)-1)*6
        ly     = y + (row_h-total)//2
        for p in parts:
            draw.text((18, ly), p.upper(), font=f_sec_lbl, fill=GOLD)
            ly += lh_e + 6

        draw.rectangle([LBL_W, y+18, LBL_W+1, y+row_h-18], fill=BORDER)
        draw_lines(draw, bl, LBL_W+30, y+SPAD, f_sec_body, TEXT_DIM, 10)
        y += row_h

    # ── Badges ────────────────────────────────────────────────────────────────
    draw.rectangle([0, y, CARD_W, y+BAD_H], fill=PANEL)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    draw.text((PAD, y+20), "STRENGTHS", font=f_badge_t, fill=TEXT_DIM)
    bxp = PAD
    for badge in data.get("badges_g", []):
        if not badge.strip(): continue
        bb = draw.textbbox((0,0), badge, font=f_badge)
        bw = bb[2]-bb[0]+30
        if bxp+bw > CARD_W//2-PAD: break
        draw.rectangle([bxp, y+56, bxp+bw, y+104], fill=(10,24,10), outline=GREEN, width=2)
        draw.text((bxp+15, y+65), badge, font=f_badge, fill=GREEN)
        bxp += bw+12

    half = CARD_W//2
    draw.text((half+PAD, y+20), "GAPS", font=f_badge_t, fill=TEXT_DIM)
    bxp = half+PAD
    for badge in data.get("badges_w", []):
        if not badge.strip(): continue
        bb = draw.textbbox((0,0), badge, font=f_badge)
        bw = bb[2]-bb[0]+30
        if bxp+bw > CARD_W-PAD: break
        draw.rectangle([bxp, y+56, bxp+bw, y+104], fill=(24,8,8), outline=RED, width=2)
        draw.text((bxp+15, y+65), badge, font=f_badge, fill=RED)
        bxp += bw+12
    y += BAD_H

    # ── Apex Byline ───────────────────────────────────────────────────────────
    draw.rectangle([0, y, CARD_W, y+1], fill=GOLD)
    draw.rectangle([0, y+1, CARD_W, y+byl_h], fill=(16,14,6))
    draw.rectangle([0, y+1, 7, y+byl_h], fill=GOLD)
    draw.text((PAD, y+26), "APEX BYLINE", font=f_bl_title, fill=GOLD)
    cy  = y+68
    cy  = draw_lines(draw, b1l, PAD, cy, f_bl_body, TEXT_DIM, 10)
    cy += 30
    draw.text((PAD, cy), "THE ONE IMPROVEMENT:", font=f_bl_title, fill=GOLD)
    cy += 42
    draw_lines(draw, b2l, PAD, cy, f_bl_imp, TEXT, 10)
    y += byl_h

    # ── Footer ────────────────────────────────────────────────────────────────
    draw.rectangle([0, y, CARD_W, y+FTR_H], fill=PANEL2)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    draw.text((PAD, y+16), "AFFECTIVE STATE", font=f_arch_lbl, fill=TEXT_DIM)
    draw.text((PAD, y+44), data.get("dec",""), font=f_arch_val, fill=GOLD)
    cred = data.get("credit","")
    cb   = draw.textbbox((0,0), cred, font=f_credit)
    draw.text((CARD_W-PAD-(cb[2]-cb[0]), y+34), cred, font=f_credit, fill=TEXT_DIM)
    y += FTR_H

    # ── Bottom strip ──────────────────────────────────────────────────────────
    draw.rectangle([0, y, CARD_W, y+BOT_H], fill=(8,8,8))
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    draw.text((PAD, y+23), "APEX DDI ENGINE  ·  LENS LEAGUE", font=f_bot, fill=MUTED)

    tier_map = {"APPRENTICE":1,"PRACTITIONER":2,"MASTER":3,"GRANDMASTER":4,"LEGEND":5}
    active   = tier_map.get(data.get("tier","").upper(), 2)
    px, py2  = CARD_W//2-80, y+24
    for i in range(5):
        col = GOLD if i<active else MUTED
        draw.rectangle([px+i*34, py2, px+i*34+22, py2+22],
                       fill=col if i<active else None, outline=col, width=2)

    sc_txt = f"LL-SCORE  {data.get('score','')}  ·  {data.get('tier','').upper()}"
    scb    = draw.textbbox((0,0), sc_txt, font=f_bot)
    draw.text((CARD_W-PAD-(scb[2]-scb[0]), y+23), sc_txt, font=f_bot, fill=MUTED)

    canvas.save(out_path, "JPEG", quality=93, optimize=True)
    return out_path
