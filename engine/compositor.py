"""
Apex Audit Card — v14
Canvas: 960px wide, dynamic height
Font: Liberation Sans (Arial-equivalent, bundled in engine/)
All body text: 11pt | Score: 14pt
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
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]:
        if os.path.exists(fb):
            try: return ImageFont.truetype(fb, size)
            except: pass
    return ImageFont.load_default()

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = (255, 255, 255)
BLACK    = (20,  20,  20)
GREY     = (80,  80,  80)
LGREY    = (210, 210, 210)
GOLD     = (160, 120, 20)
GOLD_BG  = (255, 250, 225)
GREEN    = (30,  120, 40)
RED      = (180, 30,  30)
STRIP_BG = (28,  28,  28)

CW         = 960
TH_W, TH_H = 200, 134
PAD        = 24


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


def measure_h(text, font, max_w, draw, sp=4):
    lines = wrap(text, font, max_w, draw)
    return len(lines) * fh(font) + max(0, len(lines)-1) * sp if lines else 0


def draw_wrapped(draw, text, font, color, x, y, max_w, sp=4):
    for line in wrap(text, font, max_w, draw):
        draw.text((x, y), line, font=font, fill=color)
        y += fh(font) + sp
    return y


def build_card(photo_path, data, out_path):

    # ── All fonts at 11pt (Liberation Sans = Arial) except score (14pt) ───────
    PT        = 11   # base size for everything
    SC_PT     = 14   # score number only

    f_strip    = fnt(F_BOLD,   PT)       # top/bottom strip
    f_score    = fnt(F_BOLD,   SC_PT)    # score number
    f_tier     = fnt(F_MONO_R, PT-1)     # MASTER / PRACTITIONER
    f_asset    = fnt(F_BOLD,   PT+1)     # image title (12pt — slightly larger)
    f_meta     = fnt(F_REG,    PT)       # meta line
    f_tag      = fnt(F_MONO_R, PT-1)     # genre tag / soul bonus
    f_mod_lbl  = fnt(F_MONO_R, PT-1)     # DOD / DISRUPTION labels
    f_mod_val  = fnt(F_BOLD,   PT+3)     # module score values (14pt)
    f_sec_hdr  = fnt(F_MONO,   PT-1)     # section headers
    f_sec_body = fnt(F_REG,    PT)       # section body
    f_byline_h = fnt(F_MONO,   PT-1)     # APEX BYLINE / THE ONE IMPROVEMENT
    f_byline_b = fnt(F_REG,    PT)       # byline body
    f_byline_i = fnt(F_BOLD,   PT)       # improvement text
    f_str_hdr  = fnt(F_MONO,   PT-1)     # STRENGTHS / GAPS headers
    f_str_body = fnt(F_REG,    PT)       # strengths / gaps text

    dummy = ImageDraw.Draw(Image.new("RGB", (CW, 10)))

    COL_GAP = 24
    COL_W   = (CW - PAD*2 - COL_GAP) // 2
    LC_X    = PAD
    RC_X    = PAD + COL_W + COL_GAP

    STRIP_H     = 26
    TH_Y        = STRIP_H + PAD
    photo_row_h = TH_H + 16
    mod_row_h   = fh(f_mod_lbl) + fh(f_mod_val) + 12

    # measure left column
    left_h = 0
    for _, body in data.get("rows", []):
        left_h += fh(f_sec_hdr) + 3
        left_h += measure_h(body, f_sec_body, COL_W, dummy) if body.strip() else 0
        left_h += 10

    # measure right column
    b1 = data.get("byline_1", "").strip()
    b2 = data.get("byline_2_body", "").strip()
    badges_g = [b for b in data.get("badges_g", []) if b.strip()]
    badges_w = [b for b in data.get("badges_w", []) if b.strip()]

    right_h  = fh(f_byline_h) + 3
    right_h += measure_h(b1, f_byline_b, COL_W, dummy)
    right_h += 10
    right_h += fh(f_byline_h) + 3
    right_h += measure_h(b2, f_byline_i, COL_W, dummy)
    right_h += 12
    if badges_g:
        right_h += fh(f_str_hdr) + 3
        right_h += measure_h(', '.join(badges_g), f_str_body, COL_W, dummy)
        right_h += 10
    if badges_w:
        right_h += fh(f_str_hdr) + 3
        right_h += measure_h(', '.join(badges_w), f_str_body, COL_W, dummy)
        right_h += 10

    two_col_h = max(left_h, right_h)
    BOT_H     = 26

    CH = (STRIP_H + PAD + photo_row_h +
          2 + 10 + mod_row_h +
          2 + 10 + two_col_h +
          16 + BOT_H)

    canvas = Image.new("RGB", (CW, CH), BG)
    draw   = ImageDraw.Draw(canvas)

    # ── Top strip ─────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, CW, STRIP_H], fill=STRIP_BG)
    draw.text((PAD, 7), "THE LENS LEAGUE", font=f_strip, fill=(200, 168, 75))
    et  = "APEX DDI ENGINE  ·  FULL EVALUATION"
    etb = draw.textbbox((0, 0), et, font=f_strip)
    draw.text((CW-PAD-(etb[2]-etb[0]), 7), et, font=f_strip, fill=(150,120,50))

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    TH_X = PAD
    photo = Image.open(photo_path).convert("RGB")
    pw, ph = photo.size
    scale  = max(TH_W/pw, TH_H/ph)
    nw, nh = int(pw*scale), int(ph*scale)
    photo  = photo.resize((nw, nh), Image.LANCZOS)
    cx, cy = (nw-TH_W)//2, (nh-TH_H)//2
    photo  = photo.crop((cx, cy, cx+TH_W, cy+TH_H))
    canvas.paste(photo, (TH_X, TH_Y))
    draw.rectangle([TH_X-1, TH_Y-1, TH_X+TH_W, TH_Y+TH_H], outline=LGREY, width=1)

    # ── Score badge ───────────────────────────────────────────────────────────
    BX, BY = TH_X + TH_W + 14, TH_Y
    BW, BH = 80, TH_H
    draw.rectangle([BX, BY, BX+BW, BY+BH], fill=GOLD_BG, outline=GOLD, width=1)
    sc  = str(data.get("score", "0.0"))
    sb  = draw.textbbox((0, 0), sc, font=f_score)
    draw.text((BX+(BW-(sb[2]-sb[0]))//2, BY+18), sc, font=f_score, fill=GOLD)
    tier_t = data.get("tier", "").upper()
    tierb  = draw.textbbox((0, 0), tier_t, font=f_tier)
    draw.text((BX+(BW-(tierb[2]-tierb[0]))//2, BY+80), tier_t, font=f_tier, fill=GOLD)

    # ── Info ──────────────────────────────────────────────────────────────────
    IX = BX + BW + 14
    IY = TH_Y + 6
    IW = CW - IX - PAD

    draw.text((IX, IY), data.get("asset",""), font=f_asset, fill=BLACK)
    IY += fh(f_asset) + 2
    draw.text((IX, IY), data.get("meta",""),  font=f_meta,  fill=GREY)
    IY += fh(f_meta) + 2
    draw.text((IX, IY), data.get("genre_tag",""), font=f_tag, fill=GREY)
    IY += fh(f_tag) + 3
    if data.get("soul_bonus"):
        draw.text((IX, IY), "★  SOUL BONUS ACTIVE", font=f_tag, fill=GOLD)
        IY += fh(f_tag) + 2
    if data.get("iucn_tag"):
        draw.text((IX, IY), data["iucn_tag"], font=f_tag, fill=RED)
        IY += fh(f_tag) + 2
    combined = (f"Affective State:  {data.get('dec','')}"
                f"   ·   Photographer:  {data.get('credit','')}")
    draw_wrapped(draw, combined, f_meta, BLACK, IX, IY, IW, 3)

    # ── Divider 1 ─────────────────────────────────────────────────────────────
    D1Y = TH_Y + TH_H + 12
    draw.rectangle([PAD, D1Y, CW-PAD, D1Y+1], fill=LGREY)

    # ── Module scores ─────────────────────────────────────────────────────────
    MY      = D1Y + 8
    modules = data.get("modules", [])
    n       = max(len(modules), 1)
    MW      = (CW - PAD*2) // n
    max_sc  = max((float(s) for _,s in modules), default=0)

    for i, (name, score) in enumerate(modules):
        mx  = PAD + i*MW
        col = GOLD if float(score)==max_sc else BLACK
        draw.text((mx, MY), name.upper(), font=f_mod_lbl, fill=GREY)
        draw.text((mx, MY+fh(f_mod_lbl)+1), str(score), font=f_mod_val, fill=col)
        bx  = mx
        by  = MY + fh(f_mod_lbl) + fh(f_mod_val) + 3
        bw  = MW - 14
        draw.rectangle([bx, by, bx+bw, by+3], fill=LGREY)
        fw  = int(bw * float(score)/10)
        draw.rectangle([bx, by, bx+fw, by+3],
                       fill=GOLD if float(score)==max_sc else (160,130,50))
        if i > 0:
            draw.rectangle([mx-1, MY, mx, by+3], fill=LGREY)

    # ── Divider 2 ─────────────────────────────────────────────────────────────
    D2Y = MY + fh(f_mod_lbl) + fh(f_mod_val) + 10
    draw.rectangle([PAD, D2Y, CW-PAD, D2Y+1], fill=LGREY)

    # ── Two columns ───────────────────────────────────────────────────────────
    CY_L = D2Y + 10
    CY_R = D2Y + 10

    # LEFT — five sections
    for label, body in data.get("rows", []):
        lbl = label.replace("\\n"," ").replace("\n"," ")
        draw.text((LC_X, CY_L), lbl.upper(), font=f_sec_hdr, fill=GOLD)
        CY_L += fh(f_sec_hdr) + 3
        if body and body.strip():
            CY_L = draw_wrapped(draw, body, f_sec_body, BLACK, LC_X, CY_L, COL_W)
        CY_L += 10

    # RIGHT — byline
    draw.text((RC_X, CY_R), "APEX BYLINE", font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 3
    if b1:
        CY_R = draw_wrapped(draw, b1, f_byline_b, BLACK, RC_X, CY_R, COL_W)
    CY_R += 10

    draw.text((RC_X, CY_R), "THE ONE IMPROVEMENT:", font=f_byline_h, fill=GOLD)
    CY_R += fh(f_byline_h) + 3
    if b2:
        CY_R = draw_wrapped(draw, b2, f_byline_i, BLACK, RC_X, CY_R, COL_W)
    CY_R += 12

    if badges_g:
        draw.text((RC_X, CY_R), "STRENGTHS:", font=f_str_hdr, fill=GREEN)
        CY_R += fh(f_str_hdr) + 3
        CY_R = draw_wrapped(draw, ', '.join(badges_g), f_str_body, GREEN, RC_X, CY_R, COL_W)
        CY_R += 10

    if badges_w:
        draw.text((RC_X, CY_R), "GAPS:", font=f_str_hdr, fill=RED)
        CY_R += fh(f_str_hdr) + 3
        CY_R = draw_wrapped(draw, ', '.join(badges_w), f_str_body, RED, RC_X, CY_R, COL_W)

    # ── Bottom strip ──────────────────────────────────────────────────────────
    BOT_Y = CH - BOT_H
    draw.rectangle([0, BOT_Y, CW, CH], fill=STRIP_BG)
    tier_map = {"APPRENTICE":1,"PRACTITIONER":2,"MASTER":3,"GRANDMASTER":4,"LEGEND":5}
    active   = tier_map.get(data.get("tier","").upper(), 2)
    pip_x, pip_y = CW//2-36, BOT_Y+8
    for i in range(5):
        col = (200,168,75) if i<active else (70,70,70)
        draw.rectangle([pip_x+i*16, pip_y, pip_x+i*16+10, pip_y+8],
                       fill=col if i<active else None, outline=col, width=1)
    sc_txt = f"LL  {data.get('score','')}  ·  {data.get('tier','').upper()}"
    scb    = draw.textbbox((0,0), sc_txt, font=f_strip)
    draw.text((CW-PAD-(scb[2]-scb[0]), BOT_Y+7), sc_txt, font=f_strip, fill=(150,120,50))
    draw.text((PAD, BOT_Y+7), "APEX DDI ENGINE", font=f_strip, fill=(100,90,70))

    canvas.save(out_path, "JPEG", quality=95, optimize=True)
    return out_path
