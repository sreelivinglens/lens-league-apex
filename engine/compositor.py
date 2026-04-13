"""
Apex Rating Card — v16
Exactly mirrors the share page dark design.
Canvas: 960px wide, dynamic height.
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

# ── Palette — matches share page exactly ─────────────────────────────────────
BG        = (13,  13,  11)
S1        = (20,  20,  18)
S2        = (28,  28,  26)
S3        = (36,  36,  34)
BORDER    = (42,  42,  40)
BORDER_MD = (56,  56,  54)
T1        = (240, 239, 232)
T2        = (184, 182, 174)
T3        = (122, 120, 112)
GOLD      = (200, 168, 75)
GOLD_D    = (139, 105, 20)
GOLD_BG   = (22,  19,  8)
GREEN     = (76,  175, 115)
RED       = (224, 85,  85)
AMBER     = (224, 153, 64)

CW  = 960
PAD = 32

def fh(font):
    d = ImageDraw.Draw(Image.new('RGB', (1,1)))
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

def mh(text, font, max_w, draw, sp=5):
    ls = wrap(text,font,max_w,draw)
    return len(ls)*fh(font)+max(0,len(ls)-1)*sp if ls else 0

def dw(draw, text, font, color, x, y, max_w, sp=5):
    for line in wrap(text,font,max_w,draw):
        draw.text((x,y),line,font=font,fill=color); y+=fh(font)+sp
    return y

def build_card(photo_path, data, out_path):

    # Fonts — sized to match share page readability at 960px
    fBrand   = fnt(F_MONO,   13)
    fEngine  = fnt(F_MONO_R, 11)
    fScore   = fnt(F_BOLD,   56)   # big score like share page
    fTier    = fnt(F_MONO,   13)
    fTitle   = fnt(F_BOLD,   20)
    fMeta    = fnt(F_REG,    13)
    fTag     = fnt(F_MONO_R, 11)
    fModLbl  = fnt(F_MONO_R, 11)
    fModVal  = fnt(F_BOLD,   24)
    fSecHdr  = fnt(F_MONO,   11)
    fSecBody = fnt(F_REG,    13)
    fByHdr   = fnt(F_MONO,   11)
    fByBody  = fnt(F_REG,    13)
    fByImp   = fnt(F_BOLD,   13)
    fBadge   = fnt(F_REG,    12)
    fBadgeH  = fnt(F_MONO,   10)
    fFooter  = fnt(F_MONO_R, 11)

    dummy = ImageDraw.Draw(Image.new('RGB',(CW,10)))

    # ── Layout constants ──────────────────────────────────────────────────────
    HEADER_H = 44
    PHOTO_W  = 380   # wider photo
    PHOTO_H  = 240
    PHOTO_X  = PAD
    PHOTO_Y  = HEADER_H + PAD

    # Score panel right of photo
    SP_X = PHOTO_X + PHOTO_W + 20
    SP_W = 130
    SP_H = PHOTO_H

    # Info right of score panel
    INFO_X = SP_X + SP_W + 20
    INFO_W = CW - INFO_X - PAD

    PHOTO_BLOCK_H = PHOTO_H + PAD*2

    # Module row
    MOD_H = PAD + fh(fModLbl) + 6 + fh(fModVal) + 10 + 5 + PAD

    # Two columns
    COL_GAP = 28
    COL_W   = (CW - PAD*2 - COL_GAP) // 2
    LC_X    = PAD
    RC_X    = PAD + COL_W + COL_GAP

    b1 = data.get('byline_1','').strip()
    b2 = data.get('byline_2_body','').strip()
    bg = [b for b in data.get('badges_g',[]) if b.strip()]
    bw = [b for b in data.get('badges_w',[]) if b.strip()]

    lh = sum(
        fh(fSecHdr)+4 + (mh(body,fSecBody,COL_W,dummy,5) if body.strip() else 0) + 14
        for _,body in data.get('rows',[])
    )
    rh  = fh(fByHdr)+4 + mh(b1,fByBody,COL_W,dummy,5) + 14
    rh += fh(fByHdr)+4 + mh(b2,fByImp,COL_W,dummy,5) + 16
    if bg: rh += fh(fBadgeH)+4 + mh(', '.join(bg),fBadge,COL_W,dummy,4) + 12
    if bw: rh += fh(fBadgeH)+4 + mh(', '.join(bw),fBadge,COL_W,dummy,4) + 12

    TWO_COL_H = max(lh, rh)
    FOOTER_H  = 40

    CH = HEADER_H + PHOTO_BLOCK_H + 1 + MOD_H + 1 + PAD + TWO_COL_H + PAD + FOOTER_H

    canvas = Image.new('RGB',(CW,CH),BG)
    draw   = ImageDraw.Draw(canvas)

    # ── GOLD HEADER STRIP ─────────────────────────────────────────────────────
    draw.rectangle([0,0,CW,HEADER_H], fill=GOLD)
    draw.text((PAD,13),'THE LENS LEAGUE', font=fBrand, fill=BG)
    et  = 'APEX DDI ENGINE  ·  FULL EVALUATION  ·  RATED BY SCIENCE'
    etw = draw.textbbox((0,0),et,font=fEngine)[2]
    draw.text((CW-PAD-etw, 16), et, font=fEngine, fill=(40,30,5))

    # ── PHOTO BLOCK ───────────────────────────────────────────────────────────
    draw.rectangle([0, HEADER_H, CW, HEADER_H+PHOTO_BLOCK_H], fill=S1)

    try:
        ph = Image.open(photo_path).convert('RGB')
        pw, phh = ph.size
        scale = max(PHOTO_W/pw, PHOTO_H/phh)
        nw, nh = int(pw*scale), int(phh*scale)
        ph = ph.resize((nw,nh), Image.LANCZOS)
        cx, cy = (nw-PHOTO_W)//2, (nh-PHOTO_H)//2
        ph = ph.crop((cx,cy,cx+PHOTO_W,cy+PHOTO_H))
        canvas.paste(ph, (PHOTO_X, PHOTO_Y))
        draw.rectangle([PHOTO_X-1, PHOTO_Y-1, PHOTO_X+PHOTO_W, PHOTO_Y+PHOTO_H],
                       outline=BORDER_MD, width=1)
    except:
        draw.rectangle([PHOTO_X, PHOTO_Y, PHOTO_X+PHOTO_W, PHOTO_Y+PHOTO_H], fill=S3)

    # Score panel — mirrors share page score badge
    draw.rectangle([SP_X, PHOTO_Y, SP_X+SP_W, PHOTO_Y+SP_H],
                   fill=GOLD_BG, outline=GOLD_D, width=2)

    sc  = str(data.get('score','0.0'))
    scw = draw.textbbox((0,0),sc,font=fScore)[2]
    draw.text((SP_X+(SP_W-scw)//2, PHOTO_Y+18), sc, font=fScore, fill=GOLD)

    tier = data.get('tier','').upper()
    tw   = draw.textbbox((0,0),tier,font=fTier)[2]
    draw.text((SP_X+(SP_W-tw)//2, PHOTO_Y+SP_H-fh(fTier)-28), tier, font=fTier, fill=GOLD)

    # Tier pips
    tier_map = {'APPRENTICE':1,'PRACTITIONER':2,'MASTER':3,'GRANDMASTER':4,'LEGEND':5}
    active = tier_map.get(tier,1)
    pip_w_total = 5*12 + 4*4
    pip_x0 = SP_X + (SP_W - pip_w_total)//2
    pip_y  = PHOTO_Y + SP_H - 14
    for i in range(5):
        px = pip_x0 + i*16
        draw.rectangle([px, pip_y, px+10, pip_y+5], fill=GOLD if i<active else BORDER_MD)

    # Image info
    IY = PHOTO_Y + 10
    draw.text((INFO_X, IY), data.get('asset','Untitled'), font=fTitle, fill=T1)
    IY += fh(fTitle)+4
    draw.text((INFO_X, IY), data.get('meta',''), font=fMeta, fill=T2)
    IY += fh(fMeta)+4
    draw.text((INFO_X, IY), data.get('genre_tag',''), font=fTag, fill=T3)
    IY += fh(fTag)+6
    if data.get('soul_bonus'):
        draw.text((INFO_X,IY), '★  SOUL BONUS  —  AQ ≥ 8.0', font=fTag, fill=GOLD)
        IY += fh(fTag)+4
    if data.get('iucn_tag'):
        draw.text((INFO_X,IY), data['iucn_tag'], font=fTag, fill=AMBER)
        IY += fh(fTag)+4
    IY += 4
    archline = f"Affective State: {data.get('dec','')}   ·   Photographer: {data.get('credit','')}"
    dw(draw, archline, fMeta, T3, INFO_X, IY, INFO_W, 3)

    # ── DIVIDER ───────────────────────────────────────────────────────────────
    D1 = HEADER_H + PHOTO_BLOCK_H
    draw.rectangle([0,D1,CW,D1+1], fill=BORDER_MD)

    # ── MODULE SCORES — mirrors share page module row ─────────────────────────
    draw.rectangle([0, D1+1, CW, D1+1+MOD_H], fill=S2)
    modules = data.get('modules',[])
    n  = max(len(modules),1)
    MW = (CW - PAD*2) // n
    max_sc = max((float(s) for _,s in modules if s), default=0)
    MY = D1 + 1 + PAD

    for i,(name,score) in enumerate(modules):
        mx   = PAD + i*MW
        top  = float(score) == max_sc
        col  = GOLD if top else T2
        if i > 0:
            draw.rectangle([mx-1, MY-4, mx, MY+fh(fModLbl)+fh(fModVal)+14], fill=BORDER)
        draw.text((mx+10, MY), name.upper(), font=fModLbl, fill=T3)
        draw.text((mx+10, MY+fh(fModLbl)+6), str(score), font=fModVal, fill=col)
        by = MY+fh(fModLbl)+6+fh(fModVal)+8
        bw2 = MW-24
        draw.rectangle([mx+10, by, mx+10+bw2, by+4], fill=S3)
        fw = int(bw2*float(score)/10)
        draw.rectangle([mx+10, by, mx+10+fw, by+4], fill=GOLD if top else GOLD_D)

    # ── DIVIDER 2 ─────────────────────────────────────────────────────────────
    D2 = D1 + 1 + MOD_H
    draw.rectangle([0,D2,CW,D2+1], fill=BORDER_MD)

    # Gold left accent bar (matches byline-section in share page)
    draw.rectangle([0, D2+1, 4, CH-FOOTER_H], fill=GOLD_D)

    # ── TWO COLUMNS ───────────────────────────────────────────────────────────
    CYL = D2+1+PAD
    CYR = D2+1+PAD

    # LEFT — analysis rows
    for label,body in data.get('rows',[]):
        lbl = label.replace('\\n',' ').replace('\n',' ').upper()
        draw.text((LC_X,CYL), lbl, font=fSecHdr, fill=GOLD)
        CYL += fh(fSecHdr)+4
        if body and body.strip():
            CYL = dw(draw, body, fSecBody, T2, LC_X, CYL, COL_W, 5)
        CYL += 14

    # RIGHT — byline
    draw.text((RC_X,CYR), 'APEX BYLINE', font=fByHdr, fill=GOLD)
    CYR += fh(fByHdr)+4
    if b1: CYR = dw(draw,b1,fByBody,T2,RC_X,CYR,COL_W,5)
    CYR += 14

    draw.text((RC_X,CYR), 'THE ONE IMPROVEMENT', font=fByHdr, fill=GOLD)
    CYR += fh(fByHdr)+4
    if b2: CYR = dw(draw,b2,fByImp,T1,RC_X,CYR,COL_W,5)
    CYR += 16

    if bg:
        draw.text((RC_X,CYR), 'STRENGTHS', font=fBadgeH, fill=GREEN)
        CYR += fh(fBadgeH)+4
        CYR = dw(draw,', '.join(bg),fBadge,GREEN,RC_X,CYR,COL_W,4)
        CYR += 12
    if bw:
        draw.text((RC_X,CYR), 'AREAS TO DEVELOP', font=fBadgeH, fill=RED)
        CYR += fh(fBadgeH)+4
        CYR = dw(draw,', '.join(bw),fBadge,RED,RC_X,CYR,COL_W,4)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    FY = CH-FOOTER_H
    draw.rectangle([0,FY,CW,CH], fill=S1)
    draw.rectangle([0,FY,CW,FY+1], fill=BORDER_MD)
    draw.text((PAD, FY+13), 'APEX DDI ENGINE  ·  RATED BY SCIENCE. NOT OPINION.  ·  LENS LEAGUE', font=fFooter, fill=T3)
    stamp = f"LL · {data.get('score','')} · {data.get('tier','').upper()}"
    sw = draw.textbbox((0,0),stamp,font=fFooter)[2]
    draw.text((CW-PAD-sw, FY+13), stamp, font=fFooter, fill=GOLD)

    canvas.save(out_path, 'JPEG', quality=96, optimize=True)
    return out_path
