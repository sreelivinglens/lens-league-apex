"""
Apex Audit Card — JPG Compositor
Ported from build_apex_jpg.py into a reusable module.
"""

from PIL import Image, ImageDraw, ImageFont
import os

# ── Font paths ────────────────────────────────────────────────────────────────
def _fp(name):
    """Try multiple font locations."""
    candidates = [
        f"/usr/share/fonts/truetype/google-fonts/{name}",
        f"/usr/share/fonts/truetype/liberation/{name}",
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/app/fonts/{name}",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

F_BOLD   = _fp("Poppins-Bold.ttf")   or _fp("LiberationSans-Bold.ttf")
F_MED    = _fp("Poppins-Medium.ttf") or _fp("LiberationSans-Bold.ttf")
F_REG    = _fp("Poppins-Regular.ttf")or _fp("LiberationSans-Regular.ttf")
F_LIGHT  = _fp("Poppins-Light.ttf")  or _fp("LiberationSans-Regular.ttf")
F_MONO   = _fp("LiberationMono-Bold.ttf")
F_MONO_R = _fp("LiberationMono-Regular.ttf")

def fnt(path, size):
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ── Palette ───────────────────────────────────────────────────────────────────
DARK    = (13,  13,  13)
PANEL   = (18,  18,  18)
PANEL2  = (10,  10,  10)
BORDER  = (35,  35,  35)
MUTED   = (58,  58,  58)
GOLD    = (200, 168, 75)
GOLD_L  = (226, 200, 122)
TEXT    = (232, 226, 213)
TEXT_DIM= (136, 136, 136)
GREEN   = (76,  175, 80)
RED     = (229, 57,  53)
RED_L   = (229, 115, 115)
CARD_W  = 1400


def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines, current = [], []
    for word in words:
        test = ' '.join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(' '.join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(' '.join(current))
    return lines


def text_h(lines, font, spacing=6):
    if not lines:
        return 0
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lh = d.textbbox((0, 0), "Ag", font=font)[3]
    return len(lines) * lh + (len(lines) - 1) * spacing


def draw_text_lines(draw, lines, x, y, font, color, spacing=6):
    d = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lh = d.textbbox((0, 0), "Ag", font=font)[3]
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += lh + spacing
    return y


def build_card(photo_path, data, out_path):
    today_str = data.get('date', '')
    PAD = 48
    COL = CARD_W - PAD * 2

    # Load fonts
    f_section_body = fnt(F_LIGHT, 27)
    f_byline_body  = fnt(F_LIGHT, 27)
    f_byline_2     = fnt(F_MED,   27)

    # Measure heights
    dummy_img  = Image.new("RGB", (CARD_W, 100))
    dummy_draw = ImageDraw.Draw(dummy_img)

    SECTION_PAD = 28
    section_heights = []
    for label, body in data["rows"]:
        body_lines = wrap_text(body, f_section_body, COL - 180, dummy_draw)
        bh = text_h(body_lines, f_section_body, 8)
        section_heights.append(bh + SECTION_PAD * 2)

    b1_lines = wrap_text(data["byline_1"],    f_byline_body, COL - 40, dummy_draw)
    b2_lines = wrap_text(data["byline_2_body"], f_byline_2,  COL - 40, dummy_draw)
    b1h = text_h(b1_lines, f_byline_body, 8)
    b2h = text_h(b2_lines, f_byline_2, 8)
    byline_h = b1h + b2h + 80 + SECTION_PAD * 2

    # Load & resize photo
    photo = Image.open(photo_path).convert("RGB")
    ph_w, ph_h = photo.size
    target_h = max(int(CARD_W * ph_h / ph_w * 0.55), 520)
    photo = photo.resize((CARD_W, target_h), Image.LANCZOS)

    header_h    = 52
    module_h    = 140
    badges_h    = 110
    footer_h    = 70
    bottom_h    = 52

    total_below = (
        module_h +
        sum(section_heights) + 2 * len(section_heights) +
        byline_h + 2 +
        badges_h + footer_h + bottom_h + PAD
    )
    TOTAL_H = header_h + target_h + total_below

    canvas = Image.new("RGB", (CARD_W, TOTAL_H), DARK)
    draw   = ImageDraw.Draw(canvas)
    y = 0

    # Header strip
    draw.rectangle([0, 0, CARD_W, header_h], fill=GOLD)
    draw.text((PAD, 15), "THE LENS LEAGUE",
              font=fnt(F_BOLD, 22), fill=DARK)
    etxt = "APEX DDI ENGINE  ·  FULL EVALUATION"
    eb = draw.textbbox((0,0), etxt, font=fnt(F_MONO_R, 17))
    draw.text((CARD_W - PAD - (eb[2]-eb[0]), 17), etxt,
              font=fnt(F_MONO_R, 17), fill=(60,50,10))
    y += header_h

    # Photo
    canvas.paste(photo, (0, y))
    photo_top = y

    # Gradient
    grad_h   = 220
    grad_img = Image.new("RGBA", (CARD_W, grad_h))
    for i in range(grad_h):
        alpha = int(255 * (i / grad_h) ** 1.5)
        grad_img.paste((13,13,13,alpha), (0, i, CARD_W, i+1))
    canvas.paste(grad_img, (0, photo_top + target_h - grad_h), grad_img)

    # Genre tag
    f_tag = fnt(F_MONO_R, 17)
    tag_txt = data.get("genre_tag", "WILDLIFE · CAMERA RAW")
    tb = draw.textbbox((0,0), tag_txt, font=f_tag)
    tw, th = tb[2]-tb[0], tb[3]-tb[1]
    tag_x, tag_y = PAD, photo_top + 28
    draw.rectangle([tag_x-12, tag_y-8, tag_x+tw+12, tag_y+th+10],
                   fill=(13,13,13), outline=GOLD, width=1)
    draw.text((tag_x, tag_y), tag_txt, font=f_tag, fill=GOLD)

    # Score badge
    badge_size = 110
    bx = CARD_W - PAD - badge_size
    by = photo_top + 28
    draw.rectangle([bx, by, bx+badge_size, by+badge_size],
                   fill=(13,13,13), outline=GOLD, width=2)
    f_sc  = fnt(F_BOLD, 58)
    f_tier = fnt(F_MONO_R, 14)
    sc = str(data["score"])
    sb = draw.textbbox((0,0), sc, font=f_sc)
    draw.text((bx + (badge_size-(sb[2]-sb[0]))//2, by+10), sc, font=f_sc, fill=GOLD)
    tier_txt = data["tier"].upper()
    tierb = draw.textbbox((0,0), tier_txt, font=f_tier)
    draw.text((bx + (badge_size-(tierb[2]-tierb[0]))//2, by+80),
              tier_txt, font=f_tier, fill=GOLD)

    # Soul Bonus / IUCN tags
    if data.get("soul_bonus"):
        sb_txt = "★  SOUL BONUS ACTIVE"
        f_sbt = fnt(F_MONO_R, 15)
        sbb = draw.textbbox((0,0), sb_txt, font=f_sbt)
        sbw = sbb[2]-sbb[0]
        sx = CARD_W - PAD - sbw - 20
        sy = photo_top + target_h - 72
        draw.rectangle([sx-12, sy-7, sx+sbw+12, sy+sbb[3]-sbb[1]+8],
                       fill=(30,25,5), outline=GOLD, width=1)
        draw.text((sx, sy), sb_txt, font=f_sbt, fill=GOLD)

    if data.get("iucn_tag"):
        iu_txt = data["iucn_tag"]
        f_iu = fnt(F_MONO_R, 15)
        iub = draw.textbbox((0,0), iu_txt, font=f_iu)
        iuw = iub[2]-iub[0]
        ix = CARD_W - PAD - iuw - 20
        iy = photo_top + target_h - 72
        draw.rectangle([ix-12, iy-7, ix+iuw+12, iy+iub[3]-iub[1]+8],
                       fill=(40,10,10), outline=(180,50,50), width=1)
        draw.text((ix, iy), iu_txt, font=f_iu, fill=RED_L)

    # Asset title
    f_asset = fnt(F_BOLD, 44)
    f_meta  = fnt(F_MONO_R, 17)
    title_y = photo_top + target_h - 100
    draw.text((PAD, title_y),    data["asset"], font=f_asset, fill=TEXT)
    draw.text((PAD, title_y+52), data["meta"],  font=f_meta,  fill=GOLD_L)
    y += target_h

    # Modules
    draw.rectangle([0, y, CARD_W, y+module_h], fill=PANEL)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    modules = data["modules"]
    n       = len(modules)
    cell_w  = CARD_W // n
    max_sc  = max(s for _, s in modules)
    f_ml = fnt(F_MONO_R, 17)
    f_ms = fnt(F_BOLD, 54)
    for i, (name, score) in enumerate(modules):
        cx = i * cell_w
        if i > 0:
            draw.rectangle([cx, y+16, cx+1, y+module_h-16], fill=BORDER)
        draw.text((cx+24, y+18), name.upper(), font=f_ml, fill=TEXT_DIM)
        sc_col = GOLD if score == max_sc else TEXT
        draw.text((cx+24, y+38), str(score), font=f_ms, fill=sc_col)
        bar_x = cx + 24
        bar_y = y + module_h - 22
        bar_w = cell_w - 48
        draw.rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+3], fill=MUTED)
        fw = int(bar_w * score / 10)
        draw.rectangle([bar_x, bar_y, bar_x+fw, bar_y+3],
                       fill=GOLD if score == max_sc else (160,130,60))
    y += module_h

    # Section rows
    f_lbl = fnt(F_MONO, 19)
    f_bod = fnt(F_LIGHT, 27)
    LABEL_W = 170
    for idx, (label, body) in enumerate(data["rows"]):
        body_lines = wrap_text(body, f_bod, COL - LABEL_W - 24, draw)
        bh  = text_h(body_lines, f_bod, 7)
        row_h = bh + SECTION_PAD*2
        bg = PANEL2 if idx % 2 == 0 else (14,14,14)
        draw.rectangle([0, y, CARD_W, y+row_h], fill=bg)
        draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
        draw.rectangle([0, y, LABEL_W, y+row_h], fill=(16,14,8))
        lparts = label.replace("\\n", "\n").split("\n")
        lh_each = draw.textbbox((0,0),"Ag",font=f_lbl)[3]
        label_total_h = len(lparts)*lh_each + (len(lparts)-1)*6
        lsy = y + (row_h - label_total_h)//2
        for lp in lparts:
            draw.text((16, lsy), lp, font=f_lbl, fill=GOLD)
            lsy += lh_each + 6
        draw.rectangle([LABEL_W, y+12, LABEL_W+1, y+row_h-12], fill=BORDER)
        draw_text_lines(draw, body_lines, LABEL_W+24, y+SECTION_PAD, f_bod, TEXT_DIM, 7)
        y += row_h

    # Badges
    draw.rectangle([0, y, CARD_W, y+badges_h], fill=PANEL)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    f_bt = fnt(F_MONO_R, 16)
    draw.text((PAD, y+16), "STRENGTHS", font=f_bt, fill=TEXT_DIM)
    bx_pos = PAD
    for badge in data["badges_g"]:
        bb = draw.textbbox((0,0), badge, font=f_bt)
        bw = bb[2]-bb[0]+24
        if bx_pos + bw > CARD_W//2 - PAD:
            break
        draw.rectangle([bx_pos, y+44, bx_pos+bw, y+76], fill=(10,22,10), outline=GREEN, width=1)
        draw.text((bx_pos+12, y+51), badge, font=f_bt, fill=GREEN)
        bx_pos += bw + 10
    half = CARD_W//2
    draw.text((half+PAD, y+16), "GAPS", font=f_bt, fill=TEXT_DIM)
    bx_pos = half + PAD
    for badge in data["badges_w"]:
        bb = draw.textbbox((0,0), badge, font=f_bt)
        bw = bb[2]-bb[0]+24
        if bx_pos + bw > CARD_W - PAD:
            break
        draw.rectangle([bx_pos, y+44, bx_pos+bw, y+76], fill=(22,8,8), outline=RED, width=1)
        draw.text((bx_pos+12, y+51), badge, font=f_bt, fill=RED)
        bx_pos += bw + 10
    y += badges_h

    # Apex Byline
    draw.rectangle([0, y, CARD_W, y+1], fill=GOLD)
    draw.rectangle([0, y+1, CARD_W, y+byline_h], fill=(15,13,5))
    draw.rectangle([0, y+1, 4, y+byline_h], fill=GOLD)
    f_bl  = fnt(F_LIGHT, 27)
    f_bli = fnt(F_MED, 27)
    f_blt = fnt(F_MONO, 18)
    draw.text((PAD, y+20), "APEX BYLINE", font=f_blt, fill=GOLD)
    b1l = wrap_text(data["byline_1"], f_bl, COL-8, draw)
    cy = y + 52
    cy = draw_text_lines(draw, b1l, PAD, cy, f_bl, TEXT_DIM, 7)
    cy += 22
    draw.text((PAD, cy), "THE ONE IMPROVEMENT:", font=f_blt, fill=GOLD)
    cy += 32
    b2l = wrap_text(data["byline_2_body"], f_bli, COL-8, draw)
    draw_text_lines(draw, b2l, PAD, cy, f_bli, TEXT, 7)
    y += byline_h

    # Footer
    draw.rectangle([0, y, CARD_W, y+footer_h], fill=PANEL2)
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    f_av = fnt(F_BOLD, 26)
    f_al = fnt(F_MONO_R, 16)
    f_cr = fnt(F_REG, 22)
    draw.text((PAD, y+14), "AFFECTIVE STATE", font=f_al, fill=TEXT_DIM)
    draw.text((PAD, y+35), data["dec"], font=f_av, fill=GOLD)
    cb = draw.textbbox((0,0), data["credit"], font=f_cr)
    draw.text((CARD_W - PAD - (cb[2]-cb[0]), y+24), data["credit"], font=f_cr, fill=TEXT_DIM)
    y += footer_h

    # Bottom strip
    draw.rectangle([0, y, CARD_W, y+bottom_h], fill=(8,8,8))
    draw.rectangle([0, y, CARD_W, y+1], fill=BORDER)
    f_bot = fnt(F_MONO_R, 16)
    draw.text((PAD, y+18), "APEX DDI ENGINE  ·  LENS LEAGUE", font=f_bot, fill=MUTED)
    tier_map = {"APPRENTICE":1,"PRACTITIONER":2,"MASTER":3,"GRANDMASTER":4,"LEGEND":5}
    active = tier_map.get(data["tier"].upper(), 2)
    px = CARD_W//2 - 60
    py = y + 19
    for i in range(5):
        col = GOLD if i < active else MUTED
        draw.rectangle([px+i*24, py, px+i*24+14, py+14],
                       fill=col if i < active else None, outline=col, width=1)
    sc_txt = f"LL-SCORE  {data['score']}  ·  {data['tier'].upper()}"
    scb = draw.textbbox((0,0), sc_txt, font=f_bot)
    draw.text((CARD_W - PAD - (scb[2]-scb[0]), y+18), sc_txt, font=f_bot, fill=MUTED)

    canvas.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
