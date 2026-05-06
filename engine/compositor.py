"""
Apex Rating Cards — v23
Two landscape cards at A4 300dpi (2480x1754px).
Card 1: Photo + Score + Modules  
Card 2: Full Analysis (2 columns)
Site palette: cream bg, slate blue accents, dark text, gold for highlights only.
No shield badge. No bars under module scores.
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

# ── Site Palette ──────────────────────────────────────────────────────────────
CREAM   = (253, 252, 248)   # site bg #FDFCF8
SURFACE = (241, 239, 232)   # surface-3 #F1EFE8
BORDER  = (210, 208, 200)   # border #D3D1C7
SLATE   = ( 44,  62, 107)   # #2C3E6B — slate blue
T1      = ( 26,  26,  24)   # dark text #1A1A18
T2      = ( 74,  72,  64)   # muted text #4A4840
T3      = (136, 135, 128)   # hint text #888780
GOLD    = (200, 168,  75)   # gold accent — scores/highlights only
GOLD_D  = (139, 105,  20)   # dark gold
GREEN   = ( 59, 109,  17)   # #3B6D11
RED     = (160,  45,  45)   # #A02D2D
WHITE   = (255, 255, 255)

CW, CH   = 2480, 1754
PAD      = 80
HEADER_H = 100
FOOTER_H = 80

SITE_URL   = 'shutterleague.com'
LOGO_PATH  = os.path.join(FONT_DIR, 'shutterleague-logo-cropped.png')
_LOGO_FALLBACKS = [
    LOGO_PATH,
    os.path.join(os.path.dirname(FONT_DIR), 'engine', 'shutterleague-logo-cropped.png'),
    os.path.join(os.path.dirname(FONT_DIR), 'static', 'img', 'shutterleague-logo-cropped.png'),
    '/app/engine/shutterleague-logo-cropped.png',
]

def _load_logo(h):
    for p in _LOGO_FALLBACKS:
        if p and os.path.exists(p):
            try:
                lg = PilImage.open(p).convert('RGBA')
                w = int(lg.size[0] * h / lg.size[1])
                return lg.resize((w, h), PilImage.LANCZOS), w
            except: continue
    return None, 0

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
    draw.rectangle([0,0,CW,HEADER_H], fill=SLATE)
    draw.text((PAD,28), left, font=fnt(36,bold=True,mono=True), fill=WHITE)
    rw = tw(draw,right,fnt(26,mono=True))
    draw.text((CW-PAD-rw,34), right, font=fnt(26,mono=True), fill=(180,190,210))

def draw_footer(canvas, draw, stamp, canvas_h=None):
    h = canvas_h or CH
    draw.rectangle([0,h-FOOTER_H,CW,h], fill=SLATE)
    draw.rectangle([0,h-FOOTER_H,CW,h-FOOTER_H+1], fill=(60,75,115))
    ftr_logo, flw = _load_logo(FOOTER_H - 16)
    if ftr_logo:
        canvas.paste(ftr_logo, (PAD, h - FOOTER_H + 8), ftr_logo.split()[3])
        draw.text((PAD + flw + 16, h-FOOTER_H+26),
                  f'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  {SITE_URL}',
                  font=fnt(24,mono=True), fill=(160,175,200))
    else:
        draw.text((PAD, h-FOOTER_H+26),
                  f'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  SHUTTER LEAGUE  ·  {SITE_URL}',
                  font=fnt(28,mono=True), fill=(160,175,200))
    sw = tw(draw, stamp, fnt(28,bold=True,mono=True))
    draw.text((CW-PAD-sw, h-FOOTER_H+26), stamp, font=fnt(28,bold=True,mono=True), fill=GOLD)


def build_card1(photo_path, data, out_path):
    """Card 1 — Photo + Score + Modules (landscape brag card)"""
    canvas = PilImage.new('RGB',(CW,CH),CREAM)
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
        draw.rectangle([0,HEADER_H,PHOTO_W,HEADER_H+INNER_H],fill=BORDER)

    # Right panel — cream background
    RX = PHOTO_W + PAD
    RW = CW - RX - PAD
    RY = HEADER_H + PAD

    # Score number — dark text
    score = str(data.get('score','—'))
    tier  = data.get('tier','').upper()
    draw.text((RX,RY), score, font=fnt(260,bold=True), fill=T1)
    RY += lh(fnt(260,bold=True)) + 10

    # Tier — slate blue
    draw.text((RX,RY), tier, font=fnt(72,bold=True,mono=True), fill=SLATE)
    RY += lh(fnt(72,bold=True,mono=True)) + 16

    # Tier pips — gold for active, border for inactive
    tier_map = {
        'ROOKIE':1, 'SHOOTER':1,
        'CONTENDER':2, 'CRAFTSMAN':2,
        'MAVERICK':3, 'MASTER':3,
        'GRANDMASTER':4, 'LEGEND':5,
    }
    active = tier_map.get(tier,1)
    for i in range(5):
        px = RX+i*44
        draw.rectangle([px,RY,px+32,RY+18], fill=GOLD if i<active else BORDER)
    RY += 44

    # Divider
    draw.rectangle([RX,RY,CW-PAD,RY+2], fill=BORDER)
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

    # Module scores — pinned to bottom, slate blue panel
    modules = data.get('modules',[])
    n = max(len(modules),1)
    MOD_BLOCK_H = PAD + lh(fnt(36,mono=True)) + 10 + lh(fnt(80,bold=True)) + PAD
    MOD_Y = CH - FOOTER_H - MOD_BLOCK_H

    draw.rectangle([PHOTO_W,MOD_Y,CW,CH-FOOTER_H], fill=SURFACE)
    draw.rectangle([PHOTO_W,MOD_Y,CW,MOD_Y+1], fill=BORDER)

    MW = (CW - PHOTO_W - PAD*2) // n
    max_sc = max((float(s) for _,s in modules if s), default=0)
    LBL_Y = MOD_Y + PAD

    for i,(name,mscore) in enumerate(modules):
        mx = PHOTO_W + PAD + i*MW
        top = float(mscore)==max_sc
        col = GOLD if top else T1  # gold for top, dark text for rest
        if i>0:
            draw.rectangle([mx-1,MOD_Y+10,mx,CH-FOOTER_H-10],fill=BORDER)
        draw.text((mx+12,LBL_Y), name.upper(), font=fnt(36,mono=True), fill=T3)
        draw.text((mx+12,LBL_Y+lh(fnt(36,mono=True))+10), str(mscore), font=fnt(80,bold=True), fill=col)

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

    dummy = ImageDraw.Draw(PilImage.new('RGB',(CW,100),CREAM))

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

    canvas = PilImage.new('RGB',(CW, DYN_H), CREAM)
    draw   = ImageDraw.Draw(canvas)

    INNER_Y = HEADER_H + PAD
    LY = INNER_Y
    RY = INNER_Y

    def section(x, y, label, body, w, body_color=T2):
        draw.text((x,y), label.upper(), font=fnt(38,bold=True,mono=True), fill=SLATE)
        y += lh(fnt(38,bold=True,mono=True)) + 20
        y = draw_text(draw, body, fnt(44), body_color, x, y, w, 12)
        y += 28
        draw.rectangle([x, y-14, x+w, y-13], fill=BORDER)
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

    # The One Improvement section — slate blue panel
    byline_top = RY
    # Apex Byline (gap analysis) — label + body
    draw.text((RX,RY), 'GAP ANALYSIS', font=fnt(38,bold=True,mono=True), fill=SLATE)
    RY += lh(fnt(38,bold=True,mono=True)) + 20
    RY = draw_text(draw, b1, fnt(44), T2, RX, RY, COL_W, 12)
    RY += 28

    # The One Improvement — slate blue box
    IMPROVE_PAD = 24
    improve_lines = wrap_lines(draw, b2, fnt(44,bold=True), COL_W - IMPROVE_PAD*2)
    improve_h = lh(fnt(38,bold=True,mono=True)) + 20 + sum(lh(fnt(44,bold=True))+12 for _ in improve_lines) + IMPROVE_PAD*2
    draw.rectangle([RX-8, RY, RX+COL_W+8, RY+improve_h], fill=SLATE)
    iy = RY + IMPROVE_PAD
    draw.text((RX+IMPROVE_PAD, iy), 'THE ONE IMPROVEMENT', font=fnt(38,bold=True,mono=True), fill=(180,190,210))
    iy += lh(fnt(38,bold=True,mono=True)) + 20
    draw_text(draw, b2, fnt(44,bold=True), WHITE, RX+IMPROVE_PAD, iy, COL_W-IMPROVE_PAD*2, 12)
    RY += improve_h + 20

    # Left border accent
    draw.rectangle([RX-24, byline_top, RX-16, RY], fill=GOLD_D)

    draw_footer(canvas, draw, f"SL · {data.get('score','')} · {data.get('tier','').upper()}", DYN_H)
    draw_header(canvas, draw,
                f"FULL EVALUATION  ·  {data.get('asset','')}",
                'APEX DDI ENGINE  ·  RATED BY SCIENCE')
    canvas.save(out_path,'JPEG',quality=96)
    return out_path


def build_card(photo_path, data, out_path):
    card2_path = out_path.replace('.jpg','_analysis.jpg').replace('.jpeg','_analysis.jpg')
    build_card1(photo_path, data, out_path)
    build_card2(data, card2_path)
    return out_path, card2_path
