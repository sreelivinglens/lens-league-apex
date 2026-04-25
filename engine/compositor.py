"""
Apex Rating Cards — v22
Two landscape cards at A4 300dpi (2480x1754px).
Card 1: Photo + Score + Modules  
Card 2: Full Analysis (2 columns)
"""

from PIL import Image as PilImage, ImageDraw, ImageFont
import os

FONT_DIR = os.path.dirname(os.path.abspath(__file__))

def fnt(size, bold=False, mono=False):
    if mono and bold:
        candidates = [
            os.path.join(FONT_DIR,'DejaVuSansMono-Bold.ttf'),
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
        ]
    elif mono:
        candidates = [
            os.path.join(FONT_DIR,'DejaVuSansMono.ttf'),
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        ]
    elif bold:
        candidates = [
            os.path.join(FONT_DIR,'LiberationSans-Bold.ttf'),
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]
    else:
        candidates = [
            os.path.join(FONT_DIR,'LiberationSans-Regular.ttf'),
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
    for p in candidates:
        if p and os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── Palette ───────────────────────────────────────────────────────────────────
BLACK  = (13,  13,  11)
S1     = (20,  20,  18)
S2     = (28,  28,  26)
S3     = (36,  36,  34)
BORDER = (56,  56,  54)
T1     = (240, 239, 232)
T2     = (184, 182, 174)
T3     = (122, 120, 112)
GOLD   = (200, 168,  75)
GOLD_D = (139, 105,  20)
GREEN  = (76,  175, 115)
RED    = (224,  85,  85)

CW, CH   = 2480, 1754   # A4 landscape 300dpi
PAD      = 80
HEADER_H = 100
FOOTER_H = 80

SITE_URL   = 'shutterleague.com'
LOGO_PATH  = os.path.join(FONT_DIR, 'shutterleague-logo-cropped.png')

def lh(font):
    d = ImageDraw.Draw(PilImage.new('RGB',(1,1)))
    bb = d.textbbox((0,0),'Ag',font=font)
    return bb[3]-bb[1]+6

def tw(draw, text, font):
    return draw.textbbox((0,0),text,font=font)[2]

def wrap_lines(draw, text, font, max_w):
    if not text or not text.strip(): return []
    words,lines,cur = text.split(),[],[]
    for w in words:
        test = ' '.join(cur+[w])
        if tw(draw,test,font) > max_w and cur:
            lines.append(' '.join(cur)); cur=[w]
        else: cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def draw_text(draw, text, font, color, x, y, max_w, sp=12):
    for line in wrap_lines(draw,text,font,max_w):
        draw.text((x,y),line,font=font,fill=color)
        y += lh(font)+sp
    return y

def draw_header(canvas, draw, left, right):
    draw.rectangle([0,0,CW,HEADER_H], fill=GOLD)
    # Try to paste logo on left of gold bar
    logo_placed = False
    try:
        from PIL import Image as _PL
        logo = _PL.open(LOGO_PATH).convert('RGBA')
        lh = HEADER_H - 12
        lw = int(logo.size[0] * lh / logo.size[1])
        logo = logo.resize((lw, lh), _PL.LANCZOS)
        canvas.paste(logo, (PAD, 6), logo)
        logo_placed = True
    except Exception:
        pass
    if not logo_placed:
        draw.text((PAD,28), left, font=fnt(36,bold=True,mono=True), fill=BLACK)
    rw = tw(draw,right,fnt(26,mono=True))
    draw.text((CW-PAD-rw,34), right, font=fnt(26,mono=True), fill=(40,30,5))

def draw_footer(canvas, draw, stamp):
    """Footer with Shutter League logo and branding."""
    draw.rectangle([0,CH-FOOTER_H,CW,CH], fill=S1)
    draw.rectangle([0,CH-FOOTER_H,CW,CH-FOOTER_H+1], fill=BORDER)
    # Try to paste logo
    logo_ok = False
    try:
        from PIL import Image as _PL
        logo = _PL.open(LOGO_PATH).convert('RGBA')
        lh = FOOTER_H - 16
        lw = int(logo.size[0] * lh / logo.size[1])
        logo = logo.resize((lw, lh), _PL.LANCZOS)
        canvas.paste(logo, (PAD, CH - FOOTER_H + 8), logo)
        draw.text((PAD + lw + 16, CH-FOOTER_H+26),
                  f'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  {SITE_URL}',
                  font=fnt(24,mono=True), fill=T3)
        logo_ok = True
    except Exception:
        pass
    if not logo_ok:
        draw.text((PAD, CH-FOOTER_H+26),
                  f'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  SHUTTER LEAGUE  ·  {SITE_URL}',
                  font=fnt(28,mono=True), fill=T3)
    sw = tw(draw, stamp, fnt(28,bold=True,mono=True))
    draw.text((CW-PAD-sw, CH-FOOTER_H+26), stamp, font=fnt(28,bold=True,mono=True), fill=GOLD)
def build_card1(photo_path, data, out_path):
    """Card 1 — Photo + Score + Modules (landscape brag card)"""
    canvas = PilImage.new('RGB',(CW,CH),BLACK)
    draw   = ImageDraw.Draw(canvas)

    INNER_H = CH - HEADER_H - FOOTER_H
    PHOTO_W = int(CW * 0.52)

    # Photo — left half
    try:
        ph = PilImage.open(photo_path).convert('RGB')
        pw,phh = ph.size
        scale = max(PHOTO_W/pw, INNER_H/phh)
        nw,nh = int(pw*scale),int(phh*scale)
        ph = ph.resize((nw,nh),PilImage.LANCZOS)
        cx,cy = (nw-PHOTO_W)//2,(nh-INNER_H)//2
        ph = ph.crop((cx,cy,cx+PHOTO_W,cy+INNER_H))
        canvas.paste(ph,(0,HEADER_H))

    except:
        draw.rectangle([0,HEADER_H,PHOTO_W,HEADER_H+INNER_H],fill=S3)

    # Right panel content
    RX = PHOTO_W + PAD
    RW = CW - RX - PAD
    RY = HEADER_H + PAD

    # Score
    score = str(data.get('score','—'))
    tier  = data.get('tier','').upper()
    draw.text((RX,RY), score, font=fnt(260,bold=True), fill=GOLD)
    # Logo — right panel, top right, vertically centred with score number
    try:
        from PIL import Image as _PL2
        lg = _PL2.open(LOGO_PATH).convert('RGBA')
        lg_h = 220
        lg_w = int(lg.size[0] * lg_h / lg.size[1])
        lg = lg.resize((lg_w, lg_h), _PL2.LANCZOS)
        score_block_h = 280
        lg_x = CW - PAD - lg_w
        lg_y = HEADER_H + PAD + (score_block_h - lg_h) // 2
        canvas.paste(lg, (lg_x, lg_y), lg)
    except Exception:
        pass
    RY += lh(fnt(260,bold=True)) + 10
    draw.text((RX,RY), tier, font=fnt(72,bold=True,mono=True), fill=GOLD)
    RY += lh(fnt(72,bold=True,mono=True)) + 16

    # Tier pips
    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active = tier_map.get(tier,1)
    for i in range(5):
        px = RX+i*44
        draw.rectangle([px,RY,px+32,RY+18], fill=GOLD if i<active else (56,56,54))
    RY += 44

    # Divider
    draw.rectangle([RX,RY,CW-PAD,RY+2], fill=GOLD_D)
    RY += 20

    # Title + meta
    RY = draw_text(draw, data.get('asset','Untitled'), fnt(64,bold=True), T1, RX, RY, RW, 8)
    RY = draw_text(draw, data.get('meta',''), fnt(40), T2, RX, RY, RW, 6)
    RY += 10
    arch = f"Affective State: {data.get('dec','')}  ·  {data.get('credit','')}"
    RY = draw_text(draw, arch, fnt(36,mono=True), T3, RX, RY, RW, 6)

    if data.get('soul_bonus'):
        RY += 14
        draw_text(draw,'★  SOUL BONUS ACTIVE  —  AQ ≥ 8.0',fnt(36,mono=True),GOLD,RX,RY,RW)

    # Module scores — pinned to bottom
    modules = data.get('modules',[])
    n = max(len(modules),1)
    MOD_BLOCK_H = PAD + lh(fnt(36,mono=True)) + 10 + lh(fnt(80,bold=True)) + 18 + 10 + PAD
    MOD_Y = CH - FOOTER_H - MOD_BLOCK_H

    draw.rectangle([PHOTO_W,MOD_Y,CW,CH-FOOTER_H], fill=S2)
    draw.rectangle([PHOTO_W,MOD_Y,CW,MOD_Y+1], fill=BORDER)

    MW = (CW - PHOTO_W - PAD*2) // n
    max_sc = max((float(s) for _,s in modules if s), default=0)
    LBL_Y = MOD_Y + PAD

    for i,(name,mscore) in enumerate(modules):
        mx = PHOTO_W + PAD + i*MW
        top = float(mscore)==max_sc
        col = GOLD if top else T2
        if i>0:
            draw.rectangle([mx-1,MOD_Y+10,mx,CH-FOOTER_H-10],fill=BORDER)
        draw.text((mx+12,LBL_Y), name.upper(), font=fnt(36,mono=True), fill=T3)
        draw.text((mx+12,LBL_Y+lh(fnt(36,mono=True))+10), str(mscore), font=fnt(80,bold=True), fill=col)
        by = LBL_Y+lh(fnt(36,mono=True))+10+lh(fnt(80,bold=True))+12
        bw2 = MW-28
        draw.rectangle([mx+12,by,mx+12+bw2,by+10],fill=S3)
        fw = int(bw2*float(mscore)/10)
        if fw>0:
            draw.rectangle([mx+12,by,mx+12+fw,by+10],fill=GOLD if top else GOLD_D)

    draw_header(canvas, draw, 'SHUTTER LEAGUE', 'APEX DDI ENGINE  ·  FULL EVALUATION')
    draw_footer(canvas, draw, f"SL · {score} · {tier}")
    canvas.save(out_path,'JPEG',quality=96)
    return out_path


def build_card2(data, out_path):
    """Card 2 — Full Analysis, 2 columns, DYNAMIC height based on content."""

    COL_GAP = 80
    COL_W   = (CW - PAD*2 - COL_GAP)//2
    LX      = PAD
    RX      = PAD + COL_W + COL_GAP

    rows = data.get('rows',[])
    b1   = data.get('byline_1','').strip()
    b2   = data.get('byline_2_body','').strip()
    bg   = [b for b in data.get('badges_g',[]) if b.strip()]
    bw   = [b for b in data.get('badges_w',[]) if b.strip()]

    def measure_section(dummy_draw, body, w):
        h  = lh(fnt(38,bold=True,mono=True)) + 20
        h += sum(lh(fnt(44))+12 for _ in wrap_lines(dummy_draw,body,fnt(44),w))
        h += 28 + 1
        return h

    dummy = ImageDraw.Draw(PilImage.new('RGB',(CW,100),BLACK))

    left_h = sum(measure_section(dummy,body,COL_W) for _,body in rows[:3])
    left_h += 10
    if bg:
        left_h += lh(fnt(38,bold=True,mono=True))+20
        left_h += sum(lh(fnt(44))+10 for _ in wrap_lines(dummy,', '.join(bg),fnt(44),COL_W))
        left_h += 24
    if bw:
        left_h += lh(fnt(38,bold=True,mono=True))+20
        left_h += sum(lh(fnt(44))+10 for _ in wrap_lines(dummy,', '.join(bw),fnt(44),COL_W))

    right_h = sum(measure_section(dummy,body,COL_W) for _,body in rows[3:])
    right_h += lh(fnt(38,bold=True,mono=True))+20
    right_h += sum(lh(fnt(44))+12 for _ in wrap_lines(dummy,b1,fnt(44),COL_W))
    right_h += 28
    right_h += lh(fnt(38,bold=True,mono=True))+20
    right_h += sum(lh(fnt(44,bold=True))+12 for _ in wrap_lines(dummy,b2,fnt(44,bold=True),COL_W))

    content_h = max(left_h, right_h)
    DYN_H = HEADER_H + PAD + content_h + PAD*4 + FOOTER_H

    canvas = PilImage.new('RGB',(CW, DYN_H), BLACK)
    draw   = ImageDraw.Draw(canvas)

    INNER_Y = HEADER_H + PAD
    LY = INNER_Y
    RY = INNER_Y

    def section(x, y, label, body, w, body_color=T2):
        draw.text((x,y), label.upper(), font=fnt(38,bold=True,mono=True), fill=GOLD)
        y += lh(fnt(38,bold=True,mono=True)) + 20
        y = draw_text(draw, body, fnt(44), body_color, x, y, w, 12)
        y += 28
        draw.rectangle([x, y-14, x+w, y-13], fill=(42,42,40))
        return y

    for label,body in rows[:3]:
        LY = section(LX, LY, label, body, COL_W)

    LY += 10
    if bg:
        draw.text((LX,LY), 'STRENGTHS', font=fnt(38,bold=True,mono=True), fill=GREEN)
        LY += lh(fnt(38,bold=True,mono=True)) + 20
        LY = draw_text(draw, ', '.join(bg), fnt(44), GREEN, LX, LY, COL_W, 10)
        LY += 24
    if bw:
        draw.text((LX,LY), 'AREAS TO DEVELOP', font=fnt(38,bold=True,mono=True), fill=RED)
        LY += lh(fnt(38,bold=True,mono=True)) + 20
        LY = draw_text(draw, ', '.join(bw), fnt(44), RED, LX, LY, COL_W, 10)

    for label,body in rows[3:]:
        RY = section(RX, RY, label, body, COL_W)

    byline_top = RY
    draw.text((RX,RY), 'APEX BYLINE', font=fnt(38,bold=True,mono=True), fill=GOLD)
    RY += lh(fnt(38,bold=True,mono=True)) + 20
    RY = draw_text(draw, b1, fnt(44), T2, RX, RY, COL_W, 12)
    RY += 28
    draw.text((RX,RY), 'THE ONE IMPROVEMENT', font=fnt(38,bold=True,mono=True), fill=GOLD)
    RY += lh(fnt(38,bold=True,mono=True)) + 20
    RY = draw_text(draw, b2, fnt(44,bold=True), T1, RX, RY, COL_W, 12)

    draw.rectangle([RX-24, byline_top, RX-16, RY+20], fill=GOLD_D)

    # Footer with URL — redrawn at actual dynamic canvas bottom
    actual_h = DYN_H
    draw.rectangle([0,actual_h-FOOTER_H,CW,actual_h], fill=S1)
    draw.rectangle([0,actual_h-FOOTER_H,CW,actual_h-FOOTER_H+1], fill=BORDER)
    draw.text((PAD, actual_h-FOOTER_H+24),
              f'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  SHUTTER LEAGUE  ·  {SITE_URL}',
              font=fnt(28,mono=True), fill=T3)
    stamp = f"SL · {data.get('score','')} · {data.get('tier','').upper()}"
    sw = tw(draw, stamp, fnt(28,bold=True,mono=True))
    draw.text((CW-PAD-sw, actual_h-FOOTER_H+24), stamp, font=fnt(28,bold=True,mono=True), fill=GOLD)

    draw_header(canvas, draw,
                f"FULL EVALUATION  ·  {data.get('asset','')}",
                'APEX DDI ENGINE  ·  RATED BY SCIENCE')
    canvas.save(out_path,'JPEG',quality=96)
    return out_path


def build_card(photo_path, data, out_path):
    """
    Legacy entry point — builds both cards and saves as:
      out_path         = card 1 (score card)
      out_path_card2   = card 2 (analysis card)
    Returns (card1_path, card2_path)
    """
    card2_path = out_path.replace('.jpg','_analysis.jpg').replace('.jpeg','_analysis.jpg')
    build_card1(photo_path, data, out_path)
    build_card2(data, card2_path)
    return out_path, card2_path
